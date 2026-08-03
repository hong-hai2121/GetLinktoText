"""
check_activity.py — Tô màu hàng ở sheet "TKQC API" theo việc tài khoản CÓ / KHÔNG
có hoạt động, dựa vào tab campaign của chính tài khoản đó (kết quả của Phase 1).

Tiêu chí (chốt với user): tab của tài khoản phải có NHIỀU HƠN 1 hàng — hàng 1 là
hàng tiêu đề (Chọn Lấy Chi Tiết / Cấp / Campaign ID / Tên / ...), nên từ hàng 2
trở đi mới là dữ liệu thật. Không có tab, tab rỗng, hoặc chỉ có mỗi hàng tiêu đề
đều tính là KHÔNG hoạt động.

Kết quả:
  • CÓ hoạt động   → cả hàng nền XANH nhạt
  • KHÔNG hoạt động → cả hàng nền ĐỎ nhạt

Chạy:
    python check_activity.py              # in kết quả rồi tô màu
    python check_activity.py --dry-run    # chỉ in, KHÔNG đụng vào sheet

Lưu ý: main.py (Cập nhật TKQC) cũng tô màu hàng theo cột "Chọn Lấy Camp", nên
chạy lại main.py sẽ ghi đè màu này — chạy lại check_activity.py để tô lại.
"""

import sys
from pathlib import Path

from get_campaigns import (
    AD_ACCOUNTS_SHEET,
    col_to_letter,
    connect_spreadsheet,
    sanitize_sheet_name,
)

BASE_DIR = Path(__file__).parent

# Cột trong tab tài khoản (theo HEADERS của get_campaigns.py)
CAMP_LEVEL_COL = 1   # B – "Cấp"
CAMP_SPEND_COL = 5   # F – "Spend Tháng Này"

COLOR_ACTIVE   = {"red": 0.80, "green": 0.94, "blue": 0.80}  # xanh nhạt
COLOR_INACTIVE = {"red": 0.99, "green": 0.82, "blue": 0.82}  # đỏ nhạt


def _quote(title: str) -> str:
    """Bọc tên tab cho A1 notation (nháy đơn trong tên phải nhân đôi)."""
    return "'" + title.replace("'", "''") + "'"


def _to_number(raw) -> float:
    """Đọc số tiền kiểu '12.450.000 ₫', '12,450,000', 12450000 → float."""
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip()
    if not text:
        return 0.0
    keep = "".join(c for c in text if c.isdigit() or c in ".,-")
    if not keep:
        return 0.0
    # Dấu phân cách cuối cùng: nếu sau nó có đúng 1-2 chữ số thì là dấu thập phân,
    # còn lại (3 chữ số) là dấu phân cách hàng nghìn.
    last_sep = max(keep.rfind("."), keep.rfind(","))
    if last_sep >= 0 and len(keep) - last_sep - 1 in (1, 2):
        keep = keep[:last_sep].replace(".", "").replace(",", "") + "." + keep[last_sep + 1:]
    else:
        keep = keep.replace(".", "").replace(",", "")
    try:
        return float(keep)
    except ValueError:
        return 0.0


def read_accounts(spreadsheet) -> tuple[list[dict], int]:
    """Đọc sheet TKQC API → list {row, id, name} + số cột của hàng tiêu đề."""
    ws = spreadsheet.worksheet(AD_ACCOUNTS_SHEET)
    values = ws.get_all_values()
    if len(values) < 2:
        return [], 0

    header = values[0]
    try:
        id_col = header.index("ID Tài Khoản")
        name_col = header.index("Tên Tài Khoản")
    except ValueError:
        sys.exit(f"Sheet '{AD_ACCOUNTS_SHEET}' thiếu cột 'ID Tài Khoản' / 'Tên Tài Khoản'.")

    accounts = []
    for i, row in enumerate(values[1:], start=2):   # hàng 2 trở đi
        acc_id = row[id_col].strip().removeprefix("act_") if id_col < len(row) else ""
        name = row[name_col].strip() if name_col < len(row) else ""
        if not acc_id and not name:
            continue
        accounts.append({"row": i, "id": acc_id, "name": name})
    return accounts, len(header)


def match_tab(acc: dict, titles: set[str]) -> str | None:
    """Tìm tab campaign của tài khoản: ưu tiên tên đã sanitize, fallback theo ID."""
    candidate = sanitize_sheet_name(acc["name"]) if acc["name"] else ""
    if candidate and candidate in titles:
        return candidate
    if acc["id"] and acc["id"] in titles:
        return acc["id"]
    return None


