"""
Phase 1 – Lấy danh sách Campaign tháng này cho các tài khoản được chọn
         trong sheet TKQC API (cột "Chọn Lấy Camp" = TRUE).

Ghi mỗi campaign thành 1 dòng vào tab tài khoản trong Google Sheets,
kèm metrics cấp campaign (spend, impressions, CTR, CPM …).

Cột "Chọn Lấy Chi Tiết" được giữ nguyên giá trị cũ để không mất lựa chọn.
→ Chạy get_details.py sau đó để mở rộng Adset / Ad cho các campaign được chọn.
"""

import re
import sys
import time
import threading
import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    tk = None

from config import ACCESS_TOKEN, SPREADSHEET_ID
from fb_api import graph_paginate, api_summary, RateLimitError, set_call_delay

BASE_DIR = Path(__file__).parent

AD_ACCOUNTS_SHEET = "TKQC API"
FB_API_VERSION = "v20.0"

# ── Giãn cách gọi API (tránh rate limit) ──────────────────────────────────────
CALL_DELAY_SECONDS    = 2.0  # nghỉ sau MỖI lần gọi Graph API
ACCOUNT_DELAY_SECONDS = 3.0  # nghỉ THÊM giữa các tài khoản

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

# Trạng thái PHÂN PHỐI (cột "Phân phối" trên Trình quản lý QC) — suy từ effective_status.
# Đang hoạt động (đang phân phối) / Đang chờ (chờ duyệt·xử lý) / Không hoạt động (tắt·lưu trữ).
DELIVERY_MAP = {
    "ACTIVE":          "Đang hoạt động",
    "IN_PROCESS":      "Đang chờ",
    "PENDING_REVIEW":  "Đang chờ",
    "PENDING_BILLING_INFO": "Đang chờ",
    "PREAPPROVED":     "Đang chờ",
    "PAUSED":          "Không hoạt động",
    "CAMPAIGN_PAUSED": "Không hoạt động",
    "ADSET_PAUSED":    "Không hoạt động",
    "ARCHIVED":        "Không hoạt động",
    "DELETED":         "Không hoạt động",
    "WITH_ISSUES":     "Không hoạt động",
    "DISAPPROVED":     "Không hoạt động",
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

# A–AB = 28 cột (Creative đã chuyển sang tab riêng)
HEADERS = [
    "Chọn Lấy Chi Tiết",   # A   1  – chỉ dòng Campaign mới có giá trị
    "Cấp",                   # B   2  – "Campaign" / "Adset" / "Ad"
    "Campaign ID",           # C   3  – Campaign ID (giữ nguyên ở mọi cấp)
    "Tên",                   # D   4  – Campaign / Adset / Ad Name tùy Cấp
    "Trạng Thái",            # E   5
    "Spend Tháng Này",       # F   6
    "Lượt Hiển Thị",         # G   7
    "Lượt Click",            # H   8
    "CTR (%)",               # I   9
    "CPC",                   # J  10
    "CPM",                   # K  11
    "Tiếp Cận",              # L  12
    "Tần Suất",              # M  13
    "Số Inbox",              # N  14
    "CPI",                   # O  15
    "Số Lead",               # P  16
    "CPL",                   # Q  17
    "Số Đơn Hàng",           # R  18
    "CPS",                   # S  19
    "Doanh Thu",             # T  20
    "ROAS",                  # U  21
    "Kết Quả",               # V  22
    "Chi Phí / Kết Quả",     # W  23
    "Chi Phí Campaign",      # X  24  – số nguyên, chỉ dòng Campaign
    "Cập Nhật Lúc",          # Y  25
]

COLOR_SELECTED = {"red": 0.85, "green": 0.93, "blue": 0.83}  # có spend → xanh nhạt
COLOR_DEFAULT  = {"red": 1.0,  "green": 1.0,  "blue": 1.0}   # không có spend → trắng

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


# Lấy CẢ campaign đã xóa/đã lưu trữ. FB v20.0 KHÔNG nhận `effective_status` trực
# tiếp (báo "Invalid parameter") — phải lọc qua `filtering` với campaign.effective_status.
CAMPAIGN_STATUSES = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "IN_PROCESS", "WITH_ISSUES"]
LIVE_STATUSES = {"ACTIVE", "PAUSED"}      # luôn hiện, kể cả không chi tiêu trong kỳ


