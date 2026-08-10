"""Đối chiếu lịch sử giao dịch ngân hàng: tô màu các giao dịch của một số thẻ và
tổng hợp Amount theo nhóm nội dung.

File nguồn KHÔNG bị sửa. Kết quả ghi ra một file .xlsx mới, mặc định đặt trong
thư mục Downloads, tên có kèm ngày giờ nên chạy lại không đè bản cũ.

Báo cáo nhóm ghi ở cột I/J (bắt đầu hàng 1): giao dịch cùng số thẻ gộp 1 hàng,
các nội dung khác (Chuyen khoan, Tra lai so du...) mỗi loại 1 hàng.

    python to_do_tong_tien_the.py                      # chọn file gần nhất trong Downloads
    python to_do_tong_tien_the.py --file "D:/...xlsx"
    python to_do_tong_tien_the.py --card 402156...0740 --out "D:/ketqua.xlsx"

Giao diện đồ họa: chạy gui_doi_chieu_the.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

try:
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import column_index_from_string, get_column_letter
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: openpyxl. Install with: pip install openpyxl"
    ) from exc


DEFAULT_CARD = "402156...0740"
DEFAULT_REPORT_COL = "I"
# Dấu nhận biết file do tool sinh ra, để không gợi ý chính nó làm file nguồn
OUTPUT_MARK = "_ketqua_"
# Tên file sao kê ngân hàng tải về thường có dạng Doichieugiaodich_<id>.xlsx
STATEMENT_HINT = "doichieu"

# Cột theo tiêu đề (đã bỏ dấu, chữ thường) -> dò vị trí cột, không hard-code A/B/C
HEADER_AMOUNT = "amount"
HEADER_TEXT = "line item text"
HEADER_DATE = "value date"

REPORT_TITLE = "NHÓM GIAO DỊCH"
REPORT_VALUE_TITLE = "SỐ TIỀN"
TOTAL_LABEL = "TỔNG CỘNG"
# Số hàng dọn trong vùng báo cáo mỗi lần chạy (phòng khi file nguồn đã xử lý rồi)
REPORT_SCAN_ROWS = 60

# Số thẻ trong Line Item Text: 6 số đầu + phần che (... hoặc XXXXXX) + 4 số cuối
CARD_IN_TEXT = re.compile(r"(\d{6})\s*[.xX*\s]{0,12}\s*(\d{4})")

# Vàng hổ phách + chữ đen: dễ đọc hơn hẳn nền đỏ FFC7CE dùng lúc đầu
HIGHLIGHT_HEX = "FFF2CC"
HIGHLIGHT_FILL = PatternFill(
    start_color=HIGHLIGHT_HEX, end_color=HIGHLIGHT_HEX, fill_type="solid"
)
HIGHLIGHT_FONT = Font(color="000000")
# Mọi màu tô tool từng dùng, để dọn sạch vệt cũ kể cả file sinh bởi bản trước.
# openpyxl đọc màu ra dạng có alpha nên phải nhận cả biến thể 8 ký tự.
_PAST_HEXES = (HIGHLIGHT_HEX, "FFC7CE")
HIGHLIGHT_VARIANTS = {
    variant
    for hex_code in _PAST_HEXES
    for variant in (hex_code, f"00{hex_code}", f"FF{hex_code}")
}
HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
CARD_ROW_FONT = Font(bold=True, color="000000")
TOTAL_FONT = Font(bold=True)
TOP_BORDER = Border(top=Side(style="thin"))
MONEY_FORMAT = "#,##0"


@dataclass
class Group:
    key: str
    count: int
    amount: Decimal
    is_card: bool


@dataclass
class Result:
    source: Path
    output: Path
    sheet: str
    groups: list[Group]
    total: Decimal
    highlighted: int
    months: list[str]
    report_range: str
    warnings: list[str] = field(default_factory=list)


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def header_text(value: Any) -> str:
    value_text = text(value).lower()
    value_text = "".join(
        ch
        for ch in unicodedata.normalize("NFD", value_text)
        if unicodedata.category(ch) != "Mn"
    )
    return " ".join(value_text.split())


def downloads_dir() -> Path:
    """Thư mục Downloads thật của user (có thể đã bị dời khỏi C:\\Users\\...)."""
    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                raw = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
            folder = Path(os.path.expandvars(raw))
            if folder.is_dir():
                return folder
        except OSError:
            pass
    folder = Path.home() / "Downloads"
    return folder if folder.is_dir() else Path.home()


def default_output_path(source: Path, folder: Path | None = None) -> Path:
    """Tên kết quả = tên nguồn + ngày giờ. Thêm hậu tố nếu 2 lần chạy trùng giây,
    để đúng cam kết không bao giờ đè bản cũ."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = folder or downloads_dir()
    base = f"{source.stem}{OUTPUT_MARK}{stamp}"
    candidate = target / f"{base}.xlsx"
    counter = 2
    while candidate.exists():
        candidate = target / f"{base}_{counter}.xlsx"
        counter += 1
    return candidate


