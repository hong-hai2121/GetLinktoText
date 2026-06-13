"""
Gộp các tab 'Tên TKQC (Kỳ)' (do get_campaigns tạo) THEO KỲ: mỗi khoảng thời gian
(Hôm nay / Tháng này / Toàn thời gian…) có 1 sheet tổng hợp riêng.

  - Tất cả tab cùng 1 Kỳ → xếp chồng vào sheet 'Tổng Hợp (Kỳ)' tương ứng.
    Vd: mọi tab 'Toàn thời gian' → 'Tổng Hợp (Toàn thời gian)'.
  - 1 hàng header chung ở trên cùng mỗi sheet tổng.
  - Mỗi tab nguồn: 1 hàng tiêu đề in đậm (tên tab) rồi tới toàn bộ dòng dữ liệu
    của tab đó (Campaign/Adset/Ad), giữ màu nền theo Cấp cho dễ nhìn.

GUI liệt kê các KỲ để tick chọn (không chọn từng tab lẻ). Mỗi kỳ được chọn sẽ
gộp tất cả tab của kỳ đó vào đúng sheet tổng của kỳ.
Chạy:  python tong_hop.py
"""

import sys
import json
import threading

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    tk = None

from get_campaigns import (
    DATE_PRESET_OPTIONS, HEADERS, col_to_letter, connect_spreadsheet,
    list_campaign_tabs, sanitize_sheet_name,
)

OUTPUT_PREFIX = "Tổng Hợp"
OUTPUT_TITLE  = OUTPUT_PREFIX  # fallback khi gọi build_combined_sheet không truyền tên


def output_title_for(preset_label: str) -> str:
    """Tên sheet tổng cho 1 Kỳ: 'Tổng Hợp (Toàn thời gian)'…"""
    return sanitize_sheet_name(f"{OUTPUT_PREFIX} ({preset_label})")


def group_tabs_by_preset(tabs: list[dict]) -> list[dict]:
    """Gom các tab theo Kỳ (preset). Trả [{preset, preset_label, output_title,
    titles}] — giữ thứ tự Kỳ theo DATE_PRESET_OPTIONS."""
    order = {value: i for i, (_label, value) in enumerate(DATE_PRESET_OPTIONS)}
    groups: dict[str, dict] = {}
    for t in tabs:
        g = groups.setdefault(t["preset"], {
            "preset":       t["preset"],
            "preset_label": t["preset_label"],
            "output_title": output_title_for(t["preset_label"]),
            "titles":       [],
        })
        g["titles"].append(t["title"])
    return sorted(groups.values(), key=lambda g: order.get(g["preset"], 99))

# Màu nền theo Cấp (đồng bộ với get_details) — Google Sheets dùng RGB 0–1.
COLOR_SECTION  = {"red": 0.20, "green": 0.26, "blue": 0.33}  # xám đậm, chữ trắng
COLOR_CAMPAIGN = {"red": 0.81, "green": 0.89, "blue": 0.97}  # xanh dương nhạt
COLOR_ADSET    = {"red": 1.0,  "green": 0.95, "blue": 0.80}  # vàng kem nhạt
COLOR_AD       = {"red": 0.93, "green": 0.91, "blue": 0.97}  # tím nhạt
COLOR_DEFAULT  = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
WHITE          = {"red": 1.0,  "green": 1.0,  "blue": 1.0}

STYLE_FORMAT = {
    "section":  {"textFormat": {"bold": True, "foregroundColor": WHITE},
                 "backgroundColor": COLOR_SECTION},
    "campaign": {"backgroundColor": COLOR_CAMPAIGN},
    "adset":    {"backgroundColor": COLOR_ADSET},
    "ad":       {"backgroundColor": COLOR_AD},
    "default":  {"backgroundColor": COLOR_DEFAULT},
}

_LEVEL_KEY = {"Campaign": "campaign", "Adset": "adset", "Ad": "ad"}


# ── Core ────────────────────────────────────────────────────────────────────────

