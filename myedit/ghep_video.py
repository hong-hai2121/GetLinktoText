# -*- coding: utf-8 -*-
"""Bước 4 — Ghép ảnh + audio thành video hoàn chỉnh bằng ffmpeg.

Mỗi cảnh là 1 ảnh có hiệu ứng Ken Burns (zoom vào / zoom ra xen kẽ),
nối lại rồi ghép audio gốc vào.

Cách chạy:  python ghep_video.py mau/canh.json mau/audio_mau.m4a
Kết quả  :  mau/video_ra.mp4 (1080p25, libx264 crf 18 — ưu tiên chất lượng)
Clip từng cảnh cache ở mau/clips/ — chạy lại chỉ render cảnh còn thiếu,
muốn render lại từ đầu thì thêm --lam-lai.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FPS = 25
W, H = 1920, 1080
ZOOM_MAX = 1.12


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def render_canh(anh: Path, clip: Path, dur: float, zoom_vao: bool) -> None:
    frames = max(1, round(dur * FPS))
    buoc = (ZOOM_MAX - 1.0) / frames
    if zoom_vao:
        z = f"min(1+{buoc:.6f}*on,{ZOOM_MAX})"
    else:
        z = f"max({ZOOM_MAX}-{buoc:.6f}*on,1.0)"
    loc = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
        f"crop={W * 2}:{H * 2},"
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p"
    )
    _ff("-i", str(anh), "-filter_complex", loc,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(clip))


def ghep_video(canh_json: Path, audio: Path, ra: Path | None = None,
               lam_lai: bool = False) -> Path:
    du_lieu = json.loads(canh_json.read_text(encoding="utf-8"))
    goc = canh_json.parent
    thu_muc_anh = goc / "anh"
    thu_muc_clip = goc / "clips"
    thu_muc_clip.mkdir(exist_ok=True)
    ra = ra or goc / "video_ra.mp4"

    canh = du_lieu["canh"]
    for i, c in enumerate(canh):
        anh = thu_muc_anh / f"canh_{c['tt']:03d}.jpg"
        clip = thu_muc_clip / f"canh_{c['tt']:03d}.mp4"
        if not anh.exists():
            raise FileNotFoundError(f"Thiếu ảnh {anh} — chạy tai_anh.py trước")
        if lam_lai or not clip.exists():
            dur = c["ket_thuc"] - c["bat_dau"]
            render_canh(anh, clip, dur, zoom_vao=(i % 2 == 0))
            print(f"  🎬 cảnh {c['tt']:3d}/{len(canh)} ({dur:.1f}s)")

    danh_sach = goc / "danhsach_clip.txt"
    dong = []
    for c in canh:
        clip = thu_muc_clip / f"canh_{c['tt']:03d}.mp4"
        dong.append(f"file '{clip.as_posix()}'")
    danh_sach.write_text("\n".join(dong), encoding="utf-8")

    # audio AAC/M4A thì copy nguyên vẹn, định dạng khác thì mã hóa lại AAC
    ma_audio = ["-c:a", "copy"] if audio.suffix.lower() in {".m4a", ".aac", ".mp4"} \
        else ["-c:a", "aac", "-b:a", "192k"]
    _ff("-f", "concat", "-safe", "0", "-i", str(danh_sach), "-i", str(audio),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", *ma_audio,
        "-shortest", "-movflags", "+faststart", str(ra))
    print(f"✅ Video hoàn chỉnh → {ra}")
    return ra


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ghép ảnh + audio thành video")
    ap.add_argument("canh", help="đường dẫn canh.json")
    ap.add_argument("audio", help="file audio giọng nói")
    ap.add_argument("--ra", help="file video xuất ra (mặc định mau/video_ra.mp4)")
    ap.add_argument("--lam-lai", action="store_true", help="render lại mọi cảnh")
    a = ap.parse_args()
    ghep_video(Path(a.canh).resolve(), Path(a.audio).resolve(),
               Path(a.ra).resolve() if a.ra else None, a.lam_lai)
