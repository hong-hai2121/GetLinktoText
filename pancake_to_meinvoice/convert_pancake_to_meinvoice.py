# =============================================================================
# convert_pancake_to_meinvoice.py
# Chuyển đổi dữ liệu đơn hàng từ Pancake sang mẫu hóa đơn điện tử meInvoice.vn
# Tác giả: Python Script cho kế toán bán hàng online
# Ngày tạo: 2026-05-21
# =============================================================================

import io
import os
import re
import sys
import difflib
import logging
import unicodedata
import warnings
from datetime import datetime, date
from copy import copy

import pandas as pd
import openpyxl
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from dateutil import parser as date_parser

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# =============================================================================
# CẤU HÌNH — Chỉnh các giá trị này để phù hợp với file của bạn
# =============================================================================
CONFIG = {
    # ── Đường dẫn file ──────────────────────────────────────────────────────
    "PANCAKE_FILE":    "pancake.xlsx",
    "TEMPLATE_FILE":  "Mau_hoa_don_GTGT_MTT.xls",
    "OUTPUT_FILE":    "meinvoice_output.xlsx",
    "EXTERNAL_FILE":  "external_amounts.xlsx",   # Tùy chọn, bỏ qua nếu không có

    # ── Cấu hình sheet ──────────────────────────────────────────────────────
    # Để "" hoặc None để chương trình tự tìm sheet chính
    "PANCAKE_SHEET":   "",        # Ví dụ: "Sheet1", "Đơn hàng", "Data"
    "TEMPLATE_SHEET":  "Hóa đơn GTGT",  # Sheet trong file mẫu meInvoice
    "START_ROW":       9,         # Dòng bắt đầu ghi dữ liệu (dòng 8 là header, 9 là data)

    # ── Lọc trạng thái đơn hàng ─────────────────────────────────────────────
    # Chỉ xuất hóa đơn cho các đơn có trạng thái chứa các từ khóa này
    "VALID_STATUS_KEYWORDS": [
        # Trạng thái phổ biến trong Pancake
        "đã nhận", "đã xác nhận", "xác nhận",
        "đã giao", "giao thành công", "hoàn thành", "thành công",
        "đang giao", "đang xử lý",
        "delivered", "completed", "success", "done", "confirmed",
    ],
    # Bỏ qua đơn có trạng thái chứa các từ khóa này
    "SKIP_STATUS_KEYWORDS": [
        "hủy", "huỷ", "hoàn trả", "hoàn về",
        "cancelled", "returned", "cancel", "return", "refund",
    ],
    # Để True nếu muốn xuất tất cả đơn bất kể trạng thái (khi không có cột trạng thái)
    "EXPORT_ALL_IF_NO_STATUS": True,

    # ── Thông tin mặc định hóa đơn ──────────────────────────────────────────
    "DEFAULT_TAX_RATE":      8,          # Thuế suất GTGT (%) — 8 hoặc 10
    "DEFAULT_PAYMENT_METHOD": "TM/CK",  # Hình thức thanh toán
    "DEFAULT_CURRENCY":      "VND",      # Đơn vị tiền tệ
    "SELLER_NAME":           "",         # Tên người bán/đơn vị (nếu cần)
    "SELLER_TAX_CODE":       "",         # Mã số thuế người bán

    # ── Ngày mặc định nếu không có ngày trong dữ liệu ───────────────────────
    # Để "" hoặc None để dùng ngày hiện tại
    "DEFAULT_INVOICE_DATE":  "",         # Ví dụ: "21/05/2026"

    # ── Bảng giá thuốc ──────────────────────────────────────────────────────
    # File Excel có cột: Tên thuốc/sản phẩm, Đơn giá, Thuế suất GTGT (%)
    "PRICE_TABLE_FILE":  "bang_ten_thuoc_gia_tien.xlsx",

    # ── Đơn vị tính mặc định ────────────────────────────────────────────────
    "DEFAULT_DVT":       "Hộp",

    # ── Tùy chọn khác ───────────────────────────────────────────────────────
    "INCLUDE_SHIPPING_FEE":  False,      # True = thêm dòng phí ship vào hóa đơn
    "SHIPPING_ITEM_NAME":    "Phí vận chuyển",

    # ── Để trống cột giá/thuế ───────────────────────────────────────────────
    # True  = Đơn giá, Thành tiền, Thuế suất, Tiền thuế đều để trống
    # False = Lấy từ PRICE_TABLE_FILE (nếu có) hoặc tính từ Pancake
    "LEAVE_PRICE_EMPTY":     False,
}

# =============================================================================
# ÁNH XẠ CỘT PANCAKE → MEINVOICE
# Chỉnh tên cột bên trái (KEY) nếu tên cột trong file Pancake của bạn khác
# =============================================================================
PANCAKE_COLUMN_MAP = {
    # KEY: tên cột mong đợi trong meInvoice / nội dung
    # VALUE: danh sách tên cột có thể có trong Pancake (ưu tiên từ trái)

    "ma_don_hang": [
        "Mã đơn hàng", "ma_don_hang", "Mã ĐH", "Order ID", "order_id",
        "Số đơn hàng", "ID"
    ],
    "ngay_tao_don": [
        "Ngày tạo", "ngay_tao", "Ngày tạo đơn", "Created Date",
        "Ngày đặt hàng", "Thời gian tạo", "created_at", "Date"
    ],
    "ngay_giao": [
        "Ngày giao", "ngay_giao", "Ngày giao hàng", "Delivered Date",
        "Ngày hoàn thành", "completed_at"
    ],
    "ten_khach_hang": [
        "Tên khách hàng", "Khách hàng", "Người mua", "Customer Name",
        "customer_name", "Họ tên", "Ho ten"
    ],
    "so_dien_thoai": [
        "Số điện thoại", "SĐT", "Phone", "Điện thoại",
        "so_dien_thoai", "phone_number", "SDT"
    ],
    "dia_chi": [
        "Địa chỉ", "Địa chỉ giao hàng", "Address", "dia_chi",
        "Địa chỉ nhận hàng", "shipping_address"
    ],
    "ten_san_pham": [
        "Tên sản phẩm", "Sản phẩm", "Product Name", "product_name",
        "Hàng hóa", "Item", "Tên hàng", "product"
    ],
    "so_luong": [
        "Số lượng", "SL", "Quantity", "so_luong", "qty", "Quy cách"
    ],
    "don_gia": [
        "Đơn giá", "Giá bán", "Giá", "Price", "don_gia",
        "Unit Price", "Giá sau giảm", "Giá SP"
    ],
    "thanh_tien": [
        "Thành tiền", "Tổng tiền", "Total", "thanh_tien",
        "Tổng cộng", "Amount", "Tiền hàng"
    ],
    "cod": [
        "COD", "Tiền thu hộ", "Tiền COD", "cod",
        "Tiền khách trả", "Thu hộ"
    ],
    "phi_ship": [
        "Phí ship", "Phí vận chuyển", "Phí giao hàng", "phi_ship",
        "Shipping Fee", "Cước ship",
        "Phí VC thu của khách", "Phi VC thu cua khach", "Phụ thu",
    ],
    "giam_gia": [
        "Giảm giá", "Discount", "Khuyến mãi", "giam_gia",
        "Chiết khấu", "CK"
    ],
    "trang_thai": [
        "Trạng thái", "Trạng thái đơn", "Status", "trang_thai",
        "Order Status", "Tình trạng"
    ],
    "ghi_chu": [
        "Ghi chú", "Note", "Ghi chú đơn", "ghi_chu",
        "Notes", "Ghi chú khách",
        "Ghi chú để in", "Ghi chu de in", "Ghi chú nội bộ",
    ],
    "ma_van_chuyen": [
        "Mã vận đơn", "Mã vận chuyển", "Tracking", "ma_van_chuyen",
        "Tracking Number", "Mã VC"
    ],
    "nguoi_nhan": [
        "Người nhận", "Người nhận hàng", "nguoi_nhan",
        "Tên người nhận", "Recipient",
    ],
}

