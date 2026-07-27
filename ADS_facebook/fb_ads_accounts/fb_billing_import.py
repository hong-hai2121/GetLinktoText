"""
Nhập lịch sử thanh toán Facebook Ads từ CSV → Google Sheet.
GUI: chọn tab → chọn file CSV → kiểm tra cấu trúc → xem trước → import (upsert).
"""

import csv
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

try:
    import openpyxl
    _OPENPYXL_OK = True
except ImportError:
    _OPENPYXL_OK = False

import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    sys.exit("Cần tkinter (có sẵn trong Python chuẩn trên Windows).")

# ── Cấu hình ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
from config import SPREADSHEET_ID as SHEET_ID
SCOPES   = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ID_COL           = "ID giao dịch"
STATUS_COL       = "Trạng thái"
STATUS_ALLOW     = "Đã thanh toán"
DATE_COL         = "Ngày thanh toán"   # cột ngày để lọc theo tháng
KNOWN_MONEY_COLS = ["Số tiền", "Thuế", "Tổng tiền giao dịch", "Số tiền phân bổ"]
TEXT_ID_COLS     = [
    "ID giao dịch",
    "Tài khoản quảng cáo",
    "ID nhóm quảng cáo",
    "Số tham chiếu",
]

# ── Logic nghiệp vụ ────────────────────────────────────────────────────────────

def connect_spreadsheet():
    creds = Credentials.from_service_account_file(
        str(BASE_DIR / "service_account.json"), scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(SHEET_ID)


def parse_vnd(text: str):
    if not text or not isinstance(text, str):
        return None
    s = text.replace("₫", "").replace("'", "").strip()
    if re.search(r"\d\.\d{3}", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s.strip()) if s.strip() else None
    except ValueError:
        return None


def _money_cell(raw):
    """Làm sạch 1 ô tiền để ghi lên Sheet thành SỐ thật.

    Bỏ dấu nháy `'`, ký hiệu `₫` và dấu phân tách nghìn (qua parse_vnd).
    - Parse được  → trả int (số nguyên) / float → Sheet lưu dạng SỐ, cộng & SUM được.
    - Không parse được → trả chuỗi đã bỏ dấu `'` ở đầu (ít nhất không còn nháy thừa).
    """
    s = "" if raw is None else str(raw)
    val = parse_vnd(s)
    if val is None:
        return s.lstrip("'").strip()
    return int(val) if float(val).is_integer() else val


def read_csv(path: Path):
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, encoding=enc, newline="") as f:
                sample = f.read(8192)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',\t;|')
                delim = dialect.delimiter
            except csv.Error:
                delim = ','
            with open(path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f, delimiter=delim)
                headers = list(reader.fieldnames or [])
                rows    = list(reader)
            return headers, rows
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Không đọc được file: {path}")


def read_xls(path: Path):
    """Đọc file SpreadsheetML (.xls) do FB Billing Scraper extension xuất ra."""
    NS = 'urn:schemas-microsoft-com:office:spreadsheet'
    tree = ET.parse(path)
    root = tree.getroot()

    worksheet = root.find(f'{{{NS}}}Worksheet')
    if worksheet is None:
        raise RuntimeError("Không tìm thấy Worksheet trong file XLS")
    table = worksheet.find(f'{{{NS}}}Table')
    if table is None:
        raise RuntimeError("Không tìm thấy Table trong file XLS")

    all_rows = []
    for row_el in table.findall(f'{{{NS}}}Row'):
        row = []
        for cell_el in row_el.findall(f'{{{NS}}}Cell'):
            data_el = cell_el.find(f'{{{NS}}}Data')
            row.append(data_el.text or '' if data_el is not None else '')
        all_rows.append(row)

    if not all_rows:
        return [], []

    headers = all_rows[0]
    rows = [
        dict(zip(headers, r + [''] * max(0, len(headers) - len(r))))
        for r in all_rows[1:]
    ]
    return headers, rows


def _col_idx(ref: str) -> int:
    col = ''.join(c for c in ref if c.isalpha())
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _read_xlsx_manual(path: Path):
    """Parse ZIP local headers trực tiếp — bỏ qua central directory bị hỏng."""
    import struct as _struct, zlib as _zlib

    with open(path, 'rb') as f:
        data = f.read()

    files: dict[str, bytes] = {}
    pos = 0
    while pos < len(data) - 4:
        if data[pos:pos+4] == b'PK\x03\x04':
            _, _, compress, _, _, _, comp_sz, _, fname_len, extra_len = \
                _struct.unpack_from('<HHHHH IIIHH', data, pos + 4)
            fname = data[pos+30:pos+30+fname_len].decode('utf-8', errors='replace')
            ds    = pos + 30 + fname_len + extra_len
            raw   = data[ds:ds+comp_sz]
            files[fname] = _zlib.decompress(raw, -15) if compress == 8 else raw
            pos = ds + comp_sz
        elif data[pos:pos+4] == b'PK\x01\x02':
            break
        else:
            pos += 1

    sheet_xml = files.get('xl/worksheets/sheet1.xml')
    if not sheet_xml:
        raise RuntimeError("Không tìm thấy xl/worksheets/sheet1.xml trong file XLSX")

    NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

    shared: list[str] = []
    ss_xml = files.get('xl/sharedStrings.xml')
    if ss_xml:
        ss_root = ET.fromstring(ss_xml)
        for si in ss_root.findall(f'{{{NS}}}si'):
            t_el = si.find(f'{{{NS}}}t')
            shared.append(t_el.text or '' if t_el is not None else '')

    def cell_val(c: ET.Element) -> str:
        t = c.get('t', '')
        if t == 'inlineStr':
            is_t = c.find(f'{{{NS}}}is/{{{NS}}}t')
            return (is_t.text or '') if is_t is not None else ''
        v_el = c.find(f'{{{NS}}}v')
        if v_el is None:
            return ''
        if t == 's' and shared:
            idx = int(v_el.text or 0)
            return shared[idx] if idx < len(shared) else ''
        return v_el.text or ''

    root = ET.fromstring(sheet_xml)
    sheet_data = root.find(f'{{{NS}}}sheetData')
    if sheet_data is None:
        return [], []

    all_rows: list[list[str]] = []
    for row_el in sheet_data.findall(f'{{{NS}}}row'):
        cells = row_el.findall(f'{{{NS}}}c')
        if not cells:
            continue
        max_col = max(_col_idx(c.get('r', 'A')) for c in cells)
        row = [''] * (max_col + 1)
        for c in cells:
            row[_col_idx(c.get('r', 'A'))] = cell_val(c)
        all_rows.append(row)

    if not all_rows:
        return [], []

    headers = all_rows[0]
    rows = [
        dict(zip(headers, r + [''] * max(0, len(headers) - len(r))))
        for r in all_rows[1:]
    ]
    return headers, rows


