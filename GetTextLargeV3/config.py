import os
import sys


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# ── Vị trí thư mục (hỗ trợ cả chạy .py lẫn bản đóng gói PyInstaller) ───────────
# FROZEN=True khi chạy từ .exe do PyInstaller build.
#   RES_DIR = nơi chứa TÀI NGUYÊN đóng gói (model, ffmpeg, geckodriver) — chỉ đọc.
#   APP_DIR = thư mục chứa .exe — nơi GHI output/link (cạnh .exe cho dễ thấy).
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    APP_DIR = os.path.dirname(sys.executable)
else:
    RES_DIR = os.path.abspath(os.path.dirname(__file__))
    APP_DIR = RES_DIR

BASE_DIR = _env("BASE_DIR", APP_DIR)

# ── File dữ liệu / kết quả (ghi cạnh .exe hoặc thư mục dự án) ──────────────────
LINKS_FILE = _env("LINKS_FILE", os.path.join(BASE_DIR, "linkgettoText.txt"))
PROCESSED_LINKS_FILE = _env(
    "PROCESSED_LINKS_FILE",
    os.path.join(BASE_DIR, "processed_links.txt"),
)
# Chạy trực tiếp GetTextFromLink.py -> final_result.docx.
# Chạy qua shortcut .lnk (run_lnk.pyw) -> file riêng do launcher đặt biến môi trường OUTPUT_WORD_FILE.
OUTPUT_WORD_FILE = _env("OUTPUT_WORD_FILE", os.path.join(BASE_DIR, "final_result.docx"))
OUTPUT_VIDEO_DIR = _env("OUTPUT_VIDEO_DIR", os.path.join(BASE_DIR, "output_videos"))

# ── Model Whisper (large-v3) ──────────────────────────────────────────────────
# Dự án chỉ dùng model large-v3, KHÔNG dùng turbo/medium.
#
# Engine nhận diện, chọn qua TRANSCRIBE_ENGINE:
#   "faster" (mặc định)  -> faster-whisper (CTranslate2), tự dò GPU/CPU.
#                           GPU: cuda + float16 | CPU: cpu + int8. Dùng cho bản .exe portable.
#   "openai"             -> openai-whisper nạp thẳng file large-v3.pt (chính xác, cần torch).
TRANSCRIBE_ENGINE = _env("TRANSCRIBE_ENGINE", "faster")

# Tài nguyên model đọc từ RES_DIR (bundle) khi đóng gói.
WHISPER_MODEL_PATH = _env("WHISPER_MODEL_PATH", os.path.join(RES_DIR, "whisper_cache"))
# Thư mục model large-v3 định dạng CTranslate2 (dùng cho engine "faster").
FW_MODEL_DIR = _env(
    "FW_MODEL_DIR", os.path.join(RES_DIR, "models", "faster-whisper-large-v3")
)
# File checkpoint OpenAI-Whisper large-v3.pt (dùng cho engine "openai").
WHISPER_MODEL_FILE = _env(
    "WHISPER_MODEL_FILE", os.path.join(WHISPER_MODEL_PATH, "large-v3.pt")
)
# Tên hiển thị (chỉ để thông tin).
MODEL_NAME = _env("MODEL_NAME", "large-v3")

# geckodriver đóng gói cạnh tài nguyên (chỉ cần khi bật chế độ ChatGPT/Firefox).
GECKODRIVER_PATH = _env("GECKODRIVER_PATH", os.path.join(RES_DIR, "geckodriver.exe"))
# Browser to use for yt-dlp cookie extraction ("chrome", "firefox", "edge", etc.)
COOKIES_BROWSER = _env("COOKIES_BROWSER", "firefox")