# Các cột địa chỉ phụ sẽ được ghép vào sau cột "dia_chi" chính
# Pancake thường tách thành: Địa chỉ, Phường/Xã, Quận/Huyện, Tỉnh
ADDRESS_EXTRA_COLS = [
    "Phường/Xã", "Phuong/Xa",
    "Quận/Huyện", "Quan/Huyen",
    "Tỉnh", "Tinh", "Thành phố",
]

# Cột trong file mẫu meInvoice — khớp chính xác với template thực tế
MEINVOICE_COLUMNS = [
    "Số thứ tự hóa đơn (*)",   # STT tự tăng
    "Ngày hóa đơn",             # Ngày
    "Tên đơn vị mua hàng",      # Tên khách hàng / công ty
    "Mã số thuế",               # Để trống với khách lẻ
    "Địa chỉ",                  # Địa chỉ đầy đủ (ghép Phường/Xã, Quận/Huyện, Tỉnh)
    "Người mua hàng",           # Người nhận hàng
    "Email",                    # Để trống
    "Số điện thoại",            # SĐT
    "Căn cước công dân",        # Để trống
    "Hình thức thanh toán (*)", # TM/CK
    "Tên hàng hóa/dịch vụ (*)",# Tên sản phẩm
    "ĐVT",                      # Đơn vị tính
    "Số lượng",                 # SL
    "Đơn giá",                  # Giá chưa thuế
    "Thành tiền",               # SL × Đơn giá − Giảm giá
    "Thuế suất GTGT (%)",       # 8 hoặc 10 (số, không phải "8%")
    "Tiền thuế GTGT",           # Thành tiền × Thuế suất / 100
]

# =============================================================================
# Thiết lập logging
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("convert_log.txt", encoding="utf-8", mode="w"),
    ],
)
log = logging.getLogger(__name__)


# =============================================================================
# 1. load_excel()
# =============================================================================
def load_excel(file_path: str, sheet_name=None) -> tuple[pd.DataFrame, str]:
    """Đọc file Excel, trả về DataFrame và tên sheet đã dùng."""
    if not os.path.exists(file_path):
        log.error(f"Không tìm thấy file: {file_path}")
        sys.exit(1)

    xl = pd.ExcelFile(file_path, engine="openpyxl")
    all_sheets = xl.sheet_names
    log.debug(f"File '{file_path}' có {len(all_sheets)} sheet: {all_sheets}")

    if sheet_name:
        if sheet_name not in all_sheets:
            log.warning(
                f"Sheet '{sheet_name}' không tồn tại trong '{file_path}'. "
                f"Sẽ dùng sheet đầu tiên: '{all_sheets[0]}'"
            )
            sheet_name = all_sheets[0]
    else:
        sheet_name = detect_sheet(xl, all_sheets)

    df = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    log.info(f"Đọc sheet '{sheet_name}': {len(df)} dòng, {len(df.columns)} cột")
    log.debug(f"Danh sách cột: {list(df.columns)}")
    return df, sheet_name


# =============================================================================
# 1b. forward_fill_order_rows()
# =============================================================================
# Các cột cấp ĐƠN HÀNG (order-level) — được forward-fill xuống dòng sản phẩm con
# Không fill: Sản phẩm, Mã sản phẩm, Số lượng, Đơn giá, Giảm giá (cấp sản phẩm)
ORDER_LEVEL_COLS = [
    "Mã đơn hàng", "Mã vận đơn", "Trạng thái",
    "Khách hàng", "Số điện thoại", "Người nhận",
    "Địa chỉ", "Phường/Xã", "Quận/Huyện", "Tỉnh",
    "Nguồn đơn", "Kho hàng", "Mã tuỳ chỉnh đơn hàng",
    "Trả trước", "Chuyển khoản", "Tiền khách đưa", "Quẹt thẻ",
    "Quốc gia", "Đồng bộ snappy",
    "Phí VC thu của khách", "Phụ thu", "COD",
    "Ghi chú để in", "Ghi chú nội bộ",
    "Nhân viên xử lý sản phẩm",
]


