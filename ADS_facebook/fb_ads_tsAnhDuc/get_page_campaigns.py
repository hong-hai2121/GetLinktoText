"""
Lấy chi tiết chiến dịch (Campaign) cho các Page đã chọn ở get_pages.py.

Cách hoạt động:
  Facebook KHÔNG có endpoint "campaign của 1 page". Campaign luôn thuộc về Tài
  Khoản Quảng Cáo (TKQC); page chỉ liên kết qua creative của từng quảng cáo
  (object_story_spec.page_id hoặc effective_object_story_id = "{page_id}_{post_id}").

  Vì vậy script:
    1. Lấy toàn bộ TKQC của token (/me/adaccounts).
    2. Quét ads của từng TKQC, suy ra page mỗi ad quảng cáo, gom campaign_id theo
       (TKQC, page).
    3. Với các TKQC có campaign khớp page đã chọn → lấy campaign + insights cấp
       campaign (this_month theo config).
    4. Ghi mỗi page 1 tab trong Google Sheets, mỗi campaign 1 dòng.

  Lưu ý: metric là của TOÀN campaign (nếu campaign có ad quảng cáo nhiều page thì
  số liệu gộp chung). Cột "Số Ad Của Page" cho biết bao nhiêu ad trong campaign
  quảng cáo page đang xét.

Chạy:  python get_page_campaigns.py [đường_dẫn_file_page_đã_chọn.json]
        (Thường được get_pages.py mở tự động, không cần chạy tay.)
"""

import sys
import json
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

# Google Sheet mới — mỗi page 1 tab, tab thiếu sẽ tự tạo.
SPREADSHEET_ID = "1aBWyX1f3yjMVbbJ7HxDbvS3ZvjBL9JsXc3Ycm_gTwAc"
FB_API_VERSION = "v20.0"
SELECTED_FILE = BASE_DIR / "_pages_selected.json"

SERVICE_ACCOUNT_EMAIL = "ads-392@hai-ads-check.iam.gserviceaccount.com"

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
    "TKQC",               # A
    "Account ID",         # B
    "Campaign ID",        # C
    "Tên Campaign",       # D
    "Trạng Thái",         # E
    "Số Ad Của Page",     # F  – số ad trong campaign quảng cáo page này
    "Spend Tháng Này",    # G
    "Lượt Hiển Thị",      # H
    "Lượt Click",         # I
    "CTR (%)",            # J
    "CPC",                # K
    "CPM",                # L
    "Tiếp Cận",           # M
    "Tần Suất",           # N
    "Số Inbox",           # O
    "CPI",                # P
    "Số Lead",            # Q
    "CPL",                # R
    "Số Đơn Hàng",        # S
    "CPS",                # T
    "Doanh Thu",          # U
    "ROAS",               # V
    "Kết Quả",            # W
    "Chi Phí / Kết Quả",  # X
    "Chi Phí Campaign",   # Y
    "Cập Nhật Lúc",       # Z
]

COLOR_SELECTED = {"red": 0.85, "green": 0.93, "blue": 0.83}  # có spend → xanh nhạt
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
    return spreadsheet.add_worksheet(title=safe, rows=2000, cols=len(HEADERS))


def write_to_sheet(worksheet, rows: list[list]):
    worksheet.clear()
    worksheet.update(values=[HEADERS], range_name="A1")
    if not rows:
        return
    worksheet.update(values=rows, range_name="A2", value_input_option="RAW")

    last_col = col_to_letter(len(HEADERS))
    spend_idx = HEADERS.index("Spend Tháng Này")
    formats = []
    for i, row in enumerate(rows):
        sheet_row = i + 2
        has_spend = bool(row[spend_idx]) and row[spend_idx] != ""
        formats.append({
            "range":  f"A{sheet_row}:{last_col}{sheet_row}",
            "format": {"backgroundColor": COLOR_SELECTED if has_spend else COLOR_DEFAULT},
        })
    worksheet.batch_format(formats)


# ── Facebook Graph API ─────────────────────────────────────────────────────────

