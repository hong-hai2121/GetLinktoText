import os
import shutil

from config import (
    BASE_DIR,
    COOKIES_BROWSER,
    GECKODRIVER_PATH,
    LINKS_FILE,
    MODEL_NAME,
    PROCESSED_LINKS_FILE,
    OUTPUT_VIDEO_DIR,
    OUTPUT_WORD_FILE,
    WHISPER_MODEL_PATH,
)
from profiles_config import FIREFOX_PROFILE_PATH

FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

CHUNK_LENGTH_MS = 3 * 60 * 1000  # 3 phút/đoạn
DEFAULT_MAX_CHUNKS = 2  # Mặc định nhận diện 5 đoạn đầu

# Ngôn ngữ nhận diện: "auto" = dò theo audio, hoặc mã ngôn ngữ Whisper ("vi", "en", ...)
TRANSCRIBE_LANGUAGE = "auto"
DEFAULT_LANGUAGE = "vi"  # Dùng khi dò ngôn ngữ thất bại hoặc độ tin cậy thấp
LANGUAGE_DETECT_MIN_PROB = 0.5  # Ngưỡng cho tiếng Việt / tiếng Anh
LANGUAGE_DETECT_OTHER_MIN_PROB = 0.85  # Ngôn ngữ lạ phải chắc hơn mới nhận (tránh audio nhiễu)
LANGUAGE_PROMPTS = {
    "vi": "Đây là nội dung tiếng Việt.",
    "en": "This is English content.",
}
LANGUAGE_LABELS = {
    "auto": "Tự động nhận diện",
    "vi": "Tiếng Việt",
    "en": "Tiếng Anh",
}

USE_TITLE_MODE = False
MAX_CHUNKS_RUNTIME = DEFAULT_MAX_CHUNKS

TITLE_MODE_SUBMODE = "full"
SKIP_GPT_PROCESSING = False
SKIP_LONG_VIDEOS = False
LONG_VIDEO_THRESHOLD_SECONDS = 15 * 60

# Tắt chuyển model khi phát hiện lặp từ (đặt True để bật lại)
ENABLE_MODEL_SWITCH_ON_REPEAT = False

# Tắt tự động mở Firefox khi khởi động (đặt True để bật lại)
AUTO_LAUNCH_FIREFOX = False

CHECK_TITLE_BLACKLIST = False  # Đổi thành False nếu không muốn kiểm tra tiêu đề True
BLACKLIST_KEYWORDS2 = [
    "da căng bóng",
    "sáng da",
    "da trẻ",
    "da bóng",
    "sạch da",
    "da",
    "nám",
    "nấm",
    "n.ấm",
    "n ấm",
    "n .ấm",
    "nám",
    "n .ám",
    "n ám",
    "n.ám",
    "mụn",
    "m .ụn",
    "m ụn",
    "m.ụn",
    "serum",
    "skincare",
    "tẩy trang",
]

BLACKLIST_KEYWORDS = []

# runtime state
model = None
model2 = None
WhisperModel = None
torch = None
compute_type = "int8"
device = "cpu"


def ensure_directories():
    os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
    os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