def card_pattern(card: str) -> re.Pattern[str]:
    """Regex khớp số thẻ bất kể phần che giữa là "..." hay "XXXXXX"."""
    digits = re.findall(r"\d+", card)
    if len(digits) < 2:
        raise ValueError(f"Số thẻ không hợp lệ: {card!r} (cần dạng 402156...0740)")
    return re.compile(rf"{digits[0]}\s*[.xX*\s]{{0,12}}\s*{digits[-1]}")


def group_key(line_item_text: str) -> str:
    """Khóa gộp nhóm: có số thẻ thì gộp theo thẻ, không thì gộp theo nội dung."""
    matched = CARD_IN_TEXT.search(line_item_text)
    if matched:
        return f"SO THE {matched.group(1)}...{matched.group(2)}"
    return " ".join(line_item_text.split()) or "(không có nội dung)"


def to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return None


def find_header_row(worksheet: Any) -> tuple[int, dict[str, int]]:
    """Dò hàng tiêu đề chứa "Line Item Text" và "Amount"."""
    for row in range(1, min(worksheet.max_row, 60) + 1):
        headers = {
            header_text(worksheet.cell(row, col).value): col
            for col in range(1, worksheet.max_column + 1)
        }
        if HEADER_TEXT in headers and HEADER_AMOUNT in headers:
            return row, headers
    raise ValueError(
        f'Không tìm thấy hàng tiêu đề có "{HEADER_TEXT}" và "{HEADER_AMOUNT}". '
        "File này có phải bảng đối chiếu lịch sử giao dịch không?"
    )


def find_last_data_row(worksheet: Any, first_row: int, amount_col: int) -> int:
    """Hàng dữ liệu cuối = hàng cuối cùng có Amount là số (bỏ khối báo cáo cũ)."""
    last = first_row - 1
    for row in range(first_row, worksheet.max_row + 1):
        if to_decimal(worksheet.cell(row, amount_col).value) is not None:
            last = row
    return last


def reset_cell(cell: Any) -> None:
    cell.value = None
    cell.fill = PatternFill()
    cell.font = Font()
    cell.border = Border()
    cell.alignment = Alignment()
    cell.number_format = "General"


def clear_previous_marks(
    worksheet: Any, first_row: int, last_row: int, last_col: int
) -> None:
    """Xóa vệt tô của lần chạy trước, giữ nguyên mọi định dạng gốc khác."""
    for row in range(first_row, last_row + 1):
        for col in range(1, last_col + 1):
            cell = worksheet.cell(row, col)
            if text(cell.fill.start_color.rgb).upper() in HIGHLIGHT_VARIANTS:
                cell.fill = PatternFill()
                cell.font = Font()


def month_of(value: Any) -> str:
    """Lấy "MM/YYYY" từ Value Date dạng "31.07.2026" hoặc datetime."""
    if hasattr(value, "strftime"):
        return value.strftime("%m/%Y")
    matched = re.match(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text(value))
    if matched:
        return f"{int(matched.group(2)):02d}/{matched.group(3)}"
    return ""


