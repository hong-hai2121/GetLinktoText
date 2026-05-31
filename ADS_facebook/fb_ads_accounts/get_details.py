"""
Phase 2 – Lấy chi tiết Adset / Ad / Creative + Insights cấp Ad
         cho các Campaign đã được đánh TRUE ở cột "Chọn Lấy Chi Tiết".

Chạy SAU khi đã chạy get_campaigns.py và đánh dấu campaign muốn xem chi tiết.
Script CHÈN dòng Adset/Ad vào đúng vị trí trong sheet, KHÔNG xóa dữ liệu
dòng Campaign hiện có (kể cả các cột ngoài cấu trúc script quản lý).
"""

import sys
import json
import time
import threading
from datetime import datetime

CAMPAIGN_DELAY = 5  # giây nghỉ giữa mỗi campaign — giảm tần suất gọi API

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    tk = None

from fb_api import api_summary, RateLimitError
from get_campaigns import (
    # Constants & config
    BASE_DIR, FB_API_VERSION, ACCESS_TOKEN, STATUS_MAP, _INSIGHTS_FIELDS,
    _date_params,
    # Google Sheets
    col_to_letter, connect_spreadsheet, get_all_accounts,
    read_detail_selections, get_or_create_worksheet, sanitize_sheet_name,
    # Facebook API
    paginate,
    # Metrics
    parse_insight_metrics, aggregate_metrics,
    # Formatting
    _insights_cols,
)

# ── Checkpoint ────────────────────────────────────────────────────────────────
# Cấu trúc: {acc_name: {"done": [camp_id, ...], "raw_ads": [...]}}

CHECKPOINT_FILE = BASE_DIR / "get_details_checkpoint.json"


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_checkpoint(data: dict):
    CHECKPOINT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print("Đã xóa checkpoint.")


def checkpoint_summary() -> str:
    """Trả về chuỗi mô tả checkpoint hiện tại (cho GUI)."""
    cp = load_checkpoint()
    if not cp:
        return ""
    parts = [f"{acc}: {len(v.get('done', []))} camp" for acc, v in cp.items()]
    return "Checkpoint: " + ", ".join(parts)


# ── Creative sheet ─────────────────────────────────────────────────────────────

CREATIVE_HEADERS = [
    "Creative ID",          # A  – ads[].creative.id
    "Ad ID",                # B  – ads[].id
    "Ad Name",              # C  – ads[].name
    "Trạng Thái",           # D  – ads[].status
    "Campaign ID",          # E  – từ vòng lặp fetch
    "Adset Name",           # F  – từ vòng lặp fetch
    "Page ID",              # G  – effective_object_story_id.split("_")[0]
    "Post ID",              # H  – effective_object_story_id.split("_")[1]
    "Thumbnail URL",        # I  – ads[].creative.thumbnail_url
    "Nội Dung Quảng Cáo",  # J  – ads[].creative.body
    "Tiêu Đề",              # K  – ads[].creative.title
    "Ghi Chú",              # L  – người dùng tự điền, giữ nguyên khi refresh
]


def read_creative_notes(worksheet) -> dict[str, str]:
    """Đọc cột 'Ghi Chú' hiện tại theo Creative ID để giữ lại khi ghi đè."""
    try:
        all_values = worksheet.get_all_values()
    except Exception:
        return {}
    if len(all_values) < 2:
        return {}
    header = all_values[0]
    try:
        id_col   = header.index("Creative ID")
        note_col = header.index("Ghi Chú")
    except ValueError:
        return {}
    notes = {}
    for row in all_values[1:]:
        cid  = row[id_col].strip()   if id_col   < len(row) else ""
        note = row[note_col].strip() if note_col < len(row) else ""
        if cid:
            notes[cid] = note
    return notes


def write_creative_sheet(spreadsheet, acc_name: str, creative_rows: list[list]):
    """Ghi danh sách creative vào tab '{acc_name} - Creative'."""
    title = sanitize_sheet_name(f"{acc_name} - Creative")
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if title in existing:
        ws = existing[title]
    else:
        ws = spreadsheet.add_worksheet(
            title=title, rows=2000, cols=len(CREATIVE_HEADERS))

    notes = read_creative_notes(ws)

    rows_with_notes = [
        row + [notes.get(row[0], "")]   # row[0] = Creative ID
        for row in creative_rows
    ]

    last_col = col_to_letter(len(CREATIVE_HEADERS))
    ws.update("A1", [CREATIVE_HEADERS])
    last_row = ws.row_count
    if last_row >= 2:
        ws.batch_clear([f"A2:{last_col}{last_row}"])
    if rows_with_notes:
        ws.update("A2", rows_with_notes)
    return title, len(rows_with_notes)


