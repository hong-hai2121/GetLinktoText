# =============================================================================
# convert_misa_xbh.py
# Chuyển đổi Bảng kê chi tiết HĐ từ MISA sang Phiếu Xuất Bán Hàng Liên Tục
# =============================================================================

import io
import os
import re
import sys
import logging
import unicodedata
import warnings
from datetime import datetime, date

import pandas as pd
import xlrd
import xlwt
from xlutils.copy import copy as xl_copy

warnings.filterwarnings("ignore")

# =============================================================================
# CẤU HÌNH
# =============================================================================
CONFIG = {
    # ── Đường dẫn file ──────────────────────────────────────────────────────
    "SOURCE_FILE":   "Bang_ke_chi_tiet_sp từ PM Invoi MISA - Copy.xlsx",
    "TEMPLATE_FILE": "Phieu-Xuat-Ban-Hang-Lien-Tuc.xls",
    "OUTPUT_FILE":   "output_xbh.xls",

    # ── Sheet nguồn MISA ────────────────────────────────────────────────────
    # Để "" để tự tìm sheet đầu tiên
    "SOURCE_SHEET":  "",

    # ── Hàng header trong file nguồn (1-indexed) ────────────────────────────
    # File MISA có header ở hàng 5, dữ liệu từ hàng 6
    "SOURCE_HEADER_ROW": 5,

    # ── Hàng bắt đầu ghi dữ liệu trong template (1-indexed) ────────────────
    # Hàng 1-5 là tiêu đề mẫu, KHÔNG được thay đổi
    "OUTPUT_START_ROW": 6,

    # ── Tài khoản kế toán mặc định ──────────────────────────────────────────
    "TK_NO_TIEN_HANG":  "5111",   # H: TK Nợ / Tiền hàng
    "TK_NO_TIEN_THUE":  "33311",  # I: TK Nợ / Tiền thuế
    "TK_CO_TIEN_HANG":  "131",    # J: TK Có / Tiền hàng
    "TK_NO_GIA_VON":    "632",    # K: TK Nợ / Giá vốn
    "TK_CO_GIAM_TRU":   "156",    # L: TK Có / Giảm trừ

    # ── Kho mặc định ────────────────────────────────────────────────────────
    "MA_KHO":        "K1",  # C: Mã Kho (cột M để trống)

    # ── Thông tin hóa đơn ───────────────────────────────────────────────────
    "NHOM_HD":       "R6",        # Z: Nhóm mã số
    "MAU_SO":        "1",         # AA: Mẫu số

    # ── Ng Nhận hàng mặc định (cột E) ───────────────────────────────────────
    "DEFAULT_NG_NHAN":   "Khách hàng không cung cấp thông tin",

    # ── Tên khách mặc định khi nguồn để trống (cột AF) ──────────────────────
    "DEFAULT_TEN_KHACH": "Khách hàng không cung cấp thông tin",

    # ── Diễn giải cột F (text tĩnh, khác với AH) ────────────────────────────
    "DIEN_GIAI":     "Bán hàng cho khách HĐ:",

    # ── File danh mục hàng hóa để tra Mã HH ────────────────────────────────
    "DM_FILE":       "DM hang hoa.xlsx",

    # ── Lọc trạng thái HĐ ───────────────────────────────────────────────────
    # Chỉ lấy HĐ có trạng thái chứa các từ này
    # Để [] để lấy tất cả
    "VALID_TRANG_THAI": [],

    # ── Bỏ qua HĐ KM (hàng khuyến mãi) ─────────────────────────────────────
    "SKIP_HANG_KM":  False,
}

# =============================================================================
# ÁNH XẠ CỘT NGUỒN → VỊ TRÍ CỘT TRONG TEMPLATE (0-indexed)
# =============================================================================
# Template row 5 headers (0-indexed columns):
#  0:Số C.từ  1:Ngày    2:Mã Kho   3:Mã Khách  4:Ng Nhận hàng  5:Diễn giải
#  6:Mã VV    7:TK Nợ(TH) 8:TK Nợ(TT) 9:TK Có(TH) 10:TK Nợ(GV) 11:TK Có(GT)
# 12:Mã kho  13:Mã HH  14:ĐVT     15:Số lượng 16:Giá Bán    17:%CK
# 18:Tiền CK 19:Tiền hàng 20:Thuế Suất 21:Tiền Thuế 22:Ghi chú  23:Giá Vốn
# 24:Tiền Vốn 25:Nhóm HĐ 26:Mẫu số 27:Ký hiệu  28:Số HĐ    29:Ngày PH
# 30:Mã khách 31:Tên khách 32:MST   33:Diễn giải 34:Tiền hàng 35:Thuế suất
# 36:Tiền thuế 37:Tiền TT 38:Ghi chú

