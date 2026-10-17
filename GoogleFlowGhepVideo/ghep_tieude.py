# -*- coding: utf-8 -*-
"""Ghép TIÊU ĐỀ + ẢNH MINH HỌA lên clip mở đầu (hook) 10 giây.

Quy tắc bố cục (theo yêu cầu):
  1. Nhận diện khuôn mặt bằng YuNet (OpenCV) trên vài frame rải trong clip,
     lấy frame có độ tin cậy cao nhất -> hộp khuôn mặt (x, y, w, h).
  2. Tiêu đề (PNG nền trắng) đặt DƯỚI khuôn mặt, trước ngực: mép trên tiêu đề
     cách cằm một khoảng = KHOANG_CACH x chiều cao khuôn mặt; căn giữa theo
     tâm khuôn mặt. Nền trắng quanh khung tiêu đề được làm trong suốt.
  3. Ảnh minh họa đặt DƯỚI tiêu đề (nằm sau tiêu đề), mép trên của ảnh bắt
     đầu từ GIỮA tiêu đề (1/2 chiều cao tiêu đề).
  4. Nếu ảnh chưa phủ tới đáy video thì phóng to cho phủ kín tới đáy, mép
     trên vẫn giữ ở 1/2 tiêu đề (phần dư hai bên bị cắt đều).
  5. Tiêu đề và ảnh hiển thị suốt toàn bộ thời lượng clip; giữ nguyên tiếng.
  6. PHẦN SAU: cảnh quay bác sĩ TẮT TIẾNG, lồng giọng đọc (--audio, mặc định là file mp3 trong
     thư mục Drive), dài đúng bằng audio, đưa về cùng kích thước clip hook rồi nối ngay sau 10 giây
     đầu. Không có tiêu đề/ảnh ở phần này. Nguồn hình (--phan-sau):
       - THƯ MỤC clip (mặc định: thư mục "video gốc" cạnh tool, khi bộ có giọng đọc): xáo ngẫu nhiên
         các clip rồi nối lần lượt tới khi đủ thời lượng giọng đọc; clip cuối dài hơn phần còn thiếu
         thì CẮT (chừa tối thiểu 1,5s để không lóe lên rồi hết); kho ngắn hơn giọng đọc thì xáo lại
         dùng tiếp. Mỗi clip chỉnh màu riêng. --seed N để ra đúng thứ tự clip như lần trước.
       - MỘT file video: dùng từ đầu, ngắn hơn audio thì đứng hình frame cuối (cách cũ).
  7. Khi có phần sau: hook được đưa về -14 LUFS / -1 dBTP (mức YouTube, TikTok); giọng đọc
     được KHỚP THEO HOOK: đo N giây đầu của giọng đọc (N = thời lượng hook, --cua-so-khop
     để đổi, 0 = cả file) so với mức thực tế của hook, ra một mức bù duy nhất rồi áp cho
     toàn bộ giọng đọc. --lech-giong -1 nếu muốn giọng đọc nhỏ hơn hook 1 dB.
     --lufs đổi mức chuẩn, --khong-chuan-am để tắt hoàn toàn.
  8. Chỉnh màu tự động từng clip giống "Điều chỉnh -> Tự động" của CapCut: auto levels
     (điểm đen/trắng), nâng trung tông nếu tối, cân bằng trắng theo vùng trung tính, bão hòa,
     làm nét nhẹ; áp lên hình gốc trước khi đè tiêu đề/ảnh. Xuất kèm ảnh _mau_truoc_sau.jpg
     để so sánh (--khong-chinh-mau để tắt).
  9. Tự dò GPU NVIDIA: ffmpeg có h264_nvenc và mã hóa thử thành công -> giải mã NVDEC + mã hóa
     NVENC (nhanh gấp nhiều lần); không có thì chuyển sang CHẾ ĐỘ MÁY YẾU (mục 11). --cpu để ép
     mã hóa CPU libx264 (bỏ dò NVENC/QSV/AMF).
 10. PHỤ ĐỀ khớp kịch bản (module viet_sub.py): có file kịch bản (docx/txt, "Kịch bản - ..." trong
     thư mục hoặc --kich-ban) thì nhận diện giọng nói bằng faster-whisper large-v3-turbo CHỈ để lấy
     mốc thời gian từng từ; chữ hiển thị luôn lấy từ kịch bản (máy nghe sai -> vẫn đúng chữ kịch
     bản, máy bỏ sót -> nội suy mốc). Hook + giọng đọc cùng một trục thời gian nhưng CHỈ GHI phụ đề
     cho phần sau: 10s hook đã có tiêu đề + ảnh minh họa nên để sạch (không có phần sau thì không
     làm phụ đề). Xuất <tên>_<stamp>.srt ra Downloads và đốt thẳng vào video (chữ trắng viền đen,
     giữa dưới). --khong-sub để bỏ,
     --sub-co/--sub-le-duoi/--sub-font chỉnh cỡ, lề dưới, font; --model-sub đổi model.
 11. CHẾ ĐỘ MÁY YẾU (chỉ ở khâu render ffmpeg; model nhận diện phụ đề KHÔNG đổi, vẫn large-v3-turbo,
     máy không GPU tự chạy CPU int8): tự bật khi không dò thấy NVIDIA NVENC, hoặc ép bằng --nhe;
     --manh để giữ chế độ đầy đủ dù không có GPU. In "Chế độ: máy yếu (lý do)" / "Chế độ: đầy đủ" ngay đầu.
     Khi bật: (a) mã hóa thử 0,2s lần lượt h264_qsv (Intel) -> h264_amf (AMD), cái nào chạy được thì
     dùng (VBR ~7 Mbps, trần 9 Mbps cho 1080x1920); không có thì libx264 preset veryfast crf 20 thay
     medium crf 18; (b) scale dùng flags=bicubic thay lanczos; (c) bỏ bước làm nét unsharp (chiếm
     ~nửa thời gian filter); chỉnh màu lutrgb+eq giữ nguyên vì rẻ. --do-phan-giai 720 xuất 720x1280
     (hook 1080p thu xuống, phần sau đưa thẳng về 720p) cho máy rất yếu; mặc định vẫn 1080x1920.
     Trên máy có NVENC mọi thứ giữ nguyên như trước.

QUY ƯỚC ĐẶT TÊN FILE (để tool tự nhận ra vai trò, không phân biệt hoa/thường, có dấu/không dấu):
  "Hook - <tên>.mp4"        clip mở đầu 10s (Google Flow), có tiếng
  "Tiêu đề - <tên>.png"     ảnh tiêu đề khung xanh (PNG nền trắng, tool tự làm trong suốt)
  "Minh họa - <tên>.jpg"    ảnh minh họa (jpg hoặc png)
  "Giọng đọc - <tên>.mp3"   giọng đọc MiniMax lồng vào phần sau (mp3/wav/m4a)
  "Kịch bản - <tên>.docx"   kịch bản, tool bỏ qua
  "Gốc - <tên>.mov"         video quay bác sĩ: TẠM CHƯA ÁP DỤNG, vẫn đưa riêng bằng --phan-sau
                            (nếu sau này có file "Gốc - " trong thư mục thì tool cũng nhận)
  <tên> giống nhau cho cả bộ; tên file ra lấy theo <tên>. File chưa có tiền tố vẫn được đoán
  theo đuôi như trước (mp4 đầu tiên = hook, ảnh có chữ "tiêu đề" = tiêu đề, ảnh còn lại = minh họa,
  mp3 = giọng đọc) nhưng tool in CẢNH BÁO để nhắc đổi tên.

Cách dùng:
  python ghep_tieude.py --thu-muc "D:/.../thư mục đã đặt tên theo quy ước"   # tự lấy đủ 5 file
  python ghep_tieude.py --video clip.mp4 --tieude "TIÊU ĐỀ - xxx.png" --anh "xxx.jpg"
  python ghep_tieude.py ... --phan-sau "D:/thư mục clip" --audio "giọng đọc.mp3"   # hoặc 1 file video
  python ghep_tieude.py                 # không tham số -> hộp thoại chọn file (mở ở Downloads)
  python ghep_tieude.py --drive <link thư mục Drive> [--phan-sau "video gốc.mov"]
                                        # tải cả thư mục về Downloads rồi tự ghép (mp3 trong thư mục = giọng đọc)
  python ghep_tieude.py --thu-muc ... --nhe [--do-phan-giai 720]   # ép chế độ máy yếu (xem mục 11)

Kết quả ghi ra Downloads: <tên video>_ghep_<stamp>.mp4 (chỉ hook) hoặc _full_<stamp>.mp4 (hook + phần sau),
kèm _preview.jpg bố cục 10s đầu.
Yêu cầu: opencv-python >= 4.8 (có FaceDetectorYN), ffmpeg trên PATH, gdown (chỉ khi --drive).
"""
from __future__ import annotations

import argparse
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path

import cv2
import numpy as np

for _s in (sys.stdout, sys.stderr):          # in tiếng Việt không lỗi cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
MODEL_NAME = "face_detection_yunet_2023mar.onnx"
MODEL_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/" + MODEL_NAME)

# ----- tham số bố cục mặc định (tỉ lệ) -----
TI_LE_RONG_TIEUDE = 0.90   # bề rộng tiêu đề / bề rộng video
KHOANG_CACH_CAM = 0.20     # khoảng cách cằm -> mép trên tiêu đề, tính theo chiều cao mặt
TI_LE_DIEM_BAT_DAU_ANH = 0.5  # mép trên ảnh minh họa = top tiêu đề + 1/2 chiều cao tiêu đề
NGUONG_TRANG = 235         # pixel >= ngưỡng (cả 3 kênh) coi là nền trắng của file tiêu đề

