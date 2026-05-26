import subprocess
import shutil
import os
import sys

PYTHON312 = r"C:\Users\PC\AppData\Local\Programs\Python\Python312\python.exe"
BUILD_VENV = os.path.join(os.path.dirname(__file__), "build_env")
BUILD_PY   = os.path.join(BUILD_VENV, "Scripts", "python.exe")

dist_dir = os.path.join("dist", "PancakeToMeInvoice")

# ── Tạo venv sạch với Python 3.12 (python.org) nếu chưa có ──────────────────
if not os.path.exists(BUILD_PY):
    print("=== Tao venv build voi Python 3.12 ===")
    subprocess.run([PYTHON312, "-m", "venv", BUILD_VENV], check=True)
    subprocess.run([BUILD_PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([BUILD_PY, "-m", "pip", "install", "--quiet",
                    "pyinstaller", "pandas", "openpyxl", "python-dateutil"], check=True)
else:
    print("=== Dung venv build san co ===")
    subprocess.run([BUILD_PY, "-m", "pip", "install", "--quiet", "pyinstaller"], check=True)

print("=== Dong goi ===")
subprocess.run([
    BUILD_PY, "-m", "PyInstaller",
    "--onedir",
    "--windowed",
    "--noconfirm",
    "--name", "PancakeToMeInvoice",
    "--hidden-import=convert_pancake_to_meinvoice",
    "--hidden-import=dateutil.parser",
    "--hidden-import=openpyxl",
    "--clean",
    "gui.py"
], check=True)

print("=== Sao chep file du lieu ===")
for f in os.listdir("."):
    if f.endswith(".xlsx") or f.endswith(".xls"):
        shutil.copy(f, dist_dir)
        print("  Copied:", f.encode("ascii", errors="replace").decode())

print()
print("XONG! Thu muc:", os.path.abspath(dist_dir))
