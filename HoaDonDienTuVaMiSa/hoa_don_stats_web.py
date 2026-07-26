from __future__ import annotations

import argparse
import csv
import html
import json
import os
import posixpath
import re
import shutil
import sys
import threading
import unicodedata
import webbrowser
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, urlparse
import xml.etree.ElementTree as ET


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = app_base_dir()
EXPORT_DIR = BASE_DIR / "exports"
DEFAULT_HTML_PATH = EXPORT_DIR / "thong_ke_ten_hang.html"
DEFAULT_CSV_PATH = EXPORT_DIR / "thong_ke_ten_hang.csv"

XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEADER_PRODUCT = "ten hang"
HEADER_QUANTITY = "so luong"
HEADER_UNIT = "dvt"
HEADER_INVOICE = "so hoa don"
HEADER_DATE = "ngay hoa don"
HEADER_CUSTOMER_CODE = "ma khach hang"
HEADER_CUSTOMER_NAME = "ten khach hang"
HEADER_NOTE = "ghi chu"
HEADER_STATUS = "trang thai hoa don"
INPUT_PATTERNS = ("*.csv", "*.xls", "*.xlsx", "*.xlsm")
INPUT_FILETYPES = (
    ("Excel/CSV", "*.csv *.xls *.xlsx *.xlsm"),
    ("CSV", "*.csv"),
    ("Excel", "*.xls *.xlsx *.xlsm"),
    ("Tất cả file", "*.*"),
)
ZIP_FILETYPES = (
    ("ZIP hóa đơn", "*.zip"),
    ("Tất cả file", "*.*"),
)
# Danh mục thuốc: cột A là tên hàng, cột B..F là các tên khác của cùng thuốc đó.
CATALOG_FILE_NAMES = ("Tên Sản Phẩm.xlsx", "Ten San Pham.xlsx")
CATALOG_GLOBS = ("*Sản Phẩm*.xlsx", "*San Pham*.xlsx")
CATALOG_ALIAS_COLUMNS = 5
CATALOG_SHEET_NAME = "Tên sản phẩm"
CATALOG_HEADERS = ("Tên hàng", "Tên khác 1", "Tên khác 2", "Tên khác 3", "Tên khác 4", "Tên khác 5")
# Tên mốc quá ngắn dễ nằm lọt trong tên thuốc khác nên không dùng để dò.
CATALOG_MIN_ANCHOR = 4


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
    unknown_names: list[str] = field(default_factory=list)


@dataclass
class InvoiceLine:
    item_name: str
    quantity: Decimal
    unit: str
    invoice_number: str
    row_number: int = 0
    source_file: str = ""
    source_label: str = ""
    source_kind: str = ""
    sheet_name: str = ""
    invoice_date: str = ""
    customer_code: str = ""
    customer_name: str = ""
    note: str = ""
    status: str = ""
    invoice_html_path: str = ""
    invoice_html_uri: str = ""


@dataclass
class InvoiceFolderRead:
    lines: list[InvoiceLine]
    report: ImportReport


@dataclass
class VariantStat:
    """Một tên hàng gốc trên hóa đơn đã được gộp vào sản phẩm chuẩn."""

    name: str
    kind: str = "sale"
    total_quantity: Decimal = Decimal("0")
    line_count: int = 0
    sources: set[str] = field(default_factory=set)


@dataclass
class ItemStat:
    name: str
    key: str = ""
    in_catalog: bool = False
    ambiguous: bool = False
    ambiguous_note: str = ""
    total_quantity: Decimal = Decimal("0")
    returned_quantity: Decimal = Decimal("0")
    line_count: int = 0
    units: Counter[str] = field(default_factory=Counter)
    invoices: set[str] = field(default_factory=set)
    details: list[InvoiceLine] = field(default_factory=list)
    variants: dict[str, VariantStat] = field(default_factory=dict)

    @property
    def net_quantity(self) -> Decimal:
        """Thực bán = tổng bán ra cộng phần hoàn (hoàn là số âm)."""
        return self.total_quantity + self.returned_quantity


def normalize_text(value: object) -> str:
    text = str(value or "").replace("\xa0", " ").strip().lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


# Tiền tố mô tả nhóm hàng, không phải tên sản phẩm: "Thực phẩm bảo vệ sức khỏe OMEGA 3.6.9".
PRODUCT_PREFIX_RE = re.compile(
    r"^(?:thuc pham bao ve suc khoe|thuc pham bo sung|thuc pham chuc nang|tpbvsk|tpcn)\b[\s:.\-]*"
)
# Số lô / hạn dùng bám theo tên hàng: "(SL: 200326, HD: 210429)", "(T/242 - H/30)".
# "sl"/"hd" bắt buộc có dấu hai chấm, nếu không sẽ nuốt luôn "HĐ 00004914" trong dòng điều chỉnh.
BATCH_RES = (
    re.compile(r"\b(?:sl|hd)\s*:\s*\d[0-9a-z/.\-]*"),
    re.compile(r"\b(?:hsd|nsx|so lo|lo sx|han dung|ngay sx)\s*[:.]?\s*\d[0-9a-z/.\-]*"),
    re.compile(r"\b[th]\s*/\s*\d+"),
)
# Số phải nằm sát sau từ vật chứa mới tính là quy cách: "Hộp 1 lọ x 50 viên" chứ không
# phải "... Hộp ... cho toàn bộ hàng hoá tại HĐ số 00004858".
PACK_CONTAINER_WINDOW = 4
# Từ mở đầu một cụm quy cách khi phía sau có số: "(Hộp 1 lọ x 50 viên)".
PACK_CONTAINERS = frozenset({"hop", "lo", "chai", "tui", "tuyp", "hu", "thung", "bich", "goi"})
# Đơn vị đếm đứng ngay sau số: "60 viên/lọ", "100 viên/hộp". Không để "hộp/lọ" ở đây
# vì chúng là vật chứa, "OMEGA 3.6.9 (Hộp...)" sẽ bị cắt nhầm ngay tại số 9.
PACK_MEASURES = frozenset({"vien", "goi", "ong", "vi", "que", "ml"})
# Dạng bào chế và ký tự nhân, không làm nên khác biệt quy cách: "10 viên nén" = "10 viên".
PACK_NOISE = frozenset({"x", "nen", "nang", "mem", "sui", "cung", "dang", "loai"})
# Dung tích/khối lượng mỗi đơn vị, bỏ khỏi khóa để "Hộp 15 gói" khớp "Hộp 15 gói*10ml".
PACK_VOLUME_UNITS = frozenset({"ml", "l", "lit", "g", "gam", "mg", "kg"})
TOKEN_RE = re.compile(r"[a-z0-9]+")


# "điều chỉnh giảm <tên hàng> do khách hàng trả lại toàn bộ hàng hóa" và các biến thể sai
# chính tả trong dữ liệu thật: "điêu chỉnh giảm", "dieu chỉnh giảm", "điều chỉnh giả".
RETURN_LINE_RE = re.compile(r"^d\w* chinh gi\w+\s+(?P<name>.+?)\s+do kh\w+\s")
# Điều chỉnh không phải trả hàng: bổ sung đơn vị tính, đổi tên hàng hóa.
OTHER_ADJUST_RE = re.compile(r"^d\w* chinh\b")
OTHER_ADJUST_KEY = "__dieu_chinh_khac__"
OTHER_ADJUST_NAME = "Dòng điều chỉnh khác (không phải trả hàng)"
KIND_SALE = "sale"
KIND_RETURN = "return"
KIND_OTHER = "other"


def classify_line(line: InvoiceLine) -> tuple[str, str]:
    """Phân loại dòng thành bán / hoàn / điều chỉnh khác, kèm tên dùng để tìm sản phẩm."""
    normalized = normalize_text(line.item_name)
    matched = RETURN_LINE_RE.match(normalized)
    if matched:
        return KIND_RETURN, matched.group("name")
    if OTHER_ADJUST_RE.match(normalized) and line.quantity == 0:
        # Chỉ gom vào rọ chung khi số lượng bằng 0. Dòng điều chỉnh có số lượng thật
        # phải đứng riêng, nếu không số liệu bị giấu mất.
        return KIND_OTHER, ""
    if line.quantity < 0:
        # Dòng ghi đúng tên hàng nhưng số lượng âm cũng là hàng hoàn.
        return KIND_RETURN, clean_cell(line.item_name)
    return KIND_SALE, clean_cell(line.item_name)


def return_quantity(quantity: Decimal) -> Decimal:
    """Dòng trả hàng luôn tính là âm, kể cả khi MISA ghi số dương."""
    return -abs(quantity)


@dataclass(frozen=True)
class ProductName:
    """Tên hàng đã tách thành lõi tên và quy cách đóng gói."""

    raw: str
    core: str
    pack: str

    @property
    def key(self) -> str:
        return f"{self.core}|{self.pack}"


def split_product_name(raw: object) -> ProductName:
    text = normalize_text(raw)
    for pattern in BATCH_RES:
        text = pattern.sub(" ", text)

    previous = ""
    while previous != text:
        previous = text
        text = PRODUCT_PREFIX_RE.sub("", text.lstrip(" (:-."))

    # Tách số khỏi chữ để "10ml" và "10 ml" cho ra cùng một khóa.
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    tokens = TOKEN_RE.findall(text)
    pack_start = len(tokens)
    for index, token in enumerate(tokens):
        following = tokens[index + 1 :]
        if token in PACK_CONTAINERS and any(item.isdigit() for item in following[:PACK_CONTAINER_WINDOW]):
            pack_start = index
            break
        if token.isdigit() and following and following[0] in PACK_MEASURES:
            pack_start = index
            break

    core = "".join(tokens[:pack_start])
    pack = normalize_pack(tokens[pack_start:])
    if not core:
        # Cả tên chỉ là quy cách (hiếm) thì giữ nguyên để không gộp nhầm.
        core, pack = "".join(tokens), ""
    return ProductName(raw=clean_cell(raw), core=core, pack=pack)


def normalize_pack(tokens: list[str]) -> str:
    full: list[str] = []
    without_volume: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in PACK_NOISE:
            index += 1
            continue
        if token.isdigit() and following in PACK_VOLUME_UNITS:
            full.extend((token, following))
            index += 2
            continue
        full.append(token)
        without_volume.append(token)
        index += 1

    # "Hộp 20 gói*10ml" = "Hộp 20 gói": dung tích mỗi gói không tạo ra quy cách khác.
    # Nhưng "250ml" đứng một mình lại chính là quy cách nên phải giữ.
    if any(token in PACK_MEASURES or token in PACK_CONTAINERS for token in without_volume):
        return " ".join(without_volume)
    return " ".join(full)


def catalog_anchor(name: object) -> str:
    """Chuỗi dùng để dò tên thuốc: bỏ dấu, bỏ tiền tố, bỏ số lô, bỏ mọi dấu câu."""
    parsed = split_product_name(name)
    return parsed.core + "".join(TOKEN_RE.findall(parsed.pack))


@dataclass
class CatalogProduct:
    """Một hàng trong danh mục: cột A là tên hàng, cột B..F là các tên khác."""

    name: str
    aliases: list[str] = field(default_factory=list)

    @property
    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]

    @property
    def key(self) -> str:
        return f"cat:{catalog_anchor(self.name)}"


@dataclass
class ProductCatalog:
    path: Path | None = None
    products: list[CatalogProduct] = field(default_factory=list)
    error: str = ""

    @property
    def loaded(self) -> bool:
        return bool(self.products)


@dataclass
class ProductGroup:
    """Một sản phẩm sau khi gộp, kèm cảnh báo nếu không tự quyết được quy cách."""

    key: str
    ambiguous: bool = False
    ambiguous_note: str = ""


