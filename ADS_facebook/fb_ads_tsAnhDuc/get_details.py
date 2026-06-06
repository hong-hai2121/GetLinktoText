"""
Phase 2 – Lấy chi tiết Adset / Ad + Insights cấp Ad cho các Campaign đã được
         đánh TRUE ở cột "Chọn Lấy Chi Tiết" (trong các tab TKQC).

Chạy SAU khi đã chạy get_campaigns.py và đánh dấu campaign muốn xem chi tiết.
Script CHÈN dòng Adset/Ad vào ngay dưới dòng Campaign tương ứng, KHÔNG xóa dữ
liệu dòng Campaign hiện có (kể cả các cột ngoài cấu trúc script quản lý).

Chạy:  python get_details.py
"""

import sys
import json
import time
import threading
from datetime import datetime

CAMPAIGN_DELAY = 5  # giây nghỉ giữa mỗi campaign — giảm tần suất gọi API
ACCOUNT_DELAY  = 3  # giây nghỉ giữa mỗi TKQC — giảm tần suất gọi API

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    tk = None

from fb_api import api_summary, RateLimitError
from get_campaigns import (
    # Constants & config
    BASE_DIR, FB_API_VERSION, ACCESS_TOKEN, STATUS_MAP, _INSIGHTS_FIELDS,
    _date_params, HEADERS,
    # Google Sheets
    col_to_letter, connect_spreadsheet, get_all_accounts,
    read_detail_selections, get_or_create_worksheet, sanitize_sheet_name,
    # Facebook API
    paginate, fetch_insights_campaign_level,
    # Metrics
    parse_insight_metrics, aggregate_metrics,
    # Formatting
    _insights_cols,
)

# Màu nền nhạt theo Cấp để dễ nhìn (Google Sheets dùng RGB 0–1).
COLOR_CAMPAIGN = {"red": 0.81, "green": 0.89, "blue": 0.97}  # xanh dương nhạt
COLOR_ADSET    = {"red": 1.0,  "green": 0.95, "blue": 0.80}  # vàng kem nhạt
COLOR_AD       = {"red": 0.93, "green": 0.91, "blue": 0.97}  # tím nhạt

# ── Checkpoint ────────────────────────────────────────────────────────────────
# Cấu trúc: {acc_name: {"done": [camp_id, ...]}}

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


# ── Facebook Graph API — Adset / Ad ───────────────────────────────────────────

def _act_id(account_id: str) -> str:
    account_id = account_id.strip()
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


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
        "fields":       "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit":        100,
    }
    return paginate(url, params)


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


# ── Row builders ───────────────────────────────────────────────────────────────

def _adset_row(camp_id, adset, m: dict, now_str: str) -> list:
    """Dòng Adset — 25 cột. B = Cấp, C = Campaign ID (reference), D = Adset Name."""
    return [
        "",                                                                # A  Chọn (trống)
        "Adset",                                                           # B  Cấp
        camp_id,                                                           # C  Campaign ID
        adset.get("name", ""),                                             # D  Adset Name
        STATUS_MAP.get(adset.get("status", ""), adset.get("status", "")),  # E
    ] + _insights_cols(m) + ["", now_str]  # X trống + Y


def _ad_row(camp_id, ad, m: dict, now_str: str) -> list:
    """Dòng Ad — 25 cột. B = Cấp, C = Campaign ID (reference), D = Ad Name."""
    return [
        "",                                                          # A  Chọn (trống)
        "Ad",                                                        # B  Cấp
        camp_id,                                                     # C  Campaign ID
        ad.get("name", ""),                                          # D  Ad Name
        STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),  # E
    ] + _insights_cols(m) + ["", now_str]  # X trống + Y


# ── Per-campaign write ─────────────────────────────────────────────────────────

