import os
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from src import config
from src import io
from src.notifications import play_sound
from src.services.get_text import GetTextService, StopRequestedError


class GetTextApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GetTextFromLink - GUI")
        w, h = 1200, 680
        self.root.geometry(f"{w}x{h}")
        self.center_window(w, h)
        self.root.minsize(w, h)

        self.selected_model = tk.StringVar(value=config.MODEL_NAME)

        self.title_mode_var = tk.BooleanVar(value=False)
        self.title_submode_var = tk.StringVar(value="full")
        self.skip_gpt_var = tk.BooleanVar(value=False)
        self.skip_long_video_var = tk.BooleanVar(value=False)
        self.move_processed_links_var = tk.BooleanVar(value=False)
        self.max_chunks_var = tk.IntVar(value=config.DEFAULT_MAX_CHUNKS)
        self.max_links_per_run_var = tk.IntVar(value=0)
        self.is_running = False
        self.worker_thread = None

        self.build_ui()
        self.load_links()
        self.service = GetTextService(logger=self.log)

    def center_window(self, w: int = 1200, h: int = 680):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def build_ui(self):
        for child in self.root.winfo_children():
            child.destroy()

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=0)

        # ── Top panel ────────────────────────────────────────────────────────
        top = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        # ── Config frame (left) ───────────────────────────────────────────
        cfg = ttk.LabelFrame(top, text="Cấu hình", padding=(10, 6))
        cfg.grid(row=0, column=0, sticky="ew")
        cfg.grid_columnconfigure(0, weight=1)
        cfg.grid_columnconfigure(1, weight=1)

        # Static info — 1 dòng compact
        device_label = "GPU (CUDA)" if config.device == "cuda" else "CPU"
        info_text = (
            f"📁 Video: {config.OUTPUT_VIDEO_DIR}   |   "
            f"📄 Word: {config.OUTPUT_WORD_FILE}   |   "
            f"💻 {device_label}"
        )
        ttk.Label(cfg, text=info_text, foreground="gray").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        ttk.Separator(cfg, orient="horizontal").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        # ── Cột trái ─────────────────────────────────────────────────────
        left = ttk.Frame(cfg)
        left.grid(row=2, column=0, sticky="nw", padx=(0, 16))

        # Model
        model_row = ttk.Frame(left)
        model_row.pack(anchor="w", pady=(0, 6))
        ttk.Label(model_row, text="Model Whisper:").pack(side="left", padx=(0, 8))
        ttk.Combobox(
            model_row,
            textvariable=self.selected_model,
            values=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
            state="readonly",
            width=16,
        ).pack(side="left")

        # Số link mỗi lần
        link_row = ttk.Frame(left)
        link_row.pack(anchor="w", pady=(0, 6))
        ttk.Label(link_row, text="Số link xử lý mỗi lần (0 = tất cả):").pack(side="left", padx=(0, 8))
        ttk.Spinbox(link_row, from_=0, to=100000, width=8, textvariable=self.max_links_per_run_var).pack(side="left")

        # Checkboxes nhóm trái
        ttk.Checkbutton(
            left,
            text="Bỏ qua video dài hơn 15 phút",
            variable=self.skip_long_video_var,
        ).pack(anchor="w", pady=(0, 4))

        ttk.Checkbutton(
            left,
            text="Không gửi nội dung lên GPT, chỉ lưu transcript",
            variable=self.skip_gpt_var,
        ).pack(anchor="w", pady=(0, 4))

        ttk.Checkbutton(
            left,
            text="Chuyển link đã xử lý sang processed_links.txt",
            variable=self.move_processed_links_var,
        ).pack(anchor="w", pady=(0, 4))

        # ── Cột phải ─────────────────────────────────────────────────────
        right = ttk.Frame(cfg)
        right.grid(row=2, column=1, sticky="nw")

        # Chế độ chia nhỏ
        title_row = ttk.Frame(right)
        title_row.pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(
            title_row,
            text="Chia nhỏ audio + lấy Tiêu đề/Mô tả/Tag",
            variable=self.title_mode_var,
            command=self.on_title_toggle,
        ).pack(side="left")

        chunk_row = ttk.Frame(right)
        chunk_row.pack(anchor="w", padx=(20, 0), pady=(0, 6))
        ttk.Label(chunk_row, text="Số đoạn đầu nhận diện:").pack(side="left", padx=(0, 6))
        self.max_chunks_spin = ttk.Spinbox(
            chunk_row, from_=1, to=50, width=5, textvariable=self.max_chunks_var, state="disabled"
        )
        self.max_chunks_spin.pack(side="left")

        # Submode — RadioButton (đúng hơn Checkbutton)
        submode_frame = ttk.LabelFrame(right, text="Chế độ con", padding=(8, 4))
        submode_frame.pack(anchor="w", padx=(20, 0), pady=(0, 4))

        self._submode_radios = []
        for label, value in [("Tiêu đề", "title_only"), ("Mô tả", "full"), ("Nội dung", "content_only")]:
            rb = ttk.Radiobutton(
                submode_frame,
                text=label,
                variable=self.title_submode_var,
                value=value,
                state="disabled",
            )
            rb.pack(side="left", padx=(0, 12))
            self._submode_radios.append(rb)

        # File processed links info
        ttk.Label(
            right,
            text=f"📋 Processed: {config.PROCESSED_LINKS_FILE}",
            foreground="gray",
        ).pack(anchor="w", pady=(8, 0))

        # ── Action frame (right) ──────────────────────────────────────────
        action = ttk.LabelFrame(top, text="Thao tác", padding=10)
        action.grid(row=0, column=1, sticky="ne", padx=(10, 0))
        action.grid_columnconfigure(0, weight=1)
        action.grid_columnconfigure(1, weight=1)

        self.start_btn = ttk.Button(action, text="▶ Bắt đầu xử lý", command=self.start_process, width=22)
        self.start_btn.grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="ew")

        self.stop_btn = ttk.Button(action, text="⏹ Dừng", command=self.stop_process, width=22, state="disabled")
        self.stop_btn.grid(row=0, column=1, pady=(0, 8), sticky="ew")

        self.restart_firefox_btn = ttk.Button(
            action, text="♻ Khởi động lại Firefox", command=self.restart_firefox_async, width=22
        )
        self.restart_firefox_btn.grid(row=1, column=0, padx=(0, 8), sticky="ew")

        self.save_btn = ttk.Button(action, text="💾 Lưu danh sách", command=self.save_links, width=22)
        self.save_btn.grid(row=1, column=1, sticky="ew")

        self.reload_btn = ttk.Button(action, text="🔄 Tải lại danh sách", command=self.load_links, width=22)
        self.reload_btn.grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="ew")

        # ── Main notebook ──────────────────────────────────────────────────
        main = ttk.LabelFrame(self.root, text="Danh sách", padding=10)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(8, 4))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.nb = ttk.Notebook(main)
        self.nb.grid(row=0, column=0, sticky="nsew")

        tab_log = ttk.Frame(self.nb)
        tab_links = ttk.Frame(self.nb)
        tab_result = ttk.Frame(self.nb)

        self.nb.add(tab_log, text="  Nhật ký  ")
        self.nb.add(tab_links, text="  Danh sách link  ")
        self.nb.add(tab_result, text="  Nội dung Word  ")

        for tab in (tab_log, tab_links, tab_result):
            tab.grid_rowconfigure(0, weight=1)
            tab.grid_columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(tab_log, wrap=tk.WORD)
        self.links_text = scrolledtext.ScrolledText(tab_links, wrap=tk.WORD)
        self.result_text = scrolledtext.ScrolledText(tab_result, wrap=tk.WORD)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.links_text.grid(row=0, column=0, sticky="nsew")
        self.result_text.grid(row=0, column=0, sticky="nsew")

        self.nb.select(tab_log)
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # ── Status bar ────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Sẵn sàng")
        status_bar = ttk.Frame(self.root, relief="sunken")
        status_bar.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        ttk.Label(status_bar, textvariable=self._status_var, anchor="w", padding=(8, 2)).pack(
            side="left", fill="x", expand=True
        )
        self._status_indicator = ttk.Label(status_bar, text="●", foreground="green", padding=(8, 2))
        self._status_indicator.pack(side="right")

    # ── Tab switching ──────────────────────────────────────────────────────
    def on_tab_changed(self, event=None):
        tab_text = self.nb.tab(self.nb.select(), "text").strip()

        if tab_text == "Danh sách link":
            self.links_text.config(state="normal")
            self.links_text.delete("1.0", "end")
            self.load_links()
            self.links_text.see("1.0")
        elif tab_text == "Nội dung Word":
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

    def load_result_docx(self):
        candidates = [config.OUTPUT_WORD_FILE]
        self.result_text.delete(1.0, tk.END)
        docx_path, lines = io.read_docx_lines_from_candidates(candidates)
        if not docx_path:
            self.log("⚠️ Không tìm thấy file Word kết quả (final_result.docx).")
            self.result_text.insert(1.0, "(Chưa có final_result.docx)")
            return
        try:
            content = "\n".join(lines)
            self.result_text.insert(1.0, content if content else "(File Word rỗng)")
            self.log(f"✅ Đã tải nội dung Word: {docx_path} ({len(lines)} dòng)")
        except Exception as e:
            self.log(f"❌ Lỗi khi đọc Word: {e}")
            self.result_text.insert(1.0, f"(Lỗi đọc Word: {e})")

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
