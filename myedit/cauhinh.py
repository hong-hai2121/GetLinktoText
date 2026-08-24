# -*- coding: utf-8 -*-
"""Cấu hình chung cho myedit — đường dẫn và key đọc từ .env ở gốc repo."""
import os
from pathlib import Path

GOC_MYEDIT = Path(__file__).resolve().parent           # .../GetLinktoText/myedit
GOC_REPO = GOC_MYEDIT.parent                            # .../GetLinktoText
WHISPER_CACHE = GOC_REPO / "whisper_cache"
MAU_DIR = GOC_MYEDIT / "mau"

try:
    from dotenv import load_dotenv
    load_dotenv(GOC_REPO / ".env")
except ImportError:
    pass


def key(ten: str) -> str:
    """Lấy key từ biến môi trường, trả về chuỗi rỗng nếu chưa khai."""
    return (os.environ.get(ten) or "").strip()
