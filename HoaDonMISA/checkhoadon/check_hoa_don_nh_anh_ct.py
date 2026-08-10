from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from copy import copy
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from shutil import copy2
from typing import Any

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: openpyxl. Install with: pip install openpyxl"
    ) from exc


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET_SHEET = "NH Anh CT"
DEFAULT_SOURCE_FILE = BASE_DIR / "QuanLy_NapTien_FacebookAd T7.xlsx"

# Tổng tiền theo phương thức thanh toán (thẻ)
DEFAULT_CARD_TOTAL = "Visa ···· 7040"
CARD_SUMMARY_SHEET = "Tong hop"
CARD_DETAIL_SHEET = "Chi tiet"
CARD_METHOD_SHEET = "Cac the trong file"
SOURCE_LABEL = "QuanLy_NapTien_FacebookAd"
GR_LABEL = "GR Chi phí ADS"

MONEY_FORMAT = "#,##0"
DATE_FORMAT = "dd/mm/yyyy"
REPORT_TITLE_FONT = Font(bold=True, size=14)
REPORT_LABEL_FONT = Font(bold=True)
REPORT_HEADER_FONT = Font(bold=True, color="FFFFFF")
REPORT_HEADER_FILL = PatternFill("solid", start_color="2563EB")
REPORT_TOTAL_FONT = Font(bold=True)
REPORT_TOP_BORDER = Border(top=Side(style="thin"))


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


def normalize_amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))

    value_text = text(value)
    if not value_text or value_text.startswith("="):
        return None

    value_text = value_text.replace("\xa0", "").replace(" ", "")
    if "," in value_text and "." in value_text:
        if value_text.rfind(",") > value_text.rfind("."):
            value_text = value_text.replace(".", "").replace(",", ".")
        else:
            value_text = value_text.replace(",", "")
    elif "," in value_text:
        parts = value_text.split(",")
        if len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            value_text = "".join(parts)
        else:
            value_text = value_text.replace(",", ".")
    elif "." in value_text:
        parts = value_text.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            value_text = "".join(parts)

    try:
        return Decimal(value_text)
    except InvalidOperation:
        return None


def amount_check_status(gr_amount: Any, source_amount: Any) -> str:
    gr_value = normalize_amount(gr_amount)
    source_value = normalize_amount(source_amount)
    if gr_value is None or source_value is None:
        return "Không kiểm tra được"
    return "Khớp" if gr_value == source_value else "Không khớp"


def add_amount_status(stats: dict, status: str) -> None:
    if status == "Khớp":
        stats["amount_ok"] += 1
    elif status == "Không khớp":
        stats["amount_mismatch"] += 1
    elif status == "Không tìm thấy":
        stats["amount_missing"] += 1
    else:
        stats["amount_unchecked"] += 1


def find_gr_file(base_dir: Path) -> Path:
    candidates = []
    ignored_parts = ("_backup_", "_ket_qua", "_da_doi_chieu", "_matched")
    for path in base_dir.glob("GR Chi*.xlsx"):
        stem_lower = path.stem.lower()
        if any(part in stem_lower for part in ignored_parts):
            continue
        candidates.append(path)

    if not candidates:
        raise FileNotFoundError(f"Cannot find GR Chi*.xlsx in {base_dir}")
    if len(candidates) > 1:
        names = "\n".join(f"- {path.name}" for path in candidates)
        raise RuntimeError(f"Found multiple GR files. Pass --gr explicitly:\n{names}")
    return candidates[0]


def has_account_id_in_name(sheet_name: str) -> bool:
    # Excel limits sheet names to 31 chars, so the final ")" can be missing.
    return re.search(r"\(\d{5,}\)?$", sheet_name) is not None


def is_payment_sheet(ws: Any) -> bool:
    return (
        header_text(ws.cell(1, 2).value) == "ngay thanh toan"
        and header_text(ws.cell(1, 3).value) == "so tien"
        and header_text(ws.cell(1, 4).value) == "phuong thuc tt"
        and header_text(ws.cell(1, 5).value) == "so tham chieu the"
    )


def is_target_header_row(ws: Any, row: int) -> bool:
    return (
        header_text(ws.cell(row, 2).value) == "ngay thanh toan"
        and header_text(ws.cell(row, 3).value) == "phuong thuc tt"
        and header_text(ws.cell(row, 4).value) == "so tham chieu the"
        and header_text(ws.cell(row, 5).value) == "so tien"
    )


def find_target_header_row(ws: Any) -> int | None:
    max_scan_row = min(ws.max_row or 0, 120)
    for row in range(1, max_scan_row + 1):
        if is_target_header_row(ws, row):
            return row
    return None


def count_target_rows(ws: Any) -> int:
    header_row = find_target_header_row(ws)
    if header_row is None:
        return 0

    count = 0
    for row in range(header_row + 1, ws.max_row + 1):
        method = text(ws.cell(row, 3).value)
        reference = text(ws.cell(row, 4).value)
        if method and reference:
            count += 1
    return count


def get_target_sheet_options(gr_file: Path) -> list[tuple[str, int]]:
    wb = load_workbook(gr_file, data_only=False, read_only=False)
    options = []
    for sheet_name in wb.sheetnames:
        row_count = count_target_rows(wb[sheet_name])
        if row_count > 0:
            options.append((sheet_name, row_count))
    return options


def payment_record(ws: Any, sheet_name: str, row: int) -> dict:
    return {
        "sheet": sheet_name,
        "row": row,
        "date": ws.cell(row, 2).value,
        "amount": ws.cell(row, 3).value,
        "method": ws.cell(row, 4).value,
        "reference": ws.cell(row, 5).value,
    }


def build_payment_index(
    source_file: Path,
    only_id_sheets: bool,
) -> tuple[dict, dict, dict, dict, dict, list]:
    wb = load_workbook(source_file, data_only=False, read_only=False)
    rows_by_key = defaultdict(list)
    rows_by_reference = defaultdict(list)
    cells_by_value = defaultdict(list)
    scanned_sheets = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                cell_text = text(cell.value)
                if cell_text:
                    cells_by_value[cell_text].append((sheet_name, cell.coordinate))

        if not is_payment_sheet(ws):
            continue

        record_count = 0
        for row in range(2, ws.max_row + 1):
            method = text(ws.cell(row, 4).value)
            reference = text(ws.cell(row, 5).value)
            if not method or not reference:
                continue

            record_count += 1
            record = payment_record(ws, sheet_name, row)
            rows_by_reference[reference].append(record)
            if not only_id_sheets or has_account_id_in_name(sheet_name):
                rows_by_key[(method, reference)].append(record)

        scanned_sheets.append((sheet_name, record_count))

    unique_index = {
        key: rows[0] for key, rows in rows_by_key.items() if len(rows) == 1
    }
    duplicates = {key: rows for key, rows in rows_by_key.items() if len(rows) > 1}
    reference_index = {
        reference: rows[0] for reference, rows in rows_by_reference.items() if len(rows) == 1
    }
    reference_duplicates = {
        reference: rows for reference, rows in rows_by_reference.items() if len(rows) > 1
    }
    return (
        unique_index,
        duplicates,
        reference_index,
        reference_duplicates,
        cells_by_value,
        scanned_sheets,
    )


