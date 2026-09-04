"""
tong_hop.py — Tạo tab "Tổng Hợp T{m}" giống mẫu "Tổng Hợp T6", KHÔNG cần Facebook API.

Điền dòng "1.1 Ngân sách được duyệt", "1.3 Ngân sách thực tế Camp đã tiêu" và các dòng phụ
Lệch / CP Tổng / Đơn / Doanh Số / Tỷ lệ CP (các dòng khác để trống, nhập tay):
  • Hàng 1 (từ cột B): tên các tab billing dạng "<Tên TK> (<ID>)" đang có trong sheet
    (tab do fb_billing_import_web.py tạo; bỏ qua tab "... Chi tiết").
  • Dòng 1.1: tổng cột C ("Số tiền") của tab đó, CHỈ tính các dòng có "Ngày thanh toán"
    thuộc tháng báo cáo (mẫu T6 cộng cả cột; lọc tháng để không lẫn tháng cũ).
    all_months=True nếu muốn y hệt mẫu (cộng cả cột).
  • Dòng 1.3: tổng cột "Số tiền đã chi tiêu (…)" của tab "Camp <Tên TK>" (tab do bước 3 web tạo từ
    báo cáo Ads Manager; <Tên TK> = tên ở hàng 1 bỏ "(ID)"), CHỈ các dòng hợp lệ: cột tên ("Tên nhóm
    quảng cáo", báo cáo cấp Chiến dịch thì "Tên chiến dịch") khác rỗng VÀ cột ngân sách ("Ngân sách nhóm
    quảng cáo" / "Ngân sách chiến dịch") khác 0/rỗng ("Sử dụng ngân sách chiến dịch" vẫn tính)
    → dòng tổng của Ads Manager (trống tên, ngân sách 0) không được cộng. Chưa có tab Camp → 0.
  • Dòng phụ (chỉ điền khi cột A có nhãn đó): Lệch = 1.1 + 1.2 − 1.3; CP Tổng = 1.1 + 1.2;
    Đơn = tổng "Lượt mua" và Doanh Số = tổng "Giá trị chuyển đổi lượt mua" của tab Camp (cùng quy tắc
    nhóm hợp lệ; tab chưa có cột đó → 0); Tỷ lệ CP = CP Tổng / Doanh Số (Doanh Số = 0 → để trống).
  • Dòng "ID tài khoản": hàng tiêu đề "1. NGÂN SÁCH - TẠM ỨNG" của mẫu được ĐỔI NHÃN thành "ID tài khoản"
    và điền ID từng TK tra ở tab "Danh Sách" (cột "Tên tài khoản quảng cáo" → "ID tài khoản", tiêu đề
    không nhất thiết ở hàng 1) theo tên TK ở hàng 1 bỏ "(ID)"; không có tab/không thấy tên → lấy ID
    trong ngoặc ở tên tab. Kết quả luôn là chuỗi (ID 16 số không bị làm tròn).
  • Tab mới được NHÂN BẢN từ tab mẫu nên giữ nguyên định dạng. Sheet đích chưa có tab mẫu
    thì tự SAO CHÉP mẫu từ sheet khác (template_sheet_id, mặc định là sheet báo cáo T6 cũ).
  • Chạy lại: tab đã có → chỉ cập nhật hàng 1 + các dòng công thức trên, các ô khác giữ nguyên.

Dùng từ web (fb_billing_import_web.py, mục 3) hoặc dòng lệnh:
  python tong_hop.py                              # sheet nhớ từ lần kết nối gần nhất, tháng = tháng trước
  python tong_hop.py --sheet <ID|link> --month 8 --year 2026
  python tong_hop.py --dry-run                    # chỉ in ra, không ghi
"""

import argparse
import re
import sys
import unicodedata
from datetime import date

from billing_core import extract_sheet_id, get_client, load_settings

TEMPLATE_DEFAULT       = "Tổng Hợp T6"
TEMPLATE_SHEET_DEFAULT = "1222q6Bp6ExzApMXS00UNTmcxS2eFIlaEg5-z2Y8cDiQ"   # sheet báo cáo T6 (có tab mẫu)
BUDGET_LABEL           = "1.1 Ngân sách được duyệt"
SPENT_LABEL            = "1.3 Ngân sách thực tế Camp đã tiêu"
SPENT_LABEL_PREFIX     = "1.3 Ngân sách thực tế"          # phân biệt với "1.3 Ngân sách còn lại"
CAMP_PREFIX            = "Camp "                            # tab báo cáo Ads Manager = "Camp <Tên TK>"
SPENT_HEADER           = "Số tiền đã chi tiêu"              # cột chi tiêu trong tab Camp ("… (VND)" khớp qua hậu tố)
DON_HEADER             = "Lượt mua"                         # dòng "Đơn" = tổng cột này (nhóm hợp lệ)
DOANH_SO_HEADER        = "Giá trị chuyển đổi lượt mua"      # dòng "Doanh Số" = tổng cột này; tab chưa có cột → 0
NAME_HEADERS           = ["Tên nhóm quảng cáo*", "Tên chiến dịch*", "Tên quảng cáo*"]   # cột tên theo cấp báo cáo (lấy cột đầu
                                                                                       # tìm được); dòng trống tên (dòng tổng) KHÔNG cộng
