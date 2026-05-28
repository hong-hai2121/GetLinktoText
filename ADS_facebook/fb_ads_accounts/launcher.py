"""
Giao diện chọn ngày và chạy script thu thập dữ liệu Facebook Ads.
Chạy: python launcher.py
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import json
import sys
from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).parent

PRESETS = [
    ("Hôm nay",          "today"),
    ("Hôm qua",          "yesterday"),
    ("7 ngày qua",       "last_7d"),
    ("14 ngày qua",      "last_14d"),
    ("28 ngày qua",      "last_28d"),
    ("30 ngày qua",      "last_30d"),
    ("Tháng này",        "this_month"),
    ("Tháng trước",      "last_month"),
    ("Quý này",          "this_quarter"),
    ("Quý trước",        "last_quarter"),
    ("Toàn thời gian",   "lifetime"),
]
PRESET_LABELS = [p[0] for p in PRESETS]
PRESET_MAP    = {p[0]: p[1] for p in PRESETS}

# ── Palette ────────────────────────────────────────────────────────────────────
BG      = "#0f1117"
SURFACE = "#1a1d27"
BORDER  = "#2a2d3a"
ACCENT  = "#4f8ef7"
GREEN   = "#3ecf8e"
YELLOW  = "#f0a500"
RED     = "#e05260"
TEXT    = "#d4d8e8"
MUTED   = "#7a7f96"
CODE_BG = "#131620"


def write_config(date_preset: str, time_range: dict | None):
    """Ghi config.py để get_campaigns.py và get_details.py đọc."""
    # Đọc ACCESS_TOKEN hiện tại để không bị xóa khi ghi đè
    token = ""
    config_path = BASE_DIR / "config.py"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ACCESS_TOKEN"):
                token = line + "\n"
                break
    except FileNotFoundError:
        pass

    if date_preset:
        date_part = f'DATE_PRESET = "{date_preset}"\nTIME_RANGE: dict = {{}}\n'
    else:
        date_part = f'DATE_PRESET = ""\nTIME_RANGE: dict = {json.dumps(time_range)}\n'
    config_path.write_text(token + date_part, encoding="utf-8")


# ── Widgets helpers ────────────────────────────────────────────────────────────

def _card(parent, title: str) -> tk.Frame:
    """Tạo card có tiêu đề section."""
    outer = tk.Frame(parent, bg=SURFACE, bd=1, relief="flat",
                     highlightbackground=BORDER, highlightthickness=1)
    outer.pack(fill="x", padx=20, pady=(0, 12))
    tk.Label(outer, text=title, bg=SURFACE, fg=MUTED,
             font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(10, 0))
    inner = tk.Frame(outer, bg=SURFACE)
    inner.pack(fill="x", padx=16, pady=(6, 14))
    return inner


def _radio(parent, text, var, value, command=None):
    return tk.Radiobutton(
        parent, text=text, variable=var, value=value, command=command,
        bg=SURFACE, fg=TEXT, activebackground=SURFACE, activeforeground=TEXT,
        selectcolor=BORDER, font=("Segoe UI", 10), cursor="hand2",
    )


def _check(parent, text, var):
    return tk.Checkbutton(
        parent, text=text, variable=var,
        bg=SURFACE, fg=TEXT, activebackground=SURFACE, activeforeground=TEXT,
        selectcolor=BORDER, font=("Segoe UI", 10), cursor="hand2",
    )


# ── Main app ───────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FB Ads Data Pipeline")
        self.configure(bg=BG)
        self.geometry("700x660")
        self.resizable(True, True)
        self.minsize(600, 520)

        ttk.Style(self).theme_use("clam")

        self._vars()
        self._build()

    # ── State vars ──────────────────────────────────────────────────────────

    def _vars(self):
        today = date.today()
        self.mode_var   = tk.StringVar(value="preset")
        self.preset_var = tk.StringVar(value="Tháng này")
        self.since_var  = tk.StringVar(value=today.replace(day=1).strftime("%Y-%m-%d"))
        self.until_var  = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        self.phase1_var = tk.BooleanVar(value=True)
        self.phase2_var = tk.BooleanVar(value=False)
        self._running   = False

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build(self):
        # ── Header ────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=20, pady=(20, 14))
        tk.Label(hdr, text="Facebook Ads Data Pipeline", bg=BG, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Chọn khoảng thời gian và script cần chạy",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # ── Card 1: Khoảng thời gian ──────────────────────────────────
        c1 = _card(self, "KHOẢNG THỜI GIAN")

        # Radio: preset vs custom
        row_mode = tk.Frame(c1, bg=SURFACE)
        row_mode.pack(fill="x", pady=(0, 10))
        _radio(row_mode, "Dùng preset", self.mode_var, "preset", self._toggle).pack(side="left")
        _radio(row_mode, "Tuỳ chỉnh ngày", self.mode_var, "custom", self._toggle).pack(
            side="left", padx=(28, 0))

        # Preset row
        self.row_preset = tk.Frame(c1, bg=SURFACE)
        self.row_preset.pack(fill="x", pady=(0, 4))
        tk.Label(self.row_preset, text="Preset:", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9), width=8, anchor="w").pack(side="left")

        style = ttk.Style()
        style.configure("Dark.TCombobox",
                        fieldbackground=BORDER, background=BORDER,
                        foreground=TEXT, selectbackground=ACCENT,
                        selectforeground="white", arrowcolor=MUTED)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BORDER)],
                  selectbackground=[("readonly", ACCENT)])

        self.preset_cb = ttk.Combobox(
            self.row_preset, textvariable=self.preset_var,
            values=PRESET_LABELS, state="readonly", width=24,
            style="Dark.TCombobox")
        self.preset_cb.pack(side="left", padx=(0, 0))

        # Custom row
        self.row_custom = tk.Frame(c1, bg=SURFACE)
        self.row_custom.pack(fill="x", pady=(0, 0))

        style.configure("Dark.TEntry",
                        fieldbackground=BORDER, foreground=TEXT,
                        insertbackground=TEXT)

        tk.Label(self.row_custom, text="Từ ngày:", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9), width=8, anchor="w").pack(side="left")
        self.since_e = ttk.Entry(self.row_custom, textvariable=self.since_var,
                                 width=13, style="Dark.TEntry")
        self.since_e.pack(side="left")

        tk.Label(self.row_custom, text="Đến ngày:", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(16, 0))
        self.until_e = ttk.Entry(self.row_custom, textvariable=self.until_var,
                                 width=13, style="Dark.TEntry")
        self.until_e.pack(side="left")

        tk.Label(self.row_custom, text="(YYYY-MM-DD)", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))

        self._toggle()  # set initial state

        # ── Card 2: Script ────────────────────────────────────────────
        c2 = _card(self, "SCRIPT CẦN CHẠY")

        _check(c2,
               "Phase 1 — get_campaigns.py   (danh sách campaign + metrics tháng)",
               self.phase1_var).pack(anchor="w", pady=3)
        _check(c2,
               "Phase 2 — get_details.py     (Adset / Ad / Creative chi tiết)",
               self.phase2_var).pack(anchor="w", pady=3)

        tk.Label(c2,
                 text="Phase 2 đọc cột \"Chọn Lấy Chi Tiết\" trong sheet để biết campaign nào cần mở rộng.",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 8),
                 wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))

        # ── Run button ────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 12))

        self.run_btn = tk.Button(
            btn_row, text="▶   Chạy ngay",
            bg=ACCENT, fg="white",
            activebackground="#3a7de8", activeforeground="white",
            font=("Segoe UI", 11, "bold"), relief="flat", bd=0,
            padx=28, pady=10, cursor="hand2",
            command=self._run)
        self.run_btn.pack(side="left")

        self.status_lbl = tk.Label(btn_row, text="", bg=BG, fg=GREEN,
                                   font=("Segoe UI", 10))
        self.status_lbl.pack(side="left", padx=(16, 0))

        # ── Console ───────────────────────────────────────────────────
        console_hdr = tk.Frame(self, bg=BG)
        console_hdr.pack(fill="x", padx=20)
        tk.Label(console_hdr, text="OUTPUT", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        self.console = scrolledtext.ScrolledText(
            self, bg=CODE_BG, fg=TEXT, insertbackground=TEXT,
            font=("Cascadia Code", 9), relief="flat", bd=0,
            wrap="word", state="disabled",
            highlightbackground=BORDER, highlightthickness=1)
        self.console.pack(fill="both", expand=True, padx=20, pady=(6, 20))

        self.console.tag_config("ok",    foreground=GREEN)
        self.console.tag_config("err",   foreground=RED)
        self.console.tag_config("warn",  foreground=YELLOW)
        self.console.tag_config("muted", foreground=MUTED)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _toggle(self):
        is_preset = self.mode_var.get() == "preset"
        self.preset_cb.configure(state="readonly" if is_preset else "disabled")
        state = "normal" if not is_preset else "disabled"
        self.since_e.configure(state=state)
        self.until_e.configure(state=state)

    def _validate_dates(self) -> tuple[str, dict | None] | None:
        """Trả về (date_preset, time_range) hoặc None nếu lỗi."""
        if self.mode_var.get() == "preset":
            return PRESET_MAP[self.preset_var.get()], None

        since = self.since_var.get().strip()
        until = self.until_var.get().strip()
        try:
            d_since = date.fromisoformat(since)
            d_until = date.fromisoformat(until)
        except ValueError:
            messagebox.showerror("Lỗi định dạng ngày",
                                 "Ngày phải theo định dạng YYYY-MM-DD.\nVí dụ: 2026-05-01")
            return None
        if d_since > d_until:
            messagebox.showerror("Lỗi khoảng ngày",
                                 "Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc.")
            return None
        return "", {"since": since, "until": until}

    def _run(self):
        if self._running:
            return

        if not self.phase1_var.get() and not self.phase2_var.get():
            messagebox.showwarning("Chưa chọn script",
                                   "Hãy chọn ít nhất Phase 1 hoặc Phase 2.")
            return

        result = self._validate_dates()
        if result is None:
            return
        date_preset, time_range = result

        write_config(date_preset, time_range)

        scripts = []
        if self.phase1_var.get():
            scripts.append("get_campaigns.py")
        if self.phase2_var.get():
            scripts.append("get_details.py")

        self._running = True
        self.run_btn.configure(state="disabled", text="⏳  Đang chạy...")
        self.status_lbl.configure(text="Đang chạy...", fg=GREEN)
        self._clear_console()

        if date_preset:
            label = next(k for k, v in PRESET_MAP.items() if v == date_preset)
            self._log(f"Khoảng thời gian : {label}  ({date_preset})\n", "muted")
        else:
            self._log(f"Khoảng thời gian : {time_range['since']}  →  {time_range['until']}\n", "muted")
        self._log(f"Script           : {', '.join(scripts)}\n\n", "muted")

        threading.Thread(target=self._run_scripts, args=(scripts,), daemon=True).start()

    def _run_scripts(self, scripts: list[str]):
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        all_ok = True
        for script in scripts:
            self._log(f"{'─' * 52}\n▶  {script}\n{'─' * 52}\n", "muted")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", str(BASE_DIR / script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(BASE_DIR),
                    env=env,
                )
                for line in proc.stdout:
                    self._log(line)
                proc.wait()
                if proc.returncode != 0:
                    self._log(f"\n✗  {script} thoát với lỗi (code {proc.returncode})\n", "err")
                    all_ok = False
                else:
                    self._log(f"\n✓  {script} hoàn thành\n", "ok")
            except Exception as exc:
                self._log(f"[Exception] {exc}\n", "err")
                all_ok = False

        self.after(0, self._done, all_ok)

    def _done(self, success: bool):
        self._running = False
        self.run_btn.configure(state="normal", text="▶   Chạy ngay")
        if success:
            self.status_lbl.configure(text="✓  Hoàn thành", fg=GREEN)
        else:
            self.status_lbl.configure(text="✗  Có lỗi — xem output bên dưới", fg=RED)

    def _log(self, text: str, tag: str = ""):
        self.console.configure(state="normal")
        self.console.insert("end", text, tag if tag else ())
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
