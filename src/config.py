import os
import shutil

from config import (
    BASE_DIR,
    BUNDLED_MODEL_DIR,
    COOKIES_BROWSER,
    FAILED_LINKS_FILE,
    GECKODRIVER_PATH,
    LINKS_FILE,
    MODEL_NAME,
    PROCESSED_LINKS_FILE,
    OUTPUT_VIDEO_DIR,
    OUTPUT_WORD_FILE,
    RESOURCE_DIR,
    WHISPER_MODEL_PATH,
)
from profiles_config import FIREFOX_PROFILE_PATH

_bin_dir = os.path.join(RESOURCE_DIR, "bin")
if os.path.isdir(_bin_dir):
    os.environ["PATH"] = _bin_dir + os.pathsep + os.environ.get("PATH", "")
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

# --- Chống lặp từ (hallucination loop) của Whisper ---
# temperature phải là DÃY, không phải 0. Whisper chỉ tự giải cứu khỏi vòng lặp bằng cách
# giải mã lại ở nhiệt độ cao hơn khi segment không đạt compression_ratio/log_prob threshold.
# Để temperature=0 là tắt hẳn cơ chế này -> segment lặp bị giữ nguyên và nuốt mất 30s tiếng nói.
TEMPERATURE_FALLBACK = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
LOG_PROB_THRESHOLD = -1.0  # Segment tệ hơn mức này -> giải mã lại ở nhiệt độ cao hơn
REPETITION_PENALTY = 1.1  # >1 phạt token đã sinh, chặn vòng lặp ngay từ lúc giải mã
NO_REPEAT_NGRAM_SIZE = 0  # >0 cấm lặp n-gram (4 là hợp lý); 0 = tắt vì có thể hạ nhẹ độ chính xác
MAX_WORD_REPEAT = 3  # Dọn hậu kỳ: giữ tối đa bấy nhiêu lần lặp liên tiếp của một từ

USE_TITLE_MODE = False
MAX_CHUNKS_RUNTIME = DEFAULT_MAX_CHUNKS

TITLE_MODE_SUBMODE = "full"
SKIP_GPT_PROCESSING = False
SRT_TIMESTAMPS = False  # True: mỗi câu một dòng, mốc [HH:MM:SS] ở đầu (checkbox trong GUI)
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
# Model đã nạp, theo tên -> giữ tới khi tắt app. Không bao giờ del/gc một WhisperModel
# đang chạy GPU: ctranslate2 abort tiến trình (0xC0000409) khi hủy model sau khi đã
# nhận diện file dài có temperature fallback -> app "tự tắt" không báo lỗi.
loaded_models = {}
WhisperModel = None
torch = None
compute_type = "int8"
device = "cpu"


def ensure_directories():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
    os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)


def resolve_model(model_name):
    """Prefer the installed model; other selections can use the download cache."""
    local_model = os.path.join(BUNDLED_MODEL_DIR, model_name)
    if os.path.isfile(os.path.join(local_model, "model.bin")):
        return local_model
    return model_name