COL_OUT = {
    "so_ct":          0,   # A: Số C.từ ← Số hóa đơn
    "ngay":           1,   # B: Ngày ← Ngày hóa đơn
    "ma_kho":         2,   # C: Mã Kho (config)
    "ma_khach":       3,   # D: Mã Khách ← Mã khách hàng
    "ng_nhan":        4,   # E: Ng Nhận hàng ← Người mua hàng
    "dien_giai":      5,   # F: Diễn giải (computed)
    "ma_vv":          6,   # G: Mã VV (empty)
    "tk_no_th":       7,   # H: TK Nợ Tiền hàng (config)
    "tk_no_tt":       8,   # I: TK Nợ Tiền thuế (config)
    "tk_co_th":       9,   # J: TK Có Tiền hàng (config)
    "tk_no_gv":       10,  # K: TK Nợ Giá vốn (config)
    "tk_co_gt":       11,  # L: TK Có Giảm trừ (config)
    "ma_kho2":        12,  # M: Mã kho (config, same as C)
    "ma_hh":          13,  # N: Mã HH ← Mã hàng
    "dvt":            14,  # O: ĐVT ← ĐVT
    "so_luong":       15,  # P: Số lượng ← Số lượng
    "gia_ban":        16,  # Q: Giá Bán ← Đơn giá
    "ck_pct":         17,  # R: %CK ← Tỷ lệ CK (%)
    "tien_ck":        18,  # S: Tiền CK ← Tiền CK
    "tien_hang":      19,  # T: Tiền hàng ← Thành tiền
    "thue_suat":      20,  # U: Thuế Suất ← Thuế suất (%)
    "tien_thue":      21,  # V: Tiền Thuế ← Tiền thuế GTGT
    "ghi_chu":        22,  # W: Ghi chú ← Ghi chú
    "gia_von":        23,  # X: Giá Vốn (empty)
    "tien_von":       24,  # Y: Tiền Vốn (empty)
    "nhom_hd":        25,  # Z: Nhóm HĐ (config)
    "mau_so":         26,  # AA: Mẫu số (config)
    "ky_hieu":        27,  # AB: Ký hiệu ← Ký hiệu
    "so_hd":          28,  # AC: Số HĐ ← Số hóa đơn
    "ngay_ph":        29,  # AD: Ngày PH ← Ngày hóa đơn
    "ma_khach2":      30,  # AE: Mã khách ← Mã khách hàng
    "ten_khach":      31,  # AF: Tên khách ← Tên khách hàng
    "mst":            32,  # AG: MST ← MST/CCCD
    "dien_giai2":     33,  # AH: Diễn giải (same as F)
    "tien_hang2":     34,  # AI: Tiền hàng ← Thành tiền
    "thue_suat2":     35,  # AJ: Thuế suất ← Thuế suất (%)
    "tien_thue2":     36,  # AK: Tiền thuế ← Tiền thuế GTGT
    "tien_tt":        37,  # AL: Tiền TT ← Tổng tiền TT
    "ghi_chu2":       38,  # AM: Ghi chú ← Ghi chú
}

# =============================================================================
# Logging
# =============================================================================
def _build_log_handlers():
    handlers = []
    # Stream handler — chỉ khi không phải frozen (windowed exe không có stdout)
    if not getattr(sys, "frozen", False):
        try:
            handlers.append(
                logging.StreamHandler(
                    stream=open(sys.stdout.fileno(), mode="w",
                                encoding="utf-8", buffering=1, closefd=False)
                )
            )
        except Exception:
            handlers.append(logging.StreamHandler())
    # File handler — ghi log ra file cạnh exe để debug
    try:
        _log_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
                   else os.path.dirname(os.path.abspath(__file__))
        handlers.append(
            logging.FileHandler(
                os.path.join(_log_dir, "convert_misa_xbh.log"),
                encoding="utf-8", mode="w"
            )
        )
    except Exception:
        pass
    if not handlers:
        handlers.append(logging.NullHandler())
    return handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=_build_log_handlers(),
)
log = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================
def _str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none") else s


