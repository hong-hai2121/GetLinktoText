import gspread
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from pathlib import Path

from config import ACCESS_TOKEN, SPREADSHEET_ID
from fb_api import graph_paginate, api_summary, set_call_delay

BASE_DIR = Path(__file__).parent
SHEET_NAME = "TKQC API"
FB_API_VERSION = "v20.0"
CALL_DELAY_SECONDS = 2.0  # giãn cách gọi Graph API (tránh rate limit)

# Màu nền hàng theo cột "Chọn Lấy Camp"
COLOR_SELECTED = {"red": 0.85, "green": 0.93, "blue": 0.83}  # TRUE → xanh nhạt
COLOR_DEFAULT = {"red": 1.0, "green": 1.0, "blue": 1.0}       # FALSE → trắng

ACCOUNT_STATUS_MAP = {
    1: "Đang hoạt động",
2: "Đã tắt",
    3: "Chưa thanh toán",
    7: "Đang xét duyệt rủi ro",
    9: "Trong thời gian ân hạn",
    100: "Chờ đóng",
    101: "Đã đóng",
    201: "Bất kỳ (đang hoạt động)",
    202: "Bất kỳ (đã đóng)",
}

ZERO_DECIMAL_CURRENCIES = {
    "VND", "JPY", "KRW", "BIF", "CLP", "GNF", "ISK", "KMF",
    "MGA", "PYG", "RWF", "UGX", "VUV", "XAF", "XOF", "XPF",
}

HEADERS = [
    "ID Tài Khoản",
    "Tên Tài Khoản",
    "ID Business",
    "Tên Business",
    "Trạng Thái",
    "Tiền Tệ",
    "Múi Giờ",
    "Đã Chi",
    "Số Dư",
    "Số Dư Trước",
    "Phương Thức Thanh Toán",
    "Chọn Lấy Camp",   # TRUE = sẽ được get_campaigns.py xử lý
    "Cập Nhật Lúc",
    "Số Dư Số",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def connect_sheet(credentials_file: str = "service_account.json"):
    credentials_path = BASE_DIR / credentials_file
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        return spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        # Link Sheet mới mỗi tháng → chưa có tab "TKQC API" thì tự tạo.
        print(f"Chưa có sheet '{SHEET_NAME}' — tự tạo mới.")
        return spreadsheet.add_worksheet(
            title=SHEET_NAME, rows=1000, cols=len(HEADERS)
        )


def read_existing_data(worksheet) -> tuple[dict[str, bool], dict[str, str], dict[str, str], dict[str, str]]:
    """Đọc sheet hiện tại, trả về:
    - {account_id: chọn_lấy_camp}
    - {account_id: số_dư}         ← để tính Số Dư Trước khi > 24h
    - {account_id: số_dư_trước}   ← giữ nguyên khi < 24h
    - {account_id: cập_nhật_lúc}  ← để kiểm tra 24h
    """
    try:
        all_values = worksheet.get_all_values()
    except Exception:
        return {}, {}, {}, {}

    if len(all_values) < 2:
        return {}, {}, {}, {}

    header = all_values[0]
    try:
        id_col = header.index("ID Tài Khoản")
        chon_col = header.index("Chọn Lấy Camp")
    except ValueError:
        return {}, {}, {}, {}

    so_du_col        = header.index("Số Dư")        if "Số Dư"        in header else -1
    so_du_truoc_col  = header.index("Số Dư Trước")  if "Số Dư Trước"  in header else -1
    cap_nhat_col     = header.index("Cập Nhật Lúc") if "Cập Nhật Lúc" in header else -1

    selections, prev_balances, stored_prev_balances, last_updates = {}, {}, {}, {}
    for row in all_values[1:]:
        acc_id = row[id_col].strip().removeprefix("act_") if id_col < len(row) else ""
        if not acc_id:
            continue
        chon_val = row[chon_col].strip() if chon_col < len(row) else ""
        selections[acc_id] = chon_val.upper() in ("TRUE", "ĐÚNG", "1", "X", "✓")
        if so_du_col >= 0:
            prev_balances[acc_id] = row[so_du_col].strip() if so_du_col < len(row) else ""
        if so_du_truoc_col >= 0:
            stored_prev_balances[acc_id] = row[so_du_truoc_col].strip() if so_du_truoc_col < len(row) else ""
        if cap_nhat_col >= 0:
            last_updates[acc_id] = row[cap_nhat_col].strip() if cap_nhat_col < len(row) else ""
    return selections, prev_balances, stored_prev_balances, last_updates


def fetch_ad_accounts(access_token: str) -> list[dict]:
    # Không lấy field 'business' vì cần quyền business_management (token không có).
    # Cột 'ID Business' / 'Tên Business' sẽ để trống.
    fields = "id,name,account_status,currency,timezone_name,amount_spent,balance,funding_source_details"
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me/adaccounts"
    params = {"fields": fields, "access_token": access_token, "limit": 500}
    return graph_paginate(url, params, label="me/adaccounts")


def format_money(amount_raw, currency: str) -> str:
    try:
        value = float(amount_raw)
    except (ValueError, TypeError):
        return "0"
    currency = currency.upper()
    if currency not in ZERO_DECIMAL_CURRENCIES:
        value = value / 100
    formatted = f"{int(round(value)):,}".replace(",", ".")
    return f"{formatted} ₫" if currency == "VND" else f"{formatted} {currency}"


def money_number(amount_raw, currency: str):
    try:
        value = float(amount_raw)
    except (ValueError, TypeError):
        return 0
    if currency.upper() not in ZERO_DECIMAL_CURRENCIES:
        value = value / 100
    return int(round(value)) if value.is_integer() else round(value, 2)


def _format_id_columns_as_text(worksheet):
    """Ep cac cot ID (bat dau bang 'ID ') sang dinh dang TEXT de Sheets
    khong dien giai chuoi ID 16 chu so thanh so roi lam tron."""
    id_indices = [i for i, h in enumerate(HEADERS) if h.startswith("ID ")]
    requests = []
    for ci in id_indices:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": worksheet.id,
                    "startColumnIndex": ci,
                    "endColumnIndex": ci + 1,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        })
    if requests:
        worksheet.spreadsheet.batch_update({"requests": requests})


