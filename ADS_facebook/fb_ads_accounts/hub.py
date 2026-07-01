"""
hub.py — Trung tâm điều khiển hợp nhất cho toàn bộ pipeline FB Ads → Google Sheets.

Gộp MỌI chức năng của thư mục này vào 1 giao diện duy nhất:
  • Cập nhật danh sách TKQC            (main.py)
  • Phase 1 — Campaigns + metrics      (get_campaigns.py)
  • Phase 2 — Adset / Ad / Creative    (get_details.py)
  • Import lịch sử thanh toán          (fb_billing_import.py)
  • Tổng Hợp sheet                     (TongHop.py)
  • Check Spend (kiểm tra nhất quán)   (check_spend.py)
  • Check Billing vs Campaigns         (check_billing_vs_campaigns.py)

Các tool cần chọn tương tác (tài khoản / tab / file) sẽ mở cửa sổ chuyên dụng
sẵn có của chúng; các tool còn lại chạy thẳng và in kết quả vào console dùng chung.
Khoảng thời gian (Phase 1 & 2) được ghi vào config.py trước khi mở tool con.

Chạy: python hub.py
"""
import json
import os
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

BASE_DIR = Path(__file__).parent

# ── Khoảng thời gian (preset Facebook) ─────────────────────────────────────────
PRESETS = [
    ("Hôm nay",         "today"),
    ("Hôm qua",         "yesterday"),
    ("7 ngày qua",      "last_7d"),
    ("14 ngày qua",     "last_14d"),
    ("28 ngày qua",     "last_28d"),
    ("30 ngày qua",     "last_30d"),
    ("Tháng này",       "this_month"),
    ("Tháng trước",     "last_month"),
    ("Quý này",         "this_quarter"),
    ("Quý trước",       "last_quarter"),
    ("Toàn thời gian",  "lifetime"),
]
PRESET_LABELS = [p[0] for p in PRESETS]
PRESET_MAP    = {p[0]: p[1] for p in PRESETS}

# ── Palette (Soft Light / Eye Care) ─────────────────────────────────────────
BG       = "#eef2f6"  # Xám xanh nhạt dịu mắt
SIDEBAR  = "#f8fafc"  # Trắng ngà (slate-50) thay vì trắng tinh
SURFACE  = "#f8fafc"
BORDER   = "#cbd5e1"  # Viền mềm hơn (slate-300)
ACCENT   = "#3b82f6"  # blue-500
ACCENT_HV= "#2563eb"  # blue-600
GREEN    = "#10b981"
YELLOW   = "#f59e0b"
RED      = "#ef4444"
TEXT     = "#334155"  # Giảm tương phản gắt của chữ đen (slate-700)
MUTED    = "#64748b"  # slate-500
CODE_BG  = "#f1f5f9"  # Nền code block (slate-100)


def write_config(date_preset: str, time_range: dict | None):
    """Cập nhật DATE_PRESET / TIME_RANGE trong config.py để get_campaigns.py /
    get_details.py đọc. GIỮ NGUYÊN mọi dòng khác (ACCESS_TOKEN, SPREADSHEET_ID, ...)."""
    config_path = BASE_DIR / "config.py"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    # Giữ lại tất cả trừ 2 dòng sẽ được ghi lại
    kept = [ln for ln in lines
            if not ln.lstrip().startswith(("DATE_PRESET", "TIME_RANGE"))]

    if date_preset:
        date_part = [f'DATE_PRESET = "{date_preset}"', "TIME_RANGE: dict = {}"]
    else:
        date_part = ['DATE_PRESET = ""', f"TIME_RANGE: dict = {json.dumps(time_range)}"]

    out = "\n".join(kept + date_part).rstrip("\n") + "\n"
    config_path.write_text(out, encoding="utf-8")