def forward_fill_order_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pancake export theo cấu trúc: 1 đơn hàng = nhiều dòng sản phẩm.
    Dòng đầu của mỗi đơn có đầy đủ thông tin, các dòng tiếp theo để trống.
    Hàm này forward-fill các cột cấp đơn hàng xuống các dòng sản phẩm con.
    """
    df = df.copy()

    # Chỉ fill những cột thực sự tồn tại trong DataFrame
    cols_to_fill = [c for c in ORDER_LEVEL_COLS if c in df.columns]

    if not cols_to_fill:
        return df

    # Xác định dòng đầu của mỗi đơn: Mã đơn hàng không rỗng
    id_col = next((c for c in ["Mã đơn hàng", "ma_don_hang", "Order ID"]
                   if c in df.columns), None)

    if id_col:
        # Tạo group ID: mỗi khi Mã đơn hàng có giá trị mới → group mới
        has_id = df[id_col].notna() & (df[id_col].astype(str).str.strip() != "")
        group_id = has_id.cumsum()

        # Với mỗi group: fill giá trị từ dòng đầu xuống các dòng sau
        for col in cols_to_fill:
            df[col] = df.groupby(group_id)[col].transform(
                lambda s: s.where(s.notna() & (s.astype(str).str.strip() != "")).ffill()
            )
        total_groups = group_id.max()
        log.debug(f"Forward-fill: {total_groups} đơn hàng, {len(df)} dòng sản phẩm")
    else:
        # Fallback: ffill thẳng toàn bộ
        df[cols_to_fill] = df[cols_to_fill].ffill()
        log.debug("Forward-fill toàn bộ (không tìm thấy cột Mã đơn hàng để nhóm)")

    return df


# =============================================================================
# 2. detect_sheet()
# =============================================================================
def detect_sheet(xl: pd.ExcelFile, all_sheets: list) -> str:
    """Tự động tìm sheet chính chứa dữ liệu đơn hàng."""
    order_keywords = [
        "đơn hàng", "don hang", "order", "data", "dữ liệu", "du lieu",
        "danh sách", "danh sach", "bán hàng", "ban hang", "pancake"
    ]
    for sheet in all_sheets:
        sl = sheet.lower()
        if any(kw in sl for kw in order_keywords):
            log.debug(f"Tự động chọn sheet: '{sheet}'")
            return sheet

    # Fallback: chọn sheet có nhiều dòng nhất
    best_sheet, best_rows = all_sheets[0], 0
    for sheet in all_sheets:
        try:
            df_tmp = pd.read_excel(xl, sheet_name=sheet, engine="openpyxl", nrows=5)
            rows = len(df_tmp)
            if rows > best_rows:
                best_rows = rows
                best_sheet = sheet
        except Exception:
            pass

    log.debug(f"Không tìm thấy sheet theo từ khóa, dùng sheet: '{best_sheet}'")
    return best_sheet


# =============================================================================
# 3. normalize_columns()
# =============================================================================
def normalize_columns(df: pd.DataFrame, column_map: dict) -> dict:
    """
    Tìm tên cột thực tế trong DataFrame tương ứng với từng trường logic.
    Trả về dict: {key_logic: tên_cột_thực_tế hoặc None}
    """
    df_cols_lower = {c.lower().strip(): c for c in df.columns}
    result = {}
    missing = []

    for key, candidates in column_map.items():
        found = None
        for cand in candidates:
            cand_lower = cand.lower().strip()
            if cand_lower in df_cols_lower:
                found = df_cols_lower[cand_lower]
                break
        result[key] = found
        if found is None:
            missing.append(key)

    if missing:
        log.warning(
            f"Không tìm thấy các cột sau (sẽ để trống hoặc dùng giá trị mặc định): "
            f"{missing}"
        )
        log.warning(
            "  → Hãy chỉnh PANCAKE_COLUMN_MAP trong file script để khớp tên cột thực tế."
        )
    else:
        log.debug("Đã ánh xạ đầy đủ tất cả các cột.")

    log.debug("Ánh xạ cột Pancake:")
    for k, v in result.items():
        status = f"✓ '{v}'" if v else "✗ KHÔNG TÌM THẤY"
        log.debug(f"  {k:20s} → {status}")

    return result


# =============================================================================
# 4. clean_money()
# =============================================================================
def clean_money(value) -> float:
    """
    Chuyển đổi các dạng tiền tệ VN sang float.
    Xử lý: "1.200.000 ₫", "1,200,000", "1200000", "'2.573.523 ₫", None, ""
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "-", "n/a"):
        return 0.0
    # Xóa ký tự không phải số, dấu phẩy, dấu chấm, dấu trừ
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return 0.0
    # Xác định định dạng: "1.200.000" (dấu chấm là phân cách ngàn)
    # vs "1,200.50" (dấu phẩy là phân cách ngàn, dấu chấm là thập phân)
    dot_count = s.count(".")
    comma_count = s.count(",")
    try:
        if dot_count > 1:
            # "1.200.000" → loại bỏ tất cả dấu chấm
            s = s.replace(".", "")
            if comma_count == 1:
                s = s.replace(",", ".")
            return float(s)
        elif comma_count > 1:
            # "1,200,000"
            s = s.replace(",", "")
            return float(s)
        elif dot_count == 1 and comma_count == 1:
            # "1.200,50" hoặc "1,200.50"
            dot_pos = s.index(".")
            comma_pos = s.index(",")
            if dot_pos < comma_pos:
                # "1.200,50" → dot là phân cách ngàn
                s = s.replace(".", "").replace(",", ".")
            else:
                # "1,200.50" → comma là phân cách ngàn
                s = s.replace(",", "")
            return float(s)
        elif comma_count == 1:
            # "1200,50" → dấu phẩy là thập phân (VN)
            s = s.replace(",", ".")
            return float(s)
        else:
            return float(s)
    except (ValueError, TypeError):
        log.debug(f"Không parse được tiền tệ: '{value}'")
        return 0.0