def read_xlsx(path: Path):
    """Đọc .xlsx: thử openpyxl trước, fallback sang manual ZIP parser nếu thất bại."""
    if _OPENPYXL_OK:
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header_row = next(rows_iter)
            except StopIteration:
                wb.close()
                return [], []
            headers = [str(h) if h is not None else '' for h in header_row]
            rows = [
                {headers[i]: (str(v) if v is not None else '') for i, v in enumerate(raw)}
                for raw in rows_iter
            ]
            wb.close()
            return headers, rows
        except zipfile.BadZipFile:
            pass
    return _read_xlsx_manual(path)


def read_file(path: Path):
    ext = path.suffix.lower()
    if ext == '.xls':
        return read_xls(path)
    if ext == '.xlsx':
        return read_xlsx(path)
    return read_csv(path)


def _normalize(name: str) -> str:
    """Chuẩn hóa tên cột để so sánh mềm: bỏ ký tự đặc biệt, lowercase."""
    return re.sub(r"[^\w]", "", name, flags=re.UNICODE).lower()


def filter_by_status(csv_headers: list, csv_rows: list) -> tuple:
    """Chỉ giữ dòng có Trạng thái == STATUS_ALLOW; nếu cột vắng thì giữ tất cả."""
    if STATUS_COL not in csv_headers:
        return csv_rows, 0
    kept    = [r for r in csv_rows if STATUS_ALLOW in str(r.get(STATUS_COL, ""))]
    skipped = len(csv_rows) - len(kept)
    return kept, skipped


# Ánh xạ tên tháng tiếng Anh → số (phòng khi FB hiển thị locale tiếng Anh)
_EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _extract_month_key(text: str):
    """Bóc (năm, tháng) từ chuỗi ngày của FB → dùng để so sánh tháng.

    Hỗ trợ nhiều định dạng thực tế:
      '1 tháng 6, 2026' · '1 thg 6 2026' · '2026-06-01' · '01/06/2026' · 'Jun 1, 2026'
    Nếu không thấy năm thì trả (None, tháng) — vẫn so được theo tháng.
    Trả None nếu không đọc được tháng.
    """
    if not text:
        return None
    s = str(text).strip()

    # ISO: 2026-06-01
    m = re.search(r"\b(\d{4})[-/](\d{1,2})[-/]\d{1,2}\b", s)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # DD/MM/YYYY: 01/06/2026
    m = re.search(r"\b(\d{1,2})[/](\d{1,2})[/](\d{4})\b", s)
    if m:
        return (int(m.group(3)), int(m.group(2)))

    # Tiếng Việt: 'tháng 6' / 'thg 6' (+ năm 20xx nếu có)
    mv = re.search(r"th(?:án)?g\.?\s*(\d{1,2})", s, re.IGNORECASE)
    if mv:
        my = re.search(r"\b(20\d{2})\b", s)
        return (int(my.group(1)) if my else None, int(mv.group(1)))

    # Tên tháng tiếng Anh: 'Jun 1, 2026' / 'June 1 2026'
    me = re.search(r"\b([A-Za-z]{3,})\b", s)
    if me and me.group(1)[:3].lower() in _EN_MONTHS:
        my = re.search(r"\b(20\d{2})\b", s)
        return (int(my.group(1)) if my else None, _EN_MONTHS[me.group(1)[:3].lower()])

    return None


def _month_label(key) -> str:
    y, m = key
    return f"tháng {m}/{y}" if y else f"tháng {m}"


def _find_col(headers: list, name: str):
    """Tìm cột theo tên chuẩn hóa (bỏ ký tự đặc biệt) — trả tên cột thực tế hoặc None."""
    target = _normalize(name)
    return next((h for h in headers if _normalize(h) == target), None)


def filter_by_month(csv_headers: list, csv_rows: list, target=None) -> tuple:
    """Chỉ giữ dòng thuộc THÁNG mục tiêu; loại dòng thuộc tháng khác.

    - target=None → tự lấy tháng chiếm ĐA SỐ trong file làm mục tiêu (đúng cho mọi tháng).
    - Dòng không đọc được ngày → GIỮ (không dám loại nhầm), đếm vào `unparsed`.
    Trả (kept, dropped, target, unparsed) với dropped = list[(row, key)].
    """
    col = _find_col(csv_headers, DATE_COL)
    if not col:
        return csv_rows, [], None, 0

    keys   = [_extract_month_key(r.get(col, "")) for r in csv_rows]
    parsed = [k for k in keys if k]
    if not parsed:
        return csv_rows, [], None, len(csv_rows)

    if target is None:
        target = Counter(parsed).most_common(1)[0][0]

    kept, dropped, unparsed = [], [], 0
    for row, key in zip(csv_rows, keys):
        if key is None:
            kept.append(row)
            unparsed += 1
        elif key == target:
            kept.append(row)
        else:
            dropped.append((row, key))
    return kept, dropped, target, unparsed


def analyze_structure(csv_headers: list, sheet_headers: list) -> dict:
    """So sánh cột CSV với cột sheet, trả về dict phân tích."""
    # Lọc bỏ: tên rỗng + cột numeric tự sinh
    def keep(h: str) -> bool:
        return bool(h.strip()) and not h.endswith(" (numeric)")

    clean_sheet = [h for h in sheet_headers if keep(h)]
    clean_csv   = [h for h in csv_headers   if keep(h)]

    csv_norm   = {_normalize(h): h for h in clean_csv}
    sheet_norm = {_normalize(h): h for h in clean_sheet}

    # Khớp theo tên chuẩn hóa (bỏ qua ký tự đặc biệt như ₫, dấu nháy...)
    matched  = [h for h in clean_csv   if _normalize(h) in sheet_norm]
    new_cols = [h for h in clean_csv   if _normalize(h) not in sheet_norm]
    missing  = [h for h in clean_sheet if _normalize(h) not in csv_norm]

    return {
        "matched":     matched,
        "new_cols":    new_cols,
        "missing":     missing,
        "has_id":      ID_COL in set(csv_headers),
        "sheet_empty": len(clean_sheet) == 0,
    }


def _format_text_columns(worksheet, headers: list):
    requests = []
    for col_name in TEXT_ID_COLS:
        if col_name not in headers:
            continue
        ci = headers.index(col_name)
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId":          worksheet.id,
                    "startColumnIndex": ci,
                    "endColumnIndex":   ci + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "TEXT"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        })
    if requests:
        worksheet.spreadsheet.batch_update({"requests": requests})