def process(
    source: Path,
    output: Path | None = None,
    card: str = DEFAULT_CARD,
    report_col: str = DEFAULT_REPORT_COL,
    sheet: str | None = None,
    log: Callable[[str], None] = print,
) -> Result:
    """Đọc file nguồn, ghi kết quả ra file mới. File nguồn không bị đụng tới."""
    source = Path(source)
    if not source.exists():
        raise ValueError(f"Không tìm thấy file: {source}")
    output = Path(output) if output else default_output_path(source)

    pattern = card_pattern(card)
    try:
        report_index = column_index_from_string(str(report_col).strip().upper())
    except ValueError:
        raise ValueError(f"Cột báo cáo không hợp lệ: {report_col!r}")

    log(f"Đọc: {source.name}")
    workbook = load_workbook(source)
    worksheet = workbook[sheet] if sheet else workbook.worksheets[0]
    log(f"Sheet: {worksheet.title}")

    header_row, headers = find_header_row(worksheet)
    amount_col = headers[HEADER_AMOUNT]
    label_col = headers[HEADER_TEXT]
    date_col = headers.get(HEADER_DATE, 0)
    # Bề rộng bảng = cột cuối có tiêu đề; không dùng max_column vì file đã xử lý
    # trước đó có báo cáo nằm ngoài bảng làm max_column nở ra
    data_last_col = max(col for name, col in headers.items() if name)
    first_data_row = header_row + 1
    last_data_row = find_last_data_row(worksheet, first_data_row, amount_col)
    log(
        f"Tiêu đề hàng {header_row} | Amount = cột {get_column_letter(amount_col)}"
        f" | Line Item Text = cột {get_column_letter(label_col)}"
    )
    log(f"Dữ liệu: hàng {first_data_row} -> {last_data_row}")

    if report_index <= data_last_col:
        raise ValueError(
            f"Cột báo cáo {get_column_letter(report_index)} đè lên vùng dữ liệu "
            f"(bảng chạy tới cột {get_column_letter(data_last_col)})."
        )

    # File nguồn có thể là kết quả của lần chạy trước -> dọn dấu vết cũ
    clear_previous_marks(worksheet, first_data_row, last_data_row, data_last_col)
    for row in range(last_data_row + 1, worksheet.max_row + 1):
        for col in range(1, max(data_last_col, report_index + 1) + 1):
            reset_cell(worksheet.cell(row, col))
    for row in range(1, REPORT_SCAN_ROWS + 1):
        reset_cell(worksheet.cell(row, report_index))
        reset_cell(worksheet.cell(row, report_index + 1))

    buckets: dict[str, list[Any]] = {}
    card_keys: list[str] = []
    total = Decimal(0)
    highlighted = 0
    skipped: list[int] = []
    months: Counter[str] = Counter()

    for row in range(first_data_row, last_data_row + 1):
        line_text = text(worksheet.cell(row, label_col).value)
        amount = to_decimal(worksheet.cell(row, amount_col).value)
        if amount is None:
            skipped.append(row)
            continue

        key = group_key(line_text)
        bucket = buckets.setdefault(key, [0, Decimal(0)])
        bucket[0] += 1
        bucket[1] += amount
        total += amount

        if date_col:
            month = month_of(worksheet.cell(row, date_col).value)
            if month:
                months[month] += 1

        if not pattern.search(line_text):
            continue
        if key not in card_keys:
            card_keys.append(key)
        highlighted += 1
        for col in range(1, data_last_col + 1):
            cell = worksheet.cell(row, col)
            cell.fill = HIGHLIGHT_FILL
            cell.font = HIGHLIGHT_FONT

    warnings: list[str] = []
    if skipped:
        warnings.append(
            f"{len(skipped)} hàng có Amount không phải số, đã bỏ qua: {skipped}"
        )
    if not highlighted:
        warnings.append(f"Không tìm thấy hàng nào khớp thẻ {card}.")

    # Nhóm của thẻ đang tìm lên đầu, còn lại xếp theo giá trị tuyệt đối giảm dần
    others = sorted(
        (k for k in buckets if k not in card_keys), key=lambda k: -abs(buckets[k][1])
    )
    groups = [
        Group(key, buckets[key][0], buckets[key][1], key in card_keys)
        for key in card_keys + others
    ]

    month_list = sorted(months)
    month_label = month_list[0] if len(month_list) == 1 else ""
    title = REPORT_TITLE if not month_label else f"{REPORT_TITLE} THÁNG {month_label}"

    cursor = 1
    head_label = worksheet.cell(cursor, report_index, title)
    head_value = worksheet.cell(cursor, report_index + 1, REPORT_VALUE_TITLE)
    for cell in (head_label, head_value):
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    head_value.alignment = Alignment(horizontal="right")

    for group in groups:
        cursor += 1
        label_cell = worksheet.cell(
            cursor, report_index, f"{group.key} ({group.count} giao dịch)"
        )
        value_cell = worksheet.cell(cursor, report_index + 1, group.amount)
        value_cell.number_format = MONEY_FORMAT
        if group.is_card:
            # Cùng màu với các hàng được tô để nhìn là biết dòng này ứng với vùng nào
            label_cell.font = CARD_ROW_FONT
            value_cell.font = CARD_ROW_FONT
            label_cell.fill = HIGHLIGHT_FILL
            value_cell.fill = HIGHLIGHT_FILL

    cursor += 1
    total_label = worksheet.cell(cursor, report_index, TOTAL_LABEL)
    total_value = worksheet.cell(cursor, report_index + 1, total)
    total_value.number_format = MONEY_FORMAT
    for cell in (total_label, total_value):
        cell.font = TOTAL_FONT
        cell.border = TOP_BORDER

    label_letter = get_column_letter(report_index)
    value_letter = get_column_letter(report_index + 1)
    worksheet.column_dimensions[label_letter].width = 52
    worksheet.column_dimensions[value_letter].width = 18

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        workbook.save(output)
    except PermissionError:
        raise ValueError(
            f"Không ghi được {output.name} — file đang mở trong Excel, đóng lại rồi thử lại."
        )

    log(f"Đã tô màu {highlighted} hàng khớp thẻ {card}.")
    for warning in warnings:
        log(f"Cảnh báo: {warning}")
    if len(month_list) > 1:
        log("Dữ liệu có nhiều tháng: " + ", ".join(month_list))
    for group in groups:
        log(f"  {group.amount:>16,.0f} | {group.count:>3} GD | {group.key}")
    log(f"  {total:>16,.0f} | {TOTAL_LABEL}")
    log(f"Đã lưu: {output}")

    return Result(
        source=source,
        output=output,
        sheet=worksheet.title,
        groups=groups,
        total=total,
        highlighted=highlighted,
        months=month_list,
        report_range=f"{label_letter}1:{value_letter}{cursor}",
        warnings=warnings,
    )


