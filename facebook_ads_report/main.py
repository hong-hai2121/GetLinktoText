#!/usr/bin/env python3
"""
Facebook Ads Report Tool
Lấy dữ liệu chi tiêu Facebook Ads và lưu vào Google Sheets.
"""

import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import json
import sys
import os

# ============================================================
# CONFIGURATION
# ============================================================
AD_ACCOUNT_ID = "act_882350396554887"
ACCESS_TOKEN = (
    "EAAXJKwPSJzABRSPeQ7lSX6BjHbIS0URANtsyK1yXUH1ctNFiCGN39hpOwKg7Pn"
    "PJceKciVFk688aZAwnuEaKZAGFLzdCwlJiyAn5l3C891icJAFGZC2zT9dJeeU6N9"
    "wwz1ikjVj9UCoQrvSNucxZBSH7be60ivTPUeTFCHcXPqOI2Vq3trCh0m5gqBgATK"
    "cU3uxwvfKL6dWxsb1hRjsrWDRaDEEzKZCkR1KZA3nYHv6HPnPPY8oRaZBzZAoiff"
    "IjG93UtrvfnwcjM03iGyZBZCSjD0mDBvL2F4OpnIDzXBewZDZD"
)
GOOGLE_SHEET_ID = "1lx2_GAI80riLryyiRYCREXMqGzzGptAiAzTKUXE3qiI"
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")

FB_API_VERSION = "v21.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"

# "all" = từ 2019 đến hôm nay
START_DATE = "2019-01-01"
END_DATE = date.today().strftime("%Y-%m-%d")

# Màu header
COLOR_BLUE  = {"red": 0.18, "green": 0.45, "blue": 0.71}
COLOR_GREEN = {"red": 0.08, "green": 0.50, "blue": 0.16}
WHITE       = {"red": 1.0,  "green": 1.0,  "blue": 1.0}


# ============================================================
# FACEBOOK API
# ============================================================
def fb_get(endpoint: str, params: dict) -> list:
    """GET có phân trang tới Facebook Graph API."""
    url = f"{FB_BASE_URL}/{endpoint}"
    all_data = []

    while url:
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[Network Error] {e}")
            sys.exit(1)

        result = resp.json()

        if "error" in result:
            err = result["error"]
            print(f"\n[Facebook API Error]")
            print(f"  Message : {err.get('message')}")
            print(f"  Code    : {err.get('code')}")
            print(f"  Type    : {err.get('type')}")
            print("\nHãy kiểm tra lại Access Token và quyền truy cập.")
            sys.exit(1)

        all_data.extend(result.get("data", []))

        # Phân trang
        url = result.get("paging", {}).get("next")
        params = {}  # URL tiếp theo đã chứa params

    return all_data


def get_daily_insights() -> list:
    """Tab 1: Chi tiêu tài khoản từng ngày."""
    print(f"  Đang lấy dữ liệu ngày ({START_DATE} → {END_DATE})...")
    data = fb_get(
        f"{AD_ACCOUNT_ID}/insights",
        {
            "access_token": ACCESS_TOKEN,
            "level": "account",
            "time_increment": 1,
            "time_range": json.dumps({"since": START_DATE, "until": END_DATE}),
            "fields": "date_start,spend,impressions,clicks,cpm,cpc",
            "limit": 500,
        },
    )
    print(f"  → {len(data)} ngày có dữ liệu")
    return data


def get_all_campaigns() -> list:
    """Tab 2: Tất cả campaign kèm insights lifetime."""
    print("  Đang lấy danh sách campaign...")
    campaigns = fb_get(
        f"{AD_ACCOUNT_ID}/campaigns",
        {
            "access_token": ACCESS_TOKEN,
            "effective_status": json.dumps(
                ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "CAMPAIGN_PAUSED"]
            ),
            "fields": "id,name,status,effective_status,start_time,stop_time",
            "limit": 100,
        },
    )
    print(f"  → {len(campaigns)} campaign tìm thấy")

    print("  Đang lấy insights lifetime cho từng campaign...")
    insights_list = fb_get(
        f"{AD_ACCOUNT_ID}/insights",
        {
            "access_token": ACCESS_TOKEN,
            "level": "campaign",
            "date_preset": "lifetime",
            "fields": (
                "campaign_id,spend,impressions,clicks,"
                "actions,action_values,purchase_roas"
            ),
            "limit": 500,
        },
    )

    insights_map = {row["campaign_id"]: row for row in insights_list}

    merged = []
    for c in campaigns:
        ins = insights_map.get(c["id"], {})
        merged.append(
            {
                "name":          c.get("name", ""),
                "status":        c.get("effective_status") or c.get("status", ""),
                "start_time":    c.get("start_time", ""),
                "stop_time":     c.get("stop_time", ""),
                "spend":         float(ins.get("spend", 0) or 0),
                "actions":       ins.get("actions", []),
                "purchase_roas": ins.get("purchase_roas", []),
            }
        )

    return merged


