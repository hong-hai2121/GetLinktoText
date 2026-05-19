"""
Phase 1 – Lấy danh sách Campaign tháng này cho các tài khoản được chọn
         trong sheet TKQC API (cột "Chọn Lấy Camp" = TRUE).

Ghi mỗi campaign thành 1 dòng vào tab tài khoản trong Google Sheets,
kèm metrics cấp campaign (spend, impressions, CTR, CPM …).

Cột "Chọn Lấy Chi Tiết" được giữ nguyên giá trị cũ để không mất lựa chọn.
→ Chạy get_details.py sau đó để mở rộng Adset / Ad cho các campaign được chọn.
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

STATUS_MAP = {
    "ACTIVE":   "Đang chạy",
    "PAUSED":   "Tạm dừng",
    "DELETED":  "Đã xóa",
    "ARCHIVED": "Đã lưu trữ",
}

# ── Loại action để bóc từ actions / action_values / purchase_roas ──────────────
INBOX_TYPES = [
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.messaging_first_reply",
    "messaging_new_connections",
    "onsite_conversion.messaging_user_depth_2_message_send",
]
LEAD_TYPES = [
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
]
PURCHASE_TYPES = [
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "omni_purchase",
    "onsite_conversion.purchase",
]

# Ưu tiên xác định "Kết Quả" chính (purchase → lead → inbox → engagement)
RESULT_TYPES = (
    PURCHASE_TYPES
    + LEAD_TYPES
    + INBOX_TYPES
    + ["post_engagement", "page_engagement", "link_click", "video_view", "app_install"]
)

# A–AK = 37 cột
HEADERS = [
    "Chọn Lấy Chi Tiết",   # A   1  – chỉ dòng Campaign mới có giá trị
    "Cấp",                   # B   2
    "Campaign ID",           # C   3
    "Campaign Name",         # D   4
    "Adset ID",              # E   5
    "Adset Name",            # F   6
    "Ad ID",                 # G   7
    "Ad Name",               # H   8
    "Creative ID",           # I   9
    "Page ID",               # J  10
    "Post ID",               # K  11
    "Nội Dung Quảng Cáo",   # L  12
    "Tiêu Đề",               # M  13
    "Mô Tả",                 # N  14
    "Link",                  # O  15
    "CTA",                   # P  16
    "Thumbnail URL",         # Q  17
    "Trạng Thái",            # R  18
    "Spend Tháng Này",       # S  19
    "Lượt Hiển Thị",         # T  20
    "Lượt Click",            # U  21
    "CTR (%)",               # V  22
    "CPC",                   # W  23
    "CPM",                   # X  24
    "Tiếp Cận",              # Y  25
    "Tần Suất",              # Z  26
    "Số Inbox",              # AA 27
    "CPI",                   # AB 28
    "Số Lead",               # AC 29
    "CPL",                   # AD 30
    "Số Đơn Hàng",           # AE 31
    "CPS",                   # AF 32
    "Doanh Thu",             # AG 33
    "ROAS",                  # AH 34
    "Kết Quả",               # AI 35  – primary optimization result
    "Chi Phí / Kết Quả",     # AJ 36
    "Cập Nhật Lúc",          # AK 37
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_CHON_VALUES = ("TRUE", "ĐÚNG", "1", "X", "✓")

# ── Khoảng thời gian báo cáo ──────────────────────────────────────────────────
# Mặc định khi chạy thẳng bằng python get_campaigns.py.
# Khi chạy qua launcher.py, giá trị sẽ được ghi vào config.py và đọc ở đây.
try:
    from config import DATE_PRESET, TIME_RANGE   # ghi bởi launcher.py
except ImportError:
    DATE_PRESET = "this_month"                   # preset mặc định
    TIME_RANGE: dict = {}                        # chỉ dùng khi DATE_PRESET = ""


def _date_params() -> dict:
    """Trả về dict tham số ngày để truyền vào Insights API."""
    if DATE_PRESET:
        return {"date_preset": DATE_PRESET}
    return {"time_range": json.dumps(TIME_RANGE)}


# Fields gửi cho Insights API (dùng chung cho campaign và ad level)
_INSIGHTS_FIELDS = (
    "spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,"
    "actions,action_values,purchase_roas,cost_per_action_type"
)


# ── Google Sheets ──────────────────────────────────────────────────────────────

def col_to_letter(n: int) -> str:
    """Chuyển số cột 1-based sang ký hiệu A1 (vd: 27 → 'AA', 37 → 'AK')."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def connect_spreadsheet(credentials_file: str = "service_account.json"):
    credentials_path = BASE_DIR / credentials_file
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def get_selected_accounts(spreadsheet) -> list[dict]:
    """Đọc sheet TKQC API, trả về list {id, name, currency} của tài khoản được chọn."""
    ws = spreadsheet.worksheet(AD_ACCOUNTS_SHEET)
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return []

    header = all_values[0]
    try:
        id_col       = header.index("ID Tài Khoản")
        name_col     = header.index("Tên Tài Khoản")
        currency_col = header.index("Tiền Tệ")
        chon_col     = header.index("Chọn Lấy Camp")
    except ValueError as e:
        raise RuntimeError(f"Sheet '{AD_ACCOUNTS_SHEET}' thiếu cột: {e}. Hãy chạy main.py trước.")

    selected = []
    for row in all_values[1:]:
        chon_val = row[chon_col].strip().upper() if chon_col < len(row) else ""
        if chon_val in _CHON_VALUES:
            acc_id   = row[id_col].strip()       if id_col       < len(row) else ""
            acc_name = row[name_col].strip()     if name_col     < len(row) else ""
            currency = row[currency_col].strip() if currency_col < len(row) else "VND"
            if acc_id:
                selected.append({"id": acc_id, "name": acc_name, "currency": currency})
    return selected


