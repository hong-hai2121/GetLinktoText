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


def _doc_am_thanh(path, log):
    """Giải mã âm thanh về 16 kHz, trả về (mảng mono, (trái, phải) hoặc None).
    Video 2 kênh trái/phải NGƯỢC PHA (gặp 26/10/2026 với file 1038: tương quan -0,98) thì trộn mono
    sẽ triệt tiêu giọng nói, chỉ còn nhạc nền -> Whisper ra 0 đoạn. Phát hiện bằng RMS mono nhỏ hơn
    hẳn RMS từng kênh và nhận diện bằng kênh to hơn thay vì mono."""
    import numpy as np
    from faster_whisper import decode_audio
    st = decode_audio(str(path), sampling_rate=16000, split_stereo=True)
    if not isinstance(st, tuple) or len(st) != 2:
        return st, None
    L, R = st
    if len(L) == 0 or len(R) == 0:
        return L if len(L) else R, None
    rms = lambda x: float(np.sqrt(np.mean(np.square(x, dtype=np.float32))))   # noqa: E731
    mono = (L + R) / 2
    r_mono, r_l, r_r = rms(mono), rms(L), rms(R)
    if max(r_l, r_r) > 0.01 and r_mono < 0.5 * max(r_l, r_r):
        kenh = "trái" if r_l >= r_r else "phải"
        log(f"  ⚠ Âm thanh 2 kênh ngược pha (trộn mono còn {r_mono:.3f}, từng kênh {max(r_l, r_r):.3f}) "
            f"-> nhận diện bằng kênh {kenh}.")
        return (L if r_l >= r_r else R), (L, R)
    return mono, (L, R)


def nhan_dien(path, log=print, gioi_han=GIOI_HAN_GIAY):
    """Trả về (văn bản đầy đủ, danh sách đoạn [(start, end, text)]).
    Video dài hơn `gioi_han` giây (0 = không giới hạn) -> raise VideoQuaDai TRƯỚC khi nạp model."""
    giay = thoi_luong(path)
    if giay is not None and gioi_han and giay > gioi_han:
        raise VideoQuaDai(path, giay, gioi_han)
    log(f"Thời lượng: {int(giay // 60)}:{int(giay % 60):02d}" if giay is not None else "Thời lượng: (không đo được)")
    m = nap_model(log)
    t0 = time.time()
    log(f"Đang nhận diện giọng nói: {Path(path).name}")
    try:
        am_thanh, kenh = _doc_am_thanh(path, log)
    except Exception as e:                      # noqa: BLE001 — giải mã riêng hỏng thì để Whisper tự đọc file
        log(f"  (không tách kênh được: {str(e)[:80]} — để Whisper tự đọc file)")
        am_thanh, kenh = str(path), None

    def chay(nguon):
        segs, info = m.transcribe(nguon, language="vi", beam_size=5, vad_filter=True,
                                  vad_parameters=dict(min_silence_duration_ms=400),
                                  condition_on_previous_text=False)
        out = []
        for s in segs:
            t = s.text.strip()
            if t:
                out.append((s.start, s.end, t))
        return out, info

    doan, info = chay(am_thanh)
    if len(doan) < 2 and kenh is not None:
        # trộn mono không ra gì (vd. ngược pha một phần) -> thử lại bằng kênh trái
        log("  (trộn mono không ra giọng nói -> thử lại bằng kênh trái)")
        doan2, info2 = chay(kenh[0])
        if len(doan2) > len(doan):
            doan, info = doan2, info2
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
