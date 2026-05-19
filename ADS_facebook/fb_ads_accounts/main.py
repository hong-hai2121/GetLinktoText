import requests
import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

SPREADSHEET_ID = "1zZ7H9lj_s4Dm1hTeMvrQtKLFeiOBb5rWu8h7QJ458PM"
SHEET_NAME = "TKQC API"
FB_API_VERSION = "v20.0"

ACCESS_TOKEN = "EAAWM6N6fZAPMBRaTNU4xyWC8ImGodBXZB2wcV2YF0mUidZAae4VVEl519Riqd9UA5UHrsg6O69vCTZCG4EManeL54E7ZCncOdiWZCQDvKSM05xIeSdZCYEfeNz34EQQ04ZBVO4oLxzxFnxW3QcNXkPf0UH5SqKpIMcUPw1N6Q5qf23mFmDNrRqKBlqIWA3b7lifTlHz8mKwHc8254ZAR8"

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


def read_existing_selections(worksheet) -> dict[str, bool]:
    """Đọc cột 'Chọn Lấy Camp' hiện tại, trả về {account_id: True/False}."""
    try:
        all_values = worksheet.get_all_values()
    except Exception:
        return {}

    if len(all_values) < 2:
        return {}

    header = all_values[0]
    try:
        id_col = header.index("ID Tài Khoản")
        chon_col = header.index("Chọn Lấy Camp")
    except ValueError:
        return {}

    selections = {}
    for row in all_values[1:]:
        acc_id = row[id_col].strip() if id_col < len(row) else ""
        chon_val = row[chon_col].strip() if chon_col < len(row) else ""
        if acc_id:
            selections[acc_id] = chon_val.upper() in ("TRUE", "ĐÚNG", "1", "X", "✓")
    return selections


def fetch_ad_accounts(access_token: str) -> list[dict]:
    fields = "id,name,account_status,currency,timezone_name,amount_spent,balance,business"
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me/adaccounts"
    params = {"fields": fields, "access_token": access_token, "limit": 500}

    accounts = []
    while url:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Facebook API lỗi: {data['error']['message']}")
        accounts.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}

    return accounts


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


def write_to_sheet(worksheet, accounts: list[dict], selections: dict[str, bool]):
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
        acc_id = acc.get("id", "")
        chon = "TRUE" if selections.get(acc_id, False) else "FALSE"
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
            chon,
            now_str,
        ])

    col_letter = chr(64 + len(HEADERS))
    worksheet.update("A1", [HEADERS])

    last_row = worksheet.row_count
    if last_row >= 2:
        worksheet.batch_clear([f"A2:{col_letter}{last_row}"])

    if rows:
        worksheet.update("A2", rows)
        print(f"Đã ghi {len(rows)} tài khoản quảng cáo vào sheet '{SHEET_NAME}' (từ A1).")
    else:
        print("Không có tài khoản quảng cáo nào.")


def save_json(accounts: list[dict]):
    out_path = BASE_DIR / "ad_accounts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)
    print(f"Đã lưu JSON → {out_path}")


def main():
    print("Kết nối Google Sheets...")
    worksheet = connect_sheet()

    print("Đọc lựa chọn hiện tại (giữ lại cột Chọn Lấy Camp)...")
    selections = read_existing_selections(worksheet)
    selected_count = sum(1 for v in selections.values() if v)
    print(f"  → {selected_count} tài khoản đang được chọn.")

    print("Lấy danh sách tài khoản quảng cáo từ Facebook Graph API...")
    accounts = fetch_ad_accounts(ACCESS_TOKEN)
    print(f"Tìm thấy {len(accounts)} tài khoản quảng cáo.")

    save_json(accounts)

    print(f"Ghi dữ liệu vào sheet '{SHEET_NAME}'...")
    write_to_sheet(worksheet, accounts, selections)
    print("Hoàn thành!")


if __name__ == "__main__":
    main()