def new_stats() -> dict:
    return {
        "source_rows": 0,
        "matched": 0,
        "fallback_matched": 0,
        "found_in_file_only": 0,
        "amount_ok": 0,
        "amount_mismatch": 0,
        "amount_missing": 0,
        "amount_unchecked": 0,
        "misses": [],
        "found_anywhere": [],
        "ambiguous": [],
        "matched_by_sheet": Counter(),
    }


def merge_stats(total: dict, sheet_name: str, stats: dict) -> None:
    total["source_rows"] += stats["source_rows"]
    total["matched"] += stats["matched"]
    total["fallback_matched"] += stats["fallback_matched"]
    total["found_in_file_only"] += stats["found_in_file_only"]
    total["amount_ok"] += stats["amount_ok"]
    total["amount_mismatch"] += stats["amount_mismatch"]
    total["amount_missing"] += stats["amount_missing"]
    total["amount_unchecked"] += stats["amount_unchecked"]
    total["misses"].extend(
        (sheet_name, row, method, reference, amount)
        for row, method, reference, amount in stats["misses"]
    )
    total["found_anywhere"].extend(
        (sheet_name, row, method, reference, locations)
        for row, method, reference, locations in stats["found_anywhere"]
    )
    total["ambiguous"].extend(
        (sheet_name, row, method, reference, count)
        for row, method, reference, count in stats["ambiguous"]
    )
    total["matched_by_sheet"].update(stats["matched_by_sheet"])


def copy_output_style(ws: Any, row: int) -> None:
    style_sources = {
        6: ws.cell(row, 2),
        7: ws.cell(row, 5),
        8: ws.cell(row, 3),
        9: ws.cell(row, 4),
        10: ws.cell(row, 4),
        11: ws.cell(row, 4),
    }
    for col, source_cell in style_sources.items():
        target_cell = ws.cell(row, col)
        if source_cell.has_style:
            target_cell._style = copy(source_cell._style)
        target_cell.number_format = source_cell.number_format
        target_cell.alignment = copy(source_cell.alignment)
        target_cell.border = copy(source_cell.border)
        target_cell.fill = copy(source_cell.fill)
        target_cell.font = copy(source_cell.font)


def fill_worksheet(
    ws: Any,
    sheet_name: str,
    payment_index: dict,
    duplicates: dict,
    reference_index: dict,
    reference_duplicates: dict,
    cells_by_value: dict,
    dry_run: bool,
) -> dict:
    header_row = find_target_header_row(ws)
    if header_row is None:
        raise ValueError(f"Cannot find payment header row in sheet: {sheet_name}")

    stats = new_stats()
    if not dry_run:
        ws.cell(header_row, 10).value = "Ten tab nguon"
        ws.cell(header_row, 11).value = "Kiem tra so tien"

    for row in range(header_row + 1, ws.max_row + 1):
        method = text(ws.cell(row, 3).value)
        reference = text(ws.cell(row, 4).value)
        if not method and not reference:
            continue
        if not method or not reference:
            continue

        stats["source_rows"] += 1
        key = (method, reference)

        if not dry_run:
            for col in range(6, 12):
                ws.cell(row, col).value = None
            copy_output_style(ws, row)

        if key in duplicates:
            stats["ambiguous"].append((row, method, reference, len(duplicates[key])))
            add_amount_status(stats, "Trùng dữ liệu")
            if not dry_run:
                ws.cell(row, 11).value = "Trùng dữ liệu"
            continue

        fallback_used = False
        hit = payment_index.get(key)
        if not hit:
            if reference in reference_duplicates:
                stats["ambiguous"].append(
                    (row, method, reference, len(reference_duplicates[reference]))
                )
                add_amount_status(stats, "Trùng dữ liệu")
                if not dry_run:
                    ws.cell(row, 11).value = "Trùng dữ liệu"
                continue

            hit = reference_index.get(reference)
            if hit:
                fallback_used = True
            else:
                cell_hits = cells_by_value.get(reference, [])
                if cell_hits:
                    stats["found_in_file_only"] += 1
                    stats["found_anywhere"].append((row, method, reference, cell_hits))
                    add_amount_status(stats, "Tìm thấy toàn file")
                    if not dry_run:
                        location_text = "; ".join(
                            f"{hit_sheet}!{coordinate}"
                            for hit_sheet, coordinate in cell_hits[:3]
                        )
                        if len(cell_hits) > 3:
                            location_text += f"; +{len(cell_hits) - 3}"
                        ws.cell(row, 10).value = location_text
                        ws.cell(row, 11).value = "Tìm thấy toàn file"
                    continue

                stats["misses"].append((row, method, reference, ws.cell(row, 5).value))
                add_amount_status(stats, "Không tìm thấy")
                if not dry_run:
                    ws.cell(row, 11).value = "Không tìm thấy"
                continue

        stats["matched"] += 1
        if fallback_used:
            stats["fallback_matched"] += 1
        stats["matched_by_sheet"][hit["sheet"]] += 1
        amount_status = amount_check_status(ws.cell(row, 5).value, hit["amount"])
        add_amount_status(stats, amount_status)

        if dry_run:
            continue

        ws.cell(row, 6).value = hit["date"]
        ws.cell(row, 7).value = hit["amount"]
        ws.cell(row, 8).value = hit["method"]
        ws.cell(row, 9).value = hit["reference"]
        ws.cell(row, 10).value = hit["sheet"]
        ws.cell(row, 11).value = amount_status

    if not dry_run:
        ws.column_dimensions["J"].width = max(ws.column_dimensions["J"].width or 0, 34)
        ws.column_dimensions["K"].width = max(ws.column_dimensions["K"].width or 0, 20)

    return stats


def fill_target_sheet(
    gr_file: Path,
    sheet_name: str,
    payment_index: dict,
    duplicates: dict,
    reference_index: dict,
    reference_duplicates: dict,
    cells_by_value: dict,
    dry_run: bool,
) -> tuple[Any, dict]:
    wb = load_workbook(gr_file, data_only=False, read_only=False)
    if sheet_name not in wb.sheetnames:
        raise KeyError(f"Sheet not found in GR file: {sheet_name}")

    stats = fill_worksheet(
        ws=wb[sheet_name],
        sheet_name=sheet_name,
        payment_index=payment_index,
        duplicates=duplicates,
        reference_index=reference_index,
        reference_duplicates=reference_duplicates,
        cells_by_value=cells_by_value,
        dry_run=dry_run,
    )
    return wb, stats