def _act_id(account_id: str) -> str:
    account_id = account_id.strip()
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def fetch_ad_accounts() -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me/adaccounts"
    params = {
        "fields": "id,name,currency,account_status",
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    return graph_paginate(url, params, label="me/adaccounts")


def fetch_ads_page_map(account_id: str) -> list[dict]:
    """Lấy ads của 1 TKQC kèm campaign_id + tham chiếu page trong creative."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/ads"
    params = {
        "fields": "campaign_id,creative{effective_object_story_id,object_story_spec{page_id}}",
        "access_token": ACCESS_TOKEN,
        "limit": 200,
    }
    return graph_paginate(url, params, label="act_{id}/ads")


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


def resolve_page_id(ad: dict) -> str:
    """Suy ra page_id mà 1 ad quảng cáo, từ creative."""
    creative = ad.get("creative") or {}
    spec = creative.get("object_story_spec") or {}
    pid = spec.get("page_id")
    if pid:
        return str(pid)
    story_id = creative.get("effective_object_story_id") or ""
    if "_" in story_id:
        return story_id.split("_", 1)[0]
    return ""


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


def _campaign_row(acc_name, acc_id, camp_id, camp_name, status, ad_count,
                  m: dict, now_str: str) -> list:
    return [
        acc_name,                          # A
        acc_id,                            # B
        camp_id,                           # C
        camp_name,                         # D
        STATUS_MAP.get(status, status),    # E
        ad_count,                          # F
    ] + _insights_cols(m) + [
        int(round(m["spend"])) if m["spend"] > 0 else "",  # Y
        now_str,                                            # Z
    ]


# ── Core ─────────────────────────────────────────────────────────────────────

def load_selected_pages(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {path.name}. Hãy chạy get_pages.py, chọn page rồi bấm "
            "'Lấy chi tiết chiến dịch'."
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def gather(pages: list[dict], log) -> tuple[dict, dict, dict, dict]:
    """Quét TKQC + ads, trả về:
    - acct_page_camp[acc_id][page_id] = {campaign_id: số_ad}
    - camp_meta[acc_id] = {campaign_id: {name,status}}
    - insights[acc_id]  = {campaign_id: insight_dict}
    - acct_info[acc_id] = {name, currency}
    """
    selected_ids = {str(p["id"]) for p in pages}

    log("Lấy danh sách TKQC (/me/adaccounts)...")
    accounts = fetch_ad_accounts()
    log(f"  → {len(accounts)} TKQC.")

    acct_info: dict[str, dict] = {}
    acct_page_camp: dict[str, dict] = {}

    # Phase 1 – quét ads từng TKQC, lọc theo page đã chọn
    for i, acc in enumerate(accounts, 1):
        acc_id = acc.get("id", "")
        acc_name = acc.get("name", acc_id)
        acct_info[acc_id] = {"name": acc_name, "currency": acc.get("currency", "")}
        log(f"[{i}/{len(accounts)}] Quét ads: {acc_name}")
        try:
            ads = fetch_ads_page_map(acc_id)
        except RateLimitError:
            raise  # rate limit → dừng hẳn, để handler ngoài lưu/log
        except RuntimeError as e:
            log(f"    ⚠ Bỏ qua (lỗi: {e})")
            continue

        matched = 0
        for ad in ads:
            pid = resolve_page_id(ad)
            if pid not in selected_ids:
                continue
            cid = ad.get("campaign_id")
            if not cid:
                continue
            acct_page_camp.setdefault(acc_id, {}).setdefault(pid, {})
            acct_page_camp[acc_id][pid][cid] = acct_page_camp[acc_id][pid].get(cid, 0) + 1
            matched += 1
        if matched:
            log(f"    → {matched} ad khớp page đã chọn.")

    # Phase 2 – chỉ lấy campaign + insights cho TKQC có khớp
    camp_meta: dict[str, dict] = {}
    insights: dict[str, dict] = {}
    relevant_accts = list(acct_page_camp.keys())
    log(f"\n{len(relevant_accts)} TKQC có campaign khớp page. Lấy campaign + insights...")
    for acc_id in relevant_accts:
        acc_name = acct_info[acc_id]["name"]
        log(f"  • {acc_name}: campaigns + insights")
        camps = fetch_campaigns(acc_id)
        camp_meta[acc_id] = {
            c["id"]: {"name": c.get("name", ""), "status": c.get("status", "")}
            for c in camps if "id" in c
        }
        ins = fetch_insights_campaign_level(acc_id)
        insights[acc_id] = {r["campaign_id"]: r for r in ins if "campaign_id" in r}

    return acct_page_camp, camp_meta, insights, acct_info


def build_rows_for_page(page_id, acct_page_camp, camp_meta, insights, acct_info,
                        now_str: str) -> list[list]:
    rows = []
    for acc_id, page_map in acct_page_camp.items():
        camp_map = page_map.get(page_id)
        if not camp_map:
            continue
        acc_name = acct_info[acc_id]["name"]
        acc_num = acc_id.removeprefix("act_")
        meta = camp_meta.get(acc_id, {})
        ins = insights.get(acc_id, {})
        for cid, ad_count in camp_map.items():
            cmeta = meta.get(cid, {})
            m = parse_insight_metrics(ins.get(cid, {}))
            rows.append((m["spend"], _campaign_row(
                acc_name, acc_num, cid, cmeta.get("name", "(không rõ)"),
                cmeta.get("status", ""), ad_count, m, now_str,
            )))
    # Spend giảm dần
    rows.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in rows]


def run(pages: list[dict], log):
    log(f"Kết nối Google Sheets ({SPREADSHEET_ID})...")
    try:
        ss = connect_spreadsheet()
    except Exception as e:
        raise RuntimeError(
            f"Không mở được Google Sheet. Hãy chia sẻ sheet cho service account "
            f"'{SERVICE_ACCOUNT_EMAIL}' (quyền Editor).\nChi tiết: {e}"
        )
    log(f"  → OK: {ss.title}")

    acct_page_camp, camp_meta, insights, acct_info = gather(pages, log)

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    log("\nGhi dữ liệu vào Sheets...")
    for pg in pages:
        pid, pname = str(pg["id"]), pg.get("name", pg["id"])
        rows = build_rows_for_page(pid, acct_page_camp, camp_meta, insights,
                                   acct_info, now_str)
        ws = get_or_create_worksheet(ss, pname)
        write_to_sheet(ws, rows)
        log(f"  • {pname}: {len(rows)} campaign → tab '{sanitize_sheet_name(pname)}'")

    api_summary()
    log("\n✓ Hoàn thành!")


# ── GUI tiến trình ─────────────────────────────────────────────────────────────

class ProgressApp(tk.Tk):
    BG = "#0f172a"
    FG = "#e2e8f0"
    ACCENT = "#3b82f6"

    def __init__(self, pages: list[dict]):
        super().__init__()
        self._pages = pages
        self.title("Lấy chi tiết chiến dịch của Page")

        w, h = 640, 420
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg=self.BG)

        names = ", ".join(p.get("name", p["id"]) for p in pages)
        tk.Label(self, text=f"Page: {names}", bg=self.BG, fg=self.FG,
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
            run(self._pages, self.log)
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
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SELECTED_FILE
    pages = load_selected_pages(path)
    if not pages:
        sys.exit("Không có page nào được chọn.")

    if tk is None:
        # Không có tkinter → chạy console.
        run(pages, lambda m: print(m))
    else:
        ProgressApp(pages).mainloop()
