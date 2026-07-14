# -*- coding: utf-8 -*-
"""
Xem chỉ số quảng cáo Facebook từ file Excel (chạy hoàn toàn offline).

CÁCH DÙNG:
    - Nhấp đúp file này (hoặc: python xem_ads.py) -> mở THẲNG giao diện web trước;
      trong web bấm "Thêm file .xlsx" hoặc kéo–thả để nạp NHIỀU FILE / NHIỀU TÀI KHOẢN,
      xem gộp chung (mỗi file = 1 tài khoản, có cột "Tài khoản/Nguồn").
    - Kéo file .xlsx thả lên xem_ads.py (hoặc: python xem_ads.py "duong_dan.xlsx")
      -> nạp sẵn file đó (sinh report.html) rồi vẫn thêm file khác được trong web.

Giao diện (index.html) đọc Excel ngay trong trình duyệt bằng SheetJS.
"""
import os
import sys
import json
import datetime
import webbrowser

try:  # để in được tiếng Việt trên console Windows (cp1252)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "index.html")
OUTPUT = os.path.join(HERE, "report.html")


def doc_bang(path):
    """Đọc file -> (headers, rows). Tự chọn sheet nhiều dữ liệu nhất và dò dòng tiêu đề."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        import csv
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            aoa = [list(r) for r in csv.reader(f)]
        return tach_tieu_de(aoa)

    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    best_aoa, best_score = None, -1
    for ws in wb.worksheets:
        aoa = [list(r) for r in ws.iter_rows(values_only=True)]
        score = sum(1 for row in aoa for c in row if c not in (None, ""))
        if score > best_score:
            best_score, best_aoa = score, aoa
    wb.close()
    return tach_tieu_de(best_aoa or [])


def _blank(v):
    return v is None or v == ""


def tach_tieu_de(aoa):
    """Tìm dòng tiêu đề (chứa 'chiến dịch'/'campaign') rồi tách headers + rows."""
    hr = 0
    for i, row in enumerate(aoa[:15]):
        joined = "|".join(str(c).lower() for c in row if c is not None)
        if "chiến dịch" in joined or "campaign" in joined or "tên nhóm" in joined:
            hr = i
            break
    else:
        for i, row in enumerate(aoa):
            if sum(1 for c in row if not _blank(c)) >= 3:
                hr = i
                break

    headers = [("" if c is None else str(c).strip()) for c in (aoa[hr] if aoa else [])]
    while headers and headers[-1] == "":       # bỏ cột trống ở cuối
        headers.pop()
    n = len(headers)

    rows = []
    for row in aoa[hr + 1:]:
        if not any(not _blank(c) for c in row):
            continue
        rows.append([_chuan_hoa(row[i]) if i < len(row) else "" for i in range(n)])
    return headers, rows


def _chuan_hoa(v):
    """Chuyển giá trị ô thành kiểu JSON được (số giữ nguyên, ngày -> chuỗi)."""
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def sinh_html(headers, rows, nguon):
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()

    data = {"headers": headers, "rows": rows, "source": os.path.basename(nguon)}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    inject = "window.IMPORTED_DATA = %s;" % payload

    marker = "/*__INJECT_DATA__*/"
    if marker in html:
        html = html.replace(marker, inject, 1)
    else:  # phòng khi template đổi: chèn trước </script> cuối
        html = html.rsplit("</script>", 1)
        html = ("<script>" + inject + "</script>\n</script>").join(html) if len(html) == 2 else "".join(html)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    return OUTPUT


def main():
    if not os.path.isfile(TEMPLATE):
        print("[Lỗi] Không tìm thấy index.html cạnh file này."); return

    # Có file truyền vào (kéo–thả lên .py hoặc CLI) -> nạp sẵn file đó rồi mở.
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        path = sys.argv[1]
        print("Đang đọc:", path)
        try:
            headers, rows = doc_bang(path)
        except Exception as e:
            print("[Lỗi] Không đọc được file:", e); return
        if not headers:
            print("[Lỗi] File không có dữ liệu."); return
        out = sinh_html(headers, rows, path)
        print("Đã tạo:", out, "(%d dòng, %d cột)" % (len(rows), len(headers)))
        target = out
    else:
        # Không có file: mở thẳng giao diện web trước; thêm file (nhiều tài khoản) ngay trong web.
        print("Mở giao diện web — bấm 'Thêm file .xlsx' hoặc kéo–thả để nạp (chọn được nhiều file/nhiều tài khoản).")
        target = TEMPLATE

    webbrowser.open("file:///" + target.replace("\\", "/"))
    print("Đã mở webview trong trình duyệt.")


if __name__ == "__main__":
    main()