class ProductMatcher:
    """Gộp tên hàng theo danh mục thuốc, tên nào ngoài danh mục thì theo lõi tên + quy cách."""

    def __init__(self, raw_names: Iterable[object], catalog: ProductCatalog | None = None) -> None:
        self.catalog = catalog or ProductCatalog()
        self._parsed: dict[str, ProductName] = {}
        self._redirect: dict[str, str] = {}
        self._groups: dict[str, ProductGroup] = {}
        self._full_anchors: list[tuple[str, int]] = []
        self._core_anchors: dict[str, set[int]] = {}
        self._catalog_hit: dict[str, CatalogProduct | None] = {}
        self._build_anchors()
        self._build([name for name in raw_names if not self._match_catalog(name)])

    def _build_anchors(self) -> None:
        for index, product in enumerate(self.catalog.products):
            for name in product.all_names:
                parsed = self._parse(name)
                if len(parsed.core) < CATALOG_MIN_ANCHOR:
                    continue
                self._full_anchors.append((catalog_anchor(name), index))
                self._core_anchors.setdefault(parsed.core, set()).add(index)
        # Mốc dài đứng trước để tên cụ thể hơn luôn thắng tên chung chung.
        self._full_anchors.sort(key=lambda item: -len(item[0]))

    def _match_catalog(self, raw: object) -> CatalogProduct | None:
        text = clean_cell(raw)
        if text in self._catalog_hit:
            return self._catalog_hit[text]
        found = self._find_catalog(text) if self._full_anchors else None
        self._catalog_hit[text] = found
        return found

    def _find_catalog(self, text: str) -> CatalogProduct | None:
        parsed = self._parse(text)
        target_full = catalog_anchor(text)

        # Tầng 1: khớp cả quy cách, để hai hàng danh mục cùng tên khác quy cách vẫn tách được.
        for anchor, index in self._full_anchors:
            if anchor in target_full:
                return self.catalog.products[index]

        # Tầng 2: chỉ khớp lõi tên, dành cho tên hóa đơn không ghi quy cách.
        hits = sorted((core for core in self._core_anchors if core in parsed.core), key=len, reverse=True)
        if not hits:
            return None
        owners = self._core_anchors[hits[0]]
        if len(owners) != 1:
            # Lõi tên này thuộc nhiều thuốc khác quy cách, không đoán bừa.
            return None
        return self.catalog.products[next(iter(owners))]

    def _parse(self, raw: object) -> ProductName:
        text = clean_cell(raw)
        if text not in self._parsed:
            self._parsed[text] = split_product_name(text)
        return self._parsed[text]

    def _build(self, raw_names: list[object]) -> None:
        data_packs: dict[str, set[str]] = {}
        cores_without_pack: set[str] = set()
        pack_examples: dict[tuple[str, str], str] = {}
        for raw in raw_names:
            parsed = self._parse(raw)
            core, pack = parsed.core, parsed.pack
            data_packs.setdefault(core, set())
            if pack:
                data_packs[core].add(pack)
                pack_examples.setdefault((core, pack), clean_cell(raw))
            else:
                cores_without_pack.add(core)

        for core in sorted(cores_without_pack):
            packs = sorted(data_packs.get(core, set()))
            if len(packs) == 1:
                # Chỉ có đúng một quy cách nên tên không ghi quy cách chắc chắn là quy cách đó.
                self._redirect[f"{core}|"] = f"{core}|{packs[0]}"
                continue
            if not packs:
                continue
            examples = [pack_examples.get((core, pack), pack) for pack in packs]
            self._groups[f"{core}|"] = ProductGroup(
                key=f"{core}|",
                ambiguous=True,
                ambiguous_note=(
                    f"Tên không ghi quy cách trong khi dữ liệu có {len(packs)} quy cách khác nhau: "
                    + " | ".join(examples)
                    + ". Số lượng này để riêng vì không đoán được thuộc quy cách nào."
                ),
            )

    def key_for(self, raw: object) -> str:
        product = self._match_catalog(raw)
        if product is not None:
            return product.key
        key = self._parse(raw).key
        return self._redirect.get(key, key)

    def catalog_product(self, key: str) -> CatalogProduct | None:
        for product in self.catalog.products:
            if product.key == key:
                return product
        return None

    def group(self, key: str) -> ProductGroup:
        return self._groups.get(key, ProductGroup(key=key))

    def unknown_names(self, raw_names: Iterable[object]) -> list[str]:
        """Các tên trên hóa đơn chưa có trong danh mục thuốc."""
        found: dict[str, None] = {}
        for raw in raw_names:
            text = clean_cell(raw)
            if text and self._match_catalog(text) is None:
                found.setdefault(text, None)
        return list(found)


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


def parse_xml_decimal(value: object) -> Decimal:
    text = clean_cell(value).replace(" ", "").replace("\xa0", "")
    if not text:
        return Decimal("0")
    text = re.sub(r"[^0-9,.\-+]", "", text)
    if "," in text and "." in text:
        return parse_decimal(text)
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return parse_decimal(value)


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
    source_path: str | None = None,
) -> tuple[list[InvoiceLine], ImportReport]:
    header_position, header_row_number, header_map = find_header_row(rows)
    product_index = header_map[HEADER_PRODUCT]
    quantity_index = header_map[HEADER_QUANTITY]
    unit_index = header_map.get(HEADER_UNIT)
    invoice_index = header_map.get(HEADER_INVOICE)
    date_index = header_map.get(HEADER_DATE)
    customer_code_index = header_map.get(HEADER_CUSTOMER_CODE)
    customer_name_index = header_map.get(HEADER_CUSTOMER_NAME)
    note_index = header_map.get(HEADER_NOTE)
    status_index = header_map.get(HEADER_STATUS)

    def optional_cell(values: list[str], index: int | None) -> str:
        return clean_cell(values[index] if index is not None and index < len(values) else "")

    lines: list[InvoiceLine] = []
    for row_number, values in rows[header_position + 1 :]:
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
                row_number=row_number,
                source_file=source_path or file_name,
                source_label=f"{file_name} - {sheet_name}",
                source_kind="detail",
                sheet_name=sheet_name,
                invoice_date=optional_cell(values, date_index),
                customer_code=optional_cell(values, customer_code_index),
                customer_name=optional_cell(values, customer_name_index),
                note=optional_cell(values, note_index),
                status=optional_cell(values, status_index),
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
    return lines_from_rows(rows, path.name, "CSV", str(path.resolve()))


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
                return lines_from_rows(rows, path.name, sheet_name, str(path.resolve()))
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


def read_sheet_rows(path: Path) -> list[tuple[int, list[str]]]:
    if path.suffix.lower() == ".csv":
        return read_csv_rows(path)
    if not zipfile.is_zipfile(path):
        raise ValueError(f"{path.name} không phải file Excel .xlsx hợp lệ.")
    with zipfile.ZipFile(path) as zip_file:
        shared_strings = read_shared_strings(zip_file)
        sheets = workbook_sheets(zip_file)
        if not sheets:
            raise ValueError(f"Không tìm thấy sheet nào trong {path.name}.")
        return worksheet_rows(zip_file, sheets[0][1], shared_strings)


def default_catalog_path() -> Path:
    for name in CATALOG_FILE_NAMES:
        candidate = BASE_DIR / name
        if candidate.is_file():
            return candidate
    for pattern in CATALOG_GLOBS:
        for candidate in sorted(BASE_DIR.glob(pattern)):
            if candidate.is_file() and not candidate.name.startswith("~$"):
                return candidate
    return BASE_DIR / CATALOG_FILE_NAMES[0]


def read_product_catalog(path: Path | None = None) -> ProductCatalog:
    target = path or default_catalog_path()
    if not target.is_file():
        return ProductCatalog(path=target, error=f"Chưa có danh mục thuốc: {target.name}")

    try:
        rows = read_sheet_rows(target)
    except Exception as exc:  # noqa: BLE001 - danh mục lỗi không được làm hỏng cả báo cáo.
        return ProductCatalog(path=target, error=f"Không đọc được danh mục {target.name}: {exc}")

    products: list[CatalogProduct] = []
    seen_names: set[str] = set()
    for position, (_row_number, values) in enumerate(rows):
        cells = [clean_cell(value) for value in values[: CATALOG_ALIAS_COLUMNS + 1]]
        while len(cells) <= CATALOG_ALIAS_COLUMNS:
            cells.append("")
        name = cells[0]
        if not name:
            continue
        if position == 0 and normalize_text(name) in {"ten hang", "ten san pham", "ten thuoc"}:
            continue
        if name in seen_names:
            continue
        seen_names.add(name)
        aliases = [value for value in cells[1:] if value and value != name]
        products.append(CatalogProduct(name=name, aliases=aliases))

    if not products:
        return ProductCatalog(path=target, error=f"Danh mục {target.name} chưa có tên thuốc nào.")
    return ProductCatalog(path=target, products=products)


def xlsx_escape(value: str) -> str:
    text = html.escape(value, quote=True)
    return "".join(ch for ch in text if ch >= " " or ch in "\t\n")


def write_product_catalog(path: Path, products: list[CatalogProduct]) -> None:
    """Ghi lại danh mục thành file .xlsx tối giản, Excel vẫn mở và sửa được."""
    header = list(CATALOG_HEADERS[: CATALOG_ALIAS_COLUMNS + 1])
    table = [header]
    for product in products:
        cells = [product.name, *product.aliases]
        while len(cells) <= CATALOG_ALIAS_COLUMNS:
            cells.append("")
        table.append(cells[: CATALOG_ALIAS_COLUMNS + 1])

    rows_xml: list[str] = []
    for row_index, cells in enumerate(table, start=1):
        cells_xml = "".join(
            f'<c r="{index_to_column(column)}{row_index}" t="inlineStr"><is><t xml:space="preserve">'
            f"{xlsx_escape(value)}</t></is></c>"
            for column, value in enumerate(cells)
            if value
        )
        rows_xml.append(f'<row r="{row_index}">{cells_xml}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{XLSX_NS["x"]}"><sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{XLSX_NS["x"]}" xmlns:r="{OFFICE_REL_NS}">'
        f'<sheets><sheet name="{xlsx_escape(CATALOG_SHEET_NAME)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{OFFICE_REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{OFFICE_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument'
        '.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument'
        '.spreadsheetml.worksheet+xml"/></Types>'
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("[Content_Types].xml", content_types)
        zip_file.writestr("_rels/.rels", package_rels)
        zip_file.writestr("xl/workbook.xml", workbook)
        zip_file.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zip_file.writestr("xl/worksheets/sheet1.xml", sheet)
    temp_path.replace(path)


def xml_child_text(parent: ET.Element | None, path: str) -> str:
    if parent is None:
        return ""
    node = parent.find(path)
    if node is None or node.text is None:
        return ""
    return clean_cell(node.text)


def read_invoice_xml_lines(path: Path) -> InvoiceFolderRead:
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    common = root.find(".//TTChung")
    invoice_number = xml_child_text(common, "SHDon")
    invoice_date = xml_child_text(common, "NLap")
    buyer = root.find(".//NMua")
    customer_name = xml_child_text(buyer, "Ten")
    customer_code = xml_child_text(buyer, "MST")
    html_path = path.parent / "invoice.html"
    html_uri = html_path.resolve().as_uri() if html_path.is_file() else ""
    lines: list[InvoiceLine] = []

    for index, item in enumerate(root.findall(".//DSHHDVu/HHDVu"), start=1):
        item_name = xml_child_text(item, "THHDVu")
        if not item_name:
            continue
        lines.append(
            InvoiceLine(
                item_name=item_name,
                quantity=parse_xml_decimal(xml_child_text(item, "SLuong")),
                unit=xml_child_text(item, "DVTinh"),
                invoice_number=invoice_number,
                row_number=index,
                source_file=str(path.parent),
                source_label=f"{path.parent.name} - invoice.xml",
                source_kind="invoice",
                sheet_name="invoice.xml",
                invoice_date=invoice_date,
                customer_code=customer_code,
                customer_name=customer_name,
                invoice_html_path=str(html_path) if html_path.is_file() else "",
                invoice_html_uri=html_uri,
            )
        )

    report = ImportReport(
        file_name=str(path.parent),
        sheet_name=f"invoice.xml - Số HĐ {invoice_number or path.parent.name}",
        header_row=0,
        product_column="THHDVu",
        quantity_column="SLuong",
        line_count=len(lines),
    )
    return InvoiceFolderRead(lines=lines, report=report)


class InvoiceHtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.in_th = False
        self.in_td = False
        self.current_text: list[str] = []
        self.current_row: list[str] = []
        self.headers: list[str] | None = None
        self.rows: list[list[str]] = []
        self.invoice_number = ""
        self.pending_number = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"th", "td"}:
            self.current_text = []
            self.in_th = tag == "th"
            self.in_td = tag == "td"
        elif tag == "tr":
            self.current_row = []

    def handle_data(self, data: str) -> None:
        text = clean_cell(data)
        if not text:
            return
        if self.in_th or self.in_td:
            self.current_text.append(text)
        if text == "Số:":
            self.pending_number = True
        elif self.pending_number and re.fullmatch(r"[0-9]{3,}", text):
            self.invoice_number = text
            self.pending_number = False
        elif self.pending_number and not text.startswith("Số"):
            self.pending_number = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "th" and self.in_th:
            self.current_row.append(clean_cell(" ".join(self.current_text)))
            self.current_text = []
            self.in_th = False
        elif tag == "td" and self.in_td:
            self.current_row.append(clean_cell(" ".join(self.current_text)))
            self.current_text = []
            self.in_td = False
        elif tag == "tr":
            normalized = [normalize_text(value) for value in self.current_row]
            if "ten hang hoa, dich vu" in normalized and "so luong" in normalized:
                self.headers = self.current_row[:]
            elif self.headers and len(self.current_row) >= 4:
                self.rows.append(self.current_row[:])
            self.current_row = []