# ----- phần sau (clip quay bác sĩ tắt tiếng + giọng đọc) -----
THU_MUC_GOC = HERE / "video gốc"   # kho clip mặc định: ghép ngẫu nhiên tới khi đủ giọng đọc
DUOI_VIDEO = (".mov", ".mp4", ".mkv", ".m4v")
DOAN_CUOI_TOI_THIEU = 1.5  # giây: clip cuối (bị cắt) không ngắn hơn mức này, tránh cảnh lóe lên rồi hết
FPS_RA = 30                # fps video cuối khi có phần sau (hook 24fps + body 30fps -> quy về 30)
AUDIO_BR = "192k"          # bitrate AAC khi phải encode lại audio (concat)
LUFS_MUC_TIEU = -14.0      # âm lượng phổ thông (YouTube/TikTok/Spotify chuẩn hóa về -14 LUFS)
TRUE_PEAK_DB = -1.0        # đỉnh tối đa sau chuẩn hóa (dBTP)

# ----- chỉnh màu tự động (giống "Điều chỉnh -> Tự động" của CapCut) -----
CHINH_MAU_MANH = 0.7       # 0..1: mức áp dụng auto levels / cân bằng trắng (1 = chỉnh hết cỡ)
TRUNG_TONG_MUC_TIEU = 0.47 # độ sáng trung tông mong muốn (chỉ nâng khi tối, không làm tối thêm)


# ====================================================================== tiện ích
def downloads_dir() -> Path:
    """Thư mục Downloads thật (user có thể đã dời), fallback ~/Downloads."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
        p = Path(val)
        if p.is_dir():
            return p
    except Exception:
        pass
    return Path.home() / "Downloads"


def unique_path(folder: Path, name: str) -> Path:
    """Chống trùng tên (kể cả 2 lần chạy trong cùng một giây)."""
    p = folder / name
    stem, ext = p.stem, p.suffix
    i = 1
    while p.exists():
        p = folder / f"{stem} ({i}){ext}"
        i += 1
    return p


def ensure_model() -> Path:
    model = HERE / MODEL_NAME
    if not model.exists():
        print(f"Tải model YuNet về {model} ...")
        urllib.request.urlretrieve(MODEL_URL, model)
    return model


def need_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("Không tìm thấy ffmpeg trên PATH. Cài: choco install ffmpeg (hoặc winget).")
    return exe


# ----- bộ mã hóa & chế độ render (đầy đủ / máy yếu) -----
ENCODER_FFMPEG = dict(nvenc="h264_nvenc", qsv="h264_qsv", amf="h264_amf", x264="libx264")
TEN_MA_HOA = dict(nvenc="GPU NVENC", qsv="GPU Intel Quick Sync (h264_qsv)",
                  amf="GPU AMD AMF (h264_amf)", x264="CPU libx264")
_ENC_CACHE: dict = {}


def thu_ma_hoa(ffmpeg: str, loai: str) -> bool:
    """ffmpeg có encoder `loai` (nvenc/qsv/amf) VÀ mã hóa thử 0,2 giây thành công (driver chạy được).
    Kết quả nhớ trong phiên để không dò hai lần."""
    if loai in _ENC_CACHE:
        return _ENC_CACHE[loai]
    ok = False
    try:
        if "danh_sach" not in _ENC_CACHE:
            _ENC_CACHE["danh_sach"] = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                                     text=True, timeout=30).stdout
        if ENCODER_FFMPEG[loai] in _ENC_CACHE["danh_sach"]:
            test = subprocess.run(
                [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2:r=30",
                 "-c:v", ENCODER_FFMPEG[loai], "-f", "null", "-"], capture_output=True, text=True, timeout=60)
            ok = test.returncode == 0
    except Exception:
        ok = False
    _ENC_CACHE[loai] = ok
    return ok


def gpu_encoder(ffmpeg: str, force_cpu: bool = False) -> dict | None:
    """Dò GPU NVIDIA: ffmpeg có h264_nvenc VÀ mã hóa thử thành công.
    Trả về {'loai': 'nvenc', 'name': tên card} nếu dùng được, None -> không có NVENC."""
    if force_cpu or not thu_ma_hoa(ffmpeg, "nvenc"):
        return None
    name = "NVIDIA"
    try:
        smi = shutil.which("nvidia-smi")
        if smi:
            out = subprocess.run([smi, "--query-gpu=name", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            name = out.splitlines()[0] if out else name
    except Exception:
        pass
    return dict(loai="nvenc", name=name)


def chon_bo_ma_hoa(ffmpeg: str, force_cpu: bool = False) -> dict:
    """Bộ chọn mã hóa chung, thử theo thứ tự NVENC (NVIDIA) -> QSV (Intel) -> AMF (AMD) -> libx264.
    Trả về {'loai': nvenc|qsv|amf|x264, 'name': mô tả}."""
    if not force_cpu:
        gpu = gpu_encoder(ffmpeg)
        if gpu:
            return gpu
        for loai in ("qsv", "amf"):
            if thu_ma_hoa(ffmpeg, loai):
                return dict(loai=loai, name=TEN_MA_HOA[loai])
    return dict(loai="x264", name=TEN_MA_HOA["x264"])


def chon_che_do(ffmpeg: str, nhe: bool = False, manh: bool = False, force_cpu: bool = False) -> dict:
    """Quyết định CHẾ ĐỘ render (chỉ khâu ffmpeg; model nhận diện phụ đề không đổi).
    Máy yếu khi: --nhe, hoặc không dò thấy NVENC mà không có --manh.
    Trả về {'nhe': bool, 'ly_do': str, 'enc': bộ mã hóa (xem chon_bo_ma_hoa)}."""
    enc = chon_bo_ma_hoa(ffmpeg, force_cpu)
    if nhe:
        return dict(nhe=True, ly_do="ép bằng --nhe", enc=enc)
    if manh:
        return dict(nhe=False, ly_do="ép bằng --manh", enc=enc)
    if enc["loai"] == "nvenc":
        return dict(nhe=False, ly_do="có NVIDIA NVENC", enc=enc)
    return dict(nhe=True, ly_do="ép CPU bằng --cpu" if force_cpu else "không dò thấy NVIDIA NVENC dùng được",
                enc=enc)


def ten_bo_ma_hoa(enc: dict, nhe: bool = False) -> str:
    """Mô tả bộ mã hóa để in: 'GPU NVENC (NVIDIA GeForce RTX 4060)', 'CPU libx264 veryfast crf 20'..."""
    if enc["loai"] == "nvenc":
        return f"GPU NVENC ({enc['name']})"
    if enc["loai"] == "x264":
        return "CPU libx264 " + ("veryfast crf 20" if nhe else "medium crf 18")
    return enc["name"]


def mo_ta_che_do(cd: dict) -> str:
    """Nội dung dòng 'Chế độ: ...'."""
    if not cd["nhe"]:
        return f"đầy đủ ({cd['ly_do']})"
    return (f"máy yếu ({cd['ly_do']}) -> mã hóa {ten_bo_ma_hoa(cd['enc'], True)}, "
            f"scale bicubic, bỏ làm nét; model phụ đề giữ nguyên")


def video_codec_args(enc: dict, nhe: bool = False, pixels: int = 1080 * 1920) -> list:
    """Tham số mã hóa H.264 theo bộ mã hóa đã chọn:
    - nvenc: chất lượng cố định cq 24 (~ x264 crf 18), trần 10 Mbps. Thang cq khác crf: cq 19 cho file
      to gấp 3 lần x264 crf 18.
    - qsv / amf (chế độ máy yếu): VBR ~7 Mbps, trần 9 Mbps cho 1080x1920; thu theo số pixel khi xuất 720p
      (sàn 4 Mbps).
    - x264: medium crf 18 (đầy đủ) hoặc veryfast crf 20 (máy yếu: nhanh ~3 lần, file lớn hơn chút)."""
    loai = enc["loai"]
    if loai == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "24",
                "-b:v", "0", "-maxrate", "10M", "-bufsize", "20M", "-spatial-aq", "1",
                "-temporal-aq", "1", "-profile:v", "high"]
    if loai in ("qsv", "amf"):
        mbps = max(4.0, 7.0 * pixels / (1080 * 1920))
        rate = ["-b:v", f"{mbps:.1f}M", "-maxrate", f"{mbps * 1.3:.1f}M", "-bufsize", f"{mbps * 2:.1f}M",
                "-profile:v", "high"]
        if loai == "qsv":
            return ["-c:v", "h264_qsv", "-preset", "medium", *rate]
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak", *rate]
    if nhe:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]


def hwdec_args(enc: dict | None) -> list:
    """Tuỳ chọn đặt TRƯỚC mỗi -i video. NVENC: giải mã bằng NVDEC, frame tự tải về RAM cho filter CPU
    (codec nào NVDEC không đỡ được thì ffmpeg tự rơi về giải mã phần mềm). QSV/AMF/x264: giải mã phần mềm."""
    return ["-hwaccel", "cuda"] if enc and enc.get("loai") == "nvenc" else []


def kich_thuoc_ra(W: int, H: int, canh_ngan: int) -> tuple[int, int]:
    """Kích thước xuất khi --do-phan-giai N: cạnh ngắn = N px, giữ tỉ lệ, làm tròn số chẵn; không phóng to
    (0 hoặc N >= cạnh ngắn hook -> giữ nguyên). 1080x1920, N=720 -> 720x1280."""
    if not canh_ngan or min(W, H) <= canh_ngan:
        return W, H
    k = canh_ngan / min(W, H)
    return int(round(W * k / 2)) * 2, int(round(H * k / 2)) * 2


def probe_media(path: Path):
    """(rộng, cao, thời lượng giây) của file media; ảnh/audio -> rộng=cao=0.
    Đã tính xoay (rotation metadata) để rộng/cao là kích thước hiển thị."""
    import json
    exe = shutil.which("ffprobe")
    if not exe:
        sys.exit("Không tìm thấy ffprobe trên PATH (đi kèm ffmpeg).")
    out = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:stream_side_data=rotation:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    dur = float(j.get("format", {}).get("duration") or 0)
    st = (j.get("streams") or [{}])[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    rot = 0
    for sd in st.get("side_data_list", []):
        rot = int(float(sd.get("rotation", rot)))
    if abs(rot) % 180 == 90:
        w, h = h, w
    return w, h, dur


def thoi_luong_hinh(path: Path) -> float:
    """Thời lượng LUỒNG HÌNH (giây). Clip điện thoại thường có tiếng dài hơn hình vài chục ms; dùng thời lượng
    file để xếp clip thì mỗi chỗ nối hụt ~1 frame và cuối video phải đứng hình bù."""
    import json
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=duration:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return float((j.get("streams") or [{}])[0].get("duration") or j.get("format", {}).get("duration") or 0)


def probe_channels(path: Path) -> int:
    """Số kênh audio của luồng audio đầu tiên (0 nếu không có)."""
    exe = shutil.which("ffprobe")
    out = subprocess.run(
        [exe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
         "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else 0


def to_stereo_filter(path: Path) -> str:
    """Đưa audio về stereo 48k: mono -> copy sang 2 kênh (aformat mặc định upmix mono giảm 3 dB)."""
    af = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    if probe_channels(path) == 1:
        return "pan=stereo|c0=c0|c1=c0," + af
    return af


def measure_lufs(path: Path, prefilter: str, window: float | None = None) -> dict:
    """Đo độ ồn EBU R128 của file SAU khi qua `prefilter` (để đo đúng tín hiệu sẽ đưa vào concat).
    `window`: chỉ đo `window` giây đầu (None = cả file).
    Trả về {'i': LUFS tích hợp, 'tp': đỉnh dBTP, 'lra': dải động}."""
    import json, re
    exe = shutil.which("ffmpeg")
    res = subprocess.run(
        [exe, "-v", "info", "-nostats", *(["-t", f"{window:.3f}"] if window else []), "-i", str(path), "-vn",
         "-af", f"{prefilter},loudnorm=I={LUFS_MUC_TIEU}:TP={TRUE_PEAK_DB}:LRA=11:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr)
    if not m:
        sys.exit(f"Không đo được độ ồn của {path.name}:\n{res.stderr[-800:]}")
    j = json.loads(m.group(0))
    return dict(i=float(j["input_i"]), tp=float(j["input_tp"]), lra=float(j["input_lra"]))


def chuan_am_filter(gain_db: float) -> str:
    """Gain tuyến tính (giữ nguyên dải động) rồi chặn đỉnh ở TRUE_PEAK_DB. Gain âm thì limiter
    không tác động; gain dương mà đỉnh vượt ngưỡng thì chỉ cắt đúng các đỉnh đó."""
    limit = 10 ** (TRUE_PEAK_DB / 20)
    return (f"volume={gain_db:+.2f}dB,"
            f"alimiter=limit={limit:.4f}:attack=5:release=100:level=false:latency=1")


def chuan_am(path: Path, prefilter: str, target_i: float,
             window: float | None = None) -> tuple[str, dict, float]:
    """Đo -> gain -> đo lại sau limiter -> bù phần hụt (limiter cắt đỉnh làm LUFS tụt).
    `window`: chỉ đo trên `window` giây ĐẦU của file, nhưng gain tìm được áp cho CẢ file
    (một mức bù duy nhất, không thay đổi theo thời gian).
    Trả về (chuỗi filter chuẩn hóa, số đo gốc, LUFS thực tế sau chuẩn hóa)."""
    meas = measure_lufs(path, prefilter, window)
    gain = target_i - meas["i"]
    after = meas
    for _ in range(2):                       # tối đa 2 lượt bù, dừng khi lệch < 0.2 LU
        flt = chuan_am_filter(gain)
        after = measure_lufs(path, f"{prefilter},{flt}", window)
        if abs(after["i"] - target_i) < 0.2:
            break
        gain += target_i - after["i"]
    meas["gain_db"] = round(gain, 2)
    return flt, meas, after["i"]


def imread_unicode(path: Path, flags=cv2.IMREAD_UNCHANGED):
    """cv2.imread không đọc được đường dẫn có dấu tiếng Việt -> đọc qua numpy."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, flags)
    if img is None:
        sys.exit(f"Không đọc được ảnh: {path}")
    return img


