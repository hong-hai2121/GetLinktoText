# gui_doi_chieu_the.py — Đối chiếu giao dịch thẻ (tô màu + tổng hợp theo nhóm)

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import to_do_tong_tien_the as core

# ── Bảng màu Medical (đồng bộ với các tool khác trong HoaDonMISA) ─────────────
BG = "#EEF4FB"
WHITE = "#FFFFFF"
CARD_BDR = "#C2D8F0"

BLUE = "#0D6EAB"
BLUE_H = "#0A5A8E"
TEAL = "#0A8F75"
TEAL_H = "#076F5B"

BTN_NTR = "#DDE9F5"
BTN_NTR_H = "#BDD4EC"

LOG_BG = "#0D1B2A"
LOG_FG = "#D6E8FA"

GREEN = "#1B6B3A"
HIGHLIGHT = "#FFF2CC"  # trùng màu tô trong Excel (core.HIGHLIGHT_HEX)
RED = "#B71C1C"
MUTED = "#4E6E8A"
DARK = "#0D2B45"

F_LBL = ("Segoe UI", 9)
F_BOLD = ("Segoe UI", 9, "bold")
F_TITLE = ("Segoe UI", 14, "bold")
F_LOG = ("Consolas", 9)
F_TREE = ("Segoe UI", 9)


def center_on_screen(window: tk.Misc, width: int, height: int) -> tuple[int, int]:
    """Mở cửa sổ ở giữa màn hình, co lại nếu màn hình thấp hơn kích thước mong muốn."""
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    width = min(width, screen_w - 60)
    height = min(height, screen_h - 90)  # chừa chỗ cho taskbar
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    return width, height


def bordered_btn(parent, text, command, bg, bg_h, fg=WHITE, font=None, padx=18, pady=9):
    font = font or F_BOLD
    wrap = tk.Frame(parent, bg=bg, padx=1, pady=1)
    btn = tk.Button(
        wrap,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        font=font,
        relief="flat",
        cursor="hand2",
        activebackground=bg_h,
        activeforeground=fg,
        padx=padx,
        pady=pady,
        bd=0,
    )
    btn.pack(fill="both")
    btn.bind("<Enter>", lambda _: btn.configure(bg=bg_h))
    btn.bind("<Leave>", lambda _: btn.configure(bg=bg))
    return wrap, btn


