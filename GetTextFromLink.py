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
    main()
