"""
Nhập lịch sử thanh toán Facebook Ads từ CSV → Google Sheet.
GUI: chọn tab → chọn file CSV → kiểm tra cấu trúc → xem trước → import (upsert).
"""

import csv
import re
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    sys.exit("Cần tkinter (có sẵn trong Python chuẩn trên Windows).")

# ── Cấu hình ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
SHEET_ID = "1zZ7H9lj_s4Dm1hTeMvrQtKLFeiOBb5rWu8h7QJ458PM"
SCOPES   = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ID_COL           = "ID giao dịch"
STATUS_COL       = "Trạng thái"
STATUS_ALLOW     = "Đã thanh toán"
KNOWN_MONEY_COLS = ["Số tiền", "Thuế", "Tổng tiền giao dịch"]
TEXT_ID_COLS     = [
    "ID giao dịch",
    "Tài khoản quảng cáo",
    "ID nhóm quảng cáo",
    "Số tham chiếu",
]

# ── Logic nghiệp vụ ────────────────────────────────────────────────────────────

def connect_spreadsheet():
    creds = Credentials.from_service_account_file(
        str(BASE_DIR / "service_account.json"), scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(SHEET_ID)


def parse_vnd(text: str):
    if not text or not isinstance(text, str):
        return None
    s = text.replace("₫", "").replace("'", "").strip()
    if re.search(r"\d\.\d{3}", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s.strip()) if s.strip() else None
    except ValueError:
        return None


def read_csv(path: Path):
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                headers = list(reader.fieldnames or [])
                rows    = list(reader)
            return headers, rows
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Không đọc được file: {path}")


def read_xls(path: Path):
    """Đọc file SpreadsheetML (.xls) do FB Billing Scraper extension xuất ra."""
    NS = 'urn:schemas-microsoft-com:office:spreadsheet'
    tree = ET.parse(path)
    root = tree.getroot()

    worksheet = root.find(f'{{{NS}}}Worksheet')
    if worksheet is None:
        raise RuntimeError("Không tìm thấy Worksheet trong file XLS")
    table = worksheet.find(f'{{{NS}}}Table')
    if table is None:
        raise RuntimeError("Không tìm thấy Table trong file XLS")

    all_rows = []
    for row_el in table.findall(f'{{{NS}}}Row'):
        row = []
        for cell_el in row_el.findall(f'{{{NS}}}Cell'):
            data_el = cell_el.find(f'{{{NS}}}Data')
            row.append(data_el.text or '' if data_el is not None else '')
        all_rows.append(row)

    if not all_rows:
        return [], []

    headers = all_rows[0]
    rows = [
        dict(zip(headers, r + [''] * max(0, len(headers) - len(r))))
        for r in all_rows[1:]
    ]
    return headers, rows


def read_file(path: Path):
    if path.suffix.lower() == '.xls':
        return read_xls(path)
    return read_csv(path)


def _normalize(name: str) -> str:
    """Chuẩn hóa tên cột để so sánh mềm: bỏ ký tự đặc biệt, lowercase."""
    return re.sub(r"[^\w]", "", name, flags=re.UNICODE).lower()


def filter_by_status(csv_headers: list, csv_rows: list) -> tuple:
    """Chỉ giữ dòng có Trạng thái == STATUS_ALLOW; nếu cột vắng thì giữ tất cả."""
    if STATUS_COL not in csv_headers:
        return csv_rows, 0
    kept    = [r for r in csv_rows if STATUS_ALLOW in str(r.get(STATUS_COL, ""))]
    skipped = len(csv_rows) - len(kept)
    return kept, skipped


def analyze_structure(csv_headers: list, sheet_headers: list) -> dict:
    """So sánh cột CSV với cột sheet, trả về dict phân tích."""
    # Lọc bỏ: tên rỗng + cột numeric tự sinh
    def keep(h: str) -> bool:
        return bool(h.strip()) and not h.endswith(" (numeric)")

    clean_sheet = [h for h in sheet_headers if keep(h)]
    clean_csv   = [h for h in csv_headers   if keep(h)]

    csv_norm   = {_normalize(h): h for h in clean_csv}
    sheet_norm = {_normalize(h): h for h in clean_sheet}

    # Khớp theo tên chuẩn hóa (bỏ qua ký tự đặc biệt như ₫, dấu nháy...)
    matched  = [h for h in clean_csv   if _normalize(h) in sheet_norm]
    new_cols = [h for h in clean_csv   if _normalize(h) not in sheet_norm]
    missing  = [h for h in clean_sheet if _normalize(h) not in csv_norm]

    return {
        "matched":     matched,
        "new_cols":    new_cols,
        "missing":     missing,
        "has_id":      ID_COL in set(csv_headers),
        "sheet_empty": len(clean_sheet) == 0,
    }


def _format_text_columns(worksheet, headers: list):
    requests = []
    for col_name in TEXT_ID_COLS:
        if col_name not in headers:
            continue
        ci = headers.index(col_name)
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId":          worksheet.id,
                    "startColumnIndex": ci,
                    "endColumnIndex":   ci + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "TEXT"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        })
    if requests:
        worksheet.spreadsheet.batch_update({"requests": requests})


