"""
Nhập BÁO CÁO LẬP HÓA ĐƠN (Invoice Summary CSV của Meta) → Google Sheet.

Khác fb_billing_import.py / fb_billing_pdf_import.py ở chỗ:
  • Nguồn là file CSV "..._Invoice_Summary.csv" (Meta xuất), chọn hàng loạt từ máy.
  • Ghi vào tab TỔNG HỢP của tài khoản với 7 cột giống bản "Danh sách" của extension:
        ID giao dịch | Ngày thanh toán | Số tiền | Phương thức TT |
        Số tham chiếu thẻ | Trạng thái | ID hóa đơn VAT
    (cột nào không có dữ liệu để trống).
  • Tên tab được suy ra bằng cách tra "ID tài khoản" trong CSV vào sheet "TKQC API"
    để lấy "Tên Tài Khoản", rồi ghép:  "<Tên Tài Khoản> (<ID>)".
  • Dedup theo "ID giao dịch": import lại thay dòng trùng, không nhân đôi.

Chạy: python fb_invoice_summary_import.py
"""

import csv
import re
import sys
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    sys.exit("Cần tkinter (có sẵn trong Python chuẩn trên Windows).")

# Tái dùng backend Google Sheet của fb_billing_import
from fb_billing_import import connect_spreadsheet, _normalize, ID_COL

BASE_DIR = Path(__file__).parent

AD_ACCOUNTS_SHEET = "TKQC API"

# 7 cột — TRÙNG KHỚP _buildListSheet trong fb_billing_scraper/popup.js
SUMMARY_HEADERS = [
    "ID giao dịch", "Ngày thanh toán", "Số tiền", "Phương thức TT",
    "Số tham chiếu thẻ", "Trạng thái", "ID hóa đơn VAT",
]
# Cột giữ định dạng TEXT để không mất số 0 đầu / không bị Sheets ép thành số
TEXT_COLS = ["ID giao dịch", "Số tham chiếu thẻ", "ID hóa đơn VAT"]


# ── Đọc & bóc tách CSV ──────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split())


def _digits(s: str) -> str:
    return re.sub(r"[^\d]", "", s or "")


def _col_index(header: list, *needles, default=None):
    """Vị trí cột đầu tiên có tiêu đề chứa 1 trong các từ khóa (bỏ qua hoa/thường)."""
    low = [_norm(h).lower() for h in header]
    for i, h in enumerate(low):
        if any(n in h for n in needles):
            return i
    return default


