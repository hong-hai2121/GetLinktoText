from __future__ import annotations

import argparse
import csv
import html
import json
import os
import posixpath
import re
import sys
import threading
import unicodedata
import webbrowser
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, urlparse
import xml.etree.ElementTree as ET


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR / "exports"
DEFAULT_HTML_PATH = EXPORT_DIR / "thong_ke_ten_hang.html"
DEFAULT_CSV_PATH = EXPORT_DIR / "thong_ke_ten_hang.csv"

XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEADER_PRODUCT = "ten hang"
HEADER_QUANTITY = "so luong"
HEADER_UNIT = "dvt"
HEADER_INVOICE = "so hoa don"
INPUT_PATTERNS = ("*.csv", "*.xls", "*.xlsx", "*.xlsm")
INPUT_FILETYPES = (
    ("Excel/CSV", "*.csv *.xls *.xlsx *.xlsm"),
    ("CSV", "*.csv"),
    ("Excel", "*.xls *.xlsx *.xlsm"),
    ("Tất cả file", "*.*"),
)


@dataclass
class ImportReport:
    file_name: str
    sheet_name: str
    header_row: int
    product_column: str
    quantity_column: str
    line_count: int


@dataclass
class ReportResult:
    output_html: Path
    output_csv: Path
    line_count: int
    item_count: int
    file_count: int
    errors: list[str]


@dataclass
class InvoiceLine:
    item_name: str
    quantity: Decimal
    unit: str
    invoice_number: str


@dataclass
class ItemStat:
    name: str
    total_quantity: Decimal = Decimal("0")
    line_count: int = 0
    units: Counter[str] = field(default_factory=Counter)
    invoices: set[str] = field(default_factory=set)


def normalize_text(value: object) -> str:
    text = str(value or "").replace("\xa0", " ").strip().lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def column_to_index(column: str) -> int:
    result = 0
    for ch in column.upper():
        if not ("A" <= ch <= "Z"):
            break
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def index_to_column(index: int) -> str:
    if index < 0:
        return ""
    index += 1
    letters: list[str] = []
    while index:
        index, rem = divmod(index - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def cell_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        raise ValueError(f"Không đọc được cột từ ô Excel: {cell_ref}")
    return column_to_index(match.group(1))


def parse_decimal(value: object) -> Decimal:
    text = clean_cell(value)
    if not text:
        return Decimal("0")

    text = text.replace(" ", "").replace("\xa0", "")
    text = re.sub(r"[^0-9,.\-+]", "", text)
    if text in {"", "-", "+"}:
        return Decimal("0")

    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        decimal_sep = "," if last_comma > last_dot else "."
        thousand_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousand_sep, "")
        text = text.replace(decimal_sep, ".")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) == 3 and len(parts) > 1 and all(part.isdigit() for part in parts[1:]):
            text = "".join(parts)
        else:
            text = "".join(parts[:-1]) + "." + parts[-1]
    elif "." in text:
        parts = text.split(".")
        if len(parts[-1]) == 3 and len(parts) > 1 and all(part.isdigit() for part in parts[1:]):
            text = "".join(parts)
        else:
            text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def format_decimal_vn(value: Decimal) -> str:
    if value == value.to_integral_value():
        text = str(value.quantize(Decimal("1")))
    else:
        text = format(value.normalize(), "f").rstrip("0").rstrip(".")

    sign = ""
    if text.startswith("-"):
        sign = "-"
        text = text[1:]

    integer, _, fraction = text.partition(".")
    chunks: list[str] = []
    while len(integer) > 3:
        chunks.insert(0, integer[-3:])
        integer = integer[:-3]
    chunks.insert(0, integer or "0")

    result = sign + ".".join(chunks)
    if fraction:
        result += "," + fraction
    return result


