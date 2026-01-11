import os
from pathlib import Path
import numpy as np
import librosa
import soundfile as sf
from scipy.ndimage import uniform_filter1d

# ================== CONFIG ==================
INPUT_DIR  = r"D:\Python\GetLinktoText\SourceTruyen\XulyAmThanh\AmThanh"
OUTPUT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\XulyAmThanh\AmThanh_peaks"

# Ngưỡng = noise_floor + DELTA_DB
DELTA_DB = 12.0        # tăng lên nếu còn dính nền, giảm xuống nếu mất peak nhỏ
FRAME_LENGTH = 2048
HOP_LENGTH   = 512

SMOOTH_MS = 60.0       # làm mượt gate (ms). tăng nếu bị cắt gắt
HYSTERESIS_DB = 3.0    # chống nhấp nháy gate

OUTPUT_SUFFIX = "_peaks.wav"  # xuất wav cho chắc chắn
# ===========================================


def compute_rms_db(y, frame_length=2048, hop_length=512):
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    return librosa.amplitude_to_db(rms, ref=np.max)


def gate_from_floor(rms_db, sr, hop_length, n_samples,
                    floor_db, delta_db,
                    smooth_ms=50, hysteresis_db=3):
    """
    Gate nhị phân theo ngưỡng động:
      threshold_on  = floor_db + delta_db
      threshold_off = threshold_on - hysteresis_db
    Sau đó upsample ra mask theo sample và làm mượt.
    """
    thr_on  = floor_db + delta_db
    thr_off = thr_on - hysteresis_db

    mask_frame = np.zeros_like(rms_db, dtype=np.float32)
    open_gate = False
    for i, val in enumerate(rms_db):
        if (not open_gate) and (val >= thr_on):
            open_gate = True
        elif open_gate and (val < thr_off):
            open_gate = False
        mask_frame[i] = 1.0 if open_gate else 0.0

    # Upsample từ frame -> sample
    mask_up = np.repeat(mask_frame, hop_length)
    mask_up = mask_up[:n_samples]

    # Làm mượt mask theo thời gian (moving average)
    if smooth_ms and smooth_ms > 0:
        smooth_len = int(sr * (smooth_ms / 1000.0))
        smooth_len = max(1, smooth_len)
        mask_up = uniform_filter1d(mask_up, size=smooth_len, mode="nearest")

    return mask_up, thr_on


def process_audio_file(in_path: Path, out_path: Path):
    # Load giữ stereo nếu có
    y, sr = librosa.load(str(in_path), sr=None, mono=False)

    if y.ndim == 1:
        rms_db = compute_rms_db(y, FRAME_LENGTH, HOP_LENGTH)
        floor_db = float(np.median(rms_db))  # noise floor = median

        mask_up, thr_on = gate_from_floor(
            rms_db, sr, HOP_LENGTH, len(y),
            floor_db, DELTA_DB,
            smooth_ms=SMOOTH_MS,
            hysteresis_db=HYSTERESIS_DB
        )
        y_out = y * mask_up

        sf.write(str(out_path), y_out, sr)
        return floor_db, thr_on

    else:
        outs = []
        floors = []
        thrs = []
        for ch in y:
            rms_db = compute_rms_db(ch, FRAME_LENGTH, HOP_LENGTH)
            floor_db = float(np.median(rms_db))

            mask_up, thr_on = gate_from_floor(
                rms_db, sr, HOP_LENGTH, len(ch),
                floor_db, DELTA_DB,
                smooth_ms=SMOOTH_MS,
                hysteresis_db=HYSTERESIS_DB
            )
            outs.append(ch * mask_up)
            floors.append(floor_db)
            thrs.append(thr_on)

        y_out = np.vstack(outs).T
        sf.write(str(out_path), y_out, sr)
        return floors, thrs


def main():
    in_dir = Path(INPUT_DIR)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    mp3_files = sorted(in_dir.glob("*.mp3"))
    if not mp3_files:
        print("Không tìm thấy file mp3 trong:", INPUT_DIR)
        return

    print(f"Tìm thấy {len(mp3_files)} file mp3. Bắt đầu xử lý...")

    for i, f in enumerate(mp3_files, 1):
        out_path = out_dir / (f.stem + OUTPUT_SUFFIX)

        try:
            floor_db, thr_on = process_audio_file(f, out_path)
            print(f"[{i}/{len(mp3_files)}] {f.name}")
            print(f"    noise_floor ≈ {floor_db} dB | threshold_on ≈ {thr_on} dB")
        except Exception as e:
            print(f"[{i}/{len(mp3_files)}] LỖI {f.name}: {e}")

    print("Xong! Output ở:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
