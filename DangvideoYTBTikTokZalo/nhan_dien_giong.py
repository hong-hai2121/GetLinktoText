# -*- coding: utf-8 -*-
"""Bóc băng giọng nói từ video/audio bằng faster-whisper large-v3-turbo (model user chốt, KHÔNG hạ nhỏ hơn).

Dùng cho tính năng "tạo nội dung SEO": video -> văn bản thô -> gửi Gemini sửa + viết mô tả.
Model tìm theo thứ tự: models/ cạnh tool -> ../whisper_cache (dùng chung GetTextFromLink) -> cache HF.
Model nạp xong giữ suốt phiên, không del (ctranslate2 có thể abort khi hủy model GPU).

Chạy riêng:  python nhan_dien_giong.py "video.mp4" [ra.txt]
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = "large-v3-turbo"
THU_MUC_MODEL = [HERE / "models", HERE.parent / "whisper_cache"]
GIOI_HAN_GIAY = 180        # video dài hơn 3 phút -> KHÔNG bóc băng, báo VideoQuaDai để app ghi lại link
_models = {}


class VideoQuaDai(Exception):
    """Video dài hơn giới hạn — bỏ qua, không bóc băng."""

    def __init__(self, path, giay, gioi_han=GIOI_HAN_GIAY):
        self.path, self.giay, self.gioi_han = str(path), float(giay), gioi_han
        super().__init__(f"Video dài hơn {gioi_han // 60} phút ({int(giay // 60)}:{int(giay % 60):02d}) — bỏ qua: {Path(path).name}")


def thoi_luong(path):
    """Thời lượng (giây) qua ffprobe; không đo được thì trả về None."""
    import json
    import shutil
    import subprocess
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None


def nap_model(log=print):
    if MODEL in _models:
        return _models[MODEL]
    import ctranslate2
    from faster_whisper import WhisperModel
    gpu = ctranslate2.get_cuda_device_count() > 0
    device, ctype = ("cuda", "float16") if gpu else ("cpu", "int8")
    root = next((d for d in THU_MUC_MODEL if d.is_dir()), None)
    log(f"Nạp model {MODEL} ({'GPU ' + ctype if gpu else 'CPU ' + ctype})...")
    t0 = time.time()
    m = WhisperModel(MODEL, device=device, compute_type=ctype, download_root=str(root) if root else None)
    log(f"  model sẵn sàng sau {time.time() - t0:.1f}s")
    _models[MODEL] = m
    return m


def nhan_dien(path, log=print, gioi_han=GIOI_HAN_GIAY):
    """Trả về (văn bản đầy đủ, danh sách đoạn [(start, end, text)]).
    Video dài hơn `gioi_han` giây (mặc định 3 phút) -> raise VideoQuaDai TRƯỚC khi nạp model."""
    giay = thoi_luong(path)
    if giay is not None and gioi_han and giay > gioi_han:
        raise VideoQuaDai(path, giay, gioi_han)
    log(f"Thời lượng: {int(giay // 60)}:{int(giay % 60):02d}" if giay is not None else "Thời lượng: (không đo được)")
    m = nap_model(log)
    t0 = time.time()
    log(f"Đang bóc băng: {Path(path).name}")
    segs, info = m.transcribe(str(path), language="vi", beam_size=5, vad_filter=True,
                              vad_parameters=dict(min_silence_duration_ms=400),
                              condition_on_previous_text=False)
    doan = []
    for s in segs:
        t = s.text.strip()
        if t:
            doan.append((s.start, s.end, t))
    van_ban = " ".join(t for _, _, t in doan)
    log(f"  xong {len(doan)} đoạn, {len(van_ban)} ký tự, {time.time() - t0:.1f}s (thời lượng {info.duration:.0f}s)")
    return van_ban, doan


def van_ban_co_moc(doan):
    """Văn bản kèm mốc [mm:ss] đầu mỗi đoạn — để Gemini viết chapters đúng giờ."""
    out = []
    for st, _, t in doan:
        out.append(f"[{int(st // 60):02d}:{int(st % 60):02d}] {t}")
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".txt")
    try:
        vb, d = nhan_dien(src)
    except VideoQuaDai as e:
        print("⏹", e)
        sys.stdout.flush()
        sys.exit(2)
    out.write_text(van_ban_co_moc(d), encoding="utf-8")
    print("Đã ghi:", out)
    sys.stdout.flush()
    import os
    os._exit(0)
