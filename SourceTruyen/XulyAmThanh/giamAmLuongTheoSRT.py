# -*- coding: utf-8 -*-
"""
giamAmLuongTheoSRT.py

GUI có 2 checkbox tách rời:
(1) Giảm âm theo SRT: MUTE đoạn có thoại (volume = 0), giữ nguyên đoạn không thoại
(2) Giảm nhạc nền (duck): giảm âm đoạn KHÔNG thoại, giữ nguyên đoạn thoại

Pipeline:
- Nếu bật cả 2: chạy (1) xong -> chạy (2)
- Nếu chỉ bật (1): chỉ chạy mute theo SRT
- Nếu chỉ bật (2): chỉ duck nền dựa trên SRT (không mute thoại)

Yêu cầu:
- ffmpeg trong PATH
- pip install pydub srt
"""

import os
import re
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from pydub import AudioSegment
except ImportError:
    print("❌ Thiếu pydub. Cài: pip install pydub")
    sys.exit(1)

try:
    import srt
except ImportError:
    print("❌ Thiếu srt. Cài: pip install srt")
    sys.exit(1)


def center_on_screen(win, w=None, h=None):
    """Đưa cửa sổ ra giữa màn hình; bỏ trống w/h thì giữ kích thước hiện tại."""
    win.update_idletasks()
    w = w or max(win.winfo_width(), win.winfo_reqwidth())
    h = h or max(win.winfo_height(), win.winfo_reqheight())
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(w, sw), min(h, sh)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")

# ===================== CẤU HÌNH =====================
OUTPUT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\XulyAmThanh\AmThanh_GiamGiong"

SRT_DIRS = [
    r"D:\Python\GetLinktoText\SourceTruyen\dSRT",
    r"D:\Python\GetLinktoText\SourceTruyen\old srt"
]

# Kéo start sớm hơn để không hụt đầu câu
PRE_ROLL_MS = 300

# Giảm tổng toàn track trước khi xử lý (0 = không giảm)
MASTER_REDUCTION_DB = 0

# Duck nền (đoạn KHÔNG thoại)
BG_DUCK_DB = -30     # -25 / -35 / -40 tùy tai
FADE_MS = 25         # fade tránh “cạch” khi chuyển đoạn

SUPPORTED_VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")
GATE_REL_DELTA_DB = 20   # threshold nền = P95(nền) - 20dB (tự thích nghi từng đoạn nền)

# === NOISE GATE theo dB (chức năng 2) ===
GATE_FRAME_MS = 20          # 10–20ms
GATE_THRESHOLD_DBFS = -28.0 # sẽ chỉnh theo file
GATE_MIN_ON_MS = 180        # đoạn "âm lớn" tối thiểu để giữ
GATE_MERGE_GAP_MS = 80      # gộp các đoạn gần nhau
GATE_PAD_MS = 120           # nới đầu/cuối để không cắt mất chữ
GATE_FADE_MS = 20           # fade tránh click
# ===================== UTIL =====================
def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def extract_number_from_filename(filename: str):
    """
    Lấy số cuối trong tên file.
    ví dụ: abc_001.mp4 -> 1
          video12.mkv -> 12
    """
    name = os.path.splitext(os.path.basename(filename))[0]
    m = re.search(r"(\d+)\s*$", name)
    if not m:
        # thử tìm mọi cụm số và lấy cụm cuối cùng
        nums = re.findall(r"(\d+)", name)
        if not nums:
            return None
        return int(nums[-1])
    return int(m.group(1))


def find_srt_file(video_number: int):
    """
    Tìm {video_number}.srt trong các thư mục SRT_DIRS
    """
    srt_name = f"{video_number}.srt"
    for d in SRT_DIRS:
        p = os.path.join(d, srt_name)
        if os.path.isfile(p):
            return p
    return None


