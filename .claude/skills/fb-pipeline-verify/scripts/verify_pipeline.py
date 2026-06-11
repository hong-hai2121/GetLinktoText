#!/usr/bin/env python
"""Phân tích tĩnh bất biến pipeline FB Ads.

Dùng: python verify_pipeline.py <thư-mục-biến-thể>
Vd:   python verify_pipeline.py ADS_facebook/fb_ads_tsAnhDuc

Kiểm tra (tĩnh, không gọi API/Sheets):
  1. get_campaigns.py có COLUMNS + HEADERS dẫn xuất.
  2. get_details.py không chứa .clear() / rewrite toàn sheet.
  3. py_compile mọi file .py trong thư mục.
Trả exit code 0 nếu PASS hết, 1 nếu có FAIL.
"""
import sys
import os
import re
import py_compile

# Console Windows mặc định cp1252 không in được tiếng Việt → ép UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

CHECK = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def check_columns_source(folder, problems):
    gc = os.path.join(folder, "get_campaigns.py")
    if not os.path.exists(gc):
        problems.append(f"{FAIL} Không tìm thấy get_campaigns.py trong {folder}")
        return
    src = read(gc)
    # cho phép type annotation: "COLUMNS: list[...] = ["
    has_columns = re.search(r"^\s*COLUMNS\s*(:[^=\n]+)?=", src, re.M)
    has_headers_derived = re.search(r"HEADERS\s*=\s*\[.*for\s+\w.*\s+in\s+COLUMNS", src)
    has_static_headers = re.search(r"^\s*HEADERS\s*=\s*\[", src, re.M)

    if has_columns:
        # Variant schema-driven (vd fb_ads_tsAnhDuc): COLUMNS là nguồn chân lý.
        print(f"{CHECK} get_campaigns.py định nghĩa COLUMNS (schema-driven)")
        if has_headers_derived:
            print(f"{CHECK} HEADERS dẫn xuất từ COLUMNS")
        else:
            problems.append(
                f"{FAIL} Có COLUMNS nhưng HEADERS không dẫn xuất từ nó "
                f"('HEADERS = [.. for .. in COLUMNS]') — schema không còn single-source"
            )
    elif has_static_headers:
        # Variant kiểu cũ (vd fb_ads_accounts): HEADERS tĩnh, KHÔNG schema-driven.
        print(
            f"{WARN} Variant dùng HEADERS tĩnh, không có COLUMNS schema-driven. "
            f"Đổi cột ở đây phải đồng bộ THỦ CÔNG sang get_details/tong_hop — kiểm kỹ bất biến #5."
        )
    else:
        problems.append(
            f"{FAIL} get_campaigns.py không có cả COLUMNS lẫn HEADERS — không xác định được schema"
        )


def check_phase2_no_clear(folder, problems):
    gd = os.path.join(folder, "get_details.py")
    if not os.path.exists(gd):
        print(f"{WARN} Không có get_details.py trong {folder} — bỏ qua check Phase 2")
        return
    src = read(gd)
    # bỏ comment đơn giản để giảm dương tính giả
    code_lines = [l for l in src.splitlines() if not l.strip().startswith("#")]
    code = "\n".join(code_lines)
    clear_hits = re.findall(r"\.clear\s*\(", code)
    if clear_hits:
        problems.append(
            f"{FAIL} get_details.py gọi .clear() ({len(clear_hits)} lần) — Phase 2 cấm clear, "
            f"phải dùng delete_rows()+insert_rows()"
        )
    else:
        print(f"{CHECK} get_details.py không gọi .clear()")
    if "insert_rows" in code or "delete_rows" in code:
        print(f"{CHECK} get_details.py dùng insert_rows/delete_rows")
    else:
        print(f"{WARN} get_details.py không thấy insert_rows/delete_rows — kiểm tra thủ công")


def check_compile(folder, problems):
    py_files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith(".py")
    ]
    for path in py_files:
        try:
            py_compile.compile(path, doraise=True)
            print(f"{CHECK} biên dịch {os.path.basename(path)}")
        except py_compile.PyCompileError as e:
            problems.append(f"{FAIL} biên dịch {os.path.basename(path)}: {e.msg.strip()}")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    folder = sys.argv[1]
    if not os.path.isdir(folder):
        print(f"{FAIL} Không phải thư mục: {folder}")
        sys.exit(2)

    print(f"== Xác minh pipeline: {folder} ==")
    problems = []
    check_columns_source(folder, problems)
    check_phase2_no_clear(folder, problems)
    check_compile(folder, problems)

    print("\n== Kết quả ==")
    if problems:
        for p in problems:
            print(p)
        print(f"\n{len(problems)} vi phạm — FAIL")
        sys.exit(1)
    print("Tất cả bất biến tĩnh PASS. (Vẫn cần so sánh chéo COLUMNS↔builder thủ công.)")
    sys.exit(0)


if __name__ == "__main__":
    main()
