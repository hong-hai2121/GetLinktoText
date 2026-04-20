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
        self.view_var = tk.StringVar(value="log")
        w, h = 1200, 650
        self.root.geometry(f"{w}x{h}")
        self.center_window(w, h)
        self.root.minsize(w, h)

        self.selected_model = tk.StringVar(value=config.MODEL_NAME)

        self.show_log_var = tk.BooleanVar(value=True)
        self.show_links_var = tk.BooleanVar(value=False)
        self.show_result_var = tk.BooleanVar(value=False)

        self.title_mode_var = tk.BooleanVar(value=False)
        self.title_only_var = tk.BooleanVar(value=False)
        self.desc_mode_var = tk.BooleanVar(value=True)
        self.content_mode_var = tk.BooleanVar(value=False)
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

    def center_window(self, w: int = 1200, h: int = 650):
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

        top = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        info_frame = ttk.LabelFrame(top, text="Cấu hình", padding=10)
        info_frame.grid(row=0, column=0, sticky="ew")
        info_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(info_frame, text=f"Thư mục lưu video: {config.OUTPUT_VIDEO_DIR}").grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        ttk.Label(info_frame, text=f"File Word kết quả: {config.OUTPUT_WORD_FILE}").grid(
            row=1, column=0, sticky="w", pady=(0, 2)
        )
        ttk.Label(info_frame, text=f"Thiết bị: {'GPU' if config.device == 'cuda' else 'CPU'}").grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )

        link_limit_row = ttk.Frame(info_frame)
        link_limit_row.grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Label(link_limit_row, text="So link xu ly moi lan (0 = tat ca):").pack(side="left", padx=(0, 8))
        ttk.Spinbox(link_limit_row, from_=0, to=100000, width=8, textvariable=self.max_links_per_run_var).pack(
            side="left"
        )

        ttk.Label(info_frame, text=f"File luu link da xu ly: {config.PROCESSED_LINKS_FILE}").grid(
            row=4, column=0, sticky="w", pady=(0, 6)
        )

        self.move_processed_links_cb = ttk.Checkbutton(
            info_frame,
            text="Chuyen link da xu ly sang processed_links.txt",
            variable=self.move_processed_links_var,
        )
        self.move_processed_links_cb.grid(row=5, column=0, sticky="w", pady=(0, 6))

        self.skip_long_video_cb = ttk.Checkbutton(
            info_frame, text="Bo qua video dai hon 15 phut", variable=self.skip_long_video_var
        )
        self.skip_long_video_cb.grid(row=6, column=0, sticky="w", pady=(0, 6))

        self.skip_gpt_cb = ttk.Checkbutton(
            info_frame,
            text="Khong gui noi dung len GPT, chi luu transcript",
            variable=self.skip_gpt_var,
        )
        self.skip_gpt_cb.grid(row=7, column=0, sticky="w", pady=(0, 6))

        model_row = ttk.Frame(info_frame)
        model_row.grid(row=8, column=0, sticky="w", pady=(0, 6))
        ttk.Label(model_row, text="Model Whisper:").pack(side="left", padx=(0, 8))
        ttk.Combobox(
            model_row,
            textvariable=self.selected_model,
            values=["tiny", "base", "small", "medium", "large-v3"],
            state="readonly",
            width=12,
        ).pack(side="left")

        title_row = ttk.Frame(info_frame)
        title_row.grid(row=9, column=0, sticky="w", pady=(0, 2))
        self.title_checkbox = ttk.Checkbutton(
            title_row,
            text="Chia nhỏ audio + Tiêu đề/Mô tả/Tag",
            variable=self.title_mode_var,
            command=self.on_title_toggle,
        )
        self.title_checkbox.pack(side="left")

        ttk.Label(title_row, text="  Số đoạn đầu nhận diện:").pack(side="left", padx=(10, 6))
        self.max_chunks_spin = ttk.Spinbox(
            title_row, from_=1, to=50, width=5, textvariable=self.max_chunks_var, state="disabled"
        )
        self.max_chunks_spin.pack(side="left")

        submode_row = ttk.Frame(info_frame)
        submode_row.grid(row=10, column=0, sticky="w", padx=(18, 0), pady=(2, 0))
        self.sub_title_cb = ttk.Checkbutton(
            submode_row, text="Tiêu đề", variable=self.title_only_var, command=self.on_submode_title, state="disabled"
        )
        self.sub_title_cb.pack(side="left", padx=(0, 12))
        self.sub_desc_cb = ttk.Checkbutton(
            submode_row, text="Mô tả", variable=self.desc_mode_var, command=self.on_submode_desc, state="disabled"
        )
        self.sub_desc_cb.pack(side="left", padx=(0, 12))
        self.sub_content_cb = ttk.Checkbutton(
            submode_row, text="Nội dung", variable=self.content_mode_var, command=self.on_submode_content, state="disabled"
        )
        self.sub_content_cb.pack(side="left")

        action_frame = ttk.LabelFrame(top, text="Thao tác", padding=10)
        action_frame.grid(row=0, column=1, sticky="ne", padx=(10, 0))
        action_frame.grid_columnconfigure(0, weight=1)
        action_frame.grid_columnconfigure(1, weight=1)

        self.start_btn = ttk.Button(action_frame, text="▶ Bắt đầu xử lý", command=self.start_process, width=22)
        self.start_btn.grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="ew")
        self.stop_btn = ttk.Button(action_frame, text="Dừng", command=self.stop_process, width=22, state="disabled")
        self.stop_btn.grid(row=0, column=1, pady=(0, 8), sticky="ew")

        self.restart_firefox_btn = ttk.Button(
            action_frame, text="♻ Khởi động lại Firefox", command=self.restart_firefox_async, width=22
        )
        self.restart_firefox_btn.grid(row=1, column=0, padx=(0, 8), sticky="ew")

        self.save_btn = ttk.Button(action_frame, text="💾 Lưu danh sách", command=self.save_links, width=22)
        self.save_btn.grid(row=1, column=1, sticky="ew")

        self.reload_btn = ttk.Button(action_frame, text="🔄 Tải lại danh sách", command=self.load_links, width=22)
        self.reload_btn.grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="ew")

        main = ttk.LabelFrame(self.root, text="Danh sách", padding=10)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.nb = ttk.Notebook(main)
        self.nb.grid(row=1, column=0, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        tab_log = ttk.Frame(self.nb)
        tab_links = ttk.Frame(self.nb)
        tab_result = ttk.Frame(self.nb)

        self.nb.add(tab_log, text="Nhật ký")
        self.nb.add(tab_links, text="Danh sách link")
        self.nb.add(tab_result, text="Nội dung Word")

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

    def on_tab_changed(self, event=None):
        tab_text = self.nb.tab(self.nb.select(), "text")

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

    def load_links(self):
        """Tải danh sách link từ file. Ưu tiên path bạn đưa: D:\\Python\\GetLinktoText\\linkgettoText.txt"""
        candidates = [
            r"D:\\Python\\GetLinktoText\\linkgettoText.txt",
            config.LINKS_FILE,
            os.path.abspath(config.LINKS_FILE),
        ]

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
        """
        Load nội dung từ file Word final_result.docx và đổ vào result_text.
        Ưu tiên đúng path bạn yêu cầu: D:\\Python\\GetLinktoText\\final_result.docx
        """
        candidates = [
            r"D:\\Python\\GetLinktoText\\final_result.docx",
            config.OUTPUT_WORD_FILE,
            os.path.abspath(config.OUTPUT_WORD_FILE),
        ]

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

    def on_title_toggle(self):
        if self.title_mode_var.get():
            self.max_chunks_spin.configure(state="normal")
            self.sub_title_cb.configure(state="normal")
            self.sub_desc_cb.configure(state="normal")
            self.sub_content_cb.configure(state="normal")

            if not (self.title_only_var.get() or self.desc_mode_var.get() or self.content_mode_var.get()):
                self.desc_mode_var.set(True)
        else:
            self.max_chunks_spin.configure(state="disabled")
            self.sub_title_cb.configure(state="disabled")
            self.sub_desc_cb.configure(state="disabled")
            self.sub_content_cb.configure(state="disabled")

            self.title_only_var.set(False)
            self.desc_mode_var.set(True)
            self.content_mode_var.set(False)

    def on_submode_title(self):
        self.title_only_var.set(True)
        self.desc_mode_var.set(False)
        self.content_mode_var.set(False)

    def on_submode_desc(self):
        self.desc_mode_var.set(True)
        self.title_only_var.set(False)
        self.content_mode_var.set(False)

    def on_submode_content(self):
        self.content_mode_var.set(True)
        self.title_only_var.set(False)
        self.desc_mode_var.set(False)

    def restart_firefox_async(self):
        self.restart_firefox_btn.config(state="disabled")
        threading.Thread(target=self.restart_firefox_thread, daemon=True).start()

    def restart_firefox_thread(self):
        try:
            ok = self.service.restart_firefox()
            self.log("✅ Firefox đã khởi động lại thành công!" if ok else "❌ Lỗi khi khởi động lại Firefox")
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")
        finally:
            self.root.after(0, lambda: self.restart_firefox_btn.config(state="normal"))

    def log(self, message: str):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)

        self.root.after(0, _append)

    def set_running_state(self, running: bool):
        self.is_running = running
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    def stop_process(self):
        if not self.is_running:
            self.log("Khong co tien trinh nao dang chay.")
            return
        self.stop_btn.config(state="disabled")
        self.service.request_stop()
        self.log("Da gui yeu cau dung. Vui long doi tac vu hien tai ket thuc.")

    def start_process(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.log("Tien trinh dang chay. Neu muon dung, hay bam 'Dung'.")
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

    def run_pipeline_thread(self):
        selected = self.selected_model.get()
        use_title_mode = self.title_mode_var.get()

        if use_title_mode:
            if self.title_only_var.get():
                title_submode = "title_only"
            elif self.content_mode_var.get():
                title_submode = "content_only"
            else:
                title_submode = "full"
        else:
            title_submode = "full"

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

        skip_long_videos = self.skip_long_video_var.get()
        skip_gpt_processing = self.skip_gpt_var.get()
        move_processed_links = self.move_processed_links_var.get()

        try:
            self.service.initialize_whisper()
            if self.service.is_stop_requested():
                self.log("=== DA DUNG THEO YEU CAU ===")
                self.root.after(0, lambda: self.set_running_state(False))
                return
        except Exception as e:
            self.log(f"❌ Không import được torch/whisper: {e}")
            messagebox.showerror("Lỗi", f"Không import được torch/whisper: {e}")
            self.root.after(0, lambda: self.set_running_state(False))
            return

        self.service.configure_runtime(
            model_name=selected,
            use_title_mode=use_title_mode,
            title_submode=title_submode,
            max_chunks=max_chunks,
            max_links_per_run=max_links_per_run,
            skip_long_videos=skip_long_videos,
            skip_gpt_processing=skip_gpt_processing,
            move_processed_links=move_processed_links,
        )

        try:
            self.service.load_model(selected)
            if self.service.is_stop_requested():
                self.log("=== DA DUNG THEO YEU CAU ===")
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
            self.log("=== DA DUNG THEO YEU CAU ===")
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
