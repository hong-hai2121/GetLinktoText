# -*- coding: utf-8 -*-
"""
reel_gui.py — Giao diện (Tkinter) cho GetReelStats.

Chạy:  python reel_gui.py

Chức năng:
  - Ô dán/sửa danh sách link Reel (Tải / Lưu về reel_links.txt).
  - Chọn profile Firefox, thời gian chờ, headless, tắt Firefox trước khi chạy, debug.
  - Chọn nơi lưu Excel.
  - Nút Bắt đầu / Dừng; log hiển thị trực tiếp trong cửa sổ.
"""

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import GetReelStats as core

LINKS_FILE = core.DEFAULT_LINKS_FILE
DEFAULT_OUT = os.path.join(os.path.dirname(LINKS_FILE), "reel_stats.xlsx")

_DONE = object()  # sentinel báo worker chạy xong


class _QueueWriter:
    """File-like: mọi print trong worker được đẩy vào queue để GUI hiển thị."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


class ReelStatsGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reel Stats — Crawl lượt thích/bình luận Reel Facebook")
        self.geometry("1400x600")   # tỷ lệ 21:9
        self.minsize(1120, 480)     # 21:9

        self.log_queue: "queue.Queue" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._log_buffer = ""       # gom text theo dòng để tô màu

        self._build_ui()
        self._load_links()
        self.after(100, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Dựng giao diện ───────────────────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        header = tk.Label(self, text="🎬 Reel Stats", font=("Segoe UI", 15, "bold"))
        header.pack(anchor="w", padx=12, pady=(8, 0))
        tk.Label(
            self,
            text="Dán link Reel → Bắt đầu → cập nhật Lượt xem → Xếp hạng Top Ads.",
            fg="#777",
        ).pack(anchor="w", padx=12)

        # Thân: 2 cột — trái nhập liệu, phải nhật ký (hợp tỷ lệ 21:9)
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        body.columnconfigure(0, weight=2, uniform="col")   # cột nhập liệu
        body.columnconfigure(1, weight=3, uniform="col")   # cột nhật ký (rộng hơn)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = tk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        # ── CỘT TRÁI ──────────────────────────────────────────────────────────
        # Danh sách link (co giãn lấp phần trống dọc bên trái)
        links_frame = ttk.LabelFrame(left, text="Danh sách link Reel")
        links_frame.pack(fill="both", expand=True)
        self.links_text = tk.Text(links_frame, height=6, wrap="none", font=("Consolas", 10),
                                  undo=True)
        self.links_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(links_frame, command=self.links_text.yview)
        sb.pack(side="right", fill="y", pady=6)
        self.links_text.config(yscrollcommand=sb.set)

        links_btns = tk.Frame(left)
        links_btns.pack(fill="x", pady=(4, 0))
        ttk.Button(links_btns, text="↻ Tải lại", command=self._load_links).pack(side="left", padx=(0, 6))
        ttk.Button(links_btns, text="💾 Lưu link", command=self._save_links).pack(side="left")

        # Cập nhật lượt xem từ HTML lưới reels
        views_frame = ttk.LabelFrame(left, text="Cập nhật Lượt xem — dán HTML lưới reels (Copy ▸ outerHTML)")
        views_frame.pack(fill="x", pady=(8, 0))
        self.views_text = tk.Text(views_frame, height=3, wrap="none", font=("Consolas", 9))
        self.views_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vsb = ttk.Scrollbar(views_frame, command=self.views_text.yview)
        vsb.pack(side="right", fill="y", pady=6)
        self.views_text.config(yscrollcommand=vsb.set)
        ttk.Button(left, text="👁 Cập nhật Lượt xem vào Excel", command=self._update_views).pack(
            anchor="w", pady=(4, 0))

        # Tùy chọn
        opt = ttk.LabelFrame(left, text="Tùy chọn")
        opt.pack(fill="x", pady=(8, 0))
        tk.Label(opt, text="Profile Firefox:").grid(row=0, column=0, sticky="e", **pad)
        self.profile_var = tk.StringVar()
        profiles = list(core.PROFILES.keys())
        default_profile = next(
            (name for name, path in core.PROFILES.items() if path == core.FIREFOX_PROFILE_PATH),
            profiles[0] if profiles else "",
        )
        self.profile_cb = ttk.Combobox(opt, textvariable=self.profile_var, values=profiles,
                                       state="readonly", width=16)
        self.profile_cb.set(default_profile)
        self.profile_cb.grid(row=0, column=1, sticky="w", **pad)
        tk.Label(opt, text="Chờ/reel (giây):").grid(row=0, column=2, sticky="e", **pad)
        self.wait_var = tk.StringVar(value="4")
        ttk.Spinbox(opt, from_=1, to=30, textvariable=self.wait_var, width=6).grid(
            row=0, column=3, sticky="w", **pad)

        self.headless_var = tk.BooleanVar(value=False)
        self.kill_var = tk.BooleanVar(value=True)
        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Chạy ẩn (headless)", variable=self.headless_var).grid(
            row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Tắt Firefox trước khi chạy", variable=self.kill_var).grid(
            row=1, column=2, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Debug (in aria-label)", variable=self.debug_var).grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)

        tk.Label(opt, text="Lưu Excel:").grid(row=3, column=0, sticky="e", **pad)
        self.out_var = tk.StringVar(value=DEFAULT_OUT)
        ttk.Entry(opt, textvariable=self.out_var, width=34).grid(row=3, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(opt, text="Chọn...", command=self._browse_out).grid(row=3, column=3, sticky="w", **pad)
        opt.columnconfigure(1, weight=1)

        # Nút chạy
        run_row = tk.Frame(left)
        run_row.pack(fill="x", pady=(8, 0))
        self.run_btn = ttk.Button(run_row, text="▶ Bắt đầu", command=self._start)
        self.run_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(run_row, text="■ Dừng", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.rank_btn = ttk.Button(run_row, text="🏆 Xếp hạng Top Ads", command=self._rank_ads)
        self.rank_btn.pack(side="left", padx=(0, 6))
        self.open_btn = ttk.Button(run_row, text="📂 Mở Excel", command=self._open_out, state="disabled")
        self.open_btn.pack(side="left")

        # ── CỘT PHẢI: NHẬT KÝ ─────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(right, text="Nhật ký")
        log_frame.pack(fill="both", expand=True)
        log_top = tk.Frame(log_frame)
        log_top.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Button(log_top, text="🧹 Xóa nhật ký", command=self._clear_log).pack(side="right")
        log_body = tk.Frame(log_frame)
        log_body.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(log_body, wrap="word", bg="#1e1e1e", fg="#d4d4d4",
                                font=("Consolas", 10), state="disabled",
                                spacing1=1, spacing3=3, padx=8, pady=6, relief="flat")
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(log_body, command=self.log_text.yview)
        lsb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=lsb.set)
        # màu theo loại dòng cho dễ nhìn
        self.log_text.tag_config("ok", foreground="#4ec9b0")
        self.log_text.tag_config("err", foreground="#f48771")
        self.log_text.tag_config("warn", foreground="#dcb67a")
        self.log_text.tag_config("info", foreground="#569cd6")
        self.log_text.tag_config("head", foreground="#c586c0", font=("Consolas", 10, "bold"))
        self.log_text.tag_config("muted", foreground="#8a8a8a")

    # ── File link ────────────────────────────────────────────────────────────
    def _load_links(self):
        self.links_text.delete("1.0", "end")
        if os.path.isfile(LINKS_FILE):
            with open(LINKS_FILE, "r", encoding="utf-8") as f:
                self.links_text.insert("1.0", f.read())

    def _save_links(self):
        content = self.links_text.get("1.0", "end").strip() + "\n"
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        self._log(f"💾 Đã lưu link vào {LINKS_FILE}\n")

    def _browse_out(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile="reel_stats.xlsx")
        if path:
            self.out_var.set(path)

    def _open_out(self):
        out = self.out_var.get()
        if os.path.isfile(out):
            try:
                os.startfile(out)  # Windows
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không mở được file: {e}")
        else:
            messagebox.showinfo("Chưa có file", "Chưa có file Excel để mở.")

    # ── Cập nhật lượt xem từ HTML ────────────────────────────────────────────
    def _update_views(self):
        html = self.views_text.get("1.0", "end").strip()
        if not html:
            messagebox.showinfo("Trống", "Dán HTML lưới reels vào ô trước đã.")
            return
        vmap = core.parse_views_html(html)
        if not vmap:
            self._log("⚠️ Không tìm thấy reel/lượt xem trong HTML đã dán.\n")
            messagebox.showwarning("Không thấy", "Không parse được reel/lượt xem từ HTML.")
            return
        try:
            updated, missing = core.update_views_in_excel(self.out_var.get(), vmap)
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            return
        self._log(f"👁 Parse {len(vmap)} reel — cập nhật {updated} dòng, {len(missing)} không khớp Excel.\n")
        if updated:
            self.open_btn.config(state="normal")
        messagebox.showinfo("Xong", f"Đã cập nhật Lượt xem cho {updated} dòng.\nKhông khớp trong Excel: {len(missing)}.")

    # ── Xếp hạng chọn video chạy ads ─────────────────────────────────────────
    def _rank_ads(self):
        try:
            top = core.rank_for_ads(self.out_var.get())
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            return
        self._log("\n🏆 TOP 10 NÊN CHẠY ADS — chọn video bơm quảng cáo\n")
        for line in core.ad_legend():
            self._log("   " + line + "\n")
        self._log("   " + "-" * 56 + "\n")
        for i, d in enumerate(top, 1):
            self._log(f"  {i:>2}. Ads {d['ad']:>5} | view {int(d['view']):>7} | "
                      f"ER {d['er']}% | share {d['share']}% | {d['cap']}\n")
            self._log(f"      {d['url']}\n")
        self.open_btn.config(state="normal")
        messagebox.showinfo(
            "Xong",
            "Đã thêm cột ER%, Share%, Điểm Ads và xếp hạng lại theo Điểm Ads.\n"
            "Top 10 hiển thị trong Nhật ký. Mở file Excel để xem đầy đủ.")

    # ── Chạy / dừng ──────────────────────────────────────────────────────────
    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        self._save_links()
        if not core.read_links_file(LINKS_FILE):
            messagebox.showwarning("Thiếu link", "Danh sách link đang trống.")
            return

        try:
            wait = float(self.wait_var.get())
        except ValueError:
            wait = 4.0
        profile_path = core.resolve_profile_path(self.profile_var.get())

        self.stop_event.clear()
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.open_btn.config(state="disabled")
        self._log("\n" + "=" * 60 + "\n▶ Bắt đầu crawl...\n")

        self.worker = threading.Thread(
            target=self._worker,
            args=(LINKS_FILE, self.out_var.get(), profile_path, wait,
                  self.headless_var.get(), self.kill_var.get(), self.debug_var.get()),
            daemon=True,
        )
        self.worker.start()

    def _worker(self, source, out, profile_path, wait, headless, kill, debug):
        old_stdout = sys.stdout
        sys.stdout = _QueueWriter(self.log_queue)
        try:
            core.run_pipeline(
                source, out, profile_path,
                wait=wait, headless=headless, kill=kill, debug=debug,
                stop_event=self.stop_event,
            )
        except Exception as e:
            print(f"❌ Dừng do lỗi: {e}")
        finally:
            sys.stdout = old_stdout
            self.log_queue.put(_DONE)

    def _stop(self):
        self.stop_event.set()
        self._log("⏹️ Đã yêu cầu dừng — sẽ dừng sau reel đang xử lý...\n")
        self.stop_btn.config(state="disabled")

    # ── Log ──────────────────────────────────────────────────────────────────
    def _drain_log(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item is _DONE:
                    self._on_finished()
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    @staticmethod
    def _line_tag(line):
        """Chọn màu theo nội dung dòng cho dễ nhìn."""
        s = line.strip()
        if not s:
            return None
        indented = line[:1] in (" ", "\t")   # dòng phụ (thụt lề)
        if s.startswith(("✅", "💾", "🎉", "🏆")):
            return "ok"
        if s.startswith("❌"):
            return "err"
        if s.startswith(("⚠️", "⏹️", "💡")):
            return "warn"
        if s.startswith("="):
            return "head"
        if s.startswith(("🎬", "🌐", "🦊", "🔎", "👁", "📄")):
            return "info"
        if indented:
            return "muted"
        return None

    def _log(self, text):
        # gom theo dòng để tô màu (print gửi text rồi '\n' riêng)
        self._log_buffer += text
        self.log_text.config(state="normal")
        while "\n" in self._log_buffer:
            line, self._log_buffer = self._log_buffer.split("\n", 1)
            line += "\n"
            tag = self._line_tag(line)
            self.log_text.insert("end", line, tag) if tag else self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self._log_buffer = ""
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _on_finished(self):
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        if os.path.isfile(self.out_var.get()):
            self.open_btn.config(state="normal")
        self._log("✅ Xong.\n")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("Đang chạy", "Đang crawl. Thoát và dừng?"):
                return
            self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    ReelStatsGUI().mainloop()