BUDGET_HEADERS         = ["Ngân sách nhóm quảng cáo*", "Ngân sách chiến dịch*"]        # cột ngân sách; = 0/rỗng KHÔNG cộng
                                                                                       # (chữ "Sử dụng ngân sách …" vẫn tính)
DEBT_LABEL             = "1.2 Số tiền nợ"                   # nhãn các dòng phụ (khớp đúng nhãn ở cột A, thiếu → bỏ qua)
LECH_LABEL             = "Lệch"
CP_TOTAL_LABEL         = "CP Tổng"
DON_LABEL              = "Đơn"
DOANH_SO_LABEL         = "Doanh Số"
TY_LE_CP_LABEL         = "Tỷ lệ CP"
ID_LABEL               = "ID tài khoản"                     # dòng ID: thay nhãn "1. NGÂN SÁCH - TẠM ỨNG" của mẫu
ID_OLD_LABEL_PREFIX    = "1. NGÂN SÁCH"                     # nhãn cũ ở mẫu T6 → đổi thành ID_LABEL khi ghi
DS_TAB                 = "Danh Sách"                        # tab danh sách TK (so mềm: không phân biệt hoa/thường/dấu)
DS_NAME_HEADER         = "Tên tài khoản"                    # tiêu đề cột tên TK trong tab Danh Sách (khớp tiền tố)
DS_ID_HEADER           = "ID tài khoản"                     # tiêu đề cột ID trong tab Danh Sách (khớp đúng)
BILLING_TAB_RE        = re.compile(r"\(\d{6,}\)\s*$")     # '<tên> (<ID số>)'
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


def _match_first(patterns: list) -> str:
    """Số thứ tự cột đầu tiên trong hàng 1 tab Camp khớp một trong `patterns` (thử lần lượt); không có → 0."""
    expr = "0"
    for p in reversed(patterns):
        expr = f'IFERROR(MATCH("{p}";hdr;0);{expr})'
    return expr


def _match_col(header: str) -> str:
    """Số thứ tự cột `header`: khớp đúng tên trước, rồi tới tên có hậu tố ("Số tiền đã chi tiêu (VND)"); không có → 0."""
    return _match_first([header, header + "*"])


def camp_sum_formula(col: str, header: str) -> str:
    """Tổng cột `header` của tab "Camp <tên hàng 1 bỏ (ID)>" cho cột `col`, CHỈ cộng các dòng hợp lệ:
    cột tên (Tên nhóm quảng cáo / Tên chiến dịch / Tên quảng cáo — tùy cấp báo cáo) khác rỗng VÀ cột ngân sách
    (Ngân sách nhóm quảng cáo / Ngân sách chiến dịch) khác 0/rỗng (chữ "Sử dụng ngân sách …" vẫn hợp lệ)
    → loại dòng tổng của Ads Manager. Tab không có cột tên → cộng cả cột; không có cột ngân sách → chỉ lọc
    theo tên; không có tab hoặc không có cột `header` → 0."""
    camp = f'"{CAMP_PREFIX}"&REGEXREPLACE({col}$1;"\\s*\\([^()]*\\)\\s*$";"")'
    nhom, ns = "INDEX(data;0;cNhom)", "INDEX(data;0;cNS)"
    mask = f'LEN({nhom})>0;IF(cNS=0;LEN({nhom})>0;(LEN({ns})>0)*({ns}<>0))'
    body = f'IF(cVal=0;0;IF(cNhom=0;SUM(val);SUM(FILTER(val;{mask}))))'
    return (f'=IFERROR(LET(camp;{camp};'
            f'hdr;INDIRECT("\'"&camp&"\'!1:1");'
            f'data;INDIRECT("\'"&camp&"\'!A2:ZZ");'
            f'cVal;{_match_col(header)};'
            f'cNhom;{_match_first(NAME_HEADERS)};'
            f'cNS;{_match_first(BUDGET_HEADERS)};'
            f'val;INDEX(data;0;cVal);'
            f'{body});0)')