def imwrite_unicode(path: Path, img) -> None:
    ok, buf = cv2.imencode(path.suffix, img)
    if not ok:
        sys.exit(f"Không ghi được ảnh: {path}")
    buf.tofile(str(path))


# ================================================================ nhận diện mặt
def detect_face(video: Path, model: Path, samples: int = 7):
    """Thử `samples` frame rải đều trong clip, trả về (x, y, w, h, conf, t, frame) tốt nhất."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"Không mở được video: {video}")
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = n / fps if n else 10.0

    det = cv2.FaceDetectorYN.create(str(model), "", (W, H), 0.6, 0.3, 5000)
    det.setInputSize((W, H))

    best = None
    for i in range(samples):
        t = dur * (i + 0.5) / samples
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        _, faces = det.detect(frame)
        if faces is None or len(faces) == 0:
            print(f"  t={t:4.1f}s: không thấy mặt")
            continue
        f = max(faces, key=lambda r: r[-1])          # mặt tin cậy nhất trong frame
        x, y, w, h, conf = int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[-1])
        print(f"  t={t:4.1f}s: mặt tại x={x} y={y} w={w} h={h} tin cậy={conf:.3f}")
        if best is None or conf > best[4]:
            best = (x, y, w, h, conf, t, frame)
    cap.release()

    if best is None:
        print("CẢNH BÁO: không nhận diện được khuôn mặt -> giả định mặt ở 1/3 trên, giữa khung.")
        w = int(W * 0.3); h = int(w * 1.35)
        cap = cv2.VideoCapture(str(video)); ok, frame = cap.read(); cap.release()
        best = ((W - w) // 2, int(H * 0.2), w, h, 0.0, 0.0, frame)
    return best, (W, H, fps, dur)


# ============================================================ xử lý tiêu đề PNG
def title_with_alpha(img):
    """Tiêu đề xuất từ PowerPoint là PNG nền trắng, không alpha.
    -> Làm trong suốt vùng trắng BÊN NGOÀI khung (flood-fill từ 4 góc), giữ nguyên
    vùng trong khung, giữ bóng đổ mềm (bóng xám -> đen có alpha), rồi cắt sát khung."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:                      # đã có alpha sẵn
        a = img[:, :, 3]
    else:
        bgr = img
        h, w = bgr.shape[:2]
        white = (bgr.min(axis=2) >= NGUONG_TRANG).astype(np.uint8)   # 1 = trắng
        # flood-fill vùng trắng nối với 4 góc -> vùng "ngoài khung"
        outside = np.zeros((h, w), np.uint8)
        mask = np.zeros((h + 2, w + 2), np.uint8)
        for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            if white[seed[1], seed[0]]:
                cv2.floodFill(white.copy(), mask, seed, 2, flags=cv2.FLOODFILL_MASK_ONLY | 4)
        outside = mask[1:-1, 1:-1] > 0
        # vùng bóng đổ: xám nhạt (chưa tới ngưỡng trắng) nhưng vẫn nằm ngoài khung ->
        # mở rộng vùng ngoài bằng một flood-fill nữa trên ngưỡng mềm hơn
        soft = (bgr.min(axis=2) >= 150).astype(np.uint8)
        mask2 = np.zeros((h + 2, w + 2), np.uint8)
        for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            if soft[seed[1], seed[0]]:
                cv2.floodFill(soft.copy(), mask2, seed, 2, flags=cv2.FLOODFILL_MASK_ONLY | 4)
        outside_soft = mask2[1:-1, 1:-1] > 0
        gray = bgr.min(axis=2)
        a = np.full((h, w), 255, np.uint8)
        a[outside_soft] = (255 - gray[outside_soft]).astype(np.uint8)   # bóng -> alpha mờ
        a[outside] = 0
        img = np.dstack([bgr, a])
        img[outside_soft, :3] = 0                                        # bóng màu đen
    ys, xs = np.where(a > 8)
    if len(ys) == 0:
        return img
    pad = 4
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, img.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, img.shape[1])
    return img[y0:y1, x0:x1]