def _num(val) -> float:
    """Chuyển giá trị sang số, trả về 0.0 nếu không parse được."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return 0.0 if pd.isna(val) else float(val)
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "-", ""):
        return 0.0
    # Xóa ký tự không phải số, dấu chấm, phẩy, trừ
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return 0.0
    # Xử lý định dạng VN: "1.200.000" hoặc "1,234.56"
    dot_count = s.count(".")
    comma_count = s.count(",")
    try:
        if dot_count > 1:
            s = s.replace(".", "")
            if comma_count == 1:
                s = s.replace(",", ".")
            return float(s)
        elif comma_count > 1:
            return float(s.replace(",", ""))
        elif dot_count == 1 and comma_count == 1:
            if s.index(".") < s.index(","):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
            return float(s)
        elif comma_count == 1:
            return float(s.replace(",", "."))
        else:
            return float(s)
    except (ValueError, TypeError):
        return 0.0


def _parse_pct(val) -> float:
    """Chuyển '8%' hoặc '8' hoặc 0.08 sang 8.0."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return 0.0
        v = float(val)
        # Nếu là dạng thập phân (0.08) → nhân 100
        return round(v * 100, 2) if v < 1 else v
    s = str(val).strip()
    s_clean = re.sub(r"[^\d.]", "", s)
    try:
        return float(s_clean)
    except (ValueError, TypeError):
        return 0.0


def _format_date_str(val) -> str:
    """Chuẩn hóa ngày sang dd/mm/yyyy."""
    if val is None:
        return ""
    if isinstance(val, (datetime, date)):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    # Thử parse các định dạng
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return s



