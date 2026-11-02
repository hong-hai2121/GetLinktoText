"""Initialize writable paths and logging for the installed Windows application."""
import os
import sys


def prepare_runtime():
    if not getattr(sys, "frozen", False):
        return
    from config import BASE_DIR, RESOURCE_DIR

    os.makedirs(BASE_DIR, exist_ok=True)
    bin_dir = os.path.join(RESOURCE_DIR, "bin")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    # Libraries such as yt-dlp need usable streams even in a windowed executable.
    if sys.stdout is None or sys.stderr is None:
        log_path = os.path.join(BASE_DIR, "application.log")
        if os.path.isfile(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024:
            os.replace(log_path, log_path + ".1")
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r")
