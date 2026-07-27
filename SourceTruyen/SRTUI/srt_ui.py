import os
import sys
import threading
import queue
import importlib.util
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


def center_on_screen(win, w=None, h=None):
    """Đưa cửa sổ ra giữa màn hình; bỏ trống w/h thì giữ kích thước hiện tại."""
    win.update_idletasks()
    w = w or max(win.winfo_width(), win.winfo_reqwidth())
    h = h or max(win.winfo_height(), win.winfo_reqheight())
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(w, sw), min(h, sh)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


class _LogRedirector:
    def __init__(self, log_queue):
        self._queue = log_queue

    def write(self, msg):
        if msg:
            self._queue.put(msg)

    def flush(self):
        pass


class SRTTranslatorUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRT Translator UI")
        center_on_screen(self, 1100, 720)
        self.minsize(980, 640)

        self.repo_root = Path(__file__).resolve().parents[2]
        self.dich_module = self._load_dich_module()
        if not self.dich_module:
            self.destroy()
            return
        self.check_module = self._load_aux_module(
            self.repo_root / "SourceTruyen" / "SRTUI" / "checkTiengViet.py",
            "check_tieng_viet",
            "checkTiengViet.py",
        )
        self.patch_module = self._load_aux_module(
            self.repo_root / "SourceTruyen" / "SRTUI" / "ThayTheBlock.py",
            "thay_the_block",
            "ThayTheBlock.py",
        )

        self.log_queue = queue.Queue()
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = _LogRedirector(self.log_queue)
        sys.stderr = _LogRedirector(self.log_queue)

        self.running = False
        self._build_ui()
        self._update_instruction_preview()
        self.refresh_files()
        self.refresh_folder_view()
        self._poll_log_queue()

    def _load_dich_module(self):
        module_path = self.repo_root / "SourceTruyen" / "SRTUI" / "Dich20.9.py"
        if not module_path.exists():
            messagebox.showerror(
                "Không tìm thấy file",
                f"Không tìm thấy: {module_path}",
            )
            return None
        spec = importlib.util.spec_from_file_location("dich209", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _load_aux_module(self, module_path, module_name, display_name):
        if not module_path.exists():
            messagebox.showwarning(
                "Không tìm thấy file",
                f"Không tìm thấy: {display_name}",
            )
            return None
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _build_ui(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=5)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        left_frame = ttk.Frame(self, padding=8)
        right_frame = ttk.Frame(self, padding=8)
        left_frame.grid(row=0, column=0, sticky="nsew")
        right_frame.grid(row=0, column=1, sticky="nsew")

        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(3, weight=1)

        self._build_folder_viewer(left_frame)

        ttk.Label(left_frame, text="Queue file (.srt)", font=("Segoe UI", 11, "bold")).grid(
            row=2, column=0, sticky="w", pady=(8, 6)
        )
        self.tree = ttk.Treeview(
            left_frame,
            columns=("file", "status", "progress", "output"),
            show="headings",
            selectmode="browse",
            height=15,
        )
        self.tree.heading("file", text="File")
        self.tree.heading("status", text="Trạng thái")
        self.tree.heading("progress", text="Progress")
        self.tree.heading("output", text="Output")
        self.tree.column("file", width=220, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("progress", width=90, anchor="center")
        self.tree.column("output", width=90, anchor="center")
        self.tree.grid(row=3, column=0, sticky="nsew")

        left_buttons = ttk.Frame(left_frame)
        left_buttons.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        left_buttons.columnconfigure(0, weight=1)
        ttk.Button(left_buttons, text="Refresh queue", command=self.refresh_files).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(left_buttons, text="Reset file (xóa progress/output)", command=self.reset_selected_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Label(
            left_buttons,
            text="Input: SourceTruyen/dSRT  |  Output: SourceTruyen/Outputs  |  Archive: SourceTruyen/old srt",
            foreground="#666666",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)

        header = ttk.Frame(right_frame)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Cấu hình & Trạng thái", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        self.notebook = ttk.Notebook(right_frame)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.config_tab = ttk.Frame(self.notebook, padding=8)
        self.status_tab = ttk.Frame(self.notebook, padding=8)
        self.instruction_tab = ttk.Frame(self.notebook, padding=8)
        self.tools_tab = ttk.Frame(self.notebook, padding=8)

        self.notebook.add(self.config_tab, text="Cấu hình dịch")
        self.notebook.add(self.status_tab, text="Trạng thái batch")
        self.notebook.add(self.instruction_tab, text="Instruction")
        self.notebook.add(self.tools_tab, text="Hậu xử lý")

        self._build_config_tab()
        self._build_status_tab()
        self._build_instruction_tab()
        self._build_tools_tab()

        footer = ttk.Frame(self, padding=8)
        footer.grid(row=1, column=0, columnspan=2, sticky="nsew")
        footer.columnconfigure(0, weight=1)
        footer.rowconfigure(1, weight=1)
        ttk.Label(footer, text="Log", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.log_text = tk.Text(footer, height=10, wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _build_folder_viewer(self, parent):
        self.folder_configs = [
            ("dSRT", "SourceTruyen/dSRT"),
            (".progress", "SourceTruyen/.progress"),
            ("old srt", "SourceTruyen/old srt"),
            ("Outputs", "SourceTruyen/Outputs"),
        ]
        self.folder_lists = {}

        wrapper = ttk.Frame(parent)
        wrapper.grid(row=0, column=0, sticky="nsew")
        wrapper.columnconfigure(0, weight=1)

        ttk.Label(wrapper, text="Thư mục", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        self.folder_notebook = ttk.Notebook(wrapper)
        self.folder_notebook.grid(row=1, column=0, sticky="ew")
        self.folder_notebook.bind("<<NotebookTabChanged>>", lambda _e: self.refresh_folder_view())

        for label, _path in self.folder_configs:
            tab = ttk.Frame(self.folder_notebook)
            tab.columnconfigure(0, weight=1)
            tab.rowconfigure(0, weight=1)
            listbox = tk.Listbox(tab, height=6)
            listbox.grid(row=0, column=0, sticky="ew")
            scroll = ttk.Scrollbar(tab, orient="vertical", command=listbox.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            listbox.configure(yscrollcommand=scroll.set)
            listbox.bind("<Double-1>", lambda _e: self.open_selected_file())
            self.folder_notebook.add(tab, text=label)
            self.folder_lists[label] = listbox

        action_row = ttk.Frame(wrapper)
        action_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(action_row, text="Refresh", command=self.refresh_folder_view).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(action_row, text="Mở file", command=self.open_selected_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(action_row, text="Thêm file", command=self.add_file_to_folder).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(action_row, text="Xóa file", command=self.delete_selected_file).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )

    def _build_config_tab(self):
        self.group_size_var = tk.StringVar(value=str(self.dich_module.GROUP_SIZE))
        self.start_block_var = tk.StringVar(value=str(self.dich_module.START_BLOCK_INDEX))
        self.end_block_var = tk.StringVar(
            value="" if self.dich_module.END_BLOCK_INDEX is None else str(self.dich_module.END_BLOCK_INDEX)
        )
        self.stop_on_missing_var = tk.BooleanVar(value=bool(self.dich_module.STOP_ON_MISSING))
        self.send_instruction_var = tk.BooleanVar(value=bool(self.dich_module.SEND_INSTRUCTION_BEFORE))
        self.instruction_mode_var = tk.StringVar(value=str(self.dich_module.INSTRUCTION_MODE).lower())

        row = 0
        ttk.Label(self.config_tab, text="Kích thước batch (GROUP_SIZE)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(self.config_tab, textvariable=self.group_size_var, width=12).grid(
            row=row, column=1, sticky="w", padx=(8, 0), pady=4
        )
        row += 1
        ttk.Label(self.config_tab, text="Block bắt đầu (START_BLOCK_INDEX)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(self.config_tab, textvariable=self.start_block_var, width=12).grid(
            row=row, column=1, sticky="w", padx=(8, 0), pady=4
        )
        row += 1
        ttk.Label(self.config_tab, text="Block kết thúc (để trống = tất cả)").grid(
            row=row, column=0, sticky="w", pady=4
        )
        ttk.Entry(self.config_tab, textvariable=self.end_block_var, width=12).grid(
            row=row, column=1, sticky="w", padx=(8, 0), pady=4
        )
        row += 1
        ttk.Checkbutton(self.config_tab, text="Dừng nếu thiếu nội dung", variable=self.stop_on_missing_var).grid(
            row=row, column=0, sticky="w", pady=4
        )
        row += 1
        ttk.Checkbutton(self.config_tab, text="Gửi instruction trước khi dịch", variable=self.send_instruction_var).grid(
            row=row, column=0, sticky="w", pady=4
        )
        row += 1
        ttk.Label(self.config_tab, text="Chế độ instruction").grid(row=row, column=0, sticky="w", pady=4)
        self.instruction_mode_combo = ttk.Combobox(
            self.config_tab,
            textvariable=self.instruction_mode_var,
            values=["xianxia", "anhviet", "drama"],
            state="readonly",
            width=12,
        )
        self.instruction_mode_combo.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=4)
        self.instruction_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_instruction_preview())

        row += 1
        self.start_button = ttk.Button(self.config_tab, text="Start", command=self.on_start)
        self.start_button.grid(row=row, column=0, sticky="w", pady=(10, 0))

        ttk.Button(self.config_tab, text="Refresh queue", command=self.refresh_files).grid(
            row=row, column=1, sticky="w", padx=(8, 0), pady=(10, 0)
        )

    def _build_status_tab(self):
        self.status_var = tk.StringVar(value="Idle")
        self.progress_file_var = tk.StringVar(value="-")
        self.progress_index_var = tk.StringVar(value="-")
        self.progress_time_var = tk.StringVar(value="-")
        ttk.Label(self.status_tab, text="Trạng thái chạy:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(self.status_tab, textvariable=self.status_var, foreground="#0a6bbd").grid(
            row=0, column=1, sticky="w", pady=4
        )
        ttk.Label(self.status_tab, text="File đang dịch:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Label(self.status_tab, textvariable=self.progress_file_var).grid(
            row=1, column=1, sticky="w", pady=4
        )
        ttk.Label(self.status_tab, text="Block tiếp theo:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Label(self.status_tab, textvariable=self.progress_index_var).grid(
            row=2, column=1, sticky="w", pady=4
        )
        ttk.Label(self.status_tab, text="Cập nhật lúc:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Label(self.status_tab, textvariable=self.progress_time_var).grid(
            row=3, column=1, sticky="w", pady=4
        )
        ttk.Label(
            self.status_tab,
            text="Theo dõi chi tiết batch qua Log (vì script hiện tại log theo console).",
            foreground="#666666",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=6)

    def _build_instruction_tab(self):
        self.instruction_text = tk.Text(self.instruction_tab, wrap="word", height=18)
        self.instruction_text.grid(row=0, column=0, sticky="nsew")
        self.instruction_tab.columnconfigure(0, weight=1)
        self.instruction_tab.rowconfigure(0, weight=1)
        self.instruction_text.configure(state="disabled")

    def _build_tools_tab(self):
        self.tools_tab.columnconfigure(0, weight=1)

        ttk.Label(self.tools_tab, text="Kiểm tra tiếng Việt (checkTiengViet)", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self._add_path_link(self.tools_tab, "Input: SourceTruyen/Outputs", row=1)
        self._add_path_link(self.tools_tab, "Output: SourceTruyen/Cleaned", row=2)
        self._add_path_link(self.tools_tab, "Log: SourceTruyen/Cleaned/ALL_ERRORS.log", row=3)
        ttk.Button(
            self.tools_tab,
            text="Chạy kiểm tra tiếng Việt",
            command=self.run_check_tieng_viet,
        ).grid(row=4, column=0, sticky="w", pady=(6, 12))

        ttk.Separator(self.tools_tab).grid(row=5, column=0, sticky="ew", pady=6)

        ttk.Label(self.tools_tab, text="Vá block theo ALL_ERRORS.log (ThayTheBlock)", font=("Segoe UI", 10, "bold")).grid(
            row=6, column=0, sticky="w", pady=(6, 6)
        )
        self._add_path_link(self.tools_tab, "Input/Output: SourceTruyen/Cleaned", row=7)
        self._add_path_link(self.tools_tab, "Log: SourceTruyen/Cleaned/ALL_ERRORS.log", row=8)
        ttk.Button(
            self.tools_tab,
            text="Chạy vá block từ log",
            command=self.run_patch_blocks,
        ).grid(row=9, column=0, sticky="w", pady=(6, 0))

    def _instruction_map(self):
        return {
            "xianxia": self.dich_module.INSTRUCTION_FIRST,
            "anhviet": getattr(self.dich_module, "INSTRUCTION_FIRST_AnhViet", self.dich_module.INSTRUCTION_FIRST),
            "drama": getattr(self.dich_module, "INSTRUCTION_FIRST_Darama", self.dich_module.INSTRUCTION_FIRST),
        }

    def _update_instruction_preview(self):
        mode = self.instruction_mode_var.get().lower()
        text = self._instruction_map().get(mode, "")
        self.instruction_text.configure(state="normal")
        self.instruction_text.delete("1.0", tk.END)
        self.instruction_text.insert(tk.END, text)
        self.instruction_text.configure(state="disabled")

    def refresh_files(self):
        self.tree.delete(*self.tree.get_children())
        input_dir = self.repo_root / self.dich_module.SRT_INPUT_DIR
        output_dir = self.repo_root / self.dich_module.OUTPUT_DIR
        progress_dir = self.repo_root / self.dich_module.PROGRESS_DIR

        if not input_dir.exists():
            return

        for name in sorted(os.listdir(input_dir)):
            if not name.lower().endswith(".srt"):
                continue
            progress_path = progress_dir / f"{name}.json"
            progress = self._read_progress_index(progress_path)

            stem = Path(name).stem
            output_exists = any(output_dir.glob(f"{stem}_translated*.srt")) if output_dir.exists() else False
            output = "Có" if output_exists else "Không"
            status = "Resume" if progress_path.exists() else "Pending"
            self.tree.insert("", "end", iid=name, values=(name, status, progress, output))

        self.tree.configure(displaycolumns=("file", "status", "progress", "output"))

    def refresh_folder_view(self):
        label = self._current_folder_label()
        listbox = self.folder_lists.get(label)
        if not listbox:
            return
        listbox.delete(0, tk.END)
        folder_path = self.repo_root / self._folder_path_by_label(label)
        if not folder_path.exists():
            listbox.insert(tk.END, "(Không có thư mục)")
            return
        items = sorted(os.listdir(folder_path))
        if not items:
            listbox.insert(tk.END, "(Trống)")
            return
        for name in items:
            listbox.insert(tk.END, name)

    def open_selected_file(self):
        label = self._current_folder_label()
        listbox = self.folder_lists.get(label)
        if not listbox:
            return
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning("Chưa chọn file", "Hãy chọn file trong tab thư mục.")
            return
        filename = listbox.get(selection[0])
        if filename.startswith("("):
            return
        file_path = self.repo_root / self._folder_path_by_label(label) / filename
        self._open_file_editor(file_path)

    def delete_selected_file(self):
        label = self._current_folder_label()
        listbox = self.folder_lists.get(label)
        if not listbox:
            return
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning("Chưa chọn file", "Hãy chọn file trong tab thư mục.")
            return
        filename = listbox.get(selection[0])
        if filename.startswith("("):
            return
        file_path = self.repo_root / self._folder_path_by_label(label) / filename
        if not file_path.exists():
            self.refresh_folder_view()
            return
        if file_path.is_dir():
            messagebox.showwarning("Không xóa được", "Chỉ xóa được file.")
            return
        if not messagebox.askyesno("Xóa file", f"Bạn muốn xóa file:\n{filename} ?"):
            return
        try:
            file_path.unlink()
        except Exception as exc:
            messagebox.showerror("Không xóa được file", str(exc))
            return
        self.refresh_folder_view()

    def _add_path_link(self, parent, text, row):
        label = ttk.Label(parent, text=text, foreground="#0a6bbd", cursor="hand2")
        label.grid(row=row, column=0, sticky="w", pady=2)
        label.bind("<Button-1>", lambda _e: self._open_path_from_label(text))

    def _open_path_from_label(self, label_text):
        if ":" not in label_text:
            return
        path_text = label_text.split(":", 1)[1].strip()
        path = self.repo_root / path_text
        self._open_path(path)

    def _open_path(self, path):
        try:
            if path.is_dir():
                os.startfile(str(path))
                return
            if path.exists():
                self._open_file_editor(path)
        except Exception as exc:
            messagebox.showerror("Không mở được", str(exc))

    def _open_file_editor(self, file_path):
        if not file_path.exists() or file_path.is_dir():
            messagebox.showwarning("Không mở được", "Chỉ mở được file.")
            return
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            messagebox.showerror("Không đọc được file", str(exc))
            return
        viewer = tk.Toplevel(self)
        viewer.title(file_path.name)
        center_on_screen(viewer, 900, 650)
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(1, weight=1)

        top_bar = ttk.Frame(viewer)
        top_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        ttk.Label(top_bar, text=str(file_path)).grid(row=0, column=0, sticky="w")
        ttk.Button(top_bar, text="Lưu", command=lambda: self._save_file_edits(file_path, text)).grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )

        text = tk.Text(viewer, wrap="word")
        text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        text.insert("1.0", content)

    def add_file_to_folder(self):
        label = self._current_folder_label()
        target_dir = self.repo_root / self._folder_path_by_label(label)
        if not target_dir.exists():
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                messagebox.showerror("Không tạo được thư mục", str(exc))
                return
        src_path = filedialog.askopenfilename(
            title="Chọn file để thêm",
            filetypes=[("All files", "*.*")],
        )
        if not src_path:
            return
        src_path = Path(src_path)
        dst_path = target_dir / src_path.name
        if dst_path.exists():
            if not messagebox.askyesno(
                "Trùng tên",
                f"File đã tồn tại:\n{dst_path.name}\nGhi đè?",
            ):
                return
        try:
            dst_path.write_bytes(src_path.read_bytes())
        except Exception as exc:
            messagebox.showerror("Không thêm được file", str(exc))
            return
        self.refresh_folder_view()

    def _save_file_edits(self, file_path, text_widget):
        try:
            content = text_widget.get("1.0", tk.END)
            file_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Không lưu được file", str(exc))
            return
        messagebox.showinfo("Đã lưu", "Lưu file thành công.")

    def _folder_path_by_label(self, label):
        for name, path in self.folder_configs:
            if name == label:
                return path
        return "SourceTruyen"

    def _current_folder_label(self):
        current = self.folder_notebook.index("current")
        return self.folder_notebook.tab(current, "text")

    def _read_progress_index(self, progress_path):
        if not progress_path.exists():
            return "-"
        try:
            import json
            data = json.loads(progress_path.read_text(encoding="utf-8"))
            return str(data.get("next_index", "-"))
        except Exception:
            return "-"

    def reset_selected_file(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Chưa chọn file", "Hãy chọn file .srt trong danh sách.")
            return
        filename = selection[0]
        if not messagebox.askyesno(
            "Reset file",
            f"Bạn muốn reset tiến trình và output của file:\n{filename} ?",
        ):
            return
        input_dir = self.repo_root / self.dich_module.SRT_INPUT_DIR
        output_dir = self.repo_root / self.dich_module.OUTPUT_DIR
        progress_dir = self.repo_root / self.dich_module.PROGRESS_DIR

        progress_path = progress_dir / f"{filename}.json"
        if progress_path.exists():
            try:
                progress_path.unlink()
            except Exception as exc:
                messagebox.showerror("Không xóa được progress", str(exc))
                return

        stem = Path(filename).stem
        if output_dir.exists():
            for path in output_dir.glob(f"{stem}_translated*.srt"):
                try:
                    path.unlink()
                except Exception as exc:
                    messagebox.showerror("Không xóa được output", str(exc))
                    return

        self.refresh_files()
        self.refresh_folder_view()

    def run_check_tieng_viet(self):
        if not self.check_module:
            messagebox.showwarning("Thiếu file", "Không tìm thấy checkTiengViet.py")
            return
        outputs_dir = self.repo_root / "SourceTruyen" / "Outputs"
        cleaned_dir = self.repo_root / "SourceTruyen" / "Cleaned"
        old_srt_dir = self.repo_root / "SourceTruyen" / "old srt"
        log_file = cleaned_dir / "ALL_ERRORS.log"

        self.check_module.OUTPUTS_DIR = str(outputs_dir)
        self.check_module.CLEANED_DIR = str(cleaned_dir)
        self.check_module.OLD_SRT_DIR = str(old_srt_dir)
        self.check_module.COMBINED_LOG_FILE = str(log_file)

        def _task():
            self.check_module.process_all_srt_files(
                input_folder=str(outputs_dir),
                output_folder=str(cleaned_dir),
                replacements=self.check_module.REPLACEMENTS,
                duplicate_min_chars=self.check_module.DUPLICATE_MIN_CHARS,
                old_srt_dir=str(old_srt_dir),
                combined_log_file=str(log_file),
            )

        threading.Thread(target=_task, daemon=True).start()

    def run_patch_blocks(self):
        if not self.patch_module:
            messagebox.showwarning("Thiếu file", "Không tìm thấy ThayTheBlock.py")
            return
        root_dir = self.repo_root / "SourceTruyen" / "Cleaned"
        log_file = root_dir / "ALL_ERRORS.log"

        self.patch_module.ROOT = root_dir
        self.patch_module.COMBINED_LOG = log_file

        def _task():
            self.patch_module.main()

        threading.Thread(target=_task, daemon=True).start()

    def _validate_config(self):
        try:
            group_size = int(self.group_size_var.get())
            if group_size <= 0:
                raise ValueError
        except Exception:
            raise ValueError("GROUP_SIZE phải là số nguyên dương.")

        try:
            start_index = int(self.start_block_var.get())
            if start_index < 0:
                raise ValueError
        except Exception:
            raise ValueError("START_BLOCK_INDEX phải là số nguyên >= 0.")

        end_text = self.end_block_var.get().strip()
        if end_text:
            try:
                end_index = int(end_text)
                if end_index < 0:
                    raise ValueError
            except Exception:
                raise ValueError("END_BLOCK_INDEX phải là số nguyên >= 0 hoặc để trống.")

    def _apply_config(self):
        self.dich_module.GROUP_SIZE = int(self.group_size_var.get())
        self.dich_module.START_BLOCK_INDEX = int(self.start_block_var.get())

        end_text = self.end_block_var.get().strip()
        self.dich_module.END_BLOCK_INDEX = int(end_text) if end_text else None
        self.dich_module.STOP_ON_MISSING = bool(self.stop_on_missing_var.get())
        self.dich_module.SEND_INSTRUCTION_BEFORE = bool(self.send_instruction_var.get())

        mode = self.instruction_mode_var.get().lower()
        self.dich_module.INSTRUCTION_MODE = mode

        if mode == "anhviet":
            self.dich_module.INSTRUCTION_FIRST = self._instruction_map()["anhviet"]
        elif mode == "xianxia":
            self.dich_module.INSTRUCTION_FIRST = self._instruction_map()["xianxia"]

    def on_start(self):
        if self.running:
            return
        try:
            self._validate_config()
        except ValueError as err:
            messagebox.showerror("Cấu hình không hợp lệ", str(err))
            return

        self._apply_config()
        self._set_running(True)
        thread = threading.Thread(target=self._run_translator, daemon=True)
        thread.start()

    def _run_translator(self):
        try:
            translator = self.dich_module.Translator()
            translator.run()
        except SystemExit:
            pass
        except Exception as exc:
            print(f"⚠️ Lỗi không mong muốn: {exc}")
        finally:
            self.after(0, lambda: self._set_running(False))

    def _set_running(self, value):
        self.running = value
        self.status_var.set("Running" if value else "Idle")
        self.start_button.configure(state="disabled" if value else "normal")

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, msg)
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(120, self._poll_log_queue)
        self._poll_progress_status()

    def _poll_progress_status(self):
        progress_dir = self.repo_root / self.dich_module.PROGRESS_DIR
        latest = None
        if progress_dir.exists():
            for item in progress_dir.glob("*.json"):
                try:
                    mtime = item.stat().st_mtime
                    if latest is None or mtime > latest[0]:
                        latest = (mtime, item)
                except Exception:
                    continue

        if latest:
            item = latest[1]
            self.progress_file_var.set(item.stem.replace(".srt", ".srt"))
            self.progress_index_var.set(self._read_progress_index(item))
            try:
                from datetime import datetime
                self.progress_time_var.set(datetime.fromtimestamp(latest[0]).strftime("%H:%M:%S"))
            except Exception:
                self.progress_time_var.set("-")
        else:
            self.progress_file_var.set("-")
            self.progress_index_var.set("-")
            self.progress_time_var.set("-")

    def destroy(self):
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        super().destroy()


if __name__ == "__main__":
    app = SRTTranslatorUI()
    app.mainloop()
