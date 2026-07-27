# -*- coding: utf-8 -*-
"""
tangToc12.py

Chức năng:
- Chọn thư mục chứa video (.mp4, .mkv, .avi, .mov, .m4v, .flv, .wmv)
- Tăng tốc toàn bộ video lên tốc độ tùy chỉnh (cả hình và tiếng)
- Ghép các clip lại với nhau thành 1 video theo số thứ tự ở đầu tên
- Lưu kết quả vào thư mục output cố định
- Giao diện GUI với checkbox và nhập tốc độ

Yêu cầu:
- ffmpeg có trong PATH
"""

import os
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, scrolledtext
from shutil import which
import re
import threading
from pathlib import Path


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


DEFAULT_SPEED = 1.2  # hệ số tăng tốc mặc định
OUTPUT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\XuLyVideo\Video_TangToc"
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".flv", ".wmv")

# ====== Tùy chọn chuyển video dọc (9:16) ======
VERT_ENABLE_DEFAULT = False
VERT_OUT_W = 1080
VERT_OUT_H = 1920
VERT_OUT_FPS = 30

VERT_HEADER_H = 220
VERT_HEADER_ALPHA = 0.55  # 0..1

# Text: in đậm + viền, font hỗ trợ tiếng Việt (font Windows có sẵn)
VERT_CHANNEL_NAME = "CatSubz"
VERT_TEXT_SIZE = 74
VERT_TEXT_COLOR = "white"
VERT_TEXT_BORDER_W = 5
VERT_TEXT_BORDER_COLOR = "black@0.65"
VERT_TEXT_SHADOW_X = 2
VERT_TEXT_SHADOW_Y = 2
VERT_TEXT_SHADOW_COLOR = "black@0.65"

# Nền blur tối ưu tốc độ: boxblur (nhanh hơn gblur)
VERT_USE_BOXBLUR = True
VERT_BOXBLUR_LUMA = 10   # 8..14: nhỏ hơn -> nhanh hơn
VERT_BOXBLUR_CHROMA = 1
VERT_BG_DIM = 0.12

# Encode ưu tiên GPU (NVENC) để nhanh, fallback CPU
VERT_GPU_CQ = "23"
VERT_CPU_CRF = "20"


# Biến global để dừng xử lý
stop_processing = False

FFMPEG_PATH = which("ffmpeg")
FFPROBE_PATH = which("ffprobe")
if FFMPEG_PATH is None or FFPROBE_PATH is None:
    print("❌ Thiếu ffmpeg/ffprobe trong PATH. Cài ffmpeg trước khi chạy.")
    sys.exit(1)


def ensure_output_dir(output_dir=OUTPUT_DIR):
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"✅ Đã tạo thư mục output: {output_dir}")


def select_folder_gui():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Chọn thư mục chứa video cần tăng tốc")
    root.destroy()
    return folder


def probe_duration(input_path: str) -> float | None:
    cmd = [
        FFPROBE_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1",
        input_path,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip()) if res.stdout.strip() else None
    except Exception:
        return None


def run_ffmpeg_with_progress(cmd, duration_s: float | None) -> bool:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
    )
    try:
        last_print = -1
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith("out_time_ms") and duration_s:
                try:
                    out_ms = float(line.split("=")[-1])
                    pct = min(100.0, out_ms / (duration_s * 1000000.0) * 100.0)
                    pct_round = int(pct)
                    if pct_round != last_print:
                        print(f"    ⏳ Tiến trình: {pct_round}%", end="\r")
                        last_print = pct_round
                except ValueError:
                    pass
        rc = proc.wait()
        if duration_s:
            print(" " * 40, end="\r")
        return rc == 0
    finally:
        if proc and proc.poll() is None:
            proc.kill()



def escape_drawtext(text: str) -> str:
    """Escape text for ffmpeg drawtext."""
    t = text.replace("\\", "\\\\")
    t = t.replace(":", r"\:")
    t = t.replace("'", r"\'")
    t = t.replace("%", r"\%")
    t = t.replace("\n", r"\n")
    return t