def fill_target_sheets(
    gr_file: Path,
    sheet_names: list[str],
    payment_index: dict,
    duplicates: dict,
    reference_index: dict,
    reference_duplicates: dict,
    cells_by_value: dict,
    dry_run: bool,
) -> tuple[Any, dict, dict]:
    wb = load_workbook(gr_file, data_only=False, read_only=False)
    stats_by_sheet = {}
    total_stats = new_stats()

    for sheet_name in sheet_names:
        if sheet_name not in wb.sheetnames:
            raise KeyError(f"Sheet not found in GR file: {sheet_name}")

        stats = fill_worksheet(
            ws=wb[sheet_name],
            sheet_name=sheet_name,
            payment_index=payment_index,
            duplicates=duplicates,
            reference_index=reference_index,
            reference_duplicates=reference_duplicates,
            cells_by_value=cells_by_value,
            dry_run=dry_run,
        )
        stats_by_sheet[sheet_name] = stats
        merge_stats(total_stats, sheet_name, stats)

    return wb, stats_by_sheet, total_stats


def unique_path(candidate: Path) -> Path:
    """Không bao giờ đè file có sẵn: thêm _2, _3... nếu 2 lần chạy trùng tên."""
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        alternative = candidate.with_name(
            f"{candidate.stem}_{counter}{candidate.suffix}"
        )
        if not alternative.exists():
            return alternative
        counter += 1


def default_output_path(gr_file: Path, output_dir: Path | None = None) -> Path:
    """Kết quả mặc định ghi ra Downloads, tên kèm ngày giờ nên không đè bản cũ."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = output_dir or downloads_dir()
    suffix = gr_file.suffix or ".xlsx"
    return unique_path(folder / f"{gr_file.stem}_ket_qua_{stamp}{suffix}")


def backup_output_path(gr_file: Path, output_dir: Path | None = None) -> Path:
    """Bản backup trước khi ghi đè cũng để ở Downloads, không rải vào thư mục tool."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = output_dir or downloads_dir()
    suffix = gr_file.suffix or ".xlsx"
    return unique_path(folder / f"{gr_file.stem}_backup_{stamp}{suffix}")


def save_result(wb: Any, gr_file: Path, output_file: Path | None, overwrite: bool) -> Path:
    if overwrite:
        backup_file = backup_output_path(gr_file)
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        copy2(gr_file, backup_file)
        try:
            wb.save(gr_file)
            print(f"Backup: {backup_file}")
            return gr_file
        except PermissionError:
            fallback_file = output_file or default_output_path(gr_file)
            wb.save(fallback_file)
            print(f"Cannot overwrite GR file because it is open/locked: {gr_file}")
            print(f"Backup: {backup_file}")
            return fallback_file

    result_file = output_file or default_output_path(gr_file)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(result_file)
    return result_file


def method_key(value: Any) -> str:
    """Khóa so khớp phương thức TT: 4 số cuối nếu có, không thì phần chữ đã bỏ dấu.

    Nhờ vậy "Visa ···· 0740", "402156...0740" hay chỉ "0740" đều khớp nhau.
    """
    digit_runs = re.findall(r"\d+", text(value))
    if digit_runs:
        return digit_runs[-1][-4:]
    return header_text(value)


def scan_source_payment_rows(source_file: Path) -> list[dict]:
    """Mọi dòng giao dịch trong file QuanLy (tiêu đề hàng 1, Phương thức TT cột D)."""
    wb = load_workbook(source_file, data_only=True)
    rows = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if not is_payment_sheet(ws):
            continue
        for row in range(2, ws.max_row + 1):
            method = text(ws.cell(row, 4).value)
            if not method:
                continue

            # Vài dòng hợp lệ (Số dư trả trước, Khoản tín dụng quảng cáo) không có
            # số tham chiếu, nên chỉ bỏ dòng vừa thiếu tham chiếu vừa không có tiền.
            reference = text(ws.cell(row, 5).value)
            amount = normalize_amount(ws.cell(row, 3).value)
            if not reference and amount is None:
                continue

            rows.append(
                {
                    "sheet": sheet_name,
                    "row": row,
                    "date": ws.cell(row, 2).value,
                    "method": method,
                    "reference": reference,
                    "amount": amount,
                }
            )
    return rows


def scan_gr_payment_rows(gr_file: Path) -> list[dict]:
    """Mọi dòng giao dịch trong file GR (tiêu đề dò theo tab, Phương thức TT cột C)."""
    wb = load_workbook(gr_file, data_only=True)
    rows = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        header_row = find_target_header_row(ws)
        if header_row is None:
            continue
        for row in range(header_row + 1, ws.max_row + 1):
            method = text(ws.cell(row, 3).value)
            reference = text(ws.cell(row, 4).value)
            # Dòng giao dịch thật luôn có số tham chiếu; dòng "TỔNG" cuối bảng thì không.
            if not method or not reference:
                continue
            rows.append(
                {
                    "sheet": sheet_name,
                    "row": row,
                    "date": ws.cell(row, 2).value,
                    "method": method,
                    "reference": reference,
                    "amount": normalize_amount(ws.cell(row, 5).value),
                }
            )
    return rows


def card_summary(rows: list[dict], wanted_key: str) -> dict:
    matched = [item for item in rows if method_key(item["method"]) == wanted_key]
    readable = [item for item in matched if item["amount"] is not None]
    by_sheet: dict[str, list] = {}
    for item in readable:
        bucket = by_sheet.setdefault(item["sheet"], [0, Decimal(0)])
        bucket[0] += 1
        bucket[1] += item["amount"]
    return {
        "rows": matched,
        "count": len(matched),
        "unreadable": len(matched) - len(readable),
        "total": sum((item["amount"] for item in readable), Decimal(0)),
        "labels": sorted({item["method"] for item in matched}),
        "by_sheet": by_sheet,
    }


def method_census(source_rows: list[dict], gr_rows: list[dict]) -> list[dict]:
    """Danh sách mọi phương thức TT có trong 2 file kèm số giao dịch và tổng tiền."""
    census: dict[str, dict] = {}
    for origin, rows in (("source", source_rows), ("gr", gr_rows)):
        for item in rows:
            key = method_key(item["method"])
            entry = census.setdefault(
                key,
                {
                    "key": key,
                    "labels": Counter(),
                    "source_count": 0,
                    "source_total": Decimal(0),
                    "gr_count": 0,
                    "gr_total": Decimal(0),
                },
            )
            entry["labels"][item["method"]] += 1
            entry[f"{origin}_count"] += 1
            if item["amount"] is not None:
                entry[f"{origin}_total"] += item["amount"]

    result = []
    for entry in census.values():
        entry["method"] = entry["labels"].most_common(1)[0][0]
        result.append(entry)
    result.sort(key=lambda entry: -(entry["source_count"] + entry["gr_count"]))
    return result


def downloads_dir() -> Path:
    """Thư mục Downloads thật của user (đọc registry để không sai khi đã đổi chỗ)."""
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(
                key, "{374DE290-123F-4565-9164-39C4925E467B}"
            )
        folder = Path(os.path.expandvars(value))
        if folder.is_dir():
            return folder
    except Exception:
        pass

    folder = Path.home() / "Downloads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def card_total_output_path(card_key: str, output_dir: Path | None = None) -> Path:
    safe_key = re.sub(r"[^0-9A-Za-z]+", "_", card_key).strip("_")[:40] or "the"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = output_dir or downloads_dir()
    return folder / f"Tong_tien_the_{safe_key}_{stamp}.xlsx"


