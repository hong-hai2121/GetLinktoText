"""
Lấy chi tiết chiến dịch (Campaign) cho các Tài Khoản Quảng Cáo (TKQC) được chọn.

Cách hoạt động:
    1. Đọc sheet "TKQC API" (do get_accounts.py ghi) → lọc các TKQC có cột
       "Chọn Lấy Camp" = TRUE.
    2. Với mỗi TKQC đã chọn: lấy toàn bộ campaign (/act_{id}/campaigns) + insights
       cấp campaign theo khoảng thời gian người dùng chọn lúc chạy.
    3. Ghi mỗi (TKQC × khoảng thời gian) thành 1 tab riêng tên 'Tên TKQC (Kỳ)'
       (vd 'Shop ABC (Hôm nay)'), mỗi campaign 1 dòng (sắp xếp theo spend giảm dần).
       → Chọn kỳ khác sẽ tạo tab khác, không ghi đè tab kỳ cũ.
    4. Cột "Chọn Lấy Chi Tiết" (TRUE/FALSE) cho người dùng đánh dấu campaign muốn
       mở rộng Adset/Ad — giá trị cũ được giữ nguyên qua mỗi lần chạy.
       → Chạy get_details.py sau đó để chèn Adset/Ad cho các campaign được chọn.

Chạy:  python get_campaigns.py
        (Lấy danh sách TKQC trực tiếp từ sheet TKQC API, không cần tham số.)
"""

import sys
import json
import time
import threading
from pathlib import Path
from datetime import datetime, date

# Console Windows có thể là cp1252 → ép UTF-8 để log tiếng Việt không crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import gspread
from google.oauth2.service_account import Credentials

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
except ImportError:
    tk = None

from config import ACCESS_TOKEN
from fb_api import graph_paginate, api_summary, RateLimitError

BASE_DIR = Path(__file__).parent

# Cùng Google Sheet với get_accounts.py — đọc tab "TKQC API" để biết TKQC nào TRUE.
SPREADSHEET_ID = "1aBWyX1f3yjMVbbJ7HxDbvS3ZvjBL9JsXc3Ycm_gTwAc"
TKQC_SHEET_NAME = "TKQC API"
FB_API_VERSION = "v20.0"

ACCOUNT_DELAY = 60  # giây nghỉ giữa mỗi TKQC — giảm tần suất gọi API (chống rate limit)

SERVICE_ACCOUNT_EMAIL = "ads-392@hai-ads-check.iam.gserviceaccount.com"

# Giá trị coi là "đã chọn" ở cột Chọn Lấy Camp (khớp get_accounts.py).
TRUE_VALUES = {"TRUE", "ĐÚNG", "1", "X", "✓"}

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
RESULT_TYPES = (
    PURCHASE_TYPES
    + LEAD_TYPES
    + INBOX_TYPES
    + ["post_engagement", "page_engagement", "link_click", "video_view", "app_install"]
)

# ── action_type cho các cột "kết quả" của campaign (chỉnh tại đây nếu FB đổi) ───
ACTION_RESULT        = "onsite_conversion.messaging_conversation_started_7d"  # cột Kết Quả
ACTION_MESSAGING     = "onsite_conversion.messaging_conversation_started_7d"  # Lượt bắt đầu trò chuyện
ACTION_ORDER_CREATED = "omni_purchase"                                        # Đơn Hàng Đã Tạo

# Tên cột khớp Trình quản lý quảng cáo (tiếng Việt). A + B giữ logic cũ
# (Chọn Lấy Chi Tiết ↔ get_details, Cấp = Campaign/Adset/Ad). C trở đi là thông tin
# campaign. Adset/Ad (do get_details ghi) chỉ điền các cột có nghĩa (C, D, E + metric).
COL_CAMP_ID = "ID Chiến Dịch"   # dùng làm khóa nối với get_details/tong_hop
COL_SPEND   = "Số Tiền Đã Chi Tiêu"  # build_headers() gắn thêm (Kỳ) vào cột này

# Thứ tự & cách tính từng cột định nghĩa tập trung ở COLUMNS (mục Insights metrics).
# HEADERS được derive từ COLUMNS. Muốn đổi thứ tự cột → sửa COLUMNS, mọi nơi tự theo.

COLOR_SELECTED = {"red": 0.85, "green": 0.93, "blue": 0.83}  # Chọn Lấy Chi Tiết = TRUE → xanh nhạt
COLOR_DEFAULT  = {"red": 1.0,  "green": 1.0,  "blue": 1.0}