def upsert(worksheet, csv_headers: list, csv_rows: list, replace: bool = False) -> dict:
    # Lookup chuẩn hóa: "Số tiền" ≈ "Số tiền (₫)"
    csv_norm_map = {_normalize(h): h for h in csv_headers}

    if replace:
        # Thay thế toàn bộ: bỏ qua dữ liệu cũ, header + dòng lấy hết từ file
        sheet_hdr  = list(csv_headers)
        sheet_body = []
    else:
        existing = worksheet.get_all_values()
        if existing:
            sheet_hdr  = existing[0]
            sheet_body = [list(r) for r in existing[1:]]
        else:
            sheet_hdr  = []
            sheet_body = []

        if not sheet_hdr:
            sheet_hdr  = list(csv_headers)
            sheet_body = []
        else:
            # Thêm cột mới từ CSV nếu chưa có trong sheet
            sheet_norm = {_normalize(h) for h in sheet_hdr}
            for h in csv_headers:
                if _normalize(h) not in sheet_norm:
                    sheet_hdr.append(h)
                    sheet_norm.add(_normalize(h))
            ncols = len(sheet_hdr)
            for r in sheet_body:
                while len(r) < ncols:
                    r.append("")

    id_idx = sheet_hdr.index(ID_COL) if ID_COL in sheet_hdr else None

    def _get_csv_val(row: dict, col_name: str) -> str:
        if col_name in row:
            return str(row[col_name])
        norm = csv_norm_map.get(_normalize(col_name))
        return str(row[norm]) if norm and norm in row else ""

    # File CHI TIẾT có NHIỀU dòng cùng 1 'ID giao dịch' (mỗi chiến dịch/nhóm QC
    # một dòng). Nếu dedup theo từng DÒNG như file danh sách thì các dòng cùng
    # giao dịch sẽ ĐÈ lên nhau → mất hết chỉ còn 1 dòng. Nhận diện file chi tiết
    # qua ID trùng lặp hoặc cột 'Tên chiến dịch' rồi dedup ở CẤP GIAO DỊCH.
    incoming_ids = ([str(r.get(ID_COL, "")).strip() for r in csv_rows]
                    if ID_COL in csv_headers else [])
    incoming_ids = [i for i in incoming_ids if i]
    is_detail = (len(incoming_ids) != len(set(incoming_ids))
                 or _find_col(csv_headers, "Tên chiến dịch") is not None)

    if id_idx is not None and is_detail:
        # Dedup CẤP GIAO DỊCH: xoá mọi dòng cũ có ID trùng lô mới, rồi thêm CẢ lô
        # mới (giữ đủ nhiều dòng/1 giao dịch, idempotent khi import lại).
        id_set = set(incoming_ids)
        kept, updated = [], 0
        for row in sheet_body:
            rid = row[id_idx].strip() if id_idx < len(row) else ""
            if rid and rid in id_set:
                updated += 1
                continue
            kept.append(row)
        sheet_body = kept
        added = 0
        for csv_row in csv_rows:
            sheet_body.append([_get_csv_val(csv_row, h) for h in sheet_hdr])
            added += 1
    else:
        # Dedup CẤP DÒNG (file danh sách: 1 dòng/1 giao dịch) — hành vi như cũ.
        existing_ids: dict = {}
        if id_idx is not None:
            for i, row in enumerate(sheet_body):
                rid = row[id_idx].strip() if id_idx < len(row) else ""
                if rid:
                    existing_ids[rid] = i

        updated = added = 0
        for csv_row in csv_rows:
            row_vals = [_get_csv_val(csv_row, h) for h in sheet_hdr]

            csv_id = str(csv_row.get(ID_COL, "")).strip() if ID_COL in csv_headers else ""

            if csv_id and csv_id in existing_ids:
                sheet_body[existing_ids[csv_id]] = row_vals
                updated += 1
            else:
                if csv_id:
                    existing_ids[csv_id] = len(sheet_body)
                sheet_body.append(row_vals)
                added += 1

    # Làm sạch cột tiền: bỏ dấu ' / ₫, đổi text → SỐ để cộng/SUM được trên Sheet.
    # Áp cho MỌI dòng (cũ + mới) để cả cột đồng nhất kiểu số.
    money_norm = {_normalize(c) for c in KNOWN_MONEY_COLS}
    money_idx  = [i for i, h in enumerate(sheet_hdr) if _normalize(h) in money_norm]
    if money_idx:
        for row in sheet_body:
            for i in money_idx:
                if i < len(row):
                    row[i] = _money_cell(row[i])

    worksheet.clear()
    all_data = [sheet_hdr] + sheet_body
    BATCH = 1000
    for start in range(0, len(all_data), BATCH):
        worksheet.update(
            values=all_data[start:start + BATCH],
            range_name=f"A{start + 1}",
            value_input_option="RAW",
        )

    _format_text_columns(worksheet, sheet_hdr)
    return {"tab": worksheet.title, "total": len(csv_rows),
            "updated": updated, "added": added}


# ── Hộp thoại xác nhận ────────────────────────────────────────────────────────

# ── Giao diện chính (multi-file) ───────────────────────────────────────────────

