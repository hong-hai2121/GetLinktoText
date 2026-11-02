from src.runtime import prepare_runtime

prepare_runtime()

from config import (
    BASE_DIR,
    GECKODRIVER_PATH,
    LINKS_FILE,
    MODEL_NAME,
    OUTPUT_VIDEO_DIR,
    OUTPUT_WORD_FILE,
    WHISPER_MODEL_PATH,
)
from src.gui import GetTextApp
from src.main import launch_gui, main


def retry(func, max_attempts=3):
    import time

    for attempt in range(max_attempts):
        try:
            return func()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2**attempt)  # exponential backoff


if __name__ == "__main__":
    import multiprocessing
    import sys

    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from src.diagnostics import run_self_test

        raise SystemExit(run_self_test(sys.argv[2]))
    try:
        main()
    except Exception:
        import traceback
        from tkinter import messagebox

        traceback.print_exc()
        messagebox.showerror("GetTextFromLink", "Không thể mở phần mềm.\n\n" + traceback.format_exc())
        raise