def latest_statement_in_downloads() -> Path | None:
    """Gợi ý file nguồn: ưu tiên file tên giống bảng đối chiếu, mới nhất trước.

    Không lấy đại file .xlsx mới nhất, vì Downloads thường lẫn nhiều file khác.
    """
    folder = downloads_dir()
    candidates = [
        item
        for item in folder.glob("*.xlsx")
        if item.is_file()
        and not item.name.startswith("~$")
        and OUTPUT_MARK not in item.name
    ]
    if not candidates:
        return None
    preferred = [
        item for item in candidates if STATEMENT_HINT in header_text(item.stem).replace(" ", "")
    ]
    return max(preferred or candidates, key=lambda item: item.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tô màu giao dịch theo số thẻ và tổng hợp Amount theo nhóm nội dung."
    )
    parser.add_argument("--file", default=None, help="File .xlsx nguồn")
    parser.add_argument("--out", default=None, help="File kết quả (mặc định: Downloads)")
    parser.add_argument("--sheet", default=None, help="Tên sheet (mặc định: sheet đầu)")
    parser.add_argument("--card", default=DEFAULT_CARD, help="Số thẻ cần tô màu, vd 402156...0740")
    parser.add_argument(
        "--report-col",
        default=DEFAULT_REPORT_COL,
        help=f"Cột ghi nhãn báo cáo (mặc định {DEFAULT_REPORT_COL})",
    )
    args = parser.parse_args()

    if args.file:
        source = Path(args.file)
    else:
        found = latest_statement_in_downloads()
        if not found:
            raise SystemExit(
                f"Không có .xlsx nào trong {downloads_dir()}. Chỉ định bằng --file."
            )
        source = found
        print(f"Không có --file, dùng file mới nhất trong Downloads: {source.name}")

    try:
        result = process(
            source=source,
            output=Path(args.out) if args.out else None,
            card=args.card,
            report_col=args.report_col,
            sheet=args.sheet,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))

    print(f"Báo cáo ghi tại {result.report_range}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
