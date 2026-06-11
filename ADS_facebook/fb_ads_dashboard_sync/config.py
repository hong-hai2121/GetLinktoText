"""
Cấu hình tập trung — đọc biến môi trường từ file .env.

Biến bắt buộc:
    META_ACCESS_TOKEN            Access token Meta Marketing API (quyền ads_read)
    META_AD_ACCOUNT_ID          ID tài khoản quảng cáo (có/không tiền tố act_)
    GOOGLE_SHEET_ID             ID Google Sheet làm database tạm
    GOOGLE_SERVICE_ACCOUNT_JSON Đường dẫn file JSON service account

Biến tùy chọn:
    FB_API_VERSION              Phiên bản Graph API (mặc định v20.0)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent

# Nạp .env nằm cùng thư mục dự án (không ghi đè biến môi trường đã đặt sẵn).
load_dotenv(BASE_DIR / ".env")

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json"
).strip()
FB_API_VERSION = os.getenv("FB_API_VERSION", "v20.0").strip()

# Scope tối thiểu để gspread đọc/ghi Sheet.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def service_account_path() -> Path:
    """Trả về đường dẫn tuyệt đối tới file service account (hỗ trợ path tương đối)."""
    p = Path(GOOGLE_SERVICE_ACCOUNT_JSON)
    return p if p.is_absolute() else (BASE_DIR / p)


def account_id_normalized() -> str:
    """ID tài khoản dạng act_xxx (Graph API yêu cầu tiền tố act_)."""
    acc = META_AD_ACCOUNT_ID
    return acc if acc.startswith("act_") else f"act_{acc}"


def account_id_bare() -> str:
    """ID tài khoản KHÔNG tiền tố act_ (để ghi vào cột account_id của Sheet)."""
    return META_AD_ACCOUNT_ID.removeprefix("act_")


def validate() -> None:
    """Kiểm tra biến môi trường bắt buộc; raise nếu thiếu để dừng sớm rõ ràng."""
    missing = [
        name
        for name, value in (
            ("META_ACCESS_TOKEN", META_ACCESS_TOKEN),
            ("META_AD_ACCOUNT_ID", META_AD_ACCOUNT_ID),
            ("GOOGLE_SHEET_ID", GOOGLE_SHEET_ID),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Thiếu biến môi trường bắt buộc trong .env: " + ", ".join(missing)
        )
    sa = service_account_path()
    if not sa.exists():
        raise RuntimeError(
            f"Không tìm thấy file service account: {sa}. "
            "Đặt GOOGLE_SERVICE_ACCOUNT_JSON trỏ đúng file JSON."
        )