def _status_filter() -> str:
    return json.dumps([{"field": "campaign.effective_status",
                        "operator": "IN", "value": CAMPAIGN_STATUSES}])


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
    worksheet.clear()
    worksheet.update("A1", [HEADERS])
    if not rows:
        return
    worksheet.update("A2", rows)

    last_col = col_to_letter(len(HEADERS))
    formats = []
    for i, row in enumerate(rows):
        sheet_row = i + 2
        is_selected = row[0] == "TRUE"
        formats.append({
            "range":  f"A{sheet_row}:{last_col}{sheet_row}",
            "format": {"backgroundColor": COLOR_SELECTED if is_selected else COLOR_DEFAULT},
        })
    worksheet.batch_format(formats)


# ── Facebook Graph API ─────────────────────────────────────────────────────────

def paginate(url: str, params: dict) -> list[dict]:
    # Ủy thác sang fb_api.graph_paginate để đếm + log + retry rate limit.
    return graph_paginate(url, params)


def _act_id(account_id: str) -> str:
    # Sheet lưu ID dạng số (đã removeprefix("act_") trong main.py).
    # Edge /campaigns và /insights yêu cầu prefix act_.
    account_id = account_id.strip()
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def fetch_campaigns(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/campaigns"
    params = {
        "fields":       "id,name,status,effective_status",  # effective_status = trạng thái phân phối
        "filtering":    _status_filter(),    # gồm cả camp đã xóa/đã lưu trữ
        "access_token": ACCESS_TOKEN,
        "limit":        100,
    }
    return paginate(url, params)


def fetch_insights_campaign_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/insights"
    params = {
        "level":        "campaign",
        **_date_params(),
        "fields":       f"campaign_id,{_INSIGHTS_FIELDS}",
        "filtering":    _status_filter(),    # gồm insights của camp đã xóa/đã lưu trữ
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


def _insights_cols(m: dict) -> list:
    """18 giá trị số thực cho cột F–W — lưu number để dùng được trong công thức Sheets."""
    def num(v, decimals=0):
        return round(v, decimals) if v > 0 else ""

    return [
        num(m["spend"],     2),   # F  Spend Tháng Này
        num(m["impr"]),           # G  Lượt Hiển Thị
        num(m["clicks"]),         # H  Lượt Click
        num(m["ctr"],       2),   # I  CTR (%)
        num(m["cpc"],       2),   # J  CPC
        num(m["cpm"],       2),   # K  CPM
        num(m["reach"]),          # L  Tiếp Cận
        num(m["freq"],      2),   # M  Tần Suất
        num(m["inbox"]),          # N  Số Inbox
        num(m["cpi"],       2),   # O  CPI
        num(m["leads"]),          # P  Số Lead
        num(m["cpl"],       2),   # Q  CPL
        num(m["purchases"]),      # R  Số Đơn Hàng
        num(m["cps"],       2),   # S  CPS
        num(m["revenue"],   2),   # T  Doanh Thu
        num(m["roas"],      2),   # U  ROAS
        num(m["ket_qua"]),        # V  Kết Quả
        num(m["cpkq"],      2),   # W  Chi Phí / Kết Quả
    ]


# ── Row builder ────────────────────────────────────────────────────────────────

def _campaign_row(camp_id, camp_name, is_selected, m: dict,
                  delivery: str, now_str: str, auto_by_spend: bool = False) -> list:
    """Dòng Campaign — 25 cột."""
    chon = "TRUE" if (m["spend"] > 0 if auto_by_spend else is_selected) else "FALSE"
    return [
        chon,       # A
        "Campaign",                           # B
        camp_id,                              # C  Campaign ID
        camp_name,                            # D  Tên
        DELIVERY_MAP.get(delivery, delivery), # E  Phân phối (trạng thái phân phối)
    ] + _insights_cols(m) + [
        int(round(m["spend"])) if m["spend"] > 0 else "",  # X  Chi Phí Campaign (số nguyên)
        now_str,                                            # Y  Cập Nhật Lúc
    ]


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


# ── Core processing ────────────────────────────────────────────────────────────

def get_all_accounts(spreadsheet) -> list[dict]:
    """Đọc sheet TKQC API, trả về TẤT CẢ tài khoản kèm trạng thái 'Chọn Lấy Camp'."""
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
        raise RuntimeError(f"Sheet '{AD_ACCOUNTS_SHEET}' thiếu cột: {e}.")
    da_chi_col = header.index("Đã Chi") if "Đã Chi" in header else -1

    accounts = []
    for row in all_values[1:]:
        acc_id   = row[id_col].strip()           if id_col       < len(row) else ""
        acc_name = row[name_col].strip()         if name_col     < len(row) else ""
        currency = row[currency_col].strip()     if currency_col < len(row) else "VND"
        chon_val = row[chon_col].strip().upper() if chon_col     < len(row) else ""
        da_chi   = row[da_chi_col].strip()       if da_chi_col >= 0 and da_chi_col < len(row) else ""
        # Kiểm tra có chi tiêu: bỏ ký tự không phải số rồi parse
        da_chi_num = 0
        try:
            cleaned = da_chi.replace(" ₫", "").replace(".", "").replace(",", "").strip()
            da_chi_num = int(float(cleaned)) if cleaned else 0
        except ValueError:
            pass
        if acc_id:
            accounts.append({
                "id":        acc_id,
                "name":      acc_name,
                "currency":  currency,
                "selected":  chon_val in _CHON_VALUES,
                "has_spend": da_chi_num > 0,
                "da_chi":    da_chi,
            })
    return accounts


def run_for_accounts(spreadsheet, accounts: list[dict], auto_by_spend: bool = False,
                     progress=None):
    """Fetch campaign + insights cho danh sách tài khoản, ghi vào Sheets và JSON.

    progress: callback tuỳ chọn (done, total, tên_TK, ghi_chú) — cập nhật tiến trình GUI.
    """
    month_label = datetime.now().strftime("%m/%Y")
    total = len(accounts)
    dump_campaigns:     dict[str, list] = {}
    dump_insights_camp: dict[str, list] = {}

    def _emit(done, name, note=""):
        if progress:
            progress(done, total, name, note)

    set_call_delay(CALL_DELAY_SECONDS)

    rate_limited = False
    try:
        for idx, acc in enumerate(accounts):
            acc_id   = acc["id"]
            acc_name = acc["name"]
            if idx > 0:
                print(f"  ⏱ Nghỉ {ACCOUNT_DELAY_SECONDS:g}s trước tài khoản tiếp theo...")
                time.sleep(ACCOUNT_DELAY_SECONDS)
            print(f"\n[{acc_name}] Xử lý tháng {month_label}...")
            _emit(idx, acc_name, "đang lấy danh sách campaign…")

            ws = get_or_create_worksheet(spreadsheet, acc_name)

            detail_selections = read_detail_selections(ws)
            selected_count = sum(1 for v in detail_selections.values() if v)
            print(f"  → {selected_count} campaign đang được chọn lấy chi tiết (giữ nguyên).")

            campaigns = fetch_campaigns(acc_id)
            print(f"  → {len(campaigns)} campaign (gồm cả đã xóa/đã lưu trữ).")
            dump_campaigns[acc_name] = campaigns
            _emit(idx, acc_name, f"{len(campaigns)} camp · đang lấy chi tiêu…")

            camp_insights = fetch_insights_campaign_level(acc_id)
            camp_insights_map = {r["campaign_id"]: r for r in camp_insights if "campaign_id" in r}
            print(f"  → {len(camp_insights)} dòng insights campaign.")
            dump_insights_camp[acc_name] = camp_insights

            # Camp còn sống (ACTIVE/PAUSED) luôn hiện; camp đã xóa/đã lưu trữ CHỈ hiện
            # nếu có chi tiêu trong kỳ đã chọn (tránh kéo cả trăm camp lưu trữ cũ).
            visible_camps = [
                c for c in campaigns
                if c.get("status") in LIVE_STATUSES or c.get("id") in camp_insights_map
            ]
            n_extra = sum(1 for c in visible_camps if c.get("status") not in LIVE_STATUSES)
            print(f"  → {len(visible_camps)} camp hiển thị "
                  f"({n_extra} đã xóa/đã lưu trữ có chi tiêu trong kỳ).")

            status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}
            sorted_camps = sorted(
                visible_camps,
                key=lambda c: (status_order.get(c.get("status", ""), 9), c.get("name", "")),
            )
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            rows = [
                _campaign_row(
                    camp.get("id", ""),
                    camp.get("name", ""),
                    detail_selections.get(camp.get("id", ""), False),
                    parse_insight_metrics(camp_insights_map.get(camp.get("id", ""), {})),
                    camp.get("effective_status", camp.get("status", "")),  # trạng thái phân phối
                    now_str,
                    auto_by_spend=auto_by_spend,
                )
                for camp in sorted_camps
            ]
            _emit(idx, acc_name, f"đang ghi {len(rows)} dòng vào sheet…")
            write_to_sheet(ws, rows)
            print(f"  → Đã ghi {len(rows)} dòng vào tab '{sanitize_sheet_name(acc_name)}'.")
            _emit(idx + 1, acc_name, f"xong · {len(rows)} dòng")

    except RateLimitError as e:
        rate_limited = True
        print(f"\n⚠ Rate limit: {e}")
        print(f"Đã hoàn thành {len(dump_campaigns)} tài khoản. Lưu dữ liệu hiện có...")

    base_url = f"https://graph.facebook.com/{FB_API_VERSION}"
    print("\nLưu JSON...")
    save_json(dump_campaigns, "get_campaigns.json", {
        "endpoint": f"GET {base_url}/act_{{account_id}}/campaigns",
        "fields":   "id,name,status",
        "note":     "Toàn bộ campaign của tài khoản",
    })
    save_json(dump_insights_camp, "get_campaigns_insights.json", {
        "endpoint":    f"GET {base_url}/act_{{account_id}}/insights",
        "level":       "campaign",
        "date_preset": "this_month",
        "fields":      f"campaign_id,{_INSIGHTS_FIELDS}",
        "note":        "Insights cấp campaign tháng này — dùng cho dòng Campaign trong sheet",
    })
    api_summary()
    if rate_limited:
        raise RateLimitError(f"Rate limit — đã lưu {len(dump_campaigns)} tài khoản.")
    print("\nHoàn thành!")


# ── GUI ────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    BG         = "#eef2f6"
    CARD       = "#f8fafc"
    BORDER     = "#cbd5e1"
    ACCENT     = "#3b82f6"
    ACCENT_HV  = "#2563eb"
    ACCENT_DIS = "#93c5fd"
    TEXT       = "#334155"
    MUTED      = "#64748b"

    def __init__(self):
        super().__init__()
        self.title("Get Campaigns – Chọn Tài Khoản")
        
        from ui_kit import size_window
        size_window(self, min_w=900, min_h=520)
        self.configure(bg=self.BG)
        self.resizable(True, True)

        self._spreadsheet = None
        self._items: list[dict] = []
        self._spend_var = None   # checkbox tự chọn campaign có spend

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",  background=self.BG)
        s.configure("TLabel",  background=self.BG,
                    font=("Segoe UI", 10), foreground=self.TEXT)
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background=self.BORDER, foreground=self.TEXT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("TButton",
              background=[("active", "#cbd5e1"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(22, 9), background=self.ACCENT,
                    foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#ffffff")])
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=28,
                    background=self.CARD, fieldbackground=self.CARD,
                    foreground=self.TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background=self.BORDER, foreground=self.MUTED,
                    relief="flat", padding=(8, 6))
        s.map("Treeview",
              background=[("selected", self.ACCENT)],
              foreground=[("selected", "#ffffff")])
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor=self.BORDER, borderwidth=0, thickness=6)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=24, pady=20)

        # ── Header ──
        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 2))
        tk.Label(hdr, text="Phase 1 — Campaigns", bg=self.BG,
                 font=("Segoe UI Semibold", 18), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right", pady=(8, 0))

        tk.Label(outer,
                 text="Chọn tài khoản để lấy campaign + chi tiêu tháng. Click dòng để bật / tắt; "
                      "chỉ tài khoản ✓ mới gọi API. Không ảnh hưởng sheet TKQC API.",
                 bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED,
                 justify="left", anchor="w").pack(fill="x", pady=(2, 14))

        # ── Tuỳ chọn ──
        opt_row = tk.Frame(outer, bg=self.BG)
        opt_row.pack(fill="x", pady=(0, 12))
        self._spend_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            opt_row, text="Tự chọn campaign có Spend (cột A = TRUE nếu có chi tiêu)",
            variable=self._spend_var, bg=self.BG, fg=self.TEXT,
            activebackground=self.BG, activeforeground=self.TEXT,
            selectcolor=self.BORDER, font=("Segoe UI", 9), relief="flat", bd=0,
            cursor="hand2", takefocus=0,
        ).pack(side="left")

        # ── Thanh dưới (tiến trình + nút) — pack trước để luôn hiện ──
        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", side="bottom", pady=(16, 0))

        prog = tk.Frame(bot, bg=self.BG)
        prog.pack(fill="x", pady=(0, 12))
        self._prog_lbl = tk.Label(prog, text="Sẵn sàng.", bg=self.BG, fg=self.MUTED,
                                  font=("Segoe UI", 9), anchor="w")
        self._prog_lbl.pack(fill="x")
        self._progress = ttk.Progressbar(prog, mode="determinate", length=200)
        self._progress.pack(fill="x", pady=(5, 0))

        btns = tk.Frame(bot, bg=self.BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Bật tất cả",
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text="Tắt tất cả",
                   command=lambda: self._set_all(False)).pack(side="left", padx=(6, 0))
        self._count_lbl = tk.Label(btns, text="", bg=self.BG,
                                   font=("Segoe UI", 9), fg=self.MUTED)
        self._count_lbl.pack(side="left", padx=12)
        self._run_btn = ttk.Button(btns, text="▶  Chạy", style="Accent.TButton",
                                   command=self._run, state="disabled")
        self._run_btn.pack(side="right")
        ttk.Button(btns, text="Huỷ", command=self.destroy).pack(side="right", padx=(0, 8))

        # ── Danh sách tài khoản (card) ──
        card = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = ("chon", "acc_name", "acc_id", "da_chi")
        self._tree = ttk.Treeview(card, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("chon",     text="Chọn",          anchor="center")
        self._tree.heading("acc_name", text="Tên Tài Khoản",  anchor="w")
        self._tree.heading("acc_id",   text="ID Tài Khoản",   anchor="w")
        self._tree.heading("da_chi",   text="Đã Chi",          anchor="e")
        self._tree.column("chon",     width=56,  stretch=False, anchor="center", minwidth=50)
        self._tree.column("acc_name", width=260, stretch=True,  minwidth=140)
        self._tree.column("acc_id",   width=170, stretch=False, minwidth=110)
        self._tree.column("da_chi",   width=150, stretch=False, minwidth=100, anchor="e")

        vsb = ttk.Scrollbar(card, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(card, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("on",  foreground="#198754")
        self._tree.tag_configure("off", foreground="#dc3545")
        self._tree.tag_configure("odd", background="#f1f3f5")

        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind("<space>",           self._on_space)

    # ── Connect ───────────────────────────────────────────────────────────────

    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss       = connect_spreadsheet()
            accounts = get_all_accounts(ss)
            self._spreadsheet = ss
            self.after(0, lambda: self._load_items(
                accounts, f"Kết nối OK · {ss.title} · {len(accounts)} tài khoản"))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi: {e}", error=True))

    def _load_items(self, accounts: list[dict], status_text: str):
        self._set_status(status_text)
        self._items = []
        for i, acc in enumerate(accounts):
            selected = acc.get("selected", False)
            base_tag = "on" if selected else "off"
            tags = ("odd", base_tag) if i % 2 != 0 else (base_tag,)
            iid = self._tree.insert("", "end", values=(
                "✓" if selected else "✗",
                acc["name"],
                acc["id"],
                acc.get("da_chi", ""),
            ), tags=tags)
            self._items.append({**acc, "iid": iid, "selected": selected})
        self._refresh_count()
        if any(i["selected"] for i in self._items):
            self._run_btn.configure(state="normal")

    # ── Toggle ────────────────────────────────────────────────────────────────

    def _update_item_ui(self, item: dict):
        idx = self._items.index(item)
        base_tag = "on" if item["selected"] else "off"
        tags = ("odd", base_tag) if idx % 2 != 0 else (base_tag,)
        self._tree.item(item["iid"], values=(
            "✓" if item["selected"] else "✗",
            item["name"], item["id"], item.get("da_chi", ""),
        ), tags=tags)

    def _toggle(self, iid: str):
        item = next((i for i in self._items if i["iid"] == iid), None)
        if item is None:
            return
        item["selected"] = not item["selected"]
        self._update_item_ui(item)
        self._refresh_count()
        self._run_btn.configure(
            state="normal" if any(i["selected"] for i in self._items) else "disabled"
        )

    def _on_click(self, event):
        iid = self._tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _on_space(self, _):
        for iid in self._tree.selection():
            self._toggle(iid)

    def _set_all(self, value: bool):
        for item in self._items:
            item["selected"] = value
            self._update_item_ui(item)
        self._refresh_count()
        self._run_btn.configure(state="normal" if value and self._items else "disabled")

    def _refresh_count(self):
        total    = len(self._items)
        selected = sum(1 for i in self._items if i["selected"])
        self._count_lbl.configure(
            text=f"{selected}/{total} được chọn" if total else "Danh sách trống"
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def _run(self):
        accounts = [i for i in self._items if i["selected"]]
        if not accounts:
            messagebox.showwarning("Chưa chọn", "Chưa bật tài khoản nào.")
            return
        auto_by_spend = self._spend_var.get() if self._spend_var else False
        self._run_btn.configure(state="disabled")
        self._progress.configure(mode="determinate", maximum=len(accounts), value=0)
        self._prog_lbl.configure(text=f"Bắt đầu…  0/{len(accounts)} tài khoản",
                                 fg=self.TEXT)
        self._set_status(f"Đang chạy {len(accounts)} tài khoản...")
        threading.Thread(target=self._run_worker,
                         args=(list(accounts), auto_by_spend), daemon=True).start()

    def _run_worker(self, accounts: list[dict], auto_by_spend: bool = False):
        try:
            run_for_accounts(self._spreadsheet, accounts,
                             auto_by_spend=auto_by_spend, progress=self._emit_progress)
            self.after(0, self._done)
        except RateLimitError as e:
            self.after(0, lambda e=e: self._rate_limited(str(e)))
        except Exception as e:
            self.after(0, lambda e=e: self._error(str(e)))

    def _emit_progress(self, done: int, total: int, name: str, note: str):
        """Gọi từ thread nền → chuyển về main thread cập nhật tiến trình."""
        self.after(0, self._apply_progress, done, total, name, note)

    def _apply_progress(self, done: int, total: int, name: str, note: str):
        self._progress.configure(maximum=total, value=done)
        self._prog_lbl.configure(text=f"{done}/{total} tài khoản   ·   {name} — {note}",
                                 fg=self.TEXT)
        self._set_status(f"Đang chạy…  {done}/{total}")

    def _done(self):
        try:
            self._progress.configure(value=self._progress["maximum"])
        except tk.TclError:
            pass
        self._run_btn.configure(state="normal")
        self._prog_lbl.configure(text="✓  Hoàn tất tất cả tài khoản đã chọn.", fg="#198754")
        self._set_status("✓ Hoàn thành!")
        messagebox.showinfo("Hoàn thành", "Đã lấy xong campaign cho các tài khoản được chọn.")

    def _rate_limited(self, msg: str):
        self._run_btn.configure(state="normal")
        self._prog_lbl.configure(
            text="⚠  Dừng do rate limit — dữ liệu đã xử lý xong đã được lưu.", fg=self.ACCENT)
        self._set_status("⚠ Rate limit — đã lưu dữ liệu", error=True)
        messagebox.showwarning("Rate Limit", f"{msg}\n\nDữ liệu các tài khoản đã xử lý xong đã được lưu.")

    def _error(self, msg: str):
        self._run_btn.configure(state="normal")
        self._prog_lbl.configure(text=f"✗  Lỗi: {msg}", fg="#dc3545")
        self._set_status(f"✗ Lỗi: {msg}", error=True)
        messagebox.showerror("Lỗi", msg)

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, foreground="#dc3545" if error else self.MUTED
        )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if tk is None:
        sys.exit("Cần tkinter để chạy giao diện (có sẵn trong Python chuẩn trên Windows).")
    App().mainloop()