# =============================================================================
# 5. parse_date()
# =============================================================================
def parse_date(value) -> date | None:
    """
    Chuẩn hóa ngày từ nhiều định dạng khác nhau.
    Xử lý: "21/05/2026", "21 Tháng 5, 2026", datetime Excel, None
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value

    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None

    # Chuẩn hóa tháng tiếng Việt
    vn_months = {
        "tháng 1": "January",   "tháng 2": "February",
        "tháng 3": "March",     "tháng 4": "April",
        "tháng 5": "May",       "tháng 6": "June",
        "tháng 7": "July",      "tháng 8": "August",
        "tháng 9": "September", "tháng 10": "October",
        "tháng 11": "November", "tháng 12": "December",
    }
    s_lower = s.lower()
    for vn, en in vn_months.items():
        if vn in s_lower:
            s = re.sub(vn, en, s, flags=re.IGNORECASE)
            break

    # Thử các định dạng thông dụng
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d %B %Y", "%d %b %Y",
        "%d %B, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    # Dùng dateutil làm fallback
    try:
        return date_parser.parse(s, dayfirst=True).date()
    except Exception:
        log.debug(f"Không parse được ngày: '{value}'")
        return None


def get_default_date() -> date:
    """Lấy ngày mặc định từ CONFIG hoặc ngày hiện tại."""
    cfg_date = CONFIG.get("DEFAULT_INVOICE_DATE", "")
    if cfg_date:
        parsed = parse_date(cfg_date)
        if parsed:
            return parsed
    return date.today()


def get_unique_statuses(file_path: str, sheet_name: str = "") -> list[str]:
    """Đọc file Pancake và trả về danh sách các trạng thái duy nhất."""
    try:
        xl = pd.ExcelFile(file_path, engine="openpyxl")
        sn = sheet_name if sheet_name and sheet_name in xl.sheet_names else xl.sheet_names[0]
        df = pd.read_excel(file_path, sheet_name=sn, engine="openpyxl", dtype=str)
        df.columns = [str(c).strip() for c in df.columns]

        status_candidates = ["Trạng thái", "Trạng thái đơn", "Status", "trang_thai", "Tình trạng"]
        for col in status_candidates:
            if col in df.columns:
                vals = df[col].dropna().unique().tolist()
                return sorted(str(v).strip() for v in vals if str(v).strip())
    except Exception:
        pass
    return []


# =============================================================================
# 6. filter_valid_orders()
# =============================================================================
def filter_valid_orders(df: pd.DataFrame, col_map: dict) -> tuple[pd.DataFrame, list]:
    """
    Lọc các đơn hàng hợp lệ để xuất hóa đơn.
    Trả về (df_valid, skipped_list)
    """
    skipped = []

    status_col = col_map.get("trang_thai")
    if not status_col:
        if CONFIG["EXPORT_ALL_IF_NO_STATUS"]:
            log.info("Không có cột trạng thái → xuất tất cả đơn hàng.")
            return df.copy(), skipped
        else:
            log.warning("Không có cột trạng thái và EXPORT_ALL_IF_NO_STATUS=False → không xuất gì.")
            return pd.DataFrame(), skipped

    valid_rows = []
    for idx, row in df.iterrows():
        status_raw = str(row.get(status_col, "")).strip().lower()
        reason = None

        # Kiểm tra skip trước
        for kw in CONFIG["SKIP_STATUS_KEYWORDS"]:
            if kw.lower() in status_raw:
                reason = f"Trạng thái bị bỏ qua: '{row[status_col]}'"
                break

        if reason is None and status_raw:
            # Kiểm tra valid
            is_valid = any(
                kw.lower() in status_raw
                for kw in CONFIG["VALID_STATUS_KEYWORDS"]
            )
            if not is_valid:
                reason = f"Trạng thái không hợp lệ: '{row[status_col]}'"

        if reason:
            ma_don = row.get(col_map.get("ma_don_hang") or "", f"Dòng {idx+2}")
            skipped.append({
                "ma_don_hang": ma_don,
                "dong_excel":  idx + 2,
                "ly_do":       reason,
            })
        else:
            valid_rows.append(idx)

    df_valid = df.loc[valid_rows].copy()
    log.info(
        f"Lọc trạng thái: {len(df)} tổng → {len(df_valid)} hợp lệ, "
        f"{len(skipped)} bị bỏ qua"
    )
    return df_valid, skipped


# =============================================================================
# 7. merge_external_amounts()
# =============================================================================
def merge_external_amounts(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    Ghép dữ liệu từ external_amounts.xlsx nếu file tồn tại.
    Ưu tiên số tiền và ngày hóa đơn từ file ngoài.
    """
    ext_path = CONFIG["EXTERNAL_FILE"]
    if not os.path.exists(ext_path):
        log.debug(f"Không tìm thấy '{ext_path}' → dùng dữ liệu Pancake.")
        return df

    log.info(f"Đang đọc file external: '{ext_path}'")
    try:
        df_ext = pd.read_excel(ext_path, engine="openpyxl", dtype=str)
        df_ext.columns = [str(c).strip() for c in df_ext.columns]
    except Exception as e:
        log.error(f"Lỗi đọc '{ext_path}': {e}")
        return df

    # Tìm cột mã đơn trong external
    ext_id_col = None
    for cand in ["ma_don_hang", "Mã đơn hàng", "order_id", "ID"]:
        if cand in df_ext.columns:
            ext_id_col = cand
            break
    if not ext_id_col:
        log.warning(f"Không tìm thấy cột mã đơn trong '{ext_path}' → bỏ qua.")
        return df

    ma_don_col = col_map.get("ma_don_hang")
    if not ma_don_col:
        log.warning("Không có cột mã đơn trong Pancake → không thể ghép external.")
        return df

    df_ext = df_ext.rename(columns={
        ext_id_col:                  "__ext_ma_don__",
        "so_tien_xuat_hoa_don":      "__ext_so_tien__",
        "thue_suat":                 "__ext_thue_suat__",
        "ngay_hoa_don":              "__ext_ngay__",
        "ghi_chu_hoa_don":           "__ext_ghi_chu__",
        "trang_thai_xuat_hoa_don":   "__ext_trang_thai__",
    })

    df = df.copy()
    df["__merge_key__"] = df[ma_don_col].astype(str).str.strip()
    df_ext["__merge_key__"] = df_ext["__ext_ma_don__"].astype(str).str.strip()

    ext_cols = [c for c in df_ext.columns if c.startswith("__ext_")]
    df_ext_merge = df_ext[["__merge_key__"] + ext_cols]

    df = df.merge(df_ext_merge, on="__merge_key__", how="left")
    df.drop(columns=["__merge_key__"], inplace=True)

    matched = df["__ext_so_tien__"].notna().sum()
    log.debug(f"Ghép external_amounts: {matched}/{len(df)} dòng có dữ liệu ngoài.")
    return df


# =============================================================================
# 7b. load_price_table() / lookup_price()
# =============================================================================
def load_price_table() -> dict:
    """
    Đọc bảng giá thuốc từ PRICE_TABLE_FILE.
    Trả về dict {tên_thuốc_lower: {"don_gia": float, "thue_suat": float, "ten_goc": str, "ten_moi": str}}
    Cột "Tên Mới" (nếu có) là tên dùng để in trên hóa đơn.
    """
    path = CONFIG.get("PRICE_TABLE_FILE", "")
    if not path:
        return {}
    # Nếu là đường dẫn tương đối, thử tìm bên cạnh script
    if not os.path.isabs(path):
        if getattr(sys, "frozen", False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, path)
    if not os.path.isfile(path):
        log.warning(f"Không tìm thấy bảng giá thuốc: {path}")
        return {}

    try:
        df_pt = pd.read_excel(path)
    except Exception as e:
        log.error(f"Lỗi đọc bảng giá: {e}")
        return {}

    name_col = new_name_col = price_col = tax_col = None
    for col in df_pt.columns:
        cl = str(col).lower().strip()
        if cl in ("tên mới", "ten moi", "new name"):
            new_name_col = col
        elif any(k in cl for k in ("tên", "ten", "thuốc", "thuoc", "sản phẩm", "san pham", "name")):
            if name_col is None:
                name_col = col
        elif any(k in cl for k in ("đơn giá", "don gia", "giá", "gia", "price")):
            if price_col is None:
                price_col = col
        elif any(k in cl for k in ("thuế", "thue", "tax")):
            if tax_col is None:
                tax_col = col

    if not name_col or not price_col:
        log.warning(f"Bảng giá: không tìm thấy cột tên hoặc đơn giá. Cột có: {list(df_pt.columns)}")
        return {}

    log.info(
        f"Bảng giá — cột tên tìm kiếm: '{name_col}' | cột tên mới: '{new_name_col}' "
        f"| cột giá: '{price_col}' | cột thuế: '{tax_col}'"
    )
    table = {}
    for _, row in df_pt.iterrows():
        name = str(row.get(name_col, "")).strip()
        if not name or name.lower() in ("nan", "none", ""):
            continue
        try:
            don_gia = float(re.sub(r"[^\d.]", "", str(row[price_col])) or 0)
        except Exception:
            don_gia = 0.0
        try:
            thue_suat = float(re.sub(r"[^\d.]", "", str(row[tax_col])) or CONFIG["DEFAULT_TAX_RATE"]) if tax_col else CONFIG["DEFAULT_TAX_RATE"]
        except Exception:
            thue_suat = float(CONFIG["DEFAULT_TAX_RATE"])
        ten_moi = ""
        if new_name_col:
            v = str(row.get(new_name_col, "")).strip()
            if v and v.lower() not in ("nan", "none"):
                ten_moi = v
        table[name.lower()] = {"don_gia": don_gia, "thue_suat": thue_suat, "ten_goc": name, "ten_moi": ten_moi}

    sample = list(table.keys())[:3]
    log.info(f"Đã tải bảng giá thuốc: {len(table)} sản phẩm từ '{os.path.basename(path)}' — 3 tên đầu: {sample}")
    return table