# ── Facebook Graph API — Adset / Ad ───────────────────────────────────────────

def fetch_adsets(campaign_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{campaign_id}/adsets"
    params = {
        "fields":       "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit":        100,
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
        "limit":        100,
    }
    return paginate(url, params)


def _act_id(account_id: str) -> str:
    # Sheet lưu ID dạng số (đã removeprefix("act_") trong main.py).
    # Edge /insights yêu cầu prefix act_.
    account_id = account_id.strip()
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def fetch_insights_ad_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{_act_id(account_id)}/insights"
    params = {
        "level":        "ad",
        **_date_params(),
        "fields":       f"ad_id,adset_id,campaign_id,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit":        500,
    }
    return paginate(url, params)


# ── Creative extraction ────────────────────────────────────────────────────────

def extract_creative_info(creative: dict) -> dict:
    if not creative:
        return {}

    oss        = creative.get("object_story_spec") or {}
    link_data  = oss.get("link_data")  or {}
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
    link        = creative.get("link_url") or link_data.get("link") or ""
    cta_obj     = link_data.get("call_to_action") or video_data.get("call_to_action") or {}
    cta         = cta_obj.get("type", "") if cta_obj else ""

    return {
        "creative_id":   creative.get("id", ""),
        "page_id":       page_id,
        "post_id":       post_id,
        "body":          body,
        "title":         title,
        "description":   description,
        "link":          link,
        "cta":           cta,
        "thumbnail_url": creative.get("thumbnail_url", ""),
    }


# ── Row builders ───────────────────────────────────────────────────────────────

def _adset_row(camp_id, adset, m: dict, now_str: str) -> list:
    """Dòng Adset — 25 cột. C = Campaign ID (reference), D = Adset Name."""
    return [
        "",                                                                        # A
        "Adset",                                                                   # B
        camp_id,                                                                   # C  Campaign ID
        adset.get("name", ""),                                                     # D  Adset Name
        STATUS_MAP.get(adset.get("status", ""), adset.get("status", "")),          # E
    ] + _insights_cols(m) + ["", now_str]  # X trống + Y


def _ad_row(camp_id, ad, m: dict, now_str: str) -> list:
    """Dòng Ad — 25 cột. C = Campaign ID (reference), D = Ad Name."""
    return [
        "",                                                                        # A
        "Ad",                                                                      # B
        camp_id,                                                                   # C  Campaign ID
        ad.get("name", ""),                                                        # D  Ad Name
        STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),                # E
    ] + _insights_cols(m) + ["", now_str]  # X trống + Y


