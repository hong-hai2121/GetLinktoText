"""
Lấy chi tiết chiến dịch (Campaign) cho các Tài Khoản Quảng Cáo (TKQC) được chọn.

Cách hoạt động:
    1. Đọc sheet "TKQC API" (do get_accounts.py ghi) → lọc các TKQC có cột
       "Chọn Lấy Camp" = TRUE.
    2. Với mỗi TKQC đã chọn: lấy toàn bộ campaign (/act_{id}/campaigns) + insights
       cấp campaign (this_month theo config).
    3. Ghi mỗi TKQC 1 tab trong Google Sheets, mỗi campaign 1 dòng (sắp xếp theo
       spend giảm dần).
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
from datetime import datetime

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

ACCOUNT_DELAY = 3  # giây nghỉ giữa mỗi TKQC — giảm tần suất gọi API (chống rate limit)

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

HEADERS = [
    "Chọn Lấy Chi Tiết",  # A  – chỉ dòng Campaign mới có giá trị TRUE/FALSE
    "Cấp",                # B  – "Campaign" / "Adset" / "Ad"
    "Campaign ID",        # C  – giữ nguyên ở mọi cấp (Adset/Ad tham chiếu campaign)
    "Tên",                # D  – Campaign / Adset / Ad Name tùy Cấp
    "Trạng Thái",         # E
    "Spend Tháng Này",    # F
    "Lượt Hiển Thị",      # G
    "Lượt Click",         # H
    "CTR (%)",            # I
    "CPC",                # J
    "CPM",                # K
    "Tiếp Cận",           # L
    "Tần Suất",           # M
    "Số Inbox",           # N
    "CPI",                # O
    "Số Lead",            # P
    "CPL",                # Q
    "Số Đơn Hàng",        # R
    "CPS",                # S
    "Doanh Thu",          # T
    "ROAS",               # U
    "Kết Quả",            # V
    "Chi Phí / Kết Quả",  # W
    "Chi Phí Campaign",   # X
    "Cập Nhật Lúc",       # Y
]

COLOR_SELECTED = {"red": 0.85, "green": 0.93, "blue": 0.83}  # Chọn Lấy Chi Tiết = TRUE → xanh nhạt
COLOR_DEFAULT  = {"red": 1.0,  "green": 1.0,  "blue": 1.0}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

try:
    from config import DATE_PRESET, TIME_RANGE
except ImportError:
    DATE_PRESET = "this_month"
    TIME_RANGE: dict = {}


def _date_params() -> dict:
    if DATE_PRESET:
        return {"date_preset": DATE_PRESET}
    return {"time_range": json.dumps(TIME_RANGE)}


_INSIGHTS_FIELDS = (
    "spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,"
    "actions,action_values,purchase_roas,cost_per_action_type"
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


def write_to_sheet(worksheet, rows: list[list]):
    worksheet.clear()
    worksheet.update(values=[HEADERS], range_name="A1")
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
            "format": {"backgroundColor": COLOR_SELECTED if is_selected else COLOR_DEFAULT},
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
        "fields": "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit": 200,
    }
    return graph_paginate(url, params, label="act_{id}/campaigns")


def fetch_insights_campaign_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/insights"
    params = {
        "level": "campaign",
        **_date_params(),
        "fields": f"campaign_id,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return graph_paginate(url, params, label="act_{id}/insights")


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


def _insights_cols(m: dict) -> list:
    def num(v, decimals=0):
        return round(v, decimals) if v > 0 else ""
    return [
        num(m["spend"], 2), num(m["impr"]), num(m["clicks"]), num(m["ctr"], 2),
        num(m["cpc"], 2), num(m["cpm"], 2), num(m["reach"]), num(m["freq"], 2),
        num(m["inbox"]), num(m["cpi"], 2), num(m["leads"]), num(m["cpl"], 2),
        num(m["purchases"]), num(m["cps"], 2), num(m["revenue"], 2), num(m["roas"], 2),
        num(m["ket_qua"]), num(m["cpkq"], 2),
    ]


def _campaign_row(camp_id, camp_name, is_selected, m: dict, status: str,
                  now_str: str, auto_by_spend: bool = False) -> list:
    chon = "TRUE" if (m["spend"] > 0 if auto_by_spend else is_selected) else "FALSE"
    return [
        chon,                              # A  Chọn Lấy Chi Tiết
        "Campaign",                        # B  Cấp
        camp_id,                           # C  Campaign ID
        camp_name,                         # D  Tên
        STATUS_MAP.get(status, status),    # E  Trạng Thái
    ] + _insights_cols(m) + [
        int(round(m["spend"])) if m["spend"] > 0 else "",  # X  Chi Phí Campaign
        now_str,                                            # Y  Cập Nhật Lúc
    ]


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
            selections[camp_id] = chon_val in TRUE_VALUES
    return selections


def build_rows_for_account(worksheet, acc_id: str, now_str: str,
                           auto_by_spend: bool = False) -> list[list]:
    """Lấy toàn bộ campaign + insights của 1 TKQC, trả về list dòng (spend giảm dần).
    Giữ nguyên cột 'Chọn Lấy Chi Tiết' cũ trong tab để không mất lựa chọn."""
    detail_selections = read_detail_selections(worksheet)
    camps = fetch_campaigns(acc_id)
    camp_meta = {
        c["id"]: {"name": c.get("name", ""), "status": c.get("status", "")}
        for c in camps if "id" in c
    }
    ins = fetch_insights_campaign_level(acc_id)
    insights = {r["campaign_id"]: r for r in ins if "campaign_id" in r}

    rows = []
    for cid, cmeta in camp_meta.items():
        m = parse_insight_metrics(insights.get(cid, {}))
        rows.append((m["spend"], _campaign_row(
            cid, cmeta.get("name", "(không rõ)"),
            detail_selections.get(cid, False), m, cmeta.get("status", ""),
            now_str, auto_by_spend,
        )))
    rows.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in rows]


def run(log):
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

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    for i, acc in enumerate(accounts, 1):
        acc_id, acc_name = acc["id"], acc["name"]
        if i > 1:
            log(f"  ⏱ Nghỉ {ACCOUNT_DELAY}s trước TKQC tiếp theo...")
            time.sleep(ACCOUNT_DELAY)
        log(f"[{i}/{len(accounts)}] {acc_name}: lấy campaign + insights...")
        ws = get_or_create_worksheet(ss, acc_name)  # lấy tab trước để đọc 'Chọn Lấy Chi Tiết' cũ
        try:
            rows = build_rows_for_account(ws, acc_id, now_str)
        except RateLimitError:
            raise  # rate limit → dừng hẳn, để handler ngoài lưu/log
        except RuntimeError as e:
            log(f"    ⚠ Bỏ qua (lỗi: {e})")
            continue
        write_to_sheet(ws, rows)
        log(f"    → {len(rows)} campaign → tab '{sanitize_sheet_name(acc_name)}'")

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


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if tk is None:
        # Không có tkinter → chạy console.
        run(lambda m: print(m))
    else:
        ProgressApp().mainloop()
