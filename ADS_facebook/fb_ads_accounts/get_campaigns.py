"""
Đọc sheet TKQC API → tìm tài khoản có cột "Chọn Lấy Camp" = TRUE
→ Gọi Facebook Graph API lấy chiến dịch tháng này
→ Ghi vào sheet tab có tên là tên tài khoản quảng cáo
"""

import re
import requests
import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

SPREADSHEET_ID = "1zZ7H9lj_s4Dm1hTeMvrQtKLFeiOBb5rWu8h7QJ458PM"
AD_ACCOUNTS_SHEET = "TKQC API"
FB_API_VERSION = "v20.0"

ACCESS_TOKEN = "EAAWM6N6fZAPMBRaTNU4xyWC8ImGodBXZB2wcV2YF0mUidZAae4VVEl519Riqd9UA5UHrsg6O69vCTZCG4EManeL54E7ZCncOdiWZCQDvKSM05xIeSdZCYEfeNz34EQQ04ZBVO4oLxzxFnxW3QcNXkPf0UH5SqKpIMcUPw1N6Q5qf23mFmDNrRqKBlqIWA3b7lifTlHz8mKwHc8254ZAR8"

ZERO_DECIMAL_CURRENCIES = {
    "VND", "JPY", "KRW", "BIF", "CLP", "GNF", "ISK", "KMF",
    "MGA", "PYG", "RWF", "UGX", "VUV", "XAF", "XOF", "XPF",
}

CAMPAIGN_STATUS_MAP = {
    "ACTIVE": "Đang chạy",
    "PAUSED": "Tạm dừng",
    "DELETED": "Đã xóa",
    "ARCHIVED": "Đã lưu trữ",
}

OBJECTIVE_MAP = {
    "BRAND_AWARENESS": "Nhận biết thương hiệu",
    "REACH": "Tiếp cận",
    "TRAFFIC": "Lưu lượng",
    "ENGAGEMENT": "Tương tác",
    "APP_INSTALLS": "Cài đặt app",
    "VIDEO_VIEWS": "Xem video",
    "LEAD_GENERATION": "Khách hàng tiềm năng",
    "MESSAGES": "Tin nhắn",
    "CONVERSIONS": "Chuyển đổi",
    "CATALOG_SALES": "Bán hàng catalog",
    "OUTCOME_TRAFFIC": "Lưu lượng",
    "OUTCOME_ENGAGEMENT": "Tương tác",
    "OUTCOME_LEADS": "Khách hàng tiềm năng",
    "OUTCOME_SALES": "Doanh số",
    "OUTCOME_AWARENESS": "Nhận biết",
    "OUTCOME_APP_PROMOTION": "Quảng bá ứng dụng",
}