def read_detail_selections(worksheet) -> dict[str, bool]:
    """Đọc cột 'Chọn Lấy Chi Tiết' trong tab tài khoản, trả về {campaign_id: bool}."""
    try:
        all_values = worksheet.get_all_values()
    except Exception:
        return {}

    if len(all_values) < 2:
        return {}

    header = all_values[0]
    try:
        chon_col    = header.index("Chọn Lấy Chi Tiết")
        cap_col     = header.index("Cấp")
        camp_id_col = header.index("Campaign ID")
    except ValueError:
        return {}

    selections = {}
    for row in all_values[1:]:
        cap = row[cap_col].strip() if cap_col < len(row) else ""
        if cap != "Campaign":
            continue
        camp_id  = row[camp_id_col].strip() if camp_id_col < len(row) else ""
        chon_val = row[chon_col].strip().upper() if chon_col < len(row) else ""
        if camp_id:
            selections[camp_id] = chon_val in _CHON_VALUES
    return selections


def sanitize_sheet_name(name: str) -> str:
    name = re.sub(r'[\\/*?\[\]:]', '', name)
    return name[:100].strip() or "Unknown"


def get_or_create_worksheet(spreadsheet, title: str):
    safe_title = sanitize_sheet_name(title)
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if safe_title in existing:
        return existing[safe_title]
    return spreadsheet.add_worksheet(title=safe_title, rows=5000, cols=len(HEADERS))


def write_to_sheet(worksheet, rows: list[list]):
    last_col = col_to_letter(len(HEADERS))
    worksheet.update("A1", [HEADERS])
    last_row = worksheet.row_count
    if last_row >= 2:
        worksheet.batch_clear([f"A2:{last_col}{last_row}"])
    if rows:
        worksheet.update("A2", rows)


# ── Facebook Graph API ─────────────────────────────────────────────────────────

def paginate(url: str, params: dict) -> list[dict]:
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
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/campaigns"
    params = {
        "fields":       "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit":        100,
    }
    return paginate(url, params)


def fetch_insights_campaign_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/insights"
    params = {
        "level":        "campaign",
        **_date_params(),
        "fields":       f"campaign_id,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit":        500,
    }
    return paginate(url, params)