def _normalize_name(s: str) -> str:
    """Chuẩn hóa tên: Unicode NFC, bỏ khoảng trắng ẩn, lowercase."""
    s = unicodedata.normalize("NFC", s)   # fix dấu tiếng Việt encode khác nhau
    s = s.replace("\xa0", " ").replace("\t", " ")  # non-breaking space, tab
    return " ".join(s.lower().split())


def lookup_price(ten_sp: str, price_table: dict):
    """
    Tìm đơn giá, thuế suất và tên mới theo tên sản phẩm.
    1. Exact match sau khi chuẩn hóa (lowercase + khoảng trắng)
    2. Fuzzy match với ngưỡng 0.80 — chỉ khớp khi tên rất gần nhau
    Trả về (don_gia, thue_suat, ten_moi) hoặc (None, None, None) nếu không tìm thấy.
    """
    if not price_table or not ten_sp:
        return None, None, None

    key = _normalize_name(ten_sp)
    norm_table = {_normalize_name(k): k for k in price_table}

    # 1. Exact
    if key in norm_table:
        rec = price_table[norm_table[key]]
        return rec["don_gia"], rec["thue_suat"], rec.get("ten_moi", "")

    # 2. Fuzzy — ngưỡng 0.80
    matches = difflib.get_close_matches(key, norm_table.keys(), n=1, cutoff=0.80)
    if matches:
        orig_key = norm_table[matches[0]]
        rec = price_table[orig_key]
        log.debug(f"Fuzzy match: '{ten_sp}' → '{rec['ten_goc']}'")
        return rec["don_gia"], rec["thue_suat"], rec.get("ten_moi", "")

    return None, None, None


