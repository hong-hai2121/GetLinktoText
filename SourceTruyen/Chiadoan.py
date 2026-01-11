# split_after3min_whisper_copy_cuda.py
# - Chọn file qua hộp thoại.
# - Với mỗi mốc k*TARGET_MIN, chỉ phân tích cửa sổ SAU mốc: [ideal, ideal + POST_WINDOW].
# - Whisper local (medium.pt) dùng CUDA để lấy timestamps câu nói trong cửa sổ.
# - Ưu tiên cắt tại KEYFRAME bên trong khoảng im lặng ≥ MIN_SIL_SEC.
# - Cắt -c copy, xuất D:\truyen\<ten_file>\part_XXX.mp4, log chi tiết.

import os, sys, re, json, pathlib, tempfile, subprocess, time, shutil, datetime, traceback
import tkinter as tk
from tkinter import filedialog

# ===== Cấu hình =====
MODEL_PATH   = r"D:\Python\GetLinktoText\whisper_cache\medium.pt"
OUT_ROOT     = r"D:\truyen"
TARGET_MIN   = 55            # phút/đoạn
POST_WINDOW  = 120           # chỉ nhìn 3 phút SAU mốc (giây)
MIN_SIL_SEC  = 0.7
LANG         = None          # "vi"/None...

# ===== Log & tiện ích =====
def now(): return datetime.datetime.now().strftime("%H:%M:%S")
def log(m): print(f"[{now()}] {m}", flush=True)
def which(x): from shutil import which; return which(x) is not None
def pretty_hms(s):
    s=max(0.0,float(s)); h=int(s//3600); s-=h*3600; m=int(s//60); s-=m*60
    return f"{h:d}:{m:02d}:{s:06.3f}"

def run_cap(cmd):
    # An toàn Unicode trên Windows: đọc bytes rồi decode UTF-8
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", errors="ignore")
    return out, p.returncode


def sanitize_folder(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', name).strip() or "output"

def pick_file():
    root = tk.Tk(); root.withdraw()
    return filedialog.askopenfilename(
        title="Chọn video cần cắt",
        filetypes=[("Video","*.mp4;*.mkv;*.mov;*.m4v;*.ts;*.avi"), ("All","*.*")]
    )

# ===== FFprobe/FFmpeg =====
def ffprobe_duration(path):
    out, rc = run_cap(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", path])
    if rc!=0: raise RuntimeError(out)
    return float(out.strip())

def ffprobe_keyframes_window(path, start, dur):
    """
    Lấy KEYFRAME chỉ trong cửa sổ [start, start+dur].
    Dùng -read_intervals và -skip_frame nokey để nhanh.
    """
    end = start + dur
    cmd = [
        "ffprobe","-v","error",
        "-read_intervals", f"{start:.3f}%+{dur:.3f}",
        "-select_streams","v:0",
        "-show_frames",
        "-show_entries","frame=pkt_pts_time,key_frame",
        "-skip_frame","nokey",
        "-of","json",
        path
    ]
    out, rc = run_cap(cmd)
    if rc!=0: raise RuntimeError(out)
    data = json.loads(out)
    kfs=[]
    for f in data.get("frames", []):
        t = float(f.get("pkt_pts_time","0"))
        if start-1e-3 <= t <= end+1e-3:
            kfs.append(t)
    return kfs

def extract_wav_segment(src, wav_path, start_sec, dur_sec):
    cmd = [
        "ffmpeg","-y","-ss",f"{start_sec:.3f}","-t",f"{dur_sec:.3f}",
        "-i",src,"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le", wav_path
    ]
    # Đọc bytes, tự decode
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    last = b""
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        last = line  # lưu dòng cuối để debug
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg trích audio lỗi. {last.decode('utf-8', errors='ignore')}")


def _parse_ff_time(line):
    # trích time=HH:MM:SS.xx từ log ffmpeg -> giây
    m = None
    if "time=" in line:
        try:
            t = line.split("time=")[1].split()[0]
            h, m_, s = t.split(":")
            return int(h)*3600 + int(m_)*60 + float(s)
        except Exception:
            return None
    return None

def slice_copy(src, out_path, t0, t1):
    import math, sys
    dur = max(0.001, t1 - t0)
    cmd = ["ffmpeg","-y","-ss",f"{t0:.3f}","-i",src,"-t",f"{dur:.3f}",
           "-c","copy","-movflags","+faststart","-stats", out_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    last = b""
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        last = line
        try:
            txt = line.decode("utf-8", errors="ignore").strip()
        except:
            txt = ""
        sec = _parse_ff_time(txt)
        if sec is not None and dur > 0:
            pct = min(100.0, 100.0*sec/dur)
            print(f"\r    tiến độ: {pct:6.2f}% ({sec:.1f}/{dur:.1f}s)", end="", flush=True)
    rc = proc.wait()
    print()  # xuống dòng
    ok = os.path.exists(out_path) and os.path.getsize(out_path)>0 and rc==0
    if not ok:
        print(f"[ffmpeg] lỗi khi cắt {out_path}. {last.decode('utf-8', errors='ignore')}", flush=True)
    return ok


# ===== Whisper (CUDA) =====
def load_whisper():
    import torch, whisper
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA không khả dụng. Kiểm tra driver/RTX.")
    log("CUDA OK, tải Whisper local…")
    t=time.perf_counter()
    model = whisper.load_model(MODEL_PATH, device="cuda")
    log(f"Tải Whisper xong trong {time.perf_counter()-t:.1f}s")
    return model

def transcribe_window(model, wav_path):
    import torch
    t=time.perf_counter()
    segs = model.transcribe(wav_path, language=LANG, verbose=False, task="transcribe", fp16=True).get("segments", [])
    log(f"Transcribe cửa sổ xong ({len(segs)} đoạn) trong {time.perf_counter()-t:.1f}s")
    return segs

def silence_from_segments(segments, total_local):
    if not segments: return [(0.0, total_local)]
    sil=[]
    if segments[0]["start"]>0: sil.append((0.0, float(segments[0]["start"])))
    for i in range(len(segments)-1):
        a=float(segments[i]["end"]); b=float(segments[i+1]["start"])
    # Edit: ensure positive
        if b>a: sil.append((a,b))
    if float(segments[-1]["end"])<total_local:
        sil.append((float(segments[-1]["end"]), total_local))
    return sil

# ===== Chọn điểm cắt trong cửa sổ sau mốc =====
def pick_cut_after_mark(ideal, window_start, window_dur, kfs_in_window, sil_local, min_sil):
    """
    ideal: thời điểm mốc toàn cục (giây).
    window: [window_start, window_start+window_dur] nằm SAU mốc.
    kfs_in_window: list keyframe trong cửa sổ (global seconds).
    sil_local: list im lặng trong cửa sổ (tọa độ local 0..window_dur).
    Ưu tiên: keyframe bên trong im lặng đủ dài, gần ideal nhất nhưng KHÔNG nhỏ hơn ideal.
    """
    # 1) Keyframe trong im lặng đủ dài và >= ideal
    best=None; best_d=1e18
    for (ls, le) in sil_local:
        if le-ls < min_sil: continue
        gs = window_start + ls
        ge = window_start + le
        for k in kfs_in_window:
            if k < ideal:  # chỉ sau mốc
                continue
            if gs <= k <= ge:
                d = abs(k - ideal)
                if d < best_d:
                    best_d, best = d, k
    if best is not None: return best

    # 2) Keyframe >= ideal, gần tâm im lặng
    for (ls, le) in sil_local:
        center = window_start + (ls+le)/2
        for k in kfs_in_window:
            if k < ideal: continue
            d = abs(k - center)
            if d < best_d:
                best_d, best = d, k
    if best is not None: return best

    # 3) Keyframe >= ideal gần ideal nhất
    for k in kfs_in_window:
        if k >= ideal:
            d = abs(k - ideal)
            if d < best_d:
                best_d, best = d, k
    if best is not None: return best

    # 4) Không có keyframe sau mốc trong cửa sổ → lấy tâm im lặng dài nhất trong cửa sổ sau mốc
    candidates = []
    for (ls, le) in sil_local:
        gs = window_start + ls
        ge = window_start + le
        if ge >= ideal:
            overlap = (max(gs, ideal), ge)
            if overlap[1] - overlap[0] >= min_sil:
                candidates.append(overlap)
    if candidates:
        s,e = max(candidates, key=lambda x: x[1]-x[0])
        return (s+e)/2

    # 5) Rơi về ideal
    return ideal

# ===== Main =====
def main():
    try:
        if not which("ffmpeg") or not which("ffprobe"):
            log("Thiếu ffmpeg/ffprobe trong PATH."); sys.exit(1)

        log("Chọn video…")
        src = pick_file()
        if not src: log("Chưa chọn file."); sys.exit(1)
        if not os.path.isfile(src): log("File không tồn tại."); sys.exit(1)

        stem = pathlib.Path(src).stem
        outdir = pathlib.Path(OUT_ROOT) / sanitize_folder(stem)
        outdir.mkdir(parents=True, exist_ok=True)
        log(f"Thư mục xuất: {outdir}")

        total = ffprobe_duration(src)
        log(f"Tổng thời lượng: {pretty_hms(total)}")

        model = load_whisper()

        target_sec = TARGET_MIN*60.0
        marks = []
        k=1
        while k*target_sec < total:
            marks.append(k*target_sec)
            k+=1
        log(f"Số mốc: {len(marks)}  (mỗi mốc phân tích {POST_WINDOW}s SAU mốc)")

        cuts = [0.0]
        for idx, ideal in enumerate(marks, 1):
            win_s = ideal
            win_d = min(POST_WINDOW, total - win_s)
            if win_d <= 1.0:
                log(f"[{idx}] Cửa sổ quá ngắn, dùng ideal.")
                cuts.append(ideal); continue

            # Keyframe trong cửa sổ sau mốc
            log(f"[{idx}] Quét keyframe trong {pretty_hms(win_s)} → {pretty_hms(win_s+win_d)}")
            kfs = ffprobe_keyframes_window(src, win_s, win_d)
            log(f"[{idx}] Keyframe trong cửa sổ: {len(kfs)}")

            # Trích và nhận diện audio cửa sổ sau mốc
            with tempfile.TemporaryDirectory() as td:
                wavp = os.path.join(td, "w.wav")
                log(f"[{idx}] Trích audio {win_d:.1f}s…")
                extract_wav_segment(src, wavp, win_s, win_d)
                segs = transcribe_window(model, wavp)

            sil_local = silence_from_segments(segs, win_d)
            # lọc theo ngưỡng im lặng tối thiểu
            sil_local = [(s,e) for (s,e) in sil_local if (e-s) >= MIN_SIL_SEC]
            log(f"[{idx}] Khoảng im lặng đủ dài trong cửa sổ: {len(sil_local)}")

            cut_t = pick_cut_after_mark(ideal, win_s, win_d, kfs, sil_local, MIN_SIL_SEC)
            cuts.append(max(0.0, min(total, round(cut_t,3))))
            log(f"[{idx}] Chọn cắt tại: {pretty_hms(cut_t)} (≥ mốc {pretty_hms(ideal)})")

        if cuts[-1] != total: cuts.append(total)
        cuts = sorted(set(cuts))
        seq=[]; prev=-1.0
        for c in cuts:
            if c>prev: seq.append(c); prev=c
        segments = [(seq[i], seq[i+1]) for i in range(len(seq)-1)]
        # Ưu tiên đoạn ngắn trước
        # segments.sort(key=lambda x: x[1]-x[0])
        log(f"Tổng số đoạn sẽ cắt: {len(segments)}")
        for i,(s,e) in enumerate(segments,1):
            log(f"  {i:03d}: {pretty_hms(s)} → {pretty_hms(e)}  (≈{(e-s)/60:.2f} phút)")

        # Cắt thực tế
        errors=0
        for i,(s,e) in enumerate(segments,1):
            outp = outdir / f"part_{i:03d}.mp4"
            log(f"--- CẮT {i}/{len(segments)} ---")
            if not slice_copy(src, str(outp), s, e):
                errors+=1; log(f"[LỖI] đoạn {i}")
            else:
                log(f"[OK] {outp.name} ({os.path.getsize(outp)/1e6:.2f} MB)")

        if errors:
            log(f"HOÀN TẤT với {errors} lỗi cắt."); sys.exit(2)
        log("HOÀN TẤT.")

    except Exception as e:
        log("===== LỖI =====")
        log(str(e))
        log(traceback.format_exc())
        sys.exit(3)

if __name__ == "__main__":
    main()
