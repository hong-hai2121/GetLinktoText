"""
Đọc sheet TKQC API → tìm tài khoản có cột "Chọn Lấy Camp" = TRUE
→ Lấy danh sách Campaign tháng này, ghi vào tab tài khoản
→ Với Campaign có "Chọn Lấy Chi Tiết" = TRUE:
   lấy Adset / Ad / Creative + insights level=ad rồi chèn cây bên dưới
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
    "ACTIVE": "Đang chạy",
    "PAUSED": "Tạm dừng",
    "DELETED": "Đã xóa",
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

# Ưu tiên xác định "Kết Quả" chính của chiến dịch (inbox → lead → purchase → engagement)
RESULT_TYPES = (
    INBOX_TYPES
    + LEAD_TYPES
    + PURCHASE_TYPES
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
    "CPI",                   # AA 27
    "CPL",                   # AB 28
    "Số Đơn Hàng",           # AC 29
    "CPS",                   # AD 30
    "Doanh Thu",             # AE 31
    "ROAS",                  # AF 32
    "Kết Quả",               # AG 33  – primary optimization result của campaign
    "Chi Phí / Kết Quả",     # AH 34
    "Cập Nhật Lúc",          # AI 35
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_CHON_VALUES = ("TRUE", "ĐÚNG", "1", "X", "✓")

# Fields gửi cho Insights API (dùng chung cho campaign và ad level)
_INSIGHTS_FIELDS = (
    "spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,"
    "actions,action_values,purchase_roas,cost_per_action_type"
)


# ── Google Sheets ──────────────────────────────────────────────────────────────

def col_to_letter(n: int) -> str:
    """Chuyển số cột 1-based sang ký hiệu A1 (vd: 27 → 'AA', 35 → 'AI')."""
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
        if chon_val in _CHON_VALUES:
            acc_id = row[id_col].strip() if id_col < len(row) else ""
            acc_name = row[name_col].strip() if name_col < len(row) else ""
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
        chon_col = header.index("Chọn Lấy Chi Tiết")
        cap_col = header.index("Cấp")
        camp_id_col = header.index("Campaign ID")
    except ValueError:
        return {}

    selections = {}
    for row in all_values[1:]:
        cap = row[cap_col].strip() if cap_col < len(row) else ""
        if cap != "Campaign":
            continue
        camp_id = row[camp_id_col].strip() if camp_id_col < len(row) else ""
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
        "fields": "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit": 100,
    }
    return paginate(url, params)


def fetch_adsets(campaign_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{campaign_id}/adsets"
    params = {
        "fields": "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit": 100,
    }
    return paginate(url, params)


def fetch_ads(adset_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{adset_id}/ads"
    params = {
        "fields": (
            "id,name,status,"
            "creative{id,name,object_story_spec,body,title,"
            "link_url,thumbnail_url,effective_object_story_id}"
        ),
        "access_token": ACCESS_TOKEN,
        "limit": 100,
    }
    return paginate(url, params)


def fetch_insights_campaign_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/insights"
    params = {
        "level": "campaign",
        "date_preset": "this_month",
        "fields": f"campaign_id,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return paginate(url, params)


def fetch_insights_ad_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/insights"
    params = {
        "level": "ad",
        "date_preset": "this_month",
        "fields": f"ad_id,adset_id,campaign_id,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return paginate(url, params)


def extract_creative_info(creative: dict) -> dict:
    if not creative:
        return {}

    oss = creative.get("object_story_spec") or {}
    link_data = oss.get("link_data") or {}
    video_data = oss.get("video_data") or {}

    page_id = oss.get("page_id", "")
    post_id = ""
    effective_id = creative.get("effective_object_story_id", "")
    if effective_id and "_" in effective_id:
        parts = effective_id.split("_", 1)
        if not page_id:
            page_id = parts[0]
        post_id = parts[1]

    body = (
        creative.get("body")
        or link_data.get("message")
        or video_data.get("message")
        or ""
    )
    title = (
        creative.get("title")
        or link_data.get("name")
        or video_data.get("title")
        or creative.get("name", "")
    )
    description = link_data.get("description") or video_data.get("description") or ""
    link = creative.get("link_url") or link_data.get("link") or ""
    cta_obj = link_data.get("call_to_action") or video_data.get("call_to_action") or {}
    cta = cta_obj.get("type", "") if cta_obj else ""

    return {
        "creative_id": creative.get("id", ""),
        "page_id": page_id,
        "post_id": post_id,
        "body": body,
        "title": title,
        "description": description,
        "link": link,
        "cta": cta,
        "thumbnail_url": creative.get("thumbnail_url", ""),
    }


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
    Chúng ta xấp xỉ bằng cách dùng cost_per_action_type (do API tính sẵn) theo
    thứ tự ưu tiên RESULT_TYPES, rồi lấy count từ actions.

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
    spend = safe_float(insight.get("spend"))
    impr  = safe_float(insight.get("impressions"))
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

    actions      = insight.get("actions") or []
    action_vals  = insight.get("action_values") or []
    roas_arr     = insight.get("purchase_roas") or []

    inbox     = _sum_actions(actions, INBOX_TYPES)
    leads     = _sum_actions(actions, LEAD_TYPES)
    purchases = _sum_actions(actions, PURCHASE_TYPES)
    revenue   = _sum_actions(action_vals, PURCHASE_TYPES)

    # ROAS: ưu tiên giá trị API (đã tính sẵn), fallback tính từ revenue/spend
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
    """Tổng hợp metrics từ nhiều Ad thành metrics Adset."""
    spend = sum(m["spend"] for m in metrics_list)
    impr  = sum(m["impr"]  for m in metrics_list)
    clicks = sum(m["clicks"] for m in metrics_list)
    reach  = sum(m["reach"]  for m in metrics_list)
    inbox     = sum(m["inbox"]     for m in metrics_list)
    leads     = sum(m["leads"]     for m in metrics_list)
    purchases = sum(m["purchases"] for m in metrics_list)
    revenue   = sum(m["revenue"]   for m in metrics_list)

    ket_qua = sum(m["ket_qua"] for m in metrics_list)
    return {
        "spend":     spend,
        "impr":      impr,
        "clicks":    clicks,
        "ctr":       clicks / impr  * 100 if impr   > 0 else 0.0,
        "cpc":       spend  / clicks      if clicks > 0 else 0.0,
        "cpm":       spend  / impr  * 1000 if impr  > 0 else 0.0,
        "reach":     reach,
        "freq":      impr   / reach       if reach  > 0 else 0.0,
        "inbox":     inbox,
        "cpi":       spend  / inbox       if inbox  > 0 else 0.0,
        "leads":     leads,
        "cpl":       spend  / leads       if leads  > 0 else 0.0,
        "purchases": purchases,
        "cps":       spend  / purchases   if purchases > 0 else 0.0,
        "revenue":   revenue,
        "roas":      revenue / spend      if spend  > 0 else 0.0,
        "ket_qua":   ket_qua,
        "cpkq":      spend / ket_qua      if ket_qua > 0 else 0.0,
    }


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_money(value: float, currency: str) -> str:
    """Format giá trị float (đã ở đơn vị thực, không chia 100)."""
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
    """16 giá trị cho cột S–AH (Spend → Chi Phí / Kết Quả)."""
    def money(v):  return fmt_money(v, currency) if v > 0 else ""
    def count(v):  return fmt_num(v) if v > 0 else ""

    return [
        fmt_money(m["spend"],   currency),   # S  Spend (hiện cả khi = 0)
        fmt_num(m["impr"]),                  # T  Lượt Hiển Thị
        fmt_num(m["clicks"]),                # U  Lượt Click
        fmt_pct(m["ctr"]),                   # V  CTR
        money(m["cpc"]),                     # W  CPC
        money(m["cpm"]),                     # X  CPM
        fmt_num(m["reach"]),                 # Y  Tiếp Cận
        fmt_pct(m["freq"]) if m["freq"] > 0 else "",  # Z  Tần Suất
        money(m["cpi"]),                     # AA CPI
        money(m["cpl"]),                     # AB CPL
        count(m["purchases"]),               # AC Số Đơn Hàng
        money(m["cps"]),                     # AD CPS
        money(m["revenue"]),                 # AE Doanh Thu
        f"{m['roas']:.2f}" if m["roas"] > 0 else "",  # AF ROAS
        count(m["ket_qua"]),                 # AG Kết Quả
        money(m["cpkq"]),                    # AH Chi Phí / Kết Quả
    ]


# ── Build rows ─────────────────────────────────────────────────────────────────

def _campaign_row(camp_id, camp_name, is_selected, m: dict, status: str,
                  currency: str, now_str: str) -> list:
    """Dòng Campaign — 35 cột."""
    return [
        "TRUE" if is_selected else "FALSE",  # A
        "Campaign",                           # B
        camp_id,                              # C
        camp_name,                            # D
        "", "",                               # E F Adset
        "", "",                               # G H Ad
        "", "", "", "", "", "", "", "", "",   # I..Q Creative (9)
        STATUS_MAP.get(status, status),       # R
    ] + _insights_cols(m, currency) + [now_str]  # S..AH + AI


def _adset_row(camp_id, camp_name, adset, m: dict, currency: str, now_str: str) -> list:
    """Dòng Adset — tổng hợp từ Ads — 35 cột."""
    return [
        "",                                                          # A
        "Adset",                                                     # B
        camp_id,                                                     # C
        camp_name,                                                   # D
        adset.get("id", ""),                                         # E
        adset.get("name", ""),                                       # F
        "", "",                                                      # G H Ad
        "", "", "", "", "", "", "", "", "",                          # I..Q Creative
        STATUS_MAP.get(adset.get("status", ""), adset.get("status", "")),  # R
    ] + _insights_cols(m, currency) + [now_str]


def _ad_row(camp_id, camp_name, adset_id, adset_name, ad, m: dict,
            currency: str, now_str: str) -> list:
    """Dòng Ad — đầy đủ creative + insights — 35 cột."""
    c = extract_creative_info(ad.get("creative") or {})
    return [
        "",                            # A
        "Ad",                          # B
        camp_id,                       # C
        camp_name,                     # D
        adset_id,                      # E
        adset_name,                    # F
        ad.get("id", ""),              # G
        ad.get("name", ""),            # H
        c.get("creative_id", ""),      # I
        c.get("page_id", ""),          # J
        c.get("post_id", ""),          # K
        c.get("body", ""),             # L
        c.get("title", ""),            # M
        c.get("description", ""),      # N
        c.get("link", ""),             # O
        c.get("cta", ""),              # P
        c.get("thumbnail_url", ""),    # Q
        STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),  # R
    ] + _insights_cols(m, currency) + [now_str]


def build_rows(
    campaigns: list[dict],
    camp_insights_map: dict,
    adset_data_map: dict,
    ad_insights_map: dict,
    detail_selections: dict,
    currency: str,
    now_str: str,
) -> list[list]:
    status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}
    sorted_camps = sorted(
        campaigns,
        key=lambda c: (status_order.get(c.get("status", ""), 9), c.get("name", "")),
    )

    rows = []
    for camp in sorted_camps:
        camp_id = camp.get("id", "")
        camp_name = camp.get("name", "")
        is_selected = detail_selections.get(camp_id, False)

        camp_m = parse_insight_metrics(camp_insights_map.get(camp_id, {}))
        rows.append(_campaign_row(
            camp_id, camp_name, is_selected,
            camp_m, camp.get("status", ""), currency, now_str,
        ))

        if not is_selected:
            continue

        adsets = adset_data_map.get(camp_id, [])
        sorted_adsets = sorted(
            adsets,
            key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
        )

        for adset in sorted_adsets:
            adset_id = adset.get("id", "")
            adset_name = adset.get("name", "")
            ads = adset.get("_ads", [])
            sorted_ads = sorted(
                ads,
                key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
            )

            # Tổng hợp metrics Adset từ các Ad
            ad_metrics_list = [
                parse_insight_metrics(ad_insights_map.get(ad.get("id", ""), {}))
                for ad in sorted_ads
            ]
            adset_m = aggregate_metrics(ad_metrics_list) if ad_metrics_list else parse_insight_metrics({})

            rows.append(_adset_row(camp_id, camp_name, adset, adset_m, currency, now_str))

            for ad, ad_m in zip(sorted_ads, ad_metrics_list):
                rows.append(_ad_row(
                    camp_id, camp_name, adset_id, adset_name,
                    ad, ad_m, currency, now_str,
                ))

    return rows


def write_to_sheet(worksheet, rows: list[list]):
    last_col = col_to_letter(len(HEADERS))
    worksheet.update("A1", [HEADERS])
    last_row = worksheet.row_count
    if last_row >= 2:
        worksheet.batch_clear([f"A2:{last_col}{last_row}"])
    if rows:
        worksheet.update("A2", rows)


# ── Main ───────────────────────────────────────────────────────────────────────

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


def main():
    month_label = datetime.now().strftime("%m/%Y")
    print("Kết nối Google Sheets...")
    spreadsheet = connect_spreadsheet()

    print(f"Đọc danh sách tài khoản được chọn từ sheet '{AD_ACCOUNTS_SHEET}'...")
    selected_accounts = get_selected_accounts(spreadsheet)
    if not selected_accounts:
        print("Không có tài khoản nào được chọn. Hãy đánh TRUE vào cột 'Chọn Lấy Camp' trong sheet TKQC API.")
        return
    print(f"Tìm thấy {len(selected_accounts)} tài khoản được chọn.")

    dump_campaigns: dict[str, list] = {}
    dump_adsets: dict[str, list] = {}
    dump_ads: dict[str, list] = {}
    dump_insights_camp: dict[str, list] = {}
    dump_insights_ad: dict[str, list] = {}

    for acc in selected_accounts:
        acc_id = acc["id"]
        acc_name = acc["name"]
        currency = acc["currency"]
        print(f"\n[{acc_name}] Xử lý tháng {month_label}...")

        ws = get_or_create_worksheet(spreadsheet, acc_name)

        detail_selections = read_detail_selections(ws)
        selected_camp_ids = {cid for cid, v in detail_selections.items() if v}
        print(f"  → {len(selected_camp_ids)} campaign được chọn lấy chi tiết: {selected_camp_ids or '(chưa có)'}")

        # ── API 1: Campaigns ──────────────────────────────────────────────────
        campaigns = fetch_campaigns(acc_id)
        print(f"  → {len(campaigns)} campaign.")
        dump_campaigns[acc_name] = campaigns

        # ── API 2: Insights cấp campaign ─────────────────────────────────────
        camp_insights = fetch_insights_campaign_level(acc_id)
        camp_insights_map = {r["campaign_id"]: r for r in camp_insights if "campaign_id" in r}
        print(f"  → {len(camp_insights)} dòng insights campaign.")
        dump_insights_camp[acc_name] = camp_insights

        # ── API 3+4: Adset / Ad / Insights ad cho campaign được chọn ─────────
        adset_data_map: dict[str, list] = {}
        raw_adsets: list[dict] = []
        raw_ads: list[dict] = []
        ad_insights_map: dict[str, dict] = {}

        if selected_camp_ids:
            ad_insights = fetch_insights_ad_level(acc_id)
            ad_insights_map = {r["ad_id"]: r for r in ad_insights if "ad_id" in r}
            dump_insights_ad[acc_name] = ad_insights
            print(f"  → {len(ad_insights)} dòng insights ad.")

            total_adsets = total_ads = 0
            for camp in campaigns:
                camp_id = camp.get("id", "")
                if camp_id not in selected_camp_ids:
                    continue

                adsets = fetch_adsets(camp_id)
                for adset in adsets:
                    raw_adsets.append({k: v for k, v in adset.items() if k != "_ads"})
                    ads = fetch_ads(adset["id"])
                    raw_ads.extend(ads)
                    adset["_ads"] = ads
                    total_ads += len(ads)
                adset_data_map[camp_id] = adsets
                total_adsets += len(adsets)

            print(f"  → {total_adsets} adsets, {total_ads} ads.")

        dump_adsets[acc_name] = raw_adsets
        dump_ads[acc_name] = raw_ads

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        rows = build_rows(
            campaigns, camp_insights_map, adset_data_map,
            ad_insights_map, detail_selections, currency, now_str,
        )
        write_to_sheet(ws, rows)
        print(f"  → Đã ghi {len(rows)} dòng vào tab '{sanitize_sheet_name(acc_name)}'.")

    base_url = f"https://graph.facebook.com/{FB_API_VERSION}"
    print("\nLưu JSON...")
    save_json(dump_campaigns, "campaigns.json", {
        "endpoint": f"GET {base_url}/act_{{account_id}}/campaigns",
        "fields":   "id,name,status",
        "note":     "Toàn bộ campaign của tài khoản",
    })
    save_json(dump_adsets, "adsets.json", {
        "endpoint": f"GET {base_url}/{{campaign_id}}/adsets",
        "fields":   "id,name,status",
        "note":     "Adsets của các campaign được chọn lấy chi tiết",
    })
    save_json(dump_ads, "ads.json", {
        "endpoint": f"GET {base_url}/{{adset_id}}/ads",
        "fields":   "id,name,status,creative{id,name,object_story_spec,body,title,link_url,thumbnail_url,effective_object_story_id}",
        "note":     "Ads kèm creative của các adset được chọn",
    })
    save_json(dump_insights_camp, "insights_campaign.json", {
        "endpoint":      f"GET {base_url}/act_{{account_id}}/insights",
        "level":         "campaign",
        "date_preset":   "this_month",
        "fields":        f"campaign_id,{_INSIGHTS_FIELDS}",
        "note":          "Insights cấp campaign tháng này — dùng cho dòng Campaign trong sheet",
    })
    save_json(dump_insights_ad, "insights_ad.json", {
        "endpoint":      f"GET {base_url}/act_{{account_id}}/insights",
        "level":         "ad",
        "date_preset":   "this_month",
        "fields":        f"ad_id,adset_id,campaign_id,{_INSIGHTS_FIELDS}",
        "note":          "Insights cấp ad tháng này — dùng cho dòng Ad, tổng hợp Adset",
    })
    print("\nHoàn thành!")


if __name__ == "__main__":
    main()