def read_shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []

    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for item in root.findall("x:si", XLSX_NS):
        parts = [node.text or "" for node in item.findall(".//x:t", XLSX_NS)]
        shared.append("".join(parts))
    return shared


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", XLSX_NS))

    value = cell.find("x:v", XLSX_NS)
    if value is None or value.text is None:
        return ""

    raw = value.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def workbook_sheets(zip_file: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.find("x:sheets", XLSX_NS) or []:
        name = sheet.attrib.get("name", "Sheet")
        rel_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
        target = rel_targets.get(rel_id or "")
        if not target:
            continue
        target = target.replace("\\", "/")
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        sheets.append((name, sheet_path))
    return sheets


def worksheet_rows(zip_file: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[tuple[int, list[str]]]:
    root = ET.fromstring(zip_file.read(sheet_path))
    sheet_data = root.find("x:sheetData", XLSX_NS)
    if sheet_data is None:
        return []

    rows: list[tuple[int, list[str]]] = []
    for row in sheet_data.findall("x:row", XLSX_NS):
        row_number = int(row.attrib.get("r", len(rows) + 1))
        values: list[str] = []
        for cell in row.findall("x:c", XLSX_NS):
            ref = cell.attrib.get("r", "")
            col_index = cell_column_index(ref) if ref else len(values)
            while len(values) <= col_index:
                values.append("")
            values[col_index] = clean_cell(cell_value(cell, shared_strings))
        rows.append((row_number, values))
    return rows


def find_header_row(rows: list[tuple[int, list[str]]]) -> tuple[int, int, dict[str, int]]:
    for position, (_row_number, values) in enumerate(rows):
        header_map: dict[str, int] = {}
        for index, value in enumerate(values):
            key = normalize_text(value)
            if key:
                header_map.setdefault(key, index)
        if HEADER_PRODUCT in header_map and HEADER_QUANTITY in header_map:
            return position, rows[position][0], header_map

    raise ValueError("Không tìm thấy dòng header có cột 'Tên hàng' và 'Số lượng'.")


def lines_from_rows(
    rows: list[tuple[int, list[str]]],
    file_name: str,
    sheet_name: str,
) -> tuple[list[InvoiceLine], ImportReport]:
    header_position, header_row_number, header_map = find_header_row(rows)
    product_index = header_map[HEADER_PRODUCT]
    quantity_index = header_map[HEADER_QUANTITY]
    unit_index = header_map.get(HEADER_UNIT)
    invoice_index = header_map.get(HEADER_INVOICE)

    lines: list[InvoiceLine] = []
    for _row_number, values in rows[header_position + 1 :]:
        item_name = clean_cell(values[product_index] if product_index < len(values) else "")
        quantity_text = clean_cell(values[quantity_index] if quantity_index < len(values) else "")
        if not item_name and not quantity_text:
            continue
        if not item_name:
            continue

        unit = clean_cell(values[unit_index] if unit_index is not None and unit_index < len(values) else "")
        invoice = clean_cell(values[invoice_index] if invoice_index is not None and invoice_index < len(values) else "")
        lines.append(
            InvoiceLine(
                item_name=item_name,
                quantity=parse_decimal(quantity_text),
                unit=unit,
                invoice_number=invoice,
            )
        )

    report = ImportReport(
        file_name=file_name,
        sheet_name=sheet_name,
        header_row=header_row_number,
        product_column=index_to_column(product_index),
        quantity_column=index_to_column(quantity_index),
        line_count=len(lines),
    )
    return lines, report


def read_csv_rows(path: Path) -> list[tuple[int, list[str]]]:
    encodings = ("utf-8-sig", "utf-8", "cp1258", "cp1252")
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                sample = file.read(4096)
                file.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.reader(file, dialect)
                return [(index, [clean_cell(value) for value in row]) for index, row in enumerate(reader, start=1)]
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise ValueError(f"Không đọc được file CSV: {path.name}")


def read_csv_invoice_lines(path: Path) -> tuple[list[InvoiceLine], ImportReport]:
    rows = read_csv_rows(path)
    return lines_from_rows(rows, path.name, "CSV")


def read_excel_invoice_lines(path: Path, preferred_sheet: str | None = None) -> tuple[list[InvoiceLine], ImportReport]:
    if not zipfile.is_zipfile(path):
        raise ValueError(
            f"{path.name} không phải file Excel .xlsx hợp lệ. "
            "File mẫu của MISA thường là .xlsx nhưng có đuôi .xls. "
            "Nếu đây là .xls đời cũ, hãy mở bằng Excel rồi Save As thành .xlsx."
        )

    with zipfile.ZipFile(path) as zip_file:
        shared_strings = read_shared_strings(zip_file)
        sheets = workbook_sheets(zip_file)
        if preferred_sheet:
            normalized_sheet = normalize_text(preferred_sheet)
            sheets = [sheet for sheet in sheets if normalize_text(sheet[0]) == normalized_sheet]
            if not sheets:
                raise ValueError(f"Không tìm thấy sheet: {preferred_sheet}")

        last_error: Exception | None = None
        for sheet_name, sheet_path in sheets:
            try:
                rows = worksheet_rows(zip_file, sheet_path, shared_strings)
                return lines_from_rows(rows, path.name, sheet_name)
            except Exception as exc:  # noqa: BLE001 - try next sheet and report the useful error later.
                last_error = exc
                continue

    if last_error:
        raise last_error
    raise ValueError(f"Không tìm thấy sheet có dữ liệu trong {path.name}.")


def read_invoice_lines(path: Path, preferred_sheet: str | None = None) -> tuple[list[InvoiceLine], ImportReport]:
    if path.suffix.lower() == ".csv":
        return read_csv_invoice_lines(path)
    return read_excel_invoice_lines(path, preferred_sheet)


def aggregate_lines(lines: Iterable[InvoiceLine]) -> list[ItemStat]:
    stats: dict[str, ItemStat] = {}
    for line in lines:
        display_name = clean_cell(line.item_name)
        key = display_name.casefold()
        if key not in stats:
            stats[key] = ItemStat(name=display_name)

        stat = stats[key]
        stat.total_quantity += line.quantity
        stat.line_count += 1
        if line.unit:
            stat.units[line.unit] += 1
        if line.invoice_number:
            stat.invoices.add(line.invoice_number)

    return sorted(stats.values(), key=lambda item: (-item.total_quantity, normalize_text(item.name)))


def resolve_input_files(raw_inputs: list[str]) -> list[Path]:
    if not raw_inputs:
        candidates = []
        for pattern in INPUT_PATTERNS:
            candidates.extend(BASE_DIR.glob(pattern))
        return sorted(path for path in candidates if not path.name.startswith("~$"))

    paths: list[Path] = []
    for raw in raw_inputs:
        path = Path(raw)
        if not path.is_absolute():
            path = BASE_DIR / path
        if path.is_dir():
            for pattern in INPUT_PATTERNS:
                paths.extend(path.glob(pattern))
        else:
            paths.append(path)
    return sorted(path for path in paths if not path.name.startswith("~$"))


def build_payload(stats: list[ItemStat], reports: list[ImportReport], total_lines: int) -> dict[str, object]:
    all_invoices: set[str] = set()
    for stat in stats:
        all_invoices.update(stat.invoices)

    total_quantity = sum((stat.total_quantity for stat in stats), Decimal("0"))
    rows = []
    for index, stat in enumerate(stats, start=1):
        unit = stat.units.most_common(1)[0][0] if stat.units else ""
        rows.append(
            {
                "index": index,
                "name": stat.name,
                "unit": unit,
                "quantity": float(stat.total_quantity),
                "quantityText": format_decimal_vn(stat.total_quantity),
                "lineCount": stat.line_count,
                "invoiceCount": len(stat.invoices),
            }
        )

    return {
        "generatedAt": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "reports": [report.__dict__ for report in reports],
        "summary": {
            "itemCount": len(stats),
            "lineCount": total_lines,
            "invoiceCount": len(all_invoices),
            "quantity": float(total_quantity),
            "quantityText": format_decimal_vn(total_quantity),
        },
        "rows": rows,
    }


def safe_json(data: object) -> str:
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def write_csv_report(stats: list[ItemStat], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["STT", "Tên hàng", "ĐVT", "Tổng số lượng", "Số dòng", "Số hóa đơn"])
        for index, stat in enumerate(stats, start=1):
            unit = stat.units.most_common(1)[0][0] if stat.units else ""
            writer.writerow(
                [
                    index,
                    stat.name,
                    unit,
                    format_decimal_vn(stat.total_quantity),
                    stat.line_count,
                    len(stat.invoices),
                ]
            )


def write_html_report(payload: dict[str, object], output_path: Path, csv_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html_text = (
        HTML_TEMPLATE.replace("__PAYLOAD_JSON__", safe_json(payload))
        .replace("__CSV_FILE__", html.escape(csv_path.name))
        .replace("__CSV_URI__", html.escape(csv_path.resolve().as_uri(), quote=True))
    )
    output_path.write_text(html_text, encoding="utf-8")


HTML_TEMPLATE = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Thống kê tên hàng</title>
  <style>
    :root {
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #202124;
      --muted: #667085;
      --line: #d9dee7;
      --teal: #23736b;
      --orange: #b45c2e;
      --violet: #5d5fef;
      --shadow: 0 10px 28px rgba(32, 33, 36, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }

    .app {
      width: min(1440px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 32px;
    }

    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    h1 {
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    .subtitle {
      margin-top: 6px;
      color: var(--muted);
      max-width: 900px;
    }

    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: var(--shadow);
      min-width: 0;
    }

    .metric .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .metric .value {
      margin-top: 6px;
      font-size: 26px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .main-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 16px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }

    .panel-title {
      font-size: 16px;
      font-weight: 700;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    input[type="search"] {
      width: min(340px, 52vw);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      color: var(--ink);
      background: #fff;
      outline: none;
    }

    input[type="search"]:focus {
      border-color: var(--teal);
      box-shadow: 0 0 0 3px rgba(35, 115, 107, 0.14);
    }

    button {
      border: 1px solid var(--teal);
      border-radius: 6px;
      padding: 9px 12px;
      background: var(--teal);
      color: #fff;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
      white-space: nowrap;
    }

    button.secondary {
      background: #fff;
      color: var(--teal);
    }

    .button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--teal);
      border-radius: 6px;
      padding: 9px 12px;
      background: #fff;
      color: var(--teal);
      font: inherit;
      font-weight: 650;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }

    .table-wrap {
      max-height: calc(100vh - 250px);
      min-height: 420px;
      overflow: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }

    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }

    th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #eef2f5;
      color: #30343b;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
      cursor: pointer;
      user-select: none;
    }

    td.number, th.number { text-align: right; }
    th:nth-child(1), td:nth-child(1) { width: 64px; }
    th:nth-child(3), td:nth-child(3) { width: 96px; }
    th:nth-child(4), td:nth-child(4) { width: 150px; }
    th:nth-child(5), td:nth-child(5) { width: 110px; }
    th:nth-child(6), td:nth-child(6) { width: 120px; }

    tbody tr:hover { background: #f4fbfa; }

    .item-name {
      overflow-wrap: anywhere;
      font-weight: 600;
    }

    .empty {
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }

    .side {
      display: grid;
      gap: 16px;
    }

    .source-list {
      padding: 14px;
      display: grid;
      gap: 10px;
    }

    .source {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfd;
    }

    .source strong {
      display: block;
      overflow-wrap: anywhere;
      margin-bottom: 4px;
    }

    .source span {
      display: block;
      color: var(--muted);
      font-size: 13px;
    }

    .chart {
      padding: 14px;
      display: grid;
      gap: 12px;
    }

    .bar-row {
      display: grid;
      gap: 5px;
    }

    .bar-meta {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: #30343b;
      font-size: 13px;
    }

    .bar-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 600;
    }

    .bar-track {
      height: 10px;
      background: #e8edf1;
      border-radius: 999px;
      overflow: hidden;
    }

    .bar-fill {
      height: 100%;
      min-width: 2px;
      background: linear-gradient(90deg, var(--teal), var(--orange));
    }

    .muted { color: var(--muted); }

    @media (max-width: 980px) {
      .topbar,
      .panel-head {
        align-items: stretch;
        flex-direction: column;
      }

      .summary {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .main-grid {
        grid-template-columns: 1fr;
      }

      .table-wrap {
        max-height: none;
      }
    }

    @media (max-width: 620px) {
      .app {
        width: min(100% - 20px, 1440px);
        padding-top: 14px;
      }

      h1 { font-size: 20px; }

      .summary {
        grid-template-columns: 1fr;
      }

      input[type="search"] {
        width: 100%;
      }

      .toolbar {
        width: 100%;
      }

      button {
        flex: 1 1 auto;
      }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="topbar">
      <div>
        <h1>Thống kê số lượng theo tên hàng</h1>
        <div class="subtitle" id="generatedAt"></div>
      </div>
      <div class="toolbar">
        <button class="secondary" id="resetButton" type="button">Xóa lọc</button>
        <a class="button-link" id="openCsvButton" href="__CSV_URI__" target="_blank" rel="noopener">Mở CSV bằng Excel</a>
        <button id="downloadButton" type="button">Tải CSV</button>
      </div>
    </section>

    <section class="summary">
      <div class="metric">
        <div class="label">Mặt hàng</div>
        <div class="value" id="itemCount">0</div>
      </div>
      <div class="metric">
        <div class="label">Tổng số lượng</div>
        <div class="value" id="quantityTotal">0</div>
      </div>
      <div class="metric">
        <div class="label">Dòng hóa đơn</div>
        <div class="value" id="lineCount">0</div>
      </div>
      <div class="metric">
        <div class="label">Số hóa đơn</div>
        <div class="value" id="invoiceCount">0</div>
      </div>
    </section>

    <section class="main-grid">
      <section class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Bảng tổng hợp</div>
            <div class="muted" id="visibleSummary"></div>
          </div>
          <input id="searchInput" type="search" placeholder="Tìm tên hàng, đơn vị tính...">
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="number" data-key="index">STT</th>
                <th data-key="name">Tên hàng</th>
                <th data-key="unit">ĐVT</th>
                <th class="number" data-key="quantity">Tổng số lượng</th>
                <th class="number" data-key="lineCount">Số dòng</th>
                <th class="number" data-key="invoiceCount">Số hóa đơn</th>
              </tr>
            </thead>
            <tbody id="tableBody"></tbody>
          </table>
          <div class="empty" id="emptyState" hidden>Không có mặt hàng phù hợp.</div>
        </div>
      </section>

      <aside class="side">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Top số lượng</div>
          </div>
          <div class="chart" id="chart"></div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Nguồn dữ liệu</div>
          </div>
          <div class="source-list" id="sources"></div>
        </section>
      </aside>
    </section>
  </main>

  <script>
    const payload = __PAYLOAD_JSON__;
    const csvFileName = "__CSV_FILE__";
    let currentRows = [];
    let sortState = { key: "quantity", direction: -1 };

    const searchInput = document.getElementById("searchInput");
    const tableBody = document.getElementById("tableBody");
    const emptyState = document.getElementById("emptyState");
    const visibleSummary = document.getElementById("visibleSummary");

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function formatNumber(value) {
      return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 6 }).format(value || 0);
    }

    function compareRows(a, b) {
      const key = sortState.key;
      const av = a[key];
      const bv = b[key];
      if (typeof av === "number" && typeof bv === "number") {
        return (av - bv) * sortState.direction;
      }
      return String(av ?? "").localeCompare(String(bv ?? ""), "vi", { sensitivity: "base" }) * sortState.direction;
    }

    function applyFilterAndSort() {
      const query = searchInput.value.trim().toLocaleLowerCase("vi");
      currentRows = payload.rows.filter((row) => {
        const text = `${row.name} ${row.unit}`.toLocaleLowerCase("vi");
        return !query || text.includes(query);
      }).sort(compareRows);
      renderTable();
    }

    function renderTable() {
      tableBody.innerHTML = currentRows.map((row, index) => `
        <tr>
          <td class="number">${index + 1}</td>
          <td><div class="item-name">${escapeHtml(row.name)}</div></td>
          <td>${escapeHtml(row.unit)}</td>
          <td class="number">${escapeHtml(row.quantityText)}</td>
          <td class="number">${formatNumber(row.lineCount)}</td>
          <td class="number">${formatNumber(row.invoiceCount)}</td>
        </tr>
      `).join("");

      emptyState.hidden = currentRows.length > 0;
      const visibleQuantity = currentRows.reduce((sum, row) => sum + (row.quantity || 0), 0);
      visibleSummary.textContent = `${formatNumber(currentRows.length)} mặt hàng, tổng số lượng ${formatNumber(visibleQuantity)}`;
    }

    function renderSummary() {
      const firstSource = payload.reports[0] || {};
      document.getElementById("generatedAt").textContent =
        `Tạo lúc ${payload.generatedAt}. Cột tên hàng: ${firstSource.product_column || "AB"}, cột số lượng: ${firstSource.quantity_column || "AE"}.`;
      document.getElementById("itemCount").textContent = formatNumber(payload.summary.itemCount);
      document.getElementById("quantityTotal").textContent = payload.summary.quantityText;
      document.getElementById("lineCount").textContent = formatNumber(payload.summary.lineCount);
      document.getElementById("invoiceCount").textContent = formatNumber(payload.summary.invoiceCount);
    }

    function renderSources() {
      const container = document.getElementById("sources");
      container.innerHTML = payload.reports.map((source) => `
        <div class="source">
          <strong>${escapeHtml(source.file_name)}</strong>
          <span>Sheet: ${escapeHtml(source.sheet_name)}</span>
          <span>Header dòng ${source.header_row}; tên hàng ${source.product_column}; số lượng ${source.quantity_column}</span>
          <span>${formatNumber(source.line_count)} dòng dữ liệu</span>
        </div>
      `).join("");
    }

    function renderChart() {
      const chart = document.getElementById("chart");
      const topRows = [...payload.rows].sort((a, b) => b.quantity - a.quantity).slice(0, 12);
      const maxQuantity = Math.max(...topRows.map((row) => row.quantity), 1);
      chart.innerHTML = topRows.map((row) => {
        const width = Math.max(2, (row.quantity / maxQuantity) * 100);
        return `
          <div class="bar-row" title="${escapeHtml(row.name)}">
            <div class="bar-meta">
              <span class="bar-name">${escapeHtml(row.name)}</span>
              <strong>${escapeHtml(row.quantityText)}</strong>
            </div>
            <div class="bar-track"><div class="bar-fill" style="width: ${width}%"></div></div>
          </div>
        `;
      }).join("");
    }

    function csvCell(value) {
      const text = String(value ?? "");
      return `"${text.replace(/"/g, '""')}"`;
    }

    function downloadCsv() {
      const header = ["STT", "Tên hàng", "ĐVT", "Tổng số lượng", "Số dòng", "Số hóa đơn"];
      const rows = currentRows.map((row, index) => [
        index + 1,
        row.name,
        row.unit,
        row.quantityText,
        row.lineCount,
        row.invoiceCount
      ]);
      const csv = [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\\r\\n");
      const blob = new Blob(["\\ufeff" + csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = csvFileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    document.querySelectorAll("th[data-key]").forEach((header) => {
      header.addEventListener("click", () => {
        const key = header.dataset.key;
        sortState = {
          key,
          direction: sortState.key === key ? sortState.direction * -1 : (key === "name" || key === "unit" ? 1 : -1)
        };
        applyFilterAndSort();
      });
    });

    searchInput.addEventListener("input", applyFilterAndSort);
    document.getElementById("resetButton").addEventListener("click", () => {
      searchInput.value = "";
      sortState = { key: "quantity", direction: -1 };
      applyFilterAndSort();
    });
    document.getElementById("downloadButton").addEventListener("click", downloadCsv);

    renderSummary();
    renderSources();
    renderChart();
    applyFilterAndSort();
  </script>
</body>
</html>
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Thống kê tổng số lượng theo cột Tên hàng và Số lượng từ bảng kê hóa đơn MISA."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="File Excel/CSV hoặc thư mục cần đọc. Bỏ trống sẽ hiện cửa sổ desktop chọn file.",
    )
    parser.add_argument("--sheet", help="Tên sheet cần đọc. Bỏ trống để tự tìm sheet có header.")
    parser.add_argument("--out", default=str(DEFAULT_HTML_PATH.relative_to(BASE_DIR)), help="Đường dẫn file HTML kết quả.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH.relative_to(BASE_DIR)), help="Đường dẫn file CSV kết quả.")
    parser.add_argument("--no-open", action="store_true", help="Chỉ xuất file, không mở trình duyệt.")
    parser.add_argument("--no-dialog", action="store_true", help="Không mở cửa sổ desktop khi bỏ trống input.")
    return parser.parse_args(argv)


def create_report(
    raw_inputs: list[str],
    sheet: str | None,
    out: str,
    csv_out: str,
    output_base: Path,
    open_report: bool,
) -> ReportResult:
    input_files = resolve_input_files(raw_inputs)
    if not input_files:
        raise ValueError("Không tìm thấy file .csv/.xls/.xlsx nào để thống kê.")

    all_lines: list[InvoiceLine] = []
    reports: list[ImportReport] = []
    errors: list[str] = []

    for path in input_files:
        try:
            lines, report = read_invoice_lines(path, sheet)
        except Exception as exc:  # noqa: BLE001 - show every input error to the user.
            errors.append(f"{path.name}: {exc}")
            continue
        all_lines.extend(lines)
        reports.append(report)

    if not all_lines:
        detail = "\n".join(f"- {error}" for error in errors)
        message = "Không đọc được dòng dữ liệu nào."
        if detail:
            message += "\n" + detail
        raise ValueError(message)

    stats = aggregate_lines(all_lines)
    output_html = Path(out)
    output_csv = Path(csv_out)
    if not output_html.is_absolute():
        output_html = output_base / output_html
    if not output_csv.is_absolute():
        output_csv = output_base / output_csv

    payload = build_payload(stats, reports, len(all_lines))
    write_csv_report(stats, output_csv)
    write_html_report(payload, output_html, output_csv)

    if open_report:
        webbrowser.open(output_html.resolve().as_uri())

    return ReportResult(
        output_html=output_html,
        output_csv=output_csv,
        line_count=len(all_lines),
        item_count=len(stats),
        file_count=len(reports),
        errors=errors,
    )


CONTROL_HTML = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chọn dữ liệu hóa đơn MISA</title>
  <style>
    :root {
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #202124;
      --muted: #667085;
      --line: #d9dee7;
      --teal: #23736b;
      --orange: #b45c2e;
      --danger: #b42318;
      --shadow: 0 10px 28px rgba(32, 33, 36, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }

    .app {
      width: min(980px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0;
    }

    h1 {
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 0 0 18px;
      color: var(--muted);
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 18px;
    }

    label {
      display: block;
      margin-bottom: 8px;
      font-weight: 700;
    }

    .file-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      margin-bottom: 14px;
    }

    input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      color: var(--ink);
      font: inherit;
      outline: none;
    }

    input:focus {
      border-color: var(--teal);
      box-shadow: 0 0 0 3px rgba(35, 115, 107, 0.14);
    }

    .actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }

    button, .button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border: 1px solid var(--teal);
      border-radius: 6px;
      padding: 9px 13px;
      background: var(--teal);
      color: #fff;
      font: inherit;
      font-weight: 650;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }

    button.secondary, .button-link.secondary {
      background: #fff;
      color: var(--teal);
    }

    button:disabled, .button-link.disabled {
      opacity: 0.55;
      cursor: not-allowed;
      pointer-events: none;
    }

    .status {
      min-height: 90px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      padding: 12px;
      color: var(--muted);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .status.ok { color: var(--teal); }
    .status.error { color: var(--danger); }

    .note {
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }

    @media (max-width: 680px) {
      .file-row {
        grid-template-columns: 1fr;
      }

      button, .button-link {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <main class="app">
    <h1>Thống kê hóa đơn MISA</h1>
    <p class="subtitle">Chọn một hoặc nhiều file CSV/Excel, chạy thống kê, rồi xem báo cáo ngay trong webview.</p>

    <section class="panel">
      <label for="fileInput">File dữ liệu</label>
      <div class="file-row">
        <input id="fileInput" type="text" placeholder="Chưa chọn file CSV/Excel" readonly>
        <button id="chooseButton" class="secondary" type="button">Chọn file</button>
      </div>

      <div class="actions">
        <button id="runButton" type="button">Chạy thống kê</button>
        <a id="reportButton" class="button-link secondary disabled" href="#">Mở báo cáo</a>
        <a id="csvButton" class="button-link secondary disabled" href="#">Mở CSV</a>
        <button id="shutdownButton" class="secondary" type="button">Tắt webview</button>
      </div>

      <div id="status" class="status">Chưa chọn file.</div>
      <div class="note">Có thể chọn nhiều file `.csv`, `.xls`, `.xlsx`, `.xlsm`. Báo cáo HTML và CSV sẽ được lưu vào thư mục <strong>exports</strong> cạnh file đầu tiên đã chọn.</div>
    </section>
  </main>

  <script>
    const fileInput = document.getElementById("fileInput");
    const chooseButton = document.getElementById("chooseButton");
    const runButton = document.getElementById("runButton");
    const reportButton = document.getElementById("reportButton");
    const csvButton = document.getElementById("csvButton");
    const shutdownButton = document.getElementById("shutdownButton");
    const statusBox = document.getElementById("status");
    let selectedFiles = [];

    function setStatus(text, type = "") {
      statusBox.textContent = text;
      statusBox.className = `status ${type}`;
    }

    function setBusy(isBusy) {
      chooseButton.disabled = isBusy;
      runButton.disabled = isBusy;
    }

    function enableLink(link, href) {
      link.href = href;
      link.classList.remove("disabled");
    }

    async function postJson(url, payload = {}) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "Có lỗi khi xử lý yêu cầu.");
      }
      return data;
    }

    chooseButton.addEventListener("click", async () => {
      setBusy(true);
      setStatus("Đang mở hộp thoại chọn file...");
      try {
        const data = await postJson("/api/choose-files", { currentFiles: selectedFiles });
        selectedFiles = data.files || [];
        if (selectedFiles.length) {
          fileInput.value = selectedFiles.length === 1 ? selectedFiles[0] : `${selectedFiles.length} file đã chọn`;
          setStatus(`Đã chọn ${selectedFiles.length.toLocaleString("vi-VN")} file.\\n${selectedFiles.join("\\n")}\\n\\nBấm Chạy thống kê để tạo báo cáo.`, "ok");
        } else {
          fileInput.value = "";
          setStatus("Bạn chưa chọn file.");
        }
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        setBusy(false);
      }
    });

    shutdownButton.addEventListener("click", async () => {
      try {
        await postJson("/api/shutdown");
        setStatus("Đã tắt webview local. Có thể đóng tab này.", "ok");
        setTimeout(() => window.close(), 120);
      } catch (error) {
        setStatus(error.message, "error");
      }
    });

    runButton.addEventListener("click", async () => {
      if (!selectedFiles.length) {
        setStatus("Vui lòng chọn file CSV/Excel trước khi chạy thống kê.", "error");
        return;
      }

      setBusy(true);
      reportButton.classList.add("disabled");
      csvButton.classList.add("disabled");
      setStatus("Đang đọc Excel và tạo báo cáo...");

      try {
        const data = await postJson("/api/run", { files: selectedFiles });
        const message = [
          `Đã đọc ${data.lineCount.toLocaleString("vi-VN")} dòng từ ${data.fileCount.toLocaleString("vi-VN")} file.`,
          `Đã thống kê ${data.itemCount.toLocaleString("vi-VN")} tên hàng.`,
          `HTML: ${data.htmlPath}`,
          `CSV: ${data.csvPath}`
        ];
        if (data.errorCount) {
          message.push(`Có ${data.errorCount.toLocaleString("vi-VN")} file bị bỏ qua.`);
        }
        setStatus(message.join("\\n"), "ok");
        enableLink(reportButton, data.reportUrl);
        enableLink(csvButton, data.csvUrl);
        window.location.href = data.reportUrl;
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        setBusy(false);
      }
    });
  </script>
</body>
</html>
"""


def _choose_files_from_web(current_files: list[str]) -> list[Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001 - tkinter can be unavailable on stripped Python installs.
        raise RuntimeError(f"Không mở được hộp thoại chọn file: {exc}") from exc

    initial_dir = str(BASE_DIR)
    if current_files:
        first_file = Path(current_files[0])
        if first_file.is_file():
            initial_dir = str(first_file.parent)

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    try:
        files = filedialog.askopenfilenames(
            title="Chọn file CSV/Excel hóa đơn MISA",
            initialdir=initial_dir,
            filetypes=INPUT_FILETYPES,
        )
    finally:
        root.destroy()

    return [Path(file) for file in files]


def run_webview_control(args: argparse.Namespace) -> int:
    served_reports: set[Path] = set()
    served_csvs: set[Path] = set()

    def with_shutdown_script(report_html: str) -> str:
        snippet = """
  <script>
    (() => {
      let shutdownSent = false;

      function sendShutdown() {
        if (shutdownSent) return;
        shutdownSent = true;
        try {
          if (navigator.sendBeacon) {
            navigator.sendBeacon("/api/shutdown", "");
          } else {
            fetch("/api/shutdown", { method: "POST", keepalive: true }).catch(() => {});
          }
        } catch (_error) {}
      }

      window.addEventListener("pagehide", sendShutdown);

      const toolbar = document.querySelector(".topbar .toolbar") || document.querySelector(".toolbar");
      if (toolbar) {
        const closeButton = document.createElement("button");
        closeButton.className = "secondary";
        closeButton.type = "button";
        closeButton.textContent = "Đóng webview";
        closeButton.addEventListener("click", () => {
          sendShutdown();
          setTimeout(() => {
            window.close();
            document.body.innerHTML = "<main style='font-family: Segoe UI, Arial, sans-serif; padding: 24px'>Đã tắt webview local. Có thể đóng tab này.</main>";
          }, 120);
        });
        toolbar.prepend(closeButton);
      }
    })();
  </script>
"""
        if "</body>" in report_html:
            return report_html.replace("</body>", snippet + "\n</body>", 1)
        return report_html + snippet

    class WebviewHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def send_text(self, content: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
            self.send_bytes(content.encode("utf-8"), content_type, status)

        def send_json(self, payload: dict[str, object], status: int = 200) -> None:
            self.send_text(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8", status)

        def read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw or "{}")

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler.
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                self.send_text(CONTROL_HTML)
                return

            if parsed.path == "/report":
                params = parse_qs(parsed.query)
                report_path = Path(params.get("path", [""])[0]).resolve()
                if report_path not in served_reports or not report_path.is_file():
                    self.send_text("Không tìm thấy báo cáo.", "text/plain; charset=utf-8", 404)
                    return
                report_html = report_path.read_text(encoding="utf-8")
                self.send_text(with_shutdown_script(report_html))
                threading.Timer(1.0, self.server.shutdown).start()
                return

            if parsed.path == "/csv":
                params = parse_qs(parsed.query)
                csv_path = Path(params.get("path", [""])[0]).resolve()
                if csv_path not in served_csvs or not csv_path.is_file():
                    self.send_text("Không tìm thấy file CSV.", "text/plain; charset=utf-8", 404)
                    return
                content = csv_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'inline; filename="{csv_path.name}"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

            self.send_text("Not found", "text/plain; charset=utf-8", 404)

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler.
            try:
                parsed = urlparse(self.path)
                payload = self.read_json()

                if parsed.path == "/api/choose-files":
                    raw_current_files = payload.get("currentFiles") or []
                    current_files = [str(file) for file in raw_current_files] if isinstance(raw_current_files, list) else []
                    files = _choose_files_from_web(current_files)
                    self.send_json({"ok": True, "files": [str(file) for file in files]})
                    return

                if parsed.path == "/api/run":
                    raw_files = payload.get("files") or []
                    if not isinstance(raw_files, list):
                        raise ValueError("Danh sách file không hợp lệ.")
                    files = [Path(str(file).strip('" ')).resolve() for file in raw_files if str(file).strip()]
                    if not files:
                        raise ValueError("Chưa chọn file CSV/Excel nào.")
                    missing = [str(file) for file in files if not file.is_file()]
                    if missing:
                        raise ValueError("Một số file không tồn tại:\n" + "\n".join(missing))

                    result = create_report(
                        raw_inputs=[str(file) for file in files],
                        sheet=args.sheet,
                        out=args.out,
                        csv_out=args.csv,
                        output_base=files[0].parent,
                        open_report=False,
                    )
                    report_path = result.output_html.resolve()
                    csv_path = result.output_csv.resolve()
                    served_reports.add(report_path)
                    served_csvs.add(csv_path)

                    report_url = f"/report?path={quote(str(report_path))}"
                    csv_url = f"/csv?path={quote(str(csv_path))}"
                    self.send_json(
                        {
                            "ok": True,
                            "lineCount": result.line_count,
                            "itemCount": result.item_count,
                            "fileCount": result.file_count,
                            "errorCount": len(result.errors),
                            "htmlPath": str(report_path),
                            "csvPath": str(csv_path),
                            "reportUrl": report_url,
                            "csvUrl": csv_url,
                        }
                    )
                    return

                if parsed.path == "/api/shutdown":
                    self.send_json({"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return

                self.send_json({"ok": False, "error": "Endpoint không tồn tại."}, 404)
            except Exception as exc:  # noqa: BLE001 - return useful error to webview.
                self.send_json({"ok": False, "error": str(exc)}, 500)

    try:
        server = HTTPServer(("127.0.0.1", 0), WebviewHandler)
    except OSError as exc:
        print(f"Không khởi động được webview local: {exc}")
        return 1

    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"Webview điều khiển: {url}", flush=True)
    print("Bấm 'Tắt webview' hoặc đóng trang báo cáo để kết thúc terminal.", flush=True)
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng webview local.")
    finally:
        server.server_close()
    return 0


def print_result(result: ReportResult) -> None:
    print(f"Đã đọc {result.line_count} dòng từ {result.file_count} file.")
    print(f"Đã thống kê {result.item_count} tên hàng.")
    print(f"HTML: {result.output_html}")
    print(f"CSV : {result.output_csv}")
    if result.errors:
        print("Một số file bị bỏ qua:")
        for error in result.errors:
            print(f"- {error}")


def open_path(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        webbrowser.open(path.resolve().as_uri())


def run_desktop_app(args: argparse.Namespace) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:  # noqa: BLE001 - tkinter can be unavailable on stripped Python installs.
        print(f"Không mở được cửa sổ desktop: {exc}")
        return 1

    root = tk.Tk()
    root.title("Thống kê hóa đơn MISA")
    root.geometry("920x460")
    root.minsize(780, 390)

    colors = {
        "bg": "#f4faf9",
        "panel": "#ffffff",
        "line": "#d7e3e1",
        "ink": "#17312f",
        "muted": "#667a77",
        "teal": "#0f766e",
        "teal_dark": "#0b5f59",
        "blue": "#2563eb",
        "soft": "#e9f7f5",
        "warn": "#8a4b12",
    }
    root.configure(bg=colors["bg"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Accent.TButton", padding=(14, 9), font=("Segoe UI", 10, "bold"))
    style.configure("Secondary.TButton", padding=(12, 8), font=("Segoe UI", 10))
    style.map(
        "Accent.TButton",
        background=[("active", colors["teal_dark"]), ("!disabled", colors["teal"])],
        foreground=[("!disabled", "#ffffff")],
    )
    style.map(
        "Secondary.TButton",
        background=[("active", colors["soft"]), ("!disabled", "#ffffff")],
        foreground=[("!disabled", colors["teal"])],
    )

    selected_file: Path | None = None
    last_result: ReportResult | None = None
    file_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="Chọn file Bang_ke_chi_tiet_HD, sau đó bấm Chạy thống kê.")

    outer = tk.Frame(root, bg=colors["bg"], padx=18, pady=16)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(3, weight=1)

    header = tk.Frame(outer, bg=colors["bg"])
    header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
    header.columnconfigure(0, weight=1)

    tk.Label(
        header,
        text="Hóa đơn điện tử MISA",
        bg=colors["bg"],
        fg=colors["ink"],
        font=("Segoe UI", 18, "bold"),
    ).grid(row=0, column=0, sticky="w")
    tk.Label(
        header,
        text="Thống kê số lượng theo Tên hàng cho bảng kê thuế, đơn hàng và hóa đơn bán lẻ.",
        bg=colors["bg"],
        fg=colors["muted"],
        font=("Segoe UI", 10),
    ).grid(row=1, column=0, sticky="w", pady=(4, 0))
    tk.Label(
        header,
        text="CSV / XLS / XLSX",
        bg=colors["soft"],
        fg=colors["teal_dark"],
        font=("Segoe UI", 9, "bold"),
        padx=12,
        pady=5,
    ).grid(row=0, column=1, rowspan=2, sticky="ne")

    file_frame = tk.Frame(
        outer,
        bg=colors["panel"],
        highlightbackground=colors["line"],
        highlightthickness=1,
        padx=14,
        pady=12,
    )
    file_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
    file_frame.columnconfigure(0, weight=1)

    tk.Label(
        file_frame,
        text="File Bang_ke_chi_tiet_HD",
        bg=colors["panel"],
        fg=colors["ink"],
        font=("Segoe UI", 11, "bold"),
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(
        file_frame,
        text="Chọn đúng file bảng kê chi tiết hóa đơn đã sử dụng từ MISA hoặc file CSV đã xuất.",
        bg=colors["panel"],
        fg=colors["muted"],
        font=("Segoe UI", 9),
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 10))

    file_entry = ttk.Entry(file_frame, textvariable=file_var, state="readonly")
    file_entry.grid(row=2, column=0, sticky="ew", padx=(0, 10))

    actions = tk.Frame(
        outer,
        bg=colors["panel"],
        highlightbackground=colors["line"],
        highlightthickness=1,
        padx=14,
        pady=12,
    )
    actions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
    actions.columnconfigure(4, weight=1)

    report_button = ttk.Button(actions, text="Mở báo cáo HTML", state="disabled", style="Secondary.TButton")
    csv_button = ttk.Button(actions, text="Mở CSV bằng Excel", state="disabled", style="Secondary.TButton")

    result_box = tk.Frame(
        outer,
        bg=colors["panel"],
        highlightbackground=colors["line"],
        highlightthickness=1,
        padx=14,
        pady=12,
    )
    result_box.grid(row=3, column=0, sticky="nsew")
    result_box.columnconfigure(0, weight=1)
    tk.Label(
        result_box,
        text="Trạng thái xử lý",
        bg=colors["panel"],
        fg=colors["ink"],
        font=("Segoe UI", 11, "bold"),
    ).grid(row=0, column=0, sticky="w")
    tk.Label(
        result_box,
        textvariable=status_var,
        bg=colors["panel"],
        fg=colors["muted"],
        font=("Segoe UI", 10),
        wraplength=820,
        justify="left",
    ).grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def set_selected_file(path: Path | None) -> None:
        nonlocal selected_file, last_result
        selected_file = path
        last_result = None
        file_var.set(str(path) if path else "")
        report_button.configure(state="disabled")
        csv_button.configure(state="disabled")
        if path:
            status_var.set(f"Đã chọn file:\n{path}")
        else:
            status_var.set("Chưa chọn file.")

    def choose_file() -> None:
        initial_dir = str(selected_file.parent) if selected_file else str(BASE_DIR)
        file = filedialog.askopenfilename(
            title="Chọn file Bang_ke_chi_tiet_HD",
            initialdir=initial_dir,
            filetypes=INPUT_FILETYPES,
        )
        if not file:
            return
        set_selected_file(Path(file))

    def clear_file() -> None:
        set_selected_file(None)

    def open_report() -> None:
        if last_result:
            open_path(last_result.output_html)

    def open_csv() -> None:
        if last_result:
            open_path(last_result.output_csv)

    def set_running(is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        for child in actions.winfo_children():
            child.configure(state=state)
        browse_button.configure(state=state)
        if not is_running:
            report_button.configure(state="normal" if last_result else "disabled")
            csv_button.configure(state="normal" if last_result else "disabled")

    def run_report() -> None:
        nonlocal last_result
        if selected_file is None:
            messagebox.showwarning("Chưa chọn file", "Vui lòng chọn file Bang_ke_chi_tiet_HD trước khi chạy thống kê.")
            return

        if not selected_file.is_file():
            messagebox.showerror("File không tồn tại", f"File không tồn tại:\n{selected_file}")
            return

        set_running(True)
        status_var.set("Đang đọc file và tạo báo cáo...")
        root.update_idletasks()

        try:
            result = create_report(
                raw_inputs=[str(selected_file)],
                sheet=args.sheet,
                out=args.out,
                csv_out=args.csv,
                output_base=selected_file.parent,
                open_report=False,
            )
        except Exception as exc:  # noqa: BLE001 - show full error in desktop app.
            last_result = None
            report_button.configure(state="disabled")
            csv_button.configure(state="disabled")
            status_var.set("Chạy thống kê bị lỗi.")
            messagebox.showerror("Lỗi", str(exc))
            set_running(False)
            return

        last_result = result
        report_button.configure(state="normal")
        csv_button.configure(state="normal")
        lines = [
            f"Đã đọc {result.line_count} dòng từ {result.file_count} file.",
            f"Đã thống kê {result.item_count} tên hàng.",
            f"HTML: {result.output_html}",
            f"CSV: {result.output_csv}",
        ]
        if result.errors:
            lines.append(f"Có {len(result.errors)} file bị bỏ qua.")
        status_var.set("\n".join(lines))
        set_running(False)
        open_path(result.output_html)

    browse_button = ttk.Button(
        file_frame,
        text="Chọn file Bang_ke_chi_tiet_HD",
        command=choose_file,
        style="Accent.TButton",
    )
    browse_button.grid(row=2, column=1)

    ttk.Button(actions, text="Chạy thống kê", command=run_report, style="Accent.TButton").grid(
        row=0, column=0, padx=(0, 8)
    )
    report_button.configure(command=open_report)
    report_button.grid(row=0, column=1, padx=(0, 8))
    csv_button.configure(command=open_csv)
    csv_button.grid(row=0, column=2, padx=(0, 8))
    ttk.Button(actions, text="Xóa file", command=clear_file, style="Secondary.TButton").grid(
        row=0, column=3, padx=(0, 8)
    )
    ttk.Button(actions, text="Đóng", command=root.destroy, style="Secondary.TButton").grid(row=0, column=5, sticky="e")

    root.mainloop()
    return 0


def command_output_base(raw_inputs: list[str]) -> Path:
    if raw_inputs:
        path = Path(raw_inputs[0])
        if not path.is_absolute():
            path = BASE_DIR / path
        if path.is_dir():
            return path
        if path.parent:
            return path.parent
    return BASE_DIR


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    raw_inputs = args.inputs

    if not raw_inputs and not args.no_dialog:
        return run_desktop_app(args)

    try:
        result = create_report(
            raw_inputs=raw_inputs,
            sheet=args.sheet,
            out=args.out,
            csv_out=args.csv,
            output_base=command_output_base(raw_inputs),
            open_report=not args.no_open,
        )
    except Exception as exc:  # noqa: BLE001 - command line should show concise errors.
        print(exc)
        return 1

    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