def ffmpeg_extract_audio(video_path: str, wav_out: str) -> bool:
    """
    Tách audio từ video sang WAV (PCM 16-bit, 44.1kHz stereo)
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        wav_out
    ]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            print("❌ ffmpeg lỗi:", p.stderr[-400:])
            return False
        return True
    except FileNotFoundError:
        print("❌ Không tìm thấy ffmpeg. Hãy cài ffmpeg và add vào PATH.")
        return False


def load_sub_ranges(srt_path: str):
    """
    Đọc file SRT và trả về list (start_ms, end_ms) của các đoạn có thoại.
    Có PRE_ROLL_MS để kéo start sớm hơn.
    """
    try:
        with open(srt_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

    try:
        subs = list(srt.parse(content))
    except Exception as e:
        print(f"  ⚠️ Lỗi parse SRT: {e}")
        return []

    ranges = []
    for sub in subs:
        start_ms = int(sub.start.total_seconds() * 1000) - PRE_ROLL_MS
        end_ms = int(sub.end.total_seconds() * 1000)
        if end_ms <= 0:
            continue
        if start_ms < 0:
            start_ms = 0
        if end_ms <= start_ms:
            continue
        ranges.append((start_ms, end_ms))

    # gộp các đoạn chồng/giáp nhau
    ranges.sort()
    merged = []
    for s, e in ranges:
        if not merged or s > merged[-1][1]:
            merged.append([s, e])
        else:
            merged[-1][1] = max(merged[-1][1], e)

    return [(s, e) for s, e in merged]


# ===================== AUDIO OPS =====================
def reduce_volume_in_dialogue(audio_path, dialogue_ranges, output_path):
    """
    CHỨC NĂNG (1):
    - Im lặng (0) đoạn CÓ thoại
    - Giữ nguyên đoạn KHÔNG thoại
    """
    audio = AudioSegment.from_wav(audio_path)

    if MASTER_REDUCTION_DB and isinstance(MASTER_REDUCTION_DB, (int, float)) and MASTER_REDUCTION_DB != 0:
        audio = audio + MASTER_REDUCTION_DB

    total = len(audio)
    out = AudioSegment.silent(duration=0)

    dialogue_ranges = sorted(dialogue_ranges or [])
    cur = 0

    for (s, e) in dialogue_ranges:
        s = max(0, min(int(s), total))
        e = max(0, min(int(e), total))
        if s >= e:
            continue

        # nền trước thoại: giữ nguyên
        if cur < s:
            out += audio[cur:s]

        # thoại: mute
        out += AudioSegment.silent(duration=(e - s))
        cur = e

    # đoạn cuối: giữ nguyên
    if cur < total:
        out += audio[cur:total]

    out.export(output_path, format="wav")


def duck_background_outside_dialogue(audio_path, dialogue_ranges, output_path, duck_db=BG_DUCK_DB, fade_ms=FADE_MS):
    """
    CHỨC NĂNG (2):
    - Duck đoạn KHÔNG thoại xuống duck_db
    - Giữ nguyên đoạn thoại

    Lưu ý: KHÔNG áp MASTER_REDUCTION_DB ở đây để tránh giảm 2 lần khi chạy sau (1).
    """
    audio = AudioSegment.from_wav(audio_path)
    total = len(audio)

    dialogue_ranges = sorted(dialogue_ranges or [])
    out = AudioSegment.silent(duration=0)
    cur = 0

    for (s, e) in dialogue_ranges:
        s = max(0, min(int(s), total))
        e = max(0, min(int(e), total))
        if s >= e:
            continue

        # nền: duck
        if cur < s:
            bg = audio[cur:s] + duck_db
            if fade_ms > 0 and len(bg) > fade_ms * 2:
                bg = bg.fade_in(fade_ms).fade_out(fade_ms)
            out += bg

        # thoại: giữ
        sp = audio[s:e]
        if fade_ms > 0 and len(sp) > fade_ms * 2:
            sp = sp.fade_in(fade_ms).fade_out(fade_ms)
        out += sp

        cur = e

    # nền cuối: duck
    if cur < total:
        bg = audio[cur:total] + duck_db
        if fade_ms > 0 and len(bg) > fade_ms * 2:
            bg = bg.fade_in(fade_ms).fade_out(fade_ms)
        out += bg

    out.export(output_path, format="wav")


# ===================== PROCESS ONE =====================
def process_one_video(video_path, do_srt_mute=True, do_duck_bg=True) -> bool:
    filename = os.path.basename(video_path)
    base_name = os.path.splitext(filename)[0]

    if not do_srt_mute and not do_duck_bg:
        print(f"⚠️ {filename}: Bạn tắt cả 2 chức năng -> bỏ qua.")
        return False

    # 1) tìm số
    num = extract_number_from_filename(filename)
    if num is None:
        print(f"⚠️ {filename}: Không tìm thấy số -> bỏ qua.")
        return False

    # 2) tìm SRT
    srt_path = find_srt_file(num)
    if not srt_path:
        print(f"⚠️ {filename}: Không tìm thấy {num}.srt -> bỏ qua.")
        return False

    # 3) tách audio
    temp_wav = os.path.join(OUTPUT_DIR, f"{base_name}_temp.wav")
    step1_wav = os.path.join(OUTPUT_DIR, f"{base_name}_step1_srt.wav")
    out_wav = os.path.join(OUTPUT_DIR, f"{base_name}_processed.wav")

    print("\n" + "=" * 70)
    print(f"🎬 {filename}")
    print(f"🔢 Số: {num} | 📄 SRT: {srt_path}")
    print(f"📌 Áp dụng SRT '{os.path.basename(srt_path)}' làm mốc âm thanh cho video '{filename}'")
    print(f"🎛️  (1) SRT mute: {'ON' if do_srt_mute else 'OFF'} | (2) Duck nền: {'ON' if do_duck_bg else 'OFF'}")

    if not ffmpeg_extract_audio(video_path, temp_wav):
        return False

    # 4) đọc ranges
    dialogue_ranges = load_sub_ranges(srt_path)

    try:
        current_in = temp_wav

        # (1) chạy trước
        if do_srt_mute:
            print("✅ Đang chạy (1) Giảm âm theo SRT (mute thoại)...")
            reduce_volume_in_dialogue(current_in, dialogue_ranges, step1_wav)
            current_in = step1_wav

        # (2) chạy sau
        if do_duck_bg:
            print("✅ Đang chạy (2) Giảm nhạc nền (duck ngoài thoại)...")
            gate_background_outside_dialogue(current_in, dialogue_ranges, out_wav)
        else:
            # nếu bỏ (2) thì xuất current_in thành processed cho thống nhất tên
            AudioSegment.from_wav(current_in).export(out_wav, format="wav")

        print(f"✅ DONE -> {out_wav}")
        return True

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        return False

    finally:
        # dọn rác
        for p in [temp_wav, step1_wav]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

def _p95_dbfs(seg: AudioSegment, frame_ms: int) -> float:
    """P95 dBFS của 1 đoạn AudioSegment (bỏ spike)."""
    if len(seg) <= 0:
        return -120.0
    vals = []
    for t in range(0, len(seg), frame_ms):
        fr = seg[t:min(t + frame_ms, len(seg))]
        vals.append(fr.dBFS if fr.rms > 0 else -120.0)
    vals.sort()
    return vals[int(0.95 * (len(vals) - 1))] if vals else -120.0


def _gate_segment_mute0(seg: AudioSegment,
                        frame_ms: int,
                        threshold_dbfs: float,
                        min_on_ms: int,
                        merge_gap_ms: int,
                        pad_ms: int,
                        fade_ms: int) -> AudioSegment:
    """
    Giữ phần >= threshold_dbfs, phần còn lại MUTE=0 (tuyệt đối) trong chính đoạn seg.
    """
    total = len(seg)
    if total <= 0:
        return seg

    # 1) đánh dấu frame loud
    loud = []
    for t in range(0, total, frame_ms):
        fr = seg[t:min(t + frame_ms, total)]
        db = fr.dBFS if fr.rms > 0 else -120.0
        loud.append(db >= threshold_dbfs)

    # 2) loud frames -> ranges
    ranges = []
    in_on = False
    start = 0
    t = 0
    for is_on in loud:
        if is_on and not in_on:
            in_on = True
            start = t
        elif (not is_on) and in_on:
            in_on = False
            ranges.append((start, t))
        t += frame_ms
    if in_on:
        ranges.append((start, total))

    # 3) min duration
    ranges = [(s, e) for (s, e) in ranges if (e - s) >= min_on_ms]

    # 4) merge gap
    ranges.sort()
    merged = []
    for s, e in ranges:
        if not merged or s > merged[-1][1] + merge_gap_ms:
            merged.append([s, e])
        else:
            merged[-1][1] = max(merged[-1][1], e)

    # 5) pad
    keep = []
    for s, e in merged:
        s2 = max(0, s - pad_ms)
        e2 = min(total, e + pad_ms)
        if e2 > s2:
            keep.append((s2, e2))

    # 6) dựng output: ngoài keep -> silent, trong keep -> giữ
    out = AudioSegment.silent(duration=0)
    cur = 0
    for s, e in keep:
        if cur < s:
            out += AudioSegment.silent(duration=(s - cur))
        part = seg[s:e]
        if fade_ms > 0 and len(part) > fade_ms * 2:
            part = part.fade_in(fade_ms).fade_out(fade_ms)
        out += part
        cur = e

    if cur < total:
        out += AudioSegment.silent(duration=(total - cur))

    return out


def gate_background_outside_dialogue(wav_in: str, dialogue_ranges, wav_out: str):
    """
    LOGIC B + MUTE 0:
    - Trong đoạn thoại (theo SRT): GIỮ NGUYÊN
    - Ngoài đoạn thoại: gate theo dB tương đối (P95 - GATE_REL_DELTA_DB) rồi MUTE=0 phần dưới ngưỡng
    """
    audio = AudioSegment.from_wav(wav_in)
    total = len(audio)

    dialogue_ranges = sorted(dialogue_ranges or [])
    out = AudioSegment.silent(duration=0)
    cur = 0

    for (s, e) in dialogue_ranges:
        s = max(0, min(int(s), total))
        e = max(0, min(int(e), total))
        if s >= e:
            continue

        # 1) nền trước thoại: gate + mute0
        if cur < s:
            bg = audio[cur:s]
            p95 = _p95_dbfs(bg, frame_ms=GATE_FRAME_MS)
            thr = p95 - float(GATE_REL_DELTA_DB)
            bg_gated = _gate_segment_mute0(
                bg,
                frame_ms=GATE_FRAME_MS,
                threshold_dbfs=thr,
                min_on_ms=GATE_MIN_ON_MS,
                merge_gap_ms=GATE_MERGE_GAP_MS,
                pad_ms=GATE_PAD_MS,
                fade_ms=GATE_FADE_MS
            )
            out += bg_gated

        # 2) thoại: giữ nguyên
        out += audio[s:e]
        cur = e

    # 3) nền cuối: gate + mute0
    if cur < total:
        bg = audio[cur:total]
        p95 = _p95_dbfs(bg, frame_ms=GATE_FRAME_MS)
        thr = p95 - float(GATE_REL_DELTA_DB)
        out += _gate_segment_mute0(
            bg,
            frame_ms=GATE_FRAME_MS,
            threshold_dbfs=thr,
            min_on_ms=GATE_MIN_ON_MS,
            merge_gap_ms=GATE_MERGE_GAP_MS,
            pad_ms=GATE_PAD_MS,
            fade_ms=GATE_FADE_MS
        )

    out.export(wav_out, format="wav")

# ===================== GUI =====================
def select_videos_gui(parent):
    file_paths = filedialog.askopenfilenames(
        parent=parent,
        title="Chọn video cần xử lý",
        filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.m4v"), ("All files", "*.*")]
    )
    return list(file_paths)



def main():
    ensure_output_dir()

    # GUI chính có 2 checkbox (check sẵn)
    root = tk.Tk()
    root.title("Giảm âm theo SRT + Giảm nhạc nền (2 bước)")

    selected_files = []

    # ✅ 2 chức năng (check sẵn)
    do_srt_mute_var = tk.BooleanVar(value=True)
    do_duck_bg_var = tk.BooleanVar(value=True)

    # Xóa file WAV tạm
    clear_wavs_var = tk.BooleanVar(value=True)

    def on_select_files():
        nonlocal selected_files
        selected_files = select_videos_gui(root)
        lbl_files.config(text=f"Đã chọn {len(selected_files)} file")

    def on_run():
        if not selected_files:
            messagebox.showwarning("Chưa chọn file", "Bạn chưa chọn video nào.")
            return

        if not do_srt_mute_var.get() and not do_duck_bg_var.get():
            messagebox.showwarning("Chưa chọn chức năng", "Bạn đang tắt cả 2 chức năng.")
            return

        # Xóa file WAV tạm nếu được chọn
        if clear_wavs_var.get():
                try:
                    for fn in os.listdir(OUTPUT_DIR):
                        if fn.lower().endswith(".wav"):
                            fp = os.path.join(OUTPUT_DIR, fn)
                            try:
                                os.remove(fp)
                            except OSError:
                                pass
                    print("🧹 Đã xóa các file WAV trong OUTPUT_DIR")
                except Exception as e:
                    print(f"⚠️ Không xóa được WAV: {e}")

        root.destroy()


    frm = tk.Frame(root, padx=12, pady=12)
    frm.pack(fill="both", expand=True)

    tk.Label(frm, text="1) Chọn video:").grid(row=0, column=0, sticky="w")
    tk.Button(frm, text="Chọn video...", command=on_select_files).grid(row=0, column=1, sticky="w", padx=8)
    lbl_files = tk.Label(frm, text="Chưa chọn file")
    lbl_files.grid(row=0, column=2, sticky="w")

    # ✅ 2 checkbox tách rời
    tk.Checkbutton(frm, text="(1) Giảm âm theo SRT (mute đoạn có thoại)", variable=do_srt_mute_var)\
        .grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 2))

    tk.Checkbutton(frm, text="(2) Giảm nhạc nền (duck đoạn không thoại)", variable=do_duck_bg_var)\
        .grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

    tk.Checkbutton(frm, text="Xóa file WAV tạm/đầu ra", variable=clear_wavs_var)\
        .grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 2))

    # info nhỏ
    tk.Label(
        frm,
        text=f"PRE_ROLL_MS={PRE_ROLL_MS}ms | BG_DUCK_DB={BG_DUCK_DB}dB | FADE_MS={FADE_MS}ms"
    ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

    tk.Button(frm, text="Bắt đầu xử lý", command=on_run).grid(row=5, column=0, sticky="w", pady=12)

    center_on_screen(root)
    root.mainloop()

    # chạy xử lý
    print("=" * 80)
    print("BẮT ĐẦU XỬ LÝ")
    print("=" * 80)

    ok_count = 0
    for i, vp in enumerate(selected_files, start=1):
        print(f"\n[{i}/{len(selected_files)}] {os.path.basename(vp)}")
        ok = process_one_video(
            vp,
            do_srt_mute=do_srt_mute_var.get(),
            do_duck_bg=do_duck_bg_var.get()
        )
        ok_count += 1 if ok else 0

    print("\n" + "=" * 80)
    print(f"HOÀN TẤT: {ok_count}/{len(selected_files)} file OK")
    print("=" * 80)


if __name__ == "__main__":
    main()