def find_windows_vietnamese_fontfile() -> str:
    """Chọn font Windows có sẵn, hỗ trợ tiếng Việt và in đậm."""
    fonts_dir = Path(r"C:\Windows\Fonts")
    candidates = [
        "segoeuib.ttf",   # Segoe UI Bold
        "seguisb.ttf",    # Segoe UI Semibold
        "segoeui.ttf",    # Segoe UI Regular
        "arialbd.ttf",    # Arial Bold
        "arial.ttf",
        "tahomabd.ttf",   # Tahoma Bold
        "tahoma.ttf",
        "timesbd.ttf",
        "times.ttf",
    ]
    for name in candidates:
        p = fonts_dir / name
        if p.exists():
            return str(p)
    return ""


def build_vertical_filter(fontfile: str) -> str:
    """Filter tạo video dọc: nền blur + header + chữ."""
    W, H = VERT_OUT_W, VERT_OUT_H
    header_h = VERT_HEADER_H
    overlay_y = f"{header_h}+(H-{header_h}-h)/2"

    # Background NO BLUR: just scale+crop + dim
    bg_chain = (
        f"[0:v]"
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},"
        f"eq=brightness=-{VERT_BG_DIM}"
        f"[bg]"
    )
    fg_chain = f"[0:v]scale={W}:-2:force_original_aspect_ratio=decrease[fg]"
    hdr_src = f"color=c=black@{VERT_HEADER_ALPHA}:s={W}x{header_h}[hdr]"
    comp_base = f"[bg][fg]overlay=x=(W-w)/2:y={overlay_y}:format=auto[base]"
    comp_hdr = f"[base][hdr]overlay=x=0:y=0:format=auto[with_hdr]"

    text = escape_drawtext(VERT_CHANNEL_NAME)
    fontfile_esc = escape_drawtext(fontfile) if fontfile else ""
    font_part = f":fontfile='{fontfile_esc}'" if fontfile_esc else ""

    text_draw = (
        f"[with_hdr]drawtext=text='{text}'"
        f"{font_part}"
        f":fontsize={VERT_TEXT_SIZE}"
        f":fontcolor={VERT_TEXT_COLOR}"
        f":borderw={VERT_TEXT_BORDER_W}:bordercolor={VERT_TEXT_BORDER_COLOR}"
        f":shadowx={VERT_TEXT_SHADOW_X}:shadowy={VERT_TEXT_SHADOW_Y}:shadowcolor={VERT_TEXT_SHADOW_COLOR}"
        f":x=(w-text_w)/2"
        f":y=({header_h}-text_h)/2"
        f",fps={VERT_OUT_FPS}"
        f"[vout]"
    )

    return ";".join([bg_chain, fg_chain, hdr_src, comp_base, comp_hdr, text_draw])