def upsert(worksheet, csv_headers: list, csv_rows: list) -> dict:
    # Lookup chuẩn hóa: "Số tiền" ≈ "Số tiền (₫)"
    csv_norm_map = {_normalize(h): h for h in csv_headers}

    existing = worksheet.get_all_values()
    if existing:
        sheet_hdr  = existing[0]
        sheet_body = [list(r) for r in existing[1:]]
    else:
        sheet_hdr  = []
        sheet_body = []

    if not sheet_hdr:
        sheet_hdr  = list(csv_headers)
        sheet_body = []
    else:
        # Thêm cột mới từ CSV nếu chưa có trong sheet
        sheet_norm = {_normalize(h) for h in sheet_hdr}
        for h in csv_headers:
            if _normalize(h) not in sheet_norm:
                sheet_hdr.append(h)
                sheet_norm.add(_normalize(h))
        ncols = len(sheet_hdr)
        for r in sheet_body:
            while len(r) < ncols:
                r.append("")

    id_idx = sheet_hdr.index(ID_COL) if ID_COL in sheet_hdr else None
    existing_ids: dict = {}
    if id_idx is not None:
        for i, row in enumerate(sheet_body):
            rid = row[id_idx].strip() if id_idx < len(row) else ""
            if rid:
                existing_ids[rid] = i

    def _get_csv_val(row: dict, col_name: str) -> str:
        if col_name in row:
            return str(row[col_name])
        norm = csv_norm_map.get(_normalize(col_name))
        return str(row[norm]) if norm and norm in row else ""

    updated = added = 0
    for csv_row in csv_rows:
        row_vals = [_get_csv_val(csv_row, h) for h in sheet_hdr]

        csv_id = str(csv_row.get(ID_COL, "")).strip() if ID_COL in csv_headers else ""

        if csv_id and csv_id in existing_ids:
            sheet_body[existing_ids[csv_id]] = row_vals
            updated += 1
        else:
            if csv_id:
                existing_ids[csv_id] = len(sheet_body)
            sheet_body.append(row_vals)
            added += 1

    worksheet.clear()
    all_data = [sheet_hdr] + sheet_body
    BATCH = 1000
    for start in range(0, len(all_data), BATCH):
        worksheet.update(f"A{start + 1}", all_data[start:start + BATCH],
                         value_input_option="RAW")

    _format_text_columns(worksheet, sheet_hdr)
    return {"tab": worksheet.title, "total": len(csv_rows),
            "updated": updated, "added": added}


# ── Hộp thoại xác nhận ────────────────────────────────────────────────────────