def write_to_sheet(worksheet, accounts: list[dict], selections: dict[str, bool],
                   prev_balances: dict[str, str], stored_prev_balances: dict[str, str],
                   last_updates: dict[str, str]):
    def sort_key(acc):
        biz = acc.get("business") or {}
        return (biz.get("name", "") or "￿", acc.get("name", ""))

    sorted_accounts = sorted(accounts, key=sort_key)

    now = datetime.now()
    now_str = now.strftime("%d/%m/%Y %H:%M:%S")
    cutoff = now - timedelta(hours=24)

    rows = []
    for acc in sorted_accounts:
        currency = acc.get("currency", "")
        status_code = acc.get("account_status", 0)
        biz = acc.get("business") or {}
        acc_id = acc.get("id", "").removeprefix("act_")
        current_balance = format_money(acc.get("balance", "0"), currency)
        current_balance_number = money_number(acc.get("balance", "0"), currency)
        prev_balance = prev_balances.get(acc_id, "")
        balance_changed = prev_balance != "" and current_balance != prev_balance
        chon = "TRUE" if (selections.get(acc_id, False) or balance_changed) else "FALSE"
        funding = acc.get("funding_source_details") or {}
        payment_method = funding.get("display_string", "")

        # Chỉ cập nhật Số Dư Trước khi lần cập nhật cuối > 24h (hoặc chưa có)
        last_update_str = last_updates.get(acc_id, "")
        within_24h = False
        if last_update_str:
            try:
                last_update_dt = datetime.strptime(last_update_str, "%d/%m/%Y %H:%M:%S")
                within_24h = last_update_dt >= cutoff
            except ValueError:
                pass

        if within_24h:
            so_du_truoc = stored_prev_balances.get(acc_id, prev_balance)
        else:
            so_du_truoc = prev_balance

        rows.append([
            acc_id,
            acc.get("name", ""),
            biz.get("id", ""),
            biz.get("name", ""),
            ACCOUNT_STATUS_MAP.get(status_code, str(status_code)),
            currency,
            acc.get("timezone_name", ""),
            format_money(acc.get("amount_spent", "0"), currency),
            format_money(acc.get("balance", "0"), currency),
            so_du_truoc,
            payment_method,
            chon,
            now_str,
            current_balance_number,
        ])

    col_letter = chr(64 + len(HEADERS))
    worksheet.update(values=[HEADERS], range_name="A1")

    last_row = worksheet.row_count
    if last_row >= 2:
        worksheet.batch_clear([f"A2:{col_letter}{last_row}"])

    if rows:
        # RAW: giu nguyen chuoi ID, khong de Sheets dien giai thanh so
        # roi lam tron 16 chu so (4197654223887206 -> 4197654223887200).
        worksheet.update(values=rows, range_name="A2", value_input_option="RAW")

        # Ep cot ID sang TEXT de khong bi lam tron.
        _format_id_columns_as_text(worksheet)

        # Tô màu nền hàng theo cột "Chọn Lấy Camp": TRUE = xanh nhạt, FALSE = trắng
        chon_col = HEADERS.index("Chọn Lấy Camp")
        formats = []
        for i, row in enumerate(rows):
            sheet_row = i + 2  # dữ liệu bắt đầu từ hàng 2
            is_selected = row[chon_col] == "TRUE"
            formats.append({
                "range": f"A{sheet_row}:{col_letter}{sheet_row}",
                "format": {"backgroundColor": COLOR_SELECTED if is_selected else COLOR_DEFAULT},
            })
        worksheet.batch_format(formats)

        print(f"Đã ghi {len(rows)} tài khoản quảng cáo vào sheet '{SHEET_NAME}' (từ A1).")
    else:
        print("Không có tài khoản quảng cáo nào.")


