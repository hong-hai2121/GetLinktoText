"""
Tạo bảng tổng hợp:
  - Cột A : danh sách nhãn hàng (ngân sách, báo cáo, dự quỹ...)
  - Hàng 1 từ cột B : tên tab của từng tài khoản được chọn

GUI cho phép xem + xóa bớt tab trước khi chạy.
Chạy: python consolidate.py
"""

import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    sys.exit("Cần tkinter (có sẵn trong Python chuẩn trên Windows).")

import gspread
from google.oauth2.service_account import Credentials

from get_campaigns import (
    SPREADSHEET_ID, SCOPES,
    get_selected_accounts, sanitize_sheet_name,
)

BASE_DIR = Path(__file__).parent
OUTPUT_SHEET_TITLE = f"Tổng Hợp T{datetime.now().month}"

# Hàng "1.1 Ngân sách được duyệt": mỗi cột tài khoản = tổng cột "số tiền"
# (cột C, từ C2 trở xuống) của trang tính có tên = tên tab ở hàng 1 cột đó.
BUDGET_LABEL = "1.1 Ngân sách được duyệt"
SOURCE_AMOUNT_COL = "C"
DEBT_LABEL = "1.2 Số tiền nợ"
ACTUAL_SPEND_LABEL = "1.3 Ngân sách thực tế Camp đã tiêu"
CP_TOTAL_LABEL = "CP Tổng"
LECH_LABEL = "Lệch"
NGAY_DAU_LABEL = "Ngày đầu thanh toán"
TIEN_NGAY_DAU_LABEL = "Tiền Ngày đầu nạp"
DON_LABEL = "Đơn"
DOANH_SO_LABEL = "Doanh Số"
TY_LE_CP_LABEL = "Tỷ lệ CP"

# Regex dùng trong công thức Google Sheets để bỏ nhóm ngoặc cuối (ID TK)
_STRIP_LAST_ID = '"\\s*\\([^()]*\\)\\s*$"'
TKQC_API_SHEET = "TKQC API"
TKQC_API_ID_COL = "A"
TKQC_API_BALANCE_COL = "N"
TKQC_API_BALANCE_INDEX = 14

# ── Danh sách nhãn hàng cố định ở cột A ───────────────────────────────────────
ROW_LABELS = [
    "1. NGÂN SÁCH - TẠM ỨNG",
    "1.1 Ngân sách được duyệt",
    "1.2 Số tiền nợ",
    "1.3 Ngân sách thực tế Camp đã tiêu",
    "Lệch",
    "Ngày đầu thanh toán",
    "Tiền Ngày đầu nạp",
    "Lần 1 tuần 2 T5",
    "Lần 1 tuần 3 T5",
    "Lần 1 tuần 4 T5",
    "Lần 1 tuần 5 T5",
    "1.3 Ngân sách còn lại",
    "1.4 Số tiền chưa hoàn tháng 3",
    "1.5 Số tiền đã ứng + Hold hoàn về",
    "1.6 Chuyển tiền nội bộ team",
    "2. BÁO CÁO DOANH SỐ",
    "Ngày vào",
    "CP bị hold",
    "CP Tổng",
    "CP Thuế + Ngân hàng",
    "Đơn",
    "Doanh Số",
    "Tỷ lệ CP",
    "3. DỰ QUỸ - HOÀN ỨNG",
    "3.1 Đã Hoàn ứng",
    "Hoàn Tháng 3",
    "Tuần 1 T4",
    "Tuần 2 T4",
    "Tuần 3 T4",
    "Tuần 4 T4",
    "Chốt tháng",
    "3.2 Quỹ Ads - NS đã tạm ứng - Chi phí",
    "3.2.1 Số dư TK ngân hàng cá nhân chạy ads",
    "3.2.2 Số dư TK công ty",
    "3.2.3 Số tiền bị khoanh giữ",
    "3.3 Số dư quỹ xin giữ lại TK",
    "3.4 Số hoàn về = 3.2 - 3.2.2-3.3",
]

