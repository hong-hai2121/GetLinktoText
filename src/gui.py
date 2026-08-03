import os
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from src import config
from src import io
from src.notifications import play_sound
from src.services.get_text import GetTextService, StopRequestedError


class GetTextApp:
    LANGUAGE_CODES = ("auto", "vi", "en")

    def __init__(self, root):
        self.root = root
        self.root.title("GetTextFromLink — Trích xuất nội dung")
        # Cửa sổ gọn, không ép tỉ lệ 21:9
        w, h = 1200, 720
        self.root.geometry(f"{w}x{h}")
        self.center_window(w, h)
        self.root.minsize(1080, 640)

        self.selected_model = tk.StringVar(value=config.MODEL_NAME)
        self.selected_language = tk.StringVar(
            value=config.LANGUAGE_LABELS.get(config.TRANSCRIBE_LANGUAGE, config.LANGUAGE_LABELS["auto"])
        )

        self.title_mode_var = tk.BooleanVar(value=False)
        self.title_submode_var = tk.StringVar(value="full")
        self.skip_gpt_var = tk.BooleanVar(value=True)
        self.skip_long_video_var = tk.BooleanVar(value=False)
        self.move_processed_links_var = tk.BooleanVar(value=False)
        self.max_chunks_var = tk.IntVar(value=config.DEFAULT_MAX_CHUNKS)
        self.max_links_per_run_var = tk.IntVar(value=0)
        self.is_running = False
        self.worker_thread = None

        # State cho tab "Nội dung Word" (giữ màu khi hiển thị/copy)
        self._result_paragraphs = []
        self._result_color_tags = set()
        self._result_bold_font = None

        self._init_theme()
        self.build_ui()
        self.load_links()
        self.service = GetTextService(logger=self.log)

    def center_window(self, w: int = 1200, h: int = 720):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Theme / Styles ──────────────────────────────────────────────────────
    def _init_theme(self):
        # Bảng màu hiện đại (light)
        self.C = {
            "bg": "#eef1f7",
            "surface": "#ffffff",
            "surface_alt": "#f4f6fb",
            "border": "#d8e0ec",
            "primary": "#4f46e5",
            "primary_dk": "#4338ca",
            "primary_lt": "#e9eafe",
            "success": "#16a34a",
            "success_dk": "#128a3f",
            "danger": "#e11d48",
            "danger_dk": "#be123c",
            "text": "#1e293b",
            "muted": "#6b7280",
            "header": "#4f46e5",
            "header_text": "#ffffff",
        }
        self.F = {
            "title": ("Segoe UI", 16, "bold"),
            "subtitle": ("Segoe UI", 10),
            "h": ("Segoe UI", 11, "bold"),
            "body": ("Segoe UI", 10),
            "small": ("Segoe UI", 9),
            "section": ("Segoe UI", 9, "bold"),
            "btn": ("Segoe UI", 10, "bold"),
            "mono": ("Consolas", 10),
        }
        self.root.configure(bg=self.C["bg"])
        self.setup_styles()

    def setup_styles(self):
        C, F = self.C, self.F
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Frames
        style.configure("App.TFrame", background=C["bg"])
        style.configure("Card.TFrame", background=C["surface"])
        style.configure("Surface.TFrame", background=C["surface"])
        style.configure("Header.TFrame", background=C["header"])
        style.configure("Status.TFrame", background=C["surface"])

        # Labels
        style.configure("TLabel", background=C["surface"], foreground=C["text"], font=F["body"])
        style.configure("Title.TLabel", background=C["header"], foreground=C["header_text"], font=F["title"])
        style.configure("Subtitle.TLabel", background=C["header"], foreground="#dcdefb", font=F["subtitle"])
        style.configure("Heading.TLabel", background=C["surface"], foreground=C["primary_dk"], font=F["h"])
        style.configure("Section.TLabel", background=C["surface"], foreground=C["muted"], font=F["section"])
        style.configure("Muted.TLabel", background=C["surface"], foreground=C["muted"], font=F["small"])
        style.configure("Badge.TLabel", background=C["primary_dk"], foreground="#ffffff", font=F["small"], padding=(10, 4))
        style.configure("Status.TLabel", background=C["surface"], foreground=C["muted"], font=F["small"])

        # Cards (labelframe)
        style.configure(
            "Card.TLabelframe",
            background=C["surface"],
            bordercolor=C["border"],
            relief="solid",
            borderwidth=1,
            padding=14,
        )
        style.configure("Card.TLabelframe.Label", background=C["surface"], foreground=C["primary_dk"], font=F["h"])

        # Buttons
        style.configure(
            "Primary.TButton", background=C["primary"], foreground="#ffffff",
            font=F["btn"], borderwidth=0, padding=(12, 9),
        )
        style.map(
            "Primary.TButton",
            background=[("active", C["primary_dk"]), ("disabled", "#c3c7dc")],
            foreground=[("disabled", "#eef0f7")],
        )

        style.configure(
            "Danger.TButton", background=C["danger"], foreground="#ffffff",
            font=F["btn"], borderwidth=0, padding=(12, 9),
        )
        style.map(
            "Danger.TButton",
            background=[("active", C["danger_dk"]), ("disabled", "#e7b6c1")],
            foreground=[("disabled", "#faeef1")],
        )

        style.configure(
            "Ghost.TButton", background=C["surface_alt"], foreground=C["text"],
            font=F["btn"], borderwidth=1, bordercolor=C["border"], padding=(12, 9),
        )
        style.map(
            "Ghost.TButton",
            background=[("active", C["primary_lt"]), ("disabled", "#f0f2f6")],
            bordercolor=[("active", C["primary"])],
            foreground=[("active", C["primary_dk"]), ("disabled", "#adb3c2")],
        )

        # Checkbutton / Radiobutton trên nền card
        style.configure("Card.TCheckbutton", background=C["surface"], foreground=C["text"], font=F["body"])
        style.map(
            "Card.TCheckbutton",
            background=[("active", C["surface"])],
            foreground=[("active", C["primary_dk"]), ("disabled", "#9aa1b1")],
        )
        style.configure("Card.TRadiobutton", background=C["surface"], foreground=C["text"], font=F["body"])
        style.map(
            "Card.TRadiobutton",
            background=[("active", C["surface"])],
            foreground=[("active", C["primary_dk"]), ("disabled", "#9aa1b1")],
        )

        # Combobox / Spinbox
        style.configure(
            "TCombobox", fieldbackground=C["surface"], background=C["surface"],
            foreground=C["text"], bordercolor=C["border"], arrowcolor=C["primary"], padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", C["surface"])],
            foreground=[("readonly", C["text"])],
            selectbackground=[("readonly", C["surface"])],
            selectforeground=[("readonly", C["text"])],
            bordercolor=[("focus", C["primary"])],
        )
        style.configure(
            "TSpinbox", fieldbackground=C["surface"], foreground=C["text"],
            bordercolor=C["border"], arrowcolor=C["primary"], padding=5,
        )
        style.map("TSpinbox", bordercolor=[("focus", C["primary"])])

        # Separator
        style.configure("TSeparator", background=C["border"])

        # Notebook
        style.configure("Modern.TNotebook", background=C["bg"], borderwidth=0, tabmargins=(2, 4, 2, 0))
        style.configure(
            "Modern.TNotebook.Tab", background=C["surface_alt"], foreground=C["muted"],
            font=F["btn"], padding=(20, 10), borderwidth=0,
        )
        style.map(
            "Modern.TNotebook.Tab",
            background=[("selected", C["surface"]), ("active", C["primary_lt"])],
            foreground=[("selected", C["primary_dk"])],
        )

    def build_ui(self):
        for child in self.root.winfo_children():
            child.destroy()

        C, F = self.C, self.F

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=0)  # header
        self.root.grid_rowconfigure(1, weight=0)  # controls band
        self.root.grid_rowconfigure(2, weight=1)  # notebook
        self.root.grid_rowconfigure(3, weight=0)  # status

        # ── Header ───────────────────────────────────────────────────────────
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(24, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        htext = ttk.Frame(header, style="Header.TFrame")
        htext.grid(row=0, column=0, sticky="w")
        ttk.Label(htext, text="🎬  GetTextFromLink", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            htext,
            text="Trích xuất & chuyển video / link thành văn bản bằng Whisper",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        device_label = "GPU · CUDA" if config.device == "cuda" else "CPU"
        ttk.Label(header, text=f"💻  {device_label}", style="Badge.TLabel").grid(row=0, column=1, sticky="e")

        # ── Controls band (config + actions) ─────────────────────────────────
        band = ttk.Frame(self.root, style="App.TFrame", padding=(16, 14, 16, 6))
        band.grid(row=1, column=0, sticky="ew")
        band.grid_columnconfigure(0, weight=1)
        band.grid_columnconfigure(1, weight=0, minsize=330)

        # ── Config card ───────────────────────────────────────────────────
        cfg = ttk.LabelFrame(band, text="  Cấu hình  ", style="Card.TLabelframe")
        cfg.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        for i in range(3):
            cfg.grid_columnconfigure(i, weight=1, uniform="cfg")

        # Cột 0 — Nhận diện
        c0 = ttk.Frame(cfg, style="Surface.TFrame")
        c0.grid(row=0, column=0, sticky="nw", padx=(0, 18))
        ttk.Label(c0, text="NHẬN DIỆN", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(c0, text="Model Whisper", style="TLabel").pack(anchor="w")
        ttk.Combobox(
            c0,
            textvariable=self.selected_model,
            values=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
            state="readonly",
            width=20,
        ).pack(anchor="w", fill="x", pady=(3, 10))
        ttk.Label(c0, text="Ngôn ngữ video", style="TLabel").pack(anchor="w")
        ttk.Combobox(
            c0,
            textvariable=self.selected_language,
            values=[config.LANGUAGE_LABELS[code] for code in self.LANGUAGE_CODES],
            state="readonly",
            width=20,
        ).pack(anchor="w", fill="x", pady=(3, 2))
        ttk.Label(
            c0,
            text="Giữ nguyên tiếng gốc, không dịch",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))
        ttk.Label(c0, text="Số link mỗi lần (0 = tất cả)", style="TLabel").pack(anchor="w")
        ttk.Spinbox(
            c0, from_=0, to=100000, textvariable=self.max_links_per_run_var, width=20
        ).pack(anchor="w", fill="x", pady=(3, 0))

        # Cột 1 — Tùy chọn
        c1 = ttk.Frame(cfg, style="Surface.TFrame")
        c1.grid(row=0, column=1, sticky="nw", padx=(0, 18))
        ttk.Label(c1, text="TÙY CHỌN", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(
            c1, text="Bỏ qua video dài hơn 15 phút",
            variable=self.skip_long_video_var, style="Card.TCheckbutton",
        ).pack(anchor="w", pady=3)
        ttk.Checkbutton(
            c1, text="Chỉ lưu transcript, không gửi GPT",
            variable=self.skip_gpt_var, style="Card.TCheckbutton",
        ).pack(anchor="w", pady=3)
        ttk.Checkbutton(
            c1, text="Chuyển link đã xử lý → processed_links.txt",
            variable=self.move_processed_links_var, style="Card.TCheckbutton",
        ).pack(anchor="w", pady=3)

        # Cột 2 — Chia nhỏ & tiêu đề
        c2 = ttk.Frame(cfg, style="Surface.TFrame")
        c2.grid(row=0, column=2, sticky="nw")
        ttk.Label(c2, text="CHIA NHỎ & TIÊU ĐỀ", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(
            c2, text="Chia nhỏ audio + lấy Tiêu đề / Mô tả / Tag",
            variable=self.title_mode_var, command=self.on_title_toggle, style="Card.TCheckbutton",
        ).pack(anchor="w")

        chunk_row = ttk.Frame(c2, style="Surface.TFrame")
        chunk_row.pack(anchor="w", padx=(8, 0), pady=(7, 7))
        ttk.Label(chunk_row, text="Số đoạn đầu nhận diện:", style="TLabel").pack(side="left", padx=(0, 8))
        self.max_chunks_spin = ttk.Spinbox(
            chunk_row, from_=1, to=50, width=6, textvariable=self.max_chunks_var, state="disabled"
        )
        self.max_chunks_spin.pack(side="left")

        sub = ttk.Frame(c2, style="Surface.TFrame")
        sub.pack(anchor="w", padx=(8, 0))
        ttk.Label(sub, text="Chế độ con:", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self._submode_radios = []
        for label, value in [("Tiêu đề", "title_only"), ("Mô tả", "full"), ("Nội dung", "content_only")]:
            rb = ttk.Radiobutton(
                sub, text=label, variable=self.title_submode_var, value=value,
                state="disabled", style="Card.TRadiobutton",
            )
            rb.pack(side="left", padx=(0, 10))
            self._submode_radios.append(rb)

        # Đường dẫn (dòng thông tin dưới cùng)
        ttk.Separator(cfg, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        info_text = (
            f"📁 Video: {config.OUTPUT_VIDEO_DIR}      "
            f"📄 Word: {config.OUTPUT_WORD_FILE}      "
            f"📋 Processed: {config.PROCESSED_LINKS_FILE}"
        )
        ttk.Label(cfg, text=info_text, style="Muted.TLabel", wraplength=980, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )

        # ── Action card ───────────────────────────────────────────────────
        action = ttk.LabelFrame(band, text="  Thao tác  ", style="Card.TLabelframe")
        action.grid(row=0, column=1, sticky="nsew")
        action.grid_columnconfigure(0, weight=1, uniform="act")
        action.grid_columnconfigure(1, weight=1, uniform="act")

        self.start_btn = ttk.Button(action, text="▶  Bắt đầu", command=self.start_process, style="Primary.TButton")
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        self.stop_btn = ttk.Button(
            action, text="⏹  Dừng", command=self.stop_process, style="Danger.TButton", state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))

        self.restart_firefox_btn = ttk.Button(
            action, text="♻  Khởi động lại Firefox", command=self.restart_firefox_async, style="Ghost.TButton"
        )
        self.restart_firefox_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.save_btn = ttk.Button(action, text="💾  Lưu danh sách", command=self.save_links, style="Ghost.TButton")
        self.save_btn.grid(row=2, column=0, sticky="ew", padx=(0, 6))
        self.reload_btn = ttk.Button(action, text="🔄  Tải lại", command=self.load_links, style="Ghost.TButton")
        self.reload_btn.grid(row=2, column=1, sticky="ew", padx=(6, 0))

        # ── Main notebook ────────────────────────────────────────────────────
        main = ttk.Frame(self.root, style="App.TFrame", padding=(16, 4, 16, 10))
        main.grid(row=2, column=0, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.nb = ttk.Notebook(main, style="Modern.TNotebook")
        self.nb.grid(row=0, column=0, sticky="nsew")

        tab_log = ttk.Frame(self.nb, style="Card.TFrame", padding=2)
        tab_links = ttk.Frame(self.nb, style="Card.TFrame", padding=2)
        tab_result = ttk.Frame(self.nb, style="Card.TFrame", padding=10)

        self.nb.add(tab_log, text="  📜  Nhật ký  ")
        self.nb.add(tab_links, text="  🔗  Danh sách link  ")
        self.nb.add(tab_result, text="  📄  Nội dung Word  ")

        for tab in (tab_log, tab_links):
            tab.grid_rowconfigure(0, weight=1)
            tab.grid_columnconfigure(0, weight=1)

        # Tab "Nội dung Word": thanh công cụ (row 0) + nội dung (row 1)
        tab_result.grid_rowconfigure(0, weight=0)
        tab_result.grid_rowconfigure(1, weight=1)
        tab_result.grid_columnconfigure(0, weight=1)

        result_toolbar = ttk.Frame(tab_result, style="Card.TFrame")
        result_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.copy_result_btn = ttk.Button(
            result_toolbar, text="📋  Copy (giữ màu)", command=self.copy_result_with_color, style="Ghost.TButton"
        )
        self.copy_result_btn.pack(side="left")
        self.download_docx_btn = ttk.Button(
            result_toolbar, text="⬇  Tải .docx", command=self.download_result_docx, style="Ghost.TButton"
        )
        self.download_docx_btn.pack(side="left", padx=(8, 0))
        self.download_txt_btn = ttk.Button(
            result_toolbar, text="⬇  Tải .txt", command=self.download_result_txt, style="Ghost.TButton"
        )
        self.download_txt_btn.pack(side="left", padx=(8, 0))
        ttk.Label(
            result_toolbar,
            text="Dán vào Word / WordPad hoặc Google Docs để giữ màu & định dạng. "
            "Nút 'Tải .txt' lưu nội dung vào thư mục Downloads.",
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(side="left", padx=(12, 0))

        text_kwargs = dict(
            wrap=tk.WORD,
            bg=C["surface"],
            fg=C["text"],
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=10,
            insertbackground=C["primary"],
            selectbackground=C["primary_lt"],
            selectforeground=C["text"],
        )
        self.log_text = scrolledtext.ScrolledText(tab_log, font=F["mono"], **text_kwargs)
        self.links_text = scrolledtext.ScrolledText(tab_links, font=F["body"], **text_kwargs)
        self.result_text = scrolledtext.ScrolledText(tab_result, font=F["body"], **text_kwargs)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.links_text.grid(row=0, column=0, sticky="nsew")
        self.result_text.grid(row=1, column=0, sticky="nsew")

        self.nb.select(tab_log)
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # ── Status bar ────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Sẵn sàng")
        status_bar = ttk.Frame(self.root, style="Status.TFrame", padding=(16, 7))
        status_bar.grid(row=3, column=0, sticky="ew")
        self._status_indicator = ttk.Label(
            status_bar, text="●", foreground=C["success"], background=C["surface"], font=F["body"]
        )
        self._status_indicator.pack(side="left", padx=(0, 8))
        ttk.Label(status_bar, textvariable=self._status_var, style="Status.TLabel").pack(
            side="left", fill="x", expand=True
        )

    # ── Tab switching ──────────────────────────────────────────────────────
    def on_tab_changed(self, event=None):
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            idx = 0

        if idx == 1:  # Danh sách link
            self.links_text.config(state="normal")
            self.links_text.delete("1.0", "end")
            self.load_links()
            self.links_text.see("1.0")
        elif idx == 2:  # Nội dung Word
            self.result_text.config(state="normal")
            self.result_text.delete("1.0", "end")
            self.load_result_docx()
            self.result_text.see("1.0")
        else:
            self.log_text.see(tk.END)

    # ── File I/O ───────────────────────────────────────────────────────────
    def load_links(self):
        candidates = [config.LINKS_FILE]
        self.links_text.delete(1.0, tk.END)
        path, content, link_count = io.read_links_from_candidates(candidates)
        if not path:
            self.log("⚠️ Không tìm thấy file link (linkgettoText.txt).")
            return
        try:
            self.links_text.insert(1.0, content)
            self.log(f"✅ Đã tải {link_count} link từ {path}")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải link: {e}")

    def save_links(self):
        try:
            content = self.links_text.get(1.0, tk.END).strip()
            link_count = io.write_links(config.LINKS_FILE, content)
            self.log(f"💾 Đã lưu {link_count} link vào {os.path.abspath(config.LINKS_FILE)}")
        except Exception as e:
            self.log(f"❌ Lỗi khi lưu link: {e}")
            messagebox.showerror("Lỗi", f"Không thể lưu file: {e}")

    def _ensure_result_fonts(self):
        if self._result_bold_font is not None:
            return
        import tkinter.font as tkfont

        try:
            base = tkfont.Font(font=self.result_text["font"])
        except Exception:
            base = tkfont.nametofont("TkTextFont")
        self._result_bold_font = tkfont.Font(
            family=base.actual("family"),
            size=base.actual("size"),
            weight="bold",
        )
        self.result_text.tag_configure("rt_bold", font=self._result_bold_font)

    def _result_color_tag(self, rgb):
        tag = "rt_color_%02X%02X%02X" % rgb
        if tag not in self._result_color_tags:
            self.result_text.tag_configure(tag, foreground="#%02X%02X%02X" % rgb)
            self._result_color_tags.add(tag)
        return tag

    def load_result_docx(self):
        from src import rich_docx

        candidates = [config.OUTPUT_WORD_FILE]
        self.result_text.config(state="normal")
        self.result_text.delete(1.0, tk.END)

        docx_path, paragraphs = rich_docx.read_docx_paragraphs_from_candidates(candidates)
        self._result_paragraphs = paragraphs or []

        if not docx_path:
            self.log("⚠️ Không tìm thấy file Word kết quả (final_result.docx).")
            self.result_text.insert(1.0, "(Chưa có final_result.docx)")
            return
        try:
            self._ensure_result_fonts()
            if not paragraphs:
                self.result_text.insert(1.0, "(File Word rỗng)")
            else:
                for para in paragraphs:
                    for run in para:
                        tags = []
                        rgb = run.get("rgb")
                        if rgb:
                            tags.append(self._result_color_tag(rgb))
                        if run.get("bold"):
                            tags.append("rt_bold")
                        self.result_text.insert(tk.END, run.get("text", ""), tuple(tags))
                    self.result_text.insert(tk.END, "\n")
            self.log(f"✅ Đã tải nội dung Word: {docx_path} ({len(paragraphs)} đoạn)")
        except Exception as e:
            self.log(f"❌ Lỗi khi đọc Word: {e}")
            self.result_text.insert(tk.END, f"(Lỗi đọc Word: {e})")

    def copy_result_with_color(self):
        from src import rich_docx

        paragraphs = self._result_paragraphs
        if not paragraphs:
            self.log("⚠️ Chưa có nội dung Word để copy. Hãy mở tab 'Nội dung Word' trước.")
            return

        plain = rich_docx.paragraphs_to_plain(paragraphs)
        try:
            rtf = rich_docx.paragraphs_to_rtf(paragraphs)
            html = rich_docx.paragraphs_to_html(paragraphs)
            rich_docx.copy_rich_to_clipboard(rtf, plain, html)
            self.log("📋 Đã copy nội dung Word (giữ màu) vào clipboard. Dán vào Word hoặc Google Docs để giữ định dạng.")
        except Exception as e:
            # Fallback: copy plain text bằng Tkinter nếu thiếu pywin32 hoặc lỗi clipboard
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(plain)
                self.log(f"⚠️ Không copy được định dạng màu ({e}). Đã copy dạng văn bản thường.")
            except Exception as e2:
                self.log(f"❌ Lỗi khi copy: {e2}")

    def _make_download_path(self, ext):
        """Tạo đường dẫn file tải xuống trong Downloads với timestamp và đuôi ext."""
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        try:
            os.makedirs(downloads_dir, exist_ok=True)
        except Exception:
            downloads_dir = os.path.expanduser("~")

        import datetime

        base = os.path.splitext(os.path.basename(config.OUTPUT_WORD_FILE))[0] or "final_result"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(downloads_dir, f"{base}_{timestamp}.{ext}")

    def download_result_docx(self):
        """Lưu nội dung tab 'Nội dung Word' thành file .docx giữ màu trong thư mục Downloads."""
        from src import rich_docx

        paragraphs = self._result_paragraphs
        if not paragraphs:
            self.log("⚠️ Chưa có nội dung để tải. Hãy mở tab 'Nội dung Word' trước.")
            return

        file_path = self._make_download_path("docx")
        try:
            rich_docx.paragraphs_to_docx(paragraphs, file_path)
            self.log(f"⬇️ Đã tải nội dung (giữ màu) ra file: {file_path}")
            self.update_status("Đã tải file .docx vào Downloads", "green")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải file .docx: {e}")
            messagebox.showerror("Lỗi", f"Không thể lưu file .docx: {e}")

    def download_result_txt(self):
        """Lưu nội dung tab 'Nội dung Word' thành file .txt trong thư mục Downloads."""
        from src import rich_docx

        if self._result_paragraphs:
            content = rich_docx.paragraphs_to_plain(self._result_paragraphs)
        else:
            content = self.result_text.get("1.0", tk.END)

        if not content.strip():
            self.log("⚠️ Chưa có nội dung để tải. Hãy mở tab 'Nội dung Word' trước.")
            return

        file_path = self._make_download_path("txt")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content.rstrip() + "\n")
            self.log(f"⬇️ Đã tải nội dung ra file: {file_path}")
            self.update_status("Đã tải file .txt vào Downloads", "green")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải file .txt: {e}")
            messagebox.showerror("Lỗi", f"Không thể lưu file .txt: {e}")

    # ── Title mode ─────────────────────────────────────────────────────────
    def on_title_toggle(self):
        state = "normal" if self.title_mode_var.get() else "disabled"
        self.max_chunks_spin.configure(state=state)
        for rb in self._submode_radios:
            rb.configure(state=state)
        if not self.title_mode_var.get():
            self.title_submode_var.set("full")

    # ── Firefox ────────────────────────────────────────────────────────────
    def restart_firefox_async(self):
        self.restart_firefox_btn.config(state="disabled")
        threading.Thread(target=self.restart_firefox_thread, daemon=True).start()

    def restart_firefox_thread(self):
        try:
            ok = self.service.restart_firefox()
            self.log("✅ Firefox đã khởi động lại thành công!" if ok else "❌ Lỗi khi khởi động lại Firefox.")
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")
        finally:
            self.root.after(0, lambda: self.restart_firefox_btn.config(state="normal"))

    # ── Logging & status ───────────────────────────────────────────────────
    def log(self, message: str):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)

        self.root.after(0, _append)

    def update_status(self, text: str, color: str = "green"):
        self._status_var.set(text)
        self._status_indicator.configure(foreground=color)

    def set_running_state(self, running: bool):
        self.is_running = running
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        if running:
            self.update_status("Đang xử lý...", "orange")
        else:
            self.update_status("Sẵn sàng", "green")

    # ── Stop / Start ───────────────────────────────────────────────────────
    def stop_process(self):
        if not self.is_running:
            self.log("Không có tiến trình nào đang chạy.")
            return
        self.stop_btn.config(state="disabled")
        self.service.request_stop()
        self.update_status("Đang dừng...", "red")
        self.log("⏹ Đã gửi yêu cầu dừng. Vui lòng chờ tác vụ hiện tại kết thúc.")

    def start_process(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.log("Tiến trình đang chạy. Nếu muốn dừng, hãy nhấn 'Dừng'.")
            return

        self.save_links()
        try:
            self.load_links()
        except Exception:
            pass
        try:
            self.nb.select(0)
        except Exception:
            pass

        self.service.clear_stop_request()
        self.set_running_state(True)
        self.worker_thread = threading.Thread(target=self.run_pipeline_thread, daemon=True)
        self.worker_thread.start()

    # ── Worker thread ──────────────────────────────────────────────────────
    def run_pipeline_thread(self):
        selected = self.selected_model.get()
        label_to_code = {config.LANGUAGE_LABELS[code]: code for code in self.LANGUAGE_CODES}
        language = label_to_code.get(self.selected_language.get(), "auto")
        use_title_mode = self.title_mode_var.get()
        title_submode = self.title_submode_var.get() if use_title_mode else "full"

        try:
            max_chunks = int(self.max_chunks_var.get())
            if max_chunks <= 0:
                max_chunks = config.DEFAULT_MAX_CHUNKS
        except Exception:
            max_chunks = config.DEFAULT_MAX_CHUNKS

        try:
            max_links_per_run = int(self.max_links_per_run_var.get())
            if max_links_per_run < 0:
                max_links_per_run = 0
        except Exception:
            max_links_per_run = 0

        try:
            self.service.initialize_whisper()
            if self.service.is_stop_requested():
                self.log("=== ĐÃ DỪNG THEO YÊU CẦU ===")
                self.root.after(0, lambda: self.set_running_state(False))
                return
        except Exception as e:
            self.log(f"❌ Không import được faster-whisper/torch: {e}")
            messagebox.showerror("Lỗi", f"Không import được faster-whisper/torch: {e}")
            self.root.after(0, lambda: self.set_running_state(False))
            return

        self.service.configure_runtime(
            model_name=selected,
            use_title_mode=use_title_mode,
            title_submode=title_submode,
            max_chunks=max_chunks,
            max_links_per_run=max_links_per_run,
            skip_long_videos=self.skip_long_video_var.get(),
            skip_gpt_processing=self.skip_gpt_var.get(),
            move_processed_links=self.move_processed_links_var.get(),
            language=language,
        )

        try:
            self.service.load_model(selected)
            if self.service.is_stop_requested():
                self.log("=== ĐÃ DỪNG THEO YÊU CẦU ===")
                self.root.after(0, lambda: self.set_running_state(False))
                return
        except Exception as e:
            self.log(f"❌ Lỗi khi tải model: {e}")
            play_sound("error")
            messagebox.showerror("Lỗi", f"Không thể tải model: {e}")
            self.root.after(0, lambda: self.set_running_state(False))
            return

        import builtins

        original_print = builtins.print

        def gui_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            self.log(msg)
            return original_print(*args, **kwargs)

        builtins.print = gui_print
        try:
            self.log("=== BẮT ĐẦU XỬ LÝ ===")
            self.service.process_videos()
            self.log("=== HOÀN TẤT ===")
            play_sound("success")
        except StopRequestedError:
            self.log("=== ĐÃ DỪNG THEO YÊU CẦU ===")
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")
            play_sound("error")
            messagebox.showerror("Lỗi", str(e))
        finally:
            builtins.print = original_print
            self.root.after(0, lambda: self.set_running_state(False))
            try:
                self.root.after(0, lambda: self.nb.select(0))
                self.root.after(0, lambda: self.log_text.see(tk.END))
            except Exception:
                pass