def refresh_adset_ad_rows(worksheet, adset_data_map: dict, ad_insights_map: dict,
                          detail_selections: dict, now_str: str):
    """
    Xóa toàn bộ dòng Adset/Ad hiện tại rồi chèn lại đúng vị trí.
    Dòng Campaign giữ nguyên — dữ liệu và mọi cột ngoài script không bị mất.
    Dùng insert_rows() nên các cột phía sau tự dịch chuyển theo đúng hàng.
    """
    all_data = worksheet.get_all_values()
    if len(all_data) < 2:
        return

    header = all_data[0]
    try:
        cap_col     = header.index("Cấp")
        camp_id_col = header.index("Campaign ID")
    except ValueError:
        return

    status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}

    # ── Bước 1: Xóa dòng Adset/Ad từ dưới lên (tránh lệch index) ────────────
    to_delete = [
        i + 2  # i=0 → sheet row 2 (bỏ header)
        for i, row in enumerate(all_data[1:])
        if (row[cap_col] if cap_col < len(row) else "") in ("Adset", "Ad")
    ]
    for rn in reversed(to_delete):
        worksheet.delete_rows(rn)

    # ── Bước 2: Đọc lại sau khi xóa ─────────────────────────────────────────
    all_data = worksheet.get_all_values()

    # ── Bước 3: Tìm vị trí Campaign được chọn ────────────────────────────────
    selected_positions = [
        (i + 2, row[camp_id_col] if camp_id_col < len(row) else "")
        for i, row in enumerate(all_data[1:])
        if (row[cap_col] if cap_col < len(row) else "") == "Campaign"
        and detail_selections.get(row[camp_id_col] if camp_id_col < len(row) else "", False)
    ]

    # ── Bước 4: Chèn dòng Adset/Ad từ dưới lên ───────────────────────────────
    inserted_total = 0
    for sheet_row, camp_id in reversed(selected_positions):
        adsets = sorted(
            adset_data_map.get(camp_id, []),
            key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
        )
        new_rows = []
        for adset in adsets:
            ads = sorted(
                adset.get("_ads", []),
                key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
            )
            ad_mets = [
                parse_insight_metrics(ad_insights_map.get(ad.get("id", ""), {}))
                for ad in ads
            ]
            adset_m = aggregate_metrics(ad_mets) if ad_mets else parse_insight_metrics({})
            new_rows.append(_adset_row(camp_id, adset, adset_m, now_str))
            for ad, ad_m in zip(ads, ad_mets):
                new_rows.append(_ad_row(camp_id, ad, ad_m, now_str))

        if new_rows:
            worksheet.insert_rows(new_rows, sheet_row + 1)
            inserted_total += len(new_rows)

    return inserted_total


# ── Per-campaign write ─────────────────────────────────────────────────────────