def open_in_explorer(path: Path) -> None:
    """Mở file hoặc chọn sẵn file trong Explorer."""
    if os.name != "nt":
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
        return
    if path.is_dir():
        os.startfile(str(path))  # noqa: S606
    else:
        subprocess.Popen(["explorer", "/select,", str(path)])


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Đối chiếu giao dịch thẻ — Tô màu & tổng hợp")
        self.configure(bg=BG)
        width, height = center_on_screen(self, 900, 760)
        self.minsize(min(760, width), min(600, height))

        self.source_path: Path | None = None
        self.result: core.Result | None = None
        self.running = False
        # tkinter không an toàn khi gọi từ thread khác -> worker chỉ đẩy vào queue,
        # mọi thao tác widget do main thread lấy ra xử lý
        self.events: queue.Queue = queue.Queue()

        self._build_header()
        self._build_input_card()
        self._build_result_card()
        self._build_log_card()

        self._preselect_downloads()
        self.after(80, self._drain_events)

    # ── Dựng giao diện ────────────────────────────────────────────────────────
    def _build_header(self) -> None:
        head = tk.Frame(self, bg=DARK)
        head.pack(fill="x")
        tk.Label(
            head,
            text="ĐỐI CHIẾU GIAO DỊCH THẺ",
            bg=DARK,
            fg=WHITE,
            font=F_TITLE,
            pady=12,
        ).pack(side="left", padx=18)
        tk.Label(
            head,
            text="Tô màu giao dịch của thẻ · tổng hợp theo nhóm · lưu ra Downloads",
            bg=DARK,
            fg="#8FB8D8",
            font=F_LBL,
        ).pack(side="left", padx=4)

    def _card(self, title: str) -> tk.Frame:
        outer = tk.Frame(self, bg=CARD_BDR, padx=1, pady=1)
        outer.pack(fill="x", padx=14, pady=(12, 0))
        inner = tk.Frame(outer, bg=WHITE, padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=WHITE, fg=MUTED, font=F_BOLD).pack(anchor="w")
        return inner

    def _build_input_card(self) -> None:
        card = self._card("FILE NGUỒN")

        row = tk.Frame(card, bg=WHITE)
        row.pack(fill="x", pady=(8, 0))
        self.path_var = tk.StringVar(value="Chưa chọn file")
        entry = tk.Entry(
            row,
            textvariable=self.path_var,
            font=F_LBL,
            relief="solid",
            bd=1,
            bg="#F7FAFD",
            fg=DARK,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        pick_wrap, _ = bordered_btn(row, "Chọn file", self.choose_file, BTN_NTR, BTN_NTR_H, fg=DARK)
        pick_wrap.pack(side="left", padx=(8, 0))

        opts = tk.Frame(card, bg=WHITE)
        opts.pack(fill="x", pady=(10, 0))
        tk.Label(opts, text="Số thẻ tô màu:", bg=WHITE, fg=DARK, font=F_LBL).pack(side="left")
        self.card_var = tk.StringVar(value=core.DEFAULT_CARD)
        tk.Entry(
            opts,
            textvariable=self.card_var,
            font=F_LBL,
            relief="solid",
            bd=1,
            bg="#F7FAFD",
            width=22,
        ).pack(side="left", padx=(8, 18), ipady=4)
        tk.Label(
            opts,
            text="(khớp 6 số đầu + 4 số cuối, bỏ qua phần che ... hay XXXXXX)",
            bg=WHITE,
            fg=MUTED,
            font=F_LBL,
        ).pack(side="left")

        run_row = tk.Frame(card, bg=WHITE)
        run_row.pack(fill="x", pady=(12, 2))
        run_wrap, self.run_btn = bordered_btn(
            run_row, "XỬ LÝ", self.run, BLUE, BLUE_H, font=("Segoe UI", 11, "bold"), padx=40, pady=11
        )
        run_wrap.pack()

    def _build_result_card(self) -> None:
        card = self._card("KẾT QUẢ")

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Result.Treeview",
            background=WHITE,
            fieldbackground=WHITE,
            foreground=DARK,
            rowheight=25,
            font=F_TREE,
            borderwidth=0,
        )
        style.configure("Result.Treeview.Heading", font=F_BOLD, background=BTN_NTR, foreground=DARK)
        style.map("Result.Treeview", background=[("selected", "#CFE3F7")])

        wrap = tk.Frame(card, bg=CARD_BDR, padx=1, pady=1)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(
            wrap,
            columns=("nhom", "sogd", "tien"),
            show="headings",
            height=7,
            style="Result.Treeview",
        )
        self.tree.heading("nhom", text="Nhóm giao dịch", anchor="w")
        self.tree.heading("sogd", text="Số GD", anchor="e")
        self.tree.heading("tien", text="Số tiền", anchor="e")
        self.tree.column("nhom", width=470, anchor="w")
        self.tree.column("sogd", width=70, anchor="e", stretch=False)
        self.tree.column("tien", width=150, anchor="e", stretch=False)
        self.tree.tag_configure("card", background=HIGHLIGHT, foreground=DARK, font=F_BOLD)
        self.tree.tag_configure("total", background="#EAF2FB", font=F_BOLD)
        self.tree.pack(fill="both", expand=True)

        self.summary_var = tk.StringVar(value="Chọn file rồi bấm XỬ LÝ.")
        tk.Label(
            card, textvariable=self.summary_var, bg=WHITE, fg=MUTED, font=F_LBL, anchor="w"
        ).pack(fill="x", pady=(8, 0))

    def _build_log_card(self) -> None:
        outer = tk.Frame(self, bg=CARD_BDR, padx=1, pady=1)
        outer.pack(fill="both", expand=True, padx=14, pady=12)
        inner = tk.Frame(outer, bg=WHITE)
        inner.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            inner,
            bg=LOG_BG,
            fg=LOG_FG,
            font=F_LOG,
            height=8,
            relief="flat",
            state="disabled",
            wrap="none",
        )
        self.log_text.pack(fill="both", expand=True, side="top")

        actions = tk.Frame(inner, bg=WHITE, pady=8)
        actions.pack(fill="x")
        self.open_file_wrap, self.open_file_btn = bordered_btn(
            actions, "Mở file kết quả", self.open_result, TEAL, TEAL_H
        )
        self.open_file_wrap.pack(side="right", padx=(8, 10))
        self.open_dir_wrap, self.open_dir_btn = bordered_btn(
            actions, "Mở thư mục", self.open_folder, BTN_NTR, BTN_NTR_H, fg=DARK
        )
        self.open_dir_wrap.pack(side="right")
        self._set_actions_enabled(False)

    # ── Tiện ích ──────────────────────────────────────────────────────────────
    def _set_actions_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.open_file_btn.configure(state=state)
        self.open_dir_btn.configure(state=state)

    def log(self, message: str, color: str | None = None) -> None:
        """Gọi được từ mọi thread — chỉ xếp hàng, main thread mới vẽ."""
        self.events.put(("log", message, color))

    def _append_log(self, message: str, color: str | None) -> None:
        self.log_text.configure(state="normal")
        tag = f"c{color}" if color else "plain"
        self.log_text.tag_configure(tag, foreground=color or LOG_FG)
        self.log_text.tag_configure("ts", foreground="#3A6B9A")
        self.log_text.insert("end", f"[{datetime.now():%H:%M:%S}] ", "ts")
        self.log_text.insert("end", f"{message}\n", tag)
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, *payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(payload[0], payload[1])
                elif kind == "done":
                    self._finish(payload[0])
                elif kind == "error":
                    self._finish(None)
                    messagebox.showerror("Lỗi", payload[0])
        except queue.Empty:
            pass
        self.after(80, self._drain_events)

    def _preselect_downloads(self) -> None:
        found = core.latest_statement_in_downloads()
        if found:
            self.source_path = found
            self.path_var.set(str(found))
            self.log(f"Gợi ý file mới nhất trong Downloads: {found.name}")
        else:
            self.log(f"Chưa có .xlsx nào trong {core.downloads_dir()}")

    # ── Hành động ─────────────────────────────────────────────────────────────
    def choose_file(self) -> None:
        initial = str(self.source_path.parent if self.source_path else core.downloads_dir())
        chosen = filedialog.askopenfilename(
            title="Chọn file đối chiếu lịch sử giao dịch",
            initialdir=initial,
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Tất cả", "*.*")],
        )
        if not chosen:
            return
        self.source_path = Path(chosen)
        self.path_var.set(chosen)
        self.log(f"Đã chọn: {self.source_path.name}")

    def run(self) -> None:
        if self.running:
            return
        if not self.source_path or not self.source_path.exists():
            messagebox.showwarning("Thiếu file", "Chọn file nguồn trước đã.")
            return

        self.running = True
        self.run_btn.configure(state="disabled", text="ĐANG XỬ LÝ...")
        self._set_actions_enabled(False)
        self.tree.delete(*self.tree.get_children())
        # Đọc giá trị widget ngay trên main thread rồi mới đưa sang worker
        source = self.source_path
        card = self.card_var.get().strip() or core.DEFAULT_CARD
        threading.Thread(target=self._worker, args=(source, card), daemon=True).start()

    def _worker(self, source: Path, card: str) -> None:
        try:
            result = core.process(source=source, card=card, log=self.log)
        except Exception as exc:  # lỗi đọc file / sai định dạng / file đang mở
            self.log(str(exc), "#E76F51")
            self.events.put(("error", str(exc)))
            return
        self.events.put(("done", result))

    def _finish(self, result: core.Result | None) -> None:
        self.running = False
        self.run_btn.configure(state="normal", text="XỬ LÝ")
        if result is None:
            self.summary_var.set("Xử lý thất bại — xem log bên dưới.")
            return

        self.result = result
        for group in result.groups:
            self.tree.insert(
                "",
                "end",
                values=(group.key, f"{group.count:,}", f"{group.amount:,.0f}"),
                tags=("card",) if group.is_card else (),
            )
        self.tree.insert(
            "", "end", values=("TỔNG CỘNG", "", f"{result.total:,.0f}"), tags=("total",)
        )

        month = f" tháng {result.months[0]}" if len(result.months) == 1 else ""
        self.summary_var.set(
            f"Tô màu {result.highlighted} hàng khớp thẻ{month} · báo cáo tại "
            f"{result.report_range} · file: {result.output.name}"
        )
        self.log(f"Xong. Kết quả: {result.output}", "#7CD992")
        self._set_actions_enabled(True)

    def open_result(self) -> None:
        if self.result and self.result.output.exists():
            os.startfile(str(self.result.output))  # noqa: S606

    def open_folder(self) -> None:
        if self.result:
            open_in_explorer(self.result.output)


if __name__ == "__main__":
    App().mainloop()
