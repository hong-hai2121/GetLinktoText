"""
So sánh tên chiến dịch / nhóm quảng cáo giữa 2 tab:
  - "Bs Hội 6 (799251702964605) Chi tiết"  → cột Tên chiến dịch + Tên nhóm quảng cáo
  - "Bs Hội 6"                              → cột D "Tên"

In ra các tên có trong Chi tiết nhưng KHÔNG có trong Bs Hội 6.
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

BASE_DIR       = Path(__file__).parent
from config import SPREADSHEET_ID

DETAIL_SHEET   = "Bs Hội 6 (799251702964605) Chi tiết"
CAMPAIGN_SHEET = "Bs Hội 6"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _connect():
    creds = Credentials.from_service_account_file(
        str(BASE_DIR / "service_account.json"), scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def _norm(s: str) -> str:
    return " ".join(s.split())


def run(detail_sheet: str = DETAIL_SHEET, campaign_sheet: str = CAMPAIGN_SHEET, ss=None):
    if ss is None:
        print(f"Kết nối Google Sheets...")
        ss = _connect()

    # ── Đọc tab Chi tiết ──────────────────────────────────────────────────────
    print(f"Đọc tab '{detail_sheet}'...")
    ws_detail = ss.worksheet(detail_sheet)
    detail_data = ws_detail.get_all_values()

    if len(detail_data) < 2:
        print("Tab Chi tiết trống.")
        return

    detail_header = detail_data[0]
    try:
        col_camp = detail_header.index("Tên chiến dịch")
    except ValueError as e:
        print(f"Thiếu cột trong tab Chi tiết: {e}")
        return

    # Lấy thêm cột ID giao dịch và Ngày thanh toán để log chi tiết
    try:
        col_txid = detail_header.index("ID giao dịch")
        col_date = detail_header.index("Ngày thanh toán")
    except ValueError:
        col_txid = col_date = -1

    # Cột F "Số tiền phân bổ" — dòng có tên nhưng TRỐNG cột này là giao dịch tổng, bỏ qua
    try:
        col_amount = detail_header.index("Số tiền phân bổ")
    except ValueError:
        col_amount = -1

    # dict: tên → list[(txId, date)]
    detail_campaigns: dict[str, list] = {}
    # dict: tên → tổng Số tiền phân bổ (cột F)
    billing_by_camp: dict[str, float] = {}

    skipped_total = 0
    for row in detail_data[1:]:
        camp = _norm(row[col_camp] if col_camp < len(row) else "")
        if not camp:
            continue
        # Bỏ qua dòng giao dịch tổng: có tên nhưng KHÔNG có Số tiền phân bổ (cột F)
        amount_raw = (row[col_amount] if 0 <= col_amount < len(row) else "").strip()
        if col_amount >= 0 and not amount_raw:
            skipped_total += 1
            continue
        billing_by_camp[camp] = billing_by_camp.get(camp, 0.0) + _to_float(amount_raw)
        txid = _norm(row[col_txid] if col_txid >= 0 and col_txid < len(row) else "")
        date = _norm(row[col_date] if col_date >= 0 and col_date < len(row) else "")
        ref  = f"{txid} ({date})" if txid else date
        detail_campaigns.setdefault(camp, [])
        if ref and ref not in detail_campaigns[camp]:
            detail_campaigns[camp].append(ref)

    if skipped_total:
        print(f"  → Bỏ qua {skipped_total} dòng giao dịch tổng (tên có nhưng trống Số tiền phân bổ ở cột F).")
    print(f"  → {len(detail_campaigns)} tên chiến dịch trong Chi tiết.")

    # ── Đọc tab Bs Hội 6 — cột D "Tên" ───────────────────────────────────────
    print(f"Đọc tab '{campaign_sheet}'...")
    ws_camp = ss.worksheet(campaign_sheet)
    camp_data = ws_camp.get_all_values()

    if len(camp_data) < 2:
        print(f"Tab '{campaign_sheet}' trống.")
        return

    camp_header = camp_data[0]
    try:
        col_ten = camp_header.index("Tên")
    except ValueError:
        print(f"Không tìm thấy cột 'Tên' trong tab '{campaign_sheet}'.")
        return

    # Tập hợp tất cả tên trong cột D
    sheet_names: set[str] = set()
    for row in camp_data[1:]:
        ten = _norm(row[col_ten] if col_ten < len(row) else "")
        if ten:
            sheet_names.add(ten)

    print(f"  → {len(sheet_names)} tên trong cột D của '{campaign_sheet}'.")

    # ── So sánh ───────────────────────────────────────────────────────────────
    missing_camps = {k: v for k, v in detail_campaigns.items() if k not in sheet_names}

    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  Tên chiến dịch có trong '{detail_sheet}'")
    print(f"  nhưng KHÔNG có trong cột D của '{campaign_sheet}'")
    print(sep)

    if not missing_camps:
        print(f"✓ Tất cả tên chiến dịch đều có trong '{campaign_sheet}'.")
    else:
        print(f"\n✗ {len(missing_camps)} tên CHIẾN DỊCH bị thiếu trong '{campaign_sheet}':\n")
        for name, refs in sorted(missing_camps.items()):
            print(f"  - {name}  ({billing_by_camp.get(name, 0.0):,.0f} ₫)")
            for r in refs:
                print(f"      → {r}")
        total_missing = sum(billing_by_camp.get(n, 0.0) for n in missing_camps)
        print(f"\n  ⮕ Tổng Số tiền phân bổ của {len(missing_camps)} tên không tìm thấy "
              f"trong '{campaign_sheet}': {total_missing:,.0f} ₫")

    print(f"\n{sep}")
    print("✓ Toàn bộ tên đều khớp!" if not missing_camps else f"✗ {len(missing_camps)} chiến dịch bị thiếu.")
    print(sep)


def _to_float(v) -> float:
    """Parse số tiền từ chuỗi hoặc số — xử lý cả định dạng VN (dấu chấm = nghìn)."""
    import re
    try:
        if isinstance(v, (int, float)):
            return float(v)
        # Xóa ký hiệu tiền tệ (₫, đ, Đ), dấu +, khoảng trắng
        s = re.sub(r'[₫đĐ+\s]', '', str(v or '')).strip()
        if not s:
            return 0.0
        if "," in s and "." in s:
            # Kiểu US: "1,234.56" → bỏ dấu phẩy
            s = s.replace(",", "")
        elif "," in s:
            parts = s.split(",")
            # Dấu phẩy thập phân: "1234,56" → "1234.56"
            s = s.replace(",", "") if len(parts[-1]) != 2 else s.replace(",", ".")
        elif "." in s:
            # Dấu chấm VN nghìn phân cách: "1.927.836" → "1927836"
            parts = s.split(".")
            if all(len(p) == 3 for p in parts[1:]):
                s = s.replace(".", "")
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def compare_spend(detail_sheet: str = DETAIL_SHEET, campaign_sheet: str = CAMPAIGN_SHEET,
                  tolerance: float = 1000.0, ss=None):
    """So sánh tổng Số tiền phân bổ (Chi tiết) với Spend Tháng Này (Bs Hội 6) theo chiến dịch."""
    if ss is None:
        print("Kết nối Google Sheets...")
        ss = _connect()

    # ── Đọc Chi tiết: cộng Số tiền phân bổ theo Tên chiến dịch ──────────────
    print(f"Đọc tab '{detail_sheet}'...")
    ws_detail = ss.worksheet(detail_sheet)
    detail_data = ws_detail.get_all_values()

    if len(detail_data) < 2:
        print("Tab Chi tiết trống."); return

    dh = detail_data[0]
    try:
        col_camp_name = dh.index("Tên chiến dịch")
        col_amount    = dh.index("Số tiền phân bổ")
    except ValueError as e:
        print(f"Thiếu cột trong Chi tiết: {e}"); return

    # Cột "Tổng tiền giao dịch" — để cộng tiền của các dòng giao dịch tổng bị bỏ qua
    try:
        col_txn_total = dh.index("Tổng tiền giao dịch")
    except ValueError:
        col_txn_total = -1

    billing_by_camp: dict[str, float] = {}
    skipped_total = 0
    skipped_txn_amount = 0.0
    for row in detail_data[1:]:
        name = _norm(row[col_camp_name] if col_camp_name < len(row) else "")
        if not name:
            continue
        # Bỏ qua dòng giao dịch tổng: có tên nhưng KHÔNG có Số tiền phân bổ (cột F)
        amount_raw = (row[col_amount] if col_amount < len(row) else "").strip()
        if not amount_raw:
            skipped_total += 1
            if 0 <= col_txn_total < len(row):
                skipped_txn_amount += _to_float(row[col_txn_total])
            continue
        billing_by_camp[name] = billing_by_camp.get(name, 0.0) + _to_float(amount_raw)

    if skipped_total:
        print(f"  → Bỏ qua {skipped_total} dòng giao dịch tổng (tên có nhưng trống Số tiền phân bổ ở cột F).")
    print(f"  → {len(billing_by_camp)} chiến dịch trong Chi tiết.")

    # ── Đọc Bs Hội 6: lấy Spend của dòng Campaign ────────────────────────────
    print(f"Đọc tab '{campaign_sheet}'...")
    ws_camp = ss.worksheet(campaign_sheet)
    camp_data = ws_camp.get_all_values()

    if len(camp_data) < 2:
        print(f"Tab '{campaign_sheet}' trống."); return

    ch = camp_data[0]
    try:
        col_cap   = ch.index("Cấp")
        col_ten   = ch.index("Tên")
        col_spend = ch.index("Spend Tháng Này")
    except ValueError as e:
        print(f"Thiếu cột trong '{campaign_sheet}': {e}"); return

    spend_by_camp: dict[str, float] = {}
    for row in camp_data[1:]:
        cap   = _norm(row[col_cap]   if col_cap   < len(row) else "")
        name  = _norm(row[col_ten]   if col_ten   < len(row) else "")
        spend = _to_float(row[col_spend] if col_spend < len(row) else "")
        if cap == "Campaign" and name:
            spend_by_camp[name] = spend_by_camp.get(name, 0.0) + spend

    print(f"  → {len(spend_by_camp)} chiến dịch trong '{campaign_sheet}'.")

    # ── So sánh ───────────────────────────────────────────────────────────────
    all_names = sorted(set(billing_by_camp) | set(spend_by_camp))

    sep = "=" * 72
    # Canh chiều rộng cột "Tên chiến dịch" theo tên DÀI NHẤT để in ĐẦY ĐỦ, không cắt "..".
    label_skip = f"GIAO DỊCH TỔNG đã bỏ qua ({skipped_total})"
    name_w = max([len("Tên chiến dịch"), len("TỔNG CỘNG"), len(label_skip)]
                 + [len(n) for n in all_names])
    VW = 16  # chiều rộng cột số
    print(f"\n{sep}")
    print(f"  So sánh Spend giữa 2 tab (tên tab đầy đủ):")
    print(f"    • Cột 'Số tiền PB' = '{detail_sheet}'")
    print(f"    • Cột 'Spend'      = '{campaign_sheet}'")
    print(f"  Tolerance: {tolerance:,.0f} ₫")
    print(sep)
    print(f"  {'Tên chiến dịch':<{name_w}} {'Số tiền PB':>{VW}} {'Spend':>{VW}} {'Chênh':>14}")
    print(f"  {'-'*name_w} {'-'*VW} {'-'*VW} {'-'*14}")

    match_count = 0
    diff_rows = []
    only_in_billing = []
    only_in_sheet   = []
    total_b = total_s = 0.0

    for name in all_names:
        b = billing_by_camp.get(name)
        s = spend_by_camp.get(name)

        if b is None:
            only_in_sheet.append((name, s))
        elif s is None:
            only_in_billing.append((name, b))
        else:
            diff = b - s
            flag = "" if abs(diff) <= tolerance else " ✗"
            if abs(diff) <= tolerance:
                match_count += 1
            else:
                diff_rows.append((name, b, s, diff))
            total_b += b
            total_s += s
            print(f"  {name:<{name_w}} {b:>{VW},.0f} {s:>{VW},.0f} {diff:>+14,.0f}{flag}")

    # ── Hàng tổng cộng cuối bảng ────────────────────────────────────────────────
    print(f"  {'-'*name_w} {'-'*VW} {'-'*VW} {'-'*14}")
    print(f"  {'TỔNG CỘNG':<{name_w}} {total_b:>{VW},.0f} {total_s:>{VW},.0f} {total_b - total_s:>+14,.0f}")
    # Hàng tổng tiền của các giao dịch tổng (trống Số tiền phân bổ) đã bỏ qua phía trên
    print(f"  {label_skip:<{name_w}} {skipped_txn_amount:>{VW},.0f} {'':>{VW}} {'':>14}")

    print(f"\n  Khớp (≤{tolerance:,.0f}): {match_count}  |  Lệch: {len(diff_rows)}  |  "
          f"Chỉ có trong '{detail_sheet}': {len(only_in_billing)}  |  "
          f"Chỉ có trong '{campaign_sheet}': {len(only_in_sheet)}")

    if only_in_billing:
        print(f"\n  Chỉ có trong '{detail_sheet}' (không có trong '{campaign_sheet}'):")
        for name, amt in only_in_billing:
            print(f"    - {name}  ({amt:,.0f} ₫)")
        total_only_billing = sum(amt for _, amt in only_in_billing)
        print(f"  ⮕ Tổng Số tiền phân bổ của {len(only_in_billing)} tên không tìm thấy "
              f"trong '{campaign_sheet}': {total_only_billing:,.0f} ₫")

    if only_in_sheet:
        print(f"\n  Chỉ có trong '{campaign_sheet}' (không có trong '{detail_sheet}'):")
        for name, amt in only_in_sheet:
            print(f"    - {name}  ({amt:,.0f} ₫)")

    print(f"\n  Ghi chú:")
    print(f"  (+) Số tiền phân bổ > Spend : tiền đã thu (billing) NHIỀU HƠN tiền đã tiêu")
    print(f"  (-) Số tiền phân bổ < Spend : tiền đã tiêu NHIỀU HƠN tiền đã thu (Facebook chưa thu hết)")
    print(sep)


# ── Giao diện chọn Tab Sheet ────────────────────────────────────────────────

class App(tk.Tk):
    """Cho phép chọn 2 tab có sẵn trong Google Sheet rồi chạy so sánh.

    Hai tên tab đang hardcode (DETAIL_SHEET / CAMPAIGN_SHEET) được điền sẵn
    làm giá trị mặc định.
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
        self.title("So Sánh Billing vs Chiến Dịch – Chọn Tab Sheet")

        w, h = 760, 600
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(620, 460)
        self.configure(bg=self.BG)

        self._spreadsheet = None
        self._detail_var   = tk.StringVar(value=DETAIL_SHEET)
        self._campaign_var = tk.StringVar(value=CAMPAIGN_SHEET)
        self._tol_var      = tk.StringVar(value="1000")

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
        tk.Label(hdr, text="So Sánh Billing vs Chiến Dịch", bg=self.BG,
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

        _row(0, "Tab Chi tiết:")
        self._detail_cb = ttk.Combobox(form, textvariable=self._detail_var,
                                       state="disabled")
        self._detail_cb.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=10)

        _row(1, "Tab Bs Hội 6:")
        self._campaign_cb = ttk.Combobox(form, textvariable=self._campaign_var,
                                         state="disabled")
        self._campaign_cb.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=10)

        _row(2, "Tolerance (₫):")
        tk.Entry(form, textvariable=self._tol_var, relief="flat",
                 font=("Segoe UI", 10), bg="#ffffff",
                 highlightthickness=1, highlightbackground=self.BORDER,
                 highlightcolor=self.ACCENT).grid(
                     row=2, column=1, sticky="w", padx=(0, 14), pady=(0, 12), ipady=4)

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
        self._run_btn = ttk.Button(bot, text="Chạy so sánh", style="Accent.TButton",
                                   command=self._run_compare, state="disabled")
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

    def _on_connected(self, ss_title: str, titles: list[str]):
        # Đảm bảo 2 giá trị mặc định luôn có trong danh sách để chọn lại được
        values = list(titles)
        for default in (self._detail_var.get(), self._campaign_var.get()):
            if default and default not in values:
                values.append(default)
        values.sort(key=str.lower)

        self._detail_cb.configure(values=values, state="readonly")
        self._campaign_cb.configure(values=values, state="readonly")
        self._run_btn.configure(state="normal")
        self._set_status(f"Kết nối OK · {ss_title} · {len(titles)} tab")

    # ── Chạy so sánh ────────────────────────────────────────────────────────────

    def _run_compare(self):
        detail   = self._detail_var.get().strip()
        campaign = self._campaign_var.get().strip()
        if not detail or not campaign:
            messagebox.showwarning("Thiếu lựa chọn", "Vui lòng chọn đủ 2 tab.")
            return
        try:
            tol = _to_float(self._tol_var.get())
        except Exception:
            tol = 1000.0

        self._run_btn.configure(state="disabled")
        self._progress.start(12)
        self._set_status("Đang chạy...")
        threading.Thread(target=self._run_worker,
                         args=(detail, campaign, tol), daemon=True).start()

    def _run_worker(self, detail: str, campaign: str, tol: float):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                run(detail, campaign, ss=self._spreadsheet)
                print()
                compare_spend(detail, campaign, tolerance=tol, ss=self._spreadsheet)
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
        d = cli_args[0] if len(cli_args) > 0 else DETAIL_SHEET
        c = cli_args[1] if len(cli_args) > 1 else CAMPAIGN_SHEET
        run(d, c)
        print()
        compare_spend(d, c)
    else:
        launch_gui()