# Chữ mặc định: màu đen, không in đậm — ép lại để tránh kế thừa định dạng cũ.
TEXT_DEFAULT = {"bold": False, "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

try:
    from config import DATE_PRESET, TIME_RANGE
except ImportError:
    DATE_PRESET = "this_month"
    TIME_RANGE: dict = {}

# Các khoảng thời gian cho người dùng chọn trước khi chạy: (nhãn hiển thị, date_preset FB).
DATE_PRESET_OPTIONS = [
    ("Hôm nay",         "today"),
    ("Hôm qua",         "yesterday"),
    ("7 ngày qua",      "last_7d"),
    ("28 ngày qua",     "last_28d"),
    ("Tháng này",       "this_month"),
    ("Toàn thời gian",  "maximum"),
]
DEFAULT_PRESET_LABEL = "Tháng này"

# Khoảng thời gian được chọn lúc chạy (None → dùng DATE_PRESET trong config).
SELECTED_PRESET: str | None = None


def _active_preset() -> str:
    """date_preset đang dùng: ưu tiên lựa chọn lúc chạy, fallback về config."""
    return SELECTED_PRESET if SELECTED_PRESET is not None else DATE_PRESET


def current_range_label() -> str:
    """Nhãn tiếng Việt của khoảng thời gian đang dùng (cho log / tiêu đề cột)."""
    preset = _active_preset()
    for label, value in DATE_PRESET_OPTIONS:
        if value == preset:
            return label
    return preset or "Tùy chọn"


def _date_params() -> dict:
    preset = _active_preset()
    if preset:
        return {"date_preset": preset}
    return {"time_range": json.dumps(TIME_RANGE)}


_INSIGHTS_FIELD_LIST = [
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "actions",
    "cost_per_action_type",
    "video_thruplay_watched_actions",
    "date_start",
    "date_stop",
]
_INSIGHTS_FIELDS = ",".join(_INSIGHTS_FIELD_LIST)

AD_REPORT_FIELDS = [
    "ad_id",
    "ad_name",
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "creative",
    *_INSIGHTS_FIELD_LIST,
    "post_reactions",
    "post_comments",
    "post_shares",
]

# creative and post_* are assembled after the Insights call. creative comes from
# /ads, while post_* is derived from the action list Meta already returns.
AD_INSIGHTS_FIELDS = ",".join(
    field for field in AD_REPORT_FIELDS
    if field not in {"creative", "post_reactions", "post_comments", "post_shares"}
)


# ── Google Sheets helpers ────────────────────────────────────────────────────

def col_to_letter(n: int) -> str:
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def connect_spreadsheet(credentials_file: str = "service_account.json"):
    creds = Credentials.from_service_account_file(
        str(BASE_DIR / credentials_file), scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def sanitize_sheet_name(name: str) -> str:
    import re
    name = re.sub(r'[\\/*?\[\]:]', '', name)
    return name[:100].strip() or "Unknown"


def get_or_create_worksheet(spreadsheet, title: str):
    safe = sanitize_sheet_name(title)
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if safe in existing:
        return existing[safe]
    return spreadsheet.add_worksheet(title=safe, rows=2000, cols=26)


def account_tab_title(acc_name: str, preset_label: str | None = None) -> str:
    """Tên tab cho 1 TKQC theo khoảng thời gian: 'Tên TKQC (Kỳ)'.
    Mỗi kỳ (Hôm nay / Hôm qua / Toàn thời gian…) là 1 tab riêng, không ghi đè lẫn nhau."""
    label = preset_label or current_range_label()
    return sanitize_sheet_name(f"{acc_name} ({label})")


def parse_tab_title(title: str) -> tuple[str, str | None]:
    """Tách 'Tên TKQC (Kỳ)' → (tên_TKQC, date_preset).
    Trả (title, None) nếu hậu tố trong ngoặc không khớp khoảng thời gian hợp lệ
    (vd 'TKQC API' hay tab khác → bỏ qua)."""
    import re
    m = re.match(r"^(.*) \((.+)\)$", title)
    if not m:
        return title, None
    acc_name, label = m.group(1), m.group(2)
    for lbl, value in DATE_PRESET_OPTIONS:
        if lbl == label:
            return acc_name, value
    return title, None


def build_headers() -> list[str]:
    """HEADERS với cột Số Tiền Đã Chi Tiêu kèm khoảng thời gian đang chọn (tìm theo
    tên nên không phụ thuộc vị trí cột)."""
    headers = HEADERS.copy()
    try:
        headers[headers.index(COL_SPEND)] = f"{COL_SPEND} ({current_range_label()})"
    except ValueError:
        pass
    return headers


def write_to_sheet(worksheet, rows: list[list]):
    worksheet.clear()
    # Đặt kiểu dữ liệu cột TRƯỚC khi ghi để cột ID (Plain Text) không làm tròn ID 17 số.
    worksheet.spreadsheet.batch_update(
        {"requests": number_format_requests(worksheet.id)})
    worksheet.update(values=[build_headers()], range_name="A1")
    if not rows:
        return
    worksheet.update(values=rows, range_name="A2", value_input_option="RAW")

    last_col = col_to_letter(len(HEADERS))
    formats = []
    for i, row in enumerate(rows):
        sheet_row = i + 2
        is_selected = row[0] == "TRUE"  # cột A = Chọn Lấy Chi Tiết
        formats.append({
            "range":  f"A{sheet_row}:{last_col}{sheet_row}",
            "format": {"backgroundColor": COLOR_SELECTED if is_selected else COLOR_DEFAULT,
                       "textFormat": TEXT_DEFAULT},
        })
    worksheet.batch_format(formats)


# ── Facebook Graph API ─────────────────────────────────────────────────────────

def _act_id(account_id: str) -> str:
    account_id = account_id.strip()
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def paginate(url: str, params: dict) -> list[dict]:
    """Ủy thác sang fb_api.graph_paginate (đếm + log + retry rate limit).
    Dùng chung bởi get_details.py."""
    return graph_paginate(url, params)


def fetch_campaigns(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/campaigns"
    params = {
        "fields": "id,name,status,effective_status,objective,daily_budget",
        "access_token": ACCESS_TOKEN,
        "limit": 200,
    }
    return graph_paginate(url, params, label="act_{id}/campaigns")


def fetch_insights_campaign_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/insights"
    params = {
        "level": "campaign",
        **_date_params(),
        "fields": f"campaign_id,campaign_name,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return graph_paginate(url, params, label="act_{id}/insights")


def fetch_insights_ad_level_report(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/insights"
    params = {
        "level": "ad",
        **_date_params(),
        "fields": AD_INSIGHTS_FIELDS,
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return graph_paginate(url, params, label="act_{id}/insights?level=ad")


def fetch_ad_creatives(account_id: str) -> dict[str, dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/ads"
    params = {
        "fields": "id,creative",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    rows = graph_paginate(url, params, label="act_{id}/ads")
    return {
        row["id"]: row.get("creative", {})
        for row in rows
        if row.get("id")
    }


# ── Insights metrics ───────────────────────────────────────────────────────────

def safe_float(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _sum_actions(action_list: list, types: list) -> float:
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


def _format_action_count(value: float):
    return int(value) if value else ""


def build_ad_report_rows(ad_insights: list[dict], creative_by_ad_id: dict[str, dict]) -> list[dict]:
    rows = []
    for insight in ad_insights:
        ad_id = insight.get("ad_id", "")
        actions = insight.get("actions") or []
        computed = {
            "creative": creative_by_ad_id.get(ad_id, {}),
            "post_reactions": _format_action_count(_sum_actions(actions, ["post_reaction"])),
            "post_comments": _format_action_count(_sum_actions(actions, ["comment", "post_comment"])),
            "post_shares": _format_action_count(_sum_actions(actions, ["post"])),
        }
        rows.append({
            field: computed[field] if field in computed else insight.get(field, "")
            for field in AD_REPORT_FIELDS
        })
    return rows


def _get_primary_result(insight: dict) -> tuple[float, float]:
    cost_per_action = insight.get("cost_per_action_type") or []
    actions = insight.get("actions") or []
    cost_map = {i.get("action_type", ""): safe_float(i.get("value")) for i in cost_per_action}
    action_map = {i.get("action_type", ""): safe_float(i.get("value")) for i in actions}
    for atype in RESULT_TYPES:
        cpx = cost_map.get(atype, 0.0)
        if cpx > 0:
            return action_map.get(atype, 0.0), cpx
    return 0.0, 0.0


def parse_insight_metrics(insight: dict) -> dict:
    spend  = safe_float(insight.get("spend"))
    impr   = safe_float(insight.get("impressions"))
    clicks = safe_float(insight.get("clicks"))
    reach  = safe_float(insight.get("reach"))
    ctr  = safe_float(insight.get("ctr"))
    cpc  = safe_float(insight.get("cpc"))
    cpm  = safe_float(insight.get("cpm"))
    freq = safe_float(insight.get("frequency"))

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
        "spend": spend, "impr": impr, "clicks": clicks, "ctr": ctr,
        "cpc": cpc, "cpm": cpm, "reach": reach, "freq": freq,
        "inbox": inbox, "cpi": spend / inbox if inbox > 0 else 0.0,
        "leads": leads, "cpl": spend / leads if leads > 0 else 0.0,
        "purchases": purchases, "cps": spend / purchases if purchases > 0 else 0.0,
        "revenue": revenue, "roas": roas,
        "ket_qua": ket_qua, "cpkq": cpkq,
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
        "spend": spend, "impr": impr, "clicks": clicks,
        "ctr":  clicks / impr * 100  if impr      > 0 else 0.0,
        "cpc":  spend  / clicks      if clicks    > 0 else 0.0,
        "cpm":  spend  / impr * 1000 if impr      > 0 else 0.0,
        "reach": reach,
        "freq": impr   / reach       if reach     > 0 else 0.0,
        "inbox": inbox,
        "cpi":  spend  / inbox       if inbox     > 0 else 0.0,
        "leads": leads,
        "cpl":  spend  / leads       if leads     > 0 else 0.0,
        "purchases": purchases,
        "cps":  spend  / purchases   if purchases > 0 else 0.0,
        "revenue": revenue,
        "roas": revenue / spend      if spend     > 0 else 0.0,
        "ket_qua": ket_qua,
        "cpkq": spend  / ket_qua     if ket_qua   > 0 else 0.0,
    }


def _num(v, decimals=0):
    """Số > 0 → SỐ THẬT đã làm tròn; 0/None/không parse được → ô trống.
    Ghi RAW vào Sheet là số thật để type Number/Currency/Decimal của cột hiển thị đúng
    (định dạng do number_format_requests đặt cho cả cột)."""
    f = safe_float(v)
    return round(f, decimals) if f > 0 else ""


def _frac(v):
    """Tỉ lệ % (giá trị đã nhân 100 sẵn, vd CTR=1.23) → PHÂN SỐ 0.0123 cho ô kiểu
    Percent (Sheets tự nhân 100 khi hiển thị → '1,23%'). 0/None → ô trống."""
    f = safe_float(v)
    return round(f / 100, 6) if f > 0 else ""


def _budget(v):
    """daily_budget (FB trả chuỗi theo đơn vị nhỏ nhất của tiền tệ) → số nguyên thật."""
    if v in (None, "", 0, "0"):
        return ""
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return v


# Mốc serial của Google Sheets/Excel: 1899-12-30 = 0.
_SHEETS_EPOCH = date(1899, 12, 30)


def _date_serial(v):
    """Ngày FB 'YYYY-MM-DD' → SỐ serial ngày của Sheets (để ô là kiểu Date thật,
    hiển thị dd/mm/yyyy theo number format). Rỗng/không parse được → giữ nguyên."""
    if not v:
        return ""
    try:
        d = datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return v
    return (d - _SHEETS_EPOCH).days


def format_actions(items) -> str:
    """Mảng [{action_type, value}] → chuỗi 'type: value; ...' để đưa vào 1 ô.
    Dùng chung cho cột Hành Động (actions) và Chi Phí / Hành Động (cost_per_action_type)."""
    if not items:
        return ""
    parts = []
    for it in items:
        atype = it.get("action_type", "")
        if not atype:
            continue
        f = safe_float(it.get("value"))
        val = str(int(f)) if f == int(f) else f"{f:.2f}"
        parts.append(f"{atype}: {val}")
    return "; ".join(parts)


def _action_value(actions, action_type: str) -> float:
    """value của 1 action_type cụ thể trong mảng actions (0.0 nếu không có)."""
    for it in (actions or []):
        if it.get("action_type") == action_type:
            return safe_float(it.get("value"))
    return 0.0


def _merge_action_arrays(arrays) -> list:
    """Gộp nhiều mảng actions → 1 mảng cộng dồn value theo action_type (cho Adset)."""
    totals: dict[str, float] = {}
    for arr in arrays:
        for it in (arr or []):
            atype = it.get("action_type", "")
            if atype:
                totals[atype] = totals.get(atype, 0.0) + safe_float(it.get("value"))
    return [{"action_type": t, "value": v} for t, v in totals.items()]


def aggregate_insights(insights: list[dict]) -> dict:
    """Gộp nhiều dict insight thô (các Ad) → 1 dict tổng cho Adset.
    Cộng spend/impressions/clicks/reach + gộp actions; ctr/cpc/cpm/frequency để
    _insight_metric_cols tự tính lại. cost_per_action_type bỏ trống (không cộng dồn được)."""
    if not insights:
        return {}
    return {
        "spend":       sum(safe_float(i.get("spend"))       for i in insights),
        "impressions": sum(safe_float(i.get("impressions")) for i in insights),
        "clicks":      sum(safe_float(i.get("clicks"))      for i in insights),
        "reach":       sum(safe_float(i.get("reach"))       for i in insights),
        "actions":     _merge_action_arrays([i.get("actions") for i in insights]),
        "date_start":  insights[0].get("date_start", ""),
        "date_stop":   insights[0].get("date_stop", ""),
    }


def _metrics(insight: dict) -> dict:
    """Tính toàn bộ giá trị metric từ 1 dict insight thô — dùng chung Campaign/Adset/Ad.
    ctr/cpc/cpm/frequency: ưu tiên giá trị FB trả, thiếu thì tự tính từ số gốc."""
    spend  = safe_float(insight.get("spend"))
    impr   = safe_float(insight.get("impressions"))
    clicks = safe_float(insight.get("clicks"))
    reach  = safe_float(insight.get("reach"))
    actions = insight.get("actions") or []
    result    = _action_value(actions, ACTION_RESULT)
    order     = _action_value(actions, ACTION_ORDER_CREATED)
    messaging = _action_value(actions, ACTION_MESSAGING)
    return {
        "spend": spend, "impr": impr, "reach": reach, "clicks": clicks,
        "ctr":  safe_float(insight.get("ctr"))       or (clicks / impr * 100 if impr   > 0 else 0),
        "cpc":  safe_float(insight.get("cpc"))        or (spend / clicks      if clicks > 0 else 0),
        "cpm":  safe_float(insight.get("cpm"))        or (spend / impr * 1000 if impr   > 0 else 0),
        "freq": safe_float(insight.get("frequency"))  or (impr / reach        if reach  > 0 else 0),
        "result":         result,
        "cost_result":    spend / result    if result    > 0 else 0,
        "order":          order,
        "cost_order":     spend / order      if order     > 0 else 0,
        "messaging":      messaging,
        "cost_messaging": spend / messaging  if messaging > 0 else 0,
        "actions_str":    format_actions(actions),
        "cpa_str":        format_actions(insight.get("cost_per_action_type")),
        "date_start":     insight.get("date_start", ""),
        "date_stop":      insight.get("date_stop", ""),
    }


# ── Getter cho cột entity (chỉ Campaign có hiệu lực; Adset/Ad để trống) ─────────

def _g_chon(ctx):
    if ctx["level"] != "Campaign":
        return ""                       # Adset/Ad: cột Chọn để trống
    sel = ctx["m"]["spend"] > 0 if ctx["auto_by_spend"] else ctx["is_selected"]
    return "TRUE" if sel else "FALSE"

def _g_status(ctx):
    s = ctx["entity"].get("status", "")
    return STATUS_MAP.get(s, s)

def _g_eff(ctx):
    if ctx["level"] != "Campaign":
        return ""
    s = ctx["entity"].get("effective_status", "")
    return STATUS_MAP.get(s, s)

def _g_objective(ctx):
    return ctx["entity"].get("objective", "") if ctx["level"] == "Campaign" else ""

def _g_budget(ctx):
    return _budget(ctx["entity"].get("daily_budget")) if ctx["level"] == "Campaign" else ""


# ── COLUMNS: nguồn chân lý duy nhất cho THỨ TỰ + CÁCH TÍNH từng cột ─────────────
# Mỗi cột: (header, metric?, getter(ctx)). ctx = {level, camp_id, entity, m,
# is_selected, auto_by_spend}. metric=True → giá trị suy từ insight (get_details sẽ
# refresh khi cập nhật dòng Campaign); metric=False → entity/Chọn (get_details giữ
# nguyên). ĐỔI THỨ TỰ CỘT = đổi thứ tự danh sách này; mọi file tự theo.
COLUMNS: list[tuple[str, bool, object]] = [
    ("Chọn Lấy Chi Tiết",                       False, _g_chon),
    ("Cấp",                                     False, lambda c: c["level"]),
    (COL_CAMP_ID,                               False, lambda c: c["camp_id"]),
    ("Tên Chiến Dịch",                          False, lambda c: c["entity"].get("name", "")),
    ("Trạng Thái",                              False, _g_status),
    ("Tình Trạng Phân Phối",                    False, _g_eff),
    ("Lượt Bắt Đầu Cuộc Trò Chuyện Qua Tin Nhắn", True, lambda c: _num(c["m"]["messaging"])),
    ("Chi Phí / Lượt Bắt Đầu Cuộc Trò Chuyện",  True,  lambda c: _num(c["m"]["cost_messaging"], 2)),
    ("Đơn Hàng Đã Tạo",                         True,  lambda c: _num(c["m"]["order"])),
    ("Chi Phí / Đơn Hàng",                      True,  lambda c: _num(c["m"]["cost_order"], 2)),
    ("Kết Quả",                                 True,  lambda c: _num(c["m"]["result"])),
    ("Chi Phí / Kết Quả",                       True,  lambda c: _num(c["m"]["cost_result"], 2)),
    ("Ngân Sách Hằng Ngày",                     False, _g_budget),
    (COL_SPEND,                                 True,  lambda c: _num(c["m"]["spend"], 2)),
    ("Lượt Hiển Thị",                           True,  lambda c: _num(c["m"]["impr"])),
    ("Người Tiếp Cận",                          True,  lambda c: _num(c["m"]["reach"])),
    ("Tần Suất",                                True,  lambda c: _num(c["m"]["freq"], 2)),
    ("Số Lần Nhấp",                             True,  lambda c: _num(c["m"]["clicks"])),
    ("CTR (%)",                                 True,  lambda c: _frac(c["m"]["ctr"])),
    ("CPC",                                     True,  lambda c: _num(c["m"]["cpc"], 2)),
    ("CPM",                                     True,  lambda c: _num(c["m"]["cpm"], 2)),
    ("Hành Động",                               True,  lambda c: c["m"]["actions_str"]),
    ("Chi Phí / Hành Động",                     True,  lambda c: c["m"]["cpa_str"]),
    ("Mục Tiêu",                                False, _g_objective),
    ("Ngày Bắt Đầu",                            True,  lambda c: _date_serial(c["m"]["date_start"])),
    ("Ngày Kết Thúc",                           True,  lambda c: _date_serial(c["m"]["date_stop"])),
]

HEADERS = [h for h, _metric, _get in COLUMNS]


# ── Kiểu dữ liệu (numberFormat) cho từng cột ────────────────────────────────────
# Áp THEO CỘT (cả cột từ dòng 2) nên kỳ mới / dòng Adset-Ad chèn thêm đều tự đúng
# kiểu, không phải chỉnh tay. Mỗi mục: (type Sheets, pattern). Khớp theo TÊN cột
# trong COLUMNS → suy ra vị trí, nên đổi thứ tự cột vẫn đúng.
FMT_TEXT     = ("TEXT",     None)        # Plain Text — ID 17 số không bị làm tròn
FMT_NUMBER   = ("NUMBER",   "#,##0")     # số nguyên, phân tách hàng nghìn
FMT_DECIMAL  = ("NUMBER",   "#,##0.00")  # số thập phân (Tần Suất)
FMT_CURRENCY = ("CURRENCY", '#,##0" ₫"') # tiền VND (đổi ' ₫' nếu TKQC dùng tiền khác)
FMT_PERCENT  = ("PERCENT",  "0.00%")     # CTR — ô chứa phân số, Sheets nhân 100 khi hiển thị
FMT_DATE     = ("DATE",     "dd/mm/yyyy") # ngày tháng năm — ô chứa số serial ngày

_COL_FORMAT_BY_HEADER = {
    "Cấp":                                       FMT_TEXT,
    COL_CAMP_ID:                                 FMT_TEXT,
    "Tên Chiến Dịch":                            FMT_TEXT,
    "Trạng Thái":                                FMT_TEXT,
    "Tình Trạng Phân Phối":                      FMT_TEXT,
    "Lượt Bắt Đầu Cuộc Trò Chuyện Qua Tin Nhắn": FMT_NUMBER,
    "Chi Phí / Lượt Bắt Đầu Cuộc Trò Chuyện":    FMT_CURRENCY,
    "Đơn Hàng Đã Tạo":                           FMT_NUMBER,
    "Chi Phí / Đơn Hàng":                        FMT_CURRENCY,
    "Kết Quả":                                   FMT_NUMBER,
    "Chi Phí / Kết Quả":                         FMT_CURRENCY,
    "Ngân Sách Hằng Ngày":                       FMT_CURRENCY,
    COL_SPEND:                                   FMT_CURRENCY,
    "Lượt Hiển Thị":                             FMT_NUMBER,
    "Người Tiếp Cận":                            FMT_NUMBER,
    "Tần Suất":                                  FMT_DECIMAL,
    "Số Lần Nhấp":                               FMT_NUMBER,
    "CTR (%)":                                   FMT_PERCENT,
    "CPC":                                       FMT_CURRENCY,
    "CPM":                                       FMT_CURRENCY,
    "Ngày Bắt Đầu":                              FMT_DATE,
    "Ngày Kết Thúc":                             FMT_DATE,
}
# Danh sách khớp vị trí COLUMNS (None = cột để mặc định, không áp kiểu).
COLUMN_FORMATS = [_COL_FORMAT_BY_HEADER.get(h) for h, _m, _g in COLUMNS]


def number_format_requests(sheet_id: int, start_row: int = 1) -> list[dict]:
    """repeatCell requests đặt numberFormat (kiểu dữ liệu) cho từng cột theo
    COLUMN_FORMATS. start_row 0-based, half-open (mặc định 1 = bỏ hàng header, áp cả
    cột bên dưới). Dùng với spreadsheet.batch_update({'requests': [...]})."""
    reqs = []
    for idx, fmt in enumerate(COLUMN_FORMATS):
        if not fmt:
            continue
        typ, pattern = fmt
        number_format = {"type": typ}
        if pattern:
            number_format["pattern"] = pattern
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startColumnIndex": idx,
                      "endColumnIndex": idx + 1, "startRowIndex": start_row},
            "cell": {"userEnteredFormat": {"numberFormat": number_format}},
            "fields": "userEnteredFormat.numberFormat"}})
    return reqs


def _build_row(level: str, camp_id: str, entity: dict, insight: dict,
               is_selected: bool = False, auto_by_spend: bool = False) -> list:
    ctx = {"level": level, "camp_id": camp_id, "entity": entity,
           "m": _metrics(insight), "is_selected": is_selected, "auto_by_spend": auto_by_spend}
    return [get(ctx) for _h, _metric, get in COLUMNS]


def _campaign_row(meta: dict, insight: dict, is_selected: bool,
                  auto_by_spend: bool = False) -> list:
    """Dòng Campaign theo thứ tự COLUMNS (entity từ /campaigns, metric từ insight)."""
    return _build_row("Campaign", meta.get("id", ""), meta, insight, is_selected, auto_by_spend)


def build_detail_row(level: str, camp_id: str, entity: dict, insight: dict) -> list:
    """Dòng Adset/Ad (gọi bởi get_details). C = camp_id tham chiếu; cột campaign-only
    (Mục Tiêu/Ngân Sách/Tình Trạng) tự để trống vì level != 'Campaign'."""
    return _build_row(level, camp_id, entity, insight)


def merge_metric_row(existing_row: list, insight: dict) -> list:
    """Dùng cho get_details refresh dòng Campaign: giữ nguyên cột non-metric
    (Chọn + entity) từ existing_row, chỉ thay cột metric bằng giá trị mới từ insight."""
    ctx = {"level": "Campaign", "camp_id": "", "entity": {},
           "m": _metrics(insight), "is_selected": False, "auto_by_spend": False}
    out = []
    for i, (_h, metric, get) in enumerate(COLUMNS):
        if metric:
            out.append(get(ctx))
        else:
            out.append(existing_row[i] if i < len(existing_row) else "")
    return out


# ── Core ─────────────────────────────────────────────────────────────────────

def load_selected_accounts(spreadsheet) -> list[dict]:
    """Đọc sheet TKQC API → [{id, name}] cho các TKQC có Chọn Lấy Camp = TRUE."""
    try:
        ws = spreadsheet.worksheet(TKQC_SHEET_NAME)
    except Exception:
        raise RuntimeError(
            f"Không tìm thấy sheet '{TKQC_SHEET_NAME}'. Hãy chạy get_accounts.py trước "
            "để tạo danh sách TKQC."
        )

    values = ws.get_all_values()
    if len(values) < 2:
        return []

    header = values[0]
    try:
        id_col   = header.index("ID Tài Khoản")
        name_col = header.index("Tên Tài Khoản")
        chon_col = header.index("Chọn Lấy Camp")
    except ValueError:
        raise RuntimeError(
            f"Sheet '{TKQC_SHEET_NAME}' thiếu cột bắt buộc "
            "(ID Tài Khoản / Tên Tài Khoản / Chọn Lấy Camp)."
        )

    accounts = []
    for row in values[1:]:
        acc_id = row[id_col].strip().removeprefix("act_") if id_col < len(row) else ""
        if not acc_id:
            continue
        chon = row[chon_col].strip().upper() if chon_col < len(row) else ""
        if chon in TRUE_VALUES:
            name = (row[name_col].strip() if name_col < len(row) else "") or acc_id
            accounts.append({"id": acc_id, "name": name})
    return accounts


def get_all_accounts(spreadsheet) -> list[dict]:
    """Đọc sheet TKQC API, trả về TẤT CẢ tài khoản kèm cờ 'selected' (Chọn Lấy Camp).
    Dùng bởi GUI của get_details.py để liệt kê tài khoản."""
    ws = spreadsheet.worksheet(TKQC_SHEET_NAME)
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    try:
        id_col   = header.index("ID Tài Khoản")
        name_col = header.index("Tên Tài Khoản")
        chon_col = header.index("Chọn Lấy Camp")
    except ValueError as e:
        raise RuntimeError(f"Sheet '{TKQC_SHEET_NAME}' thiếu cột: {e}.")
    da_chi_col = header.index("Đã Chi") if "Đã Chi" in header else -1

    accounts = []
    for row in values[1:]:
        acc_id   = row[id_col].strip().removeprefix("act_") if id_col   < len(row) else ""
        acc_name = row[name_col].strip()                    if name_col < len(row) else ""
        chon_val = row[chon_col].strip().upper()            if chon_col < len(row) else ""
        da_chi   = row[da_chi_col].strip() if da_chi_col >= 0 and da_chi_col < len(row) else ""
        if acc_id:
            accounts.append({
                "id":       acc_id,
                "name":     acc_name or acc_id,
                "selected": chon_val in TRUE_VALUES,
                "da_chi":   da_chi,
            })
    return accounts


def list_campaign_tabs(spreadsheet) -> list[dict]:
    """Quét các tab dạng 'Tên TKQC (Kỳ)' do get_campaigns tạo.
    Trả [{title, acc_id, acc_name, preset, preset_label}] — chỉ tab khớp 1 TKQC
    trong sheet TKQC API và 1 khoảng thời gian hợp lệ (bỏ TKQC API, snapshot...).
    Dùng chung bởi get_details.py và tong_hop.py."""
    accounts = get_all_accounts(spreadsheet)
    acc_by_name     = {sanitize_sheet_name(a["name"]).strip(): a for a in accounts}
    label_by_preset = {value: label for label, value in DATE_PRESET_OPTIONS}

    tabs = []
    for ws in spreadsheet.worksheets():
        acc_name, preset = parse_tab_title(ws.title)
        if preset is None:
            continue
        acc = acc_by_name.get(acc_name.strip())
        if acc is None:
            continue  # tên trong tab không khớp TKQC nào → bỏ qua
        tabs.append({
            "title":        ws.title,
            "acc_id":       acc["id"],
            "acc_name":     acc["name"],
            "preset":       preset,
            "preset_label": label_by_preset.get(preset, preset),
        })
    tabs.sort(key=lambda t: (t["acc_name"], t["preset_label"]))
    return tabs


def read_detail_selections(worksheet) -> dict[str, bool]:
    """Đọc cột 'Chọn Lấy Chi Tiết' trong tab tài khoản → {campaign_id: bool}.
    Chỉ xét dòng có Cấp = 'Campaign'."""
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
        camp_id_col = header.index(COL_CAMP_ID)
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
            selections[camp_id] = chon_val in TRUE_VALUES
    return selections


def build_rows_for_account(worksheet, acc_id: str,
                           auto_by_spend: bool = False,
                           raw_out: dict | None = None) -> list[list]:
    """Lấy toàn bộ campaign + insights của 1 TKQC, trả về list dòng (spend giảm dần).
    Giữ nguyên cột 'Chọn Lấy Chi Tiết' cũ trong tab để không mất lựa chọn; campaign
    MỚI (chưa có trong tab) mặc định TRUE.
    Nếu truyền raw_out, ghi dữ liệu thô (campaigns + insights) vào đó để xuất JSON."""
    detail_selections = read_detail_selections(worksheet)
    camps = fetch_campaigns(acc_id)
    if raw_out is not None:
        raw_out["campaigns"] = camps
    ins = fetch_insights_campaign_level(acc_id)
    if raw_out is not None:
        raw_out["campaign_insights"] = ins
    insights = {r["campaign_id"]: r for r in ins if "campaign_id" in r}

    rows = []
    for meta in camps:
        cid = meta.get("id")
        if not cid:
            continue
        insight = insights.get(cid, {})
        spend = safe_float(insight.get("spend"))
        rows.append((spend, _campaign_row(
            meta, insight, detail_selections.get(cid, True), auto_by_spend)))
    rows.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in rows]


# ── JSON output (dữ liệu thô để kiểm tra / chỉnh logic) ─────────────────────────

JSON_FILE = BASE_DIR / "get_campaigns.json"


def save_json(dump: dict, api_info: dict | None = None):
    """Ghi dữ liệu thô đã lấy (campaigns + insights cấp campaign) theo từng tab ra
    file để đối chiếu khi số trên Sheet trông lạ."""
    payload: dict = {}
    if api_info:
        payload["_api"] = api_info
    payload.update(dump)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run(log):
    log(f"⏰ Khoảng thời gian: {current_range_label()}  (date_preset={_active_preset()})")
    log(f"Kết nối Google Sheets ({SPREADSHEET_ID})...")
    try:
        ss = connect_spreadsheet()
    except Exception as e:
        raise RuntimeError(
            f"Không mở được Google Sheet. Hãy chia sẻ sheet cho service account "
            f"'{SERVICE_ACCOUNT_EMAIL}' (quyền Editor).\nChi tiết: {e}"
        )
    log(f"  → OK: {ss.title}")

    log(f"Đọc TKQC được chọn (Chọn Lấy Camp = TRUE) từ sheet '{TKQC_SHEET_NAME}'...")
    accounts = load_selected_accounts(ss)
    if not accounts:
        log("Không có TKQC nào được chọn (Chọn Lấy Camp = TRUE). Dừng.")
        return
    log(f"  → {len(accounts)} TKQC được chọn.")

    dump: dict[str, dict] = {}   # {tab_title: {acc_id, acc_name, campaigns, campaign_insights}}
    try:
        for i, acc in enumerate(accounts, 1):
            acc_id, acc_name = acc["id"], acc["name"]
            if i > 1:
                log(f"  ⏱ Nghỉ {ACCOUNT_DELAY}s trước TKQC tiếp theo...")
                time.sleep(ACCOUNT_DELAY)
            log(f"[{i}/{len(accounts)}] {acc_name}: lấy campaign + insights...")
            title = account_tab_title(acc_name)  # tab riêng theo kỳ: 'Tên TKQC (Kỳ)'
            ws = get_or_create_worksheet(ss, title)  # lấy tab trước để đọc 'Chọn Lấy Chi Tiết' cũ
            raw = {"acc_id": acc_id, "acc_name": acc_name}
            dump[title] = raw  # đăng ký trước để rate-limit vẫn giữ phần đã lấy
            try:
                rows = build_rows_for_account(ws, acc_id, raw_out=raw)
            except RateLimitError:
                raise  # rate limit → dừng hẳn, để handler ngoài lưu/log
            except RuntimeError as e:
                log(f"    ⚠ Bỏ qua (lỗi: {e})")
                continue
            write_to_sheet(ws, rows)
            log(f"    → {len(rows)} campaign → tab '{title}'")
    finally:
        base = f"https://graph.facebook.com/{FB_API_VERSION}"
        save_json(dump, {
            "campaigns":         f"GET {base}/act_{{id}}/campaigns  (fields=id,name,status,effective_status,objective,daily_budget)",
            "insights_campaign": f"GET {base}/act_{{id}}/insights  (level=campaign, fields=campaign_id,campaign_name,{_INSIGHTS_FIELDS})",
            "date":              _date_params(),
            "preset":            _active_preset(),
            "note":              "Mỗi tab: acc_id, acc_name, campaigns[], campaign_insights[]",
        })
        log(f"  JSON thô → {JSON_FILE}")

    api_summary()
    log("\n✓ Hoàn thành!")


# ── GUI tiến trình ─────────────────────────────────────────────────────────────

class ProgressApp(tk.Tk):
    BG = "#0f172a"
    FG = "#e2e8f0"
    ACCENT = "#3b82f6"

    def __init__(self):
        super().__init__()
        self.title("Lấy chiến dịch của TKQC được chọn")

        w, h = 640, 420
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg=self.BG)

        tk.Label(self, text="Lấy chiến dịch cho các TKQC có 'Chọn Lấy Camp' = TRUE "
                 f"trong sheet '{TKQC_SHEET_NAME}'", bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 10, "bold"), anchor="w", justify="left",
                 wraplength=600).pack(fill="x", padx=14, pady=(12, 4))

        # ── Chọn khoảng thời gian insights trước khi chạy ──────────────────────
        opts = tk.Frame(self, bg=self.BG)
        opts.pack(fill="x", padx=14, pady=(4, 6))
        tk.Label(opts, text="Khoảng thời gian:", bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 9)).pack(side="left")
        s0 = ttk.Style(self)
        s0.theme_use("clam")
        s0.configure("D.TCombobox", fieldbackground="#1e293b", background="#1e293b",
                     foreground=self.FG, arrowcolor=self.FG, borderwidth=0)
        self._preset_var = tk.StringVar(value=DEFAULT_PRESET_LABEL)
        self._preset_cb = ttk.Combobox(
            opts, textvariable=self._preset_var, state="readonly",
            values=[label for label, _ in DATE_PRESET_OPTIONS],
            style="D.TCombobox", width=18)
        self._preset_cb.pack(side="left", padx=(8, 10))
        self._start_btn = tk.Button(
            opts, text="Bắt đầu", command=self._start, relief="flat",
            bg=self.ACCENT, fg="#ffffff", activebackground="#2563eb",
            font=("Segoe UI", 9, "bold"), padx=18, pady=4)
        self._start_btn.pack(side="left")

        self._log = scrolledtext.ScrolledText(
            self, bg="#1e293b", fg=self.FG, font=("Consolas", 9),
            relief="flat", borderwidth=0, insertbackground=self.FG)
        self._log.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self._log.configure(state="disabled")

        bar = tk.Frame(self, bg=self.BG)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("P.Horizontal.TProgressbar", background=self.ACCENT,
                    troughcolor="#334155", borderwidth=0, thickness=6)
        self._progress = ttk.Progressbar(bar, mode="indeterminate", length=200,
                                         style="P.Horizontal.TProgressbar")
        self._progress.pack(side="left", fill="x", expand=True)
        self._close_btn = tk.Button(bar, text="Đóng", command=self.destroy,
                                    state="disabled", relief="flat",
                                    bg="#334155", fg=self.FG, activebackground="#475569",
                                    font=("Segoe UI", 9, "bold"), padx=16, pady=4)
        self._close_btn.pack(side="right", padx=(10, 0))

        # Chưa chạy ngay — chờ người dùng chọn khoảng thời gian rồi bấm "Bắt đầu".

    def _start(self):
        """Áp khoảng thời gian đã chọn rồi khởi động worker."""
        global SELECTED_PRESET
        label = self._preset_var.get()
        SELECTED_PRESET = next(
            (value for lbl, value in DATE_PRESET_OPTIONS if lbl == label), DATE_PRESET
        )
        self._preset_cb.configure(state="disabled")
        self._start_btn.configure(state="disabled")
        self._close_btn.configure(state="disabled")  # khóa Đóng khi đang chạy
        self._progress.start(12)
        threading.Thread(target=self._worker, daemon=True).start()

    def log(self, msg: str):
        print(msg)
        self.after(0, lambda: self._append(msg))

    def _append(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _worker(self):
        try:
            run(self.log)
        except RateLimitError as e:
            self.log(f"\n⚠ Rate limit: {e}")
        except Exception as e:
            self.log(f"\n✗ Lỗi: {e}")
        finally:
            self.after(0, self._finish)

    def _finish(self):
        self._progress.stop()
        self._close_btn.configure(state="normal")
        # Mở lại lựa chọn để chọn kỳ khác và chạy tiếp ngay trong cửa sổ này.
        self._preset_cb.configure(state="readonly")
        self._start_btn.configure(state="normal", text="Chạy tiếp")
        self._append("\n" + "─" * 50 + "\n")  # ngăn cách giữa các lần chạy


# ── Entry point ────────────────────────────────────────────────────────────────

def _choose_preset_console() -> None:
    """Hỏi khoảng thời gian qua console (khi không có tkinter)."""
    global SELECTED_PRESET
    print("\nChọn khoảng thời gian insights:")
    for i, (label, _) in enumerate(DATE_PRESET_OPTIONS, 1):
        mark = "  (mặc định)" if label == DEFAULT_PRESET_LABEL else ""
        print(f"  {i}. {label}{mark}")
    choice = input("Nhập số (Enter = mặc định): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(DATE_PRESET_OPTIONS):
        SELECTED_PRESET = DATE_PRESET_OPTIONS[int(choice) - 1][1]
    else:
        SELECTED_PRESET = next(
            (v for lbl, v in DATE_PRESET_OPTIONS if lbl == DEFAULT_PRESET_LABEL), DATE_PRESET
        )


if __name__ == "__main__":
    if tk is None:
        # Không có tkinter → chạy console.
        _choose_preset_console()
        run(lambda m: print(m))
    else:
        ProgressApp().mainloop()
