"""
tong_hop.py — Tạo tab "Tổng Hợp T{m}" giống mẫu "Tổng Hợp T6", KHÔNG cần Facebook API.

Điền dòng "1.1 Ngân sách được duyệt" và "1.3 Ngân sách thực tế Camp đã tiêu" (các dòng khác để trống):
  • Hàng 1 (từ cột B): tên các tab billing dạng "<Tên TK> (<ID>)" đang có trong sheet
    (tab do fb_billing_import_web.py tạo; bỏ qua tab "... Chi tiết").
  • Dòng 1.1: tổng cột C ("Số tiền") của tab đó, CHỈ tính các dòng có "Ngày thanh toán"
    thuộc tháng báo cáo (mẫu T6 cộng cả cột; lọc tháng để không lẫn tháng cũ).
    all_months=True nếu muốn y hệt mẫu (cộng cả cột).
  • Dòng 1.3: tổng cột "Số tiền đã chi tiêu (…)" của tab "Camp <Tên TK>" (tab do bước 3 web tạo từ
    báo cáo Ads Manager; <Tên TK> = tên ở hàng 1 bỏ "(ID)"). Chưa có tab Camp → 0.
  • Tab mới được NHÂN BẢN từ tab mẫu nên giữ nguyên định dạng. Sheet đích chưa có tab mẫu
    thì tự SAO CHÉP mẫu từ sheet khác (template_sheet_id, mặc định là sheet báo cáo T6 cũ).
  • Chạy lại: tab đã có → chỉ cập nhật hàng 1 + dòng 1.1 + dòng 1.3, các ô khác giữ nguyên.

Dùng từ web (fb_billing_import_web.py, mục 3) hoặc dòng lệnh:
  python tong_hop.py                              # sheet nhớ từ lần kết nối gần nhất, tháng = tháng trước
  python tong_hop.py --sheet <ID|link> --month 8 --year 2026
  python tong_hop.py --dry-run                    # chỉ in ra, không ghi
"""

import argparse
import re
import sys
from datetime import date

from billing_core import extract_sheet_id, get_client, load_settings

TEMPLATE_DEFAULT       = "Tổng Hợp T6"
TEMPLATE_SHEET_DEFAULT = "1222q6Bp6ExzApMXS00UNTmcxS2eFIlaEg5-z2Y8cDiQ"   # sheet báo cáo T6 (có tab mẫu)
BUDGET_LABEL           = "1.1 Ngân sách được duyệt"
SPENT_LABEL            = "1.3 Ngân sách thực tế Camp đã tiêu"
SPENT_LABEL_PREFIX     = "1.3 Ngân sách thực tế"          # phân biệt với "1.3 Ngân sách còn lại"
CAMP_PREFIX            = "Camp "                            # tab báo cáo Ads Manager = "Camp <Tên TK>"
SPENT_HEADER_WILDCARD  = "Số tiền đã chi tiêu*"             # cột chi tiêu trong tab Camp (VND/USD…)
BILLING_TAB_RE         = re.compile(r"\(\d{6,}\)\s*$")     # '<tên> (<ID số>)'
AMOUNT_COL             = "C"                                # cột "Số tiền" trong tab billing
DATE_COL               = "B"                                # cột "Ngày thanh toán"


def col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def default_month_year(today: date = None):
    today = today or date.today()
    return (12, today.year - 1) if today.month == 1 else (today.month - 1, today.year)


def month_regex(month: int, year: int) -> str:
    """Khớp 'Ngày thanh toán' của FB ở nhiều định dạng:
    '26 Tháng 8, 2026' · '26 thg 8 2026' · '26/8/2026' · '2026-08-26' · 'Aug 26, 2026'."""
    en = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"][month - 1]
    return (rf"(?i)(th(án)?g\.?\s*0?{month}\b[^\d]*{year}"
            rf"|/0?{month}/{year}\b"
            rf"|{year}-0?{month}-"
            rf"|\b{en}[a-z]*\.?\s+\d{{1,2}},?\s+{year})")


def budget_formula(col: str, month: int = None, year: int = None) -> str:
    """Công thức dòng 1.1 cho cột `col` (tên tab lấy ở hàng 1 cùng cột). Dấu ';' vì sheet locale VN."""
    amount = f'IFERROR(VALUE(INDIRECT("\'"&{col}$1&"\'!{AMOUNT_COL}2:{AMOUNT_COL}"));0)'
    if month is None:                                       # giống hệt mẫu T6
        return f"=SUM(ARRAYFORMULA({amount}))"
    dates = f'INDIRECT("\'"&{col}$1&"\'!{DATE_COL}2:{DATE_COL}")'
    rx = month_regex(month, year).replace('"', '""')
    return (f'=SUMPRODUCT(ARRAYFORMULA(IFERROR(REGEXMATCH(TO_TEXT({dates});"{rx}");FALSE))'
            f"*ARRAYFORMULA({amount}))")