def _write_one_campaign(worksheet, camp_id: str, adsets: list,
                        ad_insights_map: dict, now_str: str) -> int:
    """Xóa Adset/Ad cũ của đúng 1 campaign rồi chèn dữ liệu mới — không đụng campaign khác."""
    all_data = worksheet.get_all_values()
    if len(all_data) < 2:
        return 0

    header = all_data[0]
    try:
        cap_col     = header.index("Cấp")
        camp_id_col = header.index("Campaign ID")
    except ValueError:
        return 0

    status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}

    # Xóa Adset/Ad của campaign này (từ dưới lên)
    to_delete = [
        i + 2
        for i, row in enumerate(all_data[1:])
        if (row[cap_col] if cap_col < len(row) else "") in ("Adset", "Ad")
        and (row[camp_id_col] if camp_id_col < len(row) else "") == camp_id
    ]
    for rn in reversed(to_delete):
        worksheet.delete_rows(rn)

    # Đọc lại để index đúng sau khi xóa
    all_data = worksheet.get_all_values()

    # Tìm vị trí dòng Campaign
    camp_row = None
    for i, row in enumerate(all_data[1:]):
        if (row[cap_col] if cap_col < len(row) else "") == "Campaign" and \
           (row[camp_id_col] if camp_id_col < len(row) else "") == camp_id:
            camp_row = i + 2
            break

    if camp_row is None:
        return 0

    # Build và insert dòng Adset/Ad
    new_rows = []
    for adset in sorted(adsets, key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", ""))):
        ads = sorted(adset.get("_ads", []),
                     key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")))
        ad_mets = [parse_insight_metrics(ad_insights_map.get(ad.get("id", ""), {})) for ad in ads]
        adset_m  = aggregate_metrics(ad_mets) if ad_mets else parse_insight_metrics({})
        new_rows.append(_adset_row(camp_id, adset, adset_m, now_str))
        for ad, ad_m in zip(ads, ad_mets):
            new_rows.append(_ad_row(camp_id, ad, ad_m, now_str))

    if new_rows:
        worksheet.insert_rows(new_rows, camp_row + 1)
    return len(new_rows)


# ── Core processing ────────────────────────────────────────────────────────────

def run_for_accounts(spreadsheet, accounts: list[dict]):
    month_label = datetime.now().strftime("%m/%Y")
    checkpoint  = load_checkpoint()
    dump_insights_ad: dict[str, list] = {}

    rate_limited = False
    try:
        for acc in accounts:
            acc_id   = acc["id"]
            acc_name = acc["name"]
            print(f"\n[{acc_name}] Lấy chi tiết tháng {month_label}...")

            ws = get_or_create_worksheet(spreadsheet, acc_name)
            detail_selections = read_detail_selections(ws)
            selected_camp_ids = {cid for cid, v in detail_selections.items() if v}

            if not selected_camp_ids:
                print("  → Bỏ qua (không có campaign nào được chọn lấy chi tiết).")
                continue

            # ── Checkpoint: tách campaign đã xong và còn lại ─────────────────
            cp_acc    = checkpoint.setdefault(acc_name, {"done": [], "raw_ads": []})
            done_set  = set(cp_acc.get("done", []))
            remaining = [c for c in selected_camp_ids if c not in done_set]

            if done_set:
                print(f"  → Checkpoint: {len(done_set)} campaign đã xong, "
                      f"{len(remaining)} còn lại.")
            else:
                print(f"  → {len(selected_camp_ids)} campaign được chọn lấy chi tiết.")

            if not remaining:
                print("  → Tất cả campaign đã được xử lý (checkpoint). Bỏ qua fetch API.")
            else:
                # Insights 1 call/account — luôn fetch để có dữ liệu mới nhất
                ad_insights = fetch_insights_ad_level(acc_id)
                ad_insights_map = {r["ad_id"]: r for r in ad_insights if "ad_id" in r}
                dump_insights_ad[acc_name] = ad_insights
                print(f"  → {len(ad_insights)} dòng insights ad.")

                # ── Fetch + write từng campaign, checkpoint ngay sau mỗi cái ─
                for i, camp_id in enumerate(remaining):
                    if i > 0:
                        print(f"  ⏱ Nghỉ {CAMPAIGN_DELAY}s trước campaign tiếp theo...")
                        time.sleep(CAMPAIGN_DELAY)

                    adsets = fetch_adsets(camp_id)
                    raw_ads_camp: list[dict] = []
                    for adset in adsets:
                        ads = fetch_ads(adset["id"])
                        for ad in ads:
                            ad["_camp_id"]    = camp_id
                            ad["_adset_name"] = adset.get("name", "")
                        raw_ads_camp.extend(ads)
                        adset["_ads"] = ads

                    now_str  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    inserted = _write_one_campaign(ws, camp_id, adsets, ad_insights_map, now_str)
                    print(f"  → [{camp_id}] {len(adsets)} adsets, "
                          f"{len(raw_ads_camp)} ads — ghi {inserted} dòng.")

                    # Lưu checkpoint ngay
                    done_set.add(camp_id)
                    cp_acc["done"]     = list(done_set)
                    cp_acc["raw_ads"]  = cp_acc.get("raw_ads", []) + raw_ads_camp
                    _save_checkpoint(checkpoint)

            # ── Creative sheet dùng toàn bộ raw_ads (checkpoint + lần này) ──
            all_raw_ads = cp_acc.get("raw_ads", [])
            creative_rows = []
            for ad in all_raw_ads:
                c = extract_creative_info(ad.get("creative") or {})
                creative_rows.append([
                    c.get("creative_id",  ""),
                    ad.get("id",          ""),
                    ad.get("name",        ""),
                    STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),
                    ad.get("_camp_id",    ""),
                    ad.get("_adset_name", ""),
                    c.get("page_id",      ""),
                    c.get("post_id",      ""),
                    c.get("thumbnail_url",""),
                    c.get("body",         ""),
                    c.get("title",        ""),
                ])
            c_title, c_count = write_creative_sheet(spreadsheet, acc_name, creative_rows)
            print(f"  → Đã ghi {c_count} creative vào tab '{c_title}'.")

            # Account xong hoàn toàn → xóa khỏi checkpoint
            checkpoint.pop(acc_name, None)
            _save_checkpoint(checkpoint)

    except RateLimitError as e:
        rate_limited = True
        print(f"\n⚠ Rate limit: {e}")
        done_total = sum(len(v.get("done", [])) for v in checkpoint.values())
        print(f"Checkpoint đã lưu ({done_total} campaign). Chạy lại để tiếp tục.")

    api_summary()
    if not checkpoint:
        clear_checkpoint()
    if rate_limited:
        raise RateLimitError("Rate limit — checkpoint đã lưu, nhấn Chạy để tiếp tục.")
    print("\nHoàn thành!")


# ── GUI ────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    BG         = "#EDF1F7"
    CARD       = "#FFFFFF"
    BORDER     = "#DCE3EC"
    ACCENT     = "#2D6CDF"
    ACCENT_HV  = "#1F5AC4"
    ACCENT_DIS = "#AEC4EC"
    TEXT       = "#1E293B"
    MUTED      = "#64748B"

    def __init__(self):
        super().__init__()
        self.title("Get Details – Chọn Tài Khoản")
        self.geometry("720x440")
        self.minsize(560, 320)
        self.configure(bg=self.BG)
        self.resizable(True, True)

        self._spreadsheet = None
        self._items: list[dict] = []

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",  background=self.BG)
        s.configure("TLabel",  background=self.BG,
                    font=("Segoe UI", 10), foreground=self.TEXT)
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background="#E2E8F0", foreground="#334155",
                    bordercolor="#B9C4D4", relief="flat", borderwidth=1)
        s.map("TButton",
              background=[("active", "#CBD5E1"), ("disabled", "#F1F5F9")],
              foreground=[("disabled", "#B0B8C4")])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(22, 9), background=self.ACCENT,
                    foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#EEF2FB")])
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=28,
                    background=self.CARD, fieldbackground=self.CARD,
                    foreground=self.TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background="#F1F5F9", foreground="#475569",
                    relief="flat", padding=(8, 6))
        s.map("Treeview",
              background=[("selected", "#DBE7FB")],
              foreground=[("selected", self.TEXT)])
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor="#E2E8F0", borderwidth=0, thickness=6)

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 10))
        tk.Label(hdr, text="Get Details", bg=self.BG,
                 font=("Segoe UI Semibold", 15), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        tk.Label(outer,
                 text="Chỉ tài khoản có 'Chọn Lấy Camp' = TRUE. "
                      "Click dòng để bật / tắt tài khoản muốn lấy chi tiết.",
                 bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        # Pack bot trước card để luôn hiển thị dù cửa sổ thấp
        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(12, 0), side="bottom")

        card = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = ("chon", "acc_name", "acc_id")
        self._tree = ttk.Treeview(card, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("chon",     text="Chọn",          anchor="center")
        self._tree.heading("acc_name", text="Tên Tài Khoản",  anchor="w")
        self._tree.heading("acc_id",   text="ID Tài Khoản",   anchor="w")
        self._tree.column("chon",     width=56,  stretch=False, anchor="center", minwidth=50)
        self._tree.column("acc_name", width=280, stretch=True,  minwidth=140)
        self._tree.column("acc_id",   width=170, stretch=False, minwidth=110)

        vsb = ttk.Scrollbar(card, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(card, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("on",  foreground="#15803D")
        self._tree.tag_configure("off", foreground="#DC2626")
        self._tree.tag_configure("odd", background="#F8FAFC")

        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind("<space>",           self._on_space)

        ttk.Button(bot, text="Bật tất cả",
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bot, text="Tắt tất cả",
                   command=lambda: self._set_all(False)).pack(side="left", padx=(6, 0))
        self._new_run_btn = ttk.Button(bot, text="Bắt đầu mới",
                                       command=self._new_run)
        self._new_run_btn.pack(side="left", padx=(10, 0))

        self._count_lbl = tk.Label(bot, text="", bg=self.BG,
                                   font=("Segoe UI", 9), fg=self.MUTED)
        self._count_lbl.pack(side="left", padx=10)

        self._run_btn = ttk.Button(bot, text="Chạy / Tiếp tục",
                                   style="Accent.TButton",
                                   command=self._run, state="disabled")
        self._run_btn.pack(side="right")
        ttk.Button(bot, text="Huỷ", command=self.destroy).pack(side="right", padx=(0, 8))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=110)
        self._progress.pack(side="right", padx=(0, 10))

        # Label checkpoint — hiển thị bên dưới treeview
        self._cp_lbl = tk.Label(outer, text="", bg=self.BG,
                                font=("Segoe UI", 9), fg="#D97706")
        self._cp_lbl.pack(fill="x", pady=(4, 0), side="bottom")

    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss       = connect_spreadsheet()
            accounts = get_all_accounts(ss)
            selected = [a for a in accounts if a.get("selected")]
            self._spreadsheet = ss
            self.after(0, lambda: self._load_items(
                selected, f"Kết nối OK · {ss.title} · {len(selected)} tài khoản"))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi: {e}", error=True))

    def _load_items(self, accounts: list[dict], status_text: str):
        self._set_status(status_text)
        self._items = []
        for i, acc in enumerate(accounts):
            selected = True
            base_tag = "on" if selected else "off"
            tags = ("odd", base_tag) if i % 2 != 0 else (base_tag,)
            iid = self._tree.insert("", "end", values=(
                "✓" if selected else "✗",
                acc["name"],
                acc["id"],
            ), tags=tags)
            self._items.append({**acc, "iid": iid, "selected": selected})
        self._refresh_count()
        if self._items:
            self._run_btn.configure(state="normal")
        self._refresh_cp()

    def _toggle(self, iid: str):
        item = next((i for i in self._items if i["iid"] == iid), None)
        if item is None:
            return
        item["selected"] = not item["selected"]
        idx = self._items.index(item)
        base_tag = "on" if item["selected"] else "off"
        tags = ("odd", base_tag) if idx % 2 != 0 else (base_tag,)
        self._tree.item(iid, values=(
            "✓" if item["selected"] else "✗",
            item["name"], item["id"],
        ), tags=tags)
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
            idx = self._items.index(item)
            base_tag = "on" if value else "off"
            tags = ("odd", base_tag) if idx % 2 != 0 else (base_tag,)
            self._tree.item(item["iid"], values=(
                "✓" if value else "✗", item["name"], item["id"],
            ), tags=tags)
        self._refresh_count()
        self._run_btn.configure(state="normal" if value and self._items else "disabled")

    def _toggle_all(self):
        self._set_all(not any(i["selected"] for i in self._items))

    def _refresh_count(self):
        total    = len(self._items)
        selected = sum(1 for i in self._items if i["selected"])
        self._count_lbl.configure(
            text=f"{selected}/{total} được chọn" if total else "Không có tài khoản nào"
        )

    def _run(self):
        accounts = [i for i in self._items if i["selected"]]
        if not accounts:
            messagebox.showwarning("Chưa chọn", "Chưa bật tài khoản nào.")
            return
        self._run_btn.configure(state="disabled")
        self._progress.start(12)
        self._set_status(f"Đang chạy {len(accounts)} tài khoản...")
        threading.Thread(target=self._run_worker, args=(list(accounts),), daemon=True).start()

    def _run_worker(self, accounts: list[dict]):
        try:
            run_for_accounts(self._spreadsheet, accounts)
            self.after(0, self._done)
        except RateLimitError as e:
            self.after(0, lambda e=e: self._rate_limited(str(e)))
        except Exception as e:
            self.after(0, lambda e=e: self._error(str(e)))

    def _new_run(self):
        if messagebox.askyesno("Bắt đầu mới", "Xóa checkpoint và bắt đầu lại từ đầu?"):
            clear_checkpoint()
            self._refresh_cp()

    def _refresh_cp(self):
        summary = checkpoint_summary()
        self._cp_lbl.configure(
            text=f"⚡ {summary} — nhấn Chạy để tiếp tục" if summary else ""
        )
        self._new_run_btn.configure(state="normal" if summary else "disabled")

    def _done(self):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._set_status("✓ Hoàn thành!")
        self._refresh_cp()
        messagebox.showinfo("Hoàn thành", "Đã lấy xong chi tiết cho các tài khoản được chọn.")

    def _rate_limited(self, msg: str):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._set_status("⚠ Rate limit — checkpoint đã lưu", error=True)
        self._refresh_cp()
        messagebox.showwarning(
            "Rate Limit",
            f"{msg}\n\nCheckpoint đã lưu tiến trình.\n"
            "Nhấn 'Chạy / Tiếp tục' để tiếp tục từ chỗ còn lại."
        )

    def _error(self, msg: str):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._set_status(f"✗ Lỗi: {msg}", error=True)
        messagebox.showerror("Lỗi", msg)

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, foreground="#CC0000" if error else self.MUTED
        )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if tk is None:
        sys.exit("Cần tkinter để chạy giao diện (có sẵn trong Python chuẩn trên Windows).")
    App().mainloop()