def write_header_row(ws: Any, row: int, titles: list[str]) -> None:
    for col, title in enumerate(titles, start=1):
        cell = ws.cell(row, col, title)
        cell.font = REPORT_HEADER_FONT
        cell.fill = REPORT_HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")


def set_column_widths(ws: Any, widths: dict[str, int]) -> None:
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width


def write_card_total_report(
    card_input: str,
    card_key: str,
    source_file: Path,
    gr_file: Path,
    source_summary: dict,
    gr_summary: dict,
    census: list[dict],
    output_file: Path,
) -> Path:
    wb = Workbook()

    ws = wb.active
    ws.title = CARD_SUMMARY_SHEET
    ws["A1"] = "TỔNG TIỀN THEO PHƯƠNG THỨC THANH TOÁN"
    ws["A1"].font = REPORT_TITLE_FONT
    for row, (label, value) in enumerate(
        (
            ("Phương thức TT cần tìm:", card_input),
            ("Khớp theo 4 số cuối:", card_key),
            ("Thời điểm xuất:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
        ),
        start=2,
    ):
        ws.cell(row, 1, label).font = REPORT_LABEL_FONT
        ws.cell(row, 2, value)

    header_row = 6
    write_header_row(
        ws,
        header_row,
        ["Nguồn dữ liệu", "Tệp", "Phương thức TT khớp", "Số giao dịch", "Tổng tiền"],
    )

    row = header_row
    for label, path, summary in (
        (SOURCE_LABEL, source_file, source_summary),
        (GR_LABEL, gr_file, gr_summary),
    ):
        row += 1
        ws.cell(row, 1, label)
        ws.cell(row, 2, path.name)
        ws.cell(row, 3, ", ".join(summary["labels"]) or "(không tìm thấy)")
        ws.cell(row, 4, summary["count"])
        ws.cell(row, 5, summary["total"]).number_format = MONEY_FORMAT

    row += 1
    ws.cell(row, 1, "TỔNG CỘNG")
    ws.cell(row, 4, source_summary["count"] + gr_summary["count"])
    ws.cell(row, 5, source_summary["total"] + gr_summary["total"]).number_format = (
        MONEY_FORMAT
    )
    for col in range(1, 6):
        ws.cell(row, col).font = REPORT_TOTAL_FONT
        ws.cell(row, col).border = REPORT_TOP_BORDER

    unreadable = source_summary["unreadable"] + gr_summary["unreadable"]
    if unreadable:
        ws.cell(
            row + 2,
            1,
            f"Cảnh báo: {unreadable} dòng khớp thẻ nhưng không đọc được số tiền.",
        )
    set_column_widths(ws, {"A": 26, "B": 42, "C": 34, "D": 14, "E": 18})

    detail = wb.create_sheet(CARD_DETAIL_SHEET)
    write_header_row(
        detail,
        1,
        [
            "Nguồn dữ liệu",
            "Tab",
            "Dòng",
            "Ngày thanh toán",
            "Phương thức TT",
            "Số tham chiếu thẻ",
            "Số tiền",
        ],
    )
    detail_row = 1
    for label, summary in ((SOURCE_LABEL, source_summary), (GR_LABEL, gr_summary)):
        for item in summary["rows"]:
            detail_row += 1
            detail.cell(detail_row, 1, label)
            detail.cell(detail_row, 2, item["sheet"])
            detail.cell(detail_row, 3, item["row"])
            date_cell = detail.cell(detail_row, 4, item["date"])
            if isinstance(item["date"], datetime):
                date_cell.number_format = DATE_FORMAT
            detail.cell(detail_row, 5, item["method"])
            detail.cell(detail_row, 6, item["reference"])
            detail.cell(detail_row, 7, item["amount"]).number_format = MONEY_FORMAT
    detail.freeze_panes = "A2"
    set_column_widths(
        detail, {"A": 26, "B": 32, "C": 8, "D": 20, "E": 20, "F": 20, "G": 18}
    )

    methods = wb.create_sheet(CARD_METHOD_SHEET)
    write_header_row(
        methods,
        1,
        [
            "Phương thức TT",
            "4 số cuối",
            f"Số GD {SOURCE_LABEL}",
            f"Tổng tiền {SOURCE_LABEL}",
            f"Số GD {GR_LABEL}",
            f"Tổng tiền {GR_LABEL}",
        ],
    )
    for index, entry in enumerate(census, start=2):
        methods.cell(index, 1, entry["method"])
        methods.cell(index, 2, entry["key"])
        methods.cell(index, 3, entry["source_count"])
        methods.cell(index, 4, entry["source_total"]).number_format = MONEY_FORMAT
        methods.cell(index, 5, entry["gr_count"])
        methods.cell(index, 6, entry["gr_total"]).number_format = MONEY_FORMAT
    methods.freeze_panes = "A2"
    set_column_widths(methods, {"A": 24, "B": 12, "C": 16, "D": 22, "E": 16, "F": 22})

    output_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_file)
    return output_file


def format_card_total_summary(
    card_input: str,
    card_key: str,
    source_file: Path,
    gr_file: Path,
    source_summary: dict,
    gr_summary: dict,
    census: list[dict],
    output_file: Path | None,
) -> str:
    lines = [
        f"Phương thức TT cần tìm: {card_input}  (khớp 4 số cuối: {card_key})",
        "",
        f"{SOURCE_LABEL} ({source_file.name}): "
        f"{source_summary['count']} giao dịch | {source_summary['total']:,}",
        f"{GR_LABEL} ({gr_file.name}): "
        f"{gr_summary['count']} giao dịch | {gr_summary['total']:,}",
        f"TỔNG CỘNG: {source_summary['count'] + gr_summary['count']} giao dịch | "
        f"{source_summary['total'] + gr_summary['total']:,}",
    ]

    unreadable = source_summary["unreadable"] + gr_summary["unreadable"]
    if unreadable:
        lines.append(f"Cảnh báo: {unreadable} dòng không đọc được số tiền.")

    for label, summary in ((SOURCE_LABEL, source_summary), (GR_LABEL, gr_summary)):
        if not summary["by_sheet"]:
            continue
        lines.append("")
        lines.append(f"Chi tiết theo tab - {label}:")
        for sheet_name, (count, total) in sorted(
            summary["by_sheet"].items(), key=lambda item: -item[1][1]
        ):
            lines.append(f"- {sheet_name}: {count} GD | {total:,}")

    if source_summary["count"] == 0 and gr_summary["count"] == 0:
        lines.append("")
        lines.append(f"Không có giao dịch nào khớp {card_input}.")

    lines.append("")
    lines.append("Các phương thức TT có trong 2 file:")
    for entry in census:
        lines.append(
            f"- {entry['method']}: QuanLy {entry['source_count']} GD "
            f"({entry['source_total']:,}) | GR {entry['gr_count']} GD "
            f"({entry['gr_total']:,})"
        )

    if output_file:
        lines.append("")
        lines.append(f"Đã lưu: {output_file}")

    return "\n".join(lines)


