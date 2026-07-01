"""
Nhập lịch sử thanh toán Facebook Ads từ HÓA ĐƠN PDF (biên lai Meta) → Google Sheet.

Giống fb_billing_import.py nhưng nguồn là nhiều file PDF chọn từ máy (không phải CSV/XLS).
Mỗi PDF = 1 giao dịch, tách thành nhiều dòng theo từng chiến dịch, ghi vào tab
"... Chi tiết" với ĐÚNG 19 cột như bản xuất của extension FB Billing Scraper.

- Dedup theo "ID giao dịch" ở cấp GIAO DỊCH: import lại 1 PDF sẽ thay toàn bộ dòng của
  giao dịch đó (giữ nhiều dòng chiến dịch, idempotent).
- Cột ID giữ định dạng TEXT (không mất số 0 đầu), giống fb_billing_import.
- Tự dò tab theo "ID tài khoản" trong hóa đơn; chưa có thì tạo tab mới theo quy tắc cũ:
      "<Tên tài khoản> (<ID tài khoản>) Chi tiết"

Chạy: python fb_billing_pdf_import.py
"""

import re
import sys
import threading
from pathlib import Path

try:
    import pdfplumber
    _PDF_OK = True
except ImportError:
    _PDF_OK = False

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    sys.exit("Cần tkinter (có sẵn trong Python chuẩn trên Windows).")

# Tái dùng backend của fb_billing_import để ghi & định dạng giống hệt
from fb_billing_import import (
    connect_spreadsheet,
    _format_text_columns,
    _normalize,
    ID_COL,
    STATUS_ALLOW,
)

BASE_DIR = Path(__file__).parent

# 19 cột — TRÙNG KHỚP _buildDetailSheet trong fb_billing_scraper/popup.js
DETAIL_HEADERS = [
    "ID giao dịch", "Ngày thanh toán", "Giờ thanh toán", "Số tham chiếu",
    "Tổng tiền giao dịch", "Số tiền phân bổ", "Tài khoản quảng cáo", "4 số cuối thẻ",
    "Tên chiến dịch", "Tên nhóm quảng cáo", "ID nhóm quảng cáo", "Kết quả",
    "Thời gian tính phí", "Phương thức thanh toán", "Trạng thái", "Thuế",
    "Lý do lập hóa đơn", "Loại kết quả", "Ghi chú",
]


# ── Đọc & bóc tách PDF ──────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _digits(s: str) -> str:
    """'971.703 ₫' → '971703' (dấu chấm VN là ngăn cách nghìn)."""
    return re.sub(r"[^\d]", "", s or "")