def read_invoice_html_lines(path: Path) -> InvoiceFolderRead:
    parser = InvoiceHtmlTableParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    html_uri = path.resolve().as_uri()

    if not parser.headers:
        raise ValueError("Không tìm thấy bảng hàng hóa trong invoice.html.")

    header_map = {normalize_text(value): index for index, value in enumerate(parser.headers)}
    product_index = header_map.get("ten hang hoa, dich vu")
    quantity_index = header_map.get("so luong")
    unit_index = header_map.get("don vi tinh")
    if product_index is None or quantity_index is None:
        raise ValueError("Không tìm thấy cột Tên hàng hóa, dịch vụ và Số lượng trong invoice.html.")

    lines: list[InvoiceLine] = []
    for index, row in enumerate(parser.rows, start=1):
        item_name = clean_cell(row[product_index] if product_index < len(row) else "")
        if not item_name:
            continue
        lines.append(
            InvoiceLine(
                item_name=item_name,
                quantity=parse_decimal(row[quantity_index] if quantity_index < len(row) else ""),
                unit=clean_cell(row[unit_index] if unit_index is not None and unit_index < len(row) else ""),
                invoice_number=parser.invoice_number,
                row_number=index,
                source_file=str(path.parent),
                source_label=f"{path.parent.name} - invoice.html",
                source_kind="invoice",
                sheet_name="invoice.html",
                invoice_html_path=str(path),
                invoice_html_uri=html_uri,
            )
        )

    report = ImportReport(
        file_name=str(path.parent),
        sheet_name=f"invoice.html - Số HĐ {parser.invoice_number or path.parent.name}",
        header_row=0,
        product_column="Tên hàng hóa, dịch vụ",
        quantity_column="Số lượng",
        line_count=len(lines),
    )
    return InvoiceFolderRead(lines=lines, report=report)


def read_invoice_folder(folder: Path) -> InvoiceFolderRead:
    if not folder.is_dir():
        raise ValueError(f"Không phải thư mục hóa đơn: {folder}")

    xml_path = folder / "invoice.xml"
    html_path = folder / "invoice.html"
    if xml_path.is_file():
        return read_invoice_xml_lines(xml_path)
    if html_path.is_file():
        return read_invoice_html_lines(html_path)
    raise ValueError("Không tìm thấy invoice.xml hoặc invoice.html.")