# ── Insights metrics ───────────────────────────────────────────────────────────

def safe_float(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _sum_actions(action_list: list, types: list) -> float:
    """Tổng value của các action_type khớp trong danh sách ưu tiên."""
    if not action_list:
        return 0.0
    total = 0.0
    matched = set()
    for item in action_list:
        atype = item.get("action_type", "")
        if atype in types and atype not in matched:
            total += safe_float(item.get("value"))
            matched.add(atype)
    return total


def _get_primary_result(insight: dict) -> tuple[float, float]:
    """Xác định Kết Quả chính và Chi Phí / Kết Quả từ cost_per_action_type.

    Facebook Ads Manager hiển thị "Kết quả" dựa trên optimization event của adset.
    Xấp xỉ bằng cách dùng cost_per_action_type (API đã tính sẵn) theo thứ tự
    ưu tiên RESULT_TYPES, rồi lấy count từ actions.

    Returns: (ket_qua_count, chi_phi_ket_qua)
    """
    cost_per_action = insight.get("cost_per_action_type") or []
    actions         = insight.get("actions") or []

    cost_map   = {i.get("action_type", ""): safe_float(i.get("value")) for i in cost_per_action}
    action_map = {i.get("action_type", ""): safe_float(i.get("value")) for i in actions}

    for atype in RESULT_TYPES:
        cpx = cost_map.get(atype, 0.0)
        if cpx > 0:
            return action_map.get(atype, 0.0), cpx

    return 0.0, 0.0


def parse_insight_metrics(insight: dict) -> dict:
    """Chuyển raw insight dict từ API thành dict metrics chuẩn hóa (float).
    Dùng cho cả campaign-level và ad-level insights."""
    spend  = safe_float(insight.get("spend"))
    impr   = safe_float(insight.get("impressions"))
    clicks = safe_float(insight.get("clicks"))
    reach  = safe_float(insight.get("reach"))

    ctr  = safe_float(insight.get("ctr"))
    cpc  = safe_float(insight.get("cpc"))
    cpm  = safe_float(insight.get("cpm"))
    freq = safe_float(insight.get("frequency"))

    # Fallback tính nếu API không trả về
    if ctr == 0 and impr > 0:
        ctr = clicks / impr * 100
    if cpc == 0 and clicks > 0:
        cpc = spend / clicks
    if cpm == 0 and impr > 0:
        cpm = spend / impr * 1000
    if freq == 0 and reach > 0:
        freq = impr / reach

    actions     = insight.get("actions") or []
    action_vals = insight.get("action_values") or []
    roas_arr    = insight.get("purchase_roas") or []

    inbox     = _sum_actions(actions, INBOX_TYPES)
    leads     = _sum_actions(actions, LEAD_TYPES)
    purchases = _sum_actions(actions, PURCHASE_TYPES)
    revenue   = _sum_actions(action_vals, PURCHASE_TYPES)

    roas = _sum_actions(roas_arr, PURCHASE_TYPES)
    if roas == 0 and spend > 0 and revenue > 0:
        roas = revenue / spend

    ket_qua, cpkq = _get_primary_result(insight)

    return {
        "spend":     spend,
        "impr":      impr,
        "clicks":    clicks,
        "ctr":       ctr,
        "cpc":       cpc,
        "cpm":       cpm,
        "reach":     reach,
        "freq":      freq,
        "inbox":     inbox,
        "cpi":       spend / inbox     if inbox     > 0 else 0.0,
        "leads":     leads,
        "cpl":       spend / leads     if leads     > 0 else 0.0,
        "purchases": purchases,
        "cps":       spend / purchases if purchases > 0 else 0.0,
        "revenue":   revenue,
        "roas":      roas,
        "ket_qua":   ket_qua,
        "cpkq":      cpkq,
    }


def aggregate_metrics(metrics_list: list[dict]) -> dict:
    """Tổng hợp metrics từ nhiều Ad thành metrics Adset (dùng bởi get_details.py)."""
    spend     = sum(m["spend"]     for m in metrics_list)
    impr      = sum(m["impr"]      for m in metrics_list)
    clicks    = sum(m["clicks"]    for m in metrics_list)
    reach     = sum(m["reach"]     for m in metrics_list)
    inbox     = sum(m["inbox"]     for m in metrics_list)
    leads     = sum(m["leads"]     for m in metrics_list)
    purchases = sum(m["purchases"] for m in metrics_list)
    revenue   = sum(m["revenue"]   for m in metrics_list)
    ket_qua   = sum(m["ket_qua"]   for m in metrics_list)

    return {
        "spend":     spend,
        "impr":      impr,
        "clicks":    clicks,
        "ctr":       clicks / impr   * 100  if impr      > 0 else 0.0,
        "cpc":       spend  / clicks        if clicks    > 0 else 0.0,
        "cpm":       spend  / impr   * 1000 if impr      > 0 else 0.0,
        "reach":     reach,
        "freq":      impr   / reach         if reach     > 0 else 0.0,
        "inbox":     inbox,
        "cpi":       spend  / inbox         if inbox     > 0 else 0.0,
        "leads":     leads,
        "cpl":       spend  / leads         if leads     > 0 else 0.0,
        "purchases": purchases,
        "cps":       spend  / purchases     if purchases > 0 else 0.0,
        "revenue":   revenue,
        "roas":      revenue / spend        if spend     > 0 else 0.0,
        "ket_qua":   ket_qua,
        "cpkq":      spend  / ket_qua       if ket_qua   > 0 else 0.0,
    }


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_money(value: float, currency: str) -> str:
    currency = currency.upper()
    formatted = f"{int(round(value)):,}".replace(",", ".")
    return f"{formatted} ₫" if currency == "VND" else f"{formatted} {currency}"


def fmt_num(raw) -> str:
    try:
        return f"{int(float(raw)):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "0"


def fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def _insights_cols(m: dict, currency: str) -> list:
    """18 giá trị cho cột S–AJ (Spend → Chi Phí / Kết Quả)."""
    def money(v): return fmt_money(v, currency) if v > 0 else ""
    def count(v): return fmt_num(v)             if v > 0 else ""

    return [
        fmt_money(m["spend"],  currency),                          # S  Spend
        fmt_num(m["impr"]),                                        # T  Lượt Hiển Thị
        fmt_num(m["clicks"]),                                      # U  Lượt Click
        fmt_pct(m["ctr"]),                                         # V  CTR
        money(m["cpc"]),                                           # W  CPC
        money(m["cpm"]),                                           # X  CPM
        fmt_num(m["reach"]),                                       # Y  Tiếp Cận
        fmt_pct(m["freq"]) if m["freq"] > 0 else "",               # Z  Tần Suất
        count(m["inbox"]),                                         # AA Số Inbox
        money(m["cpi"]),                                           # AB CPI
        count(m["leads"]),                                         # AC Số Lead
        money(m["cpl"]),                                           # AD CPL
        count(m["purchases"]),                                     # AE Số Đơn Hàng
        money(m["cps"]),                                           # AF CPS
        money(m["revenue"]),                                       # AG Doanh Thu
        f"{m['roas']:.2f}" if m["roas"] > 0 else "",               # AH ROAS
        count(m["ket_qua"]),                                       # AI Kết Quả
        money(m["cpkq"]),                                          # AJ Chi Phí / Kết Quả
    ]


# ── Row builder ────────────────────────────────────────────────────────────────

def _campaign_row(camp_id, camp_name, is_selected, m: dict,
                  status: str, currency: str, now_str: str) -> list:
    """Dòng Campaign — 37 cột."""
    return [
        "TRUE" if is_selected else "FALSE",  # A
        "Campaign",                           # B
        camp_id,                              # C
        camp_name,                            # D
        "", "",                               # E F  Adset
        "", "",                               # G H  Ad
        "", "", "", "", "", "", "", "", "",   # I..Q Creative (9 ô)
        STATUS_MAP.get(status, status),       # R
    ] + _insights_cols(m, currency) + [now_str]  # S..AJ + AK


# ── JSON output ────────────────────────────────────────────────────────────────

def save_json(data: dict, filename: str, api_info: dict | None = None):
    """Ghi JSON, chèn block _api ở đầu nếu có api_info."""
    payload: dict = {}
    if api_info:
        payload["_api"] = api_info
    payload.update(data)
    out_path = BASE_DIR / filename
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  JSON → {out_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    month_label = datetime.now().strftime("%m/%Y")
    print("Kết nối Google Sheets...")
    spreadsheet = connect_spreadsheet()

    print(f"Đọc danh sách tài khoản được chọn từ sheet '{AD_ACCOUNTS_SHEET}'...")
    selected_accounts = get_selected_accounts(spreadsheet)
    if not selected_accounts:
        print("Không có tài khoản nào được chọn. Hãy đánh TRUE vào cột 'Chọn Lấy Camp'.")
        return
    print(f"Tìm thấy {len(selected_accounts)} tài khoản được chọn.")

    dump_campaigns:      dict[str, list] = {}
    dump_insights_camp:  dict[str, list] = {}

    for acc in selected_accounts:
        acc_id   = acc["id"]
        acc_name = acc["name"]
        currency = acc["currency"]
        print(f"\n[{acc_name}] Xử lý tháng {month_label}...")

        ws = get_or_create_worksheet(spreadsheet, acc_name)

        # Giữ nguyên lựa chọn chi tiết hiện tại
        detail_selections = read_detail_selections(ws)
        selected_count = sum(1 for v in detail_selections.values() if v)
        print(f"  → {selected_count} campaign đang được chọn lấy chi tiết (giữ nguyên).")

        # ── API 1: Campaigns ──────────────────────────────────────────────────
        campaigns = fetch_campaigns(acc_id)
        print(f"  → {len(campaigns)} campaign.")
        dump_campaigns[acc_name] = campaigns

        # ── API 2: Insights cấp campaign ─────────────────────────────────────
        camp_insights = fetch_insights_campaign_level(acc_id)
        camp_insights_map = {r["campaign_id"]: r for r in camp_insights if "campaign_id" in r}
        print(f"  → {len(camp_insights)} dòng insights campaign.")
        dump_insights_camp[acc_name] = camp_insights

        # Build và ghi Campaign rows
        status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}
        sorted_camps = sorted(
            campaigns,
            key=lambda c: (status_order.get(c.get("status", ""), 9), c.get("name", "")),
        )
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        rows = [
            _campaign_row(
                camp.get("id", ""),
                camp.get("name", ""),
                detail_selections.get(camp.get("id", ""), False),
                parse_insight_metrics(camp_insights_map.get(camp.get("id", ""), {})),
                camp.get("status", ""),
                currency,
                now_str,
            )
            for camp in sorted_camps
        ]
        write_to_sheet(ws, rows)
        print(f"  → Đã ghi {len(rows)} dòng vào tab '{sanitize_sheet_name(acc_name)}'.")

    base_url = f"https://graph.facebook.com/{FB_API_VERSION}"
    print("\nLưu JSON...")
    save_json(dump_campaigns, "campaigns.json", {
        "endpoint": f"GET {base_url}/act_{{account_id}}/campaigns",
        "fields":   "id,name,status",
        "note":     "Toàn bộ campaign của tài khoản",
    })
    save_json(dump_insights_camp, "insights_campaign.json", {
        "endpoint":    f"GET {base_url}/act_{{account_id}}/insights",
        "level":       "campaign",
        "date_preset": "this_month",
        "fields":      f"campaign_id,{_INSIGHTS_FIELDS}",
        "note":        "Insights cấp campaign tháng này — dùng cho dòng Campaign trong sheet",
    })
    print("\nHoàn thành!")


if __name__ == "__main__":
    main()
