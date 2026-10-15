# -*- coding: utf-8 -*-
"""Liệt kê và tải một thư mục Google Drive công khai, KHÔNG dùng gdown.

gdown tải dồn vài thư mục liên tiếp là Drive trả "Access denied" / "Cannot retrieve the public link"
cho mọi file. Hai đường dưới đây vẫn chạy được lúc đó:
  - liệt kê:  https://drive.google.com/embeddedfolderview?id=<id thư mục>  (HTML đơn giản: id + tên file
              + tên thư mục ở <title>)
  - tải file: https://drive.usercontent.google.com/download?id=<id file>&export=download&confirm=t
Tên file lấy từ danh sách (Unicode đầy đủ) nên không bị mất dấu như khi tải bằng curl trong Git Bash.
Lỗi mạng / bị chặn tạm thời thì tự thử lại (chờ 20s, 40s ...).
"""
from __future__ import annotations

import html
import re
import time
from pathlib import Path
from typing import Callable

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
LIST_URL = "https://drive.google.com/embeddedfolderview"
DL_URL = "https://drive.usercontent.google.com/download"
KY_TU_CAM = '<>:"/\\|?*'                 # ký tự Windows không cho dùng trong tên file


class DriveLoi(RuntimeError):
    pass


def folder_id(link: str) -> str | None:
    """Rút id thư mục từ link Drive (…/folders/<id>, ?id=<id>) hoặc id dán thẳng.
    Link Sheet/Docs/file lẻ -> None (tool cần THƯ MỤC chứa đủ bộ file)."""
    s = (link or "").strip()
    if not s or "docs.google.com" in s or "/file/d/" in s:
        return None
    for p in (r"/folders/([A-Za-z0-9_-]{20,})", r"[?&]id=([A-Za-z0-9_-]{20,})", r"^([A-Za-z0-9_-]{20,})$"):
        m = re.search(p, s)
        if m:
            return m.group(1)
    return None


def liet_ke(fid: str, timeout: float = 30) -> tuple[str, list[tuple[str, str]]]:
    """-> (tên thư mục, [(id file, tên file), ...]). Bỏ qua thư mục con."""
    r = requests.get(LIST_URL, params={"id": fid}, headers=UA, timeout=timeout)
    if r.status_code == 404:
        raise DriveLoi("Không thấy thư mục (sai link hoặc chưa chia sẻ 'Bất kỳ ai có đường liên kết').")
    r.raise_for_status()
    t = r.text
    files = [(m.group(1), html.unescape(m.group(2)).strip())
             for m in re.finditer(r'<a href="https://drive\.google\.com/file/d/([\w-]+)/view[^"]*"[^>]*>.*?'
                                  r'<div class="flip-entry-title">(.*?)</div>', t, re.S)]
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    ten = html.unescape(m.group(1)).strip() if m else ""
    if not files and "flip-entries" not in t:
        raise DriveLoi("Drive không trả danh sách file (thư mục chưa chia sẻ công khai?).")
    return ten, files


def ten_an_toan(name: str) -> str:
    return "".join("_" if c in KY_TU_CAM or ord(c) < 32 else c for c in name).strip(" .") or "file"


def _cho(giay: float, dung: Callable[[], bool] | None) -> bool:
    """Ngủ từng 0,5s; trả True nếu bị yêu cầu dừng giữa chừng."""
    het = time.time() + giay
    while time.time() < het:
        if dung and dung():
            return True
        time.sleep(0.5)
    return False


def _mo_luong_tai(sess: requests.Session, file_id: str) -> requests.Response:
    r = sess.get(DL_URL, params={"id": file_id, "export": "download", "confirm": "t"},
                 headers=UA, stream=True, timeout=(20, 120))
    r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type", ""):
        # file lớn: trang "chưa quét virus" có form ẩn -> gửi lại với các trường của form
        form = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', r.text))
        r.close()
        if not form:
            raise DriveLoi("Drive trả trang web thay vì file (bị giới hạn lượt tải hoặc chưa chia sẻ).")
        r = sess.get(DL_URL, params=form, headers=UA, stream=True, timeout=(20, 120))
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", ""):
            r.close()
            raise DriveLoi("Drive vẫn trả trang web thay vì file.")
    return r


def tai_file(sess: requests.Session, file_id: str, dest: Path, log: Callable[[str], None] = print,
             so_lan: int = 3, dung: Callable[[], bool] | None = None) -> int:
    """Tải 1 file về dest (ghi .part rồi đổi tên). Lỗi thì thử lại tới so_lan lần. -> số byte."""
    for lan in range(1, so_lan + 1):
        tmp = dest.with_name(dest.name + ".part")
        try:
            with _mo_luong_tai(sess, file_id) as r, open(tmp, "wb") as f:
                n = 0
                for chunk in r.iter_content(chunk_size=1 << 19):
                    if dung and dung():
                        raise DriveLoi("đã dừng theo yêu cầu")
                    f.write(chunk)
                    n += len(chunk)
            if n == 0:
                raise DriveLoi("file tải về rỗng")
            tmp.replace(dest)
            return n
        except Exception as e:
            tmp.unlink(missing_ok=True)
            if lan == so_lan or (dung and dung()):
                raise
            cho = 20 * lan
            log(f"    lỗi tải {dest.name}: {e} -> thử lại sau {cho}s ({lan}/{so_lan - 1})")
            if _cho(cho, dung):
                raise DriveLoi("đã dừng theo yêu cầu")
    return 0


def tai_thu_muc(link: str, dest: Path, log: Callable[[str], None] = print,
                dung: Callable[[], bool] | None = None) -> tuple[str, list[Path]]:
    """Tải mọi file của thư mục Drive về dest (tạo mới). -> (tên thư mục trên Drive, [file đã tải])."""
    fid = folder_id(link)
    if not fid:
        raise DriveLoi(f"Không phải link thư mục Drive: {link}")
    ten, files = liet_ke(fid)
    if not files:
        raise DriveLoi(f"Thư mục '{ten or fid}' trống.")
    dest.mkdir(parents=True, exist_ok=True)
    log(f"  Thư mục Drive '{ten}': {len(files)} file -> {dest}")
    sess = requests.Session()
    ket_qua = []
    for i, (file_id, name) in enumerate(files, 1):
        p = dest / ten_an_toan(name)
        n = tai_file(sess, file_id, p, log=log, dung=dung)
        log(f"    [{i}/{len(files)}] {p.name} ({n / 1048576:.2f} MB)")
        ket_qua.append(p)
    return ten, ket_qua


if __name__ == "__main__":                       # thử nhanh: python drive_thu_muc.py <link> [thư mục đích]
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        sys.exit("Cách dùng: python drive_thu_muc.py <link thư mục Drive> [thư mục đích]")
    if len(sys.argv) > 2:
        print(tai_thu_muc(sys.argv[1], Path(sys.argv[2])))
    else:
        print(liet_ke(folder_id(sys.argv[1]) or ""))