# ============================================================ chỉnh màu tự động
def sample_frames(path: Path, n: int, width: int = 480, max_t: float | None = None) -> list:
    """Lấy n frame rải đều trong clip (thu nhỏ về `width` để phân tích nhanh)."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
    if max_t:
        dur = min(dur, max_t)
    frames = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(dur * (i + 0.5) / n, 0) * 1000)
        ok, f = cap.read()
        if ok:
            frames.append(cv2.resize(f, (width, int(width * f.shape[0] / f.shape[1]))))
    cap.release()
    return frames


def phan_tich_mau(path: Path, n: int = 12, strength: float = CHINH_MAU_MANH,
                  max_t: float | None = None) -> dict:
    """Phân tích màu clip -> thông số chỉnh tự động (giống CapCut Auto adjust):
    điểm đen/trắng (auto levels), gamma trung tông, cân bằng trắng, bão hòa."""
    frames = sample_frames(path, n, max_t=max_t)
    if not frames:
        return {}
    bgr = np.concatenate([f.reshape(-1, 3) for f in frames]).astype(np.float32) / 255
    luma = 0.114 * bgr[:, 0] + 0.587 * bgr[:, 1] + 0.299 * bgr[:, 2]
    lo, mid, hi = np.percentile(luma, [0.5, 50, 99.5])
    # 1) auto levels: kéo điểm đen/trắng về 0/1, áp `strength` để không quá gắt
    in_min = float(lo * strength)
    in_max = float(1 - (1 - hi) * strength)
    # 2) gamma: chỉ NÂNG trung tông khi tối; không làm tối thêm quá 5% (cảnh áo trắng/tường sáng là bình thường)
    m2 = min(max((mid - in_min) / (in_max - in_min), 0.05), 0.95)
    gamma = math.log(m2) / math.log(TRUNG_TONG_MUC_TIEU)
    gamma = min(max(1 + (gamma - 1) * 0.6, 0.95), 1.25)
    # 3) cân bằng trắng: mốc là pixel SÁNG + ÍT MÀU (tường, áo trắng) để áo xanh/gỗ nâu không kéo lệch
    hsv = cv2.cvtColor((bgr[None] * 255).astype(np.uint8), cv2.COLOR_BGR2HSV)[0]
    sat = hsv[:, 1].astype(np.float32) / 255
    neutral = (sat < 0.12) & (luma > 0.4) & (luma < 0.95)
    if neutral.mean() < 0.02:                     # không đủ pixel trung tính -> gray-world trung tông
        neutral = (luma > 0.2) & (luma < 0.9)
    m = bgr[neutral].mean(axis=0)
    g = m.mean() / m
    g = np.clip(1 + (g - 1) * strength, 0.94, 1.06)
    g = g / (0.114 * g[0] + 0.587 * g[1] + 0.299 * g[2])   # giữ nguyên độ sáng tổng
    # 4) bão hòa: ảnh càng nhạt đẩy càng nhiều
    mid_sel = (luma > 0.2) & (luma < 0.9)
    s_mean = float(sat[mid_sel].mean())
    satk = 1.18 if s_mean < 0.2 else 1.12 if s_mean < 0.3 else 1.06
    return dict(in_min=round(in_min, 3), in_max=round(in_max, 3), gamma=round(float(gamma), 3),
                wb_rgb=(round(float(g[2]), 3), round(float(g[1]), 3), round(float(g[0]), 3)),
                sat=satk, goc=dict(den=round(float(lo), 3), trung=round(float(mid), 2),
                                   trang=round(float(hi), 3), bao_hoa=round(s_mean, 2)))


def chinh_mau_filter(p: dict) -> str:
    """Chuỗi filter màu (chưa gồm làm nét; làm nét đặt sau scale bằng LAM_NET).
    Chỉ MỘT lần đổi RGB (lutrgb: điểm đen/trắng + cân bằng trắng) rồi MỘT lần YUV (eq: gamma + bão hòa).
    Trước đây dùng colorlevels -> eq -> colorchannelmixer (RGB->YUV->RGB) vừa chậm gấp 3, vừa làm
    nguồn 10-bit (HEVC điện thoại) tối đi ~17/255 do đổi dải màu nhiều lần."""
    if not p:
        return ""
    lo, hi = p["in_min"], p["in_max"]

    def kenh(gain: float) -> str:   # (val - đen)/(trắng - đen) * gain, kẹp 0..max
        return f"clip(((val/maxval-{lo})/({hi}-{lo}))*{gain}*maxval\\,0\\,maxval)"

    r, g, b = p["wb_rgb"]
    return (f"lutrgb=r='{kenh(r)}':g='{kenh(g)}':b='{kenh(b)}',"
            f"eq=gamma={p['gamma']}:saturation={p['sat']}")


LAM_NET = "unsharp=5:5:0.5:5:5:0"   # làm nét nhẹ, đặt sau khi scale (bỏ ở chế độ máy yếu)


def scale_flags(nhe: bool = False) -> str:
    """Nội suy khi scale: lanczos (nét, chậm) ở chế độ đầy đủ; bicubic ở chế độ máy yếu."""
    return "bicubic" if nhe else "lanczos"


def lam_net(nhe: bool = False) -> list:
    """Bước làm nét sau scale: [] ở chế độ máy yếu (unsharp chiếm ~nửa thời gian filter)."""
    return [] if nhe else [LAM_NET]


def preview_mau(items, out_path: Path, ffmpeg: str, nhe: bool = False) -> None:
    """items: [(video, filter_màu, [giây...])] -> ảnh so sánh: hàng trên gốc, hàng dưới đã chỉnh
    (đúng chuỗi filter sẽ render: chế độ máy yếu thì không có làm nét)."""
    fit = "scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:(ow-iw)/2:(oh-ih)/2"
    cols = []
    with tempfile.TemporaryDirectory() as td:
        for k, (path, flt, ts) in enumerate(items):
            for t in ts:
                pair = []
                for tag, vf in (("b", fit), ("a", ",".join([flt, *lam_net(nhe), fit]))):
                    png = Path(td) / f"{k}_{t:.1f}_{tag}.png"
                    subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                                    "-frames:v", "1", "-vf", vf, str(png)], check=True)
                    pair.append(cv2.imread(str(png)))
                cols.append(np.concatenate(pair, axis=0))
    imwrite_unicode(out_path, np.concatenate(cols, axis=1))


# ================================================================== bố cục
def layout(W, H, face, title_rgba, illus, ti_le_rong, khoang_cach):
    x, y, w, h = face[:4]
    face_cx = x + w // 2
    face_bottom = y + h

    # --- tiêu đề: rộng = ti_le_rong * W, giữ tỉ lệ
    tw = int(W * ti_le_rong)
    th = int(round(title_rgba.shape[0] * tw / title_rgba.shape[1]))
    title = cv2.resize(title_rgba, (tw, th), interpolation=cv2.INTER_AREA)
    ty = face_bottom + int(h * khoang_cach)
    ty = max(0, min(ty, H - th))                 # không lọt ra ngoài khung
    tx = face_cx - tw // 2
    tx = max(0, min(tx, W - tw))

    # --- ảnh minh họa: mép trên = giữa tiêu đề; phủ kín tới đáy; nằm SAU tiêu đề
    iy = ty + int(th * TI_LE_DIEM_BAT_DAU_ANH)
    avail_h = H - iy
    ih, iw = illus.shape[:2]
    scale = max(W / iw, avail_h / ih)            # "cover": phủ hết bề rộng lẫn chiều cao còn lại
    nw, nh = int(round(iw * scale)), int(round(ih * scale))
    big = cv2.resize(illus, (nw, nh), interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    cx0 = (nw - W) // 2                          # cắt đều hai bên
    crop = big[0:avail_h, cx0:cx0 + W]           # mép trên giữ nguyên, dư dưới thì cắt
    return (tx, ty, title), (0, iy, crop), dict(
        tieude=(tx, ty, tw, th), anh=(0, iy, W, avail_h), ti_le_phong_anh=round(scale, 3),
        cat_moi_ben=cx0)


def composite_preview(frame, title_item, illus_item):
    out = frame.copy()
    ix, iy, crop = illus_item
    out[iy:iy + crop.shape[0], ix:ix + crop.shape[1]] = crop[:, :, :3]
    tx, ty, title = title_item
    a = title[:, :, 3:4].astype(np.float32) / 255.0
    roi = out[ty:ty + title.shape[0], tx:tx + title.shape[1]].astype(np.float32)
    out[ty:ty + title.shape[0], tx:tx + title.shape[1]] = (
        roi * (1 - a) + title[:, :, :3].astype(np.float32) * a).astype(np.uint8)
    return out


# ================================================================== ghép ffmpeg
def khoa_tu_nhien(s: str):
    """Sắp tên kiểu người đọc: '2.mov' trước '10.mov'."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", khong_dau(s))]


def liet_ke_clip(folder: Path) -> list[tuple[Path, float]]:
    """Mọi video trong thư mục (không đệ quy) kèm thời lượng HÌNH, sắp theo tên; bỏ clip < 0,3s."""
    ds = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in DUOI_VIDEO),
                key=lambda p: khoa_tu_nhien(p.name))
    return [(p, d) for p in ds for d in [thoi_luong_hinh(p)] if d >= 0.3]


def chon_clip_ngau_nhien(kho: list[tuple[Path, float]], D: float, seed: int | None = None) -> list[tuple[Path, float]]:
    """Xáo ngẫu nhiên các clip rồi nối lần lượt cho tới khi đủ D giây -> [(clip, số giây dùng)].
    Clip cuối dài hơn phần còn thiếu thì CẮT. Hết kho mà chưa đủ thì xáo lại dùng tiếp (không để một
    clip đứng liền chính nó). Tránh đoạn cuối chỉ lóe lên: nếu dùng trọn một clip sẽ để lại phần thiếu
    ngắn hơn DOAN_CUOI_TOI_THIEU giây thì cắt bớt clip đó, chừa đủ DOAN_CUOI_TOI_THIEU cho clip cuối."""
    rng = random.Random(seed)
    chon: list[tuple[Path, float]] = []
    con_lai, xap, truoc = D, [], None
    while con_lai > 0.02:
        if not xap:
            xap = kho[:]
            rng.shuffle(xap)
            if truoc is not None and len(xap) > 1 and xap[0][0] == truoc:
                xap.append(xap.pop(0))
        if con_lai < DOAN_CUOI_TOI_THIEU + 1.0:
            # phần thiếu quá ngắn để chia hai đoạn -> lấy MỘT clip đủ dài rồi cắt cho vừa
            # (ưu tiên clip còn trong lượt xáo hiện tại, không trùng clip vừa dùng)
            du_dai = [c for c in xap if c[1] >= con_lai and c[0] != truoc]
            if du_dai:
                xap.remove(du_dai[0])
                chon.append((du_dai[0][0], round(con_lai, 3)))
                break
            du_dai = [c for c in kho if c[1] >= con_lai and c[0] != truoc]
            if du_dai:
                chon.append((rng.choice(du_dai)[0], round(con_lai, 3)))
                break
        p, d = xap.pop(0)
        if d >= con_lai:
            dung = con_lai                                     # clip cuối: cắt cho vừa giọng đọc
        elif con_lai - d < DOAN_CUOI_TOI_THIEU and con_lai - DOAN_CUOI_TOI_THIEU >= 1.0:
            dung = con_lai - DOAN_CUOI_TOI_THIEU
        else:
            dung = d
        chon.append((p, round(dung, 3)))
        con_lai -= dung
        truoc = p
    return chon