# ── Khai báo các trang (tool) ──────────────────────────────────────────────────
# group → list các tool. mode: "stream" (chạy & in console) | "gui" (mở cửa sổ con)
NAV = [
    ("TỔNG QUAN", [
        ("home", "🏠  Trang chủ", None),
    ]),
    ("TÀI KHOẢN", [
        ("accounts", "📋  Cập nhật TKQC", "main.py"),
    ]),
    ("THU THẬP DỮ LIỆU", [
        ("phase1", "①  Phase 1 — Campaigns", "get_campaigns.py"),
        ("phase2", "②  Phase 2 — Chi tiết", "get_details.py"),
    ]),
    ("THANH TOÁN & TỔNG HỢP", [
        ("billing", "💳  Import Billing", "fb_billing_import.py"),
        ("billing_pdf", "🧾  Import Billing (PDF)", "fb_billing_pdf_import.py"),
        ("invoice_csv", "📄  Import Invoice CSV", "fb_invoice_summary_import.py"),
        ("tonghop", "Σ   Tổng Hợp sheet", "TongHop.py"),
    ]),
    ("KIỂM TRA", [
        ("checkspend", "✓  Check Spend", "check_spend.py"),
        ("checkbill",  "✓  Check Billing vs Camp", "check_billing_vs_campaigns.py"),
    ]),
]

# Mặc định cho 2 tool kiểm tra (khớp giá trị trong script gốc)
DEFAULT_CHECK_SHEET   = "Bs Hội 6"
DEFAULT_DETAIL_SHEET  = "Bs Hội 6 (799251702964605) Chi tiết"