class App(tk.Tk):
    # Nhãn trạng thái hiển thị trong bảng queue
    _STATUS_LABEL = {
        "loading":   "Đang đọc...",
        "checking":  "Đang so cột...",
        "ready":     "✓ Sẵn sàng",
        "mismatch":  "⚠ Cột khác",
        "no_tab":    "⚠ Chưa có tab",
        "new_tab":   "✨ Tab mới tạo",
        "importing": "Đang import...",
        "done":      "✓ Hoàn tất",
        "error":     "✗ Lỗi",
    }

    # ── Bảng màu (Soft Light / Eye Care đồng bộ với hub.py) ────────────────
    BG         = "#eef2f6"
    CARD       = "#f8fafc"
    BORDER     = "#cbd5e1"
    ACCENT     = "#3b82f6"
    ACCENT_HV  = "#2563eb"
    ACCENT_DIS = "#93c5fd"
    TEXT       = "#334155"
    MUTED      = "#64748b"
    GREEN      = "#10b981"
    YELLOW     = "#f59e0b"
    RED        = "#ef4444"
    CODE_BG    = "#f1f5f9"

    def __init__(self):
        super().__init__()
        self.title("FB Billing Import → Google Sheet")
        
        from ui_kit import size_window
        size_window(self, min_w=1040, min_h=600)
        self.configure(bg=self.BG)

        self._spreadsheet = None
        self._worksheets: list = []
        # queue item: {path, ws, headers, rows, sheet_headers, analysis, status, error, iid}
        self._queue: list[dict] = []
        # cache header sheet theo tên tab để khỏi đọc lại nhiều lần
        self._sheet_hdr_cache: dict = {}

        self._apply_styles()
        self._build_ui()
        self._connect_async()

    # ── Style ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure("TFrame",      background=self.BG)
        s.configure("Card.TFrame", background=self.CARD)
        s.configure("TLabel",      background=self.BG,
                    font=("Segoe UI", 10), foreground=self.TEXT)

        # Nút thường
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(15, 8),
                    background=self.BORDER, foreground=self.TEXT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("TButton",
              background=[("active", "#cbd5e1"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)],
              bordercolor=[("active", "#94a3b8")])

        # Nút phụ nổi bật
        s.configure("Soft.TButton", font=("Segoe UI", 9, "bold"), padding=(15, 8),
                    background="#e0f2fe", foreground=self.ACCENT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("Soft.TButton",
              background=[("active", "#bae6fd"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)],
              bordercolor=[("active", "#7dd3fc")])

        # Nút chính
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(24, 10), background=self.ACCENT,
                    foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#ffffff")])

        # Treeview
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=29,
                    background=self.CARD, fieldbackground=self.CARD,
                    foreground=self.TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background=self.BORDER, foreground=self.MUTED,
                    relief="flat", padding=(8, 7))
        s.map("Treeview",
              background=[("selected", self.ACCENT)],
              foreground=[("selected", "#ffffff")])
        s.map("Treeview.Heading", background=[("active", "#cbd5e1")])

        # Scrollbar
        for o in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            s.configure(o, background=self.BORDER, troughcolor=self.BG,
                        bordercolor=self.BG, arrowcolor=self.MUTED,
                        relief="flat", borderwidth=0)
            s.map(o, background=[("active", "#cbd5e1")])

        # Progressbar
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor=self.BORDER, borderwidth=0, thickness=8)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=16, pady=14)

        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 14))
        tk.Label(hdr, text="FB Billing Import", bg=self.BG,
                 font=("Segoe UI Semibold", 16), fg=self.TEXT).pack(side="left")
        tk.Label(hdr, text="  →  Google Sheet", bg=self.BG,
                 font=("Segoe UI", 11), fg=self.MUTED).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối Google Sheet...",
                                    bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        # ── PanedWindow: kéo to/nhỏ panel tab ──────────────────────────────
        paned = tk.PanedWindow(outer, orient="horizontal", bg=self.BG,
                               sashwidth=10, sashrelief="flat", bd=0,
                               sashpad=0, opaqueresize=True)
        paned.pack(fill="both", expand=True)

        # ── Trái: danh sách tab ─────────────────────────────────────────
        left = self._card_frame(paned, "1", "Tab Google Sheet")
        tk.Label(left.body, text="Chọn file ở bảng phải, rồi click tab để gán",
                 bg=self.CARD, font=("Segoe UI", 8), fg=self.MUTED,
                 anchor="w", justify="left").pack(fill="x", pady=(0, 6))

        tab_wrap = tk.Frame(left.body, bg=self.BORDER, bd=0,
                            highlightthickness=1, highlightbackground=self.BORDER)
        tab_wrap.pack(fill="both", expand=True)
        self._tab_list = tk.Listbox(
            tab_wrap, selectmode="single", font=("Segoe UI", 10),
            activestyle="none", selectbackground=self.ACCENT, selectforeground="#ffffff",
            relief="flat", bd=0, highlightthickness=0,
            bg=self.CARD, fg=self.TEXT,
        )
        tab_sb = ttk.Scrollbar(tab_wrap, orient="vertical", command=self._tab_list.yview)
        self._tab_list.configure(yscrollcommand=tab_sb.set)
        tab_sb.pack(side="right", fill="y")
        self._tab_list.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self._tab_list.bind("<<ListboxSelect>>", self._on_tab_click)

        paned.add(left, width=270, minsize=200, stretch="never", padx=0, pady=0)

        # ── Phải: queue file ────────────────────────────────────────────
        right = self._card_frame(paned, "2", "Danh sách file cần import")

        # Nút thao tác
        btn_row = tk.Frame(right.body, bg=self.CARD)
        btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="＋  Thêm file...", style="Soft.TButton",
                   command=self._browse_files).pack(side="left")
        ttk.Button(btn_row, text="Xóa đã chọn",
                   command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Xóa tất cả",
                   command=self._clear_queue).pack(side="left")

        # Bảng queue
        wrap = tk.Frame(right.body, bg=self.BORDER,
                        highlightthickness=1, highlightbackground=self.BORDER)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        cols = ("file", "tab", "rows", "status")
        self._q_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                    selectmode="extended")
        self._q_tree.heading("file",   text="File",       anchor="w")
        self._q_tree.heading("tab",    text="Tab đích",    anchor="w")
        self._q_tree.heading("rows",   text="Dòng",        anchor="center")
        self._q_tree.heading("status", text="Trạng thái",  anchor="w")
        self._q_tree.column("file",   width=340, stretch=True,  minwidth=150)
        self._q_tree.column("tab",    width=200, stretch=False, minwidth=100)
        self._q_tree.column("rows",   width=60,  stretch=False, anchor="center")
        self._q_tree.column("status", width=140, stretch=False)
        qvb = ttk.Scrollbar(wrap, orient="vertical",   command=self._q_tree.yview)
        qhb = ttk.Scrollbar(wrap, orient="horizontal", command=self._q_tree.xview)
        self._q_tree.configure(yscrollcommand=qvb.set, xscrollcommand=qhb.set)
        self._q_tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        qvb.grid(row=0, column=1, sticky="ns")
        qhb.grid(row=1, column=0, sticky="ew")
        # Sọc xen kẽ + màu theo trạng thái
        self._q_tree.tag_configure("odd",       background=self.BG)
        self._q_tree.tag_configure("loading",   foreground=self.MUTED)
        self._q_tree.tag_configure("checking",  foreground=self.MUTED)
        self._q_tree.tag_configure("ready",     foreground=self.GREEN)
        self._q_tree.tag_configure("mismatch",  foreground=self.YELLOW)
        self._q_tree.tag_configure("no_tab",    foreground=self.YELLOW)
        self._q_tree.tag_configure("new_tab",   foreground=self.ACCENT)
        self._q_tree.tag_configure("error",     foreground=self.RED)
        self._q_tree.tag_configure("done",      foreground=self.GREEN)
        self._q_tree.tag_configure("importing", foreground=self.TEXT)
        self._q_tree.bind("<<TreeviewSelect>>", self._on_queue_select)

        # Info box (chi tiết file đang chọn)
        self._info_box = tk.Text(
            right.body, height=5, font=("Consolas", 9),
            state="disabled", bg=self.CODE_BG, fg=self.TEXT, relief="flat", bd=0,
            padx=10, pady=8, insertbackground=self.TEXT,
            highlightthickness=1, highlightcolor=self.BORDER, highlightbackground=self.BORDER,
        )
        self._info_box.pack(fill="x", pady=(8, 0))
        self._info_box.tag_config("ok",   foreground=self.GREEN)
        self._info_box.tag_config("warn", foreground=self.YELLOW)
        self._info_box.tag_config("err",  foreground=self.RED)
        self._info_box.tag_config("info", foreground=self.ACCENT)
        self._info_box.tag_config("dim",  foreground=self.MUTED)

        paned.add(right, minsize=440, stretch="always", padx=0, pady=0)

        # ── Thanh dưới ─────────────────────────────────────────────────────
        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(14, 0))
        self._import_btn = ttk.Button(
            bot, text="Import tất cả",
            style="Accent.TButton", command=self._run_import_all, state="disabled",
        )
        self._import_btn.pack(side="left")

        # Nút chạy lại: nhớ các file lỗi lần trước, import lại chỉ những file đó
        self._retry_btn = ttk.Button(
            bot, text="↻ Chạy lại file lỗi",
            command=self._run_retry_failed, state="disabled",
        )
        self._retry_btn.pack(side="left", padx=(10, 0))

        # Checkbox: thay thế toàn bộ dữ liệu cũ trong tab trước khi import
        self._replace_var = tk.BooleanVar(value=False)
        self._replace_chk = tk.Checkbutton(
            bot, text="Thay thế dữ liệu cũ", variable=self._replace_var,
            bg=self.BG, fg=self.TEXT, font=("Segoe UI", 9),
            activebackground=self.BG, activeforeground=self.TEXT,
            selectcolor=self.BORDER, relief="flat", bd=0,
            highlightthickness=0, cursor="hand2", takefocus=0,
        )
        self._replace_chk.pack(side="left", padx=(14, 0))

        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=170)
        self._progress.pack(side="left", padx=14)
        self._result_lbl = tk.Label(bot, text="", bg=self.BG,
                                    font=("Segoe UI", 9), fg=self.MUTED)
        self._result_lbl.pack(side="left")

    def _card_frame(self, parent, num: str, title: str) -> tk.Frame:
        """Thẻ trắng có viền + tiêu đề kèm badge số. Trả về frame có thuộc tính .body."""
        card = tk.Frame(parent, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        head = tk.Frame(card, bg=self.CARD)
        head.pack(fill="x", padx=14, pady=(13, 9))
        tk.Label(head, text=f" {num} ", bg=self.ACCENT, fg="#FFFFFF",
                 font=("Segoe UI", 9, "bold"), padx=4, pady=1).pack(side="left")
        tk.Label(head, text=title, bg=self.CARD, fg=self.TEXT,
                 font=("Segoe UI Semibold", 11)).pack(side="left", padx=(9, 0))
        tk.Frame(card, bg=self.BORDER, height=1).pack(fill="x")
        body = tk.Frame(card, bg=self.CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(11, 13))
        card.body = body
        return card

    # ── Kết nối Google Sheet ──────────────────────────────────────────────────

    def _connect_async(self):
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            ss  = connect_spreadsheet()
            wss = ss.worksheets()
            self._spreadsheet = ss
            self._worksheets  = wss
            self.after(0, self._load_tabs)
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi kết nối: {e}", error=True))

    def _load_tabs(self):
        self._tab_list.delete(0, "end")
        for ws in self._worksheets:
            self._tab_list.insert("end", ws.title)
        self._set_status(
            f"Đã kết nối: {self._spreadsheet.title}  ({len(self._worksheets)} tab)"
        )

    # ── Tab click → gán cho file đang chọn ───────────────────────────────────

    def _on_tab_click(self, *_):
        sel_tabs = self._tab_list.curselection()
        sel_iids = self._q_tree.selection()
        if not sel_tabs or not sel_iids:
            return
        ws = self._worksheets[sel_tabs[0]]
        for iid in sel_iids:
            item = self._item_by_iid(iid)
            if item and item["status"] not in ("importing", "done"):
                item["ws"]            = ws
                item["analysis"]      = None
                item["sheet_headers"] = None
                if item["headers"]:
                    self._ensure_analysis(item)   # đã đọc xong file → so cột ngay
                else:
                    item["status"] = "loading"    # file còn đang đọc
                    self._refresh_tree_row(item)
        self._refresh_import_btn()

    # ── Chọn file (multi) ─────────────────────────────────────────────────────

    @staticmethod
    def _tab_candidates_from_stem(stem: str) -> list:
        """Tên tab = phần trước hậu tố '_fb_billing...'. Giữ nguyên phần '(ID)'.

        KHÔNG cắt ngắn về tên trước dấu '(' — phần '(ID tài khoản)' là một phần
        của tên tab. Cắt ngắn dễ trỏ nhầm sang một tab khác có cột khác.

        File CHI TIẾT ('…_fb_billing_CHI_TIET_…') có bộ cột KHÁC HẲN file danh
        sách (19 cột vs 7 cột), nên map sang tab RIÊNG '<tên> Chi tiết' — trùng
        tên sheet 'Chi tiết' mà extension tạo. Không thấy tab đó → tạo tab mới,
        KHÔNG so cột nhầm với tab danh sách '<tên>'.
        Ví dụ:
          'Tk2 A Hải +7 (796502949963935)_fb_billing_DANH_SACH_2026-06-01'
            → 'Tk2 A Hải +7 (796502949963935)'
          'Tk2 A Hải +7 (796502949963935)_fb_billing_CHI_TIET_2026-06-01'
            → 'Tk2 A Hải +7 (796502949963935) Chi tiết'
        """
        m = re.match(r'^(.+?)_fb_billing', stem, re.IGNORECASE)
        name = m.group(1).strip() if m else stem.strip()
        if not name:
            return []
        if re.search(r'_fb_billing_chi[_ ]?tiet', stem, re.IGNORECASE):
            return [f"{name} Chi tiết"]
        return [name]

    @staticmethod
    def _norm_for_match(s: str) -> str:
        """Chuẩn hóa để so sánh: lowercase + thay '/' → '_' (Windows đổi / thành _ trong tên file)."""
        return s.strip().lower().replace('/', '_')

    def _find_ws(self, candidates: list):
        ws_lower = [(ws, self._norm_for_match(ws.title)) for ws in self._worksheets]
        for name in candidates:
            norm = self._norm_for_match(name)
            for ws, title in ws_lower:
                if title == norm:
                    return ws
        return None

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            initialdir=str(Path.home() / "Downloads"),
            title="Chọn file CSV / XLS / XLSX",
            filetypes=[
                ("CSV / XLS / XLSX files", "*.csv *.xls *.xlsx"),
                ("CSV files", "*.csv"),
                ("Excel files", "*.xls *.xlsx"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return
        for path_str in paths:
            p = Path(path_str)
            if any(i["path"] == p for i in self._queue):
                continue  # bỏ qua file trùng
            candidates = self._tab_candidates_from_stem(p.stem)
            ws         = self._find_ws(candidates)
            pending    = candidates[0] if not ws and candidates else ""
            item = {
                "path": p, "ws": ws,
                "pending_tab_name": pending, "is_new_tab": False,
                "headers": [], "rows": [],
                "sheet_headers": None, "analysis": None,
                "status": "loading", "error": "", "iid": "",
            }
            iid = self._q_tree.insert(
                "", "end",
                values=(p.name, ws.title if ws else "—", "—", "Đang đọc..."),
                tags=("loading",),
            )
            item["iid"] = iid
            self._queue.append(item)
            threading.Thread(target=self._load_file_worker,
                             args=(item,), daemon=True).start()

    def _load_file_worker(self, item: dict):
        try:
            headers, rows   = read_file(item["path"])
            item["headers"] = headers
            item["rows"]    = rows
            if item["ws"]:
                item["status"] = "checking"
            elif item.get("pending_tab_name"):
                ncols = max(len(headers), 1)            # số cột = số cột file import
                nrows = max(len(rows) + 1, 100)         # +1 dòng header
                new_ws = self._spreadsheet.add_worksheet(
                    title=item["pending_tab_name"], rows=nrows, cols=ncols
                )
                item["ws"]         = new_ws
                item["is_new_tab"] = True
                item["status"]     = "new_tab"
            else:
                item["status"] = "no_tab"
        except Exception as e:
            item["status"] = "error"
            item["error"]  = str(e)
        self.after(0, lambda i=item: self._on_file_loaded(i))

    def _on_file_loaded(self, item: dict):
        if item.get("is_new_tab") and item["ws"]:
            self._worksheets.append(item["ws"])
            self._tab_list.insert("end", item["ws"].title)
        self._refresh_tree_row(item)
        if item["status"] in ("checking", "new_tab") and item["ws"]:
            self._ensure_analysis(item)   # đã có tab → so cột với sheet
        self._refresh_import_btn()

    # ── So sánh cột file ↔ sheet ──────────────────────────────────────────────

    def _ensure_analysis(self, item: dict):
        """Đảm bảo item có analysis (so cột với sheet). Đọc header sheet nếu cần."""
        if not item["headers"] or not item["ws"]:
            return
        title = item["ws"].title
        if title in self._sheet_hdr_cache:
            item["sheet_headers"] = self._sheet_hdr_cache[title]
            self._compute_analysis(item)
        else:
            item["status"] = "checking"
            self._refresh_tree_row(item)
            ws = item["ws"]
            threading.Thread(target=self._load_sheet_hdr_worker,
                             args=(item, ws), daemon=True).start()

    def _load_sheet_hdr_worker(self, item: dict, ws):
        try:
            hdr = ws.row_values(1)
            self._sheet_hdr_cache[ws.title] = hdr
            self.after(0, lambda: self._after_sheet_hdr(item, ws, hdr))
        except Exception as e:
            self.after(0, lambda e=e: self._sheet_hdr_error(item, str(e)))

    def _after_sheet_hdr(self, item: dict, ws, hdr: list):
        # Nếu trong lúc đọc, item đã đổi tab thì bỏ qua kết quả cũ
        if item["ws"] is not ws:
            return
        item["sheet_headers"] = hdr
        self._compute_analysis(item)

    def _sheet_hdr_error(self, item: dict, msg: str):
        item["status"] = "error"
        item["error"]  = f"Đọc cột sheet lỗi: {msg}"
        self._refresh_tree_row(item)
        self._refresh_import_btn()
        self._refresh_selected_info(item)

    def _compute_analysis(self, item: dict):
        a = analyze_structure(item["headers"], item["sheet_headers"] or [])
        item["analysis"] = a
        if item.get("is_new_tab"):
            item["status"] = "new_tab"   # giữ trạng thái tab mới tạo
        elif a["sheet_empty"] or (not a["new_cols"] and not a["missing"]):
            item["status"] = "ready"
        else:
            item["status"] = "mismatch"
        self._refresh_tree_row(item)
        self._refresh_import_btn()
        self._refresh_selected_info(item)

    def _refresh_selected_info(self, item: dict):
        """Cập nhật info box nếu item này đang được chọn."""
        sel = self._q_tree.selection()
        if sel and sel[0] == item["iid"]:
            self._show_item_info(item)

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def _item_by_iid(self, iid: str) -> dict | None:
        return next((i for i in self._queue if i["iid"] == iid), None)

    def _refresh_tree_row(self, item: dict):
        tab_text  = item["ws"].title if item["ws"] else "—"
        rows_text = str(len(item["rows"])) if item["rows"] else "—"
        status    = self._STATUS_LABEL.get(item["status"], item["status"])
        idx       = self._q_tree.index(item["iid"])
        tags      = (item["status"],) if idx % 2 == 0 else ("odd", item["status"])
        self._q_tree.item(item["iid"],
                          values=(item["path"].name, tab_text, rows_text, status),
                          tags=tags)

    def _refresh_import_btn(self):
        ok = any(i["ws"] and i["status"] in ("ready", "mismatch", "new_tab")
                 for i in self._queue)
        self._import_btn.configure(state="normal" if ok else "disabled")
        # Bật nút "Chạy lại" khi có file đã đọc xong + đã gán tab nhưng import lỗi
        has_failed = any(i["status"] == "error" and i["ws"] and i["headers"]
                         for i in self._queue)
        self._retry_btn.configure(state="normal" if has_failed else "disabled")

    def _on_queue_select(self, *_):
        sel = self._q_tree.selection()
        if not sel:
            return
        item = self._item_by_iid(sel[0])
        if item:
            self._show_item_info(item)

    def _show_item_info(self, item: dict):
        lines: list[tuple[str, str]] = [
            ("dim", f"File : {item['path'].name}\n"),
        ]
        if item["ws"]:
            if item.get("is_new_tab"):
                lines.append(("info", f"Tab  : {item['ws'].title}  ✨ (tab mới tạo tự động)\n"))
            else:
                lines.append(("ok",  f"Tab  : {item['ws'].title}\n"))
        else:
            lines.append(("warn", "Tab  : Chưa gán — click tab bên trái để gán\n"))
        if item["status"] == "error":
            lines.append(("err", f"Lỗi  : {item['error']}\n"))
        elif item["headers"]:
            filtered, skipped = filter_by_status(item["headers"], item["rows"])
            lines.append(("dim", f"Dòng : {len(item['rows'])} tổng  →  import {len(filtered)}"))
            if skipped:
                lines.append(("warn", f"  (bỏ {skipped} dòng không phải '{STATUS_ALLOW}')"))
            lines.append(("dim", "\n"))
            if ID_COL in item["headers"]:
                lines.append(("ok",  f"✓  Cột '{ID_COL}' — sẽ dedup theo ID\n"))
            else:
                lines.append(("err", f"✗  Cột '{ID_COL}' KHÔNG CÓ — sẽ append tất cả\n"))
            # Lọc theo tháng: cảnh báo dòng thuộc tháng khác (sẽ bị loại khi import)
            _, dropped, target, _un = filter_by_month(item["headers"], filtered)
            if target:
                lines.append(("dim", f"Tháng : {_month_label(target)} (tự nhận theo đa số)\n"))
            if dropped:
                cnt = Counter(_month_label(k) for _, k in dropped)
                detail = ", ".join(f"{lb} ({c})" for lb, c in cnt.items())
                lines.append(("warn",
                    f"⚠  {len(dropped)} dòng thuộc THÁNG KHÁC sẽ bị loại: {detail}\n"))
            # Kết quả so cột với sheet
            a = item["analysis"]
            if item["status"] == "checking":
                lines.append(("dim", "⋯  Đang so cột với sheet...\n"))
            elif a is not None and not a["sheet_empty"]:
                if a["new_cols"]:
                    lines.append(("warn",
                        f"⚠  {len(a['new_cols'])} cột CÓ ở file nhưng KHÔNG ở sheet "
                        f"(sẽ thêm): {', '.join(a['new_cols'])}\n"))
                if a["missing"]:
                    lines.append(("warn",
                        f"⚠  {len(a['missing'])} cột CÓ ở sheet nhưng KHÔNG ở file "
                        f"(để trống): {', '.join(a['missing'])}\n"))
                if not a["new_cols"] and not a["missing"]:
                    lines.append(("ok", "✓  Cột file khớp hoàn toàn với sheet\n"))
            elif a is not None and a["sheet_empty"]:
                lines.append(("info", "ℹ  Sheet trống — sẽ tạo cột từ file\n"))
        self._write_info_tagged(lines)

    def _remove_selected(self):
        for iid in list(self._q_tree.selection()):
            item = self._item_by_iid(iid)
            if item and item["status"] != "importing":
                self._queue.remove(item)
                self._q_tree.delete(iid)
        self._refresh_import_btn()

    def _clear_queue(self):
        for item in [i for i in self._queue if i["status"] != "importing"]:
            self._queue.remove(item)
            self._q_tree.delete(item["iid"])
        self._refresh_import_btn()

    # ── Import tất cả ────────────────────────────────────────────────────────

    def _run_import_all(self):
        importable = [i for i in self._queue
                      if i["ws"] and i["status"] in ("ready", "mismatch", "new_tab")]
        mismatched = [i for i in importable if i["status"] == "mismatch"]
        no_tab     = [i for i in self._queue if i["status"] == "no_tab"]
        if not importable:
            return

        replace = self._replace_var.get()

        # Có file lệch cột → cảnh báo chi tiết, đề phòng gán nhầm sheet
        if mismatched:
            if not self._confirm_mismatch(importable, mismatched, no_tab, replace):
                return
        else:
            lines = [f"Sẽ import {len(importable)} file vào {len(importable)} tab."]
            if replace:
                lines.append("⚠ Chế độ THAY THẾ: xóa toàn bộ dữ liệu cũ trong tab "
                             "trước khi import.")
            if no_tab:
                lines.append(f"Bỏ qua {len(no_tab)} file chưa gán tab.")
            if not messagebox.askyesno("Xác nhận Import", "\n".join(lines)):
                return

        self._import_btn.configure(state="disabled")
        self._retry_btn.configure(state="disabled")
        self._progress.start(12)
        self._result_lbl.configure(text="Đang import...")
        threading.Thread(target=self._import_all_worker,
                         args=(importable, replace), daemon=True).start()

    def _run_retry_failed(self):
        """Chạy lại chỉ những file đã import lỗi lần trước (vẫn còn trong hàng đợi)."""
        failed = [i for i in self._queue
                  if i["status"] == "error" and i["ws"] and i["headers"]]
        if not failed:
            return

        replace = self._replace_var.get()
        lines = [f"Chạy lại {len(failed)} file bị lỗi lần trước:"]
        lines += [f"  • {i['path'].name}" for i in failed[:15]]
        if len(failed) > 15:
            lines.append(f"  … và {len(failed) - 15} file nữa")
        if replace:
            lines.append("\n⚠ Chế độ THAY THẾ đang bật: dữ liệu cũ trong tab sẽ bị xóa.")
        if not messagebox.askyesno("Chạy lại file lỗi", "\n".join(lines)):
            return

        self._import_btn.configure(state="disabled")
        self._retry_btn.configure(state="disabled")
        self._progress.start(12)
        self._result_lbl.configure(text=f"Đang chạy lại {len(failed)} file lỗi...")
        threading.Thread(target=self._import_all_worker,
                         args=(failed, replace), daemon=True).start()

    def _confirm_mismatch(self, importable: list, mismatched: list, no_tab: list,
                          replace: bool = False) -> bool:
        """Hộp thoại cảnh báo: liệt kê file có cột khác sheet. Trả về True nếu vẫn import."""
        dlg = tk.Toplevel(self)
        dlg.title("⚠ Cảnh báo lệch cột")
        dlg.configure(bg=self.CARD)
        dlg.transient(self)
        dlg.grab_set()
        dlg.result = False

        tk.Label(dlg, text="⚠  Một số file có cột KHÁC với tab Google Sheet",
                 bg=self.CARD, fg=self.YELLOW, font=("Segoe UI Semibold", 12)
                 ).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(dlg,
                 text="Hãy kiểm tra xem có gán nhầm file vào sai tab không trước khi tiếp tục.",
                 bg=self.CARD, fg=self.MUTED, font=("Segoe UI", 9), justify="left"
                 ).pack(anchor="w", padx=18, pady=(0, 10))

        if replace:
            tk.Label(dlg,
                     text="⚠ Chế độ THAY THẾ đang bật: toàn bộ dữ liệu cũ trong các tab "
                          "trên sẽ bị XÓA trước khi import.",
                     bg=self.CARD, fg=self.RED, font=("Segoe UI Semibold", 9),
                     justify="left", wraplength=560
                     ).pack(anchor="w", padx=18, pady=(0, 10))

        # Vùng cuộn liệt kê chi tiết
        box = tk.Text(dlg, width=84, height=16, font=("Consolas", 9),
                      bg=self.CODE_BG, fg=self.TEXT, relief="flat", bd=0,
                      padx=10, pady=8, wrap="word", insertbackground=self.TEXT,
                      highlightthickness=1, highlightbackground=self.BORDER)
        sb = ttk.Scrollbar(dlg, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        box.pack(side="top", fill="both", expand=True, padx=(18, 0), pady=(0, 6))
        sb.place(in_=box, relx=1.0, rely=0, relheight=1.0, anchor="ne")
        box.tag_config("file", foreground=self.TEXT, font=("Consolas", 9, "bold"))
        box.tag_config("warn", foreground=self.YELLOW)
        box.tag_config("dim",  foreground=self.MUTED)

        for it in mismatched:
            a = it["analysis"]
            box.insert("end", f"📄 {it['path'].name}\n", "file")
            box.insert("end", f"   → tab: {it['ws'].title}\n", "dim")
            if a["new_cols"]:
                box.insert("end",
                    f"   ⚠ {len(a['new_cols'])} cột thừa (có ở file, thiếu ở sheet): "
                    f"{', '.join(a['new_cols'])}\n", "warn")
            if a["missing"]:
                box.insert("end",
                    f"   ⚠ {len(a['missing'])} cột thiếu (có ở sheet, thiếu ở file): "
                    f"{', '.join(a['missing'])}\n", "warn")
            box.insert("end", "\n")
        box.configure(state="disabled")

        ok_cnt = len(importable) - len(mismatched)
        summary = (f"Tổng cộng: {len(importable)} file sẽ import "
                   f"({ok_cnt} khớp, {len(mismatched)} lệch cột)")
        if no_tab:
            summary += f"  ·  bỏ qua {len(no_tab)} file chưa gán tab"
        tk.Label(dlg, text=summary, bg=self.CARD, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(2, 8))

        btn_row = tk.Frame(dlg, bg=self.CARD)
        btn_row.pack(anchor="e", padx=18, pady=(0, 16))

        def _ok():
            dlg.result = True
            dlg.destroy()

        ttk.Button(btn_row, text="Huỷ", command=dlg.destroy).pack(side="right")
        ttk.Button(btn_row, text="Vẫn import", style="Accent.TButton",
                   command=_ok).pack(side="right", padx=(0, 8))

        dlg.update_idletasks()
        w = max(dlg.winfo_width(), dlg.winfo_reqwidth())
        h = max(dlg.winfo_height(), dlg.winfo_reqheight())
        x = max(0, (dlg.winfo_screenwidth()  - w) // 2)
        y = max(0, (dlg.winfo_screenheight() - h) // 2)
        dlg.geometry(f"+{x}+{y}")
        self.wait_window(dlg)
        return dlg.result

    @staticmethod
    def _upsert_with_retry(ws, headers, rows, replace, max_retry=4):
        """Gọi upsert, tự thử lại khi gặp lỗi TẠM THỜI của Google API.

        Quota vượt ngưỡng (429) hay lỗi máy chủ (5xx) thường là nguyên nhân
        khi import nhiều file liền nhau. Chờ tăng dần (5→10→20→40→60s) rồi thử lại.
        """
        delay = 5
        for attempt in range(max_retry + 1):
            try:
                return upsert(ws, headers, rows, replace=replace)
            except APIError as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (429, 500, 502, 503) and attempt < max_retry:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise

    def _import_all_worker(self, items: list, replace: bool = False):
        total_added = total_updated = errors = 0
        dropped_report: list = []   # [(file_name, target_key, dropped_list)]
        for item in items:
            item["status"] = "importing"
            self.after(0, lambda i=item: self._refresh_tree_row(i))
            try:
                filtered, _ = filter_by_status(item["headers"], item["rows"])
                # Loại các dòng KHÔNG thuộc tháng mục tiêu (tự nhận theo đa số)
                filtered, dropped, target, _un = filter_by_month(
                    item["headers"], filtered)
                if dropped:
                    dropped_report.append((item["path"].name, target, dropped))
                stats = self._upsert_with_retry(
                    item["ws"], item["headers"], filtered, replace)
                item["status"] = "done"
                item["error"]  = ""                                # xóa lỗi cũ nếu chạy lại thành công
                self._sheet_hdr_cache.pop(item["ws"].title, None)  # cột sheet đã đổi
                total_added   += stats["added"]
                total_updated += stats["updated"]
            except Exception as e:
                item["status"] = "error"
                item["error"]  = str(e)
                errors        += 1
            self.after(0, lambda i=item: self._refresh_tree_row(i))
        self.after(0, lambda: self._import_all_done(
            total_added, total_updated, errors, len(items), dropped_report))

    def _import_all_done(self, added: int, updated: int, errors: int, total: int,
                         dropped_report: list = None):
        self._progress.stop()
        self._refresh_import_btn()
        dropped_report = dropped_report or []
        n_dropped = sum(len(d) for _, _, d in dropped_report)

        if errors:
            base = f"✓ {total - errors}/{total} file  ✗ {errors} lỗi"
        else:
            base = f"✓  {total} file  +{added} mới  ↺ {updated} cập nhật"
        if n_dropped:
            base += f"  ·  bỏ {n_dropped} dòng sai tháng"
        self._result_lbl.configure(text=base)

        if dropped_report:
            self._show_dropped_month_report(dropped_report, n_dropped)

    def _show_dropped_month_report(self, dropped_report: list, n_dropped: int):
        """Popup thông báo các dòng đã bị loại vì thuộc tháng khác tháng import."""
        lines = [f"Đã loại {n_dropped} dòng KHÔNG thuộc tháng import "
                 f"(tháng lấy theo đa số của mỗi file):", ""]
        for fname, target, dropped in dropped_report:
            lines.append(f"📄 {fname}  →  giữ {_month_label(target)}")
            cnt = Counter(_month_label(k) for _, k in dropped)
            for lb, c in cnt.items():
                lines.append(f"     • bỏ {c} dòng {lb}")
            lines.append("")
        messagebox.showwarning("Đã loại dòng sai tháng", "\n".join(lines).strip())

    # ── Text info helpers ─────────────────────────────────────────────────────

    def _write_info(self, text: str, tag: str = "dim"):
        self._info_box.configure(state="normal")
        self._info_box.delete("1.0", "end")
        self._info_box.insert("end", text, tag)
        self._info_box.configure(state="disabled")

    def _write_info_tagged(self, lines: list):
        self._info_box.configure(state="normal")
        self._info_box.delete("1.0", "end")
        for tag, text in lines:
            self._info_box.insert("end", text, tag)
        self._info_box.configure(state="disabled")

    # ── Tiện ích ──────────────────────────────────────────────────────────────

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, foreground=self.RED if error else self.MUTED)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