SECTION_LABELS = {
    "1. NGÂN SÁCH - TẠM ỨNG",
    "2. BÁO CÁO DOANH SỐ",
    "3. DỰ QUỸ - HOÀN ỨNG",
    "3.1 Đã Hoàn ứng",
    "3.2 Quỹ Ads - NS đã tạm ứng - Chi phí",
}


# ── Google Sheets helpers ──────────────────────────────────────────────────────

def connect_spreadsheet(credentials_file: str = "service_account.json"):
    creds = Credentials.from_service_account_file(
        str(BASE_DIR / credentials_file), scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def _find_tab_title(all_ws: dict, acc_name: str, acc_id: str) -> str | None:
    """
    Tìm tab khớp định dạng '{Tên TK} ({ID TK})',
    ví dụ: 'Quang Anh-2 (+7 08/05/2026) (805233045298942)'.

    KHÔNG lấy các tab chỉ có tên không kèm ID.
    Lưu ý: tên tab thật có thể chứa '/' (vd ngày tháng) nên KHÔNG sanitize
    chuỗi cần so — so trực tiếp với tên tab thật trước, sau đó mới thử bản
    đã sanitize (phòng tab do script tự tạo đã bị bỏ ký tự đặc biệt).
    """
    acc_id = (acc_id or "").strip()
    if not acc_id:
        return None

    # 1. Khớp chính xác (nhanh nhất)
    raw = f"{acc_name} ({acc_id})"
    if raw in all_ws:
        return raw

    sanitized = sanitize_sheet_name(raw)
    if sanitized in all_ws:
        return sanitized

    # 2. Neo theo (ID) — ID duy nhất nên không nhầm; bỏ qua khác biệt
    #    khoảng trắng / ký tự ở phần tên. Vẫn yêu cầu tab có kèm ID.
    needle = f"({acc_id})"
    for title in all_ws:
        if needle in title:
            return title

    return None


def col_letter(n: int) -> str:
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def build_summary_sheet(spreadsheet, tab_titles: list[str],
                        output_title: str = OUTPUT_SHEET_TITLE) -> dict:
    """Ghi sheet tổng hợp với danh sách tab_titles đã được người dùng xác nhận."""
    ncols = 1 + len(tab_titles)

    header_row = [""] + tab_titles

    # Tài khoản bắt đầu từ cột B → vị trí cột 1-based của tab thứ i = i + 2.
    def _budget_row() -> list:
        cells = []
        for i in range(len(tab_titles)):
            cl  = col_letter(i + 2)
            col = SOURCE_AMOUNT_COL
            # =SUM(ARRAYFORMULA(IFERROR(VALUE(INDIRECT("'"&B$1&"'!C2:C"));0)))
            # VALUE: ép ô dạng text → số; IFERROR(...;0): ô trống/không hợp lệ = 0.
            cells.append(
                '=SUM(ARRAYFORMULA(IFERROR(VALUE(INDIRECT("\'"&'
                + cl + '$1&"\'!' + col + '2:' + col + '"));0)))'
            )
        return cells

    def _debt_row() -> list:
        cells = []
        lookup_range = f"'{TKQC_API_SHEET}'!{TKQC_API_ID_COL}:{TKQC_API_BALANCE_COL}"
        for i in range(len(tab_titles)):
            cl = col_letter(i + 2)
            cells.append(
                f'=IFERROR(VLOOKUP(REGEXEXTRACT({cl}$1;"\\(([^()]*)\\)\\s*$");'
                f'{lookup_range};{TKQC_API_BALANCE_INDEX};FALSE);"")'
            )
        return cells

    def _sheet_name(cl: str) -> str:
        # Header hàng 1 → bỏ nhóm ngoặc cuối (ID TK) rồi bỏ dấu "/"
        # Ví dụ: "Quang Huy-2 ( +8 08/05/2026) (755854116909247)" → "Quang Huy-2 ( +8 08052026)"
        regex_part = 'REGEXREPLACE(' + cl + '$1;' + _STRIP_LAST_ID + ';"")'
        return 'SUBSTITUTE(' + regex_part + ';"/";"")'

    def _indirect(cl: str, rng: str) -> str:
        return 'INDIRECT("\'"&' + _sheet_name(cl) + '&"\'' + '!' + rng + '")'

    def _actual_spend_row() -> list:
        cells = []
        for i in range(len(tab_titles)):
            cl = col_letter(i + 2)
            cells.append(
                '=SUMIF('
                + _indirect(cl, 'B2:B') + ';'
                '"Campaign";'
                + _indirect(cl, 'X2:X')
                + ')'
            )
        return cells

    def _doanh_so_row() -> list:
        cells = []
        for i in range(len(tab_titles)):
            cl = col_letter(i + 2)
            cells.append(
                '=SUMPRODUCT('
                '(' + _indirect(cl, 'B2:B') + '="Campaign")'
                '*VALUE(SUBSTITUTE(' + _indirect(cl, 'T2:T') + ';"\'";"")'
                '))'
            )
        return cells

    def _don_row() -> list:
        cells = []
        for i in range(len(tab_titles)):
            cl = col_letter(i + 2)
            cells.append(
                '=SUMPRODUCT('
                '(' + _indirect(cl, 'B2:B') + '="Campaign")'
                '*VALUE(SUBSTITUTE(' + _indirect(cl, 'V2:V') + ';"\'";"")'
                '))'
            )
        return cells

    def _ty_le_cp_row() -> list:
        return [f'={col_letter(i + 2)}19/{col_letter(i + 2)}22' for i in range(len(tab_titles))]

    def _cp_total_row() -> list:
        # Hàng 19 = hàng 3 + hàng 4 (1.1 Ngân sách được duyệt + 1.2 Số tiền nợ)
        return [f'={col_letter(i + 2)}3+{col_letter(i + 2)}4' for i in range(len(tab_titles))]

    def _lech_row() -> list:
        return [f'={col_letter(i+2)}3+{col_letter(i+2)}4-{col_letter(i+2)}5'
                for i in range(len(tab_titles))]

    def _ngay_dau_row() -> list:
        def make(cl):
            sq  = "'"
            ind = lambda rng: f'INDIRECT("{sq}"&{cl}$1&"{sq}!{rng}")'
            return (
                f'=LET('
                f'ngay;ARRAYFORMULA(IFERROR(DATE('
                f'VALUE(REGEXEXTRACT({ind("B2:B")};",\\s*(\\d{{4}})"));'
                f'VALUE(REGEXEXTRACT({ind("B2:B")};"Tháng\\s*(\\d+)"));'
                f'VALUE(REGEXEXTRACT({ind("B2:B")};"^{sq}?(\\d+)")));'
                f'""));'
                f'TEXT(MIN(FILTER(ngay;ngay<>""));"dd/mm/yyyy")'
                f')'
            )
        return [make(col_letter(i + 2)) for i in range(len(tab_titles))]

    def _tien_ngay_dau_row() -> list:
        def make(cl):
            sq  = "'"
            ind = lambda rng: f'INDIRECT("{sq}"&{cl}$1&"{sq}!{rng}")'
            return (
                f'=LET('
                f'ngay;ARRAYFORMULA(IFERROR(DATE('
                f'VALUE(REGEXEXTRACT({ind("B2:B")};",\\s*(\\d{{4}})"));'
                f'VALUE(REGEXEXTRACT({ind("B2:B")};"Tháng\\s*(\\d+)"));'
                f'VALUE(REGEXEXTRACT({ind("B2:B")};"^{sq}?(\\d+)")));'
                f'""));'
                f'tien;ARRAYFORMULA(IFERROR(VALUE(REGEXREPLACE(TO_TEXT({ind("C2:C")});"[^\\d]";""));0));'
                f'ngaymin;MIN(FILTER(ngay;ngay<>""));'
                f'SUM(FILTER(tien;ngay=ngaymin))'
                f')'
            )
        return [make(col_letter(i + 2)) for i in range(len(tab_titles))]

    data_rows = []
    for label in ROW_LABELS:
        if label == BUDGET_LABEL:
            data_rows.append([label] + _budget_row())
        elif label == DEBT_LABEL:
            data_rows.append([label] + _debt_row())
        elif label == ACTUAL_SPEND_LABEL:
            data_rows.append([label] + _actual_spend_row())
        elif label == CP_TOTAL_LABEL:
            data_rows.append([label] + _cp_total_row())
        elif label == LECH_LABEL:
            data_rows.append([label] + _lech_row())
        elif label == NGAY_DAU_LABEL:
            data_rows.append([label] + _ngay_dau_row())
        elif label == TIEN_NGAY_DAU_LABEL:
            data_rows.append([label] + _tien_ngay_dau_row())
        elif label == DON_LABEL:
            data_rows.append([label] + _don_row())
        elif label == DOANH_SO_LABEL:
            data_rows.append([label] + _doanh_so_row())
        elif label == TY_LE_CP_LABEL:
            data_rows.append([label] + _ty_le_cp_row())
        else:
            data_rows.append([label] + [""] * len(tab_titles))

    all_data = [header_row] + data_rows

    need_rows = max(200, len(all_data) + 10)
    need_cols = max(30, ncols + 2)

    all_ws = {ws.title: ws for ws in spreadsheet.worksheets()}

    if output_title in all_ws:
        # Đã có sheet → dùng lại, ghi đè. KHÔNG tạo tab trùng tên.
        out_ws = all_ws[output_title]
        created = False
        # Nới rộng nếu tab cũ thiếu hàng/cột để chứa đủ dữ liệu mới.
        if out_ws.row_count < need_rows or out_ws.col_count < need_cols:
            out_ws.resize(rows=max(out_ws.row_count, need_rows),
                          cols=max(out_ws.col_count, need_cols))
    else:
        out_ws = spreadsheet.add_worksheet(
            title=output_title, rows=need_rows, cols=need_cols)
        created = True

    out_ws.clear()
    out_ws.update("A1", all_data, value_input_option="USER_ENTERED")
    _apply_format(out_ws, spreadsheet)

    return {
        "accounts":     len(tab_titles),
        "output_title": output_title,
        "created":      created,
    }


def _apply_format(out_ws, spreadsheet):
    sheet_id = out_ws.id
    requests = [
        # Freeze hàng 1 + cột A
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }
        },
        # In đậm hàng header
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
    ]
    for i, label in enumerate(ROW_LABELS):
        if label in SECTION_LABELS:
            row_idx = i + 1
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                        "startColumnIndex": 0,   "endColumnIndex": 1,
                    },
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            })
    spreadsheet.batch_update({"requests": requests})


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    BG        = "#EDF1F7"
    CARD      = "#FFFFFF"
    BORDER    = "#DCE3EC"
    ACCENT    = "#2D6CDF"
    ACCENT_HV = "#1F5AC4"
    ACCENT_DIS= "#AEC4EC"
    TEXT      = "#1E293B"
    MUTED     = "#64748B"

    def __init__(self):
        super().__init__()
        self.title("Tổng Hợp – Chọn Tab Sheet")
        self.geometry("680x520")
        self.minsize(520, 380)
        self.configure(bg=self.BG)
        self.resizable(True, True)

        self._spreadsheet = None
        # [{"iid": str, "tab_title": str, "acc_name": str, "acc_id": str, "found": bool}]
        self._items: list[dict] = []

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",      background=self.BG)
        s.configure("TLabel",      background=self.BG,
                    font=("Segoe UI", 10), foreground=self.TEXT)
        s.configure("TButton",     font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background="#E2E8F0", foreground="#334155",
                    bordercolor="#B9C4D4", relief="flat", borderwidth=1)
        s.map("TButton",
              background=[("active", "#CBD5E1"), ("disabled", "#F1F5F9")],
              foreground=[("disabled", "#B0B8C4")])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(22, 9), background=self.ACCENT,
                    foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#EEF2FB")])
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=28,
                    background=self.CARD, fieldbackground=self.CARD,
                    foreground=self.TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background="#F1F5F9", foreground="#475569",
                    relief="flat", padding=(8, 6))
        s.map("Treeview",
              background=[("selected", "#DBE7FB")],
              foreground=[("selected", self.TEXT)])
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor="#E2E8F0", borderwidth=0, thickness=6)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        # Header
        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 12))
        tk.Label(hdr, text="Tổng Hợp Sheet", bg=self.BG,
                 font=("Segoe UI Semibold", 15), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        # Hướng dẫn
        tk.Label(outer,
                 text="Danh sách tab tìm được từ TKQC API (Chọn Lấy Camp = TRUE).\n"
                      "Chọn rồi nhấn 'Xóa đã chọn' để loại bỏ tab không muốn, sau đó nhấn OK.",
                 bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        # Treeview card
        card = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = ("tab", "acc_name", "acc_id", "status")
        self._tree = ttk.Treeview(card, columns=cols, show="headings",
                                  selectmode="extended")
        self._tree.heading("tab",      text="Tên Tab Sheet",   anchor="w")
        self._tree.heading("acc_name", text="Tên Tài Khoản",   anchor="w")
        self._tree.heading("acc_id",   text="ID Tài Khoản",    anchor="w")
        self._tree.heading("status",   text="Trạng Thái",      anchor="center")
        self._tree.column("tab",      width=220, stretch=True,  minwidth=120)
        self._tree.column("acc_name", width=160, stretch=True,  minwidth=100)
        self._tree.column("acc_id",   width=160, stretch=False, minwidth=100)
        self._tree.column("status",   width=90,  stretch=False, anchor="center")

        vsb = ttk.Scrollbar(card, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(card, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("found",   foreground="#15803D")
        self._tree.tag_configure("missing", foreground="#DC2626")
        self._tree.tag_configure("odd",     background="#F8FAFC")

        # Double-click → copy tên tab; chuột phải → menu copy
        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<Button-3>", self._on_right_click)

        self._ctx_menu = tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="Copy tên tab",
                                   command=lambda: self._copy_column("tab"))
        self._ctx_menu.add_command(label="Copy tên tài khoản",
                                   command=lambda: self._copy_column("acc_name"))
        self._ctx_menu.add_command(label="Copy ID tài khoản",
                                   command=lambda: self._copy_column("acc_id"))
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="Copy cả dòng",
                                   command=self._copy_row)

        # Thanh dưới
        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(12, 0))

        ttk.Button(bot, text="Xóa đã chọn",
                   command=self._remove_selected).pack(side="left")
        ttk.Button(bot, text="Chọn tất cả",
                   command=self._select_all).pack(side="left", padx=6)
        ttk.Button(bot, text="Copy tên tab",
                   command=lambda: self._copy_column("tab")).pack(side="left", padx=(0, 6))

        self._count_lbl = tk.Label(bot, text="", bg=self.BG,
                                   font=("Segoe UI", 9), fg=self.MUTED)
        self._count_lbl.pack(side="left", padx=8)

        ttk.Button(bot, text="Huỷ",
                   command=self.destroy).pack(side="right")
        self._ok_btn = ttk.Button(bot, text="OK – Tạo Sheet",
                                  style="Accent.TButton",
                                  command=self._run, state="disabled")
        self._ok_btn.pack(side="right", padx=(0, 8))

        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=120)
        self._progress.pack(side="right", padx=(0, 10))

    # ── Kết nối + load tab ────────────────────────────────────────────────────

    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss  = connect_spreadsheet()
            sel = get_selected_accounts(ss)
            all_ws = {ws.title: ws for ws in ss.worksheets()}

            items = []
            for acc in sel:
                title = _find_tab_title(all_ws, acc["name"], acc["id"])
                items.append({
                    "tab_title": title or f"{acc['name']} ({acc['id']})",
                    "acc_name":  acc["name"],
                    "acc_id":    acc["id"],
                    "found":     title is not None,
                })

            self._spreadsheet = ss
            self.after(0, lambda: self._load_items(items,
                f"Kết nối OK · {ss.title} · {len(sel)} tài khoản"))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi: {e}", error=True))

    def _load_items(self, items: list[dict], status_text: str):
        self._set_status(status_text)
        self._items = []
        for i, item in enumerate(items):
            tag = "found" if item["found"] else "missing"
            if i % 2 != 0:
                tag = ("odd", tag)
            else:
                tag = (tag,)
            iid = self._tree.insert(
                "", "end",
                values=(
                    item["tab_title"],
                    item["acc_name"],
                    item["acc_id"],
                    "✓ Tìm thấy" if item["found"] else "✗ Không có",
                ),
                tags=tag,
            )
            item["iid"] = iid
            self._items.append(item)

        self._refresh_count()
        if any(i["found"] for i in self._items):
            self._ok_btn.configure(state="normal")

    # ── Thao tác danh sách ────────────────────────────────────────────────────

    def _remove_selected(self):
        for iid in list(self._tree.selection()):
            self._tree.delete(iid)
            self._items = [i for i in self._items if i["iid"] != iid]
        self._refresh_count()
        has_found = any(i["found"] for i in self._items)
        self._ok_btn.configure(state="normal" if has_found else "disabled")

    def _select_all(self):
        self._tree.selection_set(self._tree.get_children())

    # ── Copy clipboard ────────────────────────────────────────────────────────

    _COL_INDEX = {"tab": 0, "acc_name": 1, "acc_id": 2, "status": 3}

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status(f"Đã copy: {text}")

    def _copy_column(self, col: str):
        """Copy giá trị 1 cột của (các) dòng đang chọn, mỗi dòng 1 hàng."""
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._COL_INDEX[col]
        vals = [self._tree.item(iid, "values")[idx] for iid in sel]
        self._copy_to_clipboard("\n".join(vals))

    def _copy_row(self):
        """Copy toàn bộ dòng đang chọn (các cột nối bằng tab)."""
        sel = self._tree.selection()
        if not sel:
            return
        lines = ["\t".join(str(v) for v in self._tree.item(iid, "values")) for iid in sel]
        self._copy_to_clipboard("\n".join(lines))

    def _on_double_click(self, event):
        iid = self._tree.identify_row(event.y)
        if iid:
            self._tree.selection_set(iid)
            self._copy_column("tab")

    def _on_right_click(self, event):
        iid = self._tree.identify_row(event.y)
        if iid and iid not in self._tree.selection():
            self._tree.selection_set(iid)
        if self._tree.selection():
            self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _refresh_count(self):
        total  = len(self._items)
        found  = sum(1 for i in self._items if i["found"])
        self._count_lbl.configure(
            text=f"{found}/{total} tab hợp lệ" if total else "Danh sách trống"
        )

    # ── OK → chạy ─────────────────────────────────────────────────────────────

    def _run(self):
        tab_titles = [i["tab_title"] for i in self._items if i["found"]]
        if not tab_titles:
            messagebox.showwarning("Không có tab", "Không còn tab hợp lệ nào để tổng hợp.")
            return

        msg = (f"Sẽ tạo sheet '{OUTPUT_SHEET_TITLE}' với {len(tab_titles)} tab:\n\n"
               + "\n".join(f"  • {t}" for t in tab_titles))
        if not messagebox.askyesno("Xác nhận", msg):
            return

        self._ok_btn.configure(state="disabled")
        self._progress.start(12)
        self._set_status("Đang tạo sheet...")
        threading.Thread(
            target=self._run_worker, args=(list(tab_titles),), daemon=True
        ).start()

    def _run_worker(self, tab_titles: list[str]):
        try:
            result = build_summary_sheet(self._spreadsheet, tab_titles)
            self.after(0, lambda: self._done(result))
        except Exception as e:
            self.after(0, lambda e=e: self._error(str(e)))

    def _done(self, result: dict):
        self._progress.stop()
        self._ok_btn.configure(state="normal")
        self._set_status(
            f"✓ Hoàn thành: {result['accounts']} tab → sheet '{result['output_title']}'"
        )
        verb = "Đã tạo" if result.get("created") else "Đã ghi đè"
        messagebox.showinfo(
            "Hoàn thành",
            f"{verb} sheet '{result['output_title']}' với {result['accounts']} tài khoản."
        )

    def _error(self, msg: str):
        self._progress.stop()
        self._ok_btn.configure(state="normal")
        self._set_status(f"✗ Lỗi: {msg}", error=True)
        messagebox.showerror("Lỗi", msg)

    # ── Tiện ích ──────────────────────────────────────────────────────────────

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, foreground="#CC0000" if error else self.MUTED
        )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