def save_json(accounts: list[dict]):
    out_path = BASE_DIR / "main.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)
    print(f"Đã lưu JSON → {out_path}")


def create_snapshot_sheet(spreadsheet):
    """Tạo sheet mới tên 'HH:MM TM' (ví dụ '11:54 T5') là bản sao TKQC API."""
    now = datetime.now()
    title = f"{now.strftime('%H:%M')} T{now.month}"
    src = spreadsheet.worksheet(SHEET_NAME)
    body = {"requests": [{"duplicateSheet": {
        "sourceSheetId": src.id,
        "insertSheetIndex": len(spreadsheet.worksheets()),
        "newSheetName": title,
    }}]}
    spreadsheet.batch_update(body)
    print(f"  → Đã tạo sheet snapshot '{title}'.")
    return title


def main(cuoi_thang: bool = False):
    print("Kết nối Google Sheets...")
    ws = connect_sheet()
    spreadsheet = ws.spreadsheet

    print("Đọc dữ liệu hiện tại (giữ lại Chọn Lấy Camp + Số Dư Trước)...")
    selections, prev_balances, stored_prev_balances, last_updates = read_existing_data(ws)
    selected_count = sum(1 for v in selections.values() if v)
    print(f"  → {selected_count} tài khoản đang được chọn.")

    print("Lấy danh sách tài khoản quảng cáo từ Facebook Graph API...")
    set_call_delay(CALL_DELAY_SECONDS)
    accounts = fetch_ad_accounts(ACCESS_TOKEN)
    print(f"Tìm thấy {len(accounts)} tài khoản quảng cáo.")

    save_json(accounts)

    print(f"Ghi dữ liệu vào sheet '{SHEET_NAME}'...")
    write_to_sheet(ws, accounts, selections, prev_balances, stored_prev_balances, last_updates)

    if cuoi_thang:
        print("Cuối tháng — tạo sheet snapshot...")
        create_snapshot_sheet(spreadsheet)

    api_summary()
    print("Hoàn thành!")


# ── GUI ────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    BG     = "#eef2f6"
    ACCENT = "#3b82f6"
    TEXT   = "#334155"
    MUTED  = "#64748b"

    def __init__(self):
        super().__init__()
        self.title("Cập Nhật Tài Khoản")
        
        w, h = 340, 160
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.configure(bg=self.BG)

        self._cuoi_thang = tk.BooleanVar(value=False)
        self._build_ui()

    def _build_ui(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background="#e2e8f0", foreground=self.TEXT, relief="flat")
        s.map("TButton", background=[("active", "#cbd5e1"), ("disabled", self.BG)], foreground=[("disabled", self.MUTED)])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(22, 9),
                    background=self.ACCENT, foreground="#FFFFFF", relief="flat")
        s.map("Accent.TButton", background=[("active", "#2563eb"), ("disabled", "#93c5fd")])
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor="#cbd5e1", borderwidth=0, thickness=5)

        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Checkbutton(
            outer, text="Cuối tháng — tạo sheet snapshot (HH:MM TM)",
            variable=self._cuoi_thang,
            bg=self.BG, fg=self.TEXT, activebackground=self.BG,
            font=("Segoe UI", 9), relief="flat",
        ).pack(anchor="w", pady=(0, 12))

        self._status = tk.Label(outer, text="", bg=self.BG,
                                font=("Segoe UI", 9), fg=self.MUTED)
        self._status.pack(anchor="w")

        self._progress = ttk.Progressbar(outer, mode="indeterminate", length=300)
        self._progress.pack(fill="x", pady=(4, 10))

        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x")
        ttk.Button(bot, text="Huỷ", command=self.destroy).pack(side="right")
        self._run_btn = ttk.Button(bot, text="Chạy", style="Accent.TButton",
                                   command=self._run)
        self._run_btn.pack(side="right", padx=(0, 8))

    def _run(self):
        self._run_btn.configure(state="disabled")
        self._progress.start(12)
        self._status.configure(text="Đang chạy...")
        cuoi_thang = self._cuoi_thang.get()
        threading.Thread(target=self._worker, args=(cuoi_thang,), daemon=True).start()

    def _worker(self, cuoi_thang: bool):
        try:
            main(cuoi_thang=cuoi_thang)
            self.after(0, self._done)
        except Exception as e:
            self.after(0, lambda e=e: self._error(str(e)))

    def _done(self):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._status.configure(text="✓ Hoàn thành!")
        messagebox.showinfo("Hoàn thành", "Đã cập nhật tài khoản quảng cáo.")

    def _error(self, msg: str):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._status.configure(text=f"✗ Lỗi: {msg}", fg="#dc3545")
        messagebox.showerror("Lỗi", msg)


if __name__ == "__main__":
    App().mainloop()
