import os


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


BASE_DIR = _env("BASE_DIR", os.path.abspath(os.path.dirname(__file__)))
LINKS_FILE = _env("LINKS_FILE", os.path.join(BASE_DIR, "linkgettoText.txt"))
PROCESSED_LINKS_FILE = _env(
    "PROCESSED_LINKS_FILE",
    os.path.join(BASE_DIR, "processed_links.txt"),
)
OUTPUT_WORD_FILE = _env("OUTPUT_WORD_FILE", os.path.join(BASE_DIR, "final_result.docx"))
WHISPER_MODEL_PATH = _env("WHISPER_MODEL_PATH", os.path.join(BASE_DIR, "whisper_cache"))
OUTPUT_VIDEO_DIR = _env("OUTPUT_VIDEO_DIR", os.path.join(BASE_DIR, "output_videos"))
MODEL_NAME = _env("MODEL_NAME", "medium")
GECKODRIVER_PATH = _env(
    "GECKODRIVER_PATH", r"D:\\Python\\GetLinktoText\\geckodriver.exe"
)