class ConfirmDialog(tk.Toplevel):
    """Hiện phân tích cấu trúc + hỏi xác nhận trước khi import."""

    def __init__(self, parent, analysis: dict, csv_rows: int, skipped: int, sheet_title: str):
        super().__init__(parent)
        self.title("Xác nhận Import")
        self.resizable(False, False)
        self.grab_set()
        self.result = False

        pad = dict(padx=16, pady=6)

        # Tiêu đề
        tk.Label(self, text="Phân tích cấu trúc trước khi ghi",
                 font=("Segoe UI", 11, "bold"),
                 fg="#1A1A2E").pack(anchor="w", padx=16, pady=(14, 4))

        # Thông tin sheet + CSV
        total = csv_rows + skipped
        skip_line = f"\n  Bỏ qua    : {skipped} dòng (không phải '{STATUS_ALLOW}')" if skipped else ""
        info = (
            f"  Tab đích  : {sheet_title}\n"
            f"  Tổng CSV  : {total} dòng  →  Sẽ import: {csv_rows}"
            + skip_line
        )
        tk.Label(self, text=info, font=("Segoe UI", 9),
                 fg="#444444", justify="left").pack(anchor="w", **pad)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=4)

        # ID giao dịch
        id_ok   = analysis["has_id"]
        id_icon = "✓" if id_ok else "✗"
        id_col  = "#1A7A3A" if id_ok else "#CC0000"
        id_msg  = f"  {id_icon}  Cột '{ID_COL}': {'Có — sẽ dùng để kiểm tra trùng' if id_ok else 'KHÔNG CÓ — mọi dòng sẽ được APPEND (không dedup)'}"
        tk.Label(self, text=id_msg, font=("Segoe UI", 9),
                 fg=id_col, justify="left").pack(anchor="w", **pad)

        # Sheet trống
        if analysis["sheet_empty"]:
            tk.Label(self, text="  ℹ  Sheet đang trống — sẽ ghi mới toàn bộ",
                     font=("Segoe UI", 9), fg="#0055AA",
                     justify="left").pack(anchor="w", **pad)

        # Cột khớp
        if analysis["matched"]:
            tk.Label(self,
                     text=f"  ✓  {len(analysis['matched'])} cột khớp với sheet",
                     font=("Segoe UI", 9), fg="#1A7A3A",
                     justify="left").pack(anchor="w", **pad)

        # Cột mới từ CSV
        if analysis["new_cols"]:
            tk.Label(self,
                     text=f"  ⚠  {len(analysis['new_cols'])} cột mới từ CSV (sẽ thêm vào sheet):",
                     font=("Segoe UI", 9), fg="#C47A00",
                     justify="left").pack(anchor="w", padx=16, pady=(6, 0))
            tk.Label(self,
                     text="      " + ", ".join(analysis["new_cols"]),
                     font=("Segoe UI", 9), fg="#C47A00",
                     wraplength=400, justify="left").pack(anchor="w", padx=16)

        # Cột trong sheet nhưng không có trong CSV
        if analysis["missing"]:
            tk.Label(self,
                     text=f"  ✗  {len(analysis['missing'])} cột trong sheet KHÔNG có trong CSV (sẽ để trống):",
                     font=("Segoe UI", 9), fg="#CC0000",
                     justify="left").pack(anchor="w", padx=16, pady=(6, 0))
            tk.Label(self,
                     text="      " + ", ".join(analysis["missing"]),
                     font=("Segoe UI", 9), fg="#CC0000",
                     wraplength=400, justify="left").pack(anchor="w", padx=16)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=8)

        # Nút
        btn_row = tk.Frame(self, bg=self.cget("bg"))
        btn_row.pack(padx=16, pady=(0, 14))
        ttk.Button(btn_row, text="  Tiến hành Import  ",
                   command=self._ok).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Huỷ",
                   command=self._cancel).pack(side="left")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self._cancel())
        self._center(parent)

    def _ok(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()

    def _center(self, parent):
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w)//2}+{py + (ph - h)//2}")


