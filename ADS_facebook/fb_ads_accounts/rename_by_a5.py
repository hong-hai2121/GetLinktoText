"""
Đổi tên file Excel/CSV theo nội dung ô A5.

Chức năng:
  • Đọc ô A5 (dòng 5, cột A) của file Excel (.xlsx/.xlsm) hoặc CSV.
  • Đổi tên CHÍNH file đó thành nội dung ô A5 (đã làm sạch ký tự Windows cấm),
    giữ nguyên phần đuôi (.xlsx / .csv ...).
  • Nếu tên đích đã tồn tại → thêm ' (1)', ' (2)'... để KHÔNG ghi đè file khác.
    Chạy lại trên file đã đúng tên thì giữ nguyên (không nhân bản).

Dùng:
    python rename_by_a5.py <file1> [file2 ...]   # đổi tên các file chỉ định
    python rename_by_a5.py                         # mở hộp thoại chọn file
"""

import csv
import sys
from pathlib import Path

# Ký tự Windows cấm trong tên file
_INVALID = set('\\/:*?"<>|')


def read_a5(path: Path) -> str:
    """Giá trị ô A5 (dòng 5, cột A). Rỗng nếu file không đủ 5 dòng."""
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise RuntimeError("Cần cài openpyxl để đọc .xlsx:  pip install openpyxl")
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            val = wb.active["A5"].value
        finally:
            wb.close()
        return "" if val is None else str(val)

    if ext == ".csv":
        for enc in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                with open(path, encoding=enc, newline="") as f:
                    for i, row in enumerate(csv.reader(f)):
                        if i == 4:                     # dòng 5 (0-based = 4)
                            return row[0] if row else ""
                return ""                              # ít hơn 5 dòng
            except UnicodeDecodeError:
                continue
        return ""

    raise RuntimeError(f"Định dạng không hỗ trợ: {ext} (chỉ .xlsx/.xlsm/.csv)")


def sanitize(name: str) -> str:
    """Bỏ ký tự Windows cấm, gộp khoảng trắng, bỏ dấu '.'/' ' ở cuối."""
    cleaned = "".join(" " if c in _INVALID else c for c in (name or ""))
    cleaned = " ".join(cleaned.split())               # gộp khoảng trắng thừa
    return cleaned.rstrip(". ")                        # Windows cấm kết thúc '.'/' '


def unique_target(path: Path, base: str) -> Path:
    """Đường dẫn đích không trùng file KHÁC. base+ext, kẹt thì 'base (1)', 'base (2)'...
    Cho phép trùng CHÍNH file hiện tại (để chạy lại không nhân bản)."""
    directory, ext, keep = path.parent, path.suffix, path.resolve()
    cand = directory / f"{base}{ext}"
    i = 1
    while cand.exists() and cand.resolve() != keep:
        cand = directory / f"{base} ({i}){ext}"
        i += 1
    return cand


def rename_by_a5(path: Path) -> Path:
    """Đổi tên file theo ô A5. Trả về đường dẫn mới (hoặc cũ nếu đã đúng tên)."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"Không thấy file: {path}")
    base = sanitize(read_a5(path))
    if not base:
        raise RuntimeError("Ô A5 rỗng hoặc không có ký tự hợp lệ để đặt tên.")
    target = unique_target(path, base)
    if target.resolve() != path.resolve():
        path.rename(target)
    return target


def _pick_files() -> list[Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return []
    root = tk.Tk()
    root.withdraw()
    files = filedialog.askopenfilenames(
        title="Chọn file Excel/CSV để đổi tên theo ô A5",
        filetypes=[("Excel/CSV", "*.xlsx *.xlsm *.csv"), ("Tất cả", "*.*")],
    )
    root.destroy()
    return [Path(f) for f in files]


def main(argv: list[str]) -> None:
    paths = [Path(a) for a in argv] or _pick_files()
    if not paths:
        print("Không có file nào được chọn.")
        return
    for p in paths:
        try:
            new = rename_by_a5(p)
            if new.resolve() == p.resolve():
                print(f"=  {p.name}   (đã đúng tên, giữ nguyên)")
            else:
                print(f"✓  {p.name}   →   {new.name}")
        except Exception as e:
            print(f"✗  {p.name}: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
