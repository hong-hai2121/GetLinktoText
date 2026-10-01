"""
fb_billing_import_tk.py — Bản DỰ PHÒNG dùng Tkinter của tool nhập FB Billing.

Giao diện chính là fb_billing_import_web.py (WebView). Chỉ dùng file này khi
máy không chạy được WebView2. Toàn bộ logic nằm ở billing_core.py.

Chạy:  python fb_billing_import_tk.py
"""

import re
import sys
import threading
import webbrowser
from collections import Counter
from pathlib import Path

from gspread.exceptions import APIError, SpreadsheetNotFound

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
except ImportError:
    sys.exit("Cần tkinter (có sẵn trong Python chuẩn trên Windows).")

from billing_core import (
    SA_FILE, SHEETS_NEW_URL, ID_COL, STATUS_ALLOW,
    get_client, sa_email, default_sheet_id_from_config, extract_sheet_id,
    is_quota_error, load_settings, save_settings, default_sheet_title,
    tab_name_from_stem, read_file, filter_by_status, filter_by_month,
    _month_label, analyze_structure, upsert_with_retry,
)


# ── Palette (đồng bộ ui_kit / hub.py) ─────────────────────────────────────────

BG, CARD, BORDER = "#eef2f6", "#f8fafc", "#cbd5e1"
ACCENT, ACCENT_HV, ACCENT_DIS = "#3b82f6", "#2563eb", "#93c5fd"
TEXT, MUTED = "#334155", "#64748b"
GREEN, YELLOW, RED, CODE_BG = "#10b981", "#f59e0b", "#ef4444", "#f1f5f9"