def _grouped_formats(styles: list[tuple[int, str]], last_col: str) -> list[dict]:
    """Gom các hàng liền kề cùng style thành 1 range để giảm số request."""
    out, i, n = [], 0, len(styles)
    while i < n:
        key = styles[i][1]
        j = i
        while j + 1 < n and styles[j + 1][1] == key and styles[j + 1][0] == styles[j][0] + 1:
            j += 1
        out.append({
            "range":  f"A{styles[i][0]}:{last_col}{styles[j][0]}",
            "format": STYLE_FORMAT[key],
        })
        i = j + 1
    return out


def build_combined_sheet(spreadsheet, tab_titles: list[str],
                         output_title: str = OUTPUT_TITLE, log=print) -> dict:
    """Đọc từng tab trong tab_titles, xếp chồng dữ liệu vào sheet output_title."""
    all_ws = {ws.title: ws for ws in spreadsheet.worksheets()}

    header = HEADERS.copy()  # 20 cột A–T; kỳ đã nằm ở dòng tiêu đề ▼ của mỗi tab

    all_rows: list[list] = [header]
    styles: list[tuple[int, str]] = []   # (row_1based, style_key) cho từng hàng sau header
    used = 0

    for title in tab_titles:
        src = all_ws.get(title)
        if src is None:
            log(f"  ⚠ Bỏ qua '{title}' (không tìm thấy tab).")
            continue
        values = src.get_all_values()
        data = values[1:] if len(values) > 1 else []   # bỏ hàng header của tab nguồn

        all_rows.append([f"▼ {title}"])
        styles.append((len(all_rows), "section"))

        if not data:
            all_rows.append(["(không có dữ liệu)"])
            styles.append((len(all_rows), "default"))
        else:
            for row in data:
                all_rows.append(row)
                level = row[1].strip() if len(row) > 1 else ""   # cột B = Cấp
                styles.append((len(all_rows), _LEVEL_KEY.get(level, "default")))

        used += 1
        log(f"  + {title}: {len(data)} dòng")

    # ── Tạo / mở sheet đích ──────────────────────────────────────────────────
    need_rows = max(200, len(all_rows) + 10)
    need_cols = max(26, len(HEADERS) + 1)
    if output_title in all_ws:
        out = all_ws[output_title]
        if out.row_count < need_rows or out.col_count < need_cols:
            out.resize(rows=max(out.row_count, need_rows),
                       cols=max(out.col_count, need_cols))
        created = False
    else:
        out = spreadsheet.add_worksheet(title=output_title, rows=need_rows, cols=need_cols)
        created = True

    out.clear()
    last_col = col_to_letter(len(HEADERS))  # 'Y'

    # Freeze hàng 1 + ép cột Campaign ID (C) sang TEXT TRƯỚC khi ghi để ID 17 số
    # không bị Sheets làm tròn.
    spreadsheet.batch_update({"requests": [
        {"updateSheetProperties": {
            "properties": {"sheetId": out.id,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {
            "range": {"sheetId": out.id, "startColumnIndex": 2, "endColumnIndex": 3},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
            "fields": "userEnteredFormat.numberFormat"}},
    ]})

    out.update(values=all_rows, range_name="A1", value_input_option="RAW")

    formats = [{"range": f"A1:{last_col}1", "format": {"textFormat": {"bold": True}}}]
    formats += _grouped_formats(styles, last_col)
    out.batch_format(formats)

    return {
        "tabs":         used,
        "rows":         len(all_rows) - 1,
        "output_title": output_title,
        "created":      created,
    }


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
        self.title("Tổng Hợp – Gộp Tab Thành 1 Sheet")

        w, h = 720, 460
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(560, 340)
        self.configure(bg=self.BG)

        self._spreadsheet = None
        self._items: list[dict] = []

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background=self.BORDER, foreground=self.TEXT, relief="flat", borderwidth=1)
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
        tk.Label(hdr, text="Tổng Hợp Sheet", bg=self.BG,
                 font=("Segoe UI Semibold", 15), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        tk.Label(outer,
                 text="Mỗi dòng là 1 Kỳ (khoảng thời gian). Click để bật / tắt kỳ muốn gộp. "
                      "Mỗi kỳ được chọn sẽ gộp TẤT CẢ tab của kỳ đó vào sheet "
                      f"'{OUTPUT_PREFIX} (Kỳ)' tương ứng.",
                 bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED,
                 justify="left", anchor="w", wraplength=660).pack(fill="x", pady=(0, 8))

        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(12, 0), side="bottom")

        card = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = ("chon", "ky", "so_tab", "sheet")
        self._tree = ttk.Treeview(card, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("chon",   text="Chọn",       anchor="center")
        self._tree.heading("ky",     text="Kỳ",         anchor="w")
        self._tree.heading("so_tab", text="Số TKQC",    anchor="center")
        self._tree.heading("sheet",  text="Sheet Đích", anchor="w")
        self._tree.column("chon",   width=56,  stretch=False, anchor="center", minwidth=50)
        self._tree.column("ky",     width=170, stretch=False, minwidth=120)
        self._tree.column("so_tab", width=90,  stretch=False, anchor="center", minwidth=70)
        self._tree.column("sheet",  width=260, stretch=True,  minwidth=160)

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

        self._run_btn = ttk.Button(bot, text="Gộp", style="Accent.TButton",
                                   command=self._run, state="disabled")
        self._run_btn.pack(side="right")
        ttk.Button(bot, text="Huỷ", command=self.destroy).pack(side="right", padx=(0, 8))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=110)
        self._progress.pack(side="right", padx=(0, 10))

    # ── Kết nối + load tab ────────────────────────────────────────────────────

    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss   = connect_spreadsheet()
            tabs = list_campaign_tabs(ss)
            self._spreadsheet = ss
            self.after(0, lambda: self._load_items(
                tabs, f"Kết nối OK · {ss.title} · {len(tabs)} tab"))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi: {e}", error=True))

    def _load_items(self, tabs: list[dict], status_text: str):
        self._set_status(status_text)
        self._tree.delete(*self._tree.get_children())
        self._items = []
        for i, grp in enumerate(group_tabs_by_preset(tabs)):
            tags = ("odd", "off") if i % 2 != 0 else ("off",)
            iid = self._tree.insert("", "end", values=(
                "✗", grp["preset_label"], len(grp["titles"]), grp["output_title"],
            ), tags=tags)
            self._items.append({**grp, "iid": iid, "selected": False})
        self._refresh_count()

    def _update_item_ui(self, item: dict):
        idx = self._items.index(item)
        base_tag = "on" if item["selected"] else "off"
        tags = ("odd", base_tag) if idx % 2 != 0 else (base_tag,)
        self._tree.item(item["iid"], values=(
            "✓" if item["selected"] else "✗",
            item["preset_label"], len(item["titles"]), item["output_title"],
        ), tags=tags)

    def _toggle(self, iid: str):
        item = next((i for i in self._items if i["iid"] == iid), None)
        if item is None:
            return
        item["selected"] = not item["selected"]
        self._update_item_ui(item)
        self._refresh_count()
        self._run_btn.configure(
            state="normal" if any(i["selected"] for i in self._items) else "disabled")

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
            text=f"{selected}/{total} kỳ được chọn" if total
            else "Không có tab campaign nào — hãy chạy get_campaigns trước")

    # ── Gộp ───────────────────────────────────────────────────────────────────

    def _run(self):
        groups = [i for i in self._items if i["selected"]]
        if not groups:
            messagebox.showwarning("Chưa chọn", "Chưa bật kỳ nào.")
            return
        msg = (f"Sẽ gộp {len(groups)} kỳ vào các sheet tổng riêng:\n\n"
               + "\n".join(f"  • {g['preset_label']}: {len(g['titles'])} tab "
                           f"→ '{g['output_title']}'" for g in groups))
        if not messagebox.askyesno("Xác nhận", msg):
            return
        jobs = [{"output_title": g["output_title"], "preset_label": g["preset_label"],
                 "titles": list(g["titles"])} for g in groups]
        self._run_btn.configure(state="disabled")
        self._progress.start(12)
        self._set_status(f"Đang gộp {len(jobs)} kỳ...")
        threading.Thread(target=self._run_worker, args=(jobs,), daemon=True).start()

    def _run_worker(self, jobs: list[dict]):
        try:
            results = []
            for job in jobs:
                self.after(0, lambda j=job: self._set_status(
                    f"Đang gộp '{j['preset_label']}'..."))
                results.append(build_combined_sheet(
                    self._spreadsheet, job["titles"], output_title=job["output_title"]))
            self.after(0, lambda: self._done(results))
        except Exception as e:
            self.after(0, lambda e=e: self._error(str(e)))

    def _done(self, results: list[dict]):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        total_tabs = sum(r["tabs"] for r in results)
        total_rows = sum(r["rows"] for r in results)
        self._set_status(
            f"✓ Hoàn thành: {len(results)} kỳ · {total_tabs} tab · {total_rows} dòng")
        lines = "\n".join(
            f"  • {r['output_title']}: {r['tabs']} tab, {r['rows']} dòng "
            f"({'tạo mới' if r.get('created') else 'ghi đè'})" for r in results)
        messagebox.showinfo("Hoàn thành",
            f"Đã gộp {len(results)} kỳ:\n\n{lines}")

    def _error(self, msg: str):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        self._set_status(f"✗ Lỗi: {msg}", error=True)
        messagebox.showerror("Lỗi", msg)

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, foreground="#dc3545" if error else self.MUTED)