# =============================================================================
# 8. transform_to_meinvoice()
# =============================================================================
def transform_to_meinvoice(df: pd.DataFrame, col_map: dict) -> tuple[pd.DataFrame, dict]:
    """
    Chuyển đổi DataFrame Pancake sang cấu trúc meInvoice.
    Trả về (df_output, check_data)
    """
    rows_output = []
    check_data = {
        "missing_phone":    [],
        "missing_address":  [],
        "missing_product":  [],
        "missing_amount":   [],
        "missing_price":    [],
        "missing_new_name": [],
        "zero_price":       [],
        "amount_diff":      [],
        "order_comparison": {},  # {ma_don: {"ten_kh": str, "pancake": float, "invoice": float}}
    }

    def get_val(row, key):
        col = col_map.get(key)
        if col and col in row.index:
            v = row[col]
            if pd.notna(v):
                return str(v).strip()
        return ""

    default_date  = get_default_date()
    price_table   = load_price_table()
    stt           = 0
    prev_ma_don   = None

    # Tìm cột địa chỉ phụ (Phường/Xã, Quận/Huyện, Tỉnh) có trong DataFrame
    df_cols_lower = {c.lower().strip(): c for c in df.columns}
    extra_addr_cols = []
    for cand in ADDRESS_EXTRA_COLS:
        real = df_cols_lower.get(cand.lower().strip())
        if real and real not in extra_addr_cols:
            extra_addr_cols.append(real)

    for idx, row in df.iterrows():
        ma_don       = get_val(row, "ma_don_hang")
        ten_kh       = get_val(row, "ten_khach_hang")
        nguoi_nhan   = get_val(row, "nguoi_nhan") or ten_kh
        sdt          = get_val(row, "so_dien_thoai")
        ten_sp       = get_val(row, "ten_san_pham")
        sl_raw       = get_val(row, "so_luong")
        don_gia_raw  = get_val(row, "don_gia")
        thanh_tien_raw = get_val(row, "thanh_tien")
        cod_raw      = get_val(row, "cod")
        phi_ship_raw = get_val(row, "phi_ship")
        ghi_chu      = get_val(row, "ghi_chu")
        giam_gia_raw = get_val(row, "giam_gia")

        # ── Ghép địa chỉ đầy đủ ─────────────────────────────────────────────
        dia_chi_parts = [get_val(row, "dia_chi")]
        for ec in extra_addr_cols:
            v = str(row.get(ec, "")).strip()
            if v and v.lower() not in ("nan", "none", ""):
                dia_chi_parts.append(v)
        dia_chi = ", ".join(p for p in dia_chi_parts if p)

        # ── Ngày hóa đơn ────────────────────────────────────────────────────
        # Ưu tiên: external → ngày giao → ngày tạo đơn → default
        ngay_hd = None
        ext_ngay = row.get("__ext_ngay__", "")
        if pd.notna(ext_ngay) and str(ext_ngay).strip():
            ngay_hd = parse_date(ext_ngay)
        if ngay_hd is None:
            ngay_hd = parse_date(get_val(row, "ngay_giao"))
        if ngay_hd is None:
            ngay_hd = parse_date(get_val(row, "ngay_tao_don"))
        if ngay_hd is None:
            ngay_hd = default_date

        # ── STT per đơn hàng — dòng đầu tiên của mỗi đơn ───────────────────
        is_first_row = (ma_don != prev_ma_don)
        if is_first_row:
            stt += 1
            prev_ma_don = ma_don

        # ── Số lượng ────────────────────────────────────────────────────────
        so_luong = clean_money(sl_raw) if sl_raw else 1.0
        if so_luong == 0:
            so_luong = 1.0

        # ── Giá từ bảng thuốc ───────────────────────────────────────────────
        leave_price = CONFIG.get("LEAVE_PRICE_EMPTY", False)
        don_gia = thanh_tien = thue_suat = tien_thue = ""

        if not leave_price:
            if price_table:
                if not ten_sp:
                    pass  # tên trống → bỏ qua tra giá, đã ghi vào missing_product bên dưới
                else:
                    pt_don_gia, pt_thue_suat, pt_ten_moi = lookup_price(ten_sp, price_table)
                    if pt_don_gia is not None and pt_don_gia == 0:
                        ref = {"ma_don": ma_don, "dong_excel": idx + 2, "ten_sp": ten_sp}
                        check_data["zero_price"].append(ref)
                    elif pt_don_gia is not None:
                        if not pt_ten_moi:
                            ref = {"ma_don": ma_don, "dong_excel": idx + 2, "ten_sp": ten_sp}
                            check_data["missing_new_name"].append(ref)
                        else:
                            ten_sp     = pt_ten_moi
                            don_gia    = pt_don_gia
                            thue_suat  = pt_thue_suat
                            thanh_tien = round(don_gia * so_luong, 0)
                            tien_thue  = round(thanh_tien * thue_suat / 100, 0)
                    else:
                        ref_price = {"ma_don": ma_don, "dong_excel": idx + 2, "ten_sp": ten_sp}
                        check_data["missing_price"].append(ref_price)
            else:
                # Không có bảng giá → tính từ Pancake như cũ
                don_gia_raw_val  = clean_money(get_val(row, "don_gia"))
                thanh_tien_val   = clean_money(get_val(row, "thanh_tien"))
                giam_gia_val     = clean_money(get_val(row, "giam_gia"))
                cod_val          = clean_money(get_val(row, "cod"))
                if thanh_tien_val == 0 and don_gia_raw_val > 0:
                    thanh_tien_val = max(0.0, so_luong * don_gia_raw_val - giam_gia_val)
                if thanh_tien_val == 0:
                    thanh_tien_val = cod_val
                if thanh_tien_val > 0 and don_gia_raw_val == 0:
                    don_gia_raw_val = thanh_tien_val / so_luong if so_luong else thanh_tien_val
                ext_thue = row.get("__ext_thue_suat__", "")
                if pd.notna(ext_thue) and str(ext_thue).strip():
                    try:
                        thue_suat = float(re.sub(r"[^\d.]", "", str(ext_thue)))
                    except Exception:
                        thue_suat = float(CONFIG["DEFAULT_TAX_RATE"])
                else:
                    thue_suat = float(CONFIG["DEFAULT_TAX_RATE"])
                don_gia    = don_gia_raw_val
                thanh_tien = thanh_tien_val
                tien_thue  = round(thanh_tien * thue_suat / 100, 0) if isinstance(thanh_tien, (int, float)) else ""

        # ── Ghi chú ─────────────────────────────────────────────────────────
        ext_ghi_chu = str(row.get("__ext_ghi_chu__", "")).strip()
        if ext_ghi_chu and ext_ghi_chu != "nan":
            ghi_chu = ext_ghi_chu + (" | " + ghi_chu if ghi_chu else "")

        # ── Kiểm tra dữ liệu ────────────────────────────────────────────────
        ref = {"ma_don": ma_don, "dong_excel": idx + 2}
        if not sdt:
            check_data["missing_phone"].append(ref.copy())
        if not dia_chi:
            check_data["missing_address"].append(ref.copy())
        if not ten_sp:
            check_data["missing_product"].append(ref.copy())
        if not leave_price and not price_table and thanh_tien == 0:
            check_data["missing_amount"].append(ref.copy())

        # So sánh đơn giá×SL (Pancake) vs thành tiền+thuế (meInvoice)
        pancake_total = clean_money(don_gia_raw) * so_luong
        inv_tt  = thanh_tien if isinstance(thanh_tien, (int, float)) else 0.0
        inv_tax = tien_thue  if isinstance(tien_thue,  (int, float)) else 0.0
        invoice_total = inv_tt + inv_tax
        if ma_don not in check_data["order_comparison"]:
            check_data["order_comparison"][ma_don] = {"ten_kh": ten_kh, "pancake": 0.0, "invoice": 0.0}
        check_data["order_comparison"][ma_don]["pancake"] += pancake_total
        check_data["order_comparison"][ma_don]["invoice"] += invoice_total

        # Cột thông tin khách chỉ điền ở dòng đầu tiên của mỗi đơn;
        # dòng sản phẩm tiếp theo của cùng đơn để trống tránh lặp.
        row_out = {
            "Số thứ tự hóa đơn (*)":    stt,
            "Ngày hóa đơn":             ngay_hd.strftime("%d/%m/%Y") if is_first_row else "",
            "Tên đơn vị mua hàng":      ten_kh    if is_first_row else "",
            "Mã số thuế":               "",
            "Địa chỉ":                  dia_chi   if is_first_row else "",
            "Người mua hàng":           nguoi_nhan if is_first_row else "",
            "Email":                    "",
            "Số điện thoại":            sdt       if is_first_row else "",
            "Căn cước công dân":        "",
            "Hình thức thanh toán (*)": CONFIG["DEFAULT_PAYMENT_METHOD"] if is_first_row else "",
            "Tên hàng hóa/dịch vụ (*)": ten_sp,
            "ĐVT":                      CONFIG.get("DEFAULT_DVT", "Hộp"),
            "Số lượng":                 so_luong,
            "Đơn giá":                  don_gia,
            "Thành tiền":               thanh_tien,
            "Thuế suất GTGT (%)":       "" if thue_suat == "" else int(thue_suat),
            "Tiền thuế GTGT":           tien_thue,
            # Metadata — không ghi vào template
            "__ma_don__":               ma_don,
            "__ghi_chu__":              ghi_chu,
        }
        rows_output.append(row_out)

        # ── Thêm dòng phí ship nếu cấu hình ────────────────────────────────
        if CONFIG["INCLUDE_SHIPPING_FEE"] and not leave_price:
            phi_ship = clean_money(phi_ship_raw)
            if phi_ship > 0:
                stt += 1
                tien_thue_ship = round(phi_ship * thue_suat / 100, 0)
                rows_output.append({
                    **row_out,
                    "Số thứ tự hóa đơn (*)":    stt,
                    "Tên hàng hóa/dịch vụ (*)": CONFIG["SHIPPING_ITEM_NAME"],
                    "Số lượng":                  1.0,
                    "Đơn giá":                   phi_ship,
                    "Thành tiền":                phi_ship,
                    "Tiền thuế GTGT":            tien_thue_ship,
                    "__ghi_chu__":               "Phí vận chuyển",
                })

    df_out = pd.DataFrame(rows_output)
    log.info(f"Tổng số dòng sẽ ghi vào meInvoice: {len(df_out)}")
    return df_out, check_data