def center_on_screen(win):
    """Mọi cửa sổ / hộp thoại đều mở giữa màn hình."""
    win.update_idletasks()
    w = max(win.winfo_width(),  win.winfo_reqwidth())
    h = max(win.winfo_height(), win.winfo_reqheight())
    x = max(0, (win.winfo_screenwidth()  - w) // 2)
    y = max(0, (win.winfo_screenheight() - h) // 2 - 24)
    win.geometry(f"+{x}+{y}")


def _size_main_window(win):
    try:
        from ui_kit import size_window
        size_window(win, min_w=1000, min_h=580)
    except Exception:
        win.geometry("1180x640")
        win.minsize(1000, 580)
        center_on_screen(win)


def _copy_to_clipboard(win, text: str):
    win.clipboard_clear()
    win.clipboard_append(text)
    win.update()


# ── Hộp thoại chọn Sheet đích ──────────────────────────────────────────────────

class TargetDialog(tk.Toplevel):
    """Hỏi lúc chạy: TẠO Google Sheet mới (mặc định) hay DÙNG Sheet có sẵn.

    result = {"mode": "new", "title": ..., "email": ...}
           | {"mode": "existing", "sheet_id": ...}
           | None (người dùng thoát)
    """

    def __init__(self, master, settings: dict):
        super().__init__(master)
        self.title("Chọn Google Sheet đích")
        self.configure(bg=CARD)
        self.resizable(False, False)
        self.result = None

        self._mode  = tk.StringVar(value="new")          # mặc định: TẠO MỚI
        self._title = tk.StringVar(value=default_sheet_title())
        self._email = tk.StringVar(value=settings.get("share_email", ""))
        self._sheet = tk.StringVar(
            value=settings.get("sheet_id") or default_sheet_id_from_config())

        pad = {"padx": 20}
        tk.Label(self, text="Nhập dữ liệu billing vào đâu?", bg=CARD, fg=TEXT,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(16, 8), **pad)

        # ── Lựa chọn 1: tạo mới ─────────────────────────────────────────
        self._radio("Tạo Google Sheet MỚI  (mặc định)", "new").pack(anchor="w", **pad)
        f1 = tk.Frame(self, bg=CARD)
        f1.pack(fill="x", padx=44, pady=(2, 10))
        self._row(f1, "Tên sheet:", self._title, 0)
        self._row(f1, "Chia sẻ với email:", self._email, 1)
        tk.Label(f1, bg=CARD, fg=MUTED, font=("Segoe UI", 8), justify="left",
                 text="Email Google của bạn — để mở được sheet do service account tạo. "
                      "Bỏ trống thì chỉ tool này đọc/ghi được."
                 ).grid(row=2, column=1, sticky="w", pady=(0, 2))

        # ── Lựa chọn 2: sheet có sẵn ────────────────────────────────────
        self._radio("Dùng Google Sheet CÓ SẴN", "existing").pack(anchor="w", **pad)
        f2 = tk.Frame(self, bg=CARD)
        f2.pack(fill="x", padx=44, pady=(2, 10))
        self._row(f2, "Link hoặc ID:", self._sheet, 0)
        tk.Label(f2, bg=CARD, fg=MUTED, font=("Segoe UI", 8), justify="left",
                 text="Service account cần có quyền Editor; đã có quyền thì chỉ cần kết nối.\n"
                      "Giữ Quyền truy cập chung = Bị hạn chế (Restricted)."
                 ).grid(row=1, column=1, sticky="w")

        # ── Service account ─────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(4, 8))
        sa = tk.Frame(self, bg=CARD)
        sa.pack(fill="x", **pad)
        tk.Label(sa, text="Service account:", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(sa, text=sa_email() or "(không đọc được service_account.json)",
                 bg=CARD, fg=TEXT, font=("Consolas", 9)).pack(side="left", padx=6)
        ttk.Button(sa, text="Copy", command=lambda: _copy_to_clipboard(self, sa_email())
                   ).pack(side="left")

        # ── Nút ─────────────────────────────────────────────────────────
        btns = tk.Frame(self, bg=CARD)
        btns.pack(fill="x", padx=20, pady=(14, 16))
        ttk.Button(btns, text="Tiếp tục  ▶", style="Accent.TButton",
                   command=self._ok).pack(side="right")
        ttk.Button(btns, text="Thoát", command=self._cancel).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda *_: self._ok())
        self.bind("<Escape>", lambda *_: self._cancel())
        center_on_screen(self)
        self.grab_set()
        self.focus_force()

    def _radio(self, text, value):
        return tk.Radiobutton(self, text=text, value=value, variable=self._mode,
                              bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 10),
                              activebackground=CARD, selectcolor=CARD,
                              highlightthickness=0, cursor="hand2")

    @staticmethod
    def _row(parent, label, var, r):
        tk.Label(parent, text=label, bg=CARD, fg=TEXT, font=("Segoe UI", 9),
                 width=17, anchor="w").grid(row=r, column=0, sticky="w", pady=3)
        tk.Entry(parent, textvariable=var, width=58, font=("Segoe UI", 10),
                 relief="flat", bg=CODE_BG, fg=TEXT, insertbackground=TEXT,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
                 ).grid(row=r, column=1, sticky="w", pady=3, ipady=3)

    def _ok(self):
        if self._mode.get() == "new":
            title = self._title.get().strip()
            if not title:
                messagebox.showwarning("Thiếu tên", "Nhập tên cho Google Sheet mới.", parent=self)
                return
            email = self._email.get().strip()
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                messagebox.showwarning("Email sai", "Email chia sẻ không hợp lệ.", parent=self)
                return
            self.result = {"mode": "new", "title": title, "email": email}
        else:
            sid = extract_sheet_id(self._sheet.get())
            if not sid:
                messagebox.showwarning("Thiếu link",
                                       "Dán link Google Sheet (…/spreadsheets/d/<ID>/…) hoặc ID.",
                                       parent=self)
                return
            self.result = {"mode": "existing", "sheet_id": sid}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class ManualCreateDialog(tk.Toplevel):
    """Service account không tạo được file → hướng dẫn tạo bằng tài khoản Google của bạn.

    result = sheet_id | None
    """

    def __init__(self, master, error_text: str, suggested_title: str):
        super().__init__(master)
        self.title("Tạo Google Sheet bằng tài khoản của bạn")
        self.configure(bg=CARD)
        self.resizable(False, False)
        self.result = None
        self._link = tk.StringVar()
        email = sa_email()

        tk.Label(self, text="⚠  Service account không tạo được Google Sheet mới",
                 bg=CARD, fg=YELLOW, font=("Segoe UI Semibold", 12)
                 ).pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(self, text=error_text, bg=CARD, fg=MUTED, font=("Consolas", 8),
                 wraplength=640, justify="left").pack(anchor="w", padx=20, pady=(0, 8))
        tk.Label(self, bg=CARD, fg=TEXT, font=("Segoe UI", 10), justify="left",
                 wraplength=640,
                 text=("Google không còn cấp dung lượng Drive cho service account, nên "
                       "hãy tạo sheet bằng tài khoản Google của bạn rồi chia sẻ lại:\n\n"
                       "  1.  Bấm  [Mở sheets.new]  → Google tạo một sheet trống trong Drive của bạn.\n"
                       f"  2.  Đặt tên sheet (gợi ý: {suggested_title}).\n"
                       "  3.  Bấm  Share / Chia sẻ  → dán email service account (nút Copy) "
                       "→ quyền  Editor / Người chỉnh sửa; giữ Quyền truy cập chung = Bị hạn chế.\n"
                       "  4.  Copy link sheet, dán vào ô dưới → bấm  Kết nối.")
                 ).pack(anchor="w", padx=20)

        tools = tk.Frame(self, bg=CARD)
        tools.pack(fill="x", padx=20, pady=(12, 6))
        ttk.Button(tools, text="Mở sheets.new", style="Soft.TButton",
                   command=lambda: webbrowser.open(SHEETS_NEW_URL)).pack(side="left")
        ttk.Button(tools, text="Copy email service account",
                   command=lambda: _copy_to_clipboard(self, email)).pack(side="left", padx=8)
        tk.Label(tools, text=email, bg=CARD, fg=MUTED, font=("Consolas", 9)).pack(side="left")

        row = tk.Frame(self, bg=CARD)
        row.pack(fill="x", padx=20, pady=(6, 4))
        tk.Label(row, text="Link sheet:", bg=CARD, fg=TEXT, font=("Segoe UI", 9),
                 width=11, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self._link, width=70, font=("Segoe UI", 10),
                 relief="flat", bg=CODE_BG, fg=TEXT, insertbackground=TEXT,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
                 ).pack(side="left", ipady=3)

        btns = tk.Frame(self, bg=CARD)
        btns.pack(fill="x", padx=20, pady=(12, 16))
        ttk.Button(btns, text="Kết nối  ▶", style="Accent.TButton",
                   command=self._ok).pack(side="right")
        ttk.Button(btns, text="Quay lại", command=self._cancel).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda *_: self._ok())
        center_on_screen(self)
        self.grab_set()
        self.focus_force()

    def _ok(self):
        sid = extract_sheet_id(self._link.get())
        if not sid:
            messagebox.showwarning("Thiếu link", "Dán link Google Sheet vừa tạo vào ô.", parent=self)
            return
        self.result = sid
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ── Giao diện chính ────────────────────────────────────────────────────────────