def export_card_total(
    source_file: Path,
    gr_file: Path,
    card_input: str,
    output_file: Path | None = None,
) -> tuple[Path, str]:
    """Tổng tiền của một thẻ ở từng file, xuất ra workbook mới (mặc định ở Downloads)."""
    card_key = method_key(card_input)
    if not card_key:
        raise ValueError("Chưa nhập phương thức thanh toán cần tổng hợp.")

    source_rows = scan_source_payment_rows(source_file)
    gr_rows = scan_gr_payment_rows(gr_file)
    census = method_census(source_rows, gr_rows)
    source_summary = card_summary(source_rows, card_key)
    gr_summary = card_summary(gr_rows, card_key)

    target = output_file or card_total_output_path(card_key)
    write_card_total_report(
        card_input=card_input,
        card_key=card_key,
        source_file=source_file,
        gr_file=gr_file,
        source_summary=source_summary,
        gr_summary=gr_summary,
        census=census,
        output_file=target,
    )
    summary_text = format_card_total_summary(
        card_input=card_input,
        card_key=card_key,
        source_file=source_file,
        gr_file=gr_file,
        source_summary=source_summary,
        gr_summary=gr_summary,
        census=census,
        output_file=target,
    )
    return target, summary_text


def format_summary(
    scanned_sheets: list,
    stats: dict,
    result_file: Path | None,
    stats_by_sheet: dict | None = None,
) -> str:
    lines = [
        f"Payment sheets scanned: {len(scanned_sheets)}",
        f"Payment records scanned: {sum(count for _, count in scanned_sheets)}",
        f"GR source rows: {stats['source_rows']}",
        f"Matched rows: {stats['matched']}",
        f"Fallback matched by reference: {stats['fallback_matched']}",
        f"Found in file only: {stats['found_in_file_only']}",
        f"Missing rows: {len(stats['misses'])}",
        f"Ambiguous rows: {len(stats['ambiguous'])}",
        (
            "Amount check: "
            f"Khớp {stats['amount_ok']}, "
            f"Không khớp {stats['amount_mismatch']}, "
            f"Không tìm thấy {stats['amount_missing']}, "
            f"Không kiểm tra được {stats['amount_unchecked']}"
        ),
    ]

    if stats_by_sheet:
        lines.append("")
        lines.append("Target sheets:")
        for sheet_name, sheet_stats in stats_by_sheet.items():
            lines.append(
                f"- {sheet_name}: {sheet_stats['matched']}/{sheet_stats['source_rows']} matched, "
                f"{sheet_stats['fallback_matched']} fallback, "
                f"{sheet_stats['found_in_file_only']} found-only, "
                f"{len(sheet_stats['misses'])} missing, "
                f"{sheet_stats['amount_ok']} amount OK, "
                f"{sheet_stats['amount_mismatch']} amount mismatch"
            )

    if stats["found_anywhere"]:
        lines.append("")
        lines.append("Found in file only:")
        for item in stats["found_anywhere"][:30]:
            if len(item) == 5:
                sheet_name, row, method, reference, locations = item
                location_text = "; ".join(
                    f"{hit_sheet}!{coordinate}"
                    for hit_sheet, coordinate in locations[:3]
                )
                if len(locations) > 3:
                    location_text += f"; +{len(locations) - 3}"
                lines.append(
                    f"- {sheet_name} row {row}: {method} | {reference} | {location_text}"
                )
            else:
                row, method, reference, locations = item
                location_text = "; ".join(
                    f"{hit_sheet}!{coordinate}"
                    for hit_sheet, coordinate in locations[:3]
                )
                lines.append(f"- Row {row}: {method} | {reference} | {location_text}")

    if stats["matched_by_sheet"]:
        lines.append("")
        lines.append("Matched by source sheet:")
        for sheet_name, count in stats["matched_by_sheet"].most_common():
            lines.append(f"- {sheet_name}: {count}")

    if stats["misses"]:
        lines.append("")
        lines.append("First missing rows:")
        for item in stats["misses"][:30]:
            if len(item) == 5:
                sheet_name, row, method, reference, amount = item
                lines.append(f"- {sheet_name} row {row}: {method} | {reference} | {amount}")
            else:
                row, method, reference, amount = item
                lines.append(f"- Row {row}: {method} | {reference} | {amount}")

    if stats["ambiguous"]:
        lines.append("")
        lines.append("First ambiguous rows:")
        for item in stats["ambiguous"][:30]:
            if len(item) == 5:
                sheet_name, row, method, reference, count = item
                lines.append(
                    f"- {sheet_name} row {row}: {method} | {reference} | {count} matches"
                )
            else:
                row, method, reference, count = item
                lines.append(f"- Row {row}: {method} | {reference} | {count} matches")

    if result_file:
        lines.append("")
        lines.append(f"Saved: {result_file}")

    return "\n".join(lines)


def print_summary(
    scanned_sheets: list,
    stats: dict,
    result_file: Path | None,
    stats_by_sheet: dict | None = None,
) -> None:
    print(format_summary(scanned_sheets, stats, result_file, stats_by_sheet))


def center_on_screen(win: Any, w: int | None = None, h: int | None = None) -> None:
    """Đưa cửa sổ ra giữa màn hình; bỏ trống w/h thì giữ kích thước hiện tại."""
    win.update_idletasks()
    w = w or max(win.winfo_width(), win.winfo_reqwidth())
    h = h or max(win.winfo_height(), win.winfo_reqheight())
    screen_w, screen_h = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(w, screen_w), min(h, screen_h)
    win.geometry(f"{w}x{h}+{max(0, (screen_w - w) // 2)}+{max(0, (screen_h - h) // 2)}")