def parse_invoice_csv(path: Path) -> tuple[dict, list[dict]]:
    """Bóc 1 file Invoice Summary → (meta, rows) — mỗi giao dịch 1 dòng (7 cột).

    Meta xuất 2 kiểu bố cục cột: bản 4 cột (Ngày,ID giao dịch,Số tiền,Tiền tệ) và
    bản 5 cột có thêm 'Phương thức thanh toán' chèn giữa. Vì thế PHẢI dò cột theo
    TÊN tiêu đề, không đọc cứng index — nếu không sẽ nhầm cột thẻ thành số tiền.
    """
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = raw.splitlines()

    macc = re.search(r"Tài kho[ảa]n:?\s*(\d{6,})", raw)
    account_id = macc.group(1) if macc else ""

    # Dòng "Phương thức thanh toán:" ở đầu file (bản 4 cột) — BẮT BUỘC có dấu ':'
    # để không khớp nhầm vào cột cùng tên trong dòng tiêu đề của bản 5 cột.
    mpm = re.search(r"Phương thức thanh toán:\s*(.+)", raw)
    file_pm = _norm(mpm.group(1)) if mpm else ""

    # Dòng tiêu đề bảng: có "ID giao" (vd "Ngày,ID giao dịch,Số tiền,Tiền tệ")
    start = next((i for i, l in enumerate(lines) if "ID giao" in l), None)

    # Dò index cột theo tên (mặc định = bố cục 4 cột nếu không đọc được header)
    i_date, i_txid, i_amount, i_pm = 0, 1, 2, None
    if start is not None:
        try:
            header = next(csv.reader([lines[start]]))
            i_date   = _col_index(header, "ngày", default=0)
            i_txid   = _col_index(header, "id giao", default=1)
            i_amount = _col_index(header, "số tiền", default=2)
            i_pm     = _col_index(header, "phương thức")
        except StopIteration:
            pass

    def cell(parts, idx):
        return parts[idx].strip() if idx is not None and idx < len(parts) else ""

    rows: list[dict] = []
    if start is not None:
        for l in lines[start + 1:]:
            try:
                parts = next(csv.reader([l]))
            except StopIteration:
                continue
            if len(parts) < 3:
                continue
            # Bỏ dòng tổng (1 file có thể chứa nhiều bảng, mỗi bảng 1 dòng tổng)
            if "Tổng số tiền" in l:
                continue
            txid = cell(parts, i_txid)
            if not re.match(r"\d+-\d+", txid):
                continue
            rows.append({
                "ID giao dịch": txid,
                "Ngày thanh toán": cell(parts, i_date),
                "Số tiền": _digits(cell(parts, i_amount)),
                "Phương thức TT": _norm(cell(parts, i_pm)) or file_pm,
                "Số tham chiếu thẻ": "",
                "Trạng thái": "",
                "ID hóa đơn VAT": "",
            })

    payment_method = file_pm or (rows[0]["Phương thức TT"] if rows else "")
    # Tổng = cộng dồn số tiền thật của các dòng (đúng cả khi file có nhiều bảng)
    total = str(sum(int(r["Số tiền"]) for r in rows if r["Số tiền"]))
    meta = {
        "account_id": account_id,
        "payment_method": payment_method,
        "n_tx": len(rows),
        "total": total,
    }
    return meta, rows


def suggest_tab_name(account_name: str, account_id: str) -> str:
    """Quy tắc: '<Tên Tài Khoản> (<ID>)'."""
    account_name = _norm(account_name)
    if account_name and account_id:
        return f"{account_name} ({account_id})"
    return f"({account_id})" if account_id else ""


def find_summary_ws(worksheets, account_id: str, expected_name: str):
    """Tìm tab TỔNG HỢP của tài khoản — KHÔNG lấy nhầm tab '... Chi tiết'."""
    if expected_name:
        for w in worksheets:
            if w.title == expected_name:
                return w
    if account_id:
        for w in worksheets:
            if account_id in w.title and not w.title.strip().endswith("Chi tiết"):
                return w
    return None


# ── TKQC API: ID tài khoản → Tên Tài Khoản ─────────────────────────────────────

def load_account_names(spreadsheet) -> dict:
    try:
        ws = spreadsheet.worksheet(AD_ACCOUNTS_SHEET)
    except Exception:
        return {}
    vals = ws.get_all_values()
    if len(vals) < 2:
        return {}
    hdr = vals[0]
    try:
        id_i   = hdr.index("ID Tài Khoản")
        name_i = hdr.index("Tên Tài Khoản")
    except ValueError:
        return {}
    out = {}
    for row in vals[1:]:
        aid = row[id_i].strip().removeprefix("act_") if id_i < len(row) else ""
        nm  = row[name_i].strip() if name_i < len(row) else ""
        if aid:
            out[aid] = nm
    return out


# ── Chống quá tải API (quota 60 lệnh ghi/phút/user của Sheets) ─────────────────

# Giãn cách tối thiểu giữa 2 lệnh gọi API → tối đa ~40 lệnh/phút, dưới trần 60.
# Tăng số này nếu chạy song song nhiều tool dùng chung service account.
_MIN_INTERVAL = 1.5
_rate_lock = threading.Lock()
_last_call = 0.0


