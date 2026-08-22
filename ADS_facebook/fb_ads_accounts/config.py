"""Cấu hình fb_ads_accounts.

ACCESS_TOKEN đọc từ file .env ở GỐC repo (GetLinktoText/.env) — KHÔNG hardcode
ở đây nữa: file này được commit lên GitHub, dán token vào đây là lộ. File .env
bị .gitignore che; mẫu ở .env.example.

hub.py / launcher.py chỉ ghi lại hai dòng DATE_PRESET / TIME_RANGE ở cuối file,
mọi dòng khác giữ nguyên.
"""
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _env(name: str) -> str:
    """Đọc một biến trong .env gốc repo — vài dòng tự parse, khỏi cần dotenv."""
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


ACCESS_TOKEN = _env("FB_ADS_ACCOUNTS_TOKEN")
if not ACCESS_TOKEN:
    raise SystemExit(
        f"Thiếu FB_ADS_ACCOUNTS_TOKEN trong {_ENV_FILE}\n"
        "→ mở file đó (tạo từ .env.example nếu chưa có) và dán token vào."
    )

SPREADSHEET_ID = "136z7PajnSu3BhhC-K5N7mZFrEpj2OCk_RX20-aLSjYI"  # ID Google Sheet — lấy từ URL: .../spreadsheets/d/<ID>/edit
DATE_PRESET = "last_month"
TIME_RANGE: dict = {}
