import os
import shutil

from config import (
    BASE_DIR,
    GECKODRIVER_PATH,
    LINKS_FILE,
    MODEL_NAME,
    OUTPUT_VIDEO_DIR,
    OUTPUT_WORD_FILE,
    WHISPER_MODEL_PATH,
)
from profiles_config import FIREFOX_PROFILE_PATH

FFMPEG_PATH = shutil.which("ffmpeg")

CHUNK_LENGTH_MS = 3 * 60 * 1000  # 3 phút/đoạn
DEFAULT_MAX_CHUNKS = 2  # Mặc định nhận diện 5 đoạn đầu

USE_TITLE_MODE = False
MAX_CHUNKS_RUNTIME = DEFAULT_MAX_CHUNKS

TITLE_MODE_SUBMODE = "full"

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
whisper = None
torch = None
device = "cpu"


def ensure_directories():
    os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
    os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
