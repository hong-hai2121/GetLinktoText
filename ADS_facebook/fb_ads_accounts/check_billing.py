"""
Kiểm tra tính nhất quán của bảng giao dịch thanh toán Facebook Ads.

Quy tắc:
  - Nhóm các dòng theo "ID giao dịch" (cột A).
  - Cột E "Tổng tiền giao dịch": tất cả dòng trong nhóm có cùng giá trị
    (lấy dòng đầu làm chuẩn).
  - Cột F "Số tiền phân bổ": tổng các dòng trong nhóm phải bằng cột E.

Chạy:
  python check_billing.py                   # dùng SHEET_NAME mặc định
  python check_billing.py "Tên Tab Khác"   # truyền tên tab qua arg
  python check_billing.py --cli            # chế độ dòng lệnh
"""

import sys
import io
import threading
import contextlib
from collections import defaultdict
from pathlib import Path
from google.oauth2.service_account import Credentials
import gspread

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except ImportError:
    tk = None

BASE_DIR = Path(__file__).parent

from config import SPREADSHEET_ID
DEFAULT_SHEET  = "Billing"

TOLERANCE = 1.0  # sai lệch tối đa chấp nhận được (do làm tròn)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

EXPECTED_COLS = [
    "ID giao dịch",
    "Tổng tiền giao dịch",
    "Số tiền phân bổ",
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
        v = str(v).replace(",", "").replace(".", "").replace(" ₫", "").replace("₫", "").strip()
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def check_billing(sheet_name: str = DEFAULT_SHEET, tolerance: float = TOLERANCE, ss=None):
    if ss is None:
        print(f"Kết nối và đọc tab '{sheet_name}'...")
        ss = _connect()
    else:
        print(f"Đọc tab '{sheet_name}'...")

    ws = ss.worksheet(sheet_name)
    all_data = ws.get_all_values()

    if len(all_data) < 2:
        print("Sheet trống hoặc chỉ có header.")
        return

    header = all_data[0]
    try:
        col_id       = header.index("ID giao dịch")
        col_tong     = header.index("Tổng tiền giao dịch")
        col_phan_bo  = header.index("Số tiền phân bổ")
    except ValueError as e:
        print(f"Thiếu cột: {e}  →  hãy chắc sheet đúng định dạng.")
        missing = [c for c in EXPECTED_COLS if c not in header]
        if missing:
            print(f"  Các cột chưa tìm thấy: {missing}")
        return

    # Thêm các cột thông tin phụ nếu có (để hiển thị trong báo cáo lỗi)
    col_ngay     = header.index("Ngày thanh toán")  if "Ngày thanh toán"  in header else None
    col_tk       = header.index("Tài khoản quảng cáo") if "Tài khoản quảng cáo" in header else None
    col_chien    = header.index("Tên chiến dịch")   if "Tên chiến dịch"   in header else None

    def _get(row, idx):
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    # ── Nhóm dòng theo ID giao dịch ──────────────────────────────────────────
    # groups[id] = {"tong": float, "phan_bo": [float, ...], "meta": {...}}
    groups: dict[str, dict] = {}
    order: list[str] = []  # giữ thứ tự xuất hiện

    for row_num, row in enumerate(all_data[1:], start=2):
        gd_id = _get(row, col_id)
        if not gd_id:
            continue

        tong    = _to_float(_get(row, col_tong))
        phan_bo = _to_float(_get(row, col_phan_bo))

        if gd_id not in groups:
            groups[gd_id] = {
                "tong":     tong,
                "phan_bo":  [],
                "rows":     [],
                "ngay":     _get(row, col_ngay)  if col_ngay  is not None else "",
                "tk":       _get(row, col_tk)    if col_tk    is not None else "",
            }
            order.append(gd_id)
        else:
            # Nếu cùng nhóm mà giá trị E khác nhau → ghi nhận bất thường
            if tong and abs(groups[gd_id]["tong"] - tong) > tolerance:
                groups[gd_id]["tong_conflict"] = True

        groups[gd_id]["phan_bo"].append(phan_bo)
        groups[gd_id]["rows"].append(row_num)

        # Thu thập tên chiến dịch để hiển thị
        if col_chien is not None:
            chien = _get(row, col_chien)
            if chien and "chien_dich" not in groups[gd_id]:
                groups[gd_id]["chien_dich"] = chien

    # ── So sánh ───────────────────────────────────────────────────────────────
    errors:   list[dict] = []
    warnings: list[dict] = []

    for gd_id in order:
        g = groups[gd_id]
        tong    = g["tong"]
        sum_pb  = sum(g["phan_bo"])

        if g.get("tong_conflict"):
            warnings.append({
                "id":   gd_id,
                "ngay": g["ngay"],
                "msg":  "Cột E (Tổng tiền giao dịch) có nhiều giá trị khác nhau trong cùng nhóm",
                "rows": g["rows"],
            })

        if abs(tong - sum_pb) > tolerance:
            errors.append({
                "id":       gd_id,
                "ngay":     g["ngay"],
                "tk":       g["tk"],
                "chien":    g.get("chien_dich", ""),
                "tong":     tong,
                "sum_pb":   sum_pb,
                "diff":     tong - sum_pb,
                "n_dong":   len(g["phan_bo"]),
                "rows":     g["rows"],
            })

    # ── In kết quả ────────────────────────────────────────────────────────────
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  Sheet: {sheet_name}   |   Tổng ID giao dịch: {len(groups)}")
    print(sep)

    if warnings:
        print(f"\n⚠  {len(warnings)} cảnh báo (E có giá trị khác nhau trong cùng nhóm):\n")
        for w in warnings:
            print(f"  ID: {w['id']}   Ngày: {w['ngay']}   Dòng: {w['rows']}")
            print(f"    → {w['msg']}")

    print()

    if not errors:
        print("✓ Tất cả ID giao dịch: tổng Số tiền phân bổ = Tổng tiền giao dịch")
    else:
        print(f"✗ {len(errors)} ID giao dịch bị sai lệch:\n")
        for e in errors:
            print(f"  ID giao dịch : {e['id']}")
            if e["ngay"]:
                print(f"  Ngày         : {e['ngay']}")
            if e["tk"]:
                print(f"  Tài khoản    : {e['tk']}")
            if e["chien"]:
                print(f"  Chiến dịch   : {e['chien']}")
            print(f"  Số dòng      : {e['n_dong']}   (hàng {e['rows']})")
            print(f"    Tổng GD (E) = {e['tong']:>14,.0f}"
                  f"  |  Tổng PB (F) = {e['sum_pb']:>14,.0f}"
                  f"  |  Chênh = {e['diff']:>+12,.0f}")
            print()

    print(sep)
    if not errors and not warnings:
        print("✓ Toàn bộ dữ liệu nhất quán!")
    else:
        print(f"✗ Phát hiện {len(errors)} sai lệch  +  {len(warnings)} cảnh báo.")
    print(sep)


# ── Giao diện ────────────────────────────────────────────────────────────────

class App(tk.Tk):
    BG         = "#eef2f6"
    CARD       = "#f8fafc"
    BORDER     = "#cbd5e1"
    ACCENT     = "#3b82f6"
    ACCENT_HV  = "#2563eb"
    ACCENT_DIS = "#93c5fd"
    TEXT       = "#334155"
    MUTED      = "#64748b"

    def __init__(self):
        super().__init__()
        self.title("Kiểm Tra Giao Dịch – Chọn Tab Sheet")

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

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 12))
        tk.Label(hdr, text="Kiểm Tra Giao Dịch", bg=self.BG,
                 font=("Segoe UI Semibold", 15), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        tk.Label(outer,
                 text="Kiểm tra: tổng 'Số tiền phân bổ' (F) của từng ID giao dịch = 'Tổng tiền giao dịch' (E).",
                 bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

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

        tk.Label(outer, text="Kết quả:", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(fill="x", pady=(12, 4))
        self._output = scrolledtext.ScrolledText(
            outer, font=("Consolas", 9), bg=self.CARD, fg=self.TEXT,
            relief="flat", highlightthickness=1, highlightbackground=self.BORDER,
            wrap="none", state="disabled")
        self._output.pack(fill="both", expand=True)

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

    def _connect_worker(self):
        try:
            ss = _connect()
            titles = [ws.title for ws in ss.worksheets()]
            self._spreadsheet = ss
            self.after(0, lambda: self._on_connected(ss.title, titles))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi kết nối: {e}", error=True))

    def _on_connected(self, ss_title: str, titles: list):
        values = list(titles)
        default = self._sheet_var.get()
        if default and default not in values:
            values.append(default)
        values.sort(key=str.lower)
        self._sheet_cb.configure(values=values, state="readonly")
        self._run_btn.configure(state="normal")
        self._set_status(f"Kết nối OK · {ss_title} · {len(titles)} tab")

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
                check_billing(sheet, tolerance=tol, ss=self._spreadsheet)
        except Exception as e:
            buf.write(f"\n✗ Lỗi: {e}\n")
        self.after(0, lambda: self._finish_run(buf.getvalue()))

    def _finish_run(self, text: str):
        self._progress.stop()
        self._set_output(text)
        self._run_btn.configure(state="normal")
        self._set_status("Hoàn tất.")

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
        check_billing(tab)
    else:
        launch_gui()