def launch_gui() -> None:
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Đối chiếu hóa đơn Facebook")
    center_on_screen(root, 1060, 845)
    root.minsize(900, 700)
    root.configure(bg="#eef2f7")
    root.option_add("*Font", ("Segoe UI", 10))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("App.TFrame", background="#eef2f7")
    style.configure("Card.TFrame", background="#ffffff", relief="flat")
    style.configure("Title.TLabel", background="#eef2f7", foreground="#0f172a", font=("Segoe UI", 17, "bold"))
    style.configure("Subtle.TLabel", background="#eef2f7", foreground="#64748b")
    style.configure("CardTitle.TLabel", background="#ffffff", foreground="#0f172a", font=("Segoe UI", 11, "bold"))
    style.configure("Card.TLabel", background="#ffffff", foreground="#334155")
    style.configure("Status.TLabel", background="#eef2f7", foreground="#475569")
    style.configure("TCheckbutton", background="#ffffff", foreground="#334155")
    style.configure("TEntry", padding=6)
    style.configure("TButton", padding=(12, 7))
    style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff", padding=(18, 9), font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#93c5fd")])

    try:
        default_gr = str(find_gr_file(BASE_DIR))
    except Exception:
        default_gr = ""

    gr_var = tk.StringVar(value=default_gr)
    source_var = tk.StringVar(value=str(DEFAULT_SOURCE_FILE))
    output_var = tk.StringVar(
        value=str(default_output_path(Path(default_gr))) if default_gr else ""
    )
    # Còn True nghĩa là ô "File xuất" vẫn là đường dẫn tool tự gợi ý -> mỗi lần chạy
    # sẽ làm mới ngày giờ để không đè kết quả lần trước.
    output_auto = True
    overwrite_var = tk.BooleanVar(value=False)
    only_id_var = tk.BooleanVar(value=False)
    dry_run_var = tk.BooleanVar(value=False)
    sound_var = tk.BooleanVar(value=True)
    card_var = tk.StringVar(value=DEFAULT_CARD_TOTAL)
    status_var = tk.StringVar(value="Sẵn sàng.")
    sheet_options: list[tuple[str, int]] = []
    busy_controls: list[Any] = []

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    app = ttk.Frame(root, style="App.TFrame", padding=18)
    app.grid(row=0, column=0, sticky="nsew")
    app.columnconfigure(0, weight=1)
    # Hàng 2 = danh sách tab + tùy chọn, hàng 5 = ô kết quả (ưu tiên giãn cho log).
    app.rowconfigure(2, weight=1, minsize=274)
    app.rowconfigure(5, weight=2, minsize=140)

    header = ttk.Frame(app, style="App.TFrame")
    header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
    header.columnconfigure(0, weight=1)
    ttk.Label(header, text="Đối chiếu hóa đơn Facebook", style="Title.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        header,
        text=(
            "Chọn nhiều tab CT trong file GR, ghi kết quả đối chiếu vào cột F:J. "
            "File xuất lưu ra Downloads, không đè bản cũ."
        ),
        style="Subtle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    file_card = ttk.Frame(app, style="Card.TFrame", padding=14)
    file_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
    file_card.columnconfigure(1, weight=1)
    ttk.Label(file_card, text="Tệp dữ liệu", style="CardTitle.TLabel").grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
    )

    def dialog_dir() -> str:
        """Hộp thoại chọn file luôn mở ở Downloads trước, vì file tải về nằm ở đó."""
        return str(downloads_dir())

    def refresh_output_suggestion() -> None:
        gr_text = gr_var.get().strip()
        if gr_text:
            output_var.set(str(default_output_path(Path(gr_text))))

    def choose_gr_file() -> None:
        path = filedialog.askopenfilename(
            title="Chọn file GR",
            initialdir=dialog_dir(),
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if not path:
            return
        gr_var.set(path)
        if output_auto:
            refresh_output_suggestion()
        load_sheets()

    def choose_source_file() -> None:
        path = filedialog.askopenfilename(
            title="Chọn file QuanLy_NapTien",
            initialdir=dialog_dir(),
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            source_var.set(path)

    def choose_output_file() -> None:
        nonlocal output_auto
        current = Path(output_var.get().strip()) if output_var.get().strip() else None
        path = filedialog.asksaveasfilename(
            title="Chọn file xuất",
            initialdir=dialog_dir(),
            initialfile=current.name if current else "",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            output_var.set(path)
            output_auto = False

    def add_file_row(row: int, label: str, variable: tk.StringVar, command: Any) -> tuple[Any, Any]:
        ttk.Label(file_card, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", pady=4
        )
        entry = ttk.Entry(file_card, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=10, pady=4)
        button = ttk.Button(file_card, text="Chọn...", command=command)
        button.grid(row=row, column=2, sticky="ew", pady=4)
        busy_controls.extend([entry, button])
        return entry, button

    add_file_row(1, "File GR", gr_var, choose_gr_file)
    add_file_row(2, "File QuanLy", source_var, choose_source_file)
    output_entry, output_button = add_file_row(
        3, "File xuất (Downloads)", output_var, choose_output_file
    )

    main_area = ttk.Frame(app, style="App.TFrame")
    main_area.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
    main_area.columnconfigure(0, weight=3)
    main_area.columnconfigure(1, weight=2)
    main_area.rowconfigure(0, weight=1)

    sheet_card = ttk.Frame(main_area, style="Card.TFrame", padding=14)
    sheet_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    sheet_card.columnconfigure(0, weight=1)
    sheet_card.rowconfigure(2, weight=1)

    ttk.Label(sheet_card, text="Tab cần xử lý", style="CardTitle.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        sheet_card,
        text="Giữ Ctrl hoặc Shift để chọn nhiều tab.",
        style="Card.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(3, 10))

    list_container = ttk.Frame(sheet_card, style="Card.TFrame")
    list_container.grid(row=2, column=0, sticky="nsew")
    list_container.columnconfigure(0, weight=1)
    list_container.rowconfigure(0, weight=1)

    sheet_list = tk.Listbox(
        list_container,
        selectmode=tk.EXTENDED,
        height=8,
        exportselection=False,
        activestyle="none",
        bg="#ffffff",
        fg="#0f172a",
        selectbackground="#2563eb",
        selectforeground="#ffffff",
        relief="solid",
        borderwidth=1,
        highlightthickness=0,
        font=("Segoe UI", 10),
    )
    sheet_list.grid(row=0, column=0, sticky="nsew")
    sheet_scroll = ttk.Scrollbar(
        list_container, orient="vertical", command=sheet_list.yview
    )
    sheet_scroll.grid(row=0, column=1, sticky="ns")
    sheet_list.configure(yscrollcommand=sheet_scroll.set)
    busy_controls.append(sheet_list)

    sheet_buttons = ttk.Frame(sheet_card, style="Card.TFrame")
    sheet_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    reload_button = ttk.Button(sheet_buttons, text="Tải lại", command=lambda: load_sheets())
    select_all_button = ttk.Button(sheet_buttons, text="Chọn tất cả", command=lambda: select_all_sheets())
    clear_button = ttk.Button(sheet_buttons, text="Bỏ chọn", command=lambda: clear_sheet_selection())
    reload_button.pack(side="left", padx=(0, 8))
    select_all_button.pack(side="left", padx=(0, 8))
    clear_button.pack(side="left")
    busy_controls.extend([reload_button, select_all_button, clear_button])

    option_card = ttk.Frame(main_area, style="Card.TFrame", padding=14)
    option_card.grid(row=0, column=1, sticky="nsew")
    option_card.columnconfigure(0, weight=1)
    ttk.Label(option_card, text="Tùy chọn", style="CardTitle.TLabel").grid(
        row=0, column=0, sticky="w", pady=(0, 8)
    )
    overwrite_check = ttk.Checkbutton(
        option_card,
        text="Ghi đè file GR và tạo backup",
        variable=overwrite_var,
    )
    overwrite_check.grid(row=1, column=0, sticky="w", pady=4)
    only_id_check = ttk.Checkbutton(
        option_card,
        text="Chỉ quét tab nguồn có mã trong ngoặc",
        variable=only_id_var,
    )
    only_id_check.grid(row=2, column=0, sticky="w", pady=4)
    dry_run_check = ttk.Checkbutton(
        option_card,
        text="Chạy thử, không lưu file",
        variable=dry_run_var,
    )
    dry_run_check.grid(row=3, column=0, sticky="w", pady=4)
    sound_check = ttk.Checkbutton(
        option_card,
        text="Phát âm báo khi xong",
        variable=sound_var,
    )
    sound_check.grid(row=4, column=0, sticky="w", pady=4)
    busy_controls.extend([overwrite_check, only_id_check, dry_run_check, sound_check])

    action_row = ttk.Frame(app, style="App.TFrame")
    action_row.grid(row=3, column=0, sticky="ew", pady=(0, 12))
    action_row.columnconfigure(1, weight=1)

    run_button = ttk.Button(
        action_row,
        text="Chạy đối chiếu",
        style="Accent.TButton",
        command=lambda: run_job(),
    )
    run_button.grid(row=0, column=0, sticky="w")
    progress = ttk.Progressbar(action_row, mode="indeterminate")
    progress.grid(row=0, column=1, sticky="ew", padx=12)
    ttk.Label(action_row, textvariable=status_var, style="Status.TLabel").grid(
        row=0, column=2, sticky="e"
    )
    busy_controls.append(run_button)

    card_card = ttk.Frame(app, style="Card.TFrame", padding=10)
    card_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
    card_card.columnconfigure(2, weight=1)
    ttk.Label(card_card, text="Tổng tiền theo thẻ", style="CardTitle.TLabel").grid(
        row=0, column=0, sticky="w", padx=(4, 10)
    )
    card_combo = ttk.Combobox(card_card, textvariable=card_var, width=24)
    card_combo.grid(row=0, column=1, sticky="w")
    ttk.Label(
        card_card,
        text="Nhập 4 số cuối (vd 7040) hoặc chọn trong danh sách. Xuất 1 file mới ở Downloads.",
        style="Card.TLabel",
    ).grid(row=0, column=2, sticky="w", padx=12)
    load_cards_button = ttk.Button(
        card_card, text="Tải DS thẻ", command=lambda: load_card_methods()
    )
    load_cards_button.grid(row=0, column=3, sticky="e", padx=(0, 8))
    card_total_button = ttk.Button(
        card_card,
        text="Xuất tổng tiền",
        style="Accent.TButton",
        command=lambda: run_card_total(),
    )
    card_total_button.grid(row=0, column=4, sticky="e")
    busy_controls.extend([card_combo, load_cards_button, card_total_button])

    log_card = ttk.Frame(app, style="Card.TFrame", padding=14)
    log_card.grid(row=5, column=0, sticky="nsew")
    log_card.columnconfigure(0, weight=1)
    log_card.rowconfigure(1, weight=1)
    ttk.Label(log_card, text="Kết quả", style="CardTitle.TLabel").grid(
        row=0, column=0, sticky="w", pady=(0, 10)
    )

    log_text = tk.Text(
        log_card,
        height=6,
        wrap="word",
        bg="#0f172a",
        fg="#e2e8f0",
        insertbackground="#e2e8f0",
        relief="flat",
        borderwidth=0,
        padx=12,
        pady=10,
        font=("Consolas", 10),
    )
    log_text.grid(row=1, column=0, sticky="nsew")
    log_scroll = ttk.Scrollbar(log_card, orient="vertical", command=log_text.yview)
    log_scroll.grid(row=1, column=1, sticky="ns")
    log_text.configure(yscrollcommand=log_scroll.set, state="disabled")

    def set_log(message: str) -> None:
        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.insert("1.0", message)
        log_text.configure(state="disabled")

    def set_busy(is_busy: bool, message: str) -> None:
        status_var.set(message)
        root.configure(cursor="watch" if is_busy else "")
        for control in busy_controls:
            try:
                control.configure(state="disabled" if is_busy else "normal")
            except tk.TclError:
                pass
        if is_busy:
            progress.start(12)
        else:
            progress.stop()
            update_output_state()

    def update_output_state(*_args: Any) -> None:
        state = "disabled" if dry_run_var.get() else "normal"
        output_entry.configure(state=state)
        output_button.configure(state=state)

    def play_done_sound(success: bool = True) -> None:
        if not sound_var.get():
            return
        try:
            import winsound

            winsound.Beep(880 if success else 440, 220)
        except Exception:
            try:
                root.bell()
            except tk.TclError:
                pass

    def load_sheets() -> None:
        nonlocal sheet_options
        sheet_list.delete(0, "end")
        sheet_options = []

        gr_path = Path(gr_var.get().strip())
        if not gr_path.exists():
            status_var.set("Chưa tìm thấy file GR.")
            set_log(f"Không tìm thấy file GR:\n{gr_path}")
            return

        try:
            sheet_options = get_target_sheet_options(gr_path)
        except Exception as exc:
            status_var.set("Lỗi khi đọc danh sách tab.")
            set_log(f"Lỗi khi đọc danh sách tab:\n{exc}")
            return

        for sheet_name, row_count in sheet_options:
            sheet_list.insert("end", f"{sheet_name}    {row_count} dòng")

        for index, (sheet_name, _row_count) in enumerate(sheet_options):
            if sheet_name == DEFAULT_TARGET_SHEET:
                sheet_list.selection_set(index)
                sheet_list.see(index)
                break

        status_var.set(f"Đã tải {len(sheet_options)} tab.")
        set_log(f"Đã tải {len(sheet_options)} tab có bảng Facebook Billing.")

    def select_all_sheets() -> None:
        if sheet_options:
            sheet_list.selection_set(0, "end")
            status_var.set(f"Đã chọn {len(sheet_options)} tab.")

    def clear_sheet_selection() -> None:
        sheet_list.selection_clear(0, "end")
        status_var.set("Đã bỏ chọn tab.")

    def selected_sheet_names() -> list[str]:
        return [sheet_options[index][0] for index in sheet_list.curselection()]

    def finish_success(summary: str) -> None:
        set_log(summary)
        set_busy(False, "Hoàn tất.")
        play_done_sound(True)

    def finish_error(error_message: str) -> None:
        set_log(f"Lỗi khi chạy đối chiếu:\n{error_message}")
        set_busy(False, "Có lỗi khi xử lý.")
        play_done_sound(False)
        messagebox.showerror("Lỗi", error_message)

    def run_job() -> None:
        if output_auto:
            refresh_output_suggestion()
        gr_path = Path(gr_var.get().strip())
        source_path = Path(source_var.get().strip())
        output_path = Path(output_var.get().strip()) if output_var.get().strip() else None
        sheets = selected_sheet_names()

        if not gr_path.exists():
            messagebox.showerror("Thiếu file", f"Không tìm thấy file GR:\n{gr_path}")
            return
        if not source_path.exists():
            messagebox.showerror(
                "Thiếu file", f"Không tìm thấy file QuanLy:\n{source_path}"
            )
            return
        if not sheets:
            messagebox.showerror("Chưa chọn tab", "Hãy chọn ít nhất một tab cần xử lý.")
            return

        dry_run = dry_run_var.get()
        overwrite = overwrite_var.get()
        only_id_sheets = only_id_var.get()
        set_busy(True, "Đang xử lý...")
        set_log("Đang đối chiếu dữ liệu, vui lòng chờ...")

        def worker() -> None:
            try:
                (
                    payment_index,
                    duplicates,
                    reference_index,
                    reference_duplicates,
                    cells_by_value,
                    scanned_sheets,
                ) = build_payment_index(source_path, only_id_sheets)
                wb, stats_by_sheet, total_stats = fill_target_sheets(
                    gr_file=gr_path,
                    sheet_names=sheets,
                    payment_index=payment_index,
                    duplicates=duplicates,
                    reference_index=reference_index,
                    reference_duplicates=reference_duplicates,
                    cells_by_value=cells_by_value,
                    dry_run=dry_run,
                )

                result_file = None
                if not dry_run:
                    result_file = save_result(
                        wb=wb,
                        gr_file=gr_path,
                        output_file=output_path,
                        overwrite=overwrite,
                    )

                summary = format_summary(
                    scanned_sheets=scanned_sheets,
                    stats=total_stats,
                    result_file=result_file,
                    stats_by_sheet=stats_by_sheet,
                )
                root.after(0, lambda: finish_success(summary))
            except Exception as exc:
                root.after(0, lambda message=str(exc): finish_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def card_job_paths() -> tuple[Path, Path] | None:
        gr_path = Path(gr_var.get().strip())
        source_path = Path(source_var.get().strip())
        if not gr_path.exists():
            messagebox.showerror("Thiếu file", f"Không tìm thấy file GR:\n{gr_path}")
            return None
        if not source_path.exists():
            messagebox.showerror(
                "Thiếu file", f"Không tìm thấy file QuanLy:\n{source_path}"
            )
            return None
        return source_path, gr_path

    def apply_card_methods(census: list[dict]) -> None:
        card_combo.configure(values=[entry["method"] for entry in census])
        set_log(
            "Các phương thức TT có trong 2 file:\n"
            + "\n".join(
                f"- {entry['method']}: QuanLy {entry['source_count']} GD "
                f"({entry['source_total']:,}) | GR {entry['gr_count']} GD "
                f"({entry['gr_total']:,})"
                for entry in census
            )
        )
        set_busy(False, f"Đã tải {len(census)} phương thức TT.")
        play_done_sound(True)

    def load_card_methods() -> None:
        paths = card_job_paths()
        if not paths:
            return
        source_path, gr_path = paths
        set_busy(True, "Đang đọc danh sách thẻ...")
        set_log("Đang quét phương thức thanh toán trong 2 file, vui lòng chờ...")

        def worker() -> None:
            try:
                census = method_census(
                    scan_source_payment_rows(source_path),
                    scan_gr_payment_rows(gr_path),
                )
                root.after(0, lambda: apply_card_methods(census))
            except Exception as exc:
                root.after(0, lambda message=str(exc): finish_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def finish_card_total(summary: str, output_file: Path) -> None:
        set_log(summary)
        set_busy(False, "Đã xuất file tổng tiền.")
        play_done_sound(True)
        messagebox.showinfo("Hoàn tất", f"Đã lưu file tổng tiền:\n{output_file}")

    def run_card_total() -> None:
        paths = card_job_paths()
        if not paths:
            return
        source_path, gr_path = paths
        card_input = card_var.get().strip()
        if not card_input:
            messagebox.showerror(
                "Chưa nhập thẻ", "Hãy nhập phương thức TT hoặc 4 số cuối của thẻ."
            )
            return

        set_busy(True, "Đang tính tổng tiền theo thẻ...")
        set_log("Đang quét 2 file và tính tổng, vui lòng chờ...")

        def worker() -> None:
            try:
                output_file, summary = export_card_total(
                    source_file=source_path,
                    gr_file=gr_path,
                    card_input=card_input,
                )
                root.after(0, lambda: finish_card_total(summary, output_file))
            except Exception as exc:
                root.after(0, lambda message=str(exc): finish_error(message))

        threading.Thread(target=worker, daemon=True).start()

    dry_run_var.trace_add("write", update_output_state)
    update_output_state()
    load_sheets()
    root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match Facebook billing rows into GR sheet columns F:J."
    )
    parser.add_argument("--gui", action="store_true", help="Open the GUI.")
    parser.add_argument("--gr", type=Path, default=None, help="Path to GR workbook.")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_FILE,
        help="Path to QuanLy_NapTien_FacebookAd workbook.",
    )
    parser.add_argument(
        "--sheet",
        default=DEFAULT_TARGET_SHEET,
        help="Target sheet in GR workbook. Default: NH Anh CT.",
    )
    parser.add_argument(
        "--sheets",
        default=None,
        help="Comma-separated target sheet names. Overrides --sheet.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output workbook path. Default: a new timestamped file in Downloads.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Write back to the GR file. A timestamped backup goes to Downloads first.",
    )
    parser.add_argument(
        "--only-id-sheets",
        action="store_true",
        help="Only scan payment sheets whose names end with an account id in parentheses.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print matching summary. Do not save any workbook.",
    )
    parser.add_argument(
        "--card-total",
        nargs="?",
        const=DEFAULT_CARD_TOTAL,
        default=None,
        metavar="CARD",
        help=(
            "Sum transactions of one payment method in both workbooks and export a "
            f"new report. Accepts '{DEFAULT_CARD_TOTAL}' or just the last 4 digits."
        ),
    )
    parser.add_argument(
        "--card-total-output",
        type=Path,
        default=None,
        help="Output path for --card-total. Default: a new file in Downloads.",
    )
    return parser.parse_args()


def main() -> None:
    if len(sys.argv) == 1:
        launch_gui()
        return

    args = parse_args()
    if args.gui:
        launch_gui()
        return

    gr_file = args.gr or find_gr_file(BASE_DIR)

    if not gr_file.exists():
        raise FileNotFoundError(gr_file)
    if not args.source.exists():
        raise FileNotFoundError(args.source)

    if args.card_total:
        _, summary_text = export_card_total(
            source_file=args.source,
            gr_file=gr_file,
            card_input=args.card_total,
            output_file=args.card_total_output,
        )
        print(summary_text)
        return

    if args.sheets:
        sheet_names = [name.strip() for name in args.sheets.split(",") if name.strip()]
    else:
        sheet_names = [args.sheet]

    (
        payment_index,
        duplicates,
        reference_index,
        reference_duplicates,
        cells_by_value,
        scanned_sheets,
    ) = build_payment_index(args.source, args.only_id_sheets)
    wb, stats_by_sheet, total_stats = fill_target_sheets(
        gr_file=gr_file,
        sheet_names=sheet_names,
        payment_index=payment_index,
        duplicates=duplicates,
        reference_index=reference_index,
        reference_duplicates=reference_duplicates,
        cells_by_value=cells_by_value,
        dry_run=args.dry_run,
    )

    result_file = None
    if not args.dry_run:
        result_file = save_result(
            wb=wb,
            gr_file=gr_file,
            output_file=args.output,
            overwrite=args.overwrite,
        )

    print_summary(scanned_sheets, total_stats, result_file, stats_by_sheet)


if __name__ == "__main__":
    main()