def fetch_tab_data(spreadsheet, titles: list[str]) -> dict[str, list[list]]:
    """Lấy A:F của từng tab trong 1 lần gọi batch (Sheets tự cắt hàng rỗng cuối)."""
    if not titles:
        return {}
    ranges = [f"{_quote(t)}!A1:F" for t in titles]
    resp = spreadsheet.values_batch_get(ranges)
    out = {}
    for title, block in zip(titles, resp.get("valueRanges", [])):
        out[title] = block.get("values", []) or []
    return out


def summarize(rows: list[list]) -> tuple[int, float]:
    """Trả về (số dòng dữ liệu dưới hàng tiêu đề, tổng spend của dòng Campaign)."""
    data = [r for r in rows[1:] if any(str(c).strip() for c in r)]
    spend = 0.0
    for r in data:
        level = r[CAMP_LEVEL_COL].strip() if len(r) > CAMP_LEVEL_COL else ""
        if level and level.lower() != "campaign":
            continue                      # bỏ dòng Adset / Ad để không cộng trùng
        if len(r) > CAMP_SPEND_COL:
            spend += _to_number(r[CAMP_SPEND_COL])
    return len(data), spend


def money(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".") + " ₫"


def run(dry_run: bool = False):
    print("Kết nối Google Sheets...")
    spreadsheet = connect_spreadsheet()
    print(f"  → {spreadsheet.title}")

    accounts, header_len = read_accounts(spreadsheet)
    if not accounts:
        sys.exit(f"Sheet '{AD_ACCOUNTS_SHEET}' chưa có dữ liệu tài khoản.")
    print(f"Đọc '{AD_ACCOUNTS_SHEET}': {len(accounts)} tài khoản.")

    titles = [ws.title for ws in spreadsheet.worksheets()]
    title_set = set(titles)

    # Dò tab tương ứng cho từng tài khoản rồi lấy dữ liệu 1 lượt
    for acc in accounts:
        acc["tab"] = match_tab(acc, title_set)
    wanted = sorted({acc["tab"] for acc in accounts if acc["tab"]})
    print(f"Đọc dữ liệu {len(wanted)} tab tài khoản...")
    tab_data = fetch_tab_data(spreadsheet, wanted)

    active, inactive = [], []
    for acc in accounts:
        if acc["tab"]:
            n_rows, spend = summarize(tab_data.get(acc["tab"], []))
        else:
            n_rows, spend = 0, 0.0
        acc["rows"], acc["spend"] = n_rows, spend
        (active if n_rows > 0 else inactive).append(acc)

    print(f"\n{'='*70}\nCÓ HOẠT ĐỘNG — {len(active)} tài khoản\n{'='*70}")
    for acc in sorted(active, key=lambda a: -a["spend"]):
        print(f"  ✔ [hàng {acc['row']:>3}] {acc['name'][:45]:<45} "
              f"{acc['rows']:>3} camp · {money(acc['spend']):>15}")

    print(f"\n{'='*70}\nKHÔNG HOẠT ĐỘNG — {len(inactive)} tài khoản\n{'='*70}")
    for acc in inactive:
        why = "không có tab" if not acc["tab"] else "tab chỉ có hàng tiêu đề"
        print(f"  ✘ [hàng {acc['row']:>3}] {acc['name'][:45]:<45} ({why})")

    # Tab có dữ liệu nhưng không khớp tài khoản nào trong TKQC API
    used = {acc["tab"] for acc in accounts if acc["tab"]}
    orphan = [t for t in titles
              if t not in used and t not in (AD_ACCOUNTS_SHEET, "Trang tính1")]
    if orphan:
        print(f"\nTab KHÔNG khớp tài khoản nào trong '{AD_ACCOUNTS_SHEET}' ({len(orphan)}):")
        for t in orphan:
            print(f"  · {t}")

    if dry_run:
        print("\n[--dry-run] Chỉ xem trước, KHÔNG tô màu sheet.")
        return

    last_col = col_to_letter(max(header_len, 1))
    ws = spreadsheet.worksheet(AD_ACCOUNTS_SHEET)
    formats = [{
        "range": f"A{acc['row']}:{last_col}{acc['row']}",
        "format": {"backgroundColor": COLOR_ACTIVE if acc["rows"] > 0 else COLOR_INACTIVE},
    } for acc in accounts]
    ws.batch_format(formats)

    print(f"\nĐã tô màu {len(formats)} hàng trên '{AD_ACCOUNTS_SHEET}' "
          f"(A→{last_col}): xanh = có hoạt động, đỏ = không.")
    print("Lưu ý: chạy lại main.py (Cập nhật TKQC) sẽ ghi đè màu này.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run(dry_run="--dry-run" in sys.argv)
