import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path

from config import ACCESS_TOKEN
from fb_api import graph_paginate, api_summary

BASE_DIR = Path(__file__).parent

SPREADSHEET_ID = "1zZ7H9lj_s4Dm1hTeMvrQtKLFeiOBb5rWu8h7QJ458PM"
SHEET_NAME = "TKQC API"
FB_API_VERSION = "v20.0"

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

    available = [ws.title for ws in spreadsheet.worksheets()]
    if SHEET_NAME not in available:
        print(f"Không tìm thấy sheet '{SHEET_NAME}'. Các sheet hiện có: {available}")
        raise gspread.exceptions.WorksheetNotFound(SHEET_NAME)

    return spreadsheet.worksheet(SHEET_NAME)


def read_existing_data(worksheet) -> tuple[dict[str, bool], dict[str, str]]:
    """Đọc sheet hiện tại, trả về ({account_id: chọn_lấy_camp}, {account_id: số_dư})."""
    try:
        all_values = worksheet.get_all_values()
    except Exception:
        return {}, {}

    if len(all_values) < 2:
        return {}, {}

    header = all_values[0]
    try:
        id_col = header.index("ID Tài Khoản")
        chon_col = header.index("Chọn Lấy Camp")
    except ValueError:
        return {}, {}

    so_du_col = header.index("Số Dư") if "Số Dư" in header else -1

    selections, prev_balances = {}, {}
    for row in all_values[1:]:
        acc_id = row[id_col].strip().removeprefix("act_") if id_col < len(row) else ""
        if not acc_id:
            continue
        chon_val = row[chon_col].strip() if chon_col < len(row) else ""
        selections[acc_id] = chon_val.upper() in ("TRUE", "ĐÚNG", "1", "X", "✓")
        if so_du_col >= 0:
            prev_balances[acc_id] = row[so_du_col].strip() if so_du_col < len(row) else ""
    return selections, prev_balances


def fetch_ad_accounts(access_token: str) -> list[dict]:
    fields = "id,name,account_status,currency,timezone_name,amount_spent,balance,business,funding_source_details"
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


def write_to_sheet(worksheet, accounts: list[dict], selections: dict[str, bool], prev_balances: dict[str, str]):
    def sort_key(acc):
        biz = acc.get("business") or {}
        return (biz.get("name", "") or "￿", acc.get("name", ""))

    sorted_accounts = sorted(accounts, key=sort_key)

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    rows = []
    for acc in sorted_accounts:
        currency = acc.get("currency", "")
        status_code = acc.get("account_status", 0)
        biz = acc.get("business") or {}
        acc_id = acc.get("id", "").removeprefix("act_")
        current_balance = format_money(acc.get("balance", "0"), currency)
        prev_balance = prev_balances.get(acc_id, "")
        balance_changed = prev_balance != "" and current_balance != prev_balance
        chon = "TRUE" if (selections.get(acc_id, False) or balance_changed) else "FALSE"
        funding = acc.get("funding_source_details") or {}
        payment_method = funding.get("display_string", "")
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
            prev_balances.get(acc_id, ""),
            payment_method,
            chon,
            now_str,
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


def main():
    print("Kết nối Google Sheets...")
    worksheet = connect_sheet()

    print("Đọc dữ liệu hiện tại (giữ lại Chọn Lấy Camp + Số Dư Trước)...")
    selections, prev_balances = read_existing_data(worksheet)
    selected_count = sum(1 for v in selections.values() if v)
    print(f"  → {selected_count} tài khoản đang được chọn.")

    print("Lấy danh sách tài khoản quảng cáo từ Facebook Graph API...")
    accounts = fetch_ad_accounts(ACCESS_TOKEN)
    print(f"Tìm thấy {len(accounts)} tài khoản quảng cáo.")

    save_json(accounts)

    print(f"Ghi dữ liệu vào sheet '{SHEET_NAME}'...")
    write_to_sheet(worksheet, accounts, selections, prev_balances)

    api_summary()
    print("Hoàn thành!")


if __name__ == "__main__":
    main()