def _write_one_campaign(worksheet, camp_id: str, adsets: list,
                        ad_insights_map: dict, now_str: str,
                        camp_insights_map: dict | None = None) -> int:
    """Xóa Adset/Ad cũ của đúng 1 campaign rồi chèn dữ liệu mới — không đụng campaign khác.
    Nếu có camp_insights_map, cập nhật luôn metrics dòng Campaign (cột F–Y)."""
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

    # Xóa Adset/Ad của campaign này (từ dưới lên để không lệch index)
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

    # Cập nhật metrics dòng Campaign (F–Y) với dữ liệu mới nhất
    if camp_insights_map and camp_id in camp_insights_map:
        m = parse_insight_metrics(camp_insights_map[camp_id])
        camp_update = _insights_cols(m) + [
            int(round(m["spend"])) if m["spend"] > 0 else "",  # X
            now_str,                                            # Y
        ]
        worksheet.update(f"F{camp_row}:Y{camp_row}", [camp_update])

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

    # Tô màu nền theo Cấp: Campaign / Adset / Ad mỗi cấp 1 màu nhạt cho dễ nhìn.
    last_col = col_to_letter(len(HEADERS))
    formats = [{
        "range":  f"A{camp_row}:{last_col}{camp_row}",
        "format": {"backgroundColor": COLOR_CAMPAIGN},
    }]
    for k, row in enumerate(new_rows):
        sheet_row = camp_row + 1 + k
        color = COLOR_ADSET if row[1] == "Adset" else COLOR_AD  # cột B = Cấp
        formats.append({
            "range":  f"A{sheet_row}:{last_col}{sheet_row}",
            "format": {"backgroundColor": color},
        })
    worksheet.batch_format(formats)

    return len(new_rows)


# ── JSON output (để kiểm tra dữ liệu đã lấy) ────────────────────────────────────

JSON_FILE = BASE_DIR / "get_details.json"


def save_json(dump: dict, api_info: dict | None = None):
    """Ghi toàn bộ dữ liệu thô đã lấy (adset/ad + insights) ra file để check."""
    payload: dict = {}
    if api_info:
        payload["_api"] = api_info
    payload.update(dump)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  JSON → {JSON_FILE}")


# ── Core processing ────────────────────────────────────────────────────────────