def clip_filter(W: int, H: int, bw: int, bh: int, dung: float, mau: str = "", nhe: bool = False) -> str:
    """Chuỗi filter cho MỘT clip phần sau: (chỉnh màu riêng clip) -> đưa về WxH -> fps chung -> lấy đúng
    `dung` giây đầu. `nhe`: chế độ máy yếu -> scale bicubic, không làm nét."""
    target = W / H
    fl = scale_flags(nhe)
    if bw and bh and abs(bw / bh - target) / target < 0.05:
        # cùng tỉ lệ khung (sai số < 5%) -> phóng phủ kín rồi cắt giữa, không viền đen
        fit = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags={fl},crop={W}:{H}"
    else:
        # khác tỉ lệ -> thu vừa khung, viền đen hai bên/trên dưới
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags={fl},"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
    parts = ([mau] if mau else []) + [fit] + (lam_net(nhe) if mau else []) + [f"fps={FPS_RA}"]
    parts += [f"trim=duration={dung:.3f}", "setpts=PTS-STARTPTS", "format=yuv420p"]
    return ",".join(parts)


def render(video: Path, title_item, illus_item, out: Path, ffmpeg: str,
           phan_sau: list[tuple[Path, float, str]] | None = None, audio: Path | None = None,
           lufs: float | None = LUFS_MUC_TIEU, mau_hook: str = "",
           che_do: dict | None = None, cua_so_khop: float | None = None, lech_giong: float = 0.0,
           srt: Path | None = None, sub_style: str | None = None,
           kich_thuoc_ra: tuple[int, int] | None = None,
           minh_hoa: list[tuple[Path, float, float, str]] | None = None) -> dict:
    """Render clip hook đã ghép tiêu đề/ảnh. Nếu có `phan_sau` + `audio`: nối thêm phần sau =
    các clip [(clip, số giây dùng, filter màu riêng clip)] nối liền nhau, TẮT TIẾNG, lồng `audio`,
    dài đúng bằng audio (hết audio là hết video; tổng clip ngắn hơn thì đứng hình frame cuối).
    `lufs`: đưa hook về mức này (None = giữ nguyên âm lượng cả hai đoạn).
    Giọng đọc được KHỚP THEO HOOK: đo `cua_so_khop` giây đầu của giọng đọc (None = bằng thời lượng
    hook, 0 = cả file) so với mức thực tế của hook, ra MỘT mức bù rồi áp cho toàn bộ giọng đọc.
    `lech_giong`: cộng thêm dB cho giọng đọc so với hook (âm = nhỏ hơn hook) nếu tai thấy chưa đều.
    `mau_hook`: chuỗi filter chỉnh màu áp lên hình hook (trước khi đè tiêu đề/ảnh).
    `che_do`: kết quả chon_che_do() -> bộ mã hóa + chế độ máy yếu (bicubic, không làm nét);
    None = đầy đủ với libx264.
    `kich_thuoc_ra`: (W, H) video xuất; khác kích thước hook thì hook (đã đè tiêu đề/ảnh ở độ phân giải
    gốc) được thu về kích thước này, phần sau đưa thẳng về kích thước này.
    `minh_hoa`: [(file clip/ảnh, giây bắt đầu TRONG PHẦN SAU, số giây, "video"|"anh")] — cảnh minh họa đè
    kín khung lên phần sau đúng khoảng đó (overlay bật/tắt theo giây, tắt tiếng), phụ đề vẫn ở trên cùng."""
    tx, ty, title = title_item
    ix, iy, crop = illus_item
    che_do = che_do or dict(nhe=False, ly_do="mặc định", enc=dict(loai="x264", name=TEN_MA_HOA["x264"]))
    nhe, enc = che_do["nhe"], che_do["enc"]
    W, H, hook_dur = probe_media(video)
    Wo, Ho = kich_thuoc_ra or (W, H)
    thu_nho = f",scale={Wo}:{Ho}:flags={scale_flags(nhe)}" if (Wo, Ho) != (W, H) else ""
    info = dict(kich_thuoc=f"{Wo}x{Ho}" + (f" (thu từ {W}x{H})" if thu_nho else ""))
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        t_png = tdir / "title.png"; i_png = tdir / "illus.png"
        cv2.imwrite(str(t_png), title)           # RGBA
        cv2.imwrite(str(i_png), crop)            # BGR
        # phụ đề: copy .srt vào thư mục tạm và chạy ffmpeg với cwd = thư mục tạm, để filter
        # subtitles chỉ cần tên file ngắn (đường dẫn Windows có ':' và '\' rất khó escape)
        sub_chain = ""
        if srt and sub_style:
            shutil.copyfile(srt, tdir / "sub.srt")
            sub_chain = f"[v0]subtitles=sub.srt:force_style='{sub_style}'[v]"
        v_cuoi = "[v0]" if sub_chain else "[v]"
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               *hwdec_args(enc), "-i", str(video), "-i", str(i_png), "-i", str(t_png)]
        chains = []
        src = "[0:v]"
        if mau_hook:                              # chỉnh màu hình gốc, tiêu đề/ảnh đè lên không bị ảnh hưởng
            chains.append("[0:v]" + ",".join([mau_hook, *lam_net(nhe)]) + "[c0]")
            src = "[c0]"
        chains.append(f"{src}[1:v]overlay={ix}:{iy}:format=auto[a0]")
        if not phan_sau:
            chains.append(f"[a0][2:v]overlay={tx}:{ty}:format=auto{thu_nho},format=yuv420p{v_cuoi}")
            maps = ["-map", "[v]", "-map", "0:a?", "-c:a", "copy"]
        else:
            _, _, D = probe_media(audio)
            if D <= 0:
                sys.exit(f"Không đọc được thời lượng audio: {audio}")
            # input: 0 hook, 1 ảnh, 2 tiêu đề, 3..3+K-1 các clip (đọc dư 0,5s rồi trim trong filter), 3+K giọng đọc
            K = len(phan_sau)
            clip_chains, kich_co = [], set()
            for k, (p, dung, mau) in enumerate(phan_sau):
                bw, bh, _ = probe_media(p)
                kich_co.add(f"{bw}x{bh}")
                cmd += [*hwdec_args(enc), "-t", f"{dung + 0.5:.3f}", "-i", str(p)]
                clip_chains.append(f"[{3 + k}:v]{clip_filter(Wo, Ho, bw, bh, dung, mau, nhe)}[c{k}]")
            cmd += ["-i", str(audio)]
            a_in = 3 + K
            thieu = max(D - sum(d for _, d, _ in phan_sau), 0) + 0.5   # tổng clip ngắn hơn -> đứng hình frame cuối
            # cảnh minh họa: input a_in+1.., mỗi cảnh một overlay bật đúng khoảng [t0, t0+dai] trên phần sau
            mh_chains, nhan_bv = [], "[bv]"
            for k, (p_mh, t0_mh, dai_mh, loai_mh) in enumerate(minh_hoa or []):
                if loai_mh == "anh":
                    cmd += ["-loop", "1", "-framerate", str(FPS_RA), "-t", f"{dai_mh + 0.5:.3f}", "-i", str(p_mh)]
                else:
                    cmd += [*hwdec_args(enc), "-t", f"{dai_mh + 0.5:.3f}", "-i", str(p_mh)]
                # cảnh minh họa luôn PHỦ KÍN khung (phóng + cắt giữa), kể cả clip ngang -> coi như cùng tỉ lệ
                mh_chains.append(f"[{a_in + 1 + k}:v]{clip_filter(Wo, Ho, Wo, Ho, dai_mh, '', nhe)},"
                                 f"setpts=PTS+{t0_mh:.3f}/TB[m{k}]")
                mh_chains.append(f"{nhan_bv}[m{k}]overlay=eof_action=pass:"
                                 f"enable='between(t,{t0_mh:.3f},{t0_mh + dai_mh:.3f})'[bv{k + 1}]")
                nhan_bv = f"[bv{k + 1}]"
            info["minh_hoa"] = len(minh_hoa or [])
            st_hook, st_voice = to_stereo_filter(video), to_stereo_filter(audio)
            norm_hook = norm_voice = ""
            info.update(hook=round(hook_dur, 2), audio=round(D, 2), tong=round(hook_dur + D, 2), so_clip=K,
                        body_size=f"{'/'.join(sorted(kich_co))}->{Wo}x{Ho}")
            if lufs is not None:
                print("Đo & chuẩn hóa âm lượng: hook về mức chuẩn, giọng đọc khớp theo hook...")
                f_hook, m_hook, hook_out = chuan_am(video, st_hook, lufs)
                win = hook_dur if cua_so_khop is None else (cua_so_khop or None)
                f_voice, m_voice, voice_out = chuan_am(audio, st_voice, hook_out + lech_giong, window=win)
                norm_hook, norm_voice = "," + f_hook, "," + f_voice
                info["am_luong"] = (
                    f"hook {m_hook['i']:.1f} -> {hook_out:.1f} LUFS (bù {m_hook['gain_db']:+.1f} dB); "
                    f"giọng đọc đo {'%.0fs đầu' % win if win else 'cả file'} {m_voice['i']:.1f} -> {voice_out:.1f} LUFS "
                    f"(bù {m_voice['gain_db']:+.1f} dB áp cho cả file"
                    + (f", cố ý lệch {lech_giong:+.1f} dB" if lech_giong else "") + ")")
            chains += [
                # hook: video + audio gốc, ép đúng hook_dur để concat không lệch tiếng
                f"[a0][2:v]overlay={tx}:{ty}:format=auto{thu_nho},fps={FPS_RA},format=yuv420p[hv]",
                f"[0:a]atrim=duration={hook_dur:.3f},asetpts=PTS-STARTPTS,"
                f"apad=whole_dur={hook_dur:.3f},{st_hook}{norm_hook}[ha]",
                # phần sau: các clip tắt tiếng (không map audio của clip) nối liền, đưa thẳng về WoxHo,
                # cắt đúng D giây + giọng đọc
                *clip_chains,
                # fps sau concat: tpad cần nhịp frame của luồng, thiếu thì frame bù có mốc thời gian không
                # tăng -> bộ mã hóa bỏ đi (video hụt vài frame so với tiếng)
                "".join(f"[c{k}]" for k in range(K)) + f"concat=n={K}:v=1:a=0,fps={FPS_RA},"
                f"tpad=stop_mode=clone:stop_duration={thieu:.3f},trim=duration={D:.3f},setpts=PTS-STARTPTS[bv]",
                f"[{a_in}:a]atrim=duration={D:.3f},asetpts=PTS-STARTPTS,{st_voice}{norm_voice}[ba]",
                *mh_chains,
                f"[hv][ha]{nhan_bv}[ba]concat=n=2:v=1:a=1{v_cuoi}[a]",
            ]
            maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", AUDIO_BR]
        if sub_chain:
            chains.append(sub_chain)
        cmd += ["-filter_complex", ";".join(chains)] + maps + video_codec_args(enc, nhe, Wo * Ho) + [
            "-movflags", "+faststart", str(out)]
        t0 = time.time()
        subprocess.run(cmd, check=True, cwd=str(tdir))
        info["render_s"] = round(time.time() - t0, 1)
        info["bo_ma_hoa"] = ten_bo_ma_hoa(enc, nhe) + (" [chế độ máy yếu]" if nhe else "")
    return info


