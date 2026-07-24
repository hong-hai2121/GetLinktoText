import os
import shutil

from config import (
    BASE_DIR,
    COOKIES_BROWSER,
    FW_MODEL_DIR,
    GECKODRIVER_PATH,
    LINKS_FILE,
    MODEL_NAME,
    PROCESSED_LINKS_FILE,
    OUTPUT_VIDEO_DIR,
    OUTPUT_WORD_FILE,
    RES_DIR,
    TRANSCRIBE_ENGINE,
    WHISPER_MODEL_FILE,
    WHISPER_MODEL_PATH,
)
from profiles_config import FIREFOX_PROFILE_PATH


def _find_binary(name: str) -> str | None:
    """Tìm ffmpeg/ffprobe: ưu tiên bản đóng gói cạnh tài nguyên, sau đó PATH hệ thống."""
    exe = name + (".exe" if os.name == "nt" else "")
    for cand in (os.path.join(RES_DIR, exe), os.path.join(RES_DIR, "bin", exe)):
        if os.path.isfile(cand):
            return cand
    return shutil.which(name)


FFMPEG_PATH = _find_binary("ffmpeg")
FFPROBE_PATH = _find_binary("ffprobe")

CHUNK_LENGTH_MS = 3 * 60 * 1000  # 3 phút/đoạn
DEFAULT_MAX_CHUNKS = 2  # Mặc định nhận diện 5 đoạn đầu

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
model = None          # model đang dùng (faster-whisper WhisperModel hoặc openai-whisper)
model2 = None         # không dùng — giữ để tương thích code dọn bộ nhớ
WhisperModel = None   # class faster_whisper.WhisperModel (gán khi engine="faster")
whisper = None        # module openai-whisper (gán khi engine="openai")
torch = None          # None nếu môi trường không có torch (bản .exe portable)
compute_type = "int8"  # "float16" khi chạy GPU, "int8" khi chạy CPU
device = "cpu"        # "cuda" khi có GPU, ngược lại "cpu"


def empty_cuda_cache():
    """Giải phóng cache VRAM nếu đang chạy GPU và có torch. No-op ở bản portable/CPU."""
    if device == "cuda" and torch is not None:
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass


def ensure_directories():
    os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