# ============================================================
# HELPERS
# ============================================================
def fmt_vnd(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "0"


def fmt_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return date_str


STATUS_VI = {
    "ACTIVE":           "Đang chạy",
    "PAUSED":           "Tạm dừng",
    "DELETED":          "Đã xóa",
    "ARCHIVED":         "Lưu trữ",
    "CAMPAIGN_PAUSED":  "Campaign tạm dừng",
}

# Loại hành động được tính là "Kết quả"
RESULT_ACTION_TYPES = {
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "lead",
    "offsite_conversion.fb_pixel_lead",
    "complete_registration",
    "offsite_conversion.fb_pixel_complete_registration",
}


def extract_result(actions: list) -> float:
    return sum(
        float(a.get("value", 0))
        for a in actions
        if a.get("action_type") in RESULT_ACTION_TYPES
    )


def extract_roas(purchase_roas: list) -> float:
    return float(purchase_roas[0].get("value", 0)) if purchase_roas else 0.0


# ============================================================
# GOOGLE SHEETS
# ============================================================
def connect_sheet():
    if not os.path.exists(CREDENTIALS_FILE):
        print(
            f"\n[ERROR] Không tìm thấy file credentials: {CREDENTIALS_FILE}\n"
            "Hãy làm theo hướng dẫn trong README.md để tạo Google Service Account."
        )
        sys.exit(1)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)


def get_or_create_ws(spreadsheet, title: str, rows=3000, cols=20):
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
    return ws


def apply_header_format(ws, a1_range: str, bg_color: dict):
    ws.format(
        a1_range,
        {
            "backgroundColor": bg_color,
            "textFormat": {
                "foregroundColor": WHITE,
                "bold": True,
                "fontSize": 11,
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
        },
    )


def write_daily_tab(spreadsheet, daily_data: list):
    print("  Ghi tab 'Chi tiêu theo ngày'...")
    ws = get_or_create_ws(spreadsheet, "Chi tiêu theo ngày")

    headers = [
        "Ngày",
        "Chi tiêu (VND)",
        "Số lượt hiển thị",
        "Số click",
        "CPM (VND)",
        "CPC (VND)",
    ]

    rows = [headers]
    for d in sorted(daily_data, key=lambda x: x.get("date_start", "")):
        spend = float(d.get("spend", 0) or 0)
        if spend == 0:
            continue  # Bỏ qua ngày không có chi tiêu
        rows.append(
            [
                fmt_date(d.get("date_start", "")),
                fmt_vnd(spend),
                int(d.get("impressions", 0) or 0),
                int(d.get("clicks", 0) or 0),
                fmt_vnd(d.get("cpm", 0)),
                fmt_vnd(d.get("cpc", 0)),
            ]
        )

    ws.update("A1", rows)
    ws.freeze(rows=1)
    apply_header_format(ws, "A1:F1", COLOR_BLUE)
    print(f"  → {len(rows) - 1} ngày được ghi")


def write_campaign_tab(spreadsheet, campaign_data: list):
    print("  Ghi tab 'Chi tiết Campaign'...")
    ws = get_or_create_ws(spreadsheet, "Chi tiết Campaign")

    headers = [
        "Tên Campaign",
        "Trạng thái",
        "Ngày bắt đầu",
        "Ngày kết thúc",
        "Tổng chi tiêu (VND)",
        "Kết quả",
        "CPA (VND)",
        "ROAS",
    ]

    rows = [headers]
    for c in campaign_data:
        spend   = c["spend"]
        results = extract_result(c["actions"])
        roas    = extract_roas(c["purchase_roas"])
        cpa     = spend / results if results > 0 else 0

        rows.append(
            [
                c["name"],
                STATUS_VI.get(c["status"], c["status"]),
                fmt_date(c["start_time"]),
                fmt_date(c["stop_time"]),
                fmt_vnd(spend),
                int(results) if results > 0 else "-",
                fmt_vnd(cpa) if cpa > 0 else "-",
                f"{roas:.2f}" if roas > 0 else "-",
            ]
        )

    ws.update("A1", rows)
    ws.freeze(rows=1)
    apply_header_format(ws, "A1:H1", COLOR_GREEN)
    print(f"  → {len(rows) - 1} campaign được ghi")


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 55)
    print("   Facebook Ads Report Tool")
    print("=" * 55)
    print(f"Account : {AD_ACCOUNT_ID}")
    print(f"Period  : {START_DATE} → {END_DATE}")
    print()

    print("[1/4] Lấy dữ liệu chi tiêu theo ngày...")
    daily = get_daily_insights()

    print("[2/4] Lấy dữ liệu campaign...")
    campaigns = get_all_campaigns()

    print("[3/4] Kết nối Google Sheets...")
    sheet = connect_sheet()
    print(f"  → Spreadsheet: {sheet.title}")

    print("[4/4] Ghi dữ liệu vào Google Sheets...")
    write_daily_tab(sheet, daily)
    write_campaign_tab(sheet, campaigns)

    print()
    print("=" * 55)
    print("Hoàn tất!")
    print(f"Link: https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}")
    print("=" * 55)


if __name__ == "__main__":
    main()