def run_for_accounts(spreadsheet, accounts: list[dict]):
    month_label = datetime.now().strftime("%m/%Y")
    checkpoint  = load_checkpoint()
    dump: dict[str, dict] = {}   # {acc_name: {campaign_insights, ad_insights, campaigns}}

    rate_limited = False
    try:
        for ai, acc in enumerate(accounts):
            if ai > 0:
                print(f"⏱ Nghỉ {ACCOUNT_DELAY}s trước TKQC tiếp theo...")
                time.sleep(ACCOUNT_DELAY)
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
            cp_acc    = checkpoint.setdefault(acc_name, {"done": []})
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
                # Insights cấp campaign — để cập nhật dòng Campaign trong sheet
                camp_insights = fetch_insights_campaign_level(acc_id)
                camp_insights_map = {r["campaign_id"]: r for r in camp_insights if "campaign_id" in r}
                print(f"  → {len(camp_insights)} dòng insights campaign.")

                # Insights cấp ad — để ghi dòng Adset/Ad
                ad_insights = fetch_insights_ad_level(acc_id)
                ad_insights_map = {r["ad_id"]: r for r in ad_insights if "ad_id" in r}
                print(f"  → {len(ad_insights)} dòng insights ad.")

                # Gom dữ liệu thô để xuất JSON kiểm tra
                acc_dump = dump.setdefault(acc_name, {"campaigns": {}})
                acc_dump["campaign_insights"] = camp_insights
                acc_dump["ad_insights"] = ad_insights

                # ── Fetch + write từng campaign, checkpoint ngay sau mỗi cái ─
                for i, camp_id in enumerate(remaining):
                    if i > 0:
                        print(f"  ⏱ Nghỉ {CAMPAIGN_DELAY}s trước campaign tiếp theo...")
                        time.sleep(CAMPAIGN_DELAY)

                    adsets = fetch_adsets(camp_id)
                    for adset in adsets:
                        adset["_ads"] = fetch_ads(adset["id"])

                    acc_dump["campaigns"][camp_id] = adsets

                    now_str  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    inserted = _write_one_campaign(
                        ws, camp_id, adsets, ad_insights_map, now_str,
                        camp_insights_map=camp_insights_map,
                    )
                    print(f"  → [{camp_id}] {len(adsets)} adsets — "
                          f"ghi {inserted} dòng (campaign updated).")

                    # Lưu checkpoint ngay
                    done_set.add(camp_id)
                    cp_acc["done"] = list(done_set)
                    _save_checkpoint(checkpoint)

            # Account xong hoàn toàn → xóa khỏi checkpoint
            checkpoint.pop(acc_name, None)
            _save_checkpoint(checkpoint)

    except RateLimitError as e:
        rate_limited = True
        print(f"\n⚠ Rate limit: {e}")
        done_total = sum(len(v.get("done", [])) for v in checkpoint.values())
        print(f"Checkpoint đã lưu ({done_total} campaign). Chạy lại để tiếp tục.")

    # Xuất JSON dữ liệu thô (kể cả khi rate limit — lưu phần đã lấy được)
    base = f"https://graph.facebook.com/{FB_API_VERSION}"
    print("\nLưu JSON...")
    save_json(dump, {
        "adsets":            f"GET {base}/{{campaign_id}}/adsets  (fields=id,name,status)",
        "ads":               f"GET {base}/{{adset_id}}/ads  (fields=id,name,status)",
        "insights_campaign": f"GET {base}/act_{{id}}/insights  (level=campaign)",
        "insights_ad":       f"GET {base}/act_{{id}}/insights  (level=ad)",
        "date":              _date_params(),
        "note":              "Mỗi tài khoản: campaign_insights, ad_insights, campaigns{camp_id: [adset{_ads:[ad]}]}",
    })

    api_summary()
    if not checkpoint:
        clear_checkpoint()
    if rate_limited:
        raise RateLimitError("Rate limit — checkpoint đã lưu, nhấn Chạy để tiếp tục.")
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
        self.title("Get Details – Chọn Tài Khoản")

        w, h = 720, 440
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
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
                      "Click dòng để bật / tắt tài khoản muốn lấy chi tiết Adset/Ad.",
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

        self._tree.tag_configure("on",  foreground="#198754")
        self._tree.tag_configure("off", foreground="#dc3545")
        self._tree.tag_configure("odd", background="#f1f3f5")

        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind("<space>",           self._on_space)

        ttk.Button(bot, text="Bật tất cả",
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bot, text="Tắt tất cả",
                   command=lambda: self._set_all(False)).pack(side="left", padx=(6, 0))

        self._count_lbl = tk.Label(bot, text="", bg=self.BG,
                                   font=("Segoe UI", 9), fg=self.MUTED)
        self._count_lbl.pack(side="left", padx=10)

        self._run_btn = ttk.Button(bot, text="Chạy",
                                   style="Accent.TButton",
                                   command=self._run, state="disabled")
        self._run_btn.pack(side="right")
        ttk.Button(bot, text="Huỷ", command=self.destroy).pack(side="right", padx=(0, 8))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=110)
        self._progress.pack(side="right", padx=(0, 10))

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

    def _update_item_ui(self, item: dict):
        idx = self._items.index(item)
        base_tag = "on" if item["selected"] else "off"
        tags = ("odd", base_tag) if idx % 2 != 0 else (base_tag,)
        self._tree.item(item["iid"], values=(
            "✓" if item["selected"] else "✗",
            item["name"], item["id"],
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
            text=f"{selected}/{total} được chọn" if total else "Không có tài khoản nào"
        )

    def _run(self):
        accounts = [i for i in self._items if i["selected"]]
        if not accounts:
            messagebox.showwarning("Chưa chọn", "Chưa bật tài khoản nào.")
            return
        clear_checkpoint()
        self._run_btn.configure(state="disabled")
        self._progress.start(12)
        self._set_status(f"Đang chạy {len(accounts)} tài khoản...")
        threading.Thread(target=self._run_worker,
                         args=(list(accounts),), daemon=True).start()

    def _run_worker(self, accounts: list[dict]):
        try:
            run_for_accounts(self._spreadsheet, accounts)
            self.after(0, self._done)
        except RateLimitError as e:
            self.after(0, lambda e=e: self._rate_limited(str(e)))
        except Exception as e:
            self.after(0, lambda e=e: self._error(str(e)))

    def _done(self):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._set_status("✓ Hoàn thành!")
        messagebox.showinfo("Hoàn thành", "Đã lấy xong chi tiết cho các tài khoản được chọn.")

    def _rate_limited(self, msg: str):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._set_status("⚠ Rate limit", error=True)
        messagebox.showwarning("Rate Limit", msg)

    def _error(self, msg: str):
        self._progress.stop()
        self._run_btn.configure(state="normal")
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
