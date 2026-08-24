# -*- coding: utf-8 -*-
"""myedit — biến audio giọng nói thành video có ảnh minh họa.

Chạy cả chuỗi:   python chay.py mau/audio_mau.m4a
Chạy từng bước:  python chay.py mau/audio_mau.m4a --buoc nhandien
                 (nhandien | chiacanh | taianh | ghep)

Chuỗi xử lý: nhận diện audio → chia cảnh (Gemini) → tải ảnh → ghép video.
Bước nào đã có kết quả thì tự bỏ qua; muốn làm lại bước nào thì xóa file
kết quả của bước đó (transcript.json / canh.json / anh/ / clips/).
"""
import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from nhandien_audio import nhan_dien
from chia_canh import chia_canh
from tai_anh import tai_anh
from ghep_video import ghep_video


def chay(audio: Path, buoc: str | None = None) -> None:
    transcript = audio.parent / "transcript.json"
    canh = audio.parent / "canh.json"

    if buoc in (None, "nhandien"):
        if transcript.exists():
            print(f"⏭️ Đã có {transcript.name} — bỏ qua nhận diện")
        else:
            print("── Bước 1/4: nhận diện audio ──")
            nhan_dien(audio)
        if buoc:
            return

    if buoc in (None, "chiacanh"):
        if canh.exists():
            print(f"⏭️ Đã có {canh.name} — bỏ qua chia cảnh")
        else:
            print("── Bước 2/4: chia cảnh + từ khóa ảnh ──")
            if chia_canh(transcript) is None:
                return  # chưa có GEMINI_API_KEY — đã in hướng dẫn dán tay
        if buoc:
            return

    if buoc in (None, "taianh"):
        print("── Bước 3/4: tải ảnh minh họa ──")
        tai_anh(canh)
        if buoc:
            return

    if buoc in (None, "ghep"):
        print("── Bước 4/4: ghép video ──")
        ghep_video(canh, audio)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Audio giọng nói → video ảnh minh họa")
    ap.add_argument("audio", help="file audio giọng nói")
    ap.add_argument("--buoc", choices=["nhandien", "chiacanh", "taianh", "ghep"],
                    help="chỉ chạy 1 bước thay vì cả chuỗi")
    a = ap.parse_args()
    chay(Path(a.audio).resolve(), a.buoc)