# =============================================================================
# 9. write_to_template()
# =============================================================================
def _safe_output_path(output_path: str) -> str:
    """
    Nếu file đang bị khóa (Excel đang mở), tự tạo tên mới có timestamp.
    Trả về đường dẫn có thể ghi được.
    """
    if not os.path.exists(output_path):
        return output_path
    try:
        with open(output_path, "a"):
            pass
        return output_path
    except PermissionError:
        base, ext = os.path.splitext(output_path)
        ts = datetime.now().strftime("%H%M%S")
        new_path = f"{base}_{ts}{ext}"
        log.warning(
            f"File '{os.path.basename(output_path)}' đang mở trong Excel → "
            f"lưu sang '{os.path.basename(new_path)}'"
        )
        log.warning("Đóng Excel rồi chạy lại để ghi đè file cũ.")
        return new_path


def write_to_template(df_out: pd.DataFrame) -> str:
    """
    Ghi dữ liệu vào file mẫu meInvoice, giữ nguyên định dạng.
    Trả về đường dẫn file đã lưu thực tế (có thể khác output_path nếu bị khóa).
    """
    template_path = CONFIG["TEMPLATE_FILE"]
    output_path   = _safe_output_path(CONFIG["OUTPUT_FILE"])
    start_row     = CONFIG["START_ROW"]

    # ── Chuẩn bị cột để ghi (bỏ metadata) ──────────────────────────────────
    write_cols = [c for c in MEINVOICE_COLUMNS if c in df_out.columns]
    df_write = df_out[write_cols].copy()

    # ── Thử ghi vào template nếu có ─────────────────────────────────────────
    if os.path.exists(template_path):
        log.debug(f"Đang ghi vào template: '{template_path}'")
        try:
            # Đọc qua BytesIO để bypass kiểm tra extension của openpyxl
            # (file .xls có thể thực chất là định dạng xlsx bên trong)
            with open(template_path, "rb") as _f:
                wb = load_workbook(io.BytesIO(_f.read()))
            sheet_name = CONFIG["TEMPLATE_SHEET"] or wb.sheetnames[0]
            if sheet_name not in wb.sheetnames:
                log.warning(
                    f"Sheet '{sheet_name}' không có trong template, "
                    f"dùng sheet đầu: '{wb.sheetnames[0]}'"
                )
                sheet_name = wb.sheetnames[0]

            ws = wb[sheet_name]
            log.debug(f"Ghi vào sheet '{sheet_name}', bắt đầu từ dòng {start_row}")

            # Dò tìm dòng header thực sự (quét tối đa 10 dòng đầu)
            header_row, template_headers = _detect_header_row(ws, start_row, df_write.columns)

            if not template_headers:
                log.warning("Không khớp được header template → ghi theo thứ tự cột DataFrame.")
                _write_rows_no_template(ws, df_write, start_row)
            else:
                log.debug(f"Header template tại dòng {header_row}: {list(template_headers.keys())}")
                actual_start = header_row + 1
                _write_rows_with_template(ws, df_write, actual_start, template_headers)

            wb.save(output_path)
            CONFIG["_ACTUAL_OUTPUT"] = output_path
            log.info(f"Đã lưu file output: '{output_path}'")
            return output_path

        except PermissionError:
            log.error("Không ghi được — file đang mở trong Excel. Đóng Excel rồi thử lại.")
            raise
        except Exception as e:
            log.error(f"Lỗi khi ghi vào template: {e}")
            log.info("Fallback: ghi file output không dùng template...")

    # ── Fallback: ghi thẳng bằng pandas ─────────────────────────────────────
    log.info(f"Ghi file output (không dùng template): '{output_path}'")
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_write.to_excel(writer, index=False, sheet_name="meInvoice")
        _auto_format_sheet(writer.sheets["meInvoice"])

    CONFIG["_ACTUAL_OUTPUT"] = output_path
    log.info(f"Đã lưu file output: '{output_path}'")
    return output_path


def _detect_header_row(ws, start_row: int, df_cols) -> tuple[int, dict]:
    """
    Quét tối đa 10 dòng đầu của template để tìm dòng header thực sự.
    Chọn dòng có nhiều ô khớp với tên cột meInvoice nhất.
    """
    df_cols_lower = {c.lower().strip() for c in df_cols}
    best_row, best_headers, best_score = start_row - 1, {}, 0

    for r in range(1, min(11, ws.max_row + 1)):
        headers = {}
        score = 0
        for c in range(1, ws.max_column + 1):
            val = ws.cell(row=r, column=c).value
            if val:
                s = str(val).strip()
                headers[s] = c
                if s.lower().strip() in df_cols_lower:
                    score += 1
        if score > best_score:
            best_score, best_row, best_headers = score, r, headers

    # Nếu không khớp gì thì trả về dict rỗng
    if best_score == 0:
        return start_row - 1, {}
    return best_row, best_headers


def _write_rows_no_template(ws, df_write: pd.DataFrame, start_row: int):
    """Ghi dữ liệu theo thứ tự cột DataFrame từ trái sang."""
    for r_idx, (_, row) in enumerate(df_write.iterrows()):
        for c_idx, val in enumerate(row.values, start=1):
            ws.cell(row=start_row + r_idx, column=c_idx, value=_convert_val(val))


def _write_rows_with_template(
    ws, df_write: pd.DataFrame, start_row: int, template_headers: dict
):
    """Ghi dữ liệu khớp theo tên cột header trong template."""
    for r_idx, (_, row) in enumerate(df_write.iterrows()):
        for col_name, col_idx in template_headers.items():
            # Tìm cột tương ứng trong df_write (khớp không phân biệt hoa thường)
            matched_col = None
            for df_col in df_write.columns:
                if df_col.lower().strip() == col_name.lower().strip():
                    matched_col = df_col
                    break
            val = row.get(matched_col, "") if matched_col else ""
            ws.cell(
                row=start_row + r_idx,
                column=col_idx,
                value=_convert_val(val),
            )


def _convert_val(val):
    """Chuyển đổi giá trị để ghi vào Excel."""
    if pd.isna(val) if isinstance(val, float) else False:
        return ""
    if isinstance(val, str) and val.lower() in ("nan", "none"):
        return ""
    return val


def _auto_format_sheet(ws):
    """Tự động chỉnh độ rộng cột."""
    for col in ws.columns:
        max_len = max(
            (len(str(cell.value)) for cell in col if cell.value is not None),
            default=10
        )
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 50)



