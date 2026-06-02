"""
Kiểm tra tính nhất quán của cột Spend (cột F) trong tab tài khoản quảng cáo.

Quy tắc:
  - Spend Campaign  = tổng Spend của tất cả Adset thuộc campaign đó.
  - Spend Adset     = tổng Spend của tất cả Ad thuộc adset đó.

Chạy:
  python check_spend.py                        # dùng SHEET_NAME mặc định
  python check_spend.py "Tên Tab Khác"         # truyền tên tab qua arg
"""

import sys
import io
import threading
import contextlib
from pathlib import Path
from google.oauth2.service_account import Credentials
import gspread

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except ImportError:
    tk = None  # Cho phép chạy chế độ CLI khi không có tkinter

BASE_DIR = Path(__file__).parent

SPREADSHEET_ID = "1zZ7H9lj_s4Dm1hTeMvrQtKLFeiOBb5rWu8h7QJ458PM"
DEFAULT_SHEET  = "Bs Hội 6"

TOLERANCE = 1.0  # sai lệch tối đa chấp nhận được (do làm tròn)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _connect(credentials_file: str = "service_account.json"):
    creds = Credentials.from_service_account_file(
        str(BASE_DIR / credentials_file), scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def _to_float(v) -> float:
    try:
        if isinstance(v, (int, float)):
            return float(v)
        v = str(v).replace(",", "").replace(".", "").replace(" ₫", "").strip()
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def check_spend(sheet_name: str = DEFAULT_SHEET, tolerance: float = TOLERANCE, ss=None):
    if ss is None:
        print(f"Kết nối và đọc tab '{sheet_name}'...")
        ss = _connect()
    else:
        print(f"Đọc tab '{sheet_name}'...")
    ws  = ss.worksheet(sheet_name)
    all_data = ws.get_all_values()

    if len(all_data) < 2:
        print("Sheet trống hoặc chỉ có header.")
        return

    header = all_data[0]
    try:
        col_cap      = header.index("Cấp")
        col_camp_id  = header.index("Campaign ID")
        col_name     = header.index("Tên")
        col_spend    = header.index("Spend Tháng Này")
    except ValueError as e:
        print(f"Thiếu cột: {e}  →  hãy chắc sheet đúng định dạng get_campaigns.")
        return

    # ── Parse tuần tự: Campaign → Adset → Ad ─────────────────────────────────
    campaigns: list[dict] = []
    cur_camp  = None
    cur_adset = None

    for row in all_data[1:]:
        cap   = row[col_cap].strip()   if col_cap   < len(row) else ""
        name  = row[col_name].strip()  if col_name  < len(row) else ""
        cid   = row[col_camp_id].strip() if col_camp_id < len(row) else ""
        spend = _to_float(row[col_spend] if col_spend < len(row) else "")

        if cap == "Campaign":
            cur_camp  = {"id": cid, "name": name, "spend": spend, "adsets": []}
            cur_adset = None
            campaigns.append(cur_camp)
        elif cap == "Adset" and cur_camp is not None:
            cur_adset = {"name": name, "spend": spend, "ads": []}
            cur_camp["adsets"].append(cur_adset)
        elif cap == "Ad" and cur_adset is not None:
            cur_adset["ads"].append({"name": name, "spend": spend})

    # ── So sánh ───────────────────────────────────────────────────────────────
    camp_errors:  list[dict] = []
    adset_errors: list[dict] = []

    for camp in campaigns:
        adset_total = sum(a["spend"] for a in camp["adsets"])
        if camp["adsets"] and abs(camp["spend"] - adset_total) > tolerance:
            camp_errors.append({
                "id":          camp["id"],
                "name":        camp["name"],
                "camp_spend":  camp["spend"],
                "adset_total": adset_total,
                "diff":        camp["spend"] - adset_total,
            })

        for adset in camp["adsets"]:
            ad_total = sum(a["spend"] for a in adset["ads"])
            if adset["ads"] and abs(adset["spend"] - ad_total) > tolerance:
                adset_errors.append({
                    "adset_name":  adset["name"],
                    "camp_name":   camp["name"],
                    "adset_spend": adset["spend"],
                    "ad_total":    ad_total,
                    "diff":        adset["spend"] - ad_total,
                })

    # ── In kết quả ────────────────────────────────────────────────────────────
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  Sheet: {sheet_name}   |   Tổng campaign đọc được: {len(campaigns)}")
    print(sep)

    # --- Campaign vs Adset ---
    if not camp_errors:
        print("✓ Tất cả Campaign: Spend Camp = tổng Spend Adset")
    else:
        print(f"✗ {len(camp_errors)} Campaign bị sai lệch:\n")
        for e in camp_errors:
            print(f"  [{e['id']}] {e['name']}")
            print(f"    Camp = {e['camp_spend']:>12,.2f}  |  "
                  f"Tổng Adset = {e['adset_total']:>12,.2f}  |  "
                  f"Chênh = {e['diff']:>+12,.2f}")

    print()

    # --- Adset vs Ad ---
    if not adset_errors:
        print("✓ Tất cả Adset: Spend Adset = tổng Spend Ad")
    else:
        print(f"✗ {len(adset_errors)} Adset bị sai lệch:\n")
        for e in adset_errors:
            print(f"  Adset : {e['adset_name']}")
            print(f"  Camp  : {e['camp_name']}")
            print(f"    Adset = {e['adset_spend']:>12,.2f}  |  "
                  f"Tổng Ad = {e['ad_total']:>12,.2f}  |  "
                  f"Chênh = {e['diff']:>+12,.2f}")

    print(f"\n{sep}")
    if not camp_errors and not adset_errors:
        print("✓ Toàn bộ dữ liệu nhất quán!")
    else:
        print(f"✗ Phát hiện {len(camp_errors)} lỗi Campaign  +  "
              f"{len(adset_errors)} lỗi Adset.")
    print(sep)


# ── Giao diện chọn Tab Sheet ────────────────────────────────────────────────

class App(tk.Tk):
    """Cho phép chọn 1 tab có sẵn trong Google Sheet rồi kiểm tra Spend.

    Tên tab đang hardcode (DEFAULT_SHEET) được điền sẵn làm giá trị mặc định.
    """

    BG        = "#eef2f6"
    CARD      = "#f8fafc"
    BORDER    = "#cbd5e1"
    ACCENT    = "#3b82f6"
    ACCENT_HV = "#2563eb"
    ACCENT_DIS = "#93c5fd"
    TEXT      = "#334155"
    MUTED     = "#64748b"

    def __init__(self):
        super().__init__()
        self.title("Kiểm Tra Spend – Chọn Tab Sheet")

        w, h = 760, 600
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(620, 460)
        self.configure(bg=self.BG)

        self._spreadsheet = None
        self._sheet_var = tk.StringVar(value=DEFAULT_SHEET)
        self._tol_var   = tk.StringVar(value=str(TOLERANCE))

        self._apply_styles()
        self._build_ui()
        threading.Thread(target=self._connect_worker, daemon=True).start()

    # ── Styles ──────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=self.BG)
        s.configure("TLabel", background=self.BG,
                    font=("Segoe UI", 10), foreground=self.TEXT)
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background=self.BORDER, foreground=self.TEXT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("TButton",
              background=[("active", "#cbd5e1"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(22, 9), background=self.ACCENT,
                    foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#ffffff")])
        s.configure("TCombobox", padding=6, font=("Segoe UI", 10))
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor=self.BORDER, borderwidth=0, thickness=6)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        # Header
        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 12))
        tk.Label(hdr, text="Kiểm Tra Spend", bg=self.BG,
                 font=("Segoe UI Semibold", 15), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        # Khối chọn tab
        form = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        def _row(r, label):
            tk.Label(form, text=label, bg=self.CARD, fg=self.TEXT,
                     font=("Segoe UI", 10)).grid(row=r, column=0, sticky="w",
                                                 padx=(14, 10), pady=10)

        _row(0, "Tab cần kiểm tra:")
        self._sheet_cb = ttk.Combobox(form, textvariable=self._sheet_var,
                                      state="disabled")
        self._sheet_cb.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=10)

        _row(1, "Tolerance:")
        tk.Entry(form, textvariable=self._tol_var, relief="flat",
                 font=("Segoe UI", 10), bg="#ffffff",
                 highlightthickness=1, highlightbackground=self.BORDER,
                 highlightcolor=self.ACCENT).grid(
                     row=1, column=1, sticky="w", padx=(0, 14), pady=(0, 12), ipady=4)

        # Khu vực kết quả
        tk.Label(outer, text="Kết quả:", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(fill="x", pady=(12, 4))
        self._output = scrolledtext.ScrolledText(
            outer, font=("Consolas", 9), bg=self.CARD, fg=self.TEXT,
            relief="flat", highlightthickness=1, highlightbackground=self.BORDER,
            wrap="none", state="disabled")
        self._output.pack(fill="both", expand=True)

        # Thanh dưới
        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(12, 0))

        ttk.Button(bot, text="Copy kết quả",
                   command=self._copy_output).pack(side="left")

        ttk.Button(bot, text="Đóng", command=self.destroy).pack(side="right")
        self._run_btn = ttk.Button(bot, text="Kiểm tra", style="Accent.TButton",
                                   command=self._run_check, state="disabled")
        self._run_btn.pack(side="right", padx=(0, 8))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=120)
        self._progress.pack(side="right", padx=(0, 10))

    # ── Kết nối + nạp danh sách tab ─────────────────────────────────────────────

    def _connect_worker(self):
        try:
            ss = _connect()
            titles = [ws.title for ws in ss.worksheets()]
            self._spreadsheet = ss
            self.after(0, lambda: self._on_connected(ss.title, titles))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi kết nối: {e}", error=True))

    def _on_connected(self, ss_title: str, titles: list):
        # Đảm bảo giá trị mặc định luôn có trong danh sách để chọn lại được
        values = list(titles)
        default = self._sheet_var.get()
        if default and default not in values:
            values.append(default)
        values.sort(key=str.lower)

        self._sheet_cb.configure(values=values, state="readonly")
        self._run_btn.configure(state="normal")
        self._set_status(f"Kết nối OK · {ss_title} · {len(titles)} tab")

    # ── Chạy kiểm tra ───────────────────────────────────────────────────────────

    def _run_check(self):
        sheet = self._sheet_var.get().strip()
        if not sheet:
            messagebox.showwarning("Thiếu lựa chọn", "Vui lòng chọn 1 tab.")
            return
        tol = _to_float(self._tol_var.get())

        self._run_btn.configure(state="disabled")
        self._progress.start(12)
        self._set_status("Đang kiểm tra...")
        threading.Thread(target=self._run_worker,
                         args=(sheet, tol), daemon=True).start()

    def _run_worker(self, sheet: str, tol: float):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                check_spend(sheet, tolerance=tol, ss=self._spreadsheet)
        except Exception as e:
            buf.write(f"\n✗ Lỗi: {e}\n")
        self.after(0, lambda: self._finish_run(buf.getvalue()))

    def _finish_run(self, text: str):
        self._progress.stop()
        self._set_output(text)
        self._run_btn.configure(state="normal")
        self._set_status("Hoàn tất.")

    # ── Tiện ích ────────────────────────────────────────────────────────────────

    def _set_output(self, text: str):
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", text)
        self._output.configure(state="disabled")

    def _copy_output(self):
        text = self._output.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._set_status("Đã copy kết quả.")

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(text=text,
                                   fg="#dc3545" if error else self.MUTED)


def launch_gui():
    if tk is None:
        sys.exit("Cần tkinter để mở giao diện (hoặc chạy với --cli).")
    App().mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--cli" in args or tk is None:
        cli_args = [a for a in args if a != "--cli"]
        tab = cli_args[0] if cli_args else DEFAULT_SHEET
        check_spend(tab)
    else:
        launch_gui()