def safe_folder_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .")
    return name or "invoice_zip"


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()

    def ensure_inside(target: Path) -> None:
        try:
            target.relative_to(destination_root)
        except ValueError as exc:
            raise ValueError(f"Đường dẫn không an toàn trong ZIP: {target}") from exc

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            member_name = member.filename.replace("\\", "/")
            if not member_name or member_name.endswith("/"):
                target_dir = (destination / member_name).resolve()
                ensure_inside(target_dir)
                target_dir.mkdir(parents=True, exist_ok=True)
                continue

            target = (destination / member_name).resolve()
            ensure_inside(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                output.write(source.read())


def find_invoice_folders(root: Path) -> list[Path]:
    folders: dict[Path, int] = {}
    for xml_path in root.rglob("invoice.xml"):
        if xml_path.is_file():
            folders[xml_path.parent] = 0
    for html_path in root.rglob("invoice.html"):
        if html_path.is_file():
            folders.setdefault(html_path.parent, 1)
    return [folder for folder, _priority in sorted(folders.items(), key=lambda item: str(item[0]).lower())]


def clear_extracted_invoice_cache() -> None:
    cache_dir = EXPORT_DIR / "extracted_invoices"
    if not cache_dir.exists():
        return

    expected = cache_dir.resolve()
    export_root = EXPORT_DIR.resolve()
    if expected.name != "extracted_invoices" or expected.parent != export_root or cache_dir.is_symlink():
        raise ValueError(f"Không xóa cache giải nén vì đường dẫn không an toàn: {cache_dir}")

    shutil.rmtree(expected)


def extract_invoice_zips(zip_paths: list[Path]) -> tuple[list[Path], list[str]]:
    if not zip_paths:
        return [], []

    clear_extracted_invoice_cache()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    extract_root = EXPORT_DIR / "extracted_invoices" / run_id
    invoice_folders: list[Path] = []
    errors: list[str] = []

    for index, zip_path in enumerate(zip_paths, start=1):
        if not zip_path.is_file():
            errors.append(f"{zip_path}: File ZIP không tồn tại.")
            continue
        if zip_path.suffix.lower() != ".zip":
            errors.append(f"{zip_path}: Không phải file .zip.")
            continue

        target_dir = extract_root / f"{index:03d}_{safe_folder_name(zip_path.stem)}"
        try:
            safe_extract_zip(zip_path, target_dir)
            found = find_invoice_folders(target_dir)
        except Exception as exc:  # noqa: BLE001 - keep processing the remaining zips.
            errors.append(f"{zip_path.name}: {exc}")
            continue

        if not found:
            errors.append(f"{zip_path.name}: Không tìm thấy invoice.xml hoặc invoice.html sau giải nén.")
            continue
        invoice_folders.extend(found)

    return invoice_folders, errors


def product_names_for_matching(lines: Iterable[InvoiceLine]) -> list[str]:
    names: list[str] = []
    for line in lines:
        kind, match_name = classify_line(line)
        if kind != KIND_OTHER and match_name:
            names.append(match_name)
    return names


def aggregate_lines(lines: Iterable[InvoiceLine], matcher: ProductMatcher | None = None) -> list[ItemStat]:
    stats: dict[str, ItemStat] = {}
    for line in lines:
        display_name = clean_cell(line.item_name)
        kind, match_name = classify_line(line)
        if kind == KIND_OTHER:
            key = OTHER_ADJUST_KEY
        elif matcher:
            key = matcher.key_for(match_name)
        else:
            key = match_name.casefold()
        if key not in stats:
            stats[key] = ItemStat(name=display_name, key=key)

        stat = stats[key]
        if kind == KIND_RETURN:
            stat.returned_quantity += return_quantity(line.quantity)
        else:
            stat.total_quantity += line.quantity
        stat.line_count += 1
        stat.details.append(line)
        if line.unit:
            stat.units[line.unit] += 1
        if line.invoice_number:
            stat.invoices.add(line.invoice_number)

        variant = stat.variants.get(display_name)
        if variant is None:
            variant = VariantStat(name=display_name, kind=kind)
            stat.variants[display_name] = variant
        variant.total_quantity += return_quantity(line.quantity) if kind == KIND_RETURN else line.quantity
        variant.line_count += 1
        variant.sources.add(line.source_label or line.source_file)

    for stat in stats.values():
        name_product(stat, matcher)

    return sorted(
        stats.values(),
        key=lambda item: (item.key == OTHER_ADJUST_KEY, -item.total_quantity, normalize_text(item.name)),
    )


def name_product(stat: ItemStat, matcher: ProductMatcher | None) -> None:
    """Chọn tên hiển thị: tên gốc xuất hiện nhiều nhất trong nhóm."""
    if stat.key == OTHER_ADJUST_KEY:
        stat.name = OTHER_ADJUST_NAME
        return

    if matcher:
        product = matcher.catalog_product(stat.key)
        if product is not None:
            # Tên hiển thị lấy đúng cột A của danh mục để bạn kiểm soát được.
            stat.in_catalog = True
            stat.name = product.name
            return
        group = matcher.group(stat.key)
        stat.ambiguous = group.ambiguous
        stat.ambiguous_note = group.ambiguous_note

    sale_variants = [item for item in stat.variants.values() if item.kind == KIND_SALE]
    candidates = sale_variants or list(stat.variants.values())
    if candidates:
        # Dòng hoàn mang cả câu "điều chỉnh giảm ... do khách trả lại" nên không được
        # dùng làm tên hiển thị khi sản phẩm còn dòng bán bình thường. Bằng số dòng thì
        # lấy tên ngắn hơn vì tên dài thường là bản có kèm số lô, hạn dùng.
        best = max(candidates, key=lambda item: (item.line_count, -len(item.name)))
        stat.name = best.name


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


def is_adjustment_line(line: InvoiceLine) -> bool:
    normalized = normalize_text(line.item_name)
    return line.quantity < 0 or "dieu chinh giam" in normalized or "tra lai" in normalized


def line_to_detail(line: InvoiceLine) -> dict[str, object]:
    return {
        "sourceFile": line.source_file,
        "sourceLabel": line.source_label,
        "sourceKind": line.source_kind,
        "sheetName": line.sheet_name,
        "rowNumber": line.row_number,
        "invoiceNumber": line.invoice_number,
        "invoiceDate": line.invoice_date,
        "customerCode": line.customer_code,
        "customerName": line.customer_name,
        "itemName": line.item_name,
        "unit": line.unit,
        "quantity": float(line.quantity),
        "quantityText": format_decimal_vn(line.quantity),
        "note": line.note,
        "status": line.status,
        "invoiceHtmlPath": line.invoice_html_path,
        "invoiceHtmlUri": line.invoice_html_uri,
        "isAdjustment": is_adjustment_line(line),
    }


def variants_to_list(stat: ItemStat) -> list[dict[str, object]]:
    variants = sorted(stat.variants.values(), key=lambda item: (-item.total_quantity, item.name))
    return [
        {
            "name": variant.name,
            "kind": variant.kind,
            "isReturn": variant.kind == KIND_RETURN,
            "quantity": float(variant.total_quantity),
            "quantityText": format_decimal_vn(variant.total_quantity),
            "lineCount": variant.line_count,
            "sources": sorted(source for source in variant.sources if source),
            "isCanonical": variant.name == stat.name,
        }
        for variant in variants
    ]


def stats_to_rows(stats: list[ItemStat]) -> list[dict[str, object]]:
    rows = []
    for index, stat in enumerate(stats, start=1):
        unit = stat.units.most_common(1)[0][0] if stat.units else ""
        rows.append(
            {
                "index": index,
                "rowKey": f"row-{index}",
                "productKey": stat.key,
                "name": stat.name,
                "unit": unit,
                "quantity": float(stat.total_quantity),
                "quantityText": format_decimal_vn(stat.total_quantity),
                "returned": float(stat.returned_quantity),
                "returnedText": format_decimal_vn(stat.returned_quantity),
                "net": float(stat.net_quantity),
                "netText": format_decimal_vn(stat.net_quantity),
                "lineCount": stat.line_count,
                "invoiceCount": len(stat.invoices),
                "invoiceNumbers": sorted(stat.invoices),
                "inCatalog": stat.in_catalog,
                "unknown": not stat.in_catalog and stat.key != OTHER_ADJUST_KEY,
                "ambiguous": stat.ambiguous,
                "ambiguousNote": stat.ambiguous_note,
                "variants": variants_to_list(stat),
                "details": [line_to_detail(line) for line in stat.details],
            }
        )
    return rows


def build_merge_report(stats: list[ItemStat], matcher: ProductMatcher | None) -> dict[str, object]:
    groups = [
        {
            "name": stat.name,
            "productKey": stat.key,
            "ambiguous": stat.ambiguous,
            "ambiguousNote": stat.ambiguous_note,
            "quantityText": format_decimal_vn(stat.total_quantity),
            "returnedText": format_decimal_vn(stat.returned_quantity),
            "variantCount": len(stat.variants),
            "variants": variants_to_list(stat),
        }
        for stat in stats
        if stat.key != OTHER_ADJUST_KEY and (len(stat.variants) > 1 or stat.ambiguous)
    ]
    merged_groups = [group for group in groups if int(group["variantCount"] or 0) > 1]
    merged_name_count = sum(int(group["variantCount"] or 0) for group in merged_groups)
    catalog = matcher.catalog if matcher else ProductCatalog()
    unknown = [stat for stat in stats if stat.key != OTHER_ADJUST_KEY and not stat.in_catalog]
    return {
        "enabled": matcher is not None,
        "groups": groups,
        "mergedGroupCount": len(merged_groups),
        "mergedNameCount": merged_name_count,
        "ambiguousCount": sum(1 for group in groups if group["ambiguous"]),
        "catalogLoaded": catalog.loaded,
        "catalogFile": catalog.path.name if catalog.path else "",
        "catalogSize": len(catalog.products),
        "catalogError": catalog.error,
        "unknownCount": len(unknown),
        "unknownNames": [
            {"name": stat.name, "productKey": stat.key, "quantityText": format_decimal_vn(stat.total_quantity)}
            for stat in unknown
        ],
    }


def stats_summary(stats: list[ItemStat], total_lines: int) -> dict[str, object]:
    all_invoices: set[str] = set()
    for stat in stats:
        all_invoices.update(stat.invoices)

    total_quantity = sum((stat.total_quantity for stat in stats), Decimal("0"))
    total_returned = sum((stat.returned_quantity for stat in stats), Decimal("0"))
    return {
        "itemCount": len(stats),
        "lineCount": total_lines,
        "invoiceCount": len(all_invoices),
        "quantity": float(total_quantity),
        "quantityText": format_decimal_vn(total_quantity),
        "returned": float(total_returned),
        "returnedText": format_decimal_vn(total_returned),
        "net": float(total_quantity + total_returned),
        "netText": format_decimal_vn(total_quantity + total_returned),
    }


def build_payload(
    stats: list[ItemStat],
    reports: list[ImportReport],
    total_lines: int,
    sections: list[dict[str, object]] | None = None,
    matcher: ProductMatcher | None = None,
) -> dict[str, object]:
    return {
        "generatedAt": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "reports": [report.__dict__ for report in reports],
        "summary": stats_summary(stats, total_lines),
        "rows": stats_to_rows(stats),
        "sections": sections or [],
        "mergeReport": build_merge_report(stats, matcher),
    }


def safe_json(data: object) -> str:
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def write_csv_report(
    stats: list[ItemStat],
    output_path: Path,
    sections: list[dict[str, object]] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        merge_columns = ["Số tên gốc", "Tên gốc đã gộp", "Cảnh báo"]
        quantity_columns = ["Hoàn", "Tổng số lượng", "Thực bán"]
        if sections:
            writer.writerow(
                ["Nguồn", "STT", "Tên hàng", *quantity_columns, "Số dòng", "Số hóa đơn", *merge_columns]
            )
            for section in sections:
                section_title = str(section.get("title", ""))
                rows = section.get("rows", [])
                if not isinstance(rows, list):
                    continue
                for index, row in enumerate(rows, start=1):
                    if not isinstance(row, dict):
                        continue
                    variants = row.get("variants") or []
                    writer.writerow(
                        [
                            section_title,
                            index,
                            row.get("name", ""),
                            row.get("returnedText", ""),
                            row.get("quantityText", ""),
                            row.get("netText", ""),
                            row.get("lineCount", 0),
                            row.get("invoiceCount", 0),
                            len(variants),
                            " | ".join(str(variant.get("name", "")) for variant in variants),
                            row.get("ambiguousNote", ""),
                        ]
                    )
            return

        writer.writerow(["STT", "Tên hàng", *quantity_columns, "Số dòng", "Số hóa đơn", *merge_columns])
        for index, stat in enumerate(stats, start=1):
            writer.writerow(
                [
                    index,
                    stat.name,
                    format_decimal_vn(stat.returned_quantity),
                    format_decimal_vn(stat.total_quantity),
                    format_decimal_vn(stat.net_quantity),
                    stat.line_count,
                    len(stat.invoices),
                    len(stat.variants),
                    " | ".join(sorted(stat.variants)),
                    stat.ambiguous_note,
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
      grid-template-columns: repeat(6, minmax(120px, 1fr));
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
      grid-template-columns: minmax(0, 1fr);
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
      max-height: min(680px, calc(100vh - 280px));
      min-height: 320px;
      overflow: auto;
    }

    .section-block {
      border-bottom: 1px solid var(--line);
    }

    .section-block:last-child {
      border-bottom: 0;
    }

    .section-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 14px;
      background: #fbfcfd;
      border-bottom: 1px solid var(--line);
    }

    .section-title {
      font-weight: 750;
      color: var(--ink);
    }

    .section-desc {
      margin-top: 3px;
      color: var(--muted);
      font-size: 13px;
    }

    .section-stats {
      color: var(--muted);
      font-size: 13px;
      text-align: right;
      white-space: nowrap;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      min-width: 980px;
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
    th:nth-child(1), td:nth-child(1) { width: 56px; }
    th:nth-child(3), td:nth-child(3) { width: clamp(78px, 7vw, 96px); }
    th:nth-child(4), td:nth-child(4) { width: clamp(110px, 11vw, 140px); }
    th:nth-child(5), td:nth-child(5) { width: clamp(96px, 9vw, 118px); }
    th:nth-child(6), td:nth-child(6) { width: clamp(80px, 8vw, 100px); }
    th:nth-child(7), td:nth-child(7) { width: clamp(92px, 9vw, 112px); }
    th:nth-child(8), td:nth-child(8) { width: clamp(160px, 16vw, 190px); }

    tbody tr:hover { background: #f4fbfa; }

    .item-name {
      overflow-wrap: anywhere;
      font-weight: 600;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      overflow: hidden;
    }

    .copyable {
      cursor: pointer;
      border-radius: 4px;
      transition: background 0.12s ease;
    }

    .copyable:hover {
      background: #e8f3f1;
      box-shadow: 0 0 0 3px #e8f3f1;
    }

    .copyable:active { background: #d5eae6; }

    .toast {
      position: fixed;
      left: 50%;
      bottom: 28px;
      transform: translate(-50%, 12px);
      background: #17312f;
      color: #fff;
      border-radius: 8px;
      padding: 10px 16px;
      font-weight: 650;
      box-shadow: 0 10px 28px rgba(32, 33, 36, 0.28);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
      z-index: 60;
      max-width: min(560px, 90vw);
      overflow-wrap: anywhere;
    }

    .toast.show {
      opacity: 1;
      transform: translate(-50%, 0);
    }

    .empty {
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }

    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(15, 23, 42, 0.42);
    }

    .modal-backdrop[hidden] {
      display: none;
    }

    .modal-card {
      width: min(1180px, 100%);
      max-height: min(760px, calc(100vh - 48px));
      display: flex;
      flex-direction: column;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.26);
      overflow: hidden;
    }

    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      padding: 16px;
      border-bottom: 1px solid var(--line);
    }

    .modal-title {
      font-size: 17px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }

    .modal-body {
      padding: 16px;
      overflow: auto;
    }

    .detail-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }

    .detail-metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfd;
    }

    .detail-metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }

    .detail-metric strong {
      display: block;
      margin-top: 4px;
      font-size: 18px;
    }

    .invoice-list {
      display: block;
      max-height: 112px;
      overflow: auto;
      gap: 6px;
      margin: 0 0 14px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }

    .invoice-pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      margin: 3px;
      background: #fff;
      color: #30343b;
      font-size: 12px;
    }

    .detail-table-wrap {
      max-height: 390px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    .detail-table {
      table-layout: auto;
      min-width: 1120px;
    }

    .detail-table th,
    .detail-table td {
      font-size: 13px;
      padding: 8px 10px;
    }

    .detail-table th:nth-child(n),
    .detail-table td:nth-child(n) {
      width: auto;
    }

    .adjustment-row {
      background: #fff7ed;
    }

    .open-link {
      color: var(--teal);
      font-weight: 650;
      text-decoration: none;
    }

    .open-link:hover {
      text-decoration: underline;
    }

    .row-actions {
      display: inline-flex;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 6px;
    }

    .detail-action,
    .compare-action {
      padding: 6px 10px;
      font-size: 13px;
    }

    .muted { color: var(--muted); }

    tr.row-unknown {
      background: #fff8ef;
      box-shadow: inset 3px 0 0 var(--orange);
    }

    tr.row-unknown:hover { background: #fff2e0; }

    tr.row-unknown .item-name { color: var(--orange); }

    @keyframes rowFlash {
      0%, 100% { background: #fff8ef; }
      30% { background: #ffd9ad; }
    }

    tr.row-flash { animation: rowFlash 0.7s ease 2; }

    .notice {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin: 0 14px 12px;
      padding: 11px 14px;
      border: 1px solid #f0c99a;
      border-radius: 8px;
      background: #fff7ed;
      color: #7c4210;
    }

    .notice strong { font-weight: 750; }

    .notice .notice-text { flex: 1; min-width: 240px; }

    .notice button {
      border-color: var(--orange);
      background: var(--orange);
    }

    .returned-cell,
    .returned-value {
      color: var(--orange);
      font-weight: 650;
    }

    .net-cell { font-weight: 650; }

    .tag-return {
      background: #fff2e2;
      color: var(--orange);
    }

    .merge-panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
      overflow: hidden;
    }

    .merge-panel > summary {
      cursor: pointer;
      padding: 14px 16px;
      font-weight: 700;
      list-style: none;
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .merge-panel > summary::-webkit-details-marker { display: none; }

    .merge-panel > summary::before {
      content: "▸";
      color: var(--muted);
      font-size: 12px;
    }

    .merge-panel[open] > summary::before { content: "▾"; }

    .merge-panel > summary .muted { font-weight: 400; }

    .merge-body {
      padding: 0 16px 16px;
    }

    .merge-warning {
      border: 1px solid #f0c99a;
      background: #fff7ed;
      color: #7c4210;
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 12px;
    }

    .merge-warning ul {
      margin: 6px 0 0;
      padding-left: 18px;
    }

    .merge-warning li { margin-top: 4px; }

    .merge-table-wrap {
      max-height: 420px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    .merge-table { min-width: 780px; }

    .merge-table th,
    .merge-table td {
      font-size: 13px;
      padding: 8px 10px;
      vertical-align: top;
      width: auto;
    }

    .variant-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 3px 0;
      overflow-wrap: anywhere;
    }

    .variant-line + .variant-line { border-top: 1px dashed var(--line); }

    .variant-name {
      flex: 1;
      min-width: 0;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      overflow: hidden;
    }

    .detail-table .item-name { max-width: 420px; }

    .variant-line strong { font-weight: 650; }

    .variant-line .variant-quantity {
      color: var(--muted);
      white-space: nowrap;
    }

    .tag {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11.5px;
      font-weight: 650;
      white-space: nowrap;
    }

    .tag-merged {
      background: #eef0ff;
      color: var(--violet);
    }

    .tag-warn {
      background: #fff2e2;
      color: var(--orange);
      cursor: help;
    }

    .name-tags {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 4px;
    }

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

      .detail-metrics {
        grid-template-columns: 1fr;
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
        <div class="label">Hàng hoàn</div>
        <div class="value returned-value" id="returnedTotal">0</div>
      </div>
      <div class="metric">
        <div class="label">Thực bán</div>
        <div class="value" id="netTotal">0</div>
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

    <details class="merge-panel" id="mergePanel" hidden>
      <summary>
        <span id="mergeHeadline">Đã gộp tên hàng</span>
        <span class="muted" id="mergeSubline"></span>
      </summary>
      <div class="merge-body">
        <div class="merge-warning" id="mergeWarnings" hidden></div>
        <div class="merge-table-wrap">
          <table class="merge-table">
            <thead>
              <tr>
                <th class="number">STT</th>
                <th>Sản phẩm sau khi gộp</th>
                <th class="number">Hoàn</th>
                <th class="number">Tổng SL</th>
                <th>Các tên gốc trên hóa đơn</th>
              </tr>
            </thead>
            <tbody id="mergeRows"></tbody>
          </table>
        </div>
      </div>
    </details>

    <section class="main-grid">
      <section class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Bảng tổng hợp theo nguồn</div>
            <div class="muted" id="visibleSummary"></div>
          </div>
          <input id="searchInput" type="search" placeholder="Tìm tên hàng, đơn vị tính...">
        </div>
        <div class="notice" id="unknownNotice" hidden>
          <span class="notice-text" id="unknownNoticeText"></span>
          <button type="button" id="gotoUnknownButton">Đi đến</button>
        </div>
        <div id="sectionsContainer"></div>
        <div class="empty" id="emptyState" hidden>Không có mặt hàng phù hợp.</div>
      </section>
    </section>
  </main>

  <div class="toast" id="toast" role="status" aria-live="polite"></div>

  <div class="modal-backdrop" id="detailModal" hidden>
    <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="detailTitle">
      <div class="modal-head">
        <div>
          <div class="modal-title" id="detailTitle"></div>
          <div class="muted" id="detailSubtitle"></div>
        </div>
        <button class="secondary" id="closeDetailButton" type="button">Đóng</button>
      </div>
      <div class="modal-body">
        <div class="detail-metrics" id="detailMetrics"></div>
        <div class="muted" id="detailInvoicesLabel" style="margin-bottom: 6px;">Các số hóa đơn có mặt hàng này</div>
        <div class="invoice-list" id="detailInvoices"></div>
        <div class="detail-table-wrap">
          <table class="detail-table">
            <thead>
              <tr id="detailHeaderRow">
                <th class="number">STT</th>
                <th>Nguồn</th>
                <th class="number">Dòng</th>
                <th>Số hóa đơn</th>
                <th>Ngày hóa đơn</th>
                <th>Khách hàng</th>
                <th>Tên hàng gốc</th>
                <th>ĐVT</th>
                <th class="number">Số lượng</th>
                <th>Ghi chú</th>
                <th>invoice.html</th>
              </tr>
            </thead>
            <tbody id="detailRows"></tbody>
          </table>
        </div>
      </div>
    </section>
  </div>

  <script>
    const payload = __PAYLOAD_JSON__;
    const csvFileName = "__CSV_FILE__";
    let currentSections = [];
    let sortState = { key: "quantity", direction: -1 };

    const searchInput = document.getElementById("searchInput");
    const sectionsContainer = document.getElementById("sectionsContainer");
    const emptyState = document.getElementById("emptyState");
    const visibleSummary = document.getElementById("visibleSummary");
    const detailModal = document.getElementById("detailModal");
    const detailTitle = document.getElementById("detailTitle");
    const detailSubtitle = document.getElementById("detailSubtitle");
    const detailMetrics = document.getElementById("detailMetrics");
    const detailInvoicesLabel = document.getElementById("detailInvoicesLabel");
    const detailInvoices = document.getElementById("detailInvoices");
    const detailHeaderRow = document.getElementById("detailHeaderRow");
    const detailRows = document.getElementById("detailRows");

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

    function nameKey(value) {
      return String(value || "").trim().replace(/\\s+/g, " ").toLocaleLowerCase("vi");
    }

    function matchKey(row) {
      return row && row.productKey ? `key:${row.productKey}` : `name:${nameKey(row && row.name)}`;
    }

    const mergeReport = payload.mergeReport || {};
    const catalogLoaded = Boolean(mergeReport.catalogLoaded);
    const catalogFile = mergeReport.catalogFile || "danh mục thuốc";

    const toast = document.getElementById("toast");
    let toastTimer = null;

    function showToast(message) {
      toast.textContent = message;
      toast.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove("show"), 2200);
    }

    function copyFallback(text) {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.top = "-1000px";
      document.body.appendChild(area);
      area.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch (error) {
        copied = false;
      }
      area.remove();
      return copied;
    }

    function copyText(text) {
      const value = String(text || "");
      if (!value) {
        return;
      }
      const shortened = value.length > 70 ? `${value.slice(0, 70)}...` : value;
      const done = () => showToast(`Đã copy: ${shortened}`);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(done, () => {
          if (copyFallback(value)) {
            done();
          } else {
            showToast("Không copy được, hãy bôi đen rồi bấm Ctrl+C");
          }
        });
        return;
      }
      if (copyFallback(value)) {
        done();
      } else {
        showToast("Không copy được, hãy bôi đen rồi bấm Ctrl+C");
      }
    }

    // Tên hàng dài bị cắt còn 2 dòng: hover xem tên đầy đủ, bấm là copy.
    function nameCell(value, extraClass) {
      const text = String(value ?? "");
      return `<div class="item-name copyable ${extraClass || ""}" title="${escapeHtml(text)} (bấm để copy)" data-copy="${escapeHtml(text)}">${escapeHtml(text)}</div>`;
    }

    document.addEventListener("click", (event) => {
      const target = event.target.closest("[data-copy]");
      if (target) {
        event.stopPropagation();
        copyText(target.dataset.copy);
      }
    });

    function variantMarkup(variants) {
      if (!variants || !variants.length) {
        return "";
      }
      return variants.map((variant) => `
        <div class="variant-line">
          <span class="variant-name copyable" title="${escapeHtml(variant.name)} (bấm để copy)" data-copy="${escapeHtml(variant.name)}">
            ${variant.isCanonical ? "<strong>" : ""}${escapeHtml(variant.name)}${variant.isCanonical ? "</strong>" : ""}
            ${variant.isReturn ? `<span class="tag tag-return">hoàn</span>` : ""}
          </span>
          <span class="variant-quantity ${variant.isReturn ? "returned-cell" : ""}">${escapeHtml(variant.quantityText)}</span>
        </div>
      `).join("");
    }

    function allSourceSections() {
      return payload.sections && payload.sections.length
        ? payload.sections
        : [{ key: "all", title: "Tổng hợp", description: "", summary: payload.summary, rows: payload.rows }];
    }

    function applyFilterAndSort() {
      const query = searchInput.value.trim().toLocaleLowerCase("vi");
      const sourceSections = allSourceSections();

      currentSections = sourceSections.map((section) => {
        const rows = section.rows.filter((row) => {
          const text = `${row.name} ${row.unit}`.toLocaleLowerCase("vi");
          return !query || text.includes(query);
        }).sort(compareRows);
        return { ...section, rows };
      });
      renderSections();
    }

    function renderRows(rows, sectionKey) {
      return rows.map((row, index) => {
        const variants = row.variants || [];
        const unknown = catalogLoaded && row.unknown;
        const tags = [];
        if (variants.length > 1) {
          tags.push(`<span class="tag tag-merged" title="${escapeHtml(variants.map((item) => item.name).join(" | "))}">gộp ${formatNumber(variants.length)} tên</span>`);
        }
        if (unknown) {
          tags.push(`<span class="tag tag-warn" title="Tên này chưa có trong ${escapeHtml(catalogFile)}. Mở Danh mục thuốc trong cửa sổ chương trình để thêm.">⚠ chưa có trong danh mục</span>`);
        }
        if (row.ambiguous) {
          tags.push(`<span class="tag tag-warn" title="${escapeHtml(row.ambiguousNote || "")}">⚠ chưa rõ quy cách</span>`);
        }
        return `
        <tr class="${unknown ? "row-unknown" : ""}"${unknown ? ' data-unknown="1"' : ""}>
          <td class="number">${index + 1}</td>
          <td>
            ${nameCell(row.name)}
            ${tags.length ? `<div class="name-tags">${tags.join("")}</div>` : ""}
          </td>
          <td class="number ${row.returned ? "returned-cell" : "muted"}">${escapeHtml(row.returnedText)}</td>
          <td class="number">${escapeHtml(row.quantityText)}</td>
          <td class="number net-cell">${escapeHtml(row.netText)}</td>
          <td class="number">${formatNumber(row.lineCount)}</td>
          <td class="number">${formatNumber(row.invoiceCount)}</td>
          <td class="number">
            <span class="row-actions">
              <button class="secondary compare-action" type="button" data-section-key="${escapeHtml(sectionKey)}" data-row-key="${escapeHtml(row.rowKey)}">So sánh</button>
              <button class="secondary detail-action" type="button" data-section-key="${escapeHtml(sectionKey)}" data-row-key="${escapeHtml(row.rowKey)}">Chi tiết</button>
            </span>
          </td>
        </tr>
      `;
      }).join("");
    }

    function tableMarkup(section) {
      const visibleQuantity = section.rows.reduce((sum, row) => sum + (row.quantity || 0), 0);
      const visibleReturned = section.rows.reduce((sum, row) => sum + (row.returned || 0), 0);
      return `
        <section class="section-block">
          <div class="section-head">
            <div>
              <div class="section-title">${escapeHtml(section.title)}</div>
              <div class="section-desc">${escapeHtml(section.description || "")}</div>
            </div>
            <div class="section-stats">
              ${formatNumber(section.rows.length)} mặt hàng<br>
              Tổng SL ${formatNumber(visibleQuantity)}${visibleReturned ? ` - hoàn ${formatNumber(visibleReturned)} = ${formatNumber(visibleQuantity + visibleReturned)}` : ""}
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th class="number">STT</th>
                  <th data-key="name">Tên hàng</th>
                  <th class="number" data-key="returned" title="Hàng khách trả lại, lấy từ các dòng điều chỉnh giảm">Hoàn</th>
                  <th class="number" data-key="quantity">Tổng số lượng</th>
                  <th class="number" data-key="net" title="Thực bán = Tổng số lượng + Hoàn">Thực bán</th>
                  <th class="number" data-key="lineCount">Số dòng</th>
                  <th class="number" data-key="invoiceCount">Số hóa đơn</th>
                  <th class="number">Thao tác</th>
                </tr>
              </thead>
              <tbody>${renderRows(section.rows, section.key)}</tbody>
            </table>
          </div>
        </section>
      `;
    }

    function renderSections() {
      const allVisibleRows = currentSections.flatMap((section) => section.rows);
      const visibleSections = currentSections.filter((section) => section.rows.length > 0);
      sectionsContainer.innerHTML = visibleSections.map(tableMarkup).join("");

      renderUnknownNotice();
      emptyState.hidden = allVisibleRows.length > 0;
      const visibleQuantity = allVisibleRows.reduce((sum, row) => sum + (row.quantity || 0), 0);
      visibleSummary.textContent = `${formatNumber(visibleSections.length)} bảng, ${formatNumber(allVisibleRows.length)} mặt hàng, tổng số lượng ${formatNumber(visibleQuantity)}`;
    }

    function renderSummary() {
      const firstSource = payload.reports[0] || {};
      document.getElementById("generatedAt").textContent =
        `Tạo lúc ${payload.generatedAt}. Cột tên hàng: ${firstSource.product_column || "AB"}, cột số lượng: ${firstSource.quantity_column || "AE"}.`;
      document.getElementById("itemCount").textContent = formatNumber(payload.summary.itemCount);
      document.getElementById("quantityTotal").textContent = payload.summary.quantityText;
      document.getElementById("returnedTotal").textContent = payload.summary.returnedText ?? "0";
      document.getElementById("netTotal").textContent = payload.summary.netText ?? payload.summary.quantityText;
      document.getElementById("lineCount").textContent = formatNumber(payload.summary.lineCount);
      document.getElementById("invoiceCount").textContent = formatNumber(payload.summary.invoiceCount);
    }

    const unknownNotice = document.getElementById("unknownNotice");
    const unknownNoticeText = document.getElementById("unknownNoticeText");
    let unknownCursor = -1;

    function unknownRowElements() {
      return [...sectionsContainer.querySelectorAll("tr[data-unknown]")];
    }

    function renderUnknownNotice() {
      const rows = catalogLoaded ? unknownRowElements() : [];
      unknownCursor = -1;
      if (!rows.length) {
        unknownNotice.hidden = true;
        return;
      }
      const names = currentSections
        .flatMap((section) => section.rows)
        .filter((row) => row.unknown)
        .map((row) => row.name);
      const preview = [...new Set(names)].slice(0, 2).join(" | ");
      unknownNoticeText.innerHTML =
        `⚠ <strong>${formatNumber(rows.length)} tên hàng chưa có trong ${escapeHtml(catalogFile)}</strong>`
        + ` - ${escapeHtml(preview)}${names.length > 2 ? "..." : ""}`
        + ` - mở <strong>Danh mục thuốc</strong> trong cửa sổ chương trình để thêm.`;
      unknownNotice.hidden = false;
    }

    function gotoNextUnknown() {
      const rows = unknownRowElements();
      if (!rows.length) {
        return;
      }
      unknownCursor = (unknownCursor + 1) % rows.length;
      const target = rows[unknownCursor];
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      rows.forEach((row) => row.classList.remove("row-flash"));
      // Gỡ rồi gắn lại để animation chạy lại khi bấm liên tiếp cùng một hàng.
      void target.offsetWidth;
      target.classList.add("row-flash");
      if (rows.length > 1) {
        showToast(`Tên chưa có trong danh mục ${unknownCursor + 1}/${rows.length}`);
      }
    }

    function renderMergeReport() {
      const report = payload.mergeReport;
      const panel = document.getElementById("mergePanel");
      if (!report || !report.enabled || !(report.groups || []).length) {
        panel.hidden = true;
        return;
      }

      document.getElementById("mergeHeadline").textContent =
        `Đã gộp ${formatNumber(report.mergedNameCount)} tên trên hóa đơn thành ${formatNumber(report.mergedGroupCount)} sản phẩm`;
      const notes = [];
      if (catalogLoaded) {
        notes.push(`${catalogFile}: ${formatNumber(report.catalogSize)} thuốc`);
      } else if (report.catalogError) {
        notes.push(report.catalogError);
      }
      if (report.unknownCount) {
        notes.push(`${formatNumber(report.unknownCount)} tên chưa có trong danh mục`);
      }
      if (report.ambiguousCount) {
        notes.push(`${formatNumber(report.ambiguousCount)} tên chưa rõ quy cách`);
      }
      document.getElementById("mergeSubline").textContent = notes.join(" - ");

      const warned = report.groups.filter((group) => group.ambiguous);
      const warningBox = document.getElementById("mergeWarnings");
      warningBox.hidden = !warned.length;
      if (warned.length) {
        warningBox.innerHTML = `
          <strong>⚠ ${formatNumber(warned.length)} tên không ghi quy cách nên chưa gộp được</strong>
          <ul>
            ${warned.map((group) => `<li><strong>${escapeHtml(group.name)}</strong> - ${escapeHtml(group.ambiguousNote)}</li>`).join("")}
          </ul>
        `;
      }

      document.getElementById("mergeRows").innerHTML = report.groups.map((group, index) => {
        const tags = [];
        if (group.variantCount > 1) {
          tags.push(`<span class="tag tag-merged">gộp ${formatNumber(group.variantCount)} tên</span>`);
        }
        if (group.ambiguous) {
          tags.push(`<span class="tag tag-warn" title="${escapeHtml(group.ambiguousNote || "")}">⚠ chưa rõ quy cách</span>`);
        }
        return `
          <tr>
            <td class="number">${index + 1}</td>
            <td>
              ${nameCell(group.name)}
              ${tags.length ? `<div class="name-tags">${tags.join("")}</div>` : ""}
            </td>
            <td class="number returned-cell">${escapeHtml(group.returnedText)}</td>
            <td class="number">${escapeHtml(group.quantityText)}</td>
            <td>${variantMarkup(group.variants)}</td>
          </tr>
        `;
      }).join("");

      panel.hidden = false;
    }

    function uniqueValues(values) {
      return [...new Set(values.filter((value) => String(value || "").trim()))];
    }

    function closeDetail() {
      detailModal.hidden = true;
    }

    function openDetail(sectionKey, rowKey) {
      const section = currentSections.find((item) => String(item.key) === String(sectionKey));
      if (!section) {
        return;
      }
      const row = section.rows.find((item) => String(item.rowKey) === String(rowKey));
      if (!row) {
        return;
      }

      const details = row.details || [];
      const variants = row.variants || [];
      const invoiceNumbers = uniqueValues(details.map((detail) => detail.invoiceNumber));
      const invoiceFiles = uniqueValues(details.map((detail) => detail.invoiceHtmlUri));

      detailTitle.textContent = row.name;
      detailSubtitle.textContent = `${section.title} - ${formatNumber(details.length)} dòng gốc được cộng vào tổng`;
      if (variants.length > 1) {
        detailSubtitle.textContent += ` - gộp từ ${formatNumber(variants.length)} tên hàng khác nhau`;
      }
      if (row.ambiguous) {
        detailSubtitle.textContent += ` - ⚠ ${row.ambiguousNote || ""}`;
      }
      detailInvoicesLabel.textContent = variants.length > 1
        ? "Các tên gốc đã gộp vào sản phẩm này"
        : "Các số hóa đơn có mặt hàng này";
      detailMetrics.innerHTML = `
        <div class="detail-metric"><span>ĐVT</span><strong>${escapeHtml(row.unit || "-")}</strong></div>
        <div class="detail-metric"><span>Tổng số lượng</span><strong>${escapeHtml(row.quantityText)}</strong></div>
        <div class="detail-metric"><span>Hoàn</span><strong class="${row.returned ? "returned-value" : ""}">${escapeHtml(row.returnedText)}</strong></div>
        <div class="detail-metric"><span>Thực bán</span><strong>${escapeHtml(row.netText)}</strong></div>
        <div class="detail-metric"><span>Số dòng</span><strong>${formatNumber(row.lineCount)}</strong></div>
        <div class="detail-metric"><span>Số hóa đơn</span><strong>${formatNumber(row.invoiceCount)}</strong></div>
      `;
      if (variants.length > 1) {
        detailInvoices.innerHTML = variantMarkup(variants);
      } else {
        detailInvoices.innerHTML = invoiceNumbers.length
          ? invoiceNumbers.map((invoice) => `<span class="invoice-pill">${escapeHtml(invoice)}</span>`).join("")
          : `<span class="invoice-pill">Không có số hóa đơn</span>`;
      }

      detailHeaderRow.innerHTML = `
        <th class="number">STT</th>
        <th>Nguồn</th>
        <th class="number">Dòng</th>
        <th>Số hóa đơn</th>
        <th>Ngày hóa đơn</th>
        <th>Khách hàng</th>
        <th>Tên hàng gốc</th>
        <th>ĐVT</th>
        <th class="number">Số lượng</th>
        <th>Ghi chú</th>
        <th>invoice.html</th>
      `;
      detailRows.innerHTML = details.map((detail, index) => {
        const customerText = [detail.customerCode, detail.customerName].filter(Boolean).join(" - ");
        const invoiceLink = detail.invoiceHtmlUri
          ? `<a class="open-link" href="${escapeHtml(detail.invoiceHtmlUri)}" target="_blank" rel="noopener">Mở file</a>`
          : "";
        const rowClass = detail.isAdjustment ? "adjustment-row" : "";
        return `
          <tr class="${rowClass}">
            <td class="number">${index + 1}</td>
            <td>${escapeHtml(detail.sourceLabel || detail.sourceFile || "")}</td>
            <td class="number">${detail.rowNumber ? formatNumber(detail.rowNumber) : ""}</td>
            <td>${escapeHtml(detail.invoiceNumber || "")}</td>
            <td>${escapeHtml(detail.invoiceDate || "")}</td>
            <td>${escapeHtml(customerText)}</td>
            <td>${nameCell(detail.itemName || "")}</td>
            <td>${escapeHtml(detail.unit || "")}</td>
            <td class="number">${escapeHtml(detail.quantityText || "")}</td>
            <td>${escapeHtml(detail.note || detail.status || "")}</td>
            <td>${invoiceLink}</td>
          </tr>
        `;
      }).join("");

      if (invoiceFiles.length) {
        detailSubtitle.textContent += ` - ${formatNumber(invoiceFiles.length)} file invoice.html có thể mở`;
      }
      detailModal.hidden = false;
    }

    function openCompare(sectionKey, rowKey) {
      const baseSection = allSourceSections().find((item) => String(item.key) === String(sectionKey));
      if (!baseSection) {
        return;
      }
      const baseRow = baseSection.rows.find((item) => String(item.rowKey) === String(rowKey));
      if (!baseRow) {
        return;
      }

      const targetKey = matchKey(baseRow);
      const comparedRows = allSourceSections().map((section) => {
        const matched = section.rows.find((row) => matchKey(row) === targetKey);
        const quantity = matched ? Number(matched.quantity || 0) : 0;
        const diff = quantity - Number(baseRow.quantity || 0);
        return { section, row: matched, quantity, diff };
      });

      const allVariants = [];
      comparedRows.forEach((item) => {
        (item.row ? item.row.variants || [] : []).forEach((variant) => allVariants.push(variant));
      });

      detailTitle.textContent = `So sánh: ${baseRow.name}`;
      detailSubtitle.textContent = `So sánh cùng một sản phẩm giữa ${formatNumber(comparedRows.length)} bảng. Bảng gốc: ${baseSection.title}.`;
      detailMetrics.innerHTML = `
        <div class="detail-metric"><span>Bảng gốc</span><strong>${escapeHtml(baseSection.title)}</strong></div>
        <div class="detail-metric"><span>Số lượng gốc</span><strong>${escapeHtml(baseRow.quantityText)}</strong></div>
        <div class="detail-metric"><span>Số bảng có sản phẩm</span><strong>${formatNumber(comparedRows.filter((item) => item.row).length)}</strong></div>
        <div class="detail-metric"><span>Số tên gốc đã gộp</span><strong>${formatNumber(new Set(allVariants.map((variant) => variant.name)).size)}</strong></div>
      `;
      detailInvoicesLabel.textContent = "Ghi chú so sánh";
      detailInvoices.innerHTML = `
        <span class="invoice-pill">${baseRow.productKey
          ? "So sánh theo sản phẩm: bỏ tiền tố \\"Thực phẩm bảo vệ sức khỏe\\", số lô - hạn dùng, hoa/thường; quy cách khác nhau vẫn tách riêng"
          : "So sánh theo tên hàng giống hệt sau khi chuẩn hóa khoảng trắng và chữ hoa/thường"}</span>
        <span class="invoice-pill">Chênh lệch = Số lượng từng bảng - Số lượng bảng gốc</span>
        ${baseRow.ambiguous ? `<span class="invoice-pill">⚠ ${escapeHtml(baseRow.ambiguousNote || "")}</span>` : ""}
      `;
      detailHeaderRow.innerHTML = `
        <th class="number">STT</th>
        <th>Nguồn</th>
        <th>Trạng thái</th>
        <th class="number">Hoàn</th>
        <th class="number">Tổng số lượng</th>
        <th class="number">Thực bán</th>
        <th class="number">Chênh lệch</th>
        <th class="number">Số dòng</th>
        <th class="number">Số hóa đơn</th>
        <th>Tên gốc trong bảng</th>
      `;
      detailRows.innerHTML = comparedRows.map((item, index) => {
        const matched = item.row;
        const diffText = item.diff > 0 ? `+${formatNumber(item.diff)}` : formatNumber(item.diff);
        return `
          <tr>
            <td class="number">${index + 1}</td>
            <td>${escapeHtml(item.section.title)}</td>
            <td>${matched ? "Có" : "Không có"}</td>
            <td class="number ${matched && matched.returned ? "returned-cell" : "muted"}">${matched ? escapeHtml(matched.returnedText) : "0"}</td>
            <td class="number">${matched ? escapeHtml(matched.quantityText) : "0"}</td>
            <td class="number net-cell">${matched ? escapeHtml(matched.netText) : "0"}</td>
            <td class="number">${diffText}</td>
            <td class="number">${matched ? formatNumber(matched.lineCount) : "0"}</td>
            <td class="number">${matched ? formatNumber(matched.invoiceCount) : "0"}</td>
            <td>${matched ? variantMarkup(matched.variants) : `<div class="item-name muted">Không có trong bảng này</div>`}</td>
          </tr>
        `;
      }).join("");
      detailModal.hidden = false;
    }

    function csvCell(value) {
      const text = String(value ?? "");
      return `"${text.replace(/"/g, '""')}"`;
    }

    function downloadCsv() {
      const header = ["Nguồn", "STT", "Tên hàng", "Tổng số lượng", "Số dòng", "Số hóa đơn"];
      const rows = currentSections.flatMap((section) =>
        section.rows.map((row, index) => [
          section.title,
          index + 1,
          row.name,
          row.quantityText,
          row.lineCount,
          row.invoiceCount
        ])
      );
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

    sectionsContainer.addEventListener("click", (event) => {
      const header = event.target.closest("th[data-key]");
      if (header) {
        const key = header.dataset.key;
        sortState = {
          key,
          direction: sortState.key === key ? sortState.direction * -1 : (key === "name" || key === "unit" ? 1 : -1)
        };
        applyFilterAndSort();
        return;
      }

      const detailButton = event.target.closest("button.detail-action");
      if (detailButton) {
        openDetail(detailButton.dataset.sectionKey, detailButton.dataset.rowKey);
        return;
      }

      const compareButton = event.target.closest("button.compare-action");
      if (compareButton) {
        openCompare(compareButton.dataset.sectionKey, compareButton.dataset.rowKey);
      }
    });

    searchInput.addEventListener("input", applyFilterAndSort);
    document.getElementById("resetButton").addEventListener("click", () => {
      searchInput.value = "";
      sortState = { key: "quantity", direction: -1 };
      applyFilterAndSort();
    });
    document.getElementById("downloadButton").addEventListener("click", downloadCsv);
    document.getElementById("gotoUnknownButton").addEventListener("click", gotoNextUnknown);
    document.getElementById("closeDetailButton").addEventListener("click", closeDetail);
    detailModal.addEventListener("click", (event) => {
      if (event.target === detailModal) {
        closeDetail();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeDetail();
      }
    });

    renderSummary();
    renderMergeReport();
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
    parser.add_argument(
        "--invoice-folder",
        action="append",
        default=[],
        help="Thư mục chứa invoice.xml/invoice.html. Có thể truyền nhiều lần.",
    )
    parser.add_argument(
        "--invoice-zip",
        action="append",
        default=[],
        help="File ZIP hóa đơn chứa invoice.xml/invoice.html. Có thể truyền nhiều lần.",
    )
    return parser.parse_args(argv)


def create_report(
    raw_inputs: list[str],
    invoice_folders: list[str] | None,
    invoice_zips: list[str] | None,
    sheet: str | None,
    out: str,
    csv_out: str,
    output_base: Path,
    open_report: bool,
) -> ReportResult:
    input_files = resolve_input_files(raw_inputs) if raw_inputs else []
    invoice_folder_paths = [Path(folder).resolve() for folder in (invoice_folders or []) if str(folder).strip()]
    invoice_zip_paths = [Path(zip_path).resolve() for zip_path in (invoice_zips or []) if str(zip_path).strip()]
    if not input_files and not invoice_folder_paths and not invoice_zip_paths:
        raise ValueError("Không tìm thấy file .csv/.xls/.xlsx, thư mục hóa đơn hoặc file ZIP nào để thống kê.")

    all_lines: list[InvoiceLine] = []
    detail_lines: list[InvoiceLine] = []
    invoice_source_lines: list[InvoiceLine] = []
    reports: list[ImportReport] = []
    detail_reports: list[ImportReport] = []
    invoice_source_reports: list[ImportReport] = []
    errors: list[str] = []

    extracted_folders, zip_errors = extract_invoice_zips(invoice_zip_paths)
    invoice_folder_paths.extend(extracted_folders)
    errors.extend(zip_errors)

    for path in input_files:
        try:
            lines, report = read_invoice_lines(path, sheet)
        except Exception as exc:  # noqa: BLE001 - show every input error to the user.
            errors.append(f"{path.name}: {exc}")
            continue
        all_lines.extend(lines)
        detail_lines.extend(lines)
        reports.append(report)
        detail_reports.append(report)

    for folder in invoice_folder_paths:
        try:
            folder_read = read_invoice_folder(folder)
        except Exception as exc:  # noqa: BLE001 - collect every folder error for the user.
            errors.append(f"{folder}: {exc}")
            continue
        all_lines.extend(folder_read.lines)
        invoice_source_lines.extend(folder_read.lines)
        reports.append(folder_read.report)
        invoice_source_reports.append(folder_read.report)

    if not all_lines:
        detail = "\n".join(f"- {error}" for error in errors)
        message = "Không đọc được dòng dữ liệu nào."
        if detail:
            message += "\n" + detail
        raise ValueError(message)

    catalog = read_product_catalog()
    # Bộ khớp dựng từ toàn bộ tên hàng nên hai bảng gộp giống hệt nhau, So sánh mới khớp được.
    # Dòng hoàn chỉ góp phần tên sản phẩm trích ra, dòng điều chỉnh khác thì bỏ qua hẳn.
    product_names = product_names_for_matching(all_lines)
    matcher = ProductMatcher(product_names, catalog)

    stats = aggregate_lines(all_lines, matcher)
    sections: list[dict[str, object]] = []
    if detail_lines:
        detail_stats = aggregate_lines(detail_lines, matcher)
        sections.append(
            {
                "key": "detail",
                "title": "Bảng kê chi tiết hóa đơn",
                "description": "Dữ liệu từ file Bang_ke_chi_tiet_HD (.csv/.xls/.xlsx/.xlsm).",
                "summary": stats_summary(detail_stats, len(detail_lines)),
                "rows": stats_to_rows(detail_stats),
                "reports": [report.__dict__ for report in detail_reports],
            }
        )
    if invoice_source_lines:
        invoice_stats = aggregate_lines(invoice_source_lines, matcher)
        sections.append(
            {
                "key": "invoice_sources",
                "title": "Hóa đơn HTML/XML/ZIP",
                "description": "Dữ liệu từ các thư mục hóa đơn và file ZIP hóa đơn.",
                "summary": stats_summary(invoice_stats, len(invoice_source_lines)),
                "rows": stats_to_rows(invoice_stats),
                "reports": [report.__dict__ for report in invoice_source_reports],
            }
        )
    output_html = Path(out)
    output_csv = Path(csv_out)
    if not output_html.is_absolute():
        output_html = BASE_DIR / output_html
    if not output_csv.is_absolute():
        output_csv = BASE_DIR / output_csv

    payload = build_payload(stats, reports, len(all_lines), sections, matcher)
    write_csv_report(stats, output_csv, sections)
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
        unknown_names=[stat.name for stat in stats if stat.key != OTHER_ADJUST_KEY and not stat.in_catalog],
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
                        invoice_folders=None,
                        invoice_zips=None,
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


def open_catalog_window(parent: object, colors: dict[str, str], unknown_names: list[str]) -> None:
    """Cửa sổ thêm/sửa/xóa tên thuốc, lưu thẳng vào Tên Sản Phẩm.xlsx."""
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk

    catalog = read_product_catalog()
    products = [CatalogProduct(name=item.name, aliases=list(item.aliases)) for item in catalog.products]
    catalog_path = catalog.path or default_catalog_path()

    window = tk.Toplevel(parent)  # type: ignore[arg-type]
    window.title("Danh mục thuốc")
    window.geometry("1040x600")
    window.minsize(880, 520)
    window.configure(bg=colors["bg"])
    window.transient(parent)  # type: ignore[arg-type]
    window.grab_set()

    dirty = False
    status_var = tk.StringVar(value=f"{len(products)} thuốc - {catalog_path}")

    outer = tk.Frame(window, bg=colors["bg"], padx=16, pady=14)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=3)
    outer.columnconfigure(1, weight=2)
    outer.rowconfigure(1, weight=1)

    tk.Label(
        outer,
        text="Cột A là tên hàng chính, các cột sau là tên khác của cùng thuốc đó.",
        bg=colors["bg"],
        fg=colors["muted"],
        font=("Segoe UI", 10),
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

    table_frame = tk.Frame(outer, bg=colors["panel"], highlightbackground=colors["line"], highlightthickness=1)
    table_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)

    tree = ttk.Treeview(table_frame, columns=("name", "aliases"), show="headings", selectmode="browse")
    tree.heading("name", text="Tên hàng")
    tree.heading("aliases", text="Tên khác")
    tree.column("name", width=330, anchor="w")
    tree.column("aliases", width=330, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree_scroll.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=tree_scroll.set)

    side = tk.Frame(outer, bg=colors["panel"], highlightbackground=colors["line"], highlightthickness=1, padx=12, pady=10)
    side.grid(row=1, column=1, sticky="nsew")
    side.rowconfigure(2, weight=1)
    side.columnconfigure(0, weight=1)
    tk.Label(
        side,
        text="Tên trên hóa đơn chưa có trong danh mục",
        bg=colors["panel"],
        fg=colors["ink"],
        font=("Segoe UI", 11, "bold"),
    ).grid(row=0, column=0, sticky="w")
    tk.Label(
        side,
        text="Chọn một tên rồi bấm nút bên dưới để đưa vào danh mục.",
        bg=colors["panel"],
        fg=colors["muted"],
        font=("Segoe UI", 9),
        wraplength=330,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(3, 8))

    unknown_box = tk.Listbox(
        side,
        selectmode="browse",
        bg="#fffaf3",
        fg=colors["ink"],
        highlightthickness=1,
        highlightbackground=colors["line"],
        relief="flat",
        font=("Segoe UI", 9),
    )
    unknown_box.grid(row=2, column=0, sticky="nsew")
    for name in unknown_names:
        unknown_box.insert(tk.END, name)
    if not unknown_names:
        unknown_box.insert(tk.END, "(chạy thống kê để thấy các tên chưa có)")

    def refresh_tree(select_index: int | None = None) -> None:
        tree.delete(*tree.get_children())
        for index, product in enumerate(products):
            tree.insert("", "end", iid=str(index), values=(product.name, " | ".join(product.aliases)))
        if select_index is not None and 0 <= select_index < len(products):
            tree.selection_set(str(select_index))
            tree.see(str(select_index))
        mark = " (chưa lưu)" if dirty else ""
        status_var.set(f"{len(products)} thuốc{mark} - {catalog_path}")

    def selected_index() -> int | None:
        selection = tree.selection()
        return int(selection[0]) if selection else None

    def edit_product(index: int | None) -> None:
        nonlocal dirty
        current = products[index] if index is not None else CatalogProduct(name="")
        form = tk.Toplevel(window)
        form.title("Sửa thuốc" if index is not None else "Thêm thuốc")
        form.configure(bg=colors["bg"])
        form.transient(window)
        form.grab_set()
        form.geometry("620x360")
        body = tk.Frame(form, bg=colors["bg"], padx=16, pady=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        entries: list[tk.Entry] = []
        values = [current.name, *current.aliases]
        while len(values) <= CATALOG_ALIAS_COLUMNS:
            values.append("")
        for row_index, label in enumerate(CATALOG_HEADERS[: CATALOG_ALIAS_COLUMNS + 1]):
            tk.Label(
                body,
                text=label,
                bg=colors["bg"],
                fg=colors["ink"],
                font=("Segoe UI", 10, "bold" if row_index == 0 else "normal"),
            ).grid(row=row_index, column=0, sticky="w", pady=4, padx=(0, 10))
            entry = ttk.Entry(body, width=60)
            entry.insert(0, values[row_index])
            entry.grid(row=row_index, column=1, sticky="ew", pady=4)
            entries.append(entry)
        entries[0].focus_set()

        def save_form() -> None:
            nonlocal dirty
            name = clean_cell(entries[0].get())
            if not name:
                messagebox.showwarning("Thiếu tên hàng", "Cột Tên hàng không được để trống.", parent=form)
                return
            aliases = [clean_cell(entry.get()) for entry in entries[1:]]
            aliases = [value for value in aliases if value and value != name]
            product = CatalogProduct(name=name, aliases=aliases)
            if index is None:
                products.append(product)
            else:
                products[index] = product
            dirty = True
            form.destroy()
            refresh_tree(len(products) - 1 if index is None else index)

        buttons = tk.Frame(body, bg=colors["bg"])
        buttons.grid(row=CATALOG_ALIAS_COLUMNS + 1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Xong", command=save_form, style="Accent.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Hủy", command=form.destroy, style="Secondary.TButton").pack(side="left")
        form.bind("<Return>", lambda _event: save_form())
        form.bind("<Escape>", lambda _event: form.destroy())

    def add_product() -> None:
        edit_product(None)

    def edit_selected() -> None:
        index = selected_index()
        if index is None:
            messagebox.showinfo("Chưa chọn", "Hãy chọn một thuốc trong danh sách.", parent=window)
            return
        edit_product(index)

    def delete_selected() -> None:
        nonlocal dirty
        index = selected_index()
        if index is None:
            messagebox.showinfo("Chưa chọn", "Hãy chọn một thuốc trong danh sách.", parent=window)
            return
        if not messagebox.askyesno("Xóa thuốc", f"Xóa \"{products[index].name}\" khỏi danh mục?", parent=window):
            return
        products.pop(index)
        dirty = True
        refresh_tree(min(index, len(products) - 1) if products else None)

    def selected_unknown() -> str:
        selection = unknown_box.curselection()
        if not selection or not unknown_names:
            return ""
        return unknown_names[selection[0]] if selection[0] < len(unknown_names) else ""

    def unknown_as_new() -> None:
        nonlocal dirty
        name = selected_unknown()
        if not name:
            messagebox.showinfo("Chưa chọn", "Hãy chọn một tên ở danh sách bên phải.", parent=window)
            return
        products.append(CatalogProduct(name=name))
        dirty = True
        refresh_tree(len(products) - 1)

    def unknown_as_alias() -> None:
        nonlocal dirty
        name = selected_unknown()
        index = selected_index()
        if not name or index is None:
            messagebox.showinfo(
                "Chưa chọn đủ",
                "Chọn một thuốc ở bảng bên trái và một tên ở danh sách bên phải.",
                parent=window,
            )
            return
        product = products[index]
        if len(product.aliases) >= CATALOG_ALIAS_COLUMNS:
            messagebox.showwarning(
                "Hết chỗ",
                f"\"{product.name}\" đã có đủ {CATALOG_ALIAS_COLUMNS} tên khác.",
                parent=window,
            )
            return
        if name != product.name and name not in product.aliases:
            product.aliases.append(name)
            dirty = True
        refresh_tree(index)

    def save_catalog() -> None:
        nonlocal dirty
        try:
            write_product_catalog(catalog_path, products)
        except Exception as exc:  # noqa: BLE001 - báo lỗi ghi file cho người dùng.
            messagebox.showerror("Không lưu được", str(exc), parent=window)
            return
        dirty = False
        refresh_tree(selected_index())
        messagebox.showinfo(
            "Đã lưu",
            f"Đã lưu {len(products)} thuốc vào:\n{catalog_path}\n\nChạy lại thống kê để áp dụng.",
            parent=window,
        )

    def close_window() -> None:
        if dirty and not messagebox.askyesno(
            "Chưa lưu", "Danh mục đang có thay đổi chưa lưu. Đóng luôn?", parent=window
        ):
            return
        window.destroy()

    side_buttons = tk.Frame(side, bg=colors["panel"])
    side_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    ttk.Button(side_buttons, text="Thành thuốc mới", command=unknown_as_new, style="Accent.TButton").pack(
        fill="x", pady=(0, 6)
    )
    ttk.Button(
        side_buttons,
        text="Thành tên khác của thuốc đang chọn",
        command=unknown_as_alias,
        style="Secondary.TButton",
    ).pack(fill="x")

    actions = tk.Frame(outer, bg=colors["bg"])
    actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    ttk.Button(actions, text="Thêm thuốc", command=add_product, style="Accent.TButton").pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Sửa", command=edit_selected, style="Secondary.TButton").pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Xóa", command=delete_selected, style="Secondary.TButton").pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Lưu vào file", command=save_catalog, style="Accent.TButton").pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Đóng", command=close_window, style="Secondary.TButton").pack(side="right")

    tk.Label(
        outer,
        textvariable=status_var,
        bg=colors["bg"],
        fg=colors["muted"],
        font=("Segoe UI", 9),
        wraplength=980,
        justify="left",
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

    tree.bind("<Double-1>", lambda _event: edit_selected())
    window.protocol("WM_DELETE_WINDOW", close_window)
    refresh_tree(0 if products else None)
    if catalog.error:
        status_var.set(catalog.error)


def run_desktop_app(args: argparse.Namespace) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:  # noqa: BLE001 - tkinter can be unavailable on stripped Python installs.
        print(f"Không mở được cửa sổ desktop: {exc}")
        return 1

    root = tk.Tk()
    root.title("Thống kê hóa đơn MISA")
    window_width = 980
    window_height = 620
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    position_x = max(0, (screen_width - window_width) // 2)
    position_y = max(0, (screen_height - window_height) // 2)
    root.geometry(f"{window_width}x{window_height}+{position_x}+{position_y}")
    root.minsize(860, 540)

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
    selected_invoice_sources: list[Path] = []
    last_result: ReportResult | None = None
    file_var = tk.StringVar(value="")
    file_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="Chọn file Bang_ke_chi_tiet_HD hoặc file ZIP hóa đơn, sau đó bấm Chạy thống kê.")

    outer = tk.Frame(root, bg=colors["bg"], padx=18, pady=16)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(4, weight=1)

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
        text="EXCEL / CSV / ZIP",
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

    source_frame = tk.Frame(
        outer,
        bg=colors["panel"],
        highlightbackground=colors["line"],
        highlightthickness=1,
        padx=14,
        pady=12,
    )
    source_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
    source_frame.columnconfigure(0, weight=1)

    tk.Label(
        source_frame,
        text="File ZIP hóa đơn HTML/XML",
        bg=colors["panel"],
        fg=colors["ink"],
        font=("Segoe UI", 11, "bold"),
    ).grid(row=0, column=0, columnspan=3, sticky="w")
    tk.Label(
        source_frame,
        text="Chọn một hoặc nhiều file ZIP hóa đơn. Mỗi ZIP sẽ được giải nén riêng để tránh trùng invoice.xml/invoice.html.",
        bg=colors["panel"],
        fg=colors["muted"],
        font=("Segoe UI", 9),
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 10))

    source_box = tk.Listbox(
        source_frame,
        height=3,
        selectmode="extended",
        bg="#fbfefd",
        fg=colors["ink"],
        highlightthickness=1,
        highlightbackground=colors["line"],
        relief="flat",
        font=("Segoe UI", 9),
    )
    source_box.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
    source_scrollbar = ttk.Scrollbar(source_frame, orient="vertical", command=source_box.yview)
    source_scrollbar.grid(row=2, column=1, sticky="ns", padx=(0, 10))
    source_box.configure(yscrollcommand=source_scrollbar.set)

    source_buttons = tk.Frame(source_frame, bg=colors["panel"])
    source_buttons.grid(row=2, column=2, sticky="ns")

    actions = tk.Frame(
        outer,
        bg=colors["panel"],
        highlightbackground=colors["line"],
        highlightthickness=1,
        padx=14,
        pady=12,
    )
    actions.grid(row=3, column=0, sticky="ew", pady=(0, 12))
    actions.columnconfigure(5, weight=1)

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
    result_box.grid(row=4, column=0, sticky="nsew")
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

    def refresh_source_box() -> None:
        source_box.delete(0, tk.END)
        for source in selected_invoice_sources:
            source_box.insert(tk.END, f"[ZIP] {source}")
        if selected_invoice_sources:
            status_var.set(f"Đã chọn {len(selected_invoice_sources)} file ZIP hóa đơn.")

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

    def downloads_dir() -> Path:
        path = Path.home() / "Downloads"
        return path if path.is_dir() else BASE_DIR

    def choose_invoice_zips() -> None:
        files = filedialog.askopenfilenames(
            title="Chọn file ZIP hóa đơn",
            initialdir=str(downloads_dir()),
            filetypes=ZIP_FILETYPES,
        )
        if not files:
            return
        for file in files:
            path = Path(file)
            if path not in selected_invoice_sources:
                selected_invoice_sources.append(path)
        report_button.configure(state="disabled")
        csv_button.configure(state="disabled")
        refresh_source_box()

    def remove_selected_sources() -> None:
        selected_indexes = set(source_box.curselection())
        if not selected_indexes:
            return
        kept = [source for index, source in enumerate(selected_invoice_sources) if index not in selected_indexes]
        selected_invoice_sources.clear()
        selected_invoice_sources.extend(kept)
        report_button.configure(state="disabled")
        csv_button.configure(state="disabled")
        refresh_source_box()

    def clear_invoice_sources() -> None:
        selected_invoice_sources.clear()
        report_button.configure(state="disabled")
        csv_button.configure(state="disabled")
        refresh_source_box()
        if not selected_file:
            status_var.set("Chưa chọn file Bang_ke_chi_tiet_HD hoặc file ZIP hóa đơn.")

    def open_report() -> None:
        if last_result:
            open_path(last_result.output_html)

    def open_csv() -> None:
        if last_result:
            open_path(last_result.output_csv)

    def open_catalog() -> None:
        open_catalog_window(root, colors, last_result.unknown_names if last_result else [])

    def set_running(is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        for child in actions.winfo_children():
            child.configure(state=state)
        browse_button.configure(state=state)
        for child in source_buttons.winfo_children():
            child.configure(state=state)
        if not is_running:
            report_button.configure(state="normal" if last_result else "disabled")
            csv_button.configure(state="normal" if last_result else "disabled")

    def run_report() -> None:
        nonlocal last_result
        invoice_zips = selected_invoice_sources[:]

        if selected_file is None and not selected_invoice_sources:
            messagebox.showwarning(
                "Chưa chọn dữ liệu",
                "Vui lòng chọn file Bang_ke_chi_tiet_HD hoặc file ZIP hóa đơn.",
            )
            return

        if selected_file is not None and not selected_file.is_file():
            messagebox.showerror("File không tồn tại", f"File không tồn tại:\n{selected_file}")
            return
        missing_zips = [str(zip_path) for zip_path in invoice_zips if not zip_path.is_file()]
        if missing_zips:
            messagebox.showerror(
                "File ZIP không tồn tại",
                "Một số file ZIP không tồn tại:\n" + "\n".join(missing_zips),
            )
            return

        set_running(True)
        status_var.set("Đang đọc dữ liệu và tạo báo cáo...")
        root.update_idletasks()

        try:
            result = create_report(
                raw_inputs=[str(selected_file)] if selected_file else [],
                invoice_folders=[],
                invoice_zips=[str(zip_path) for zip_path in invoice_zips],
                sheet=args.sheet,
                out=args.out,
                csv_out=args.csv,
                output_base=BASE_DIR,
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

    ttk.Button(
        source_buttons,
        text="Chọn ZIP hóa đơn",
        command=choose_invoice_zips,
        style="Accent.TButton",
    ).pack(fill="x", pady=(0, 8))
    ttk.Button(
        source_buttons,
        text="Bỏ nguồn đã chọn",
        command=remove_selected_sources,
        style="Secondary.TButton",
    ).pack(fill="x", pady=(0, 8))
    ttk.Button(
        source_buttons,
        text="Xóa nguồn",
        command=clear_invoice_sources,
        style="Secondary.TButton",
    ).pack(fill="x")

    ttk.Button(actions, text="Chạy thống kê", command=run_report, style="Accent.TButton").grid(
        row=0, column=0, padx=(0, 8)
    )
    report_button.configure(command=open_report)
    report_button.grid(row=0, column=1, padx=(0, 8))
    csv_button.configure(command=open_csv)
    csv_button.grid(row=0, column=2, padx=(0, 8))
    ttk.Button(actions, text="Danh mục thuốc", command=open_catalog, style="Secondary.TButton").grid(
        row=0, column=3, padx=(0, 8)
    )
    ttk.Button(actions, text="Xóa file", command=clear_file, style="Secondary.TButton").grid(
        row=0, column=4, padx=(0, 8)
    )
    ttk.Button(actions, text="Đóng", command=root.destroy, style="Secondary.TButton").grid(row=0, column=6, sticky="e")

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
    if not raw_inputs and args.no_dialog and not args.invoice_folder and not args.invoice_zip:
        raw_inputs = [str(BASE_DIR)]

    try:
        result = create_report(
            raw_inputs=raw_inputs,
            invoice_folders=args.invoice_folder,
            invoice_zips=args.invoice_zip,
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
