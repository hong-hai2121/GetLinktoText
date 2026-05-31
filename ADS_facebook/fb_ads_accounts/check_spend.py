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
from pathlib import Path
from google.oauth2.service_account import Credentials
import gspread

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


def check_spend(sheet_name: str = DEFAULT_SHEET):
    print(f"Kết nối và đọc tab '{sheet_name}'...")
    ss  = _connect()
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
        if camp["adsets"] and abs(camp["spend"] - adset_total) > TOLERANCE:
            camp_errors.append({
                "id":          camp["id"],
                "name":        camp["name"],
                "camp_spend":  camp["spend"],
                "adset_total": adset_total,
                "diff":        camp["spend"] - adset_total,
            })

        for adset in camp["adsets"]:
            ad_total = sum(a["spend"] for a in adset["ads"])
            if adset["ads"] and abs(adset["spend"] - ad_total) > TOLERANCE:
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


if __name__ == "__main__":
    tab = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SHEET
    check_spend(tab)
