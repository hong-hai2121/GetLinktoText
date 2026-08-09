from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = PROJECT_DIR / "packaging" / "build_installer.ps1"


def main() -> int:
    if not SCRIPT_PATH.is_file():
        print(f"Khong tim thay file build: {SCRIPT_PATH}")
        return 1

    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT_PATH),
    ]
    return subprocess.call(command, cwd=PROJECT_DIR)


if __name__ == "__main__":
    sys.exit(main())