def verticalize_video(input_path: str, output_path: str) -> bool:
    """
    Chuyển 1 video sang dọc (9:16) + header CatSubz.
    Ưu tiên GPU h264_nvenc, fallback CPU libx264.
    Giữ audio (copy) nếu được, fallback AAC nếu copy lỗi.
    """
    duration = probe_duration(input_path)
    fontfile = find_windows_vietnamese_fontfile()
    filt = build_vertical_filter(fontfile)

    # GPU (NVENC)
    gpu_cmd = [
        FFMPEG_PATH, "-y",
        "-i", input_path,
        "-filter_complex", filt,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", VERT_GPU_CQ,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",
        "-c:a", "copy",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        output_path,
    ]

    # CPU (có audio)
    cpu_cmd = [
        FFMPEG_PATH, "-y",
        "-i", input_path,
        "-filter_complex", filt,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", VERT_CPU_CRF,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",
        "-c:a", "copy",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        output_path,
    ]

    # Fallback audio AAC (GPU)
    gpu_aac = gpu_cmd.copy()
    # replace last audio settings
    # find "-c:a" index
    ca_idx = gpu_aac.index("-c:a")
    gpu_aac[ca_idx:ca_idx+2] = ["-c:a", "aac"]
    # insert bitrate after aac
    gpu_aac.insert(ca_idx+2, "-b:a")
    gpu_aac.insert(ca_idx+3, "192k")

    # Fallback audio AAC (CPU)
    cpu_aac = cpu_cmd.copy()
    ca_idx2 = cpu_aac.index("-c:a")
    cpu_aac[ca_idx2:ca_idx2+2] = ["-c:a", "aac"]
    cpu_aac.insert(ca_idx2+2, "-b:a")
    cpu_aac.insert(ca_idx2+3, "192k")

    print("    📱 Chuyển dọc: thử GPU (NVENC) ...")
    if run_ffmpeg_with_progress(gpu_cmd, duration):
        return True

    print("    ↩️ GPU lỗi, thử CPU ...")
    if run_ffmpeg_with_progress(cpu_cmd, duration):
        return True

    print("    ↩️ Copy audio lỗi, thử AAC (GPU) ...")
    if run_ffmpeg_with_progress(gpu_aac, duration):
        return True

    print("    ↩️ Thử AAC (CPU) ...")
    return run_ffmpeg_with_progress(cpu_aac, duration)

def speed_up_video(input_path: str, output_path: str, speed: float = DEFAULT_SPEED) -> bool:
    """Tăng tốc video + audio lên speed. Ưu tiên GPU (h264_nvenc), fallback CPU.
    Hiển thị tiến trình khi render."""
    setpts = 1.0 / speed
    duration = probe_duration(input_path)

    # Ưu tiên GPU NVENC
    gpu_cmd = [
        FFMPEG_PATH, "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", input_path,
        "-filter_complex", f"[0:v]setpts={setpts:.6f}*PTS[v];[0:a]atempo={speed}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        output_path,
    ]

    # Fallback CPU (có audio)
    cpu_cmd = [
        FFMPEG_PATH, "-y",
        "-i", input_path,
        "-filter_complex", f"[0:v]setpts={setpts:.6f}*PTS[v];[0:a]atempo={speed}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        output_path,
    ]

    # Fallback CPU video-only
    cpu_video_only = [
        FFMPEG_PATH, "-y",
        "-i", input_path,
        "-filter:v", f"setpts={setpts:.6f}*PTS",
        "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        output_path,
    ]

    print("    ⚡ Thử GPU (NVENC) ...")
    if run_ffmpeg_with_progress(gpu_cmd, duration):
        return True

    print("    ↩️ GPU lỗi, chuyển CPU...")
    if run_ffmpeg_with_progress(cpu_cmd, duration):
        return True

    print("    ↩️ CPU có audio lỗi, thử video-only...")
    return run_ffmpeg_with_progress(cpu_video_only, duration)


def extract_number_from_filename(filename: str) -> tuple:
    """Trích xuất số thứ tự từ đầu tên file để sắp xếp."""
    match = re.match(r'^(\d+)', filename)
    if match:
        return (int(match.group(1)), filename)
    return (float('inf'), filename)  # File không có số -> đẩy xuống cuối