def spent_formula(col: str) -> str:
    """Dòng 1.3 cho cột `col`: tổng "Số tiền đã chi tiêu (…)" của tab Camp, nhóm QC hợp lệ."""
    return camp_sum_formula(col, SPENT_HEADER)


def _ref(col: str, row) -> str:
    return f"{col}{row}" if row else ""


def lech_formula(col: str, budget_row: int, debt_row, spent_row: int) -> str:
    """Lệch = 1.1 + 1.2 − 1.3 (không có dòng 1.2 → 1.1 − 1.3)."""
    debt = f"+{_ref(col, debt_row)}" if debt_row else ""
    return f"={col}{budget_row}{debt}-{col}{spent_row}"


def cp_total_formula(col: str, budget_row: int, debt_row) -> str:
    """CP Tổng = 1.1 + 1.2 (không có dòng 1.2 → = 1.1)."""
    debt = f"+{_ref(col, debt_row)}" if debt_row else ""
    return f"={col}{budget_row}{debt}"


def ty_le_cp_formula(col: str, cp_row: int, ds_row: int) -> str:
    """Tỷ lệ CP = CP Tổng / Doanh Số; Doanh Số = 0 hoặc trống → ô trống."""
    return f'=IFERROR({col}{cp_row}/{col}{ds_row};"")'


def _fold(s: str) -> str:
    """Bỏ dấu + casefold + gọn khoảng trắng để so mềm tên tab / tiêu đề ("Danh Sách" = "danh sach ")."""
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return " ".join(s.casefold().split())


def find_danh_sach(wss, tab: str = DS_TAB):
    """Tìm tab "Danh Sách" (so mềm) và vị trí cột "Tên tài khoản…" / "ID tài khoản" trong 10 hàng đầu
    (tiêu đề thật thường ở hàng 2, hàng 1 là tên BM). Trả {"tab", "row" (hàng tiêu đề), "name_col",
    "id_col"} hoặc None nếu thiếu tab/cột → dòng ID sẽ lấy ID trong ngoặc ở tên tab."""
    ws = next((w for w in wss if _fold(w.title) == _fold(tab)), None)
    if ws is None:
        return None
    name_key, id_key = _fold(DS_NAME_HEADER), _fold(DS_ID_HEADER)
    for r, row in enumerate(ws.get_values("A1:Z10"), 1):
        cells = [_fold(v) for v in row]
        id_i   = next((i for i, v in enumerate(cells) if v == id_key), None)
        name_i = next((i for i, v in enumerate(cells) if v.startswith(name_key)), None)
        if id_i is not None and name_i is not None:
            return {"tab": ws.title, "row": r,
                    "name_col": col_letter(name_i + 1), "id_col": col_letter(id_i + 1)}
    return None


def id_formula(col: str, ds: dict = None) -> str:
    """Dòng "ID tài khoản" cho cột `col`: tra ID theo tên TK (hàng 1 bỏ "(ID)") trong tab Danh Sách `ds`
    (kết quả của find_danh_sach); không có tab/cột, không thấy tên hoặc ô ID trống → lấy ID trong ngoặc
    ở tên tab. Luôn trả chuỗi (TEXT(...;"0")) để ID 16 số không bị hiển thị dạng 1,5E+15."""
    from_title = f'IFERROR(REGEXEXTRACT({col}$1;"\\((\\d+)\\)\\s*$");"")'
    if not ds:
        return f"={from_title}"
    tab = ds["tab"].replace("'", "''")
    r0 = ds["row"] + 1                                       # dữ liệu bắt đầu ngay dưới hàng tiêu đề
    names = f"'{tab}'!${ds['name_col']}${r0}:${ds['name_col']}"
    ids   = f"'{tab}'!${ds['id_col']}${r0}:${ds['id_col']}"
    ten   = f'TRIM(REGEXREPLACE({col}$1;"\\s*\\([^()]*\\)\\s*$";""))'
    return (f'=IFERROR(LET(v;INDEX({ids};MATCH({ten};ARRAYFORMULA(TRIM({names}));0));'
            f'IF(LEN(v)=0;{from_title};IF(ISNUMBER(v);TEXT(v;"0");v&"")));{from_title})')