def _throttle():
    """Đảm bảo 2 lệnh gọi API liên tiếp cách nhau ít nhất _MIN_INTERVAL giây."""
    global _last_call
    with _rate_lock:
        wait = _last_call + _MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _is_quota_429(e: Exception) -> bool:
    resp = getattr(e, "response", None)
    if getattr(resp, "status_code", None) == 429:
        return True
    return "[429]" in str(e) or "RESOURCE_EXHAUSTED" in str(e)


def _api_call(fn, *args, **kwargs):
    """Gọi API Sheets có giãn nhịp; nếu vẫn dính 429 thì chờ rồi tự thử lại."""
    delay = 20
    for attempt in range(5):
        _throttle()
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == 4 or not _is_quota_429(e):
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)


# ── Định dạng cột TEXT ──────────────────────────────────────────────────────────

def _format_text_columns(worksheet, headers: list):
    requests = []
    for col_name in TEXT_COLS:
        if col_name not in headers:
            continue
        ci = headers.index(col_name)
        requests.append({
            "repeatCell": {
                "range": {"sheetId": worksheet.id,
                          "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        })
    if requests:
        _api_call(worksheet.spreadsheet.batch_update, {"requests": requests})


# ── Upsert theo ID giao dịch ────────────────────────────────────────────────────

def upsert_by_id(worksheet, rows: list[dict], replace: bool = False) -> dict:
    existing = _api_call(worksheet.get_all_values)
    if replace or not existing:
        sheet_hdr, body = list(SUMMARY_HEADERS), []
    else:
        sheet_hdr = existing[0] if existing[0] else list(SUMMARY_HEADERS)
        body = [list(r) for r in existing[1:]]
        seen = {_normalize(h) for h in sheet_hdr}
        for h in SUMMARY_HEADERS:
            if _normalize(h) not in seen:
                sheet_hdr.append(h)
                seen.add(_normalize(h))
        ncols = len(sheet_hdr)
        for r in body:
            while len(r) < ncols:
                r.append("")

    incoming = {str(r.get(ID_COL, "")).strip() for r in rows if str(r.get(ID_COL, "")).strip()}
    removed = 0
    if not replace and incoming and ID_COL in sheet_hdr:
        idx = sheet_hdr.index(ID_COL)
        kept = []
        for r in body:
            rid = r[idx].strip() if idx < len(r) else ""
            if rid and rid in incoming:
                removed += 1
                continue
            kept.append(r)
        body = kept

    norm_map = {_normalize(h): h for h in SUMMARY_HEADERS}

    def val(row, header):
        if header in row:
            return str(row[header])
        src = norm_map.get(_normalize(header))
        return str(row[src]) if src and src in row else ""

    for row in rows:
        body.append([val(row, h) for h in sheet_hdr])

    # Ghi đè 1 LẦN thay cho clear() + update từng khúc 1000 dòng: đệm ô trống
    # phủ hết phần dữ liệu cũ còn thừa → tiết kiệm quota ghi (60 lệnh/phút)
    # và không còn khoảnh khắc tab bị trống nếu lỗi giữa chừng.
    all_data = [sheet_hdr] + body
    ncols = max(len(sheet_hdr), max((len(r) for r in existing), default=0))
    all_data = [r + [""] * (ncols - len(r)) for r in all_data]
    all_data += [[""] * ncols for _ in range(len(existing) - len(all_data))]

    # Cột "Số tiền" ghi dưới dạng SỐ (int), không phải text → Sheets tính tổng
    # trực tiếp, bỏ dấu ' báo "số lưu dạng văn bản". Cột ID vẫn giữ text (bên dưới).
    money_i = next((i for i, h in enumerate(sheet_hdr)
                    if _normalize(h) == _normalize("Số tiền")), None)
    if money_i is not None:
        for r in all_data[1:]:                       # bỏ hàng tiêu đề
            v = str(r[money_i]).strip()
            if v.isdigit():
                r[money_i] = int(v)

    if worksheet.row_count < len(all_data) or worksheet.col_count < ncols:
        _api_call(worksheet.resize,
                  rows=max(worksheet.row_count, len(all_data)),
                  cols=max(worksheet.col_count, ncols))
    _api_call(worksheet.update, "A1", all_data, value_input_option="RAW")
    _format_text_columns(worksheet, sheet_hdr)
    return {"tab": worksheet.title, "added": len(rows),
            "removed": removed, "transactions": len(incoming)}


# ── Giao diện (multi-CSV) ───────────────────────────────────────────────────────

class App(tk.Tk):
    _STATUS_LABEL = {
        "loading":   "Đang đọc...",
        "ready":     "✓ Sẵn sàng",
        "no_tab":    "⚠ Không thấy TK",
        "new_tab":   "✨ Tab mới tạo",
        "importing": "Đang import...",
        "done":      "✓ Hoàn tất",
        "error":     "✗ Lỗi",
    }

    BG, CARD, BORDER = "#eef2f6", "#f8fafc", "#cbd5e1"
    ACCENT, ACCENT_HV, ACCENT_DIS = "#3b82f6", "#2563eb", "#93c5fd"
    TEXT, MUTED = "#334155", "#64748b"
    GREEN, YELLOW, RED, CODE_BG = "#10b981", "#f59e0b", "#ef4444", "#f1f5f9"

    def __init__(self):
        super().__init__()
        self.title("FB Invoice Summary Import → Google Sheet")
        from ui_kit import size_window
        size_window(self, min_w=1040, min_h=600)
        self.configure(bg=self.BG)

        self._spreadsheet = None
        self._worksheets: list = []
        self._name_map: dict = {}          # ID tài khoản → Tên Tài Khoản (TKQC API)
        self._queue: list[dict] = []

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    # ── Style ────────────────────────────────────────────────────────────────
    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=self.BG)
        s.configure("TLabel", background=self.BG, font=("Segoe UI", 10), foreground=self.TEXT)
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(15, 8),
                    background=self.BORDER, foreground=self.TEXT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("TButton", background=[("active", "#cbd5e1"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)])
        s.configure("Soft.TButton", font=("Segoe UI", 9, "bold"), padding=(15, 8),
                    background="#e0f2fe", foreground=self.ACCENT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("Soft.TButton", background=[("active", "#bae6fd"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(24, 10),
                    background=self.ACCENT, foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#ffffff")])
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=29,
                    background=self.CARD, fieldbackground=self.CARD,
                    foreground=self.TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background=self.BORDER, foreground=self.MUTED, relief="flat", padding=(8, 7))
        s.map("Treeview", background=[("selected", self.ACCENT)], foreground=[("selected", "#ffffff")])
        s.configure("TProgressbar", background=self.ACCENT, troughcolor=self.BORDER,
                    borderwidth=0, thickness=8)

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=16, pady=14)

        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 14))
        tk.Label(hdr, text="FB Invoice Summary Import", bg=self.BG,
                 font=("Segoe UI Semibold", 16), fg=self.TEXT).pack(side="left")
        tk.Label(hdr, text="  →  Google Sheet", bg=self.BG,
                 font=("Segoe UI", 11), fg=self.MUTED).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối Google Sheet...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        paned = tk.PanedWindow(outer, orient="horizontal", bg=self.BG,
                               sashwidth=10, sashrelief="flat", bd=0, opaqueresize=True)
        paned.pack(fill="both", expand=True)

        left = self._card_frame(paned, "1", "Tab Google Sheet")
        tk.Label(left.body, text="Tự dò theo ID tài khoản (tra TKQC API). Có thể click tab để gán tay.",
                 bg=self.CARD, font=("Segoe UI", 8), fg=self.MUTED,
                 anchor="w", justify="left").pack(fill="x", pady=(0, 6))
        tab_wrap = tk.Frame(left.body, bg=self.BORDER, highlightthickness=1,
                            highlightbackground=self.BORDER)
        tab_wrap.pack(fill="both", expand=True)
        self._tab_list = tk.Listbox(tab_wrap, selectmode="single", font=("Segoe UI", 10),
                                    activestyle="none", selectbackground=self.ACCENT,
                                    selectforeground="#ffffff", relief="flat", bd=0,
                                    highlightthickness=0, bg=self.CARD, fg=self.TEXT)
        tab_sb = ttk.Scrollbar(tab_wrap, orient="vertical", command=self._tab_list.yview)
        self._tab_list.configure(yscrollcommand=tab_sb.set)
        tab_sb.pack(side="right", fill="y")
        self._tab_list.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self._tab_list.bind("<<ListboxSelect>>", self._on_tab_click)
        paned.add(left, width=290, minsize=220, stretch="never")

        right = self._card_frame(paned, "2", "Danh sách file Invoice Summary (CSV)")
        btn_row = tk.Frame(right.body, bg=self.CARD)
        btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="＋  Thêm CSV...", style="Soft.TButton",
                   command=self._browse_files).pack(side="left")
        ttk.Button(btn_row, text="Xóa đã chọn", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Xóa tất cả", command=self._clear_queue).pack(side="left")

        wrap = tk.Frame(right.body, bg=self.BORDER, highlightthickness=1, highlightbackground=self.BORDER)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        cols = ("file", "acc", "tab", "ntx", "total", "status")
        self._q_tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for c, txt, w_, anc in (
            ("file", "File", 230, "w"), ("acc", "ID tài khoản", 140, "w"),
            ("tab", "Tab đích", 230, "w"), ("ntx", "Số GD", 55, "center"),
            ("total", "Tổng tiền", 110, "e"), ("status", "Trạng thái", 120, "w"),
        ):
            self._q_tree.heading(c, text=txt, anchor=anc)
            self._q_tree.column(c, width=w_, anchor=anc,
                                stretch=(c in ("file", "tab")), minwidth=50)
        qvb = ttk.Scrollbar(wrap, orient="vertical", command=self._q_tree.yview)
        qhb = ttk.Scrollbar(wrap, orient="horizontal", command=self._q_tree.xview)
        self._q_tree.configure(yscrollcommand=qvb.set, xscrollcommand=qhb.set)
        self._q_tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        qvb.grid(row=0, column=1, sticky="ns")
        qhb.grid(row=1, column=0, sticky="ew")
        for tag, color in (("loading", self.MUTED), ("ready", self.GREEN),
                           ("no_tab", self.YELLOW), ("new_tab", self.ACCENT),
                           ("error", self.RED), ("done", self.GREEN), ("importing", self.TEXT)):
            self._q_tree.tag_configure(tag, foreground=color)
        self._q_tree.tag_configure("odd", background=self.BG)
        self._q_tree.bind("<<TreeviewSelect>>", self._on_queue_select)

        self._info_box = tk.Text(right.body, height=6, font=("Consolas", 9), state="disabled",
                                 bg=self.CODE_BG, fg=self.TEXT, relief="flat", bd=0,
                                 padx=10, pady=8, highlightthickness=1,
                                 highlightbackground=self.BORDER)
        self._info_box.pack(fill="x", pady=(8, 0))
        for tag, color in (("ok", self.GREEN), ("warn", self.YELLOW), ("err", self.RED),
                           ("info", self.ACCENT), ("dim", self.MUTED)):
            self._info_box.tag_config(tag, foreground=color)
        paned.add(right, minsize=440, stretch="always")

        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(14, 0))
        self._import_btn = ttk.Button(bot, text="Import tất cả", style="Accent.TButton",
                                      command=self._run_import_all, state="disabled")
        self._import_btn.pack(side="left")
        self._replace_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bot, text="Thay thế dữ liệu cũ", variable=self._replace_var,
                       bg=self.BG, fg=self.TEXT, font=("Segoe UI", 9),
                       activebackground=self.BG, activeforeground=self.TEXT,
                       selectcolor=self.BORDER, relief="flat", bd=0,
                       highlightthickness=0, cursor="hand2", takefocus=0).pack(side="left", padx=(14, 0))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=170)
        self._progress.pack(side="left", padx=14)
        self._result_lbl = tk.Label(bot, text="", bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._result_lbl.pack(side="left")

    def _card_frame(self, parent, num: str, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        head = tk.Frame(card, bg=self.CARD)
        head.pack(fill="x", padx=14, pady=(13, 9))
        tk.Label(head, text=f" {num} ", bg=self.ACCENT, fg="#FFFFFF",
                 font=("Segoe UI", 9, "bold"), padx=4, pady=1).pack(side="left")
        tk.Label(head, text=title, bg=self.CARD, fg=self.TEXT,
                 font=("Segoe UI Semibold", 11)).pack(side="left", padx=(9, 0))
        tk.Frame(card, bg=self.BORDER, height=1).pack(fill="x")
        body = tk.Frame(card, bg=self.CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(11, 13))
        card.body = body
        return card

    # ── Kết nối ───────────────────────────────────────────────────────────────
    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss = connect_spreadsheet()
            wss = ss.worksheets()
            names = load_account_names(ss)
            self._spreadsheet = ss
            self._worksheets = wss
            self._name_map = names
            self.after(0, self._load_tabs)
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi kết nối: {e}", error=True))

    def _load_tabs(self):
        self._tab_list.delete(0, "end")
        for ws in self._worksheets:
            self._tab_list.insert("end", ws.title)
        self._set_status(f"Đã kết nối: {self._spreadsheet.title}  ·  {len(self._worksheets)} tab  ·  "
                         f"{len(self._name_map)} TK trong TKQC API")
        for item in self._queue:
            if item["meta"] and item["status"] in ("no_tab", "loading"):
                self._auto_match(item)
                self._refresh_tree_row(item)
        self._refresh_import_btn()

    # ── Chọn CSV ──────────────────────────────────────────────────────────────
    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            initialdir=str(Path.home() / "Downloads"),
            title="Chọn file Invoice Summary (CSV)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        for path_str in paths:
            p = Path(path_str)
            if any(i["path"] == p for i in self._queue):
                continue
            item = {"path": p, "meta": None, "rows": [], "ws": None,
                    "is_new_tab": False, "suggested": "", "status": "loading",
                    "error": "", "iid": ""}
            iid = self._q_tree.insert("", "end",
                                      values=(p.name, "—", "—", "—", "—", "Đang đọc..."),
                                      tags=("loading",))
            item["iid"] = iid
            self._queue.append(item)
            threading.Thread(target=self._load_file_worker, args=(item,), daemon=True).start()

    def _load_file_worker(self, item: dict):
        try:
            meta, rows = parse_invoice_csv(item["path"])
            if not meta["account_id"]:
                raise RuntimeError("Không tìm thấy 'Tài khoản: <ID>' trong file")
            if not rows:
                raise RuntimeError("Không bóc được giao dịch nào từ file")
            item["meta"] = meta
            item["rows"] = rows
            if self._spreadsheet is not None:
                self._auto_match(item)
            else:
                item["status"] = "loading"       # chờ kết nối xong rồi dò lại
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
        self.after(0, lambda i=item: self._on_file_loaded(i))

    def _auto_match(self, item: dict):
        acc = item["meta"]["account_id"]
        name = self._name_map.get(acc, "")
        item["suggested"] = suggest_tab_name(name, acc)
        ws = find_summary_ws(self._worksheets, acc, item["suggested"])
        if ws:
            item["ws"], item["is_new_tab"], item["status"] = ws, False, "ready"
        elif name:                                # có tên trong TKQC API → tạo tab mới
            item["ws"], item["is_new_tab"], item["status"] = None, True, "new_tab"
        else:                                     # không thấy ID trong TKQC API
            item["ws"], item["is_new_tab"], item["status"] = None, False, "no_tab"

    def _on_file_loaded(self, item: dict):
        self._refresh_tree_row(item)
        self._refresh_selected_info(item)
        self._refresh_import_btn()

    # ── Gán tab thủ công ──────────────────────────────────────────────────────
    def _on_tab_click(self, *_):
        sel_tabs = self._tab_list.curselection()
        sel_iids = self._q_tree.selection()
        if not sel_tabs or not sel_iids:
            return
        ws = self._worksheets[sel_tabs[0]]
        for iid in sel_iids:
            item = self._item_by_iid(iid)
            if item and item["status"] not in ("importing", "done", "loading"):
                item["ws"], item["is_new_tab"], item["status"] = ws, False, "ready"
                self._refresh_tree_row(item)
                self._refresh_selected_info(item)
        self._refresh_import_btn()

    # ── Queue helpers ─────────────────────────────────────────────────────────
    def _item_by_iid(self, iid):
        return next((i for i in self._queue if i["iid"] == iid), None)

    def _target_tab_text(self, item: dict) -> str:
        if item["ws"]:
            return item["ws"].title
        if item["status"] == "new_tab" and item["suggested"]:
            return item["suggested"] + "  ✨"
        return "—"

    def _refresh_tree_row(self, item: dict):
        m = item["meta"] or {}
        total = f"{int(m['total']):,} ₫".replace(",", ".") if str(m.get("total", "")).isdigit() else "—"
        idx = self._q_tree.index(item["iid"])
        tags = (item["status"],) if idx % 2 == 0 else ("odd", item["status"])
        self._q_tree.item(item["iid"], values=(
            item["path"].name, m.get("account_id", "—") or "—",
            self._target_tab_text(item), str(m.get("n_tx", "—")) if m else "—",
            total, self._STATUS_LABEL.get(item["status"], item["status"]),
        ), tags=tags)

    def _refresh_import_btn(self):
        ok = any(i["status"] in ("ready", "new_tab") for i in self._queue)
        self._import_btn.configure(state="normal" if ok else "disabled")

    def _on_queue_select(self, *_):
        sel = self._q_tree.selection()
        if sel:
            item = self._item_by_iid(sel[0])
            if item:
                self._show_item_info(item)

    def _refresh_selected_info(self, item: dict):
        sel = self._q_tree.selection()
        if sel and sel[0] == item["iid"]:
            self._show_item_info(item)

    def _show_item_info(self, item: dict):
        self._info_box.configure(state="normal")
        self._info_box.delete("1.0", "end")
        L = lambda t, tag="dim": self._info_box.insert("end", t, tag)
        L(f"File : {item['path'].name}\n")
        if item["status"] == "error":
            L(f"Lỗi  : {item['error']}\n", "err")
        elif item["meta"]:
            m = item["meta"]
            name = self._name_map.get(m["account_id"], "")
            L(f"ID tài khoản : {m['account_id']}"
              + (f"  →  {name}\n" if name else "  →  (không có trong TKQC API)\n"),
              "ok" if name else "warn")
            L(f"Giao dịch    : {m['n_tx']} dòng   ·   Tổng: "
              f"{int(m['total']):,} ₫\n".replace(",", "."))
            L(f"Phương thức  : {m['payment_method']}\n")
            if item["ws"]:
                L(f"Tab đích     : {item['ws'].title}\n", "ok")
            elif item["status"] == "new_tab":
                L(f"Tab đích     : {item['suggested']}  ✨ (sẽ tạo mới khi import)\n", "info")
            else:
                L("Tab đích     : chưa xác định — ID không có trong TKQC API. "
                  "Chạy 'Cập nhật TKQC' hoặc click tab bên trái để gán tay.\n", "warn")
        self._info_box.configure(state="disabled")

    def _remove_selected(self):
        for iid in list(self._q_tree.selection()):
            item = self._item_by_iid(iid)
            if item and item["status"] != "importing":
                self._queue.remove(item)
                self._q_tree.delete(iid)
        self._refresh_import_btn()

    def _clear_queue(self):
        for item in [i for i in self._queue if i["status"] != "importing"]:
            self._queue.remove(item)
            self._q_tree.delete(item["iid"])
        self._refresh_import_btn()

    # ── Import ────────────────────────────────────────────────────────────────
    def _run_import_all(self):
        items = [i for i in self._queue if i["status"] in ("ready", "new_tab")]
        if not items:
            return
        replace = self._replace_var.get()
        new_tabs = [i for i in items if i["status"] == "new_tab"]
        msg = [f"Sẽ import {len(items)} file Invoice Summary."]
        if new_tabs:
            msg.append(f"Tạo mới {len(new_tabs)} tab (theo '<Tên TKQC API> (<ID>)').")
        if replace:
            msg.append("⚠ THAY THẾ: xóa toàn bộ dữ liệu cũ trong tab trước khi ghi.")
        if not messagebox.askyesno("Xác nhận Import", "\n".join(msg)):
            return
        self._import_btn.configure(state="disabled")
        self._progress.start(12)
        self._result_lbl.configure(text="Đang import...")
        threading.Thread(target=self._import_worker, args=(items, replace), daemon=True).start()

    def _import_worker(self, items: list, replace: bool):
        added = removed = errors = 0
        created: dict = {}   # title → ws (tab đã tạo/dùng trong lần chạy này)
        wiped: set = set()   # title đã bị "Thay thế" — chỉ xóa 1 lần/tab
        for item in items:
            item["status"] = "importing"
            self.after(0, lambda i=item: self._refresh_tree_row(i))
            try:
                # Nhiều file cùng 1 tab: tạo tab 1 lần rồi dùng lại cho các file sau
                ws = item["ws"]
                if ws is None:
                    title = item["suggested"]
                    ws = created.get(title) or next(
                        (w for w in self._worksheets if w.title == title), None)
                    if ws is None:
                        ws = _api_call(
                            self._spreadsheet.add_worksheet,
                            title=title, rows=max(len(item["rows"]) + 10, 100),
                            cols=len(SUMMARY_HEADERS))
                        self._worksheets.append(ws)
                        self.after(0, lambda t=title: self._tab_list.insert("end", t))
                    item["ws"] = ws
                created[ws.title] = ws
                # "Thay thế" chỉ xóa lần đầu chạm tab; file cùng tab sau đó chỉ thêm mới
                eff_replace = replace and ws.title not in wiped
                stats = upsert_by_id(ws, item["rows"], replace=eff_replace)
                wiped.add(ws.title)
                added += stats["added"]
                removed += stats["removed"]
                item["status"] = "done"
            except Exception as e:
                item["status"] = "error"
                item["error"] = str(e)
                errors += 1
            self.after(0, lambda i=item: self._refresh_tree_row(i))
        self.after(0, lambda: self._import_done(added, removed, errors, len(items)))

    def _import_done(self, added: int, removed: int, errors: int, total: int):
        self._progress.stop()
        self._refresh_import_btn()
        if errors:
            self._result_lbl.configure(text=f"✓ {total - errors}/{total} file  ✗ {errors} lỗi")
        else:
            self._result_lbl.configure(
                text=f"✓  {total} file  +{added} dòng  (thay {removed} dòng trùng ID)")

    # ── Tiện ích ──────────────────────────────────────────────────────────────
    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(text=text, foreground=self.RED if error else self.MUTED)


if __name__ == "__main__":
    App().mainloop()