class App(tk.Tk):
    _STATUS_LABEL = {
        "loading":   "Đang đọc...",
        "checking":  "Đang so cột...",
        "ready":     "✓ Sẵn sàng",
        "mismatch":  "⚠ Cột khác",
        "new_tab":   "✨ Tab mới",
        "importing": "Đang import...",
        "done":      "✓ Hoàn tất",
        "error":     "✗ Lỗi",
    }

    def __init__(self):
        super().__init__()
        self.title("FB Billing Import v2 → Google Sheet")
        self.configure(bg=BG)
        self.withdraw()                      # ẩn tới khi chọn xong Sheet đích

        self._gc = None
        self._spreadsheet = None
        self._ws_by_title: dict = {}
        self._queue: list = []               # {path, tab, headers, rows, sheet_headers, analysis, status, error, iid}
        self._sheet_hdr_cache: dict = {}
        self._settings = load_settings()

        self._apply_styles()
        self._build_ui()
        self.after(50, self._choose_target)

    # ── Style ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, font=("Segoe UI", 10), foreground=TEXT)
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(15, 8),
                    background=BORDER, foreground=TEXT, bordercolor=BORDER,
                    relief="flat", borderwidth=1)
        s.map("TButton", background=[("active", "#cbd5e1"), ("disabled", BG)],
              foreground=[("disabled", MUTED)])
        s.configure("Soft.TButton", font=("Segoe UI", 9, "bold"), padding=(15, 8),
                    background="#e0f2fe", foreground=ACCENT, bordercolor=BORDER,
                    relief="flat", borderwidth=1)
        s.map("Soft.TButton", background=[("active", "#bae6fd"), ("disabled", BG)],
              foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(24, 10),
                    background=ACCENT, foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton", background=[("active", ACCENT_HV), ("disabled", ACCENT_DIS)],
              foreground=[("disabled", "#ffffff")])
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=29, background=CARD,
                    fieldbackground=CARD, foreground=TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background=BORDER,
                    foreground=MUTED, relief="flat", padding=(8, 7))
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#fff")])
        for o in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            s.configure(o, background=BORDER, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, relief="flat", borderwidth=0)
        s.configure("TProgressbar", background=ACCENT, troughcolor=BORDER,
                    borderwidth=0, thickness=8)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=14)

        hdr = tk.Frame(outer, bg=BG)
        hdr.pack(fill="x", pady=(0, 12))
        tk.Label(hdr, text="FB Billing Import v2", bg=BG, fg=TEXT,
                 font=("Segoe UI Semibold", 16)).pack(side="left")
        tk.Label(hdr, text="  →  Google Sheet  ·  tab đặt theo tên file", bg=BG,
                 fg=MUTED, font=("Segoe UI", 11)).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._status_lbl.pack(side="right")

        # ── Card 1: Sheet đích ─────────────────────────────────────────
        c1 = self._card(outer, "1", "Google Sheet đích")
        c1.pack(fill="x", pady=(0, 10))
        row = tk.Frame(c1.body, bg=CARD)
        row.pack(fill="x")
        self._sheet_title_lbl = tk.Label(row, text="—", bg=CARD, fg=TEXT,
                                         font=("Segoe UI Semibold", 11))
        self._sheet_title_lbl.pack(side="left")
        self._sheet_url_lbl = tk.Label(row, text="", bg=CARD, fg=ACCENT,
                                       font=("Segoe UI", 9, "underline"), cursor="hand2")
        self._sheet_url_lbl.pack(side="left", padx=(12, 0))
        self._sheet_url_lbl.bind("<Button-1>", lambda *_: self._open_sheet())
        ttk.Button(row, text="Đổi Sheet...", command=self._choose_target).pack(side="right")
        ttk.Button(row, text="Copy link", command=self._copy_link).pack(side="right", padx=6)
        ttk.Button(row, text="Mở Sheet", style="Soft.TButton",
                   command=self._open_sheet).pack(side="right")

        # ── Card 2: file ───────────────────────────────────────────────
        c2 = self._card(outer, "2", "File cần import  (tab đích = tên file trước '_fb_billing')")
        c2.pack(fill="both", expand=True)
        btn_row = tk.Frame(c2.body, bg=CARD)
        btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="＋  Thêm file...", style="Soft.TButton",
                   command=self._browse_files).pack(side="left")
        ttk.Button(btn_row, text="Đổi tên tab đích...",
                   command=self._rename_tab).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Xóa đã chọn", command=self._remove_selected).pack(side="left")
        ttk.Button(btn_row, text="Xóa tất cả", command=self._clear_queue).pack(side="left", padx=6)

        wrap = tk.Frame(c2.body, bg=BORDER, highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        cols = ("file", "tab", "rows", "status")
        self._q_tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for c, txt, w, anchor in (("file", "File", 380, "w"), ("tab", "Tab đích", 320, "w"),
                                  ("rows", "Dòng", 60, "center"), ("status", "Trạng thái", 130, "w")):
            self._q_tree.heading(c, text=txt, anchor=anchor)
            self._q_tree.column(c, width=w, minwidth=60, anchor=anchor,
                                stretch=(c in ("file", "tab")))
        qvb = ttk.Scrollbar(wrap, orient="vertical",   command=self._q_tree.yview)
        qhb = ttk.Scrollbar(wrap, orient="horizontal", command=self._q_tree.xview)
        self._q_tree.configure(yscrollcommand=qvb.set, xscrollcommand=qhb.set)
        self._q_tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        qvb.grid(row=0, column=1, sticky="ns")
        qhb.grid(row=1, column=0, sticky="ew")
        self._q_tree.tag_configure("odd", background=BG)
        for tag, color in (("loading", MUTED), ("checking", MUTED), ("ready", GREEN),
                           ("mismatch", YELLOW), ("new_tab", ACCENT), ("error", RED),
                           ("done", GREEN), ("importing", TEXT)):
            self._q_tree.tag_configure(tag, foreground=color)
        self._q_tree.bind("<<TreeviewSelect>>", self._on_queue_select)
        self._q_tree.bind("<Double-1>", lambda *_: self._rename_tab())

        self._info_box = tk.Text(c2.body, height=6, font=("Consolas", 9), state="disabled",
                                 bg=CODE_BG, fg=TEXT, relief="flat", bd=0, padx=10, pady=8,
                                 highlightthickness=1, highlightbackground=BORDER)
        self._info_box.pack(fill="x", pady=(8, 0))
        for tag, color in (("ok", GREEN), ("warn", YELLOW), ("err", RED),
                           ("info", ACCENT), ("dim", MUTED)):
            self._info_box.tag_config(tag, foreground=color)

        # ── Thanh dưới ─────────────────────────────────────────────────
        bot = tk.Frame(outer, bg=BG)
        bot.pack(fill="x", pady=(12, 0))
        self._import_btn = ttk.Button(bot, text="Import tất cả", style="Accent.TButton",
                                      command=self._run_import_all, state="disabled")
        self._import_btn.pack(side="left")
        self._retry_btn = ttk.Button(bot, text="↻ Chạy lại file lỗi",
                                     command=self._run_retry_failed, state="disabled")
        self._retry_btn.pack(side="left", padx=(10, 0))
        self._replace_var = tk.BooleanVar(value=False)
        self._month_var   = tk.BooleanVar(value=True)
        for text, var, px in (("Thay thế dữ liệu cũ trong tab", self._replace_var, 14),
                              ("Chỉ giữ tháng đa số của file", self._month_var, 6)):
            tk.Checkbutton(bot, text=text, variable=var, bg=BG, fg=TEXT, font=("Segoe UI", 9),
                           activebackground=BG, selectcolor=BORDER, relief="flat",
                           highlightthickness=0, cursor="hand2", takefocus=0
                           ).pack(side="left", padx=(px, 0))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=160)
        self._progress.pack(side="left", padx=14)
        self._result_lbl = tk.Label(bot, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._result_lbl.pack(side="left")

    @staticmethod
    def _card(parent, num: str, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(head, text=f" {num} ", bg=ACCENT, fg="#FFFFFF",
                 font=("Segoe UI", 9, "bold"), padx=4, pady=1).pack(side="left")
        tk.Label(head, text=title, bg=CARD, fg=TEXT,
                 font=("Segoe UI Semibold", 11)).pack(side="left", padx=(9, 0))
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x")
        body = tk.Frame(card, bg=CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(10, 12))
        card.body = body
        return card

    # ── Chọn / kết nối Sheet đích ─────────────────────────────────────────────

    def _choose_target(self):
        dlg = TargetDialog(self, self._settings)
        self.wait_window(dlg)
        choice = dlg.result
        if choice is None:
            if self._spreadsheet is None:
                self.destroy()               # thoát ngay từ hộp thoại đầu
            return
        self._set_status("Đang kết nối Google Sheet...")
        threading.Thread(target=self._connect_worker, args=(choice,), daemon=True).start()

    def _connect_worker(self, choice: dict):
        try:
            if self._gc is None:
                self._gc = get_client()
            share_err = ""
            if choice["mode"] == "new":
                ss = self._gc.create(choice["title"])
                if choice.get("email"):
                    try:
                        ss.share(choice["email"], perm_type="user", role="writer", notify=True)
                    except Exception as e:      # tạo được nhưng chia sẻ lỗi → vẫn tiếp tục
                        share_err = str(e)
            else:
                ss = self._gc.open_by_key(choice["sheet_id"])
            wss = ss.worksheets()
            self.after(0, lambda: self._on_connected(ss, wss, choice, share_err))
        except Exception as e:
            self.after(0, lambda e=e: self._on_connect_failed(choice, e))

    def _on_connect_failed(self, choice: dict, exc: Exception):
        self._set_status("")
        if choice["mode"] == "new" and is_quota_error(exc):
            dlg = ManualCreateDialog(self, str(exc)[:300], choice["title"])
            self.wait_window(dlg)
            if dlg.result:
                self._set_status("Đang kết nối Google Sheet...")
                threading.Thread(target=self._connect_worker,
                                 args=({"mode": "existing", "sheet_id": dlg.result},),
                                 daemon=True).start()
                return
            self._choose_target()
            return

        if isinstance(exc, SpreadsheetNotFound):
            msg = ("Không tìm thấy Google Sheet với ID đã nhập.\n"
                   "Kiểm tra lại link, hoặc sheet chưa được chia sẻ cho service account.")
        elif isinstance(exc, APIError) and "403" in str(exc):
            msg = (f"Không có quyền truy cập sheet.\n"
                   f"Kiểm tra quyền Editor của:  {sa_email()}  trên Sheet này.\n"
                   "Nếu chưa có, thêm riêng email này trong Share / Chia sẻ.\n"
                   "Giữ Quyền truy cập chung = Bị hạn chế (Restricted).")
        else:
            msg = str(exc)
        messagebox.showerror("Lỗi kết nối", msg)
        self._choose_target()

    def _on_connected(self, ss, wss: list, choice: dict, share_err: str = ""):
        self._spreadsheet = ss
        self._ws_by_title = {ws.title: ws for ws in wss}
        self._sheet_hdr_cache.clear()
        self._sheet_title_lbl.configure(text=ss.title)
        self._sheet_url_lbl.configure(text=ss.url)
        self._set_status(f"Đã kết nối  ·  {len(wss)} tab")

        self._settings.update({"sheet_id": ss.id,
                               "share_email": choice.get("email", self._settings.get("share_email", ""))})
        save_settings(self._settings)

        if self.state() == "withdrawn":
            self.deiconify()
            _size_main_window(self)

        for item in self._queue:             # đổi sheet → so cột lại
            if item["status"] not in ("importing",):
                item["analysis"] = item["sheet_headers"] = None
                item["status"] = "loading" if not item["headers"] else "checking"
                self._refresh_tree_row(item)
                if item["headers"]:
                    self._ensure_analysis(item)
        self._refresh_import_btn()

        if choice["mode"] == "new":
            _copy_to_clipboard(self, ss.url)
            lines = [f"Đã tạo Google Sheet mới: {ss.title}", "", ss.url,
                     "", "(link đã copy vào clipboard)"]
            if choice.get("email") and not share_err:
                lines.append(f"Đã chia sẻ cho {choice['email']} (Editor).")
            elif share_err:
                lines.append(f"⚠ Chia sẻ cho {choice['email']} thất bại: {share_err}")
            else:
                lines.append("⚠ Chưa chia sẻ cho ai: sheet thuộc service account, "
                             "bạn sẽ không mở được bằng tài khoản Google của mình.")
            messagebox.showinfo("Sheet mới", "\n".join(lines))

    def _open_sheet(self):
        if self._spreadsheet:
            webbrowser.open(self._spreadsheet.url)

    def _copy_link(self):
        if self._spreadsheet:
            _copy_to_clipboard(self, self._spreadsheet.url)
            self._set_status("Đã copy link vào clipboard")

    # ── Chọn file ─────────────────────────────────────────────────────────────

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            initialdir=str(Path.home() / "Downloads"),
            title="Chọn file FB Billing (xlsx / xls / csv)",
            filetypes=[("Excel / CSV", "*.xlsx *.xls *.csv"), ("All files", "*.*")],
        )
        for path_str in paths:
            p = Path(path_str)
            if any(i["path"] == p for i in self._queue):
                continue
            item = {"path": p, "tab": tab_name_from_stem(p.stem),
                    "headers": [], "rows": [], "sheet_headers": None, "analysis": None,
                    "status": "loading", "error": "", "iid": ""}
            item["iid"] = self._q_tree.insert("", "end", values=(p.name, item["tab"], "—", "Đang đọc..."),
                                              tags=("loading",))
            self._queue.append(item)
            threading.Thread(target=self._load_file_worker, args=(item,), daemon=True).start()

    def _load_file_worker(self, item: dict):
        try:
            item["headers"], item["rows"] = read_file(item["path"])
            item["status"] = "checking"
        except Exception as e:
            item["status"], item["error"] = "error", str(e)
        self.after(0, lambda: self._on_file_loaded(item))

    def _on_file_loaded(self, item: dict):
        self._refresh_tree_row(item)
        if item["status"] == "checking":
            self._ensure_analysis(item)
        self._refresh_import_btn()

    def _rename_tab(self):
        sel = self._q_tree.selection()
        if not sel:
            return
        item = self._item_by_iid(sel[0])
        if not item or item["status"] == "importing":
            return
        new = simpledialog.askstring("Đổi tên tab đích", "Tên tab trong Google Sheet:",
                                     initialvalue=item["tab"], parent=self)
        if not new or not new.strip():
            return
        new = re.sub(r"[\[\]\*\?/\\:]", "_", new.strip())[:100]
        for iid in sel:                       # áp cho mọi dòng đang chọn
            it = self._item_by_iid(iid)
            if it and it["status"] != "importing":
                it["tab"] = new
                it["analysis"] = it["sheet_headers"] = None
                self._refresh_tree_row(it)
                if it["headers"]:
                    self._ensure_analysis(it)

    # ── So cột file ↔ tab ─────────────────────────────────────────────────────

    def _ensure_analysis(self, item: dict):
        if not item["headers"] or not self._spreadsheet:
            return
        ws = self._ws_by_title.get(item["tab"])
        if ws is None:                        # tab chưa có → sẽ tạo lúc import
            item["sheet_headers"], item["analysis"] = [], analyze_structure(item["headers"], [])
            item["status"] = "new_tab"
            self._refresh_tree_row(item)
            self._refresh_import_btn()
            self._refresh_selected_info(item)
            return
        if item["tab"] in self._sheet_hdr_cache:
            item["sheet_headers"] = self._sheet_hdr_cache[item["tab"]]
            self._compute_analysis(item)
            return
        item["status"] = "checking"
        self._refresh_tree_row(item)
        threading.Thread(target=self._load_sheet_hdr_worker, args=(item, ws), daemon=True).start()

    def _load_sheet_hdr_worker(self, item: dict, ws):
        try:
            hdr = ws.row_values(1)
            self._sheet_hdr_cache[ws.title] = hdr
            self.after(0, lambda: self._after_sheet_hdr(item, ws, hdr))
        except Exception as e:
            self.after(0, lambda e=e: self._sheet_hdr_error(item, str(e)))

    def _after_sheet_hdr(self, item: dict, ws, hdr: list):
        if item["tab"] != ws.title:           # đã đổi tab trong lúc đọc → bỏ kết quả cũ
            return
        item["sheet_headers"] = hdr
        self._compute_analysis(item)

    def _sheet_hdr_error(self, item: dict, msg: str):
        item["status"], item["error"] = "error", f"Đọc cột sheet lỗi: {msg}"
        self._refresh_tree_row(item)
        self._refresh_import_btn()
        self._refresh_selected_info(item)

    def _compute_analysis(self, item: dict):
        a = analyze_structure(item["headers"], item["sheet_headers"] or [])
        item["analysis"] = a
        item["status"] = "ready" if (a["sheet_empty"] or (not a["new_cols"] and not a["missing"])) \
                         else "mismatch"
        self._refresh_tree_row(item)
        self._refresh_import_btn()
        self._refresh_selected_info(item)

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def _item_by_iid(self, iid: str):
        return next((i for i in self._queue if i["iid"] == iid), None)

    def _refresh_tree_row(self, item: dict):
        rows_text = str(len(item["rows"])) if item["rows"] else "—"
        status    = self._STATUS_LABEL.get(item["status"], item["status"])
        idx       = self._q_tree.index(item["iid"])
        tags      = (item["status"],) if idx % 2 == 0 else ("odd", item["status"])
        self._q_tree.item(item["iid"], values=(item["path"].name, item["tab"], rows_text, status),
                          tags=tags)

    def _refresh_import_btn(self):
        ok = self._spreadsheet is not None and any(
            i["status"] in ("ready", "mismatch", "new_tab") for i in self._queue)
        self._import_btn.configure(state="normal" if ok else "disabled")
        has_failed = any(i["status"] == "error" and i["headers"] for i in self._queue)
        self._retry_btn.configure(state="normal" if has_failed else "disabled")

    def _refresh_selected_info(self, item: dict):
        sel = self._q_tree.selection()
        if sel and sel[0] == item["iid"]:
            self._show_item_info(item)

    def _on_queue_select(self, *_):
        sel = self._q_tree.selection()
        if sel:
            item = self._item_by_iid(sel[0])
            if item:
                self._show_item_info(item)

    def _show_item_info(self, item: dict):
        lines = [("dim", f"File : {item['path'].name}\n")]
        if item["status"] == "new_tab":
            lines.append(("info", f"Tab  : {item['tab']}  ✨ (chưa có — sẽ tạo lúc import)\n"))
        else:
            lines.append(("ok", f"Tab  : {item['tab']}\n"))
        if item["status"] == "error":
            lines.append(("err", f"Lỗi  : {item['error']}\n"))
        elif item["headers"]:
            filtered, skipped = filter_by_status(item["headers"], item["rows"])
            lines.append(("dim", f"Dòng : {len(item['rows'])} tổng  →  import {len(filtered)}"))
            if skipped:
                lines.append(("warn", f"  (bỏ {skipped} dòng không phải '{STATUS_ALLOW}')"))
            lines.append(("dim", "\n"))
            if ID_COL in item["headers"]:
                lines.append(("ok", f"✓  Cột '{ID_COL}' — sẽ dedup theo ID\n"))
            else:
                lines.append(("err", f"✗  Cột '{ID_COL}' KHÔNG CÓ — sẽ append tất cả\n"))
            _, dropped, target, _un = filter_by_month(item["headers"], filtered)
            if target:
                lines.append(("dim", f"Tháng : {_month_label(target)} (đa số)\n"))
            if dropped:
                cnt = Counter(_month_label(k) for _, k in dropped)
                detail = ", ".join(f"{lb} ({c})" for lb, c in cnt.items())
                if self._month_var.get():
                    lines.append(("warn", f"⚠  {len(dropped)} dòng THÁNG KHÁC sẽ bị loại: {detail}\n"))
                else:
                    lines.append(("dim", f"ℹ  {len(dropped)} dòng tháng khác (đang giữ): {detail}\n"))
            a = item["analysis"]
            if item["status"] == "checking":
                lines.append(("dim", "⋯  Đang so cột với sheet...\n"))
            elif a is not None and not a["sheet_empty"]:
                if a["new_cols"]:
                    lines.append(("warn", f"⚠  {len(a['new_cols'])} cột CÓ ở file, KHÔNG ở tab "
                                          f"(sẽ thêm): {', '.join(a['new_cols'])}\n"))
                if a["missing"]:
                    lines.append(("warn", f"⚠  {len(a['missing'])} cột CÓ ở tab, KHÔNG ở file "
                                          f"(để trống): {', '.join(a['missing'])}\n"))
                if not a["new_cols"] and not a["missing"]:
                    lines.append(("ok", "✓  Cột file khớp hoàn toàn với tab\n"))
            elif a is not None:
                lines.append(("info", "ℹ  Tab trống — sẽ tạo cột từ file\n"))
        self._info_box.configure(state="normal")
        self._info_box.delete("1.0", "end")
        for tag, text in lines:
            self._info_box.insert("end", text, tag)
        self._info_box.configure(state="disabled")

    def _remove_selected(self):
        for iid in list(self._q_tree.selection()):
            item = self._item_by_iid(iid)
            if item and item["status"] != "importing":
                self._queue.remove(item)
                self._q_tree.delete(iid)
        self._refresh_import_btn()

    def _clear_queue(self):
        for item in [i for i in self._queue if i["status"] != "importing"]:
            self._queue.remove(item)
            self._q_tree.delete(item["iid"])
        self._refresh_import_btn()

    # ── Import ────────────────────────────────────────────────────────────────

    def _run_import_all(self):
        importable = [i for i in self._queue if i["status"] in ("ready", "mismatch", "new_tab")]
        if not importable:
            return
        mismatched = [i for i in importable if i["status"] == "mismatch"]
        new_tabs   = [i for i in importable if i["status"] == "new_tab"]
        replace    = self._replace_var.get()

        lines = [f"Sheet : {self._spreadsheet.title}",
                 f"Import {len(importable)} file → {len({i['tab'] for i in importable})} tab."]
        if new_tabs:
            lines.append(f"Tạo mới {len(new_tabs)} tab:")
            lines += [f"   • {i['tab']}" for i in new_tabs[:8]]
            if len(new_tabs) > 8:
                lines.append(f"   … và {len(new_tabs) - 8} tab nữa")
        if mismatched:
            lines.append(f"⚠ {len(mismatched)} file có cột KHÁC tab đích (cột mới sẽ được thêm):")
            lines += [f"   • {i['path'].name}" for i in mismatched[:6]]
        if replace:
            lines.append("⚠ Chế độ THAY THẾ: xóa toàn bộ dữ liệu cũ trong tab trước khi import.")
        if not messagebox.askyesno("Xác nhận Import", "\n".join(lines)):
            return
        self._start_import(importable, replace)

    def _run_retry_failed(self):
        failed = [i for i in self._queue if i["status"] == "error" and i["headers"]]
        if not failed:
            return
        lines = [f"Chạy lại {len(failed)} file bị lỗi:"] + [f"  • {i['path'].name}" for i in failed[:15]]
        if not messagebox.askyesno("Chạy lại file lỗi", "\n".join(lines)):
            return
        self._start_import(failed, self._replace_var.get())

    def _start_import(self, items: list, replace: bool):
        self._import_btn.configure(state="disabled")
        self._retry_btn.configure(state="disabled")
        self._progress.start(12)
        self._result_lbl.configure(text="Đang import...")
        threading.Thread(target=self._import_worker,
                         args=(items, replace, self._month_var.get()), daemon=True).start()

    def _get_or_create_ws(self, item: dict):
        ws = self._ws_by_title.get(item["tab"])
        if ws is not None:
            return ws
        ws = self._spreadsheet.add_worksheet(
            title=item["tab"], rows=max(len(item["rows"]) + 1, 100),
            cols=max(len(item["headers"]), 1))
        self._ws_by_title[item["tab"]] = ws
        return ws

    def _import_worker(self, items: list, replace: bool, month_filter: bool):
        total_added = total_updated = errors = 0
        dropped_report: list = []
        for item in items:
            item["status"] = "importing"
            self.after(0, lambda i=item: self._refresh_tree_row(i))
            try:
                ws = self._get_or_create_ws(item)
                filtered, _ = filter_by_status(item["headers"], item["rows"])
                if month_filter:
                    filtered, dropped, target, _un = filter_by_month(item["headers"], filtered)
                    if dropped:
                        dropped_report.append((item["path"].name, target, dropped))
                stats = upsert_with_retry(ws, item["headers"], filtered, replace)
                item["status"], item["error"] = "done", ""
                self._sheet_hdr_cache.pop(ws.title, None)
                total_added   += stats["added"]
                total_updated += stats["updated"]
            except Exception as e:
                item["status"], item["error"] = "error", str(e)
                errors += 1
            self.after(0, lambda i=item: self._refresh_tree_row(i))
        self.after(0, lambda: self._import_done(total_added, total_updated, errors,
                                                len(items), dropped_report))

    def _import_done(self, added, updated, errors, total, dropped_report):
        self._progress.stop()
        self._refresh_import_btn()
        self._set_status(f"Đã kết nối  ·  {len(self._ws_by_title)} tab")
        n_dropped = sum(len(d) for _, _, d in dropped_report)
        text = (f"✓ {total - errors}/{total} file  ✗ {errors} lỗi" if errors
                else f"✓  {total} file  +{added} mới  ↺ {updated} cập nhật")
        if n_dropped:
            text += f"  ·  bỏ {n_dropped} dòng sai tháng"
        self._result_lbl.configure(text=text)
        sel = self._q_tree.selection()
        if sel:
            item = self._item_by_iid(sel[0])
            if item:
                self._show_item_info(item)
        if dropped_report:
            lines = [f"Đã loại {n_dropped} dòng KHÔNG thuộc tháng đa số của file:", ""]
            for fname, target, dropped in dropped_report:
                lines.append(f"📄 {fname}  →  giữ {_month_label(target)}")
                for lb, c in Counter(_month_label(k) for _, k in dropped).items():
                    lines.append(f"     • bỏ {c} dòng {lb}")
                lines.append("")
            messagebox.showwarning("Đã loại dòng sai tháng", "\n".join(lines).strip())

    # ── Tiện ích ──────────────────────────────────────────────────────────────

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(text=text, foreground=RED if error else MUTED)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not SA_FILE.exists():
        sys.exit(f"Thiếu {SA_FILE} — cần file service account để ghi Google Sheet.")
    App().mainloop()