def _find_row(labels: list, prefix: str, exact: bool = False):
    """Số hàng (1-based) có nhãn ở cột A bắt đầu bằng `prefix` (hoặc bằng đúng `prefix` khi exact)."""
    key = prefix.strip().casefold()
    return next((i for i, v in enumerate(labels, 1)
                 if (v.strip().casefold() == key if exact else v.strip().startswith(prefix))), None)


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
    cols = [col_letter(i + 2) for i in range(len(tabs))]
    formulas = [budget_formula(c, mf, year) for c in cols]
    spent    = [spent_formula(c) for c in cols]

    # Dòng phụ: chỉ điền khi cột A có đúng nhãn (thiếu nhãn → bỏ qua, không báo lỗi)
    debt_row = _find_row(labels, "1.2 ")
    cp_row   = _find_row(labels, CP_TOTAL_LABEL, exact=True)
    ds_row   = _find_row(labels, DOANH_SO_LABEL, exact=True)
    extra = {}                                                # nhãn → (số hàng, [công thức từng cột])
    # Dòng ID: tab đã đổi nhãn → "ID tài khoản"; tab mẫu → hàng "1. NGÂN SÁCH - TẠM ỨNG" (sẽ đổi nhãn khi ghi)
    ds = find_danh_sach(wss)
    id_row = _find_row(labels, ID_LABEL, exact=True) or _find_row(labels, ID_OLD_LABEL_PREFIX)
    if id_row:
        extra[ID_LABEL] = (id_row, [id_formula(c, ds) for c in cols])
    if r := _find_row(labels, LECH_LABEL, exact=True):
        extra[LECH_LABEL] = (r, [lech_formula(c, budget_row, debt_row, spent_row) for c in cols])
    if cp_row:
        extra[CP_TOTAL_LABEL] = (cp_row, [cp_total_formula(c, budget_row, debt_row) for c in cols])
    if r := _find_row(labels, DON_LABEL, exact=True):
        extra[DON_LABEL] = (r, [camp_sum_formula(c, DON_HEADER) for c in cols])
    if ds_row:
        extra[DOANH_SO_LABEL] = (ds_row, [camp_sum_formula(c, DOANH_SO_HEADER) for c in cols])
    if (r := _find_row(labels, TY_LE_CP_LABEL, exact=True)) and cp_row and ds_row:
        extra[TY_LE_CP_LABEL] = (r, [ty_le_cp_formula(c, cp_row, ds_row) for c in cols])
    formula_rows = [(budget_row, formulas), (spent_row, spent)] + list(extra.values())

    result = {"ok": True, "mode": mode, "target": target, "accounts": len(tabs),
              "template": tpl.title if tpl else target, "template_from": tpl_from,
              "budget_row": budget_row, "spent_row": spent_row, "month": month, "year": year,
              "all_months": all_months, "sheet": ss.title, "formula": formulas[0],
              "spent_formula": spent[0], "header": header,
              "extra_rows": {k: v[0] for k, v in extra.items()},
              "extra_formulas": {k: v[1][0] for k, v in extra.items()},
              "id_row": id_row, "danh_sach": ds}
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
    label_writes = [{"range": f"A{id_row}", "values": [[ID_LABEL]]}] if id_row else []   # đổi nhãn hàng ID
    ws.batch_update(label_writes
                    + [{"range": f"B{r}:{last_col}{r}", "values": [vals]} for r, vals in formula_rows],
                    value_input_option="USER_ENTERED")
    if existing:                                              # bớt cột thừa nếu số tài khoản giảm
        extra_from = 2 + len(tabs)
        if ws.col_count >= extra_from:
            c0, c1 = col_letter(extra_from), col_letter(ws.col_count)
            ws.batch_clear([f"{c0}1:{c1}1"] + [f"{c0}{r}:{c1}{r}" for r, _ in formula_rows])

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
    ds = r.get("danh_sach")
    print("Danh Sách: " + (f'tab "{ds["tab"]}" (tiêu đề hàng {ds["row"]}, tên cột {ds["name_col"]}, '
                          f'ID cột {ds["id_col"]}) → dòng {r["id_row"]} "{ID_LABEL}"' if ds
                          else f'không có tab "{DS_TAB}" → dòng "{ID_LABEL}" lấy ID trong ngoặc ở tên tab'))
    if a.dry_run:
        print("[dry-run] hàng 1 :", r["header"][1:4], "…")
        print(f"[dry-run] B{r['budget_row']}:", r["formula"])
        print(f"[dry-run] B{r['spent_row']}:", r["spent_formula"])
        for k, row in r["extra_rows"].items():
            print(f"[dry-run] B{row} ({k}):", r["extra_formulas"][k])
        return
    extra = ", ".join(f"{k} (hàng {v})" for k, v in r["extra_rows"].items())
    print(f"\n✓ Đã {r['mode']} tab \"{r['target']}\": {r['accounts']} tài khoản, "
          f"dòng {r['budget_row']} ({BUDGET_LABEL}) và dòng {r['spent_row']} ({SPENT_LABEL}) có công thức."
          + (f"\n  Dòng phụ: {extra}." if extra else ""))
    print("  " + r["url"])


if __name__ == "__main__":
    main()
