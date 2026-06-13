"""
hub.py — Trung tâm điều khiển hợp nhất cho pipeline FB Ads tsAnhDuc → Google Sheets.

Gộp 4 bước của thư mục này vào 1 giao diện duy nhất:
  ① Cập nhật danh sách TKQC            (get_accounts.py)
  ② Phase 1 — Campaigns + metrics      (get_campaigns.py)
  ③ Phase 2 — Adset / Ad / Creative    (get_details.py)
  ④ Tổng Hợp các tab theo kỳ           (tong_hop.py)

Mọi lựa chọn (kỳ ở Phase 1, tab ở Phase 2, kỳ gộp ở Tổng Hợp) nằm NGAY trong
hub — không mở cửa sổ con. Khi nhấn Chạy, hub gọi tool con ở chế độ --console
bằng subprocess và stream kết quả vào khung OUTPUT dùng chung.

BẮT BUỘC subprocess (không import chạy thẳng): get_campaigns.py đọc config.py
(DATE_PRESET/TIME_RANGE) lúc import; mỗi lần Popen là một import mới nên kỳ
được truyền qua --preset/tên-tab áp dụng đúng, không bị "đóng băng" trong
tiến trình hub chạy dài. Danh sách tab/kỳ lấy qua --list-* (đọc Google Sheet).

Chạy: python hub.py
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

BASE_DIR = Path(__file__).parent

# Kỳ insights cho Phase 1 — fallback hiển thị ngay; hub tự nạp lại danh sách thật
# qua `get_campaigns.py --list-presets` (nguồn chân lý: get_campaigns.DATE_PRESET_OPTIONS).
PRESET_FALLBACK = [
    ("Hôm nay", "today"), ("Hôm qua", "yesterday"), ("7 ngày qua", "last_7d"),
    ("28 ngày qua", "last_28d"), ("Tháng này", "this_month"), ("Toàn thời gian", "maximum"),
]
DEFAULT_PRESET_LABEL = "Tháng này"

# ── Palette (Soft Light / Eye Care — đồng bộ hub.py của fb_ads_accounts) ─────
BG       = "#eef2f6"  # Xám xanh nhạt dịu mắt
SIDEBAR  = "#f8fafc"  # Trắng ngà (slate-50)
SURFACE  = "#f8fafc"
BORDER   = "#cbd5e1"  # slate-300
ACCENT   = "#3b82f6"  # blue-500
ACCENT_HV= "#2563eb"  # blue-600
GREEN    = "#10b981"
YELLOW   = "#f59e0b"
RED      = "#ef4444"
TEXT     = "#334155"  # slate-700
MUTED    = "#64748b"  # slate-500
CODE_BG  = "#f1f5f9"  # slate-100

# ── Khai báo các trang (tool) ──────────────────────────────────────────────────
NAV = [
    ("TỔNG QUAN", [
        ("home", "🏠  Trang chủ", None),
    ]),
    ("PIPELINE", [
        ("accounts", "①  Cập nhật TKQC", "get_accounts.py"),
        ("phase1",   "②  Phase 1 — Campaigns", "get_campaigns.py"),
        ("phase2",   "③  Phase 2 — Chi tiết", "get_details.py"),
        ("tonghop",  "④  Tổng Hợp theo kỳ", "tong_hop.py"),
    ]),
]

# Mô tả chi tiết từng chức năng — hiển thị ở Trang chủ để tra cứu.
# (key, tiêu đề, file script, mô tả nhiều dòng)
FUNC_INFO = [
    ("accounts", "①  Cập nhật TKQC", "get_accounts.py",
     "Gọi Facebook Graph API lấy TOÀN BỘ tài khoản quảng cáo của token hiện tại, "
     "ghi vào sheet \"TKQC API\" (ID, tên, business, trạng thái, tiền tệ, múi giờ, "
     "đã chi, số dư, phương thức thanh toán). Giữ nguyên cột \"Chọn Lấy Camp\" do "
     "bạn tự đánh dấu. Tích \"Cuối tháng\" để tạo thêm 1 sheet snapshot (HH:MM TM). "
     "Chạy thẳng — kết quả in ở khung OUTPUT bên dưới."),
    ("phase1", "②  Phase 1 — Campaigns", "get_campaigns.py",
     "Với mỗi tài khoản có \"Chọn Lấy Camp\" = TRUE: lấy danh sách campaign + metrics "
     "(Spend, CTR, CPC, CPM, Reach, Inbox, Lead, Đơn, Doanh Thu, ROAS, Kết Quả, "
     "Chi Phí/Kết Quả...). Ghi mỗi campaign 1 dòng vào tab riêng theo kỳ "
     "'Tên TKQC (Kỳ)'. Chọn khoảng thời gian ngay trong hub. "
     "Giữ nguyên cột \"Chọn Lấy Chi Tiết\". Nghỉ 60s giữa mỗi TKQC."),
    ("phase2", "③  Phase 2 — Chi tiết", "get_details.py",
     "Với mỗi campaign có \"Chọn Lấy Chi Tiết\" = TRUE trong các tab bạn chọn: lấy "
     "Adset / Ad kèm Creative + insights cấp ad. Chèn các dòng Adset/Ad ngay DƯỚI "
     "dòng Campaign (KHÔNG xoá dữ liệu Campaign hay cột bạn tự thêm). Ghi thêm tab "
     "Creative riêng. Có checkpoint để chạy tiếp khi gặp rate limit. "
     "Nghỉ 60s giữa mỗi tab, 5s giữa mỗi campaign."),
    ("tonghop", "④  Tổng Hợp theo kỳ", "tong_hop.py",
     "Gộp các tab campaign cùng kỳ (Tháng này, Tháng trước...) vào 1 sheet tổng "
     "\"Tổng Hợp (Kỳ)\". Hub liệt kê các kỳ tìm thấy, cho phép chọn kỳ nào cần "
     "gộp trước khi chạy. Sheet tổng ghi đè nếu đã tồn tại."),
]


class Hub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FB Ads tsAnhDuc — Trung Tâm Điều Khiển")

        w, h = 1000, 700
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(860, 580)
        self.configure(bg=BG)

        self._running = False
        self._nav_btns: dict[str, tuple] = {}
        self._active = None

        # State riêng từng trang
        self.cuoi_thang_var = tk.BooleanVar(value=False)
        self._preset_var = tk.StringVar(value=DEFAULT_PRESET_LABEL)  # Phase 1: nhãn kỳ đang chọn
        self._presets: list[tuple[str, str]] = list(PRESET_FALLBACK)  # [(nhãn, value)]
        self._phase2_items: list[dict] = []   # [{title, acc_name, preset_label, acc_id, selected}]
        self._tonghop_items: list[dict] = []  # [{preset, preset_label, num_tabs, output_title, selected}]

        self._styles()
        self._build()
        self._show("home")
        self._load_presets_async()  # nạp danh sách kỳ thật cho Phase 1 (nền)

    # ── Styles ────────────────────────────────────────────────────────────────
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Modern.TEntry", fieldbackground=SURFACE, foreground=TEXT,
                    insertbackground=TEXT, bordercolor=BORDER)
        # Bảng danh sách (Phase 2 / Tổng Hợp)
        s.configure("Hub.Treeview", font=("Segoe UI", 10), rowheight=30,
                    background="#ffffff", fieldbackground="#ffffff",
                    foreground=TEXT, borderwidth=0)
        s.configure("Hub.Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background=CODE_BG, foreground=MUTED, relief="flat",
                    padding=(8, 8))
        s.map("Hub.Treeview.Heading", background=[("active", BORDER)])
        s.map("Hub.Treeview", background=[("selected", "#dbeafe")],
              foreground=[("selected", TEXT)])

    # ── Build khung chính ─────────────────────────────────────────────────────
    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Sidebar
        side = tk.Frame(self, bg=SIDEBAR, width=250)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)

        # Viền mờ ngăn cách sidebar và main
        side_border = tk.Frame(side, bg=BORDER, width=1)
        side_border.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        tk.Label(side, text="FB Ads tsAnhDuc", bg=SIDEBAR, fg=ACCENT,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=24, pady=(24, 2))
        tk.Label(side, text="Trung tâm điều khiển", bg=SIDEBAR, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=24, pady=(0, 20))

        for group, items in NAV:
            tk.Label(side, text=group, bg=SIDEBAR, fg=MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=24, pady=(16, 6))
            for key, label, _script in items:
                row = tk.Frame(side, bg=SIDEBAR)
                row.pack(fill="x", padx=12, pady=2)

                ind = tk.Frame(row, bg=SIDEBAR, width=4)
                ind.pack(side="left", fill="y", pady=4)

                lbl = tk.Label(row, text=label, bg=SIDEBAR, fg=TEXT,
                               font=("Segoe UI", 10), anchor="w", cursor="hand2",
                               padx=12, pady=8)
                lbl.pack(side="left", fill="x", expand=True)

                def on_click(e, k=key): self._show(k)
                def on_enter(e, r=row): self._hover(r, True)
                def on_leave(e, r=row): self._hover(r, False)

                for w in (row, ind, lbl):
                    w.bind("<Button-1>", on_click)
                    w.bind("<Enter>", on_enter)
                    w.bind("<Leave>", on_leave)

                self._nav_btns[key] = (row, ind, lbl)

        # Main column
        main = tk.Frame(self, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(2, weight=1)   # content
        main.rowconfigure(3, weight=1)   # console
        main.columnconfigure(0, weight=1)

        # Header
        hdr = tk.Frame(main, bg=BG)
        hdr.grid(row=0, column=0, sticky="ew", padx=32, pady=(28, 4))
        self.title_lbl = tk.Label(hdr, text="", bg=BG, fg=TEXT,
                                   font=("Segoe UI", 18, "bold"))
        self.title_lbl.pack(side="left")
        self.status_lbl = tk.Label(hdr, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10))
        self.status_lbl.pack(side="right", pady=(6, 0))
        self.subtitle_lbl = tk.Label(main, text="", bg=BG, fg=MUTED,
                                     font=("Segoe UI", 10), anchor="w", justify="left")
        self.subtitle_lbl.grid(row=1, column=0, sticky="ew", padx=32, pady=(0, 16))

        # Content (rebuilt per page)
        self.content = tk.Frame(main, bg=BG)
        self.content.grid(row=2, column=0, sticky="nsew", padx=32, pady=(0, 8))

        # Console
        cwrap = tk.Frame(main, bg=BG)
        cwrap.grid(row=3, column=0, sticky="nsew", padx=32, pady=(0, 24))
        cwrap.rowconfigure(1, weight=1)
        cwrap.columnconfigure(0, weight=1)
        chdr = tk.Frame(cwrap, bg=BG)
        chdr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(chdr, text="OUTPUT", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Button(chdr, text="Xoá", bg=BG, fg=MUTED, relief="flat", bd=0,
                  font=("Segoe UI", 9, "underline"), cursor="hand2", padx=10,
                  activebackground=BG, activeforeground=TEXT,
                  command=self._clear_console).pack(side="right")
        self.console = scrolledtext.ScrolledText(
            cwrap, bg=CODE_BG, fg=TEXT, insertbackground=TEXT,
            font=("Cascadia Code", 9), relief="flat", bd=0, wrap="word", state="disabled",
            highlightbackground=BORDER, highlightthickness=1, height=10)
        self.console.grid(row=1, column=0, sticky="nsew")
        self.console.tag_config("ok",    foreground=GREEN)
        self.console.tag_config("err",   foreground=RED)
        self.console.tag_config("warn",  foreground=YELLOW)
        self.console.tag_config("muted", foreground=MUTED)

    def _hover(self, row, on):
        key = next(k for k, v in self._nav_btns.items() if v[0] == row)
        if key == self._active:
            return
        bg_color = CODE_BG if on else SIDEBAR
        r, ind, lbl = self._nav_btns[key]
        r.configure(bg=bg_color)
        lbl.configure(bg=bg_color)
        ind.configure(bg=bg_color)

    # ── Điều hướng ────────────────────────────────────────────────────────────
    def _show(self, key: str):
        if self._active and self._active in self._nav_btns:
            r, ind, lbl = self._nav_btns[self._active]
            r.configure(bg=SIDEBAR)
            lbl.configure(bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 10))
            ind.configure(bg=SIDEBAR)

        self._active = key
        if key in self._nav_btns:
            r, ind, lbl = self._nav_btns[key]
            r.configure(bg="#e0f2fe")
            lbl.configure(bg="#e0f2fe", fg=ACCENT, font=("Segoe UI", 10, "bold"))
            ind.configure(bg=ACCENT)

        for w in self.content.winfo_children():
            w.destroy()

        builder = getattr(self, f"_page_{key}", None)
        if builder:
            builder()

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _set_header(self, title: str, subtitle: str = ""):
        self.title_lbl.configure(text=title)
        self.subtitle_lbl.configure(text=subtitle)

    def _card(self, parent=None) -> tk.Frame:
        parent = parent or self.content
        c = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        c.pack(fill="x", pady=(0, 16))
        return c

    def _primary_btn(self, parent, text, command) -> tk.Button:
        b = tk.Button(parent, text=text, bg=ACCENT, fg="white",
                      activebackground=ACCENT_HV, activeforeground="white",
                      font=("Segoe UI", 10, "bold"), relief="flat", bd=0,
                      padx=24, pady=10, cursor="hand2", command=command)
        b.bind("<Enter>", lambda e: b.configure(bg=ACCENT_HV))
        b.bind("<Leave>", lambda e: b.configure(bg=ACCENT))
        return b

    def _secondary_btn(self, parent, text, command) -> tk.Button:
        """Nút phụ có viền rõ ràng — nhìn là biết bấm được."""
        b = tk.Button(parent, text=text, bg="#ffffff", fg=TEXT,
                      activebackground=CODE_BG, activeforeground=ACCENT_HV,
                      font=("Segoe UI", 9, "bold"), relief="solid", bd=1,
                      padx=16, pady=8, cursor="hand2", command=command)
        b.configure(highlightbackground=BORDER, highlightcolor=BORDER)
        b.bind("<Enter>", lambda e: b.configure(bg=CODE_BG, fg=ACCENT_HV))
        b.bind("<Leave>", lambda e: b.configure(bg="#ffffff", fg=TEXT))
        return b

    def _desc(self, parent, text):
        tk.Label(parent, text=text, bg=SURFACE, fg=TEXT, font=("Segoe UI", 10),
                 justify="left", anchor="w", wraplength=640).pack(
                 anchor="w", padx=20, pady=(16, 12))

    # ── Trang ─────────────────────────────────────────────────────────────────
    def _page_home(self):
        self._set_header("Trang chủ — Pipeline 4 bước",
                         "Chạy lần lượt ① → ④. Bấm vào một thẻ để mở bước tương ứng.")

        # Vùng cuộn được (nhiều thẻ mô tả)
        canvas = tk.Canvas(self.content, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(self.content, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width))

        # Cuộn bằng con lăn chuột khi trỏ vào vùng này
        def _wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        for key, title, script, desc in FUNC_INFO:
            card = tk.Frame(inner, bg=SURFACE, highlightbackground=BORDER,
                            highlightthickness=1, cursor="hand2")
            card.pack(fill="x", pady=(0, 12), padx=(0, 4))

            top = tk.Frame(card, bg=SURFACE)
            top.pack(fill="x", padx=20, pady=(16, 4))
            t = tk.Label(top, text=title, bg=SURFACE, fg=ACCENT,
                         font=("Segoe UI", 11, "bold"))
            t.pack(side="left")
            s = tk.Label(top, text=script, bg=SURFACE, fg=MUTED,
                         font=("Consolas", 9))
            s.pack(side="right")
            d = tk.Label(card, text=desc, bg=SURFACE, fg=TEXT,
                         font=("Segoe UI", 9), justify="left", anchor="w",
                         wraplength=600)
            d.pack(fill="x", padx=20, pady=(0, 16))

            # Bấm bất kỳ đâu trong thẻ → mở trang
            for w in (card, top, t, s, d):
                w.bind("<Button-1>", lambda e, k=key: self._show(k))
            def _enter(e, c=card):
                c.configure(highlightbackground=ACCENT_HV)
            def _leave(e, c=card):
                c.configure(highlightbackground=BORDER)
            for w in (card, top, t, s, d):
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

    def _page_accounts(self):
        self._set_header("①  Cập nhật danh sách TKQC",
                         "Lấy toàn bộ ad account → ghi sheet \"TKQC API\". Giữ nguyên cột \"Chọn Lấy Camp\".")
        card = self._card()
        self._desc(card, "Đồng bộ danh sách tài khoản quảng cáo, số dư, trạng thái và phương thức "
                         "thanh toán. Kết quả in ở khung OUTPUT bên dưới. "
                         "Tích \"Cuối tháng\" để tạo thêm 1 sheet snapshot (HH:MM TM).")
        tk.Checkbutton(card, text="Cuối tháng — tạo sheet snapshot",
                       variable=self.cuoi_thang_var, bg=SURFACE, fg=TEXT,
                       selectcolor=BORDER, activebackground=SURFACE,
                       activeforeground=TEXT, font=("Segoe UI", 10),
                       cursor="hand2").pack(anchor="w", padx=20, pady=(0, 20))
        self._primary_btn(
            self.content, "▶  Cập nhật ngay", self._run_accounts
        ).pack(anchor="w")

    def _page_phase1(self):
        self._set_header("②  Phase 1 — Campaigns",
                         "Lấy campaign + metrics cho các TK có \"Chọn Lấy Camp\" = TRUE. Tab riêng theo kỳ.")
        card = self._card()
        self._desc(card, "Chọn khoảng thời gian rồi nhấn \"Chạy Phase 1\". Mỗi campaign 1 dòng vào tab "
                         "'Tên TKQC (Kỳ)'. Cột \"Chọn Lấy Chi Tiết\" được giữ nguyên. "
                         "Nghỉ 3s mỗi lần gọi API, 60s giữa mỗi TKQC; gặp lỗi (vd 429) dừng ngay. "
                         "Tiến trình in ở khung OUTPUT bên dưới.")
        row = tk.Frame(card, bg=SURFACE)
        row.pack(anchor="w", fill="x", padx=20, pady=(0, 20))
        tk.Label(row, text="Khoảng thời gian:", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10)).pack(side="left")
        self._preset_cb = ttk.Combobox(
            row, textvariable=self._preset_var, state="readonly", width=22,
            values=[lbl for lbl, _ in self._presets])
        self._preset_cb.pack(side="left", padx=(10, 0))

        self._primary_btn(
            self.content, "▶  Chạy Phase 1", self._run_phase1
        ).pack(anchor="w")

    def _page_phase2(self):
        self._set_header("③  Phase 2 — Chi tiết",
                         "Lấy Adset / Ad / Creative cho campaign có \"Chọn Lấy Chi Tiết\" = TRUE. Không xoá dữ liệu Campaign.")
        self._desc(self._card(),
                   "Nhấn \"Tải danh sách\" để lấy các tab 'Tên TKQC (Kỳ)' từ Google Sheet, tích chọn "
                   "tab muốn lấy chi tiết rồi nhấn \"Chạy Phase 2\". Chèn Adset/Ad ngay dưới mỗi "
                   "Campaign và ghi tab Creative riêng. Có checkpoint — gặp rate limit chạy lại để "
                   "tiếp tục từ chỗ dừng.")
        self._build_table_page(
            kind="phase2", empty_text="Chưa tải. Nhấn \"Tải danh sách\".",
            load_cmd=["get_details.py", "--list-tabs"],
            run_label="▶  Chạy Phase 2", run_cmd=self._run_phase2)

    def _page_tonghop(self):
        self._set_header("④  Tổng Hợp theo kỳ",
                         "Gộp các tab campaign cùng kỳ vào 1 sheet tổng \"Tổng Hợp (Kỳ)\".")
        self._desc(self._card(),
                   "Nhấn \"Tải danh sách\" để liệt kê các Kỳ tìm thấy (Tháng này, Toàn thời gian...), "
                   "tích chọn kỳ cần gộp rồi nhấn \"Gộp\". Mỗi kỳ gộp TẤT CẢ tab của kỳ đó vào "
                   "1 sheet tổng riêng (tạo mới hoặc ghi đè).")
        self._build_table_page(
            kind="tonghop", empty_text="Chưa tải. Nhấn \"Tải danh sách\".",
            load_cmd=["tong_hop.py", "--list-periods"],
            run_label="▶  Gộp các kỳ đã chọn", run_cmd=self._run_tonghop)

    # ── Bảng danh sách tái dùng (Phase 2 / Tổng Hợp) ────────────────────────────
    # (col_id, tiêu đề, rộng, canh, co giãn, sắp xếp được)
    _TABLE_COLS = {
        "phase2": [
            ("chon",     "Chọn",          56,  "center", False, False),
            ("acc_name", "Tên Tài Khoản", 240, "w",      True,  True),
            ("ky",       "Kỳ",            130, "w",      False, True),
            ("acc_id",   "ID Tài Khoản",  170, "w",      False, True),
        ],
        "tonghop": [
            ("chon",   "Chọn",       56,  "center", False, False),
            ("ky",     "Kỳ",         180, "w",      False, True),
            ("so_tab", "Số TKQC",    90,  "center", False, True),
            ("sheet",  "Sheet Đích", 260, "w",      True,  True),
        ],
    }

    def _build_table_page(self, kind, empty_text, load_cmd, run_label, run_cmd):
        """Dựng khung: thanh nút (Tải / Chọn cả / Bỏ cả / Chạy) + bảng Treeview."""
        bar = tk.Frame(self.content, bg=BG)
        bar.pack(fill="x", pady=(0, 10))
        self._secondary_btn(bar, "⟳  Tải danh sách",
                            lambda: self._load_checklist(kind, load_cmd)).pack(side="left")
        self._secondary_btn(bar, "Chọn tất cả",
                            lambda: self._set_all_checks(kind, True)).pack(side="left", padx=(8, 0))
        self._secondary_btn(bar, "Bỏ tất cả",
                            lambda: self._set_all_checks(kind, False)).pack(side="left", padx=(8, 0))
        self._check_count_lbl = tk.Label(bar, text="", bg=BG, fg=MUTED,
                                         font=("Segoe UI", 9))
        self._check_count_lbl.pack(side="left", padx=14)
        self._primary_btn(bar, run_label, run_cmd).pack(side="right")

        # Bảng
        card = tk.Frame(self.content, bg=SURFACE, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = self._TABLE_COLS[kind]
        tree = ttk.Treeview(card, columns=[c[0] for c in cols], show="headings",
                            selectmode="none", style="Hub.Treeview")
        for col_id, head, width, anchor, stretch, sortable in cols:
            cmd = (lambda k=kind, c=col_id: self._sort_by(k, c)) if sortable else ""
            tree.heading(col_id, text=head, anchor=anchor, command=cmd)
            tree.column(col_id, width=width, anchor=anchor, stretch=stretch,
                        minwidth=50)
        vsb = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb.grid(row=0, column=1, sticky="ns")

        tree.tag_configure("on",    foreground="#198754")   # xanh lá: đang chọn
        tree.tag_configure("off",   foreground="#dc3545")   # đỏ: chưa chọn
        tree.tag_configure("odd",   background="#f1f5f9")    # sọc xen kẽ
        tree.tag_configure("muted", foreground=MUTED)
        tree.bind("<ButtonRelease-1>", self._on_table_click)

        self._tree = tree
        self._tree_kind = kind
        self._check_empty_text = empty_text
        self._sort_col = None
        self._sort_reverse = False
        self._render_table(kind)

    def _row_values(self, kind, it):
        mark = "✓" if it["selected"] else "✗"
        if kind == "phase2":
            return (mark, it["acc_name"], it["preset_label"], it["acc_id"])
        return (mark, it["preset_label"], it["num_tabs"], it["output_title"])

    @staticmethod
    def _row_tags(idx, selected):
        base = "on" if selected else "off"
        return ("odd", base) if idx % 2 else (base,)

    def _render_table(self, kind):
        """Vẽ lại bảng từ state (giữ lựa chọn khi chuyển trang / sắp xếp)."""
        if self._active != kind:
            return
        tree = getattr(self, "_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        tree.delete(*tree.get_children())
        self._row_items = {}
        items = self._phase2_items if kind == "phase2" else self._tonghop_items
        if not items:
            ncol = len(self._TABLE_COLS[kind])
            blank = ("", self._check_empty_text) + ("",) * (ncol - 2)
            tree.insert("", "end", values=blank, tags=("muted",))
            self._refresh_check_count(kind)
            return
        for i, it in enumerate(items):
            it["_idx"] = i
            iid = tree.insert("", "end", values=self._row_values(kind, it),
                              tags=self._row_tags(i, it["selected"]))
            it["iid"] = iid
            self._row_items[iid] = it
        self._refresh_check_count(kind)

    def _on_table_click(self, event):
        tree = self._tree
        iid = tree.identify_row(event.y)
        it = getattr(self, "_row_items", {}).get(iid)
        if it is None:
            return  # hàng trống / placeholder
        kind = self._tree_kind
        it["selected"] = not it["selected"]
        tree.item(iid, values=self._row_values(kind, it),
                  tags=self._row_tags(it["_idx"], it["selected"]))
        self._refresh_check_count(kind)

    def _sort_by(self, kind, col):
        """Sắp xếp theo cột; bấm lại cùng cột để đảo chiều. Kỳ theo thứ tự logic."""
        items = self._phase2_items if kind == "phase2" else self._tonghop_items
        if not items:
            return
        self._sort_reverse = (self._sort_col == col) and not self._sort_reverse
        self._sort_col = col
        order = {lbl: i for i, (lbl, _) in enumerate(self._presets)}

        def key(it):
            if col == "ky":
                return (order.get(it["preset_label"], 99),)
            if col == "so_tab":
                return (it.get("num_tabs", 0),)
            if col == "sheet":
                return (it.get("output_title", "").lower(),)
            if col == "acc_id":
                return (it.get("acc_id", ""),)
            return (it.get("acc_name", "").lower(),)

        items.sort(key=key, reverse=self._sort_reverse)
        self._render_table(kind)
        self._update_sort_arrows(kind)

    def _update_sort_arrows(self, kind):
        tree = getattr(self, "_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for col_id, head, *_ in self._TABLE_COLS[kind]:
            arrow = (" ▼" if self._sort_reverse else " ▲") if col_id == self._sort_col else ""
            tree.heading(col_id, text=head + arrow)

    def _refresh_check_count(self, kind):
        lbl = getattr(self, "_check_count_lbl", None)
        if lbl is None or not lbl.winfo_exists():
            return
        items = self._phase2_items if kind == "phase2" else self._tonghop_items
        sel = sum(1 for it in items if it["selected"])
        unit = "tab" if kind == "phase2" else "kỳ"
        lbl.configure(text=f"{sel}/{len(items)} {unit} đã chọn" if items else "")

    def _set_all_checks(self, kind, value: bool):
        items = self._phase2_items if kind == "phase2" else self._tonghop_items
        for it in items:
            it["selected"] = value
        self._render_table(kind)

    def _load_checklist(self, kind, cmd):
        """Gọi tool con ở chế độ liệt kê (--list-*), nhận JSON, dựng checkbox."""
        if self._running:
            messagebox.showinfo("Đang chạy", "Đợi tác vụ hiện tại xong rồi tải lại.")
            return
        self._set_status("Đang tải danh sách...", YELLOW)
        self._log(f"⟳  Đang tải danh sách từ Google Sheet ({cmd[0]})...\n", "muted")
        full = [sys.executable, str(BASE_DIR / cmd[0]), *cmd[1:]]
        self._run_capture(full, lambda data: self._on_checklist_loaded(kind, data))

    def _on_checklist_loaded(self, kind, data):
        if data is None:
            self._set_status("✗ Tải danh sách lỗi — xem OUTPUT", RED)
            return
        if kind == "phase2":
            self._phase2_items = [{
                "title":        t["title"],
                "acc_name":     t["acc_name"],
                "preset_label": t["preset_label"],
                "acc_id":       t["acc_id"],
                "selected":     False,
            } for t in data]
            n = len(self._phase2_items)
        else:
            self._tonghop_items = [{
                "preset":       g["preset"],
                "preset_label": g["preset_label"],
                "num_tabs":     g["num_tabs"],
                "output_title": g["output_title"],
                "selected":     False,
            } for g in data]
            n = len(self._tonghop_items)
        self._render_table(kind)
        self._set_status(f"✓ Đã tải {n} mục", GREEN)
        self._log(f"✓  Đã tải {n} mục. Tích chọn rồi nhấn Chạy.\n\n", "ok")

    # ── Chạy từng bước ──────────────────────────────────────────────────────────
    def _run_phase1(self):
        label = self._preset_var.get()
        value = next((v for lbl, v in self._presets if lbl == label), label)
        self._run_stream(
            [sys.executable, "-u", "get_campaigns.py", "--console", "--preset", value],
            f"Phase 1 — Campaigns ({label})")

    def _run_phase2(self):
        titles = [it["title"] for it in self._phase2_items if it["selected"]]
        if not titles:
            messagebox.showwarning("Chưa chọn", "Chưa tích tab nào. Tải danh sách rồi chọn tab.")
            return
        self._run_stream(
            [sys.executable, "-u", "get_details.py", "--console", "--tabs", *titles],
            f"Phase 2 — Chi tiết ({len(titles)} tab)")

    def _run_tonghop(self):
        presets = [it["preset"] for it in self._tonghop_items if it["selected"]]
        if not presets:
            messagebox.showwarning("Chưa chọn", "Chưa tích kỳ nào. Tải danh sách rồi chọn kỳ.")
            return
        self._run_stream(
            [sys.executable, "-u", "tong_hop.py", "--console", "--periods", *presets],
            f"Tổng Hợp ({len(presets)} kỳ)")

    def _run_accounts(self):
        cmd = [sys.executable, "-u", "get_accounts.py", "--console"]
        if self.cuoi_thang_var.get():
            cmd.append("--cuoi-thang")
        self._run_stream(cmd, "Cập nhật danh sách TKQC")

    def _run_stream(self, cmd: list[str], header: str):
        """Chạy lệnh, stream stdout vào console (dùng cho tool không cần chọn)."""
        if self._running:
            messagebox.showinfo("Đang chạy",
                                "Đang có một tác vụ chạy. Đợi hoàn thành rồi thử lại.")
            return
        self._running = True
        self._set_status("Đang chạy...", GREEN)
        self._clear_console()
        self._log(f"$ {header}\n\n", "muted")
        threading.Thread(target=self._stream_worker, args=(cmd,), daemon=True).start()

    def _stream_worker(self, cmd: list[str]):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                cwd=str(BASE_DIR), env=env)
            for line in proc.stdout:
                self.after(0, self._log, line, self._auto_tag(line))
            proc.wait()
            self.after(0, self._finish, proc.returncode)
        except Exception as exc:
            self.after(0, self._log, f"[Exception] {exc}\n", "err")
            self.after(0, self._finish, -1)

    def _finish(self, code: int):
        self._running = False
        if code == 0:
            self._log("\n✓  Hoàn thành.\n", "ok")
            self._set_status("✓ Hoàn thành", GREEN)
        else:
            self._log(f"\n✗  Kết thúc với mã lỗi {code}.\n", "err")
            self._set_status("✗ Có lỗi — xem OUTPUT", RED)

    # ── Liệt kê (capture JSON, không stream) ────────────────────────────────────
    def _run_capture(self, cmd: list[str], on_ok):
        """Chạy lệnh liệt kê, gom toàn bộ stdout, parse JSON rồi gọi on_ok(data|None)
        ở main thread. Dùng cho --list-presets / --list-tabs / --list-periods."""
        threading.Thread(target=self._capture_worker, args=(cmd, on_ok), daemon=True).start()

    def _capture_worker(self, cmd: list[str], on_ok):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                cwd=str(BASE_DIR), env=env)
            data = self._parse_json(proc.stdout)
            if data is None:
                msg = (proc.stderr or proc.stdout or "").strip() or "Không nhận được dữ liệu."
                self.after(0, self._log, f"[Lỗi tải] {msg}\n\n", "err")
            self.after(0, on_ok, data)
        except Exception as exc:
            self.after(0, self._log, f"[Exception] {exc}\n\n", "err")
            self.after(0, on_ok, None)

    @staticmethod
    def _parse_json(text: str):
        """Lấy JSON (list/dict) từ stdout — chịu được dòng log phụ phía trước."""
        text = (text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line.startswith(("[", "{")):
                    try:
                        return json.loads(line)
                    except Exception:
                        continue
        return None

    def _load_presets_async(self):
        """Nạp danh sách kỳ thật từ get_campaigns (nguồn chân lý); giữ fallback nếu lỗi."""
        cmd = [sys.executable, str(BASE_DIR / "get_campaigns.py"), "--list-presets"]
        self._run_capture(cmd, self._on_presets_loaded)

    def _on_presets_loaded(self, data):
        if not data:
            return  # giữ PRESET_FALLBACK
        self._presets = [(d["label"], d["value"]) for d in data]
        labels = [l for l, _ in self._presets]
        if self._preset_var.get() not in labels:
            self._preset_var.set(labels[0])
        cb = getattr(self, "_preset_cb", None)
        if cb is not None:
            try:
                cb.configure(values=labels)
            except tk.TclError:
                pass  # combobox đã bị huỷ khi rời trang Phase 1

    @staticmethod
    def _auto_tag(line: str) -> str:
        low = line
        if "✓" in low or "Hoàn thành" in low or "→ Đã" in low:
            return "ok"
        if "✗" in low or "Lỗi" in low or "lỗi" in low or "Traceback" in low or "Error" in low:
            return "err"
        if "⚠" in low or "Rate limit" in low or "Thiếu" in low:
            return "warn"
        return ""

    # ── Console ───────────────────────────────────────────────────────────────
    def _log(self, text: str, tag: str = ""):
        self.console.configure(state="normal")
        self.console.insert("end", text, tag if tag else ())
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _set_status(self, text: str, color: str = MUTED):
        self.status_lbl.configure(text=text, fg=color)


if __name__ == "__main__":
    Hub().mainloop()
