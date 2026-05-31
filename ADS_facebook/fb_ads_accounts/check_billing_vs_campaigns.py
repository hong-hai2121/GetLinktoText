"""
So sánh tên chiến dịch / nhóm quảng cáo giữa 2 tab:
  - "Bs Hội 6 (799251702964605) Chi tiết"  → cột Tên chiến dịch + Tên nhóm quảng cáo
  - "Bs Hội 6"                              → cột D "Tên"

In ra các tên có trong Chi tiết nhưng KHÔNG có trong Bs Hội 6.
"""

import sys
from pathlib import Path
from google.oauth2.service_account import Credentials
import gspread

BASE_DIR       = Path(__file__).parent
SPREADSHEET_ID = "1zZ7H9lj_s4Dm1hTeMvrQtKLFeiOBb5rWu8h7QJ458PM"

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


def run(detail_sheet: str = DETAIL_SHEET, campaign_sheet: str = CAMPAIGN_SHEET):
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

    # dict: tên → list[(txId, date)]
    detail_campaigns: dict[str, list] = {}

    for row in detail_data[1:]:
        camp = _norm(row[col_camp] if col_camp < len(row) else "")
        txid = _norm(row[col_txid] if col_txid >= 0 and col_txid < len(row) else "")
        date = _norm(row[col_date] if col_date >= 0 and col_date < len(row) else "")
        ref  = f"{txid} ({date})" if txid else date
        if camp:
            detail_campaigns.setdefault(camp, [])
            if ref and ref not in detail_campaigns[camp]:
                detail_campaigns[camp].append(ref)

    print(f"  → {len(detail_campaigns)} tên chiến dịch trong Chi tiết.")

    # ── Đọc tab Bs Hội 6 — cột D "Tên" ───────────────────────────────────────
    print(f"Đọc tab '{campaign_sheet}'...")
    ws_camp = ss.worksheet(campaign_sheet)
    camp_data = ws_camp.get_all_values()

    if len(camp_data) < 2:
        print("Tab Bs Hội 6 trống.")
        return

    camp_header = camp_data[0]
    try:
        col_ten = camp_header.index("Tên")
    except ValueError:
        print("Không tìm thấy cột 'Tên' trong tab Bs Hội 6.")
        return

    # Tập hợp tất cả tên trong cột D
    sheet_names: set[str] = set()
    for row in camp_data[1:]:
        ten = _norm(row[col_ten] if col_ten < len(row) else "")
        if ten:
            sheet_names.add(ten)

    print(f"  → {len(sheet_names)} tên trong cột D của Bs Hội 6.")

    # ── So sánh ───────────────────────────────────────────────────────────────
    missing_camps = {k: v for k, v in detail_campaigns.items() if k not in sheet_names}

    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  Tên chiến dịch có trong '{detail_sheet}'")
    print(f"  nhưng KHÔNG có trong cột D của '{campaign_sheet}'")
    print(sep)

    if not missing_camps:
        print("✓ Tất cả tên chiến dịch đều có trong Bs Hội 6.")
    else:
        print(f"\n✗ {len(missing_camps)} tên CHIẾN DỊCH bị thiếu trong '{campaign_sheet}':\n")
        for name, refs in sorted(missing_camps.items()):
            print(f"  - {name}")
            for r in refs:
                print(f"      → {r}")

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
                  tolerance: float = 1000.0):
    """So sánh tổng Số tiền phân bổ (Chi tiết) với Spend Tháng Này (Bs Hội 6) theo chiến dịch."""
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


    billing_by_camp: dict[str, float] = {}
    for row in detail_data[1:]:
        name   = _norm(row[col_camp_name] if col_camp_name < len(row) else "")
        amount = _to_float(row[col_amount] if col_amount < len(row) else "")
        if name:
            billing_by_camp[name] = billing_by_camp.get(name, 0.0) + amount

    print(f"  → {len(billing_by_camp)} chiến dịch trong Chi tiết.")

    # ── Đọc Bs Hội 6: lấy Spend của dòng Campaign ────────────────────────────
    print(f"Đọc tab '{campaign_sheet}'...")
    ws_camp = ss.worksheet(campaign_sheet)
    camp_data = ws_camp.get_all_values()

    if len(camp_data) < 2:
        print("Tab Bs Hội 6 trống."); return

    ch = camp_data[0]
    try:
        col_cap   = ch.index("Cấp")
        col_ten   = ch.index("Tên")
        col_spend = ch.index("Spend Tháng Này")
    except ValueError as e:
        print(f"Thiếu cột trong Bs Hội 6: {e}"); return

    spend_by_camp: dict[str, float] = {}
    for row in camp_data[1:]:
        cap   = _norm(row[col_cap]   if col_cap   < len(row) else "")
        name  = _norm(row[col_ten]   if col_ten   < len(row) else "")
        spend = _to_float(row[col_spend] if col_spend < len(row) else "")
        if cap == "Campaign" and name:
            spend_by_camp[name] = spend_by_camp.get(name, 0.0) + spend

    print(f"  → {len(spend_by_camp)} chiến dịch trong Bs Hội 6.")

    # ── So sánh ───────────────────────────────────────────────────────────────
    all_names = sorted(set(billing_by_camp) | set(spend_by_camp))

    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  So sánh Spend: Chi tiết (Số tiền phân bổ) vs Bs Hội 6 (Spend Tháng Này)")
    print(f"  Tolerance: {tolerance:,.0f} ₫")
    print(sep)
    print(f"  {'Tên chiến dịch':<40} {'Chi tiết':>14} {'Bs Hội 6':>14} {'Chênh':>12}")
    print(f"  {'-'*40} {'-'*14} {'-'*14} {'-'*12}")

    match_count = 0
    diff_rows = []
    only_in_billing = []
    only_in_sheet   = []

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
            short = name[:38] + ".." if len(name) > 40 else name
            print(f"  {short:<40} {b:>14,.0f} {s:>14,.0f} {diff:>+12,.0f}{flag}")

    print(f"\n  Khớp (≤{tolerance:,.0f}): {match_count}  |  Lệch: {len(diff_rows)}  |  "
          f"Chỉ có trong Chi tiết: {len(only_in_billing)}  |  Chỉ có trong Bs Hội 6: {len(only_in_sheet)}")

    if only_in_billing:
        print(f"\n  Chỉ có trong CHI TIẾT (không có trong Bs Hội 6):")
        for name, amt in only_in_billing:
            print(f"    - {name}  ({amt:,.0f} ₫)")

    if only_in_sheet:
        print(f"\n  Chỉ có trong BS HỘI 6 (không có trong Chi tiết):")
        for name, amt in only_in_sheet:
            print(f"    - {name}  ({amt:,.0f} ₫)")

    print(f"\n  Ghi chú:")
    print(f"  (+) Chi tiết > Bs Hội 6 : tiền đã thu (billing) NHIỀU HƠN tiền đã tiêu")
    print(f"  (-) Chi tiết < Bs Hội 6 : tiền đã tiêu NHIỀU HƠN tiền đã thu (Facebook chưa thu hết)")
    print(sep)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else DETAIL_SHEET
    c = sys.argv[2] if len(sys.argv) > 2 else CAMPAIGN_SHEET
    run(d, c)
    print()
    compare_spend(d, c)