# =============================================================================
# 11. main()
# =============================================================================
def main():
    log.info("=" * 65)
    log.info("  PANCAKE → MEINVOICE CONVERTER")
    log.info("=" * 65)

    # ── Bước 1: Đọc file Pancake ─────────────────────────────────────────────
    log.info("\n[BƯỚC 1] Đọc dữ liệu Pancake...")
    df_pancake, pancake_sheet = load_excel(
        CONFIG["PANCAKE_FILE"],
        CONFIG.get("PANCAKE_SHEET") or None,
    )
    total_rows = len(df_pancake)

    # ── Bước 1b: Forward-fill cột đơn hàng xuống dòng sản phẩm con ──────────
    log.debug("\n[BƯỚC 1b] Forward-fill dòng sản phẩm (1 đơn nhiều SP)...")
    df_pancake = forward_fill_order_rows(df_pancake)

    # ── Bước 2: Ánh xạ cột ──────────────────────────────────────────────────
    log.debug("\n[BƯỚC 2] Ánh xạ cột Pancake...")
    col_map = normalize_columns(df_pancake, PANCAKE_COLUMN_MAP)

    # ── Bước 3: Lọc đơn hàng hợp lệ ────────────────────────────────────────
    log.info("\n[BƯỚC 3] Lọc đơn hàng hợp lệ...")
    df_valid, skipped = filter_valid_orders(df_pancake, col_map)
    total_valid = len(df_valid)

    if total_valid == 0:
        log.warning("Không có đơn hàng hợp lệ nào! Kiểm tra lại cột trạng thái và CONFIG.")
        log.warning("Gợi ý: chỉnh VALID_STATUS_KEYWORDS hoặc đặt EXPORT_ALL_IF_NO_STATUS=True")
        df_out = pd.DataFrame(columns=MEINVOICE_COLUMNS)
        write_to_template(df_out)
        return

    # ── Bước 4: Ghép external amounts ───────────────────────────────────────
    log.debug("\n[BƯỚC 4] Ghép dữ liệu external (nếu có)...")
    df_merged = merge_external_amounts(df_valid, col_map)

    # ── Bước 5: Chuyển đổi sang định dạng meInvoice ─────────────────────────
    log.info("\n[BƯỚC 5] Chuyển đổi sang định dạng meInvoice...")
    df_out, check_data = transform_to_meinvoice(df_merged, col_map)
    total_output = len(df_out)

    # ── Kiểm tra giá thuốc bị thiếu ─────────────────────────────────────────
    if check_data["missing_price"]:
        log.error("⛔ DỪNG — Không tìm thấy giá trong bảng thuốc cho các sản phẩm sau:")
        for item in check_data["missing_price"]:
            log.error(f"  • Mã đơn: {item['ma_don']}  |  Dòng {item['dong_excel']}  |  {item['ten_sp']}")
        log.error("Hãy bổ sung tên và giá vào bảng giá thuốc rồi chạy lại.")
        sys.exit(1)

    if check_data["missing_new_name"]:
        log.error("⛔ DỪNG — Cột 'Tên Mới' đang trống cho các sản phẩm sau trong bảng giá:")
        for item in check_data["missing_new_name"]:
            log.error(f"  • Mã đơn: {item['ma_don']}  |  Dòng {item['dong_excel']}  |  {item['ten_sp']}")
        log.error("Hãy bổ sung 'Tên Mới' vào bảng giá thuốc rồi chạy lại.")
        sys.exit(1)

    if check_data["zero_price"]:
        log.error("⛔ DỪNG — Đơn giá đang là 0 cho các sản phẩm sau trong bảng thuốc:")
        for item in check_data["zero_price"]:
            log.error(f"  • Mã đơn: {item['ma_don']}  |  Dòng {item['dong_excel']}  |  {item['ten_sp']}")
        log.error("Hãy nhập đơn giá vào bảng giá thuốc rồi chạy lại.")
        sys.exit(1)

    # ── Bước 6: Ghi ra file output ──────────────────────────────────────────
    log.info("\n[BƯỚC 6] Ghi file output...")
    actual_output = write_to_template(df_out)

    # ── Tóm tắt ─────────────────────────────────────────────────────────────
    log.info("\n" + "=" * 65)
    log.info("  HOÀN THÀNH!")
    log.info(f"  → Tổng đọc:    {total_rows} dòng từ Pancake")
    log.info(f"  → Hợp lệ:      {total_valid} đơn")
    log.info(f"  → Bỏ qua:      {len(skipped)} đơn")
    log.info(f"  → Xuất ra:     {total_output} dòng meInvoice")
    log.info(f"  → File output: {os.path.abspath(actual_output)}")

    if check_data["missing_phone"]:
        log.warning(f"  ⚠  {len(check_data['missing_phone'])} dòng thiếu SĐT")
    if check_data["missing_address"]:
        log.warning(f"  ⚠  {len(check_data['missing_address'])} dòng thiếu địa chỉ")
    if check_data["missing_product"]:
        log.warning(f"  ⚠  {len(check_data['missing_product'])} dòng thiếu tên sản phẩm")
    if check_data["missing_amount"]:
        log.warning(f"  ⚠  {len(check_data['missing_amount'])} dòng thiếu số tiền")
    if check_data["amount_diff"]:
        log.warning(f"  ⚠  {len(check_data['amount_diff'])} dòng chênh lệch tiền")

    # ── So sánh đơn giá×SL (Pancake) vs Thành tiền+Thuế (meInvoice) ─────────
    comparison = check_data.get("order_comparison", {})
    if comparison:
        log.info("\n── So sánh Pancake (đơn giá×SL) vs meInvoice (thành tiền+thuế) ──")
        has_diff = False
        for ma_don, data in comparison.items():
            diff = data["invoice"] - data["pancake"]
            if data["pancake"] == 0 and data["invoice"] == 0:
                continue
            if abs(diff) > 1:
                has_diff = True
                log.warning(
                    f"  {ma_don}  Pancake: {data['pancake']:>12,.0f}"
                    f"  |  meInvoice: {data['invoice']:>12,.0f}"
                    f"  |  Chênh: {diff:>+10,.0f}"
                )
            else:
                log.info(
                    f"  {ma_don}  Pancake: {data['pancake']:>12,.0f}"
                    f"  |  meInvoice: {data['invoice']:>12,.0f}"
                    f"  |  Khớp"
                )
        if has_diff:
            log.warning("⚠ Có đơn chênh lệch — kiểm tra lại bảng giá thuốc.")

    log.info("=" * 65)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    # Đổi working directory về thư mục chứa script
    if getattr(sys, "frozen", False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    main()