# ================================================================== Drive
def download_drive_folder(url: str, dest_root: Path) -> Path:
    try:
        import gdown
    except ImportError:
        sys.exit("Cần cài gdown để tải thư mục Drive: pip install gdown")
    dest = unique_path(dest_root, "drive_" + time.strftime("%Y%m%d_%H%M%S"))
    dest.mkdir(parents=True)
    print(f"Tải thư mục Drive về {dest} ...")
    gdown.download_folder(url=url, output=str(dest), quiet=False, use_cookies=False)
    return dest


# vai trò -> (các tiền tố chấp nhận, viết không dấu/thường ; đuôi file hợp lệ)
VAI_TRO = {
    "video":   (("hook", "mo dau", "clip"),                      (".mp4", ".mov", ".mkv")),
    "tieude":  (("tieu de", "title"),                            (".png", ".jpg", ".jpeg")),
    "anh":     (("minh hoa", "anh minh hoa", "anh", "image"),    (".jpg", ".jpeg", ".png")),
    "body":    (("goc", "video goc", "phan sau", "body"),        (".mov", ".mp4", ".mkv")),
    "audio":   (("giong doc", "giong", "voice", "audio", "tts"), (".mp3", ".wav", ".m4a")),
    "kichban": (("kich ban", "script"),                          (".docx", ".txt", ".md")),
}
TEN_VAI_TRO = dict(video="Hook", tieude="Tiêu đề", anh="Minh họa", body="Gốc", audio="Giọng đọc", kichban="Kịch bản")


def khong_dau(s: str) -> str:
    """'Tiêu Đề' -> 'tieu de' (bỏ dấu, thường, gộp khoảng trắng) để so tiền tố."""
    s = unicodedata.normalize("NFD", s).replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def vai_tro_theo_ten(path: Path) -> tuple[str | None, str]:
    """'Tiêu đề - Ai cũng khổ.png' -> ('tieude', 'Ai cũng khổ'). Không có tiền tố -> (None, stem)."""
    m = re.match(r"^\s*([^-]{1,20}?)\s*-\s*(.+)$", path.stem)
    if m:
        tien_to, ten = khong_dau(m.group(1)), m.group(2).strip()
        for vai, (prefixes, _) in VAI_TRO.items():
            if tien_to in prefixes:
                return vai, ten
    return None, path.stem


