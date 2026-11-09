# -*- coding: utf-8 -*-
"""Đổi video sang .mp4 cho hàng đợi đăng — Zalo chỉ nhận .mp4 (user 09/11/2026), YouTube/TikTok nhận mp4 là chắc nhất.

dam_bao_mp4(path, log) -> đường dẫn file .mp4 dùng để đăng:
  - đã là .mp4 -> trả nguyên.
  - cạnh file gốc đã có <tên>.mp4 đọc được (ffprobe ra thời lượng) -> dùng lại, không đổi lần nữa
    (kể cả khi file gốc đã bị xoá: hàng đợi cũ trỏ .webm, người dùng đã tự đổi sang .mp4).
  - hình H.264/HEVC + tiếng AAC/MP3 (thường là .mov/.mkv/.m4v) -> chỉ đổi vỏ (-c copy), vài giây.
  - còn lại (.webm VP9/AV1 + Opus...) -> mã hóa lại H.264: thử GPU NVENC -> Intel QSV -> AMD AMF -> CPU libx264.
  Ghi ra <tên>.mp4.part rồi đổi tên khi xong; file gốc giữ nguyên.

Chạy riêng:  python doi_mp4.py "video.webm" ["video2.mov" ...]
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# (tên encoder trong ffmpeg, tham số) theo thứ tự ưu tiên; libx264 luôn có.
BO_MA_HOA = (
    ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-b:v", "0",
                    "-maxrate", "12M", "-bufsize", "24M", "-profile:v", "high"]),
    ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "medium", "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M",
                  "-profile:v", "high"]),
    ("h264_amf", ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak", "-b:v", "8M", "-maxrate", "10M",
                  "-bufsize", "16M", "-profile:v", "high"]),
    ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high"]),
)
TEN_MA_HOA = {"h264_nvenc": "GPU NVIDIA NVENC", "h264_qsv": "GPU Intel Quick Sync", "h264_amf": "GPU AMD AMF",
              "libx264": "CPU libx264"}
HINH_GIU_NGUYEN = ("h264", "hevc")            # mp4 chứa được -> chỉ đổi vỏ
TIENG_GIU_NGUYEN = ("aac", "mp3", None)
_ENC_CACHE = {}
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _exe(ten):
    p = shutil.which(ten)
    if not p:
        raise RuntimeError(f"Chưa cài {ten} (cần ffmpeg để đổi video sang .mp4).")
    return p


def thong_tin(path):
    """{'vcodec','acodec','width','height','giay','dinh_dang'} qua ffprobe; file hỏng/không đọc được -> None."""
    try:
        out = subprocess.run([_exe("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                             capture_output=True, timeout=120, creationflags=_FLAGS).stdout
        d = json.loads(out.decode("utf-8", "replace") or "{}")
    except Exception:
        return None
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    try:
        giay = float((d.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        giay = 0.0
    if v is None or giay <= 0:
        return None
    return {"vcodec": v.get("codec_name"), "acodec": a.get("codec_name") if a else None,
            "width": v.get("width"), "height": v.get("height"), "giay": giay,
            "dinh_dang": (d.get("format") or {}).get("format_name", "")}


def _thu_ma_hoa(ffmpeg, ten):
    """Encoder `ten` có trong ffmpeg VÀ mã hóa thử 0,2 giây thành công (driver GPU chạy được). Nhớ trong phiên."""
    if ten in _ENC_CACHE:
        return _ENC_CACHE[ten]
    ok = ten == "libx264"
    if not ok:
        try:
            if "danh_sach" not in _ENC_CACHE:
                _ENC_CACHE["danh_sach"] = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                                         timeout=30, creationflags=_FLAGS).stdout.decode("utf-8", "replace")
            if ten in _ENC_CACHE["danh_sach"]:
                t = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2:r=30",
                                    "-c:v", ten, "-f", "null", "-"], capture_output=True, timeout=60, creationflags=_FLAGS)
                ok = t.returncode == 0
        except Exception:
            ok = False
    _ENC_CACHE[ten] = ok
    return ok


def _chay(args, timeout):
    r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_FLAGS)
    loi = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return r.returncode == 0, (loi[-1] if loi else f"ffmpeg thoát mã {r.returncode}")


def dam_bao_mp4(path, log=print):
    """Trả về đường dẫn .mp4 để đăng (xem đầu file). Lỗi -> ném RuntimeError/FileNotFoundError."""
    src = Path(str(path).strip().strip('"'))
    if src.suffix.lower() == ".mp4":
        return str(src)
    dst = src.with_suffix(".mp4")
    if dst.exists():
        if thong_tin(dst):
            log(f"  Dùng file .mp4 đã có cạnh video gốc: {dst.name}")
            return str(dst)
        dst = src.with_name(src.stem + " (mp4).mp4")      # có <tên>.mp4 nhưng hỏng/đang ghi -> không đè, đặt tên khác
    if not src.is_file():
        raise FileNotFoundError(f"Không thấy file video: {src} (cũng không có {src.stem}.mp4 cạnh đó)")
    ffmpeg = _exe("ffmpeg")
    tt = thong_tin(src)
    if tt is None:
        raise RuntimeError(f"ffprobe không đọc được video: {src.name}")
    tmp = dst.with_name(dst.name + ".part")
    timeout = max(1800, int(tt["giay"] * 20))
    dau = [ffmpeg, "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?"]
    tieng = ["-c:a", "copy"] if tt["acodec"] in TIENG_GIU_NGUYEN else ["-c:a", "aac", "-b:a", "192k"]
    duoi = ["-movflags", "+faststart", "-f", "mp4", str(tmp)]
    t0 = time.time()
    ok, loi, cach = False, "", ""
    if tt["vcodec"] in HINH_GIU_NGUYEN:                   # chỉ đổi vỏ, không mã hóa lại hình
        cach = f"giữ nguyên hình {tt['vcodec']}, chỉ đổi vỏ"
        log(f"  Đổi sang .mp4: {src.name} ({cach})...")
        tag = ["-tag:v", "hvc1"] if tt["vcodec"] == "hevc" else []
        ok, loi = _chay(dau + ["-c:v", "copy", *tag, *tieng, *duoi], timeout)
        if not ok:
            log(f"  ⚠ Đổi vỏ không được ({loi}) -> mã hóa lại hình.")
    if not ok:
        for ten, tham_so in BO_MA_HOA:
            if not _thu_ma_hoa(ffmpeg, ten):
                continue
            cach = f"{tt['vcodec']} -> H.264 bằng {TEN_MA_HOA[ten]}"
            log(f"  Đổi sang .mp4: {src.name} ({cach}, {tt['width']}x{tt['height']}, {tt['giay']:.0f}s)...")
            ok, loi = _chay(dau + [*tham_so, "-pix_fmt", "yuv420p", *tieng, *duoi], timeout)
            if ok:
                break
            log(f"  ⚠ {TEN_MA_HOA[ten]} lỗi ({loi}) -> thử bộ mã hóa khác.")
            _ENC_CACHE[ten] = False
    if not ok or thong_tin(tmp) is None:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Không đổi được {src.name} sang .mp4: {loi or 'file ra không đọc được'}")
    tmp.replace(dst)
    log(f"  ✓ {dst.name} ({dst.stat().st_size / 1048576:.1f} MB, {time.time() - t0:.0f}s, {cach}). File gốc giữ nguyên.")
    return str(dst)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for p in sys.argv[1:]:
        try:
            print(dam_bao_mp4(p))
        except Exception as e:      # noqa: BLE001
            print(f"✗ {p}: {e}")
