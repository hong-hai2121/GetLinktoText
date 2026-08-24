# -*- coding: utf-8 -*-
"""Bước 1 — Nhận diện audio thành chữ kèm mốc thời gian (faster-whisper, offline).

Cách chạy:  python nhandien_audio.py mau/audio_mau.m4a
Kết quả  :  transcript.json nằm cùng thư mục với file audio.
"""
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cauhinh import WHISPER_CACHE

MODEL_REPO = "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"


def _thu_muc_model() -> Path:
    """Snapshot mới nhất của model trong whisper_cache (offline hoàn toàn)."""
    snaps = WHISPER_CACHE / MODEL_REPO / "snapshots"
    ds = sorted(p for p in snaps.iterdir() if p.is_dir())
    if not ds:
        raise FileNotFoundError(f"Không thấy snapshot model trong {snaps}")
    return ds[-1]


def nap_model():
    from faster_whisper import WhisperModel

    local_dir = str(_thu_muc_model())
    try:
        print("📂 Nạp large-v3-turbo (CUDA, float16)...")
        return WhisperModel(local_dir, device="cuda", compute_type="float16",
                            local_files_only=True)
    except Exception as e:
        print(f"⚠️ CUDA lỗi ({e}) → chuyển sang CPU int8 (chậm hơn).")
        return WhisperModel(local_dir, device="cpu", compute_type="int8",
                            local_files_only=True)


def nhan_dien(audio: Path) -> Path:
    model = nap_model()
    t0 = time.time()
    segments, info = model.transcribe(str(audio), vad_filter=True)
    print(f"🎧 Ngôn ngữ: {info.language} — thời lượng {info.duration:.0f}s")

    doan = []
    for seg in segments:
        doan.append({
            "bat_dau": round(seg.start, 2),
            "ket_thuc": round(seg.end, 2),
            "noi_dung": seg.text.strip(),
        })
        if len(doan) % 25 == 0:
            print(f"  ... {len(doan)} đoạn, đến {seg.end:.0f}s / {info.duration:.0f}s")

    ra = audio.parent / "transcript.json"
    ra.write_text(json.dumps({
        "audio": audio.name,
        "ngon_ngu": info.language,
        "thoi_luong": round(info.duration, 2),
        "doan": doan,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {len(doan)} đoạn trong {time.time() - t0:.0f}s → {ra}")
    return ra


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Cách dùng: python nhandien_audio.py <file audio>")
    nhan_dien(Path(sys.argv[1]).resolve())
