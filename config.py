import os
import sys


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


IS_FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
_default_base = (
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GetTextFromLink")
    if IS_FROZEN else RESOURCE_DIR
)
BASE_DIR = os.path.abspath(_env("BASE_DIR", _default_base))
BUNDLED_MODEL_DIR = os.path.join(RESOURCE_DIR, "models")
LINKS_FILE = _env("LINKS_FILE", os.path.join(BASE_DIR, "linkgettoText.txt"))
PROCESSED_LINKS_FILE = _env(
    "PROCESSED_LINKS_FILE",
    os.path.join(BASE_DIR, "processed_links.txt"),
)
# Link không lấy được nội dung — xem/lấy lại ở tab "Link chưa lấy" trên GUI
FAILED_LINKS_FILE = _env(
    "FAILED_LINKS_FILE",
    os.path.join(BASE_DIR, "failed_links.txt"),
)
# Chạy trực tiếp GetTextFromLink.py -> final_result.docx.
# Chạy qua shortcut .lnk (GetTextFromLink.bat) -> file riêng do .bat đặt biến môi trường OUTPUT_WORD_FILE.
OUTPUT_WORD_FILE = _env("OUTPUT_WORD_FILE", os.path.join(BASE_DIR, "final_result.docx"))
WHISPER_MODEL_PATH = _env("WHISPER_MODEL_PATH", os.path.join(BASE_DIR, "whisper_cache"))
OUTPUT_VIDEO_DIR = _env("OUTPUT_VIDEO_DIR", os.path.join(BASE_DIR, "output_videos"))
MODEL_NAME = _env("MODEL_NAME", "large-v3-turbo")
GECKODRIVER_PATH = _env(
    "GECKODRIVER_PATH", os.path.join(RESOURCE_DIR, "bin", "geckodriver.exe")
    if IS_FROZEN else os.path.join(RESOURCE_DIR, "geckodriver.exe")
)
# Browser to use for yt-dlp cookie extraction ("chrome", "firefox", "edge", etc.)
COOKIES_BROWSER = _env("COOKIES_BROWSER", "firefox")