def spent_formula(col: str) -> str:
    """Dòng 1.3 cho cột `col`: SUM cột "Số tiền đã chi tiêu*" của tab "Camp <tên hàng 1 bỏ (ID)>"; không có tab → 0."""
    camp = f'"{CAMP_PREFIX}"&REGEXREPLACE({col}$1;"\\s*\\([^()]*\\)\\s*$";"")'
    data = f'INDIRECT("\'"&{camp}&"\'!A2:ZZ")'
    hdr  = f'INDIRECT("\'"&{camp}&"\'!1:1")'
    return f'=IFERROR(SUM(INDEX({data};0;MATCH("{SPENT_HEADER_WILDCARD}";{hdr};0)));0)'


def _find_row(labels: list, prefix: str):
    return next((i for i, v in enumerate(labels, 1) if v.strip().startswith(prefix)), None)


def list_billing_tabs(titles) -> list:
    return sorted((t for t in titles if BILLING_TAB_RE.search(t) and not t.endswith("Chi tiết")),
                  key=str.casefold)


def _find_template(wss, name: str):
    return next((w for w in wss if w.title == name), None) \
        or next((w for w in wss if w.title.startswith("Tổng Hợp T")), None)


def build_summary(ss, month: int, year: int, all_months: bool = False,
                  template: str = TEMPLATE_DEFAULT, template_sheet_id: str = "",
                  gc=None, dry_run: bool = False) -> dict:
    """Tạo/cập nhật tab 'Tổng Hợp T{month}' trong spreadsheet `ss`. Trả dict kết quả; lỗi → ValueError."""
    if not 1 <= month <= 12:
        raise ValueError("Tháng phải từ 1 đến 12")
    wss = ss.worksheets()
    by_title = {w.title: w for w in wss}
    tabs = list_billing_tabs(by_title)
    if not tabs:
        raise ValueError("Sheet chưa có tab billing dạng '<tên> (<ID>)' nào. Import file billing trước.")

    target = f"Tổng Hợp T{month}"
    existing = by_title.get(target)
    tpl = _find_template(wss, template)
    tpl_from = ss.title
    if existing is None and tpl is None:
        # Sheet đích chưa có mẫu → lấy từ sheet mẫu (mặc định: sheet báo cáo T6)
        src_id = extract_sheet_id(template_sheet_id or "") or TEMPLATE_SHEET_DEFAULT
        if src_id == ss.id:
            raise ValueError(f'Sheet không có tab mẫu "{template}" và không có sheet mẫu nào khác.')
        gc = gc or get_client()
        try:
            src = gc.open_by_key(src_id)
        except Exception as e:
            raise ValueError(f"Không mở được sheet mẫu {src_id}: {e}") from e
        tpl = _find_template(src.worksheets(), template)
        if tpl is None:
            raise ValueError(f'Sheet mẫu "{src.title}" cũng không có tab "{template}".')
        tpl_from = src.title

    mode = "cập nhật" if existing else "tạo mới"
    mf = None if all_months else month
    src_ws = existing or tpl
    labels = src_ws.col_values(1)
    budget_row = _find_row(labels, "1.1 ")
    spent_row  = _find_row(labels, SPENT_LABEL_PREFIX)
    if budget_row is None:
        raise ValueError(f'Không thấy dòng "{BUDGET_LABEL}" ở cột A của tab mẫu.')
    if spent_row is None:
        raise ValueError(f'Không thấy dòng "{SPENT_LABEL}" ở cột A của tab mẫu.')
    n_rows = max(len(labels), 3)
    last_col = col_letter(1 + len(tabs))
    header = [""] + tabs
    formulas = [budget_formula(col_letter(i + 2), mf, year) for i in range(len(tabs))]
    spent    = [spent_formula(col_letter(i + 2)) for i in range(len(tabs))]

    result = {"ok": True, "mode": mode, "target": target, "accounts": len(tabs),
              "template": tpl.title if tpl else target, "template_from": tpl_from,
              "budget_row": budget_row, "spent_row": spent_row, "month": month, "year": year,
              "all_months": all_months, "sheet": ss.title, "formula": formulas[0],
              "spent_formula": spent[0], "header": header}
    if dry_run:
        return result

    if existing:
        ws = existing
    else:
        if tpl.spreadsheet.id == ss.id:
            ws = ss.duplicate_sheet(tpl.id, insert_sheet_index=tpl.index + 1, new_sheet_name=target)
        else:
            copied = tpl.copy_to(ss.id)                       # → "Copy of ..." trong sheet đích
            ws = ss.get_worksheet_by_id(copied["sheetId"])
            ws.update_title(target)
            ws.update_index(0)                                # đưa lên đầu
        # Xóa giá trị/công thức cũ trừ cột A (nhãn) — định dạng giữ nguyên
        ws.batch_clear([f"B1:{col_letter(max(ws.col_count, 2))}{max(ws.row_count, n_rows)}"])

    need_cols = 1 + len(tabs) + 1
    if ws.col_count < need_cols:                              # thêm cột + copy định dạng cột B
        old_cols = ws.col_count
        ws.resize(cols=need_cols)
        ss.batch_update({"requests": [{"copyPaste": {
            "source":      {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": n_rows,
                            "startColumnIndex": 1, "endColumnIndex": 2},
            "destination": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": n_rows,
                            "startColumnIndex": old_cols, "endColumnIndex": need_cols},
            "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}}]})

    ws.update(range_name=f"A1:{last_col}1", values=[header], value_input_option="RAW")
    ws.update(range_name=f"B{budget_row}:{last_col}{budget_row}", values=[formulas],
              value_input_option="USER_ENTERED")
    ws.update(range_name=f"B{spent_row}:{last_col}{spent_row}", values=[spent],
              value_input_option="USER_ENTERED")
    if existing:                                              # bớt cột thừa nếu số tài khoản giảm
        extra_from = 2 + len(tabs)
        if ws.col_count >= extra_from:
            ws.batch_clear([f"{col_letter(extra_from)}1:{col_letter(ws.col_count)}1",
                            f"{col_letter(extra_from)}{budget_row}:{col_letter(ws.col_count)}{budget_row}",
                            f"{col_letter(extra_from)}{spent_row}:{col_letter(ws.col_count)}{spent_row}"])

    result.update({"url": f"{ss.url}#gid={ws.id}", "gid": ws.id})
    return result


def main():
    ap = argparse.ArgumentParser(description="Tạo tab Tổng Hợp T{m} từ mẫu, chỉ điền dòng 1.1")
    ap.add_argument("--sheet", help="ID hoặc link Google Sheet đích (mặc định: sheet dùng gần nhất)")
    ap.add_argument("--month", type=int, help="tháng báo cáo (mặc định: tháng hiện tại - 1)")
    ap.add_argument("--year", type=int, help="năm báo cáo (mặc định: theo tháng)")
    ap.add_argument("--template", default=TEMPLATE_DEFAULT, help=f'tên tab mẫu (mặc định "{TEMPLATE_DEFAULT}")')
    ap.add_argument("--template-sheet", help="ID/link sheet chứa tab mẫu nếu sheet đích chưa có")
    ap.add_argument("--all-months", action="store_true", help="dòng 1.1 cộng cả cột C như mẫu, không lọc tháng")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in kế hoạch, không ghi")
    a = ap.parse_args()

    settings = load_settings()
    m0, y0 = default_month_year()
    month = a.month or m0
    year  = a.year or (y0 if a.month is None else date.today().year)
    sheet_id = extract_sheet_id(a.sheet or "") or settings.get("sheet_id", "")
    if not sheet_id:
        sys.exit("Chưa biết sheet nào: truyền --sheet <ID|link> (hoặc kết nối một lần trong fb_billing_import_web.py).")

    gc = get_client()
    ss = gc.open_by_key(sheet_id)
    try:
        r = build_summary(ss, month, year, all_months=a.all_months, template=a.template,
                          template_sheet_id=a.template_sheet or settings.get("template_sheet_id", ""),
                          gc=gc, dry_run=a.dry_run)
    except ValueError as e:
        sys.exit(f"Lỗi: {e}")

    print(f"Sheet    : {r['sheet']}")
    print(f"Mẫu      : {r['template']}  (từ: {r['template_from']})")
    print(f"Tài khoản: {r['accounts']} tab billing")
    print(f"Đích     : {r['target']}  ({r['mode']})  |  dòng 1.1: "
          + ("cộng cả cột C" if r["all_months"] else f"chỉ tháng {month}/{year}"))
    if a.dry_run:
        print("[dry-run] hàng 1 :", r["header"][1:4], "…")
        print(f"[dry-run] B{r['budget_row']}:", r["formula"])
        print(f"[dry-run] B{r['spent_row']}:", r["spent_formula"])
        return
    print(f"\n✓ Đã {r['mode']} tab \"{r['target']}\": {r['accounts']} tài khoản, "
          f"dòng {r['budget_row']} ({BUDGET_LABEL}) và dòng {r['spent_row']} ({SPENT_LABEL}) có công thức.")
    print("  " + r["url"])


if __name__ == "__main__":
    main()