def parse_receipt(text: str) -> tuple[dict, list[dict]]:
    """Bóc 1 biên lai Meta thành (meta, rows) — rows theo từng chiến dịch (19 cột)."""
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
    full = "\n".join(lines)

    def find(pat, grp=1):
        m = re.search(pat, full)
        return _norm(m.group(grp)) if m else ""

    account_name = find(r"Biên lai cho\s+(.+)")
    account_id   = find(r"ID tài khoản:\s*(\d+)")
    tx_id        = find(r"(\d{6,}-\d{6,})")
    reference    = find(r"Số tham chiếu:\s*([A-Za-z0-9]+)")

    mdt = re.search(r"(\d{1,2}:\d{2})\s+(\d{1,2} tháng \d{1,2},\s*\d{4})", full)
    ptime = mdt.group(1) if mdt else ""
    pdate = _norm(mdt.group(2)) if mdt else ""

    mcard = re.search(
        r"((?:Visa|Mastercard|MasterCard|JCB|American Express|Amex|Napas|ATM)[^\n]*?(\d{4}))",
        full,
    )
    payment_method = _norm(mcard.group(1)) if mcard else ""
    card_last4     = mcard.group(2) if mcard else ""

    status = STATUS_ALLOW if STATUS_ALLOW in full else ""
    note   = find(r"(Khoản thanh toán[^\n]*)")
    period = find(r"(Từ .+?đến .+?\d{4})")

    # "Lý do lập hóa đơn" = dòng ngay sau "Chiến dịch" (vd: "Lượt mua")
    reason = ""
    for i, ln in enumerate(lines):
        if ln == "Chiến dịch" and i + 1 < len(lines):
            reason = lines[i + 1]
            break

    # Tổng in trên hóa đơn: dòng chỉ chứa "<số> ₫"
    total_printed = ""
    for ln in lines:
        m = re.match(r"^([\d.]+)\s*₫$", ln)
        if m:
            total_printed = _digits(m.group(1))
            break

    # Danh sách chiến dịch nằm sau "Chiến dịch", dừng ở footer hóa đơn
    campaigns = []
    started = False
    for ln in lines:
        if ln == "Chiến dịch":
            started = True
            continue
        if not started:
            continue
        if ln.startswith(("Meta Platforms", "Powered by", "Hóa đơn #")):
            break
        ma = re.search(r"([\d.]+)\s*₫\s*$", ln)
        if not ma:
            continue
        amount = _digits(ma.group(1))
        head = ln[:ma.start()].rstrip()
        # head kết thúc bằng "<tên> <kết quả> <loại kết quả>"; neo từ phải:
        # kết quả = số cuối, loại kết quả = phần chữ (không số) tới cuối chuỗi.
        m2 = re.search(r"(?P<result>[\d][\d.]*)\s+(?P<rtype>[^\d]+?)$", head)
        if not m2:
            continue  # dòng tổng (chỉ có số tiền, không có kết quả) → bỏ
        name = _norm(head[:m2.start()])
        if not name:
            continue
        campaigns.append({
            "name": name,
            "result": m2.group("result"),
            "rtype": _norm(m2.group("rtype")),
            "amount": amount,
        })

    total = total_printed or str(sum(int(c["amount"]) for c in campaigns if c["amount"]))

    meta = {
        "account_name": account_name, "account_id": account_id, "tx_id": tx_id,
        "reference": reference, "total": total, "n_campaigns": len(campaigns),
    }
    rows = [{
        "ID giao dịch": tx_id, "Ngày thanh toán": pdate, "Giờ thanh toán": ptime,
        "Số tham chiếu": reference, "Tổng tiền giao dịch": total,
        "Số tiền phân bổ": c["amount"], "Tài khoản quảng cáo": account_id,
        "4 số cuối thẻ": card_last4, "Tên chiến dịch": c["name"],
        "Tên nhóm quảng cáo": "", "ID nhóm quảng cáo": "", "Kết quả": c["result"],
        "Thời gian tính phí": period, "Phương thức thanh toán": payment_method,
        "Trạng thái": status, "Thuế": "", "Lý do lập hóa đơn": reason,
        "Loại kết quả": c["rtype"], "Ghi chú": note,
    } for c in campaigns]
    return meta, rows


def read_pdf(path: Path) -> tuple[dict, list[dict]]:
    with pdfplumber.open(str(path)) as pdf:
        text = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
    return parse_receipt(text)


def suggest_tab_name(meta: dict) -> str:
    """Quy tắc cũ: '<Tên tài khoản> (<ID tài khoản>) Chi tiết'."""
    name = meta.get("account_name", "").strip()
    acc  = meta.get("account_id", "").strip()
    base = f"{name} ({acc})" if acc else name
    return _norm(f"{base} Chi tiết") or "Chi tiết"


# ── Upsert cấp giao dịch ────────────────────────────────────────────────────────