# ── Entry point ────────────────────────────────────────────────────────────────

def _list_periods_console():
    """In JSON các Kỳ (group) tìm thấy (cho hub.py dựng checklist)."""
    ss = connect_spreadsheet()
    groups = group_tabs_by_preset(list_campaign_tabs(ss))
    print(json.dumps([{
        "preset":       g["preset"],
        "preset_label": g["preset_label"],
        "output_title": g["output_title"],
        "num_tabs":     len(g["titles"]),
    } for g in groups], ensure_ascii=False))


def _run_console(presets: list[str]):
    """Gộp các Kỳ có preset nằm trong `presets`, in tiến trình ra stdout."""
    ss = connect_spreadsheet()
    want = set(presets)
    groups = [g for g in group_tabs_by_preset(list_campaign_tabs(ss)) if g["preset"] in want]
    if not groups:
        print("Không tìm thấy Kỳ nào khớp lựa chọn. Dừng.")
        return
    for g in groups:
        print(f"\nĐang gộp '{g['preset_label']}' ({len(g['titles'])} tab) → '{g['output_title']}'...")
        r = build_combined_sheet(ss, g["titles"], output_title=g["output_title"], log=print)
        print(f"  → {r['tabs']} tab, {r['rows']} dòng "
              f"({'tạo mới' if r.get('created') else 'ghi đè'}).")
    print("\n✓ Hoàn thành!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Tổng Hợp — gộp các tab campaign cùng Kỳ vào 1 sheet tổng.")
    parser.add_argument("--console", action="store_true",
                        help="Gộp thẳng theo --periods, in ra stdout, không mở GUI.")
    parser.add_argument("--list-periods", action="store_true",
                        help="In JSON các Kỳ tìm thấy rồi thoát (dùng bởi hub.py).")
    parser.add_argument("--periods", nargs="*", default=[],
                        help="date_preset các Kỳ cần gộp (mỗi kỳ 1 phần tử).")
    args = parser.parse_args()

    if args.list_periods:
        _list_periods_console()
    elif args.console:
        _run_console(args.periods)
    else:
        if tk is None:
            sys.exit("Cần tkinter để chạy giao diện (có sẵn trong Python chuẩn trên Windows).")
        App().mainloop()