def concat_videos(video_paths: list, output_path: str, log_func=None) -> bool:
    """Ghép nhiều video thành 1 video duy nhất theo thứ tự."""
    if not video_paths:
        return False
    
    def log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)
    
    # Tạo file list tạm cho ffmpeg concat trong cùng thư mục với output
    output_dir = os.path.dirname(output_path)
    list_file = os.path.join(output_dir, "concat_list.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for vp in video_paths:
                # Escape đường dẫn cho ffmpeg
                escaped = vp.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        
        log(f"🔗 Đang ghép {len(video_paths)} video...")
        
        cmd = [
            FFMPEG_PATH, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            log(f"✅ Ghép thành công: {os.path.basename(output_path)}")
            return True
        else:
            log(f"❌ Lỗi ghép video: {result.stderr}")
            return False
    except Exception as e:
        log(f"❌ Lỗi: {e}")
        return False
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


class VideoProcessorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Processor - Tăng tốc & Ghép video")
        center_on_screen(self.root, 900, 750)
        
        self.folder_path = tk.StringVar()
        self.output_path = tk.StringVar(value=OUTPUT_DIR)
        self.speed_var = tk.StringVar(value=str(DEFAULT_SPEED))
        self.enable_speedup = tk.BooleanVar(value=True)
        self.enable_vertical = tk.BooleanVar(value=VERT_ENABLE_DEFAULT)
        self.enable_concat = tk.BooleanVar(value=True)
        self.list_source = 'input'  # 'input' hoặc 'output' - nguồn của danh sách hiện tại
        
        self.video_files = []  # Danh sách file video
        self.is_processing = False
        
        self.setup_ui()
        
    def setup_ui(self):
        # Frame chọn folder input
        folder_frame = ttk.LabelFrame(self.root, text="Chọn thư mục video tăng tốc", padding=10)
        folder_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Entry(folder_frame, textvariable=self.folder_path, width=50).pack(side="left", padx=5)
        ttk.Button(folder_frame, text="Chọn thư mục", command=self.select_folder).pack(side="left")
        ttk.Button(folder_frame, text="Tải danh sách", command=self.load_video_list).pack(side="left", padx=5)
        
        # Frame chọn folder output
        output_frame = ttk.LabelFrame(self.root, text="Chọn thư mục video ghép lại thành 1 video", padding=10)
        output_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Entry(output_frame, textvariable=self.output_path, width=50).pack(side="left", padx=5)
        ttk.Button(output_frame, text="Chọn thư mục", command=self.select_output_folder).pack(side="left")
        ttk.Button(output_frame, text="Tải danh sách", command=self.load_output_video_list).pack(side="left", padx=5)
        
        # Frame danh sách file và sắp xếp
        list_frame = ttk.LabelFrame(self.root, text="Danh sách video (kéo thả để sắp xếp)", padding=10)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Listbox với scrollbar
        list_scroll_frame = ttk.Frame(list_frame)
        list_scroll_frame.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_scroll_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.file_listbox = tk.Listbox(list_scroll_frame, yscrollcommand=scrollbar.set, 
                                       selectmode=tk.SINGLE, height=8)
        self.file_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.file_listbox.yview)
        
        # Nút điều chỉnh thứ tự
        order_btn_frame = ttk.Frame(list_frame)
        order_btn_frame.pack(fill="x", pady=5)
        ttk.Button(order_btn_frame, text="↑ Lên", command=self.move_up, width=10).pack(side="left", padx=2)
        ttk.Button(order_btn_frame, text="↓ Xuống", command=self.move_down, width=10).pack(side="left", padx=2)
        ttk.Button(order_btn_frame, text="� Xóa", command=self.remove_video, width=10).pack(side="left", padx=2)
        ttk.Button(order_btn_frame, text="�🔄 Đảo ngược", command=self.reverse_order, width=12).pack(side="left", padx=2)
        ttk.Button(order_btn_frame, text="🔢 Sắp xếp theo số", command=self.sort_by_number, width=15).pack(side="left", padx=2)
        
        # Frame tùy chọn
        options_frame = ttk.LabelFrame(self.root, text="Tùy chọn xử lý", padding=10)
        options_frame.pack(fill="x", padx=10, pady=5)
        
        # Checkbox tăng tốc
        speedup_frame = ttk.Frame(options_frame)
        speedup_frame.pack(fill="x", pady=2)
        ttk.Checkbutton(speedup_frame, text="Tăng tốc video", 
                       variable=self.enable_speedup).pack(side="left")
        ttk.Label(speedup_frame, text="Tốc độ:").pack(side="left", padx=(20, 5))
        speed_entry = ttk.Entry(speedup_frame, textvariable=self.speed_var, width=8)
        speed_entry.pack(side="left")
        ttk.Label(speedup_frame, text="x").pack(side="left", padx=2)
        
        # Checkbox chuyển video dọc
        ttk.Checkbutton(options_frame,
                        text="Chuyển video dọc (9:16) + header CatSubz (từ danh sách hiện tại)",
                        variable=self.enable_vertical).pack(anchor="w", pady=2)

        # Checkbox ghép video
        ttk.Checkbutton(options_frame, text="Ghép các video thành 1 video duy nhất (theo thứ tự hiển thị)", 
                       variable=self.enable_concat).pack(anchor="w", pady=2)
        
        # Nút xử lý
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=10)
        
        self.process_btn = ttk.Button(button_frame, text="▶ Bắt đầu xử lý", 
                                       command=self.start_processing, width=20)
        self.process_btn.pack(side="left", padx=5)
        
        self.stop_btn = ttk.Button(button_frame, text="⏹ DỪNG KHẨN CẤP", 
                                    command=self.emergency_stop, width=20, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        
        ttk.Button(button_frame, text="📁 Mở thư mục output", 
                  command=self.open_output_folder, width=20).pack(side="left", padx=5)
        
        # Log area
        log_frame = ttk.LabelFrame(self.root, text="Nhật ký xử lý", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill="both", expand=True)
        
        # Progress
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(fill="x", padx=10, pady=5)
        
    def select_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa video")
        if folder:
            self.folder_path.set(folder)
    
    def select_output_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục lưu kết quả", 
                                        initialdir=self.output_path.get())
        if folder:
            self.output_path.set(folder)
    
    def load_video_list(self):
        """Tải danh sách video từ thư mục video tăng tốc (input)"""
        folder = self.folder_path.get()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Lỗi", "Vui lòng chọn thư mục video tăng tốc hợp lệ!")
            return
        
        files = [f for f in os.listdir(folder) if f.lower().endswith(VIDEO_EXTS)]
        if not files:
            messagebox.showwarning("Cảnh báo", "Không tìm thấy file video nào trong thư mục!")
            return
        
        # Sắp xếp theo số thứ tự
        files.sort(key=extract_number_from_filename)
        
        self.video_files = files
        self.list_source = 'input'
        self.update_listbox()
        self.log(f"✅ Đã tải {len(files)} file video từ: {folder}")
    
    def load_output_video_list(self):
        """Tải danh sách video từ thư mục video ghép (output)"""
        folder = self.output_path.get()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Lỗi", "Vui lòng chọn thư mục video ghép hợp lệ!")
            return
        
        files = [f for f in os.listdir(folder) if f.lower().endswith(VIDEO_EXTS)]
        if not files:
            messagebox.showwarning("Cảnh báo", "Không tìm thấy file video nào trong thư mục!")
            return
        
        # Sắp xếp theo số thứ tự
        files.sort(key=extract_number_from_filename)
        
        self.video_files = files
        self.list_source = 'output'
        self.update_listbox()
        self.log(f"✅ Đã tải {len(files)} file video từ: {folder}")
    
    def update_listbox(self):
        """Cập nhật listbox hiển thị"""
        self.file_listbox.delete(0, tk.END)
        for idx, filename in enumerate(self.video_files, start=1):
            self.file_listbox.insert(tk.END, f"{idx}. {filename}")
    
    def move_up(self):
        """Di chuyển file lên trên"""
        selection = self.file_listbox.curselection()
        if not selection or selection[0] == 0:
            return
        
        idx = selection[0]
        self.video_files[idx], self.video_files[idx-1] = self.video_files[idx-1], self.video_files[idx]
        self.update_listbox()
        self.file_listbox.select_set(idx-1)
    
    def move_down(self):
        """Di chuyển file xuống dưới"""
        selection = self.file_listbox.curselection()
        if not selection or selection[0] == len(self.video_files) - 1:
            return
        
        idx = selection[0]
        self.video_files[idx], self.video_files[idx+1] = self.video_files[idx+1], self.video_files[idx]
        self.update_listbox()
        self.file_listbox.select_set(idx+1)
    
    def reverse_order(self):
        """Đảo ngược thứ tự"""
        if not self.video_files:
            return
        self.video_files.reverse()
        self.update_listbox()
        self.log("🔄 Đã đảo ngược thứ tự danh sách")
    
    def sort_by_number(self):
        """Sắp xếp lại theo số thứ tự"""
        if not self.video_files:
            return
        self.video_files.sort(key=extract_number_from_filename)
        self.update_listbox()
        self.log("🔢 Đã sắp xếp lại theo số thứ tự")
    
    def remove_video(self):
        """Xóa video được chọn khỏi danh sách"""
        selection = self.file_listbox.curselection()
        if not selection:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn video cần xóa!")
            return
        
        idx = selection[0]
        removed_file = self.video_files.pop(idx)
        self.update_listbox()
        self.log(f"🗑 Đã xóa: {removed_file}")
        
        # Chọn lại item gần đó nếu còn
        if self.video_files:
            new_idx = min(idx, len(self.video_files) - 1)
            self.file_listbox.select_set(new_idx)
    
    def emergency_stop(self):
        """Dừng xử lý khẩn cấp"""
        global stop_processing
        stop_processing = True
        self.log("⏹ ĐANG DỪNG KHẨN CẤP...")
        self.stop_btn.config(state="disabled")
            
    def open_output_folder(self):
        output_dir = self.output_path.get()
        if os.path.exists(output_dir):
            os.startfile(output_dir)
        else:
            messagebox.showwarning("Cảnh báo", "Thư mục output chưa tồn tại!")
            
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update()
        
    def start_processing(self):
        if not self.video_files:
            messagebox.showwarning("Cảnh báo", "Vui lòng tải danh sách video trước!")
            return
        
        try:
            speed = float(self.speed_var.get())
            if speed <= 0 or speed > 10:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Lỗi", "Tốc độ phải là số dương (0-10)!")
            return
        
        if (not self.enable_speedup.get()) and (not self.enable_vertical.get()) and (not self.enable_concat.get()):
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 chức năng!")
            return
        
        # Reset stop flag
        global stop_processing
        stop_processing = False
        
        # Chạy trong thread riêng để không block UI
        thread = threading.Thread(target=self.process_videos, 
                                 args=(speed,), daemon=True)
        thread.start()
        
    def process_videos(self, speed):
        global stop_processing
        self.process_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress.start()
        self.log_text.delete(1.0, tk.END)
        
        # Xác định thư mục nguồn và đích
        input_folder = self.folder_path.get()
        output_dir = self.output_path.get()
        
        try:
            self.log("=" * 60)
            self.log("BẮT ĐẦU XỬ LÝ VIDEO")
            self.log("=" * 60)
            
            # Đảm bảo thư mục output tồn tại
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir, exist_ok=True)
                self.log(f"✅ Đã tạo thư mục output: {output_dir}")
            
            # Sử dụng danh sách đã sắp xếp
            files = self.video_files
            
            self.log(f"\n📋 DANH SÁCH VIDEO ({len(files)} file):")
            self.log("-" * 60)
            for idx, name in enumerate(files, start=1):
                self.log(f"  {idx}. {name}")
            
            if stop_processing:
                self.log("\n⏹ ĐÃ DỪNG BỞI NGƯỜI DÙNG")
                return
            
            processed_files = []
            
            # Bước 1: Tăng tốc (nếu được chọn)
            if self.enable_speedup.get():
                self.log(f"\n📹 BƯỚC 1: TĂNG TỐC VIDEO ({speed}x)")
                self.log("-" * 60)
                self.log(f"📁 Thư mục nguồn: {input_folder}")
                self.log(f"📁 Thư mục đích: {output_dir}")
                
                for idx, name in enumerate(files, start=1):
                    if stop_processing:
                        self.log("\n⏹ ĐÃ DỪNG BỞI NGƯỜI DÙNG")
                        return
                    
                    full_in = os.path.join(input_folder, name)
                    base, _ = os.path.splitext(name)
                    out_name = f"{base}_{speed}x.mp4"
                    full_out = os.path.join(output_dir, out_name)
                    
                    if os.path.isfile(full_out):
                        self.log(f"[{idx}/{len(files)}] 🔁 Bỏ qua (đã có): {out_name}")
                        processed_files.append(full_out)
                        continue
                    
                    self.log(f"[{idx}/{len(files)}] 🚀 Đang xử lý: {name}")
                    ok = speed_up_video(full_in, full_out, speed)
                    if ok:
                        self.log(f"    ✅ Xong: {out_name}")
                        processed_files.append(full_out)
                    else:
                        self.log(f"    ❌ Lỗi: {name}")
            else:
                # Nếu không tăng tốc: dùng đúng nguồn của danh sách hiện tại
                src_folder = input_folder if self.list_source == 'input' else output_dir
                self.log(f"\n⏭ BỎ QUA TĂNG TỐC, DÙNG VIDEO TỪ: {src_folder}")
                processed_files = [os.path.join(src_folder, f) for f in files]
            
            if stop_processing:
                self.log("\n⏹ ĐÃ DỪNG BỞI NGƯỜI DÙNG")
                return
            
            if stop_processing:
                self.log("\n⏹ ĐÃ DỪNG BỞI NGƯỜI DÙNG")
                return

            # Bước 2: Chuyển video dọc (nếu được chọn)
            if self.enable_vertical.get() and processed_files:
                self.log(f"\n📱 BƯỚC 2: CHUYỂN VIDEO DỌC (9:16)")
                self.log("-" * 60)

                vertical_files = []
                for idx, in_path in enumerate(processed_files, start=1):
                    if stop_processing:
                        self.log("\n⏹ ĐÃ DỪNG BỞI NGƯỜI DÙNG")
                        return

                    base = os.path.splitext(os.path.basename(in_path))[0]
                    out_name = f"{base}_vertical.mp4"
                    out_path = os.path.join(output_dir, out_name)

                    if os.path.isfile(out_path):
                        self.log(f"[{idx}/{len(processed_files)}] 🔁 Bỏ qua (đã có): {out_name}")
                        vertical_files.append(out_path)
                        continue

                    self.log(f"[{idx}/{len(processed_files)}] 📱 Đang chuyển dọc: {os.path.basename(in_path)}")
                    ok = verticalize_video(in_path, out_path)
                    if ok:
                        self.log(f"    ✅ Xong: {out_name}")
                        vertical_files.append(out_path)
                    else:
                        self.log(f"    ❌ Lỗi chuyển dọc: {os.path.basename(in_path)}")

                # nếu có file dọc, dùng danh sách đó cho bước ghép
                if vertical_files:
                    processed_files = vertical_files

            # Bước 2: Ghép video (nếu được chọn)
            if self.enable_concat.get() and processed_files:
                self.log(f"\n🔗 BƯỚC 2: GHÉP VIDEO")
                self.log("-" * 60)
                self.log(f"📋 Thứ tự ghép ({len(processed_files)} file):")
                for idx, path in enumerate(processed_files, start=1):
                    self.log(f"  {idx}. {os.path.basename(path)}")
                
                # Tạo tên file theo version để không đè file cũ
                version = 1
                while True:
                    concat_output = os.path.join(output_dir, f"merged_output_v{version}.mp4")
                    if not os.path.exists(concat_output):
                        break
                    version += 1
                
                concat_videos(processed_files, concat_output, self.log)
            
            if not stop_processing:
                self.log("\n" + "=" * 60)
                self.log("✅ HOÀN TẤT TẤT CẢ")
                self.log("=" * 60)
                messagebox.showinfo("Thành công", "Xử lý video hoàn tất!")
            
        except Exception as e:
            self.log(f"❌ LỖI: {e}")
            messagebox.showerror("Lỗi", f"Có lỗi xảy ra: {e}")
        finally:
            self.progress.stop()
            self.process_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            stop_processing = False


def main():
    root = tk.Tk()
    app = VideoProcessorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