def upsert_transactions(worksheet, rows: list[dict], replace: bool = False) -> dict:
    """Ghi rows (nhiều dòng/1 giao dịch) vào sheet, dedup theo ID giao dịch ở cấp giao dịch.

    - replace=True : xoá sạch tab, chỉ ghi dữ liệu mới.
    - replace=False: xoá mọi dòng cũ có ID giao dịch trùng với lô mới rồi thêm lô mới.
    """
    if replace or not (worksheet.get_all_values()):
        sheet_hdr, body = list(DETAIL_HEADERS), []
    else:
        existing = worksheet.get_all_values()
        sheet_hdr = existing[0] if existing and existing[0] else list(DETAIL_HEADERS)
        body = [list(r) for r in existing[1:]]
        # Bổ sung cột thiếu (giữ cột lạ người dùng tự thêm)
        seen = {_normalize(h) for h in sheet_hdr}
        for h in DETAIL_HEADERS:
            if _normalize(h) not in seen:
                sheet_hdr.append(h)
                seen.add(_normalize(h))
        ncols = len(sheet_hdr)
        for r in body:
            while len(r) < ncols:
                r.append("")

    incoming_ids = {str(r.get(ID_COL, "")).strip()
                    for r in rows if str(r.get(ID_COL, "")).strip()}

    removed = 0
    if not replace and incoming_ids and ID_COL in sheet_hdr:
        idx = sheet_hdr.index(ID_COL)
        kept = []
        for r in body:
            rid = r[idx].strip() if idx < len(r) else ""
            if rid and rid in incoming_ids:
                removed += 1
                continue
            kept.append(r)
        body = kept

    norm_map = {_normalize(h): h for h in DETAIL_HEADERS}

    def val(row: dict, header: str) -> str:
        if header in row:
            return str(row[header])
        src = norm_map.get(_normalize(header))
        return str(row[src]) if src and src in row else ""

    for row in rows:
        body.append([val(row, h) for h in sheet_hdr])

    worksheet.clear()
    all_data = [sheet_hdr] + body
    BATCH = 1000
    for start in range(0, len(all_data), BATCH):
        worksheet.update(f"A{start + 1}", all_data[start:start + BATCH],
                         value_input_option="RAW")
    _format_text_columns(worksheet, sheet_hdr)
    return {"tab": worksheet.title, "added": len(rows),
            "removed": removed, "transactions": len(incoming_ids)}


# ── Giao diện (multi-PDF) ───────────────────────────────────────────────────────

