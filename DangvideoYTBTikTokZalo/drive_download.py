# -*- coding: utf-8 -*-
"""Tải video từ link Google Drive (file chia sẻ công khai) về thư mục Downloads."""
import re
import time
from pathlib import Path

import requests

DOWNLOADS = Path.home() / "Downloads"


def extract_drive_id(url: str):
    """Rút file-id từ các dạng link Drive thường gặp."""
    patterns = [
        r"/file/d/([A-Za-z0-9_-]{20,})",
        r"[?&]id=([A-Za-z0-9_-]{20,})",
        r"/uc\?.*id=([A-Za-z0-9_-]{20,})",
        r"^([A-Za-z0-9_-]{20,})$",  # dán thẳng file-id
    ]
    for p in patterns:
        m = re.search(p, url.strip())
        if m:
            return m.group(1)
    return None


def _unique_path(folder: Path, name: str) -> Path:
    """Chống trùng tên file (kể cả trùng trong cùng một giây)."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    path = folder / name
    i = 1
    while path.exists():
        path = folder / (f"{stem} ({i})." + ext if ext else f"{stem} ({i})")
        i += 1
    return path


def download_drive(url: str, log=print) -> str:
    """Tải file Drive về Downloads, trả về đường dẫn file local."""
    file_id = extract_drive_id(url)
    if not file_id:
        raise ValueError(f"Không nhận ra file-id trong link Drive: {url}")

    log(f"Đang tải từ Google Drive (id={file_id})...")
    sess = requests.Session()
    dl_url = "https://drive.usercontent.google.com/download"
    params = {"id": file_id, "export": "download", "confirm": "t"}
    r = sess.get(dl_url, params=params, stream=True, timeout=60)
    r.raise_for_status()

    # Nếu trả về trang HTML xác nhận (file lớn chưa quét virus) -> lấy token trong form
    ctype = r.headers.get("Content-Type", "")
    if "text/html" in ctype:
        html = r.text
        form_inputs = dict(re.findall(
            r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html))
        if not form_inputs:
            raise RuntimeError(
                "Drive không cho tải trực tiếp — kiểm tra file đã bật chia sẻ "
                "'Bất kỳ ai có đường liên kết' chưa.")
        r.close()
        r = sess.get(dl_url, params=form_inputs, stream=True, timeout=60)
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "text/html" in ctype:
            raise RuntimeError("Drive vẫn trả về trang web thay vì file — link có thể cần đăng nhập.")

    # Tên file từ Content-Disposition
    name = f"drive_{file_id}.mp4"
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="([^"]+)"', cd)
    if m:
        name = requests.utils.unquote(m.group(1))

    dest = _unique_path(DOWNLOADS, name)
    total = int(r.headers.get("Content-Length") or 0)
    done = 0
    last_log = time.time()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 512):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                if time.time() - last_log > 3:
                    if total:
                        log(f"  ... {done/1048576:.0f}/{total/1048576:.0f} MB ({done*100//total}%)")
                    else:
                        log(f"  ... {done/1048576:.0f} MB")
                    last_log = time.time()
    log(f"✓ Đã tải về: {dest} ({done/1048576:.1f} MB)")
    return str(dest)
