# -*- coding: utf-8 -*-
"""
tachGiongNoi.py

Chức năng:
- Chọn thư mục chứa nhiều file .mp4.
- Mỗi file .mp4:
    + Extract audio sang WAV bằng ffmpeg (giữ stereo).
    + (Tùy chọn) nếu bật SRT và có file SRT tương ứng trong:
          D:\Python\GetLinktoText\SourceTruyen\dSRT
      thì chỉ xử lý (tách giọng) ở những đoạn có sub.
    + Dùng Demucs (htdemucs) ước lượng giọng (vocals),
      sau đó lấy:
          bg_novoice = audio_goc - alpha * vocals_est
      để giữ nhạc + SFX gần giống bản gốc nhất, chỉ giảm giọng.
- Kết quả lưu tại:
    D:\Python\GetLinktoText\SourceTruyen\XulyAmThanh\AmThanh_peaks

Output mỗi video:
    <tenfile>_voice.wav       : giọng nói / giọng hát
    <tenfile>_bg_novoice.wav  : âm thanh gốc đã giảm/loại giọng
"""

import os
import sys
import tempfile
import subprocess

import torch
import torchaudio
from demucs.pretrained import get_model
from demucs.apply import apply_model

import srt
import tkinter as tk
from tkinter import filedialog

# ==== CẤU HÌNH ĐƯỜNG DẪN ====
OUTPUT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\XulyAmThanh\AmThanh_peaks"
SRT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\dSRT"
# hệ số trừ giọng khỏi bản gốc: 0.5–0.9
ALPHA = 0.75

# Ưu tiên dùng GPU (CUDA)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def ensure_output_dir():
    if not os.path.isdir(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)