def pick_from_folder(folder: Path) -> dict:
    """Nhận diện file trong thư mục theo tiền tố (xem VAI_TRO). File không có tiền tố thì đoán theo
    đuôi như cách cũ. Trả về dict: video, tieude, anh, body?, audio?, ten (tên chung của bộ)."""
    from collections import Counter
    ung_vien: dict[str, list] = {}            # vai trò -> [(tên, path)...]
    con_lai = []
    for p in sorted(x for x in folder.iterdir() if x.is_file()):
        vai, t = vai_tro_theo_ten(p)
        if vai and p.suffix.lower() not in VAI_TRO[vai][1]:
            print(f"CẢNH BÁO: {p.name} có tiền tố '{TEN_VAI_TRO[vai]}' nhưng đuôi {p.suffix} không hợp, bỏ qua")
        elif vai:
            ung_vien.setdefault(vai, []).append((t, p))
        else:
            con_lai.append(p)
    # tên chung của bộ = <tên> xuất hiện nhiều nhất sau các tiền tố
    dem = Counter(t for lst in ung_vien.values() for t, _ in lst)
    ten = dem.most_common(1)[0][0] if dem else None
    found = {}
    for vai, lst in ung_vien.items():
        khop = [p for t, p in lst if t == ten]
        found[vai] = (khop or [p for _, p in lst])[0]   # ưu tiên file cùng <tên> với bộ
        if len(lst) > 1:
            bo = ", ".join(p.name for _, p in lst if p != found[vai])
            print(f"CẢNH BÁO: có {len(lst)} file '{TEN_VAI_TRO[vai]} - ', dùng {found[vai].name}; bỏ: {bo}")
    # dự phòng cho file chưa đặt tên theo quy ước: đoán theo đuôi + cảnh báo để nhắc đổi tên
    imgs = [p for p in con_lai if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    vids = [p for p in con_lai if p.suffix.lower() in (".mp4", ".mov", ".mkv")]
    auds = [p for p in con_lai if p.suffix.lower() in (".mp3", ".wav", ".m4a")]

    def doan(vai: str, p: Path):
        found[vai] = p
        print(f"CẢNH BÁO: {p.name} không có tiền tố, đoán là {TEN_VAI_TRO[vai]} -> "
              f"nên đổi tên thành '{TEN_VAI_TRO[vai]} - {ten or p.stem}{p.suffix}'")

    if "tieude" not in found:
        t = [p for p in imgs if "tieu de" in khong_dau(p.stem)]
        if t:
            doan("tieude", t[0]); imgs.remove(t[0])
    if "anh" not in found and imgs:
        doan("anh", imgs[0])
    if "video" not in found and vids:
        doan("video", vids[0])
    if "audio" not in found and auds:
        doan("audio", auds[0])
    docs = [p for p in con_lai if p.suffix.lower() in (".docx", ".txt")]
    if "kichban" not in found and docs:
        doan("kichban", docs[0])
    thieu = [TEN_VAI_TRO[v] for v in ("video", "tieude", "anh") if v not in found]
    if thieu:
        sys.exit(f"Thư mục {folder} thiếu file: {', '.join(thieu)}. "
                 f"Đặt tên theo quy ước 'Hook - ', 'Tiêu đề - ', 'Minh họa - ' (xem --help).")
    found["ten"] = ten or found["video"].stem
    return found


def ask_files():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    d = str(downloads_dir())
    v = filedialog.askopenfilename(title="Chọn file 'Hook - ...' (clip mở đầu 10s)", initialdir=d,
                                   filetypes=[("Video", "*.mp4 *.mov *.mkv"), ("Tất cả", "*.*")])
    if not v: sys.exit("Đã hủy.")
    t = filedialog.askopenfilename(title="Chọn file 'Tiêu đề - ...' (png)", initialdir=str(Path(v).parent),
                                   filetypes=[("Ảnh", "*.png *.jpg *.jpeg")])
    if not t: sys.exit("Đã hủy.")
    a = filedialog.askopenfilename(title="Chọn file 'Minh họa - ...' (jpg/png)", initialdir=str(Path(v).parent),
                                   filetypes=[("Ảnh", "*.png *.jpg *.jpeg")])
    if not a: sys.exit("Đã hủy.")
    b = filedialog.askopenfilename(title="Chọn VIDEO GỐC quay bác sĩ (sẽ tắt tiếng) - Cancel nếu không có",
                                   initialdir=d, filetypes=[("Video", "*.mov *.mp4 *.mkv"), ("Tất cả", "*.*")])
    au = None
    if b:
        au = filedialog.askopenfilename(title="Chọn file 'Giọng đọc - ...' (mp3)", initialdir=str(Path(v).parent),
                                        filetypes=[("Audio", "*.mp3 *.wav *.m4a")])
        if not au: sys.exit("Có video gốc thì phải chọn giọng đọc.")
    root.destroy()
    return Path(v), Path(t), Path(a), (Path(b) if b else None), (Path(au) if au else None)


# ================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video"); ap.add_argument("--tieude"); ap.add_argument("--anh")
    ap.add_argument("--drive", help="link thư mục Google Drive (chia sẻ công khai) -> tải về rồi ghép")
    ap.add_argument("--thu-muc", help="thư mục trên máy đã đặt tên file theo quy ước (Hook - / Tiêu đề - / ...)")
    ap.add_argument("--phan-sau", help="phần sau (tắt tiếng, nối sau clip 10s): THƯ MỤC clip -> xáo ngẫu nhiên nối tới "
                                       "khi đủ giọng đọc, clip cuối dài hơn thì cắt; hoặc MỘT file video. "
                                       f"Mặc định = thư mục '{THU_MUC_GOC.name}' cạnh tool (khi bộ có giọng đọc)")
    ap.add_argument("--seed", type=int, default=None,
                    help="hạt giống xáo clip (cùng số = cùng thứ tự clip, để làm lại y hệt); mặc định ngẫu nhiên mỗi lần")
    ap.add_argument("--audio", help="giọng đọc lồng vào phần sau; mặc định = file mp3 trong thư mục Drive")
    ap.add_argument("--out", help="thư mục ghi kết quả (mặc định: Downloads)")
    ap.add_argument("--ti-le-tieude", type=float, default=TI_LE_RONG_TIEUDE,
                    help=f"bề rộng tiêu đề / bề rộng video (mặc định {TI_LE_RONG_TIEUDE})")
    ap.add_argument("--khoang-cach", type=float, default=KHOANG_CACH_CAM,
                    help=f"khoảng cách cằm -> tiêu đề, theo chiều cao mặt (mặc định {KHOANG_CACH_CAM})")
    ap.add_argument("--preview-only", action="store_true", help="chỉ xuất ảnh xem trước, không render video")
    ap.add_argument("--lufs", type=float, default=LUFS_MUC_TIEU,
                    help=f"chuẩn hóa âm lượng từng đoạn về mức LUFS này khi có phần sau (mặc định {LUFS_MUC_TIEU:g})")
    ap.add_argument("--khong-chuan-am", action="store_true", help="giữ nguyên âm lượng gốc, không chuẩn hóa")
    ap.add_argument("--cua-so-khop", type=float, default=None,
                    help="số giây ĐẦU của giọng đọc đem so với hook để tính mức bù chung (mặc định = thời lượng hook, 0 = cả file)")
    ap.add_argument("--lech-giong", type=float, default=0.0,
                    help="cố ý cho giọng đọc to/nhỏ hơn hook bấy nhiêu dB (vd -1 = nhỏ hơn 1 dB), mặc định 0")
    ap.add_argument("--khong-chinh-mau", action="store_true",
                    help="tắt chỉnh màu tự động (mặc định bật: auto levels, cân bằng trắng, bão hòa, làm nét như CapCut)")
    ap.add_argument("--cpu", action="store_true",
                    help="ép mã hóa CPU libx264 (bỏ dò NVENC/QSV/AMF); mặc định tự dò GPU NVIDIA, có thì dùng NVENC/NVDEC. "
                         "Không kèm --manh thì vào chế độ máy yếu")
    ap.add_argument("--nhe", action="store_true",
                    help="ép CHẾ ĐỘ MÁY YẾU ở khâu render ffmpeg (mặc định tự bật khi không có NVIDIA NVENC): mã hóa "
                         "h264_qsv/h264_amf nếu chạy được, không thì libx264 veryfast crf 20; scale bicubic; bỏ làm nét. "
                         "Model nhận diện phụ đề KHÔNG đổi")
    ap.add_argument("--manh", action="store_true",
                    help="ép CHẾ ĐỘ ĐẦY ĐỦ (scale lanczos + làm nét, libx264 medium crf 18) dù không có GPU NVIDIA")
    ap.add_argument("--do-phan-giai", type=int, default=0, metavar="N",
                    help="xuất video có cạnh ngắn = N px, vd 720 -> 720x1280 (hook 1080p thu xuống, phần sau đưa thẳng về "
                         "720p) cho máy rất yếu; mặc định 0 = giữ kích thước hook (1080x1920). Không phóng to")
    ap.add_argument("--kich-ban", help="file kịch bản (docx/txt) làm chuẩn chữ cho phụ đề; mặc định = 'Kịch bản - ...' trong thư mục")
    ap.add_argument("--khong-sub", action="store_true", help="không làm phụ đề (mặc định có nếu tìm thấy kịch bản)")
    ap.add_argument("--model-sub", default=None, help="model faster-whisper lấy mốc thời gian (mặc định large-v3-turbo)")
    ap.add_argument("--thu-muc-model", default=None, help="thư mục cache model (mặc định: models/ cạnh tool -> ../whisper_cache -> HF)")
    ap.add_argument("--sub-font", default="Arial", help="font phụ đề (mặc định Arial)")
    ap.add_argument("--sub-co", type=float, default=11, help="cỡ chữ phụ đề theo thang 288 (11 ~ 73px trên video 1920)")
    ap.add_argument("--sub-le-duoi", type=int, default=45, help="lề dưới phụ đề theo thang 288 (45 ~ 300px trên video 1920)")
    ap.add_argument("--minh-hoa", default=None, metavar="SHEET|CSV",
                    help="kho cảnh minh họa theo từ khóa (link Google Sheet tab 'Kho minh họa' hoặc file CSV); cần kịch bản + "
                         "phần sau. AI chọn câu/từ khóa, tool chèn clip đúng giây câu đó (xem minh_hoa.py)")
    ap.add_argument("--minh-hoa-ai", default="gpt", choices=["gpt", "claude", "gemini"], help="AI chọn từ khóa (mặc định gpt)")
    ap.add_argument("--minh-hoa-model", default=None, help="model của AI đó (mặc định của CLI)")
    ap.add_argument("--minh-hoa-giay", type=float, default=6.0, help="mỗi cảnh minh họa tối đa bấy nhiêu giây (mặc định 6)")
    ap.add_argument("--minh-hoa-ti-le", type=float, default=0.45, help="tổng minh họa tối đa bấy nhiêu phần thời lượng phần sau (0.45)")
    ap.add_argument("--khong-minh-hoa", action="store_true", help="bỏ cảnh minh họa dù có --minh-hoa")
    args = ap.parse_args()
    if args.nhe and args.manh:
        sys.exit("--nhe và --manh loại trừ nhau, chọn một.")
    if args.do_phan_giai < 0:
        sys.exit("--do-phan-giai phải >= 0 (0 = giữ kích thước hook).")

    out_dir = Path(args.out) if args.out else downloads_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    body = Path(args.phan_sau) if args.phan_sau else None
    audio = Path(args.audio) if args.audio else None
    kich_ban = Path(args.kich_ban) if args.kich_ban else None
    ten = None
    if args.drive or args.thu_muc:
        folder = download_drive_folder(args.drive, out_dir) if args.drive else Path(args.thu_muc)
        if not folder.is_dir():
            sys.exit(f"Không thấy thư mục: {folder}")
        f = pick_from_folder(folder)
        video, tieude, anh, ten = f["video"], f["tieude"], f["anh"], f["ten"]
        body, audio = body or f.get("body"), audio or f.get("audio")
        kich_ban = kich_ban or f.get("kichban")
    elif args.video and args.tieude and args.anh:
        video, tieude, anh = Path(args.video), Path(args.tieude), Path(args.anh)
    else:
        video, tieude, anh, b, au = ask_files()
        body, audio = body or b, audio or au
    # phần sau mặc định = kho clip "video gốc" của dự án (chỉ khi bộ có giọng đọc); --phan-sau để chọn khác
    if body is None and audio and THU_MUC_GOC.is_dir():
        body = THU_MUC_GOC
    if body and not audio:
        sys.exit("Có video phần sau thì cần giọng đọc: --audio hoặc file 'Giọng đọc - ....mp3' trong thư mục.")
    for p in (video, tieude, anh, body, audio, kich_ban):
        if p and not p.exists():
            sys.exit(f"Không thấy file: {p}")
    ten = ten or vai_tro_theo_ten(video)[1]       # tên chung của bộ -> đặt tên file ra
    # phụ đề chỉ ở PHẦN SAU (10s hook đã có tiêu đề + ảnh minh họa nên để sạch) -> không có phần sau thì bỏ
    lam_sub = bool(kich_ban) and bool(body) and not args.khong_sub
    # cảnh minh họa theo từ khóa: cũng cần kịch bản khớp giọng đọc (lấy giây từng câu) + phần sau
    lam_minh_hoa = bool(kich_ban) and bool(body) and bool(args.minh_hoa) and not args.khong_minh_hoa

    # các đoạn phần sau: thư mục -> xáo ngẫu nhiên clip tới khi đủ giọng đọc; một file -> dùng file đó
    clips_sau: list[tuple[Path, float]] = []
    if body:
        _, _, D = probe_media(audio)
        if body.is_dir():
            kho = liet_ke_clip(body)
            if not kho:
                sys.exit(f"Thư mục {body} không có clip video nào ({', '.join(DUOI_VIDEO)}).")
            clips_sau = chon_clip_ngau_nhien(kho, D, args.seed)
        else:
            clips_sau = [(body, round(min(thoi_luong_hinh(body), D), 3))]

    print(f"Bộ      : {ten}")
    print(f"Hook     : {video.name}")
    print(f"Tiêu đề  : {tieude.name}")
    print(f"Minh họa : {anh.name}")
    if body:
        if body.is_dir():
            dai = dict(kho)
            tong_kho = sum(dai.values())
            print(f"Gốc      : thư mục {body.name} — {len(kho)} clip ({tong_kho:.0f}s), ghép ngẫu nhiên tới đủ giọng "
                  f"đọc {D:.1f}s (tắt tiếng)" + ("; giọng đọc dài hơn cả kho -> có clip dùng lại" if D > tong_kho else ""))
            print(f"Phần sau : {len(clips_sau)} clip: " + " → ".join(
                f"{p.name} {dung:.1f}s" + (f" (cắt từ {dai[p]:.1f}s)" if dung < dai[p] - 0.05 else "")
                for p, dung in clips_sau))
        else:
            print(f"Gốc      : {body.name}  (tắt tiếng)")
        print(f"Giọng đọc: {audio.name}")
    else:
        print("Phần sau : không có (chỉ ghép clip hook)")
    print(f"Kịch bản : {kich_ban.name if kich_ban else 'không có -> không làm phụ đề'}"
          + ("  (--khong-sub: bỏ phụ đề)" if kich_ban and args.khong_sub else "")
          + ("  (chỉ có hook -> không làm phụ đề)" if kich_ban and not body else ""))

    # chế độ render quyết định sớm (trước cả nhận diện mặt) để --preview-only cũng thấy; chỉ ảnh hưởng ffmpeg
    ffmpeg = need_ffmpeg()
    che_do = chon_che_do(ffmpeg, nhe=args.nhe, manh=args.manh, force_cpu=args.cpu)
    print(f"Chế độ   : {mo_ta_che_do(che_do)}")
    print(f"Bộ mã hóa: {ten_bo_ma_hoa(che_do['enc'], che_do['nhe'])}")

    model = ensure_model()
    print("Nhận diện khuôn mặt (YuNet)...")
    face, (W, H, fps, dur) = detect_face(video, model)
    x, y, w, h, conf, t, frame = face
    print(f"-> Chọn frame t={t:.1f}s, mặt x={x} y={y} w={w} h={h} (tin cậy {conf:.2f}); video {W}x{H} {dur:.1f}s")
    kt_ra = kich_thuoc_ra(W, H, args.do_phan_giai)
    if kt_ra != (W, H):
        print(f"Kích thước ra: {kt_ra[0]}x{kt_ra[1]} (thu từ {W}x{H}, --do-phan-giai {args.do_phan_giai})")
    elif args.do_phan_giai:
        print(f"Kích thước ra: giữ {W}x{H} (--do-phan-giai {args.do_phan_giai} không nhỏ hơn cạnh ngắn hook, không phóng to)")

    title_rgba = title_with_alpha(imread_unicode(tieude))
    illus = imread_unicode(anh, cv2.IMREAD_COLOR)
    title_item, illus_item, info = layout(W, H, face, title_rgba, illus, args.ti_le_tieude, args.khoang_cach)
    print(f"Bố cục   : tiêu đề (x,y,w,h)={info['tieude']}  ảnh (x,y,w,h)={info['anh']}  "
          f"phóng ảnh x{info['ti_le_phong_anh']} cắt mỗi bên {info['cat_moi_ben']}px")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    preview_path = unique_path(out_dir, f"{ten}_ghep_{stamp}_preview.jpg")
    imwrite_unicode(preview_path, composite_preview(frame, title_item, illus_item))
    print(f"Xem trước: {preview_path}")

    mau_hook = ""
    mau_clips = [""] * len(clips_sau)
    if not args.khong_chinh_mau:
        print("Phân tích màu để chỉnh tự động...")
        p_hook = phan_tich_mau(video, n=6)
        mau_hook = chinh_mau_filter(p_hook)
        print(f"  hook    : {p_hook}")
        items = [(video, mau_hook, [dur * 0.1, dur * 0.5, dur * 0.9])]
        if len(clips_sau) == 1:                   # một video gốc dài: như trước, 12 frame, 4 ảnh so sánh
            p, L = clips_sau[0]
            p_body = phan_tich_mau(p, n=12, max_t=L)
            mau_clips[0] = chinh_mau_filter(p_body)
            print(f"  phần sau: {p_body}")
            items.append((p, mau_clips[0], [L * k for k in (0.08, 0.35, 0.62, 0.9)]))
        elif clips_sau:                           # nhiều clip: chỉnh màu RIÊNG từng clip (mỗi cảnh quay một khác)
            cache: dict[Path, str] = {}
            for i, (p, dung) in enumerate(clips_sau):
                if p not in cache:
                    cache[p] = chinh_mau_filter(phan_tich_mau(p, n=4, max_t=dung))
                mau_clips[i] = cache[p]
            print(f"  phần sau: chỉnh màu riêng {len(cache)} clip")
            items += [(p, mau_clips[i], [dung * 0.5]) for i, (p, dung) in enumerate(clips_sau[:6])]
        mau_preview = unique_path(out_dir, f"{ten}_ghep_{stamp}_mau_truoc_sau.jpg")
        preview_mau(items, mau_preview, ffmpeg, nhe=che_do["nhe"])
        print(f"So sánh màu trước/sau: {mau_preview}")
    if args.preview_only:
        return

    srt_path = None
    tu_khop = None
    if lam_sub or lam_minh_hoa:
        import viet_sub
        _, _, D = probe_media(audio)
        # hook vẫn đưa vào nhận diện để căn đúng mốc 3 câu đầu kịch bản, nhưng bo_truoc=dur
        # -> không ghi câu nào trong 10s hook; phụ đề bắt đầu từ phần sau
        nguon = [(video, 0.0, dur), (audio, dur, None)]
        srt_path = unique_path(out_dir, f"{ten}_{stamp}.srt")
        print("Phụ đề   : nhận diện giọng nói lấy mốc thời gian, chữ lấy theo kịch bản (chỉ phần sau)..." if lam_sub
              else "Khớp lời : nhận diện giọng nói lấy mốc thời gian từng câu (cho cảnh minh họa)...")
        tk = viet_sub.tao_srt(kich_ban, nguon, dur + D, srt_path, ten_model=args.model_sub or viet_sub.MODEL_MAC_DINH,
                              thu_muc_model=Path(args.thu_muc_model) if args.thu_muc_model else None,
                              bo_truoc=dur, log=lambda s: print("  " + s))
        tu_khop = tk.get("tu")
        if not lam_sub:                              # chỉ cần mốc câu, không đốt phụ đề
            srt_path.unlink(missing_ok=True)
            srt_path = None
    canh_mh = []
    if lam_minh_hoa and tu_khop:
        import minh_hoa
        print(f"Minh họa : {args.minh_hoa_ai} chọn câu + từ khóa theo kho {args.minh_hoa} ...")
        kq_mh = minh_hoa.chuan_bi(tu_khop, kho_nguon=args.minh_hoa, tong_giay=D, tu_giay=dur, nha=args.minh_hoa_ai,
                                  model=args.minh_hoa_model, toi_da_giay=args.minh_hoa_giay, ti_le_toi_da=args.minh_hoa_ti_le,
                                  seed=args.seed, ten_bo=ten, log=lambda s: print("  " + s))
        # mốc trong video cuối -> mốc trong phần sau (trừ thời lượng hook)
        canh_mh = [(c.clip.duong_dan, c.start - dur, c.end - c.start, c.clip.loai) for c in kq_mh["canh"]]
        if kq_mh["canh"]:
            print(f"Minh họa : {len(kq_mh['canh'])} cảnh: " + minh_hoa.mo_ta_canh(kq_mh["canh"]))
        else:
            print("Minh họa : không chèn cảnh nào" + (f" ({kq_mh['loi']})" if kq_mh["loi"] else ""))
    tag = "full" if body else "ghep"
    out_path = unique_path(out_dir, f"{ten}_{tag}_{stamp}.mp4")
    print("Đang render ffmpeg..." + (" (có phần sau, mã hóa CPU, chờ vài phút)"
                                    if body and che_do["enc"]["loai"] == "x264" else ""))
    sub_style = None
    if srt_path:
        import viet_sub
        sub_style = viet_sub.force_style(args.sub_font, args.sub_co, args.sub_le_duoi)
    phan_sau = [(p, dung, mau_clips[i]) for i, (p, dung) in enumerate(clips_sau)] or None
    info = render(video, title_item, illus_item, out_path, ffmpeg, phan_sau, audio,
                  lufs=None if args.khong_chuan_am else args.lufs,
                  mau_hook=mau_hook, che_do=che_do,
                  cua_so_khop=args.cua_so_khop, lech_giong=args.lech_giong,
                  srt=srt_path, sub_style=sub_style, kich_thuoc_ra=kt_ra, minh_hoa=canh_mh)
    if info.get("hook"):
        print(f"Thời lượng: hook {info['hook']}s + phần sau {info['audio']}s ({info['so_clip']} clip"
              + (f", {info['minh_hoa']} cảnh minh họa" if info.get("minh_hoa") else "") + f", {info['body_size']}) = {info['tong']}s")
    if info.get("am_luong"):
        print(f"Âm lượng : {info['am_luong']}")
    print(f"Render   : {info.get('render_s', '?')}s bằng {info.get('bo_ma_hoa', '?')}, {info.get('kich_thuoc', '?')}")
    if srt_path:
        print(f"Phụ đề   : {srt_path}  (đã đốt vào video)")
    print(f"XONG     : {out_path}")


if __name__ == "__main__":
    main()
    # Đã nạp model whisper thì thoát thẳng: bỏ qua bước Python hủy WhisperModel
    # (ctranslate2 có thể abort 0xC0000409 khi hủy model GPU sau file dài).
    if sys.modules.get("viet_sub") and getattr(sys.modules["viet_sub"], "_models", None):
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