CAMPAIGN_HEADERS = [
    "STT",
    "ID Chiến Dịch",
    "Tên Chiến Dịch",
    "Mục Tiêu",
    "Trạng Thái",
    "Ngân Sách / Ngày",
    "Ngân Sách Toàn Kỳ",
    "Chi Phí Tháng Này",
    "Lượt Hiển Thị",
    "Lượt Click",
    "CTR (%)",
    "CPC",
    "Tiếp Cận",
    "Tần Suất",
    "Cập Nhật Lúc",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Google Sheets ──────────────────────────────────────────────────────────────

def connect_spreadsheet(credentials_file: str = "service_account.json"):
    credentials_path = BASE_DIR / credentials_file
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def get_selected_accounts(spreadsheet) -> list[dict]:
    """Đọc sheet TKQC API, trả về list {id, name, currency} của các tài khoản được chọn."""
    ws = spreadsheet.worksheet(AD_ACCOUNTS_SHEET)
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return []

    header = all_values[0]
    try:
        id_col = header.index("ID Tài Khoản")
        name_col = header.index("Tên Tài Khoản")
        currency_col = header.index("Tiền Tệ")
        chon_col = header.index("Chọn Lấy Camp")
    except ValueError as e:
        raise RuntimeError(f"Sheet '{AD_ACCOUNTS_SHEET}' thiếu cột: {e}. Hãy chạy main.py trước.")

    selected = []
    for row in all_values[1:]:
        chon_val = row[chon_col].strip().upper() if chon_col < len(row) else ""
        if chon_val in ("TRUE", "ĐÚNG", "1", "X", "✓"):
            acc_id = row[id_col].strip() if id_col < len(row) else ""
            acc_name = row[name_col].strip() if name_col < len(row) else ""
            currency = row[currency_col].strip() if currency_col < len(row) else "VND"
            if acc_id:
                selected.append({"id": acc_id, "name": acc_name, "currency": currency})
    return selected


def sanitize_sheet_name(name: str) -> str:
    """Xóa ký tự không hợp lệ cho tên tab Google Sheets, giới hạn 100 ký tự."""
    name = re.sub(r'[\\/*?\[\]:]', '', name)
    return name[:100].strip() or "Unknown"


def get_or_create_worksheet(spreadsheet, title: str):
    safe_title = sanitize_sheet_name(title)
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if safe_title in existing:
        return existing[safe_title]
    return spreadsheet.add_worksheet(title=safe_title, rows=1000, cols=20)


# ── Facebook Graph API ─────────────────────────────────────────────────────────

def paginate(url: str, params: dict) -> list[dict]:
    """Gọi API với phân trang tự động."""
    results = []
    while url:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Facebook API lỗi: {data['error']['message']}")
        results.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return results


def fetch_campaigns(account_id: str) -> list[dict]:
    """Lấy danh sách chiến dịch của tài khoản (đang chạy + tạm dừng + lưu trữ)."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/campaigns"
    params = {
        "fields": "id,name,status,objective,daily_budget,lifetime_budget,start_time,stop_time",
        "access_token": ACCESS_TOKEN,
        "limit": 100,
    }
    return paginate(url, params)


def fetch_insights_this_month(account_id: str) -> list[dict]:
    """Lấy insights ở mức chiến dịch cho tháng hiện tại."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/insights"
    params = {
        "level": "campaign",
        "date_preset": "this_month",
        "fields": "campaign_id,spend,impressions,clicks,ctr,cpc,reach,frequency",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return paginate(url, params)


def merge_campaigns_insights(campaigns: list[dict], insights: list[dict]) -> list[dict]:
    """Gộp insights vào campaigns theo campaign_id."""
    insights_map = {row["campaign_id"]: row for row in insights if "campaign_id" in row}
    for camp in campaigns:
        insight = insights_map.get(camp["id"], {})
        camp["_spend"] = insight.get("spend", "0")
        camp["_impressions"] = insight.get("impressions", "0")
        camp["_clicks"] = insight.get("clicks", "0")
        camp["_ctr"] = insight.get("ctr", "0")
        camp["_cpc"] = insight.get("cpc", "0")
        camp["_reach"] = insight.get("reach", "0")
        camp["_frequency"] = insight.get("frequency", "0")
    return campaigns


# ── Formatting ─────────────────────────────────────────────────────────────────

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


def fmt_num(raw) -> str:
    try:
        return f"{int(float(raw)):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "0"


def fmt_pct(raw) -> str:
    try:
        return f"{float(raw):.2f}%"
    except (ValueError, TypeError):
        return "0%"


# ── Write campaigns to sheet ───────────────────────────────────────────────────

def write_campaigns(worksheet, campaigns: list[dict], currency: str):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Sắp xếp: đang chạy trước, sau đó tạm dừng, cuối là xóa/lưu trữ
    status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}
    sorted_camps = sorted(campaigns, key=lambda c: (status_order.get(c.get("status", ""), 9), c.get("name", "")))

    rows = []
    for i, camp in enumerate(sorted_camps, start=1):
        objective_raw = camp.get("objective", "")
        daily_budget = camp.get("daily_budget")
        lifetime_budget = camp.get("lifetime_budget")
        rows.append([
            i,
            camp.get("id", ""),
            camp.get("name", ""),
            OBJECTIVE_MAP.get(objective_raw, objective_raw),
            CAMPAIGN_STATUS_MAP.get(camp.get("status", ""), camp.get("status", "")),
            format_money(daily_budget, currency) if daily_budget else "",
            format_money(lifetime_budget, currency) if lifetime_budget else "",
            format_money(camp["_spend"], currency),
            fmt_num(camp["_impressions"]),
            fmt_num(camp["_clicks"]),
            fmt_pct(camp["_ctr"]),
            format_money(camp["_cpc"], currency),
            fmt_num(camp["_reach"]),
            fmt_pct(camp["_frequency"]),
            now_str,
        ])

    col_letter = chr(64 + len(CAMPAIGN_HEADERS))
    worksheet.update("A1", [CAMPAIGN_HEADERS])

    last_row = worksheet.row_count
    if last_row >= 2:
        worksheet.batch_clear([f"A2:{col_letter}{last_row}"])

    if rows:
        worksheet.update("A2", rows)


# ── Main ───────────────────────────────────────────────────────────────────────

def save_json(data, filename: str):
    out_path = BASE_DIR / filename
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  JSON → {out_path}")


def main():
    month_label = datetime.now().strftime("%m/%Y")
    print("Kết nối Google Sheets...")
    spreadsheet = connect_spreadsheet()

    print(f"Đọc danh sách tài khoản được chọn từ sheet '{AD_ACCOUNTS_SHEET}'...")
    selected = get_selected_accounts(spreadsheet)
    if not selected:
        print("Không có tài khoản nào được chọn. Hãy đánh TRUE vào cột 'Chọn Lấy Camp' trong sheet TKQC API.")
        return
    print(f"Tìm thấy {len(selected)} tài khoản được chọn.")

    all_data = {}
    for acc in selected:
        acc_id = acc["id"]
        acc_name = acc["name"]
        currency = acc["currency"]
        print(f"\n[{acc_name}] Lấy chiến dịch tháng {month_label}...")

        campaigns = fetch_campaigns(acc_id)
        print(f"  → {len(campaigns)} chiến dịch.")

        insights = fetch_insights_this_month(acc_id)
        print(f"  → {len(insights)} dòng insights.")

        merged = merge_campaigns_insights(campaigns, insights)
        all_data[acc_name] = merged

        ws = get_or_create_worksheet(spreadsheet, acc_name)
        write_campaigns(ws, merged, currency)
        print(f"  → Đã ghi vào sheet tab '{sanitize_sheet_name(acc_name)}'.")

    save_json(all_data, "campaigns.json")
    print("\nHoàn thành!")


if __name__ == "__main__":
    main()