def ffmpeg_extract_wav(input_mp4, out_wav, sample_rate=32000):
    """
    Extract audio từ mp4 sang wav (stereo).
    Dùng sample_rate thấp hơn (32k) để xử lý nhanh hơn.
    Cần ffmpeg trong PATH.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_mp4,
        "-vn",
        "-ar", str(sample_rate),
        out_wav
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        print(f"[LỖI] ffmpeg không extract được audio từ: {input_mp4}")
        return False
    return True


def load_audio(path):
    wav, sr = torchaudio.load(path)
    return wav, sr


def save_audio(path, wav, sr):
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    torchaudio.save(path, wav.cpu(), sample_rate=sr)


def load_sub_ranges(srt_path, total_duration, margin=0.3):
    """
    Đọc file .srt, trả về list (start_sec, end_sec)
    đã cộng margin và merge các đoạn chồng nhau.
    """
    with open(srt_path, "r", encoding="utf-8") as f:
        text = f.read()
    subs = list(srt.parse(text))

    ranges = []
    for sub in subs:
        start = max(sub.start.total_seconds() - margin, 0.0)
        end = min(sub.end.total_seconds() + margin, total_duration)
        if end > start:
            ranges.append((start, end))

    if not ranges:
        return []

    ranges.sort()
    merged = [ranges[0]]
    for s, e in ranges[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e + 0.1:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def prepare_channels_for_model(model, segment, original_channels):
    """
    Điều chỉnh số kênh để phù hợp với model (thường là 2),
    nhưng vẫn biết file gốc ban đầu có bao nhiêu kênh.
    """
    expected_ch = getattr(model, "audio_channels", 2)
    ch, t = segment.shape

    if ch < expected_ch:
        seg = segment.repeat(expected_ch // ch + (expected_ch % ch > 0), 1)[:expected_ch, :]
    elif ch > expected_ch:
        seg = segment[:expected_ch, :]
    else:
        seg = segment

    return seg, expected_ch, original_channels


def estimate_vocals_segment(model, segment, base_name, tag=""):
    """
    Chạy Demucs trên một đoạn nhỏ [C, T] để ước lượng vocals.
    Trả về vocals có cùng số kênh với đoạn gốc (1 hoặc 2).
    """
    original_channels = segment.shape[0]
    seg_proc, exp_ch, orig_ch = prepare_channels_for_model(model, segment, original_channels)

    # chuẩn hóa tránh clipping
    max_abs = seg_proc.abs().max()
    if max_abs > 0:
        seg_proc = seg_proc / max_abs

    mix = seg_proc.to(DEVICE).unsqueeze(0)

    with torch.no_grad():
        print(f"    → Demucs VOCALS {base_name} {tag} ...")
        sources = apply_model(model, mix)[0]  # [num_sources, C, T]

    source_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
    try:
        vocals_idx = source_names.index("vocals")
    except ValueError:
        print("    [LỖI] Model không có stem 'vocals'.")
        return None

    vocals = sources[vocals_idx]  # [C, T]

    # Nếu file gốc 1 kênh, convert vocals về 1 kênh
    if orig_ch == 1 and vocals.shape[0] > 1:
        vocals = vocals.mean(dim=0, keepdim=True)

    # Cắt cho khớp độ dài đoạn gốc
    min_len = min(segment.shape[1], vocals.shape[1])
    vocals = vocals[:, :min_len]

    return vocals.cpu()


def soft_subtract_background(full_wav, vocals_est, alpha=ALPHA):
    """
    full_wav   : audio gốc [C, T]
    vocals_est : ước lượng giọng [C, T] (cùng shape hoặc nhỏ hơn)
    alpha      : hệ số trừ.
    """
    ch, t = full_wav.shape
    ch_v, t_v = vocals_est.shape

    min_len = min(t, t_v)
    full_wav = full_wav[:, :min_len]
    vocals_est = vocals_est[:, :min_len]

    bg = full_wav - alpha * vocals_est
    bg = torch.clamp(bg, -1.0, 1.0)
    return bg, min_len


def process_one_wav_with_optional_srt(model, wav_path, srt_path, base_name, use_srt=True):
    """
    Xử lý 1 file wav:
    - Nếu use_srt=True và có srt -> chỉ trừ giọng ở đoạn có thoại.
    - Nếu use_srt=False hoặc không có srt -> trừ giọng trên toàn file.
    Trả về (voice_out, bg_out, sr)
    """
    wav, sr = load_audio(wav_path)
    total_duration = wav.shape[1] / sr
    ch, t = wav.shape

    has_srt = use_srt and os.path.isfile(srt_path)

    if not has_srt:
        if use_srt:
            print("  Không tìm thấy SRT, tách trên toàn file.")
        else:
            print("  Đã tắt SRT, tách trên toàn file.")
        # ước lượng vocals toàn file
        vocals_est = estimate_vocals_segment(model, wav, base_name, tag="[FULL]")
        if vocals_est is None:
            return None, None, sr

        bg_out, min_len = soft_subtract_background(wav, vocals_est, alpha=ALPHA)
        voice_out = torch.zeros_like(wav)
        voice_out[:, :min_len] = vocals_est[:, :min_len]
        return voice_out, bg_out, sr

    # Có SRT và đang bật SRT -> chỉ xử lý đoạn có thoại
    print(f"  Dùng SRT: {srt_path}")
    ranges = load_sub_ranges(srt_path, total_duration, margin=0.3)
    print(f"  Có {len(ranges)} đoạn thoại sau khi merge.")

    voice_out = torch.zeros_like(wav)   # mặc định im lặng
    bg_out = wav.clone()                # mặc định = audio gốc

    if not ranges:
        print("  SRT không có đoạn thoại hợp lệ, giữ nguyên bg, voice im lặng.")
        return voice_out, bg_out, sr

    for i, (start_sec, end_sec) in enumerate(ranges, start=1):
        s = int(start_sec * sr)
        e = int(end_sec * sr)
        if e <= s or s >= t:
            continue
        e = min(e, t)

        print(f"  [{i}/{len(ranges)}] Segment {start_sec:.2f}–{end_sec:.2f} s")
        segment = wav[:, s:e]
        vocals_seg = estimate_vocals_segment(
            model, segment, base_name, tag=f"[{i}/{len(ranges)}]"
        )
        if vocals_seg is None:
            continue

        seg_len = min(segment.shape[1], vocals_seg.shape[1])
        # ghi vocals vào voice_out
        voice_out[:, s:s+seg_len] = vocals_seg[:, :seg_len]
        # trừ giọng trong bg_out
        bg_seg = segment[:, :seg_len] - ALPHA * vocals_seg[:, :seg_len]
        bg_seg = torch.clamp(bg_seg, -1.0, 1.0)
        bg_out[:, s:s+seg_len] = bg_seg

    return voice_out, bg_out, sr


def select_folder_gui():
    root = tk.Tk()
    root.withdraw()
    folder_selected = filedialog.askdirectory(title="Chọn thư mục chứa các file .mp4")
    root.destroy()
    return folder_selected


def main():
    print("=== TÁCH GIỌNG HÁT / GIỌNG NÓI RA KHỎI ÂM THANH GỐC (GPU nếu có) ===")
    print(f"Sử dụng thiết bị: {DEVICE}")

    folder = select_folder_gui()
    if not folder:
        print("[LỖI] Bạn chưa chọn thư mục nào, thoát.")
        sys.exit(1)

    folder = folder.strip().strip('"')
    if not os.path.isdir(folder):
        print(f"[LỖI] Thư mục không tồn tại: {folder}")
        sys.exit(1)

    # Hỏi bật/tắt SRT
    use_srt_input = input("Sử dụng SRT nếu có? (y/n, Enter = y): ").strip().lower()
    use_srt = (use_srt_input != "n")

    ensure_output_dir()
    print(f"Thư mục input : {folder}")
    print(f"Thư mục output: {OUTPUT_DIR}")
    print(f"Thư mục SRT   : {SRT_DIR}")
    print(f"Dùng SRT      : {use_srt}")

    print("Đang load model Demucs: htdemucs ...")
    model = get_model("htdemucs")
    model.to(DEVICE)
    model.eval()
    print("Đã load model xong.")

    files = [f for f in os.listdir(folder) if f.lower().endswith(".mp4")]
    if not files:
        print("[THÔNG BÁO] Không tìm thấy file .mp4 nào.")
        sys.exit(0)

    print(f"Tìm thấy {len(files)} file .mp4.")

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, filename in enumerate(files, start=1):
            full_path = os.path.join(folder, filename)
            base_name = os.path.splitext(filename)[0]
            print(f"\n[{idx}/{len(files)}] Xử lý: {filename}")

            temp_wav = os.path.join(tmpdir, f"{base_name}.wav")
            ok = ffmpeg_extract_wav(full_path, temp_wav, sample_rate=32000)
            if not ok:
                continue

            srt_path = os.path.join(SRT_DIR, base_name + ".srt")

            try:
                voice_out, bg_out, sr = process_one_wav_with_optional_srt(
                    model, temp_wav, srt_path, base_name, use_srt=use_srt
                )
            except Exception as e:
                print(f"  [LỖI] Khi xử lý audio: {e}")
                continue

            if voice_out is None or bg_out is None:
                print("  [LỖI] Không tạo được voice/bg cho file này.")
                continue

            voice_file = os.path.join(OUTPUT_DIR, f"{base_name}_voice.wav")
            bg_file = os.path.join(OUTPUT_DIR, f"{base_name}_bg_novoice.wav")

            try:
                save_audio(voice_file, voice_out, sr)
                save_audio(bg_file, bg_out, sr)
            except Exception as e:
                print(f"  [LỖI] Không lưu được file output: {e}")
                continue

            print(f"  ✓ Voice      : {voice_file}")
            print(f"  ✓ BG no-voice: {bg_file}")

    print("\n=== HOÀN TẤT TẤT CẢ FILE .MP4 ===")


if __name__ == "__main__":
    main()
