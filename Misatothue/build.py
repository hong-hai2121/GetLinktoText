import subprocess
import shutil
import os

# Luôn làm việc trong thư mục chứa build.py
os.chdir(os.path.dirname(os.path.abspath(__file__)))

PYTHON312 = r"C:\Users\PC\AppData\Local\Programs\Python\Python312\python.exe"
BUILD_VENV = os.path.join(os.getcwd(), "build_env")
BUILD_PY   = os.path.join(BUILD_VENV, "Scripts", "python.exe")

APP_NAME = "MisaXuatBanHang"
dist_dir = os.path.join(os.getcwd(), "dist", APP_NAME)

# ── Luôn xóa build_env cũ để tạo sạch ──────────────────────────────────────
if os.path.exists(BUILD_VENV):
    print("=== Xoa venv cu ===")
    shutil.rmtree(BUILD_VENV)

print("=== Tao venv build voi Python 3.12 ===")
subprocess.run([PYTHON312, "-m", "venv", BUILD_VENV], check=True)
subprocess.run([BUILD_PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
subprocess.run([BUILD_PY, "-m", "pip", "install", "--quiet",
                "pyinstaller",
                "pandas",
                "openpyxl",
                "xlrd==2.0.1",
                "xlwt==1.3.0",
                "xlutils==2.0.0"], check=True)

print("=== Dong goi ===")
subprocess.run([
    BUILD_PY, "-m", "PyInstaller",
    "--onedir",
    "--windowed",
    "--noconfirm",
    "--name", APP_NAME,
    "--hidden-import=convert_misa_xbh",
    "--hidden-import=openpyxl",
    "--hidden-import=xlrd",
    "--hidden-import=xlwt",
    "--hidden-import=xlutils",
    "--hidden-import=xlutils.copy",
    "--hidden-import=difflib",
    "--hidden-import=unicodedata",
    "--collect-all=xlutils",
    "--clean",
    "gui_misa_xbh.py"
], check=True)

print("=== Sao chep file du lieu ===")
SKIP = {"build_env"}
for f in os.listdir("."):
    if f in SKIP:
        continue
    if f.endswith(".xlsx") or f.endswith(".xls"):
        shutil.copy(f, dist_dir)
        print("  Copied:", f.encode("ascii", errors="replace").decode())

print()
print("XONG! Thu muc:", os.path.abspath(dist_dir))