class App(tk.Tk):
    _STATUS_LABEL = {
        "loading":   "Đang đọc...",
        "ready":     "✓ Sẵn sàng",
        "no_tab":    "⚠ Chưa gán tab",
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
        self.title("FB Billing PDF Import → Google Sheet")
        w, h = 1200, 720
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(960, 600)
        self.configure(bg=self.BG)

        self._spreadsheet = None
        self._worksheets: list = []
        self._queue: list[dict] = []

        self._apply_styles()
        self._build_ui()
        if not _PDF_OK:
            self._set_status("Thiếu thư viện pdfplumber — chạy: pip install pdfplumber", error=True)
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
        tk.Label(hdr, text="FB Billing PDF Import", bg=self.BG,
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
        tk.Label(left.body, text="Tự dò theo ID tài khoản. Có thể click tab để gán thủ công.",
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

        right = self._card_frame(paned, "2", "Danh sách hóa đơn PDF")
        btn_row = tk.Frame(right.body, bg=self.CARD)
        btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="＋  Thêm PDF...", style="Soft.TButton",
                   command=self._browse_files).pack(side="left")
        ttk.Button(btn_row, text="Xóa đã chọn", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Xóa tất cả", command=self._clear_queue).pack(side="left")

        wrap = tk.Frame(right.body, bg=self.BORDER, highlightthickness=1, highlightbackground=self.BORDER)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        cols = ("file", "acc", "tab", "camp", "total", "status")
        self._q_tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for c, txt, w_, anc in (
            ("file", "File", 240, "w"), ("acc", "Tài khoản", 150, "w"),
            ("tab", "Tab đích", 220, "w"), ("camp", "Camp", 55, "center"),
            ("total", "Tổng tiền", 110, "e"), ("status", "Trạng thái", 120, "w"),
        ):
            self._q_tree.heading(c, text=txt, anchor=anc)
            self._q_tree.column(c, width=w_, anchor=anc,
                                stretch=(c in ("file", "tab")),
                                minwidth=50)
        qvb = ttk.Scrollbar(wrap, orient="vertical", command=self._q_tree.yview)
        qhb = ttk.Scrollbar(wrap, orient="horizontal", command=self._q_tree.xview)
        self._q_tree.configure(yscrollcommand=qvb.set, xscrollcommand=qhb.set)
        self._q_tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        qvb.grid(row=0, column=1, sticky="ns")
        qhb.grid(row=1, column=0, sticky="ew")
        for tag, color in (("odd", self.BG), ("loading", self.MUTED), ("ready", self.GREEN),
                           ("no_tab", self.YELLOW), ("new_tab", self.ACCENT),
                           ("error", self.RED), ("done", self.GREEN), ("importing", self.TEXT)):
            self._q_tree.tag_configure(tag, foreground=color) if tag != "odd" \
                else self._q_tree.tag_configure(tag, background=color)
        self._q_tree.bind("<<TreeviewSelect>>", self._on_queue_select)

        self._info_box = tk.Text(right.body, height=6, font=("Consolas", 9), state="disabled",
                                 bg=self.CODE_BG, fg=self.TEXT, relief="flat", bd=0,
                                 padx=10, pady=8, highlightthickness=1,
                                 highlightbackground=self.BORDER)
        self._info_box.pack(fill="x", pady=(8, 0))
        for tag, color in (("ok", self.GREEN), ("warn", self.YELLOW), ("err", self.RED),
                           ("info", self.ACCENT), ("dim", self.MUTED)):
            self._info_box.tag_config(tag, foreground=color)
        paned.add(right, minsize=460, stretch="always")

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
            self._spreadsheet = ss
            self._worksheets = wss
            self.after(0, self._load_tabs)
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi kết nối: {e}", error=True))

    def _load_tabs(self):
        self._tab_list.delete(0, "end")
        for ws in self._worksheets:
            self._tab_list.insert("end", ws.title)
        self._set_status(f"Đã kết nối: {self._spreadsheet.title}  ({len(self._worksheets)} tab)")
        # Dò lại tab cho các item đã đọc xong trước khi kết nối
        for item in self._queue:
            if item["status"] == "no_tab" and item["meta"]:
                self._auto_match(item)
                self._refresh_tree_row(item)
        self._refresh_import_btn()

    # ── Chọn PDF ──────────────────────────────────────────────────────────────
    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            initialdir=str(Path.home() / "Downloads"),
            title="Chọn hóa đơn PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        for path_str in paths:
            p = Path(path_str)
            if any(i["path"] == p for i in self._queue):
                continue
            item = {"path": p, "meta": None, "rows": [], "ws": None,
                    "is_new_tab": False, "status": "loading", "error": "", "iid": ""}
            iid = self._q_tree.insert("", "end",
                                      values=(p.name, "—", "—", "—", "—", "Đang đọc..."),
                                      tags=("loading",))
            item["iid"] = iid
            self._queue.append(item)
            threading.Thread(target=self._load_file_worker, args=(item,), daemon=True).start()

    def _load_file_worker(self, item: dict):
        try:
            if not _PDF_OK:
                raise RuntimeError("Chưa cài pdfplumber (pip install pdfplumber)")
            meta, rows = read_pdf(item["path"])
            if not rows:
                raise RuntimeError("Không bóc được dòng chiến dịch nào từ PDF")
            item["meta"] = meta
            item["rows"] = rows
            self._auto_match(item)
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
        self.after(0, lambda i=item: self._on_file_loaded(i))

    def _auto_match(self, item: dict):
        """Dò tab theo ID tài khoản; không thấy → sẽ tạo tab mới theo quy tắc cũ."""
        acc = item["meta"].get("account_id", "").strip()
        ws = None
        if acc:
            ws = next((w for w in self._worksheets if acc in w.title), None)
        if ws:
            item["ws"] = ws
            item["is_new_tab"] = False
            item["status"] = "ready"
        elif self._spreadsheet is None:
            item["status"] = "no_tab"          # chờ kết nối xong rồi dò lại
        else:
            item["ws"] = None
            item["is_new_tab"] = True
            item["status"] = "new_tab"         # sẽ tạo tab lúc import

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
                item["ws"] = ws
                item["is_new_tab"] = False
                item["status"] = "ready"
                self._refresh_tree_row(item)
                self._refresh_selected_info(item)
        self._refresh_import_btn()

    # ── Queue helpers ─────────────────────────────────────────────────────────
    def _item_by_iid(self, iid):
        return next((i for i in self._queue if i["iid"] == iid), None)

    def _target_tab_text(self, item: dict) -> str:
        if item["ws"]:
            return item["ws"].title
        if item["meta"] and item["status"] == "new_tab":
            return suggest_tab_name(item["meta"]) + "  ✨"
        return "—"

    def _refresh_tree_row(self, item: dict):
        m = item["meta"] or {}
        total = f"{int(m['total']):,} ₫".replace(",", ".") if m.get("total", "").isdigit() else "—"
        idx = self._q_tree.index(item["iid"])
        tags = (item["status"],) if idx % 2 == 0 else ("odd", item["status"])
        self._q_tree.item(item["iid"], values=(
            item["path"].name, m.get("account_name", "—") or "—",
            self._target_tab_text(item),
            str(m.get("n_campaigns", "—")) if m else "—",
            total, self._STATUS_LABEL.get(item["status"], item["status"]),
        ), tags=tags)

    def _refresh_import_btn(self):
        ok = any(i["status"] in ("ready", "new_tab") for i in self._queue)
        self._import_btn.configure(state="normal" if ok and _PDF_OK else "disabled")

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
            L(f"Tài khoản : {m['account_name']}  (ID {m['account_id']})\n", "ok")
            L(f"Giao dịch : {m['tx_id']}\n")
            L(f"Chiến dịch: {m['n_campaigns']} dòng   ·   Tổng: "
              f"{int(m['total']):,} ₫\n".replace(",", "."))
            if item["ws"]:
                L(f"Tab đích  : {item['ws'].title}\n", "ok")
            elif item["status"] == "new_tab":
                L(f"Tab đích  : {suggest_tab_name(m)}  ✨ (sẽ tạo mới khi import)\n", "info")
            else:
                L("Tab đích  : chưa gán — click tab bên trái\n", "warn")
            L("Lưu ý: tên chiến dịch trong PDF bị Facebook cắt ngắn ('...').\n", "warn")
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
        msg = [f"Sẽ import {len(items)} hóa đơn PDF."]
        if new_tabs:
            msg.append(f"Tạo mới {len(new_tabs)} tab (theo quy tắc '<Tên> (<ID>) Chi tiết').")
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
        for item in items:
            item["status"] = "importing"
            self.after(0, lambda i=item: self._refresh_tree_row(i))
            try:
                if item["ws"] is None:                    # tạo tab mới theo quy tắc cũ
                    title = suggest_tab_name(item["meta"])
                    ws = self._spreadsheet.add_worksheet(
                        title=title, rows=max(len(item["rows"]) + 10, 100),
                        cols=len(DETAIL_HEADERS))
                    item["ws"] = ws
                    self._worksheets.append(ws)
                    self.after(0, lambda t=title: self._tab_list.insert("end", t))
                stats = upsert_transactions(item["ws"], item["rows"], replace=replace)
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
                text=f"✓  {total} hóa đơn  +{added} dòng  (thay {removed} dòng trùng ID)")

    # ── Tiện ích ──────────────────────────────────────────────────────────────
    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(text=text, foreground=self.RED if error else self.MUTED)


if __name__ == "__main__":
    App().mainloop()