# Mô tả chi tiết từng chức năng — hiển thị ở Trang chủ để tra cứu sau này.
# (key, tiêu đề, file script, mô tả nhiều dòng)
FUNC_INFO = [
    ("accounts", "📋  Cập nhật TKQC", "main.py",
     "Gọi Facebook Graph API lấy TOÀN BỘ tài khoản quảng cáo của token hiện tại, "
     "ghi vào sheet \"TKQC API\" (ID, tên, business, trạng thái, tiền tệ, múi giờ, "
     "đã chi, số dư, phương thức thanh toán). Giữ nguyên cột \"Chọn Lấy Camp\" do "
     "bạn tự đánh dấu. Tích \"Cuối tháng\" để tạo thêm 1 sheet snapshot (HH:MM TM)."),
    ("phase1", "①  Phase 1 — Campaigns", "get_campaigns.py",
     "Với mỗi tài khoản có \"Chọn Lấy Camp\" = TRUE: lấy danh sách campaign + 18 metrics "
     "tháng (Spend, CTR, CPC, CPM, Reach, Inbox, Lead, Đơn, Doanh Thu, ROAS, Kết Quả, "
     "Chi Phí/Kết Quả...). Ghi mỗi campaign thành 1 dòng vào tab riêng của tài khoản. "
     "Áp dụng khoảng thời gian đã chọn ở thanh trên. Giữ nguyên cột \"Chọn Lấy Chi Tiết\"."),
    ("phase2", "②  Phase 2 — Chi tiết", "get_details.py",
     "Với mỗi campaign có \"Chọn Lấy Chi Tiết\" = TRUE: lấy Adset / Ad kèm Creative + "
     "insights cấp ad. Chèn các dòng Adset/Ad ngay DƯỚI dòng Campaign (KHÔNG xoá dữ liệu "
     "Campaign hay cột bạn tự thêm). Metrics Adset = tổng hợp từ Ad con. Ghi thêm tab "
     "\"{TK} - Creative\" (12 cột). Có checkpoint để chạy tiếp khi gặp rate limit."),
    ("billing", "💳  Import Billing", "fb_billing_import.py",
     "Nhập lịch sử thanh toán từ file CSV/XLS (xuất từ extension FB Billing Scraper) vào "
     "một tab bất kỳ. Upsert theo \"ID giao dịch\": trùng → cập nhật, mới → thêm dòng. "
     "Chỉ giữ dòng \"Đã thanh toán\". Cột mới trong CSV tự được thêm; cột ID giữ định dạng "
     "TEXT để không mất số 0 đầu. Có preview trước khi import."),
    ("billing_pdf", "🧾  Import Billing (PDF)", "fb_billing_pdf_import.py",
     "Chọn HÀNG LOẠT hóa đơn PDF (biên lai Meta) từ máy, tự bóc tách và ghi vào tab "
     "\"... Chi tiết\" với đúng 19 cột như bản CSV/XLS. Mỗi PDF = 1 giao dịch → nhiều dòng "
     "theo từng chiến dịch. Tự dò tab theo \"ID tài khoản\"; chưa có thì tạo tab mới theo "
     "quy tắc \"<Tên> (<ID>) Chi tiết\". Dedup theo \"ID giao dịch\" ở cấp giao dịch "
     "(import lại thay toàn bộ dòng của giao dịch đó). Cần thư viện pdfplumber."),
    ("invoice_csv", "📄  Import Invoice CSV", "fb_invoice_summary_import.py",
     "Chọn HÀNG LOẠT file 'Invoice_Summary.csv' (Báo cáo lập hóa đơn Meta) từ máy, ghi vào "
     "tab TỔNG HỢP của tài khoản với 7 cột (ID giao dịch, Ngày thanh toán, Số tiền, Phương "
     "thức TT, Số tham chiếu thẻ, Trạng thái, ID hóa đơn VAT). Tên tab suy ra bằng cách tra "
     "\"ID tài khoản\" trong file vào sheet \"TKQC API\" để lấy Tên Tài Khoản → \"<Tên> (<ID>)\". "
     "Dedup theo \"ID giao dịch\"; cột thiếu dữ liệu để trống."),
    ("tonghop", "Σ   Tổng Hợp sheet", "TongHop.py",
     "Tạo sheet \"Tổng Hợp T{tháng}\": cột A = các nhãn (Ngân sách được duyệt, Số tiền nợ, "
     "Spend thực tế, Đơn, Doanh Số, Tỷ lệ CP, Dự quỹ - hoàn ứng...), cột B trở đi = từng "
     "tab tài khoản. Tự điền công thức Google Sheets tham chiếu sang các tab tài khoản. "
     "Cửa sổ cho phép bỏ bớt tab trước khi tạo."),
    ("checkspend", "✓  Check Spend", "check_spend.py",
     "Kiểm tra tính nhất quán cột \"Spend Tháng Này\" trong 1 tab tài khoản: "
     "Spend Campaign phải = tổng Spend các Adset, và Spend Adset phải = tổng Spend các Ad. "
     "In ra danh sách các dòng bị lệch (ngoài sai số làm tròn)."),
    ("checkbill", "✓  Check Billing vs Camp", "check_billing_vs_campaigns.py",
     "Đối chiếu tab Chi tiết (billing) với tab tài khoản: (1) tên chiến dịch có trong "
     "billing nhưng THIẾU ở tab tài khoản; (2) tổng \"Số tiền phân bổ\" (billing) so với "
     "\"Spend Tháng Này\" theo từng chiến dịch, chỉ ra phần lệch và chỉ-có-một-bên."),
]