def _normalize_name(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\xa0", " ").replace("\t", " ")
    return " ".join(s.lower().split())


# =============================================================================
# 1b. Danh mục hàng hóa → tra Mã HH
# =============================================================================
def load_dm_file() -> dict:
    """Đọc DM hàng hóa, trả về {tên_hàng_normalized: (mã_hàng, dvt)}."""
    path = CONFIG.get("DM_FILE", "DM hang hoa.xlsx")
    if not os.path.isabs(path):
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, path)

    if not os.path.isfile(path):
        log.warning(f"Không tìm thấy file DM hàng hóa: {path} — cột N, O sẽ để trống")
        return {}

    try:
        df = pd.read_excel(path, engine="openpyxl", dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
    except Exception as e:
        log.error(f"Lỗi đọc DM hàng hóa: {e}")
        return {}

    ma_col = ten_col = dvt_col = None
    for c in df.columns:
        cl = c.lower().strip()
        if ma_col  is None and any(k in cl for k in ("mã hàng", "ma hang", "mã")):
            ma_col  = c
        if ten_col is None and any(k in cl for k in ("tên hàng", "ten hang", "tên")):
            ten_col = c
        if dvt_col is None and "đvt" in cl:
            dvt_col = c

    if not ma_col or not ten_col:
        log.warning(f"DM hàng hóa: không tìm được cột Mã hàng/Tên hàng. Cột: {list(df.columns)}")
        return {}

    dm = {}
    for _, row in df.iterrows():
        ma  = _str(row.get(ma_col,  ""))
        ten = _str(row.get(ten_col, ""))
        dvt = _str(row.get(dvt_col, "")) if dvt_col else ""
        if ma and ten:
            dm[_normalize_name(ten)] = (ma, dvt)

    log.info(f"Đã tải DM hàng hóa: {len(dm)} mặt hàng từ '{os.path.basename(path)}'")
    return dm


def lookup_ma_hh(ten_hang: str, dm_map: dict) -> str:
    """Tìm Mã HH theo tên hàng, không phân biệt hoa/thường, phân biệt chính tả."""
    if not dm_map or not ten_hang:
        return ""
    entry = dm_map.get(_normalize_name(ten_hang))
    return entry[0] if entry else ""


def lookup_dvt(ten_hang: str, dm_map: dict) -> str:
    """Lấy ĐVT từ DM hàng hóa theo tên hàng."""
    if not dm_map or not ten_hang:
        return ""
    entry = dm_map.get(_normalize_name(ten_hang))
    return entry[1] if entry else ""


# =============================================================================
# 1. Đọc file nguồn MISA
# =============================================================================
def load_source(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        raise RuntimeError(f"Không tìm thấy file nguồn: {file_path}")

    with open(file_path, "rb") as f:
        data = f.read()

    header_row = CONFIG["SOURCE_HEADER_ROW"] - 1  # pandas dùng 0-indexed

    # Thử openpyxl (xlsx) trước, nếu lỗi fallback sang xlrd (xls)
    for engine in ("openpyxl", "xlrd"):
        try:
            xl = pd.ExcelFile(io.BytesIO(data), engine=engine)
            sheet_name = CONFIG.get("SOURCE_SHEET", "")
            if not sheet_name or sheet_name not in xl.sheet_names:
                sheet_name = xl.sheet_names[0]

            df = pd.read_excel(
                io.BytesIO(data),
                sheet_name=sheet_name,
                header=header_row,
                engine=engine,
                dtype=str,
            )
            df.columns = [str(c).strip() for c in df.columns]
            df = df.dropna(how="all").reset_index(drop=True)
            log.info(f"Đọc '{os.path.basename(file_path)}' [{engine}]: {len(df)} dòng")
            return df
        except Exception as e:
            if engine == "xlrd":
                raise RuntimeError(f"Không đọc được file nguồn: {e}")
            log.debug(f"openpyxl thất bại ({e}), thử xlrd...")


# =============================================================================
# 2. Tìm cột theo danh sách ứng viên
# =============================================================================
def _find_col(df: pd.DataFrame, candidates: list) -> str | None:
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        real = cols_lower.get(cand.lower().strip())
        if real is not None:
            return real
    return None


def build_col_map(df: pd.DataFrame) -> dict:
    mapping = {
        "ky_hieu":     ["Ký hiệu"],
        "so_hd":       ["Số hóa đơn"],
        "ngay_hd":     ["Ngày hóa đơn"],
        "ma_khach":    ["Mã khách hàng"],
        "ten_khach":   ["Tên khách hàng"],
        "dia_chi":     ["Địa chỉ"],
        "mst":         ["MST/CCCD chủ hộ", "MST/CCCD cá nhân", "MST"],
        "msdk":        ["MSĐVCQHVNS"],
        "nguoi_mua":   ["Người mua hàng"],
        "hinh_thuc_tt":["Hình thức TT"],
        "ma_hang":     ["Mã hàng"],
        "ten_hang":    ["Tên hàng"],
        "quy_cach":    ["Quy cách"],
        "ghi_chu":     ["Ghi chú"],
        "dvt":         ["ĐVT"],
        "so_luong":    ["Số lượng"],
        "don_gia":     ["Đơn giá"],
        "thanh_tien":  ["Thành tiền"],
        "ty_le_ck":    ["Tỷ lệ CK (%)", "Tỷ lệ CK"],
        "tien_ck":     ["Tiền CK"],
        "thue_suat":   ["Thuế suất (%)", "Thuế suất"],
        "tien_thue":   ["Tiền thuế GTGT", "Tiền thuế"],
        "tong_tt":     ["Tổng tiền TT", "Tổng TT"],
        "trang_thai_cqt": ["Trạng thái gửi CQT"],
        "hang_km":     ["Hàng KM"],
        "trang_thai_hd":  ["Trạng thái HĐ"],
    }
    result = {}
    missing = []
    for key, cands in mapping.items():
        col = _find_col(df, cands)
        result[key] = col
        if col is None:
            missing.append(key)
    if missing:
        log.warning(f"Không tìm thấy cột trong file nguồn (sẽ để trống): {missing}")
    return result


# =============================================================================
# 3. Lọc dữ liệu
# =============================================================================
def filter_rows(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    valid_tt = [v.strip().lower() for v in CONFIG.get("VALID_TRANG_THAI", []) if v.strip()]
    skip_km = CONFIG.get("SKIP_HANG_KM", False)

    keep = []
    for idx, row in df.iterrows():
        # Bỏ dòng thiếu Số hóa đơn hoặc Tên hàng
        so_hd_col = col_map.get("so_hd")
        ten_hang_col = col_map.get("ten_hang")
        if so_hd_col and not _str(row.get(so_hd_col)):
            continue
        if ten_hang_col and not _str(row.get(ten_hang_col)):
            continue

        # Lọc trạng thái HĐ
        if valid_tt:
            tt_col = col_map.get("trang_thai_hd")
            tt = _str(row.get(tt_col, "")).lower() if tt_col else ""
            if not any(kw in tt for kw in valid_tt):
                continue

        # Bỏ hàng khuyến mãi
        if skip_km:
            km_col = col_map.get("hang_km")
            km_val = _str(row.get(km_col, "")) if km_col else ""
            if km_val:
                continue

        keep.append(idx)

    df_out = df.loc[keep].copy()
    log.info(f"Sau lọc: {len(df_out)}/{len(df)} dòng hợp lệ")
    return df_out


# =============================================================================
# 4. Chuyển đổi theo nhóm Số C.từ
# =============================================================================
# Quy tắc ghi theo cột:
#   A-G  (0-6)  : chỉ hàng đầu của mỗi nhóm Số C.từ
#   H-Q  (7-16) : đầy đủ mọi hàng
#   R-T  (17-19): luôn trống
#   U    (20)   : đầy đủ mọi hàng (Thuế Suất)
#   Z-AG (25-32): chỉ hàng đầu của mỗi nhóm Số C.từ
#   AH-AM(33-38): chỉ hàng đầu của mỗi nhóm thuế suất trong cùng Số C.từ (gom theo thuế suất)
# =============================================================================

_NHOM_HD_BY_THUE = {5: "R3", 8: "R6"}


def _parse_ma_khach_start(s: str):
    """'HK0001' → ('HK', 1, 4) — prefix, start_num, zero_pad_len. None nếu không hợp lệ."""
    m = re.match(r'^([A-Za-z]*)(\d+)$', s.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2)), len(m.group(2))

def _nhom_hd(ts_key) -> str:
    """Trả về Nhóm HĐ dựa theo thuế suất; fallback về config."""
    if ts_key != "":
        try:
            pct = int(round(float(ts_key)))
            if pct in _NHOM_HD_BY_THUE:
                return _NHOM_HD_BY_THUE[pct]
        except (ValueError, TypeError):
            pass
    return CONFIG.get("NHOM_HD", "")


def transform_groups(df: pd.DataFrame, col_map: dict, dm_map: dict) -> list:
    def g(row, key):
        col = col_map.get(key)
        return _str(row.get(col)) if col else ""

    # ── Gom nhóm liên tiếp theo Số C.từ ─────────────────────────────────────
    groups: list[tuple[str, list]] = []
    for idx, row in df.iterrows():
        so_ct = g(row, "so_hd")
        if groups and groups[-1][0] == so_ct:
            groups[-1][1].append((idx, row))
        else:
            groups.append((so_ct, [(idx, row)]))

    # ── Sinh mã khách tuần tự nếu có MA_KHACH_START ──────────────────────────
    ma_khach_seq: dict[str, str] = {}
    _mk_start = CONFIG.get("MA_KHACH_START", "").strip()
    if _mk_start:
        parsed = _parse_ma_khach_start(_mk_start)
        if parsed:
            _mk_prefix, _mk_num, _mk_pad = parsed
            for i, (so_ct, _) in enumerate(groups):
                ma_khach_seq[so_ct] = f"{_mk_prefix}{str(_mk_num + i).zfill(_mk_pad)}"

    output_rows = []
    missing_dm = []

    for so_ct, row_list in groups:
        # ── Thông tin khách (từ hàng đầu) ───────────────────────────────────
        _, first   = row_list[0]
        so_hd      = g(first, "so_hd")
        ky_hieu    = g(first, "ky_hieu")
        ngay_str   = _format_date_str(g(first, "ngay_hd"))
        ma_khach   = ma_khach_seq.get(so_ct) or g(first, "ma_khach") or "KH00001"
        ten_khach  = g(first, "ten_khach")
        mst        = g(first, "mst")
        ghi_chu_hd = g(first, "ghi_chu")

        ma_kho        = CONFIG.get("MA_KHO", "K1")
        ng_nhan_out   = ten_khach or CONFIG.get("DEFAULT_NG_NHAN",   "Khách hàng không cung cấp thông tin")
        ten_khach_out = ten_khach or CONFIG.get("DEFAULT_TEN_KHACH", "Khách hàng không cung cấp thông tin")
        dien_giai_f   = CONFIG.get("DIEN_GIAI", "Bán hàng cho khách HĐ:")

        # ── Gom nhóm theo thuế suất, giữ thứ tự xuất hiện ──────────────────
        thue_groups: dict = {}
        for idx, row in row_list:
            ts_key = _parse_pct(g(row, "thue_suat"))
            if ts_key is None:
                ts_key = ""
            if ts_key not in thue_groups:
                thue_groups[ts_key] = []
            thue_groups[ts_key].append((idx, row))

        # ── Pre-compute tất cả group summaries (Z, AH-AM) ───────────────────
        group_summaries = []
        for ts_key, ts_rows in thue_groups.items():
            group_summaries.append({
                "nhom_hd":    _nhom_hd(ts_key),
                "dien_giai2": ", ".join(t for t in (g(r, "ten_hang") for _, r in ts_rows) if t),
                "tien_hang2": sum(_num(g(r, "thanh_tien")) for _, r in ts_rows),
                "thue_suat2": ts_key if ts_key != "" else "",
                "tien_thue2": sum(_num(g(r, "tien_thue"))  for _, r in ts_rows),
                "tien_tt":    sum(_num(g(r, "tong_tt"))    for _, r in ts_rows),
                "ghi_chu2":   ghi_chu_hd,
            })

        # ── Điều chỉnh V để sum(V) khớp AK theo từng nhóm thuế suất ───────
        v_adjustments: dict = {}
        for g_idx, (ts_key, ts_rows) in enumerate(thue_groups.items()):
            if not ts_key:
                continue
            ts_float = ts_key / 100.0
            v_per_row = [
                round(_num(g(r, "so_luong")) * _num(g(r, "don_gia")) * ts_float)
                for _, r in ts_rows
            ]
            sum_v = sum(v_per_row)
            tien_thue_ak = round(group_summaries[g_idx]["tien_thue2"])
            lenh = tien_thue_ak - sum_v
            if lenh == 0:
                continue
            if abs(lenh) < 100:
                last_idx, _ = ts_rows[-1]
                v_new = v_per_row[-1] + lenh
                v_adjustments[(ts_key, last_idx)] = v_new
                log.info(
                    f"C.từ '{so_ct}' thuế {ts_key}%: sum(V)={sum_v:,.0f} "
                    f"lệch AK {lenh:+.0f}đ → điều chỉnh V dòng cuối "
                    f"{v_per_row[-1]:,.0f} → {v_new:,.0f}"
                )
            else:
                log.warning(
                    f"C.từ '{so_ct}' thuế {ts_key}%: sum(V)={sum_v:,.0f} "
                    f"lệch AK {lenh:+.0f}đ >= 100đ — KHÔNG điều chỉnh V"
                )

        # ── Ghi từng dòng ────────────────────────────────────────────────────
        # Z và AH-AM dùng doc_row_idx để lấy summary → dồn liên tiếp từ hàng đầu
        doc_row_idx = 0
        for ts_key, ts_rows in thue_groups.items():
            for j, (row_idx, row) in enumerate(ts_rows):
                is_first_doc = (doc_row_idx == 0)
                summary = group_summaries[doc_row_idx] if doc_row_idx < len(group_summaries) else None

                ten_hang  = g(row, "ten_hang")
                dvt       = lookup_dvt(ten_hang, dm_map)
                so_luong  = _num(g(row, "so_luong"))
                don_gia   = _num(g(row, "don_gia"))
                thue_suat = _parse_pct(g(row, "thue_suat"))

                ma_hh = lookup_ma_hh(ten_hang, dm_map)
                if not ma_hh and ten_hang:
                    excel_row = row_idx + CONFIG["SOURCE_HEADER_ROW"] + 1
                    missing_dm.append((ten_hang, excel_row))

                row_data = {
                    # ── A-G: chỉ hàng đầu chứng từ ──────────────────────────
                    "so_ct":     so_hd          if is_first_doc else "",  # A
                    "ngay":      ngay_str       if is_first_doc else "",  # B
                    "ma_kho":    ma_kho         if is_first_doc else "",  # C
                    "ma_khach":  ma_khach       if is_first_doc else "",  # D
                    "ng_nhan":   ng_nhan_out    if is_first_doc else "",  # E
                    "dien_giai": dien_giai_f    if is_first_doc else "",  # F
                    "ma_vv":     "",                                       # G
                    # ── H-Q: đầy đủ mọi hàng ─────────────────────────────────
                    "tk_no_th":  CONFIG.get("TK_NO_TIEN_HANG", ""),  # H
                    "tk_no_tt":  CONFIG.get("TK_NO_TIEN_THUE", ""),  # I
                    "tk_co_th":  CONFIG.get("TK_CO_TIEN_HANG", ""),  # J
                    "tk_no_gv":  CONFIG.get("TK_NO_GIA_VON",   ""),  # K
                    "tk_co_gt":  CONFIG.get("TK_CO_GIAM_TRU",  ""),  # L
                    "ma_kho2":   "",                                   # M
                    "ma_hh":     ma_hh,                               # N
                    "dvt":       dvt,                                  # O
                    "so_luong":  so_luong,                            # P
                    "gia_ban":   don_gia,                             # Q
                    # ── R-T: luôn trống ──────────────────────────────────────
                    "ck_pct":    "",  # R
                    "tien_ck":   "",  # S
                    "tien_hang": "",  # T
                    # ── U: đầy đủ mọi hàng ───────────────────────────────────
                    "thue_suat": thue_suat if thue_suat else "",  # U
                    # ── V: P×Q×U%, dòng cuối mỗi nhóm điều chỉnh để sum(V)=AK ──
                    "tien_thue": v_adjustments.get(
                        (ts_key, row_idx),
                        round(so_luong * don_gia * (thue_suat / 100)) if thue_suat else ""
                    ),  # V
                    "ghi_chu":   "",  # W
                    "gia_von":   "",  # X
                    "tien_von":  "",  # Y
                    # ── Z: dồn lên theo doc_row_idx ──────────────────────────
                    "nhom_hd":    summary["nhom_hd"]    if summary else "",  # Z
                    # ── AA-AG: chỉ hàng đầu chứng từ ────────────────────────
                    "mau_so":    CONFIG.get("MAU_SO",  "")  if is_first_doc else "",  # AA
                    "ky_hieu":   ky_hieu                    if is_first_doc else "",  # AB
                    "so_hd":     so_hd                      if is_first_doc else "",  # AC
                    "ngay_ph":   ngay_str                   if is_first_doc else "",  # AD
                    "ma_khach2": ma_khach                   if is_first_doc else "",  # AE
                    "ten_khach": ten_khach_out              if is_first_doc else "",  # AF
                    "mst":       mst                        if is_first_doc else "",  # AG
                    # ── AH-AM: dồn lên theo doc_row_idx ─────────────────────
                    "dien_giai2": summary["dien_giai2"] if summary else "",  # AH
                    "tien_hang2": summary["tien_hang2"] if summary else "",  # AI
                    "thue_suat2": summary["thue_suat2"] if summary else "",  # AJ
                    "tien_thue2": summary["tien_thue2"] if summary else "",  # AK
                    "tien_tt":    summary["tien_tt"]    if summary else "",  # AL
                    "ghi_chu2":   summary["ghi_chu2"]   if summary else "",  # AM
                }
                output_rows.append(row_data)
                doc_row_idx += 1

    if missing_dm:
        by_name: dict = {}
        for name, row_num in missing_dm:
            by_name.setdefault(name, []).append(row_num)
        parts = [f"  • '{name}'  →  dòng Excel {', '.join(str(r) for r in row_nums)}"
                 for name, row_nums in sorted(by_name.items())]
        msg = (
            f"Không tìm thấy Mã HH cho {len(by_name)} tên hàng trong Danh mục.\n"
            f"Vui lòng bổ sung vào file DM trước khi xuất:\n"
            + "\n".join(parts)
        )
        log.error(msg)
        raise RuntimeError(msg)

    return output_rows


# =============================================================================
# 5. Ghi ra file output (xlwt, dựa vào template)
# =============================================================================
def _safe_output_path(output_path: str) -> str:
    if not os.path.exists(output_path):
        return output_path
    base, ext = os.path.splitext(output_path)
    counter = 1
    while True:
        new_path = f"{base} ({counter}){ext}"
        if not os.path.exists(new_path):
            log.info(f"File đã tồn tại → lưu sang '{os.path.basename(new_path)}'")
            return new_path
        counter += 1


def write_output(rows_data: list, template_path: str, output_path: str) -> str:
    output_path = _safe_output_path(output_path)
    start_row = CONFIG["OUTPUT_START_ROW"] - 1  # 0-indexed

    if not os.path.exists(template_path):
        raise RuntimeError(f"Không tìm thấy file template: {template_path}")

    # Đọc template với formatting
    rb = xlrd.open_workbook(template_path, formatting_info=True)
    wb = xl_copy(rb)
    ws = wb.get_sheet(0)

    # Style mặc định cho ô dữ liệu
    default_style = xlwt.XFStyle()
    num_style = xlwt.XFStyle()
    num_style.num_format_str = "#,##0"
    date_style = xlwt.XFStyle()
    date_style.num_format_str = "DD/MM/YYYY"

    for r_idx, row_data in enumerate(rows_data):
        xlwt_row = start_row + r_idx
        for field_key, col_idx in COL_OUT.items():
            val = row_data.get(field_key, "")
            _write_cell(ws, xlwt_row, col_idx, val, num_style, default_style)

    try:
        wb.save(output_path)
        log.info(f"Đã lưu: '{output_path}'")
        return output_path
    except PermissionError:
        log.error("Không ghi được — file đang mở. Đóng file rồi thử lại.")
        raise


def _write_cell(ws, row: int, col: int, val, num_style, str_style):
    if val is None or val == "":
        ws.write(row, col, "", str_style)
        return
    if isinstance(val, float):
        if val == 0.0:
            ws.write(row, col, "", str_style)
        else:
            ws.write(row, col, val, num_style)
    elif isinstance(val, int):
        if val == 0:
            ws.write(row, col, "", str_style)
        else:
            ws.write(row, col, val, num_style)
    else:
        ws.write(row, col, str(val), str_style)


# =============================================================================
# 6. main()
# =============================================================================
def main():
    log.info("=" * 65)
    log.info("  MISA → PHIẾU XUẤT BÁN HÀNG LIÊN TỤC")
    log.info("=" * 65)

    source_path   = CONFIG["SOURCE_FILE"]
    template_path = CONFIG["TEMPLATE_FILE"]
    output_path   = CONFIG["OUTPUT_FILE"]

    # Bước 1: Đọc file nguồn
    log.info("[1] Đọc file nguồn MISA...")
    df = load_source(source_path)

    # Bước 2: Ánh xạ cột
    log.info("[2] Ánh xạ cột...")
    col_map = build_col_map(df)

    # Bước 3: Lọc dữ liệu
    log.info("[3] Lọc dữ liệu...")
    df = filter_rows(df, col_map)

    if len(df) == 0:
        raise RuntimeError("Không có dòng dữ liệu nào hợp lệ sau khi lọc!")

    # Bước 4: Tải danh mục hàng hóa
    log.info("[4] Tải danh mục hàng hóa...")
    dm_map = load_dm_file()

    # Bước 5: Chuyển đổi theo nhóm Số C.từ
    log.info("[5] Chuyển đổi dữ liệu (nhóm theo Số C.từ)...")
    rows_data = transform_groups(df, col_map, dm_map)

    log.info(f"Tổng {len(rows_data)} dòng sẽ ghi vào output")

    # Bước 6: Ghi file output
    log.info("[6] Ghi file output...")
    actual_output = write_output(rows_data, template_path, output_path)
    CONFIG["_ACTUAL_OUTPUT"] = actual_output

    log.info("=" * 65)
    log.info("  HOÀN THÀNH!")
    log.info(f"  → Nhóm HĐ: {sum(1 for r in rows_data if r.get('so_ct'))}")
    log.info(f"  → Dòng ghi: {len(rows_data)}")
    log.info(f"  → File output:  {os.path.abspath(actual_output)}")
    log.info("=" * 65)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    main()
