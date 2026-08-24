# -*- coding: utf-8 -*-
"""Bước 3 — Tải ảnh minh họa cho từng cảnh trong canh.json.

Nguồn ảnh (thử lần lượt, nguồn nào có key thì dùng):
  - Pexels   (PEXELS_API_KEY trong .env)  — miễn phí 200 lượt/giờ
  - Pixabay  (PIXABAY_API_KEY trong .env) — miễn phí 100 lượt/phút
  - Openverse — không cần key nhưng giới hạn chặt, chỉ làm phao cứu hộ
Cảnh nào không tìm được ảnh → tự vẽ thẻ chữ (nền tối + tóm tắt cảnh) để
video không bị thủng lỗ.

Cách chạy:  python tai_anh.py mau/canh.json
Kết quả  :  mau/anh/canh_001.jpg, canh_002.jpg, ... (1920x1080, đã crop)
"""
import argparse
import io
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests
from PIL import Image, ImageDraw, ImageFont

from cauhinh import key

KICH_THUOC = (1920, 1080)
UA = {"User-Agent": "myedit/1.0 (personal video tool)"}
_da_dung: set[str] = set()  # URL đã dùng — tránh 2 cảnh trùng 1 ảnh


def _chon_moi(urls: list[str]) -> str | None:
    for u in urls:
        if u and u not in _da_dung:
            _da_dung.add(u)
            return u
    return None


def tim_pexels(q: str) -> str | None:
    r = requests.get("https://api.pexels.com/v1/search",
                     headers={"Authorization": key("PEXELS_API_KEY"), **UA},
                     params={"query": q, "per_page": 5, "orientation": "landscape"},
                     timeout=30)
    r.raise_for_status()
    return _chon_moi([p["src"]["large2x"] for p in r.json().get("photos", [])])


def tim_pixabay(q: str) -> str | None:
    r = requests.get("https://pixabay.com/api/",
                     params={"key": key("PIXABAY_API_KEY"), "q": q,
                             "image_type": "photo", "orientation": "horizontal",
                             "per_page": 5}, headers=UA, timeout=30)
    r.raise_for_status()
    return _chon_moi([h["largeImageURL"] for h in r.json().get("hits", [])])


def tim_openverse(q: str) -> str | None:
    r = requests.get("https://api.openverse.org/v1/images/",
                     params={"q": q, "page_size": 5}, headers=UA, timeout=30)
    r.raise_for_status()
    return _chon_moi([h["url"] for h in r.json().get("results", [])])


def tim_anh(q: str) -> str | None:
    """Thử từng nguồn theo thứ tự ưu tiên, nguồn lỗi thì bỏ qua."""
    nguon = []
    if key("PEXELS_API_KEY"):
        nguon.append(("pexels", tim_pexels))
    if key("PIXABAY_API_KEY"):
        nguon.append(("pixabay", tim_pixabay))
    nguon.append(("openverse", tim_openverse))
    for ten, ham in nguon:
        try:
            url = ham(q)
            if url:
                return url
        except Exception as e:
            print(f"    ⚠️ {ten}: {e}")
    return None


def cover_crop(anh: Image.Image) -> Image.Image:
    """Phóng + cắt giữa cho vừa khít 1920x1080."""
    w, h = KICH_THUOC
    ti_le = max(w / anh.width, h / anh.height)
    anh = anh.resize((round(anh.width * ti_le), round(anh.height * ti_le)),
                     Image.LANCZOS)
    x = (anh.width - w) // 2
    y = (anh.height - h) // 2
    return anh.crop((x, y, x + w, y + h))


def the_chu(canh: dict) -> Image.Image:
    """Thẻ chữ thay thế khi không tìm được ảnh."""
    w, h = KICH_THUOC
    anh = Image.new("RGB", KICH_THUOC, (24, 28, 40))
    ve = ImageDraw.Draw(anh)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    chu = canh.get("y_chinh") or canh["tu_khoa_anh"]
    # bẻ dòng thô theo độ rộng
    dong, hang = [], ""
    for tu in chu.split():
        thu = (hang + " " + tu).strip()
        if ve.textlength(thu, font=font) > w - 300:
            dong.append(hang)
            hang = tu
        else:
            hang = thu
    dong.append(hang)
    y = h / 2 - len(dong) * 42
    for d in dong:
        ve.text((w / 2, y), d, font=font, fill=(235, 238, 245), anchor="mm")
        y += 84
    return anh


def tai_anh(canh_json: Path) -> Path:
    du_lieu = json.loads(canh_json.read_text(encoding="utf-8"))
    thu_muc = canh_json.parent / "anh"
    thu_muc.mkdir(exist_ok=True)

    thieu = 0
    for c in du_lieu["canh"]:
        ra = thu_muc / f"canh_{c['tt']:03d}.jpg"
        if ra.exists():
            continue
        url = tim_anh(c["tu_khoa_anh"])
        if url is None:  # thử rút gọn từ khóa còn 2 từ đầu
            url = tim_anh(" ".join(c["tu_khoa_anh"].split()[:2]))
        try:
            if url:
                r = requests.get(url, headers=UA, timeout=60)
                r.raise_for_status()
                anh = cover_crop(Image.open(io.BytesIO(r.content)).convert("RGB"))
                print(f"  🖼️ cảnh {c['tt']:3d}: {c['tu_khoa_anh']}")
            else:
                raise ValueError("không có kết quả")
        except Exception as e:
            anh = the_chu(c)
            thieu += 1
            print(f"  📝 cảnh {c['tt']:3d}: dùng thẻ chữ ({e})")
        anh.save(ra, "JPEG", quality=88)
        time.sleep(0.4)  # lịch sự với API

    print(f"✅ Ảnh nằm ở {thu_muc}" + (f" — {thieu} cảnh dùng thẻ chữ" if thieu else ""))
    return thu_muc


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tải ảnh minh họa cho các cảnh")
    ap.add_argument("canh", help="đường dẫn canh.json")
    a = ap.parse_args()
    tai_anh(Path(a.canh).resolve())
