"""
Lớp Google Sheets — kết nối + upsert (cập nhật/chèn) không làm mất dữ liệu cũ.

Hàm chính:
    connect_spreadsheet()       Mở Google Sheet bằng service account.
    get_or_create_worksheet()   Lấy/ tạo tab + đảm bảo dòng header đúng.
    upsert_to_google_sheet()    Upsert theo khóa: trùng → update, mới → append.
                                Hỗ trợ preserve_cols (giữ giá trị người dùng nhập tay).
    append_sync_log()           Ghi 1 dòng vào sheet sync_log.
"""

import logging

import gspread
from google.oauth2.service_account import Credentials

import config

log = logging.getLogger("sheets")


def col_to_letter(n: int) -> str:
    """1 → A, 26 → Z, 27 → AA ..."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def connect_spreadsheet():
    creds = Credentials.from_service_account_file(
        str(config.service_account_path()), scopes=config.GOOGLE_SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_key(config.GOOGLE_SHEET_ID)


def get_or_create_worksheet(spreadsheet, title: str, header: list[str]):
    """Lấy tab theo tên; tạo nếu chưa có. Luôn đảm bảo dòng 1 = header.

    Nếu tab mới (trống) → ghi header. Nếu header hiện tại khác → ghi đè ĐÚNG dòng 1
    (không đụng dữ liệu bên dưới)."""
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if title in existing:
        ws = existing[title]
    else:
        ws = spreadsheet.add_worksheet(
            title=title, rows=2000, cols=max(26, len(header) + 2)
        )
        log.info("Đã tạo tab mới: %s", title)

    current = ws.row_values(1)
    if current != header:
        end = col_to_letter(len(header))
        ws.update(values=[header], range_name=f"A1:{end}1",
                  value_input_option="RAW")
    return ws


def _stringify(v) -> str:
    """Ép mọi giá trị về chuỗi để ghi RAW — ID dài không bị làm tròn, số giữ nguyên text."""
    if v is None:
        return ""
    if isinstance(v, float):
        # bỏ .0 thừa cho số nguyên dạng float
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def _dedup_keep_last(rows: list[dict], key_cols: list[str]) -> list[dict]:
    """Khử trùng trong batch theo khóa, giữ bản ghi XUẤT HIỆN SAU (mới nhất).

    Cần thiết vì các khoảng thời gian chồng lấn (hôm nay ⊂ tháng này) sinh cùng khóa."""
    by_key: dict[tuple, dict] = {}
    for d in rows:
        key = tuple(_stringify(d.get(k, "")) for k in key_cols)
        by_key[key] = d
    return list(by_key.values())


def upsert_to_google_sheet(worksheet, header: list[str], rows: list[dict],
                           key_cols: list[str],
                           preserve_cols: list[str] | None = None) -> tuple[int, int]:
    """Upsert danh sách dict `rows` vào worksheet theo `key_cols`.

    - Dòng trùng khóa → cập nhật tại chỗ; khóa mới → thêm vào cuối.
    - preserve_cols: cột đã có giá trị trong sheet sẽ ĐƯỢC GIỮ (không ghi đè) — dùng
      cho cột người dùng/CRM nhập tay (orders, revenue, note...).
    - Trả về (rows_inserted, rows_updated).
    """
    preserve_cols = preserve_cols or []
    rows = _dedup_keep_last(rows, key_cols)
    if not rows:
        return 0, 0

    all_values = worksheet.get_all_values()
    sheet_header = all_values[0] if all_values else header
    col_index = {name: i for i, name in enumerate(sheet_header)}

    def cell(row: list[str], name: str) -> str:
        i = col_index.get(name)
        return row[i] if i is not None and i < len(row) else ""

    # Map khóa → số dòng (1-based) trong sheet.
    key_to_row: dict[tuple, int] = {}
    for r_idx, row in enumerate(all_values[1:], start=2):
        key = tuple(cell(row, k) for k in key_cols)
        key_to_row[key] = r_idx

    end_col = col_to_letter(len(header))
    updates: list[dict] = []   # {range, values} cho batch_update
    appends: list[list[str]] = []
    inserted = updated = 0

    for d in rows:
        key = tuple(_stringify(d.get(k, "")) for k in key_cols)
        values = [_stringify(d.get(h, "")) for h in header]

        if key in key_to_row:
            rownum = key_to_row[key]
            if preserve_cols:
                existing = all_values[rownum - 1]
                for pc in preserve_cols:
                    if pc in col_index:
                        old = cell(existing, pc)
                        if old != "":  # giữ giá trị cũ người dùng đã nhập
                            values[header.index(pc)] = old
            updates.append({"range": f"A{rownum}:{end_col}{rownum}", "values": [values]})
            updated += 1
        else:
            appends.append(values)
            inserted += 1

    if updates:
        worksheet.batch_update(updates, value_input_option="RAW")
    if appends:
        worksheet.append_rows(appends, value_input_option="RAW")

    return inserted, updated


def append_sync_log(worksheet, row: dict, header: list[str]) -> None:
    """Thêm 1 dòng log (luôn append, không upsert)."""
    worksheet.append_row(
        [_stringify(row.get(h, "")) for h in header],
        value_input_option="RAW",
    )