class Hub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FB Ads Suite — Trung Tâm Điều Khiển")
        
        w, h = 1040, 720
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(880, 600)
        self.configure(bg=BG)

        self._running = False
        self._nav_btns: dict[str, tuple] = {}
        self._active = None

        # State khoảng thời gian (dùng chung Phase 1 & 2)
        today = date.today()
        self.mode_var   = tk.StringVar(value="preset")
        self.preset_var = tk.StringVar(value="Tháng này")
        self.since_var  = tk.StringVar(value=today.replace(day=1).strftime("%Y-%m-%d"))
        self.until_var  = tk.StringVar(value=today.strftime("%Y-%m-%d"))

        # State riêng từng trang
        self.cuoi_thang_var = tk.BooleanVar(value=False)
        self.cspend_var     = tk.StringVar(value=DEFAULT_CHECK_SHEET)
        self.cbill_detail   = tk.StringVar(value=DEFAULT_DETAIL_SHEET)
        self.cbill_camp     = tk.StringVar(value=DEFAULT_CHECK_SHEET)

        self._styles()
        self._build()
        self._show("home")

    # ── Styles ────────────────────────────────────────────────────────────────
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Modern.TCombobox",
                    fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
                    selectbackground=ACCENT, selectforeground="white", arrowcolor=MUTED)
        s.map("Modern.TCombobox",
              fieldbackground=[("readonly", SURFACE)],
              selectbackground=[("readonly", ACCENT)])
        s.configure("Modern.TEntry", fieldbackground=SURFACE, foreground=TEXT,
                    insertbackground=TEXT, bordercolor=BORDER)

    # ── Build khung chính ─────────────────────────────────────────────────────
    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Sidebar
        side = tk.Frame(self, bg=SIDEBAR, width=260)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)

        # Viền mờ ngăn cách sidebar và main
        side_border = tk.Frame(side, bg=BORDER, width=1)
        side_border.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        tk.Label(side, text="FB Ads Suite", bg=SIDEBAR, fg=ACCENT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=24, pady=(24, 2))
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
            r.configure(bg="#e0f2fe")  # Nền xanh nhạt dịu hơn
            lbl.configure(bg="#e0f2fe", fg=ACCENT, font=("Segoe UI", 10, "bold"))
            ind.configure(bg=ACCENT)   # Indicator xanh đậm

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
        return b

    def _entry(self, parent, var, width=46):
        return ttk.Entry(parent, textvariable=var, width=width, style="Modern.TEntry")

    def _desc(self, parent, text):
        tk.Label(parent, text=text, bg=SURFACE, fg=TEXT, font=("Segoe UI", 10),
                 justify="left", anchor="w", wraplength=660).pack(
                 anchor="w", padx=20, pady=(16, 12))

    def _date_bar(self, parent):
        """Thanh chọn khoảng thời gian dùng cho Phase 1 & 2."""
        card = self._card(parent)
        tk.Label(card, text="KHOẢNG THỜI GIAN", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(16, 4))

        row = tk.Frame(card, bg=SURFACE)
        row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Radiobutton(row, text="Preset", variable=self.mode_var, value="preset",
                       command=self._toggle_dates, bg=SURFACE, fg=TEXT,
                       selectcolor=BORDER, activebackground=SURFACE,
                       activeforeground=TEXT, font=("Segoe UI", 10),
                       cursor="hand2").pack(side="left")
        self.preset_cb = ttk.Combobox(row, textvariable=self.preset_var,
                                       values=PRESET_LABELS, state="readonly",
                                       width=18, style="Modern.TCombobox")
        self.preset_cb.pack(side="left", padx=(8, 0))

        row2 = tk.Frame(card, bg=SURFACE)
        row2.pack(fill="x", padx=16, pady=(0, 20))
        tk.Radiobutton(row2, text="Tuỳ chỉnh", variable=self.mode_var, value="custom",
                       command=self._toggle_dates, bg=SURFACE, fg=TEXT,
                       selectcolor=BORDER, activebackground=SURFACE,
                       activeforeground=TEXT, font=("Segoe UI", 10),
                       cursor="hand2").pack(side="left")
        tk.Label(row2, text="Từ", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 4))
        self.since_e = self._entry(row2, self.since_var, width=12)
        self.since_e.pack(side="left")
        tk.Label(row2, text="Đến", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self.until_e = self._entry(row2, self.until_var, width=12)
        self.until_e.pack(side="left")
        tk.Label(row2, text="(YYYY-MM-DD)", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))
        self._toggle_dates()

    def _toggle_dates(self):
        is_preset = self.mode_var.get() == "preset"
        self.preset_cb.configure(state="readonly" if is_preset else "disabled")
        st = "disabled" if is_preset else "normal"
        self.since_e.configure(state=st)
        self.until_e.configure(state=st)

    # ── Trang ─────────────────────────────────────────────────────────────────
    def _page_home(self):
        self._set_header("Trang chủ — Danh mục chức năng",
                         "Mô tả từng tab để tra cứu. Bấm vào một thẻ để mở tab tương ứng.")

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
                         wraplength=620)
            d.pack(fill="x", padx=20, pady=(0, 16))

            # Bấm bất kỳ đâu trong thẻ → mở tab
            for w in (card, top, t, s, d):
                w.bind("<Button-1>", lambda e, k=key: self._show(k))
            # Hover sáng viền
            def _enter(e, c=card):
                c.configure(highlightbackground=ACCENT_HV)
            def _leave(e, c=card):
                c.configure(highlightbackground=BORDER)
            for w in (card, top, t, s, d):
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

    def _page_accounts(self):
        self._set_header("Cập nhật danh sách TKQC",
                         "Gọi Facebook Graph API lấy toàn bộ ad account → ghi sheet \"TKQC API\". Giữ nguyên cột \"Chọn Lấy Camp\".")
        card = self._card()
        self._desc(card, "Đồng bộ danh sách tài khoản quảng cáo, số dư, trạng thái và phương thức "
                         "thanh toán. Tích \"Cuối tháng\" để tạo thêm 1 sheet snapshot (HH:MM TM).")
        tk.Checkbutton(card, text="Cuối tháng — tạo sheet snapshot",
                       variable=self.cuoi_thang_var, bg=SURFACE, fg=TEXT,
                       selectcolor=BORDER, activebackground=SURFACE,
                       activeforeground=TEXT, font=("Segoe UI", 10),
                       cursor="hand2").pack(anchor="w", padx=20, pady=(0, 20))
        self._primary_btn(
            self.content, "▶  Cập nhật ngay",
            lambda: self._run_stream(
                [sys.executable, "-u", "-c",
                 f"import main; main.main(cuoi_thang={self.cuoi_thang_var.get()})"],
                "Cập nhật danh sách TKQC")
        ).pack(anchor="w")

    def _page_phase1(self):
        self._set_header("Phase 1 — Campaigns",
                         "Lấy danh sách campaign + metrics tháng cho các TK có \"Chọn Lấy Camp\" = TRUE.")
        self._date_bar(self.content)
        card = self._card()
        self._desc(card, "Mở cửa sổ chọn tài khoản. Khoảng thời gian ở trên sẽ được áp dụng "
                         "(ghi vào config.py trước khi mở). Cột \"Chọn Lấy Chi Tiết\" được giữ nguyên.")
        self._primary_btn(
            self.content, "▶  Mở chọn tài khoản & chạy Phase 1",
            lambda: self._launch_gui("get_campaigns.py", write_cfg=True)
        ).pack(anchor="w")

    def _page_phase2(self):
        self._set_header("Phase 2 — Chi tiết",
                         "Lấy Adset / Ad / Creative cho campaign có \"Chọn Lấy Chi Tiết\" = TRUE. Không xoá dữ liệu Campaign.")
        self._date_bar(self.content)
        card = self._card()
        self._desc(card, "Mở cửa sổ chọn tài khoản. Chèn các dòng Adset/Ad ngay dưới mỗi Campaign "
                         "và ghi tab Creative riêng. Có checkpoint để chạy tiếp khi gặp rate limit.")
        self._primary_btn(
            self.content, "▶  Mở chọn tài khoản & chạy Phase 2",
            lambda: self._launch_gui("get_details.py", write_cfg=True)
        ).pack(anchor="w")

    def _page_billing(self):
        self._set_header("Import lịch sử thanh toán",
                         "Nhập file CSV/XLS từ FB Billing Scraper vào một tab, upsert theo \"ID giao dịch\".")
        card = self._card()
        self._desc(card, "Mở công cụ Import Billing: chọn tab đích → chọn file CSV/XLS → xem preview "
                         "→ Import. Chỉ giữ dòng \"Đã thanh toán\"; cột mới tự thêm; cột ID giữ định dạng TEXT.")
        self._primary_btn(
            self.content, "▶  Mở công cụ Import Billing",
            lambda: self._launch_gui("fb_billing_import.py")
        ).pack(anchor="w")

    def _page_billing_pdf(self):
        self._set_header("Import lịch sử thanh toán (PDF)",
                         "Chọn hàng loạt hóa đơn PDF (biên lai Meta) → ghi vào tab \"... Chi tiết\" giống bản CSV/XLS.")
        card = self._card()
        self._desc(card, "Mở công cụ Import Billing PDF: chọn nhiều file PDF → tự bóc tách theo "
                         "từng chiến dịch → tự dò tab theo ID tài khoản (chưa có thì tạo mới) → Import. "
                         "Dedup theo \"ID giao dịch\" ở cấp giao dịch. Cần thư viện pdfplumber "
                         "(pip install pdfplumber).")
        self._primary_btn(
            self.content, "▶  Mở công cụ Import Billing (PDF)",
            lambda: self._launch_gui("fb_billing_pdf_import.py")
        ).pack(anchor="w")

    def _page_invoice_csv(self):
        self._set_header("Import Báo cáo lập hóa đơn (Invoice CSV)",
                         "Chọn hàng loạt file Invoice_Summary.csv → ghi vào tab tổng hợp \"<Tên> (<ID>)\" (7 cột).")
        card = self._card()
        self._desc(card, "Mở công cụ Import Invoice CSV: chọn nhiều file CSV → tự đọc \"ID tài khoản\" "
                         "→ tra sheet \"TKQC API\" lấy Tên Tài Khoản để suy ra/ tìm tab → Import. "
                         "Mỗi giao dịch 1 dòng, dedup theo \"ID giao dịch\". Nếu ID chưa có trong "
                         "TKQC API, hãy chạy \"Cập nhật TKQC\" trước hoặc gán tab thủ công.")
        self._primary_btn(
            self.content, "▶  Mở công cụ Import Invoice CSV",
            lambda: self._launch_gui("fb_invoice_summary_import.py")
        ).pack(anchor="w")

    def _page_tonghop(self):
        self._set_header("Tổng Hợp sheet",
                         "Tạo bảng tổng hợp ngân sách / doanh số: cột A = nhãn hàng, cột B+ = từng tab tài khoản.")
        card = self._card()
        self._desc(card, "Mở cửa sổ chọn tab: liệt kê tab của các TK \"Chọn Lấy Camp\" = TRUE, cho phép "
                         "bỏ bớt trước khi tạo sheet \"Tổng Hợp T{tháng}\" với các công thức tự động.")
        self._primary_btn(
            self.content, "▶  Mở chọn tab & tạo Tổng Hợp",
            lambda: self._launch_gui("TongHop.py")
        ).pack(anchor="w")

    def _page_checkspend(self):
        self._set_header("Check Spend",
                         "Kiểm tra: Spend Campaign = Σ Spend Adset, và Spend Adset = Σ Spend Ad trong 1 tab.")
        card = self._card()
        self._desc(card, "Đọc tab tài khoản và đối chiếu tính nhất quán của cột \"Spend Tháng Này\" "
                         "theo cấp Campaign → Adset → Ad. Kết quả in ở khung OUTPUT.")
        row = tk.Frame(card, bg=SURFACE)
        row.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(row, text="Tên tab:", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        self._entry(row, self.cspend_var).pack(side="left")
        self._primary_btn(
            self.content, "▶  Kiểm tra Spend", self._run_checkspend
        ).pack(anchor="w")

    def _page_checkbill(self):
        self._set_header("Check Billing vs Campaigns",
                         "Đối chiếu tên chiến dịch + tổng tiền giữa tab Chi tiết (billing) và tab tài khoản.")
        card = self._card()
        self._desc(card, "So sánh: (1) tên chiến dịch có trong tab Chi tiết nhưng thiếu ở tab tài khoản, "
                         "và (2) tổng \"Số tiền phân bổ\" so với \"Spend Tháng Này\" theo từng chiến dịch.")
        grid = tk.Frame(card, bg=SURFACE)
        grid.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(grid, text="Tab Chi tiết:", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9), width=12, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        self._entry(grid, self.cbill_detail, width=44).grid(row=0, column=1, sticky="w")
        tk.Label(grid, text="Tab tài khoản:", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9), width=12, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        self._entry(grid, self.cbill_camp, width=44).grid(row=1, column=1, sticky="w")
        self._primary_btn(
            self.content, "▶  Đối chiếu Billing vs Campaigns", self._run_checkbill
        ).pack(anchor="w")

    # ── Khoảng thời gian → config.py ──────────────────────────────────────────
    def _write_config_from_bar(self) -> bool:
        if self.mode_var.get() == "preset":
            write_config(PRESET_MAP[self.preset_var.get()], None)
            return True
        since = self.since_var.get().strip()
        until = self.until_var.get().strip()
        try:
            d_since = date.fromisoformat(since)
            d_until = date.fromisoformat(until)
        except ValueError:
            messagebox.showerror("Lỗi định dạng ngày",
                                 "Ngày phải theo định dạng YYYY-MM-DD.\nVí dụ: 2026-05-01")
            return False
        if d_since > d_until:
            messagebox.showerror("Lỗi khoảng ngày",
                                 "Ngày bắt đầu phải ≤ ngày kết thúc.")
            return False
        write_config("", {"since": since, "until": until})
        return True

    # ── Chạy tool ─────────────────────────────────────────────────────────────
    def _launch_gui(self, script: str, write_cfg: bool = False):
        """Mở cửa sổ GUI sẵn có của tool con (chọn tài khoản / tab / file)."""
        if write_cfg and not self._write_config_from_bar():
            return
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            subprocess.Popen([sys.executable, str(BASE_DIR / script)],
                             cwd=str(BASE_DIR), env=env)
        except Exception as exc:
            self._log(f"[Lỗi mở {script}] {exc}\n", "err")
            return
        self._log(f"▶  Đã mở cửa sổ: {script}\n", "ok")
        if write_cfg:
            if self.mode_var.get() == "preset":
                self._log(f"   Khoảng thời gian: {self.preset_var.get()} "
                          f"({PRESET_MAP[self.preset_var.get()]})\n", "muted")
            else:
                self._log(f"   Khoảng thời gian: {self.since_var.get()} → "
                          f"{self.until_var.get()}\n", "muted")
        self._log("   Chọn trong cửa sổ vừa mở rồi nhấn Chạy ở đó.\n\n", "muted")

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

    def _run_checkspend(self):
        name = self.cspend_var.get().strip()
        cmd = [sys.executable, "-u", "check_spend.py"]
        if name:                       # rỗng → check_spend.py dùng DEFAULT_SHEET
            cmd.append(name)
        self._run_stream(cmd, f"Check Spend: {name or '(mặc định)'}")

    def _run_checkbill(self):
        detail = self.cbill_detail.get().strip()
        camp = self.cbill_camp.get().strip()
        if not detail or not camp:
            messagebox.showwarning("Thiếu thông tin",
                                   "Cần nhập đủ tên tab Chi tiết và tab tài khoản.")
            return
        self._run_stream(
            [sys.executable, "-u", "check_billing_vs_campaigns.py", detail, camp],
            "Check Billing vs Campaigns")

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