# ── Giao diện chính ────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FB Billing Import → Google Sheet")
        self.geometry("1150x700")
        self.minsize(900, 580)
        self.configure(bg="#F0F2F5")

        self._spreadsheet  = None
        self._worksheets   = []
        self._csv_headers  = []
        self._csv_rows     = []
        self._selected_ws  = None
        self._sheet_headers = []       # headers đang có trong tab được chọn
        self._analysis      = None     # kết quả analyze_structure

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    # ── Style ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",       background="#F0F2F5")
        s.configure("Card.TFrame",  background="#FFFFFF", relief="flat")
        s.configure("TLabel",       background="#F0F2F5", font=("Segoe UI", 10))
        s.configure("Status.TLabel",background="#F0F2F5",
                    font=("Segoe UI", 9), foreground="#555555")
        s.configure("TButton",      font=("Segoe UI", 10), padding=(10, 6))
        s.configure("Import.TButton",
                    font=("Segoe UI", 10, "bold"), padding=(18, 8))
        s.configure("Treeview",
                    font=("Segoe UI", 9), rowheight=24, fieldbackground="#FFFFFF")
        s.configure("Treeview.Heading",
                    font=("Segoe UI", 9, "bold"), background="#E8EBF0")
        s.map("Treeview", background=[("selected", "#4A90D9")])

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = ttk.Frame(self, style="TFrame", padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(2, weight=1)

        # Tiêu đề + status
        hdr = ttk.Frame(root, style="TFrame")
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        tk.Label(hdr, text="FB Billing Import",
                 bg="#F0F2F5", font=("Segoe UI", 14, "bold"),
                 fg="#1A1A2E").pack(side="left")
        self._status_lbl = ttk.Label(hdr, text="Đang kết nối Google Sheet...",
                                     style="Status.TLabel")
        self._status_lbl.pack(side="right")

        # ── Trái: chọn tab ───────────────────────────────────────────────
        left = self._card(root, "1  Chọn tab Google Sheet", width=220)
        left.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        self._tab_list = tk.Listbox(
            left, selectmode="single",
            font=("Segoe UI", 10), activestyle="none",
            selectbackground="#4A90D9", selectforeground="white",
            relief="flat", bd=0,
            highlightthickness=1,
            highlightcolor="#D0D5DD", highlightbackground="#D0D5DD",
        )
        tab_sb = ttk.Scrollbar(left, orient="vertical",
                               command=self._tab_list.yview)
        self._tab_list.configure(yscrollcommand=tab_sb.set)
        self._tab_list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        tab_sb.grid(row=1, column=1, sticky="ns",  pady=(6, 0))
        self._tab_list.bind("<<ListboxSelect>>", self._on_tab_select)

        # ── Phải trên: chọn file CSV ─────────────────────────────────────
        right_top = self._card(root, "2  Chọn file CSV / XLS")
        right_top.grid(row=1, column=1, sticky="nsew", pady=(0, 8))
        right_top.columnconfigure(1, weight=1)

        ttk.Button(right_top, text="Duyệt file...",
                   command=self._browse_csv).grid(
            row=1, column=0, sticky="w", pady=(8, 4), padx=(0, 10))
        self._file_lbl = ttk.Label(right_top, text="Chưa chọn file",
                                   style="Status.TLabel")
        self._file_lbl.grid(row=1, column=1, sticky="w")

        # Thông tin CSV + kiểm tra cấu trúc (Text box 7 dòng)
        self._info_box = tk.Text(
            right_top, height=7, font=("Segoe UI", 9),
            state="disabled", bg="#F8F9FA",
            relief="flat", bd=0,
            highlightthickness=1,
            highlightcolor="#D0D5DD", highlightbackground="#D0D5DD",
        )
        self._info_box.grid(row=2, column=0, columnspan=2,
                            sticky="ew", pady=(6, 0))
        # Tags màu
        self._info_box.tag_config("ok",   foreground="#1A7A3A")
        self._info_box.tag_config("warn", foreground="#C47A00")
        self._info_box.tag_config("err",  foreground="#CC0000")
        self._info_box.tag_config("info", foreground="#0055AA")
        self._info_box.tag_config("dim",  foreground="#777777")

        # ── Phải dưới: preview ───────────────────────────────────────────
        prev = self._card(root, "3  Xem trước dữ liệu CSV")
        prev.grid(row=2, column=1, sticky="nsew")
        prev.rowconfigure(1, weight=1)
        prev.columnconfigure(0, weight=1)

        wrap = ttk.Frame(prev, style="Card.TFrame")
        wrap.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(wrap, show="headings", selectmode="browse")
        vb = ttk.Scrollbar(wrap, orient="vertical",   command=self._tree.yview)
        hb = ttk.Scrollbar(wrap, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vb.set, xscrollcommand=hb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vb.grid(row=0, column=1, sticky="ns")
        hb.grid(row=1, column=0, sticky="ew")

        # ── Thanh dưới ───────────────────────────────────────────────────
        bot = ttk.Frame(root, style="TFrame")
        bot.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self._import_btn = ttk.Button(
            bot, text="  Import vào Sheet  ",
            style="Import.TButton",
            command=self._run_import, state="disabled",
        )
        self._import_btn.pack(side="left")
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=160)
        self._progress.pack(side="left", padx=12)
        self._result_lbl = ttk.Label(bot, text="", style="Status.TLabel")
        self._result_lbl.pack(side="left")

    def _card(self, parent, title: str, width: int = 0) -> ttk.Frame:
        kw = {"width": width} if width else {}
        outer = ttk.Frame(parent, style="Card.TFrame", padding=12, **kw)
        tk.Label(outer, text=title, bg="#FFFFFF",
                 font=("Segoe UI", 10, "bold"),
                 fg="#333333").grid(row=0, column=0, columnspan=2, sticky="w")
        return outer

    # ── Kết nối Google Sheet ─────────────────────────────────────────────────

    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss  = connect_spreadsheet()
            wss = ss.worksheets()
            self._spreadsheet = ss
            self._worksheets  = wss
            self.after(0, self._load_tabs)
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Lỗi kết nối: {e}", error=True))

    def _load_tabs(self):
        self._tab_list.delete(0, "end")
        for ws in self._worksheets:
            self._tab_list.insert("end", ws.title)
        self._set_status(
            f"Đã kết nối: {self._spreadsheet.title}  ({len(self._worksheets)} tab)"
        )

    def _on_tab_select(self, *_):
        sel = self._tab_list.curselection()
        if not sel:
            return
        self._selected_ws    = self._worksheets[sel[0]]
        self._sheet_headers  = []
        self._analysis       = None
        self._refresh_import_btn()
        # Đọc headers của tab vừa chọn (background)
        self._set_status(f"Đang đọc cấu trúc tab '{self._selected_ws.title}'...")
        threading.Thread(target=self._load_sheet_headers_worker, daemon=True).start()

    def _load_sheet_headers_worker(self):
        try:
            first_row = self._selected_ws.row_values(1)
            self.after(0, lambda: self._on_sheet_headers_loaded(first_row))
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Lỗi đọc sheet: {e}", error=True))

    def _on_sheet_headers_loaded(self, headers: list):
        self._sheet_headers = headers
        tab = self._selected_ws.title if self._selected_ws else ""
        n   = len([h for h in headers if h])
        self._set_status(
            f"Tab '{tab}': {n} cột{'  (sheet đang trống)' if n == 0 else ''}"
        )
        if self._csv_headers:
            self._run_analysis()

    # ── Chọn file CSV ────────────────────────────────────────────────────────

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            initialdir=str(Path.home() / "Downloads"),
            title="Chọn file CSV hoặc XLS",
            filetypes=[
                ("CSV / XLS files", "*.csv *.xls"),
                ("CSV files", "*.csv"),
                ("XLS files", "*.xls"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        p = Path(path)
        self._file_lbl.configure(text=p.name)
        self._csv_headers = []
        self._csv_rows    = []
        self._analysis    = None
        self._refresh_import_btn()
        self._write_info("Đang đọc file...", "dim")
        threading.Thread(target=self._load_csv_worker, args=(p,), daemon=True).start()

    def _load_csv_worker(self, path: Path):
        try:
            headers, rows = read_file(path)
            self._csv_headers = headers
            self._csv_rows    = rows
            self.after(0, lambda: self._on_csv_loaded(headers, rows))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Lỗi đọc file", str(e)))

    def _on_csv_loaded(self, headers: list, rows: list):
        self._show_csv_basic_info(headers, rows)
        self._populate_preview(headers, rows)
        self._refresh_import_btn()
        if self._sheet_headers is not None:
            self._run_analysis()

    def _show_csv_basic_info(self, headers: list, rows: list):
        filtered, skipped = filter_by_status(headers, rows)
        lines = [
            ("dim", f"Tổng dòng   : {len(rows)}\n"),
            ("dim", f"Số cột      : {len(headers)}\n"),
        ]
        if STATUS_COL in headers:
            tag = "warn" if skipped > 0 else "ok"
            lines.append((tag,
                f"✓  Sẽ import : {len(filtered)} dòng  "
                f"(bỏ qua {skipped} dòng không phải '{STATUS_ALLOW}')\n"))
        if ID_COL in headers:
            lines.append(("ok",  f"✓  Cột ID    : {ID_COL}\n"))
        else:
            lines.append(("err", f"✗  Cột ID    : '{ID_COL}' KHÔNG CÓ\n"))
        self._write_info_tagged(lines)

    # ── Phân tích cấu trúc ───────────────────────────────────────────────────

    def _run_analysis(self):
        if not self._csv_headers or self._selected_ws is None:
            return
        self._analysis = analyze_structure(self._csv_headers, self._sheet_headers)
        self._show_analysis()
        self._refresh_import_btn()

    def _show_analysis(self):
        a = self._analysis
        if a is None:
            return
        lines = []

        if a["sheet_empty"]:
            lines.append(("info", "\n── Cấu trúc sheet ──────────────────\n"))
            lines.append(("info", "ℹ  Sheet đang trống — sẽ tạo cột từ CSV\n"))
        else:
            lines.append(("dim",  "\n── Cấu trúc so với sheet ──────────\n"))
            if a["matched"]:
                lines.append(("ok",  f"✓  {len(a['matched'])} cột khớp\n"))
            if a["new_cols"]:
                lines.append(("warn",
                    f"⚠  {len(a['new_cols'])} cột mới từ CSV sẽ được thêm:\n"))
                lines.append(("warn", f"   {', '.join(a['new_cols'])}\n"))
            if a["missing"]:
                lines.append(("err",
                    f"✗  {len(a['missing'])} cột trong sheet THIẾU trong CSV (để trống):\n"))
                lines.append(("err",  f"   {', '.join(a['missing'])}\n"))

        self._append_info_tagged(lines)

    # ── Preview ──────────────────────────────────────────────────────────────

    def _populate_preview(self, headers: list, rows: list, limit: int = 200):
        tree = self._tree
        tree.delete(*tree.get_children())
        tree["columns"] = headers
        for h in headers:
            tree.heading(h, text=h)
            tree.column(h, width=max(100, len(h) * 9),
                        minwidth=60, stretch=False)
        tree.tag_configure("alt", background="#F5F7FA")
        for i, row in enumerate(rows[:limit]):
            tree.insert("", "end",
                        values=[row.get(h, "") for h in headers],
                        tags=("alt",) if i % 2 else ())
        if len(rows) > limit:
            tree.insert("", "end",
                        values=[f"... còn {len(rows) - limit} dòng"] + [""] * (len(headers) - 1))

    # ── Import ───────────────────────────────────────────────────────────────

    def _refresh_import_btn(self):
        ready = self._selected_ws is not None and bool(self._csv_rows)
        self._import_btn.configure(state="normal" if ready else "disabled")

    def _run_import(self):
        if not self._selected_ws or not self._csv_rows:
            return

        # Nếu chưa có analysis (sheet headers chưa về) thì chờ
        if self._analysis is None and self._sheet_headers == []:
            messagebox.showinfo("Vui lòng chờ",
                                "Đang tải cấu trúc sheet, thử lại sau vài giây.")
            return

        # Hiện hộp thoại xác nhận
        if self._analysis is None:
            self._analysis = analyze_structure(self._csv_headers, self._sheet_headers)

        filtered_rows, skipped = filter_by_status(self._csv_headers, self._csv_rows)
        dlg = ConfirmDialog(self, self._analysis,
                            len(filtered_rows), skipped,
                            self._selected_ws.title)
        self.wait_window(dlg)
        if not dlg.result:
            return

        self._import_btn.configure(state="disabled")
        self._result_lbl.configure(text="Đang ghi dữ liệu...")
        self._progress.start(12)
        threading.Thread(target=self._import_worker, daemon=True).start()

    def _import_worker(self):
        try:
            filtered_rows, skipped = filter_by_status(self._csv_headers, self._csv_rows)
            stats = upsert(self._selected_ws, self._csv_headers, filtered_rows)
            stats["skipped"] = skipped
            self.after(0, lambda: self._show_result(stats))
        except Exception as e:
            self.after(0, lambda: self._import_error(str(e)))

    def _show_result(self, stats: dict):
        self._progress.stop()
        self._import_btn.configure(state="normal")
        self._result_lbl.configure(
            text=f"✓  +{stats['added']} mới  /  ↺ {stats['updated']} cập nhật"
        )
        skipped   = stats.get("skipped", 0)
        total_csv = stats["total"] + skipped
        skip_line = (f"\nBỏ qua      : {skipped} dòng (không phải '{STATUS_ALLOW}')"
                     if skipped else "")
        messagebox.showinfo(
            "Import thành công",
            f"Tab đã ghi   : {stats['tab']}\n"
            f"Tổng CSV     : {total_csv} dòng\n"
            f"Đã import    : {stats['total']} dòng\n"
            f"Cập nhật     : {stats['updated']} dòng (trùng ID)\n"
            f"Thêm mới     : {stats['added']} dòng"
            + skip_line,
        )

    def _import_error(self, msg: str):
        self._progress.stop()
        self._import_btn.configure(state="normal")
        self._result_lbl.configure(text="Lỗi!")
        messagebox.showerror("Lỗi khi import", msg)

    # ── Text info helpers ─────────────────────────────────────────────────────

    def _write_info(self, text: str, tag: str = "dim"):
        self._info_box.configure(state="normal")
        self._info_box.delete("1.0", "end")
        self._info_box.insert("end", text, tag)
        self._info_box.configure(state="disabled")

    def _write_info_tagged(self, lines: list):
        self._info_box.configure(state="normal")
        self._info_box.delete("1.0", "end")
        for tag, text in lines:
            self._info_box.insert("end", text, tag)
        self._info_box.configure(state="disabled")

    def _append_info_tagged(self, lines: list):
        self._info_box.configure(state="normal")
        for tag, text in lines:
            self._info_box.insert("end", text, tag)
        self._info_box.configure(state="disabled")

    # ── Tiện ích ─────────────────────────────────────────────────────────────

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text,
            foreground="#CC0000" if error else "#555555",
        )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
