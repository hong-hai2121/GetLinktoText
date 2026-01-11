# -*- coding: utf-8 -*-
"""
NhanDienGiongNoiTaoSRT.py

Chức năng:
- Chọn thư mục chứa các file video .mp4 (thường là thư mục sau khi chia đoạn)
- Trích xuất âm thanh từ mỗi video
- Nhận diện giọng nói bằng Whisper (tiếng Trung)
- Tạo file SRT với timestamps và nội dung
- Lưu file SRT cùng thư mục với video

Yêu cầu:
- ffmpeg trong PATH
- Whisper model đã tồn tại trong whisper_cache
"""

import os
import sys
import subprocess
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
from pathlib import Path

try:
    import whisper
    import torch
    import srt
    from datetime import timedelta
except ImportError as e:
    print(f"❌ Cần cài đặt: pip install openai-whisper torch srt")
    sys.exit(1)

# ================= CẤU HÌNH =================
WHISPER_MODEL_PATH = "whisper_cache"
MODEL_NAME = "medium"  # large-v3, medium, small
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov")

# Kiểm tra GPU
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"✅ Whisper sẽ chạy trên {'GPU' if device == 'cuda' else 'CPU'}")

# Kiểm tra ffmpeg
import shutil
FFMPEG_PATH = shutil.which("ffmpeg")
if FFMPEG_PATH is None:
    print("❌ ffmpeg không có trong PATH. Cài ffmpeg trước khi chạy.")
    sys.exit(1)

# Model sẽ được load khi cần thiết
model = None


def get_model():
    """Load Whisper model (lazy loading)"""
    global model
    if model is None:
        print(f"🔄 Đang tải mô hình Whisper '{MODEL_NAME}'...")
        model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
        print("✅ Model đã tải xong.")
    return model


def extract_audio_to_wav(video_path, output_wav):
    """Trích xuất âm thanh từ video sang WAV"""
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Lỗi trích xuất âm thanh: {e}")
        return False


def transcribe_to_segments(audio_path):
    """Nhận diện giọng nói và trả về segments có timestamp"""
    model = get_model()
    
    print("  📝 Đang nhận diện giọng nói (tiếng Trung)...")
    result = model.transcribe(
        audio_path,
        language="zh",
        verbose=False,
        word_timestamps=True
    )
    
    # Lấy segments (mỗi segment có start, end, text)
    segments = result.get("segments", [])
    print(f"  ✅ Nhận diện xong ({len(segments)} đoạn)")
    
    return segments


def segments_to_srt(segments):
    """Chuyển segments Whisper thành SRT subtitles"""
    subtitles = []
    
    for idx, segment in enumerate(segments, start=1):
        start_time = timedelta(seconds=segment["start"])
        end_time = timedelta(seconds=segment["end"])
        text = segment["text"].strip()
        
        if text:  # Chỉ thêm nếu có nội dung
            sub = srt.Subtitle(
                index=idx,
                start=start_time,
                end=end_time,
                content=text
            )
            subtitles.append(sub)
    
    return subtitles


def save_srt(subtitles, output_path):
    """Lưu SRT file"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))
    print(f"  💾 Đã lưu SRT: {output_path}")


def process_video(video_path):
    """Xử lý 1 video: trích audio → nhận diện → tạo SRT"""
    video_name = os.path.basename(video_path)
    base_name = os.path.splitext(video_name)[0]
    video_dir = os.path.dirname(video_path)
    srt_output = os.path.join(video_dir, f"{base_name}.srt")
    
    # Nếu SRT đã tồn tại, bỏ qua
    if os.path.isfile(srt_output):
        print(f"  🔁 Bỏ qua (SRT đã tồn tại): {srt_output}")
        return True
    
    print(f"\n{'='*60}")
    print(f"🎬 Xử lý: {video_name}")
    
    # Trích audio tạm
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        temp_wav = tmp.name
    
    try:
        print(f"  🎵 Đang trích âm thanh...")
        if not extract_audio_to_wav(video_path, temp_wav):
            return False
        
        # Nhận diện
        segments = transcribe_to_segments(temp_wav)
        
        if not segments:
            print(f"  ⚠️ Không nhận diện được nội dung")
            return False
        
        # Tạo SRT
        subtitles = segments_to_srt(segments)
        save_srt(subtitles, srt_output)
        
        print(f"  ✅ Hoàn tất: {srt_output}")
        return True
        
    except Exception as e:
        print(f"  ❌ Lỗi: {e}")
        return False
    finally:
        # Xóa file tạm
        if os.path.exists(temp_wav):
            os.unlink(temp_wav)


class NhanDienGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Nhận Diện Giọng Nói & Tạo SRT")
        self.root.geometry("700x600")
        self.root.resizable(False, False)
        
        self.is_processing = False
        self.videos = []
        self.processed_count = 0
        
        self.setup_ui()
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Tiêu đề
        title = ttk.Label(main_frame, text="🎙️ NHẬN DIỆN GIỌNG NÓI & TẠO SRT",
                         font=("Arial", 14, "bold"))
        title.pack(pady=(0, 20))
        
        # Thư mục
        folder_frame = ttk.LabelFrame(main_frame, text="Thư mục video", padding="10")
        folder_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.folder_label = ttk.Label(folder_frame, text="Chưa chọn thư mục",
                                      font=("Arial", 10), foreground="gray")
        self.folder_label.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(folder_frame, text="📁 Chọn Thư Mục",
                  command=self.select_folder).pack(fill=tk.X)
        
        # Danh sách video
        list_frame = ttk.LabelFrame(main_frame, text="Danh sách video cần xử lý", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Scrollbar + Listbox
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.video_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                        font=("Arial", 9), height=12)
        self.video_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.video_listbox.yview)
        
        # Nút xử lý
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.start_btn = ttk.Button(button_frame, text="▶️ Bắt Đầu Xử Lý",
                                    command=self.start_processing, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(button_frame, text="⏹️ Dừng",
                                   command=self.stop_processing, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # Trạng thái
        self.status_label = ttk.Label(main_frame, text="⚪ Sẵn sàng",
                                      font=("Arial", 11), foreground="blue")
        self.status_label.pack(pady=(0, 10))
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var,
                                           maximum=100, length=600, mode='determinate')
        self.progress_bar.pack(fill=tk.X)
    
    def select_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa video")
        if not folder:
            return
        
        # Tìm tất cả video
        self.videos = []
        for ext in VIDEO_EXTS:
            self.videos.extend([
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.lower().endswith(ext) and os.path.isfile(os.path.join(folder, f))
            ])
        
        self.videos.sort()
        
        if not self.videos:
            messagebox.showwarning("Cảnh báo", f"Không tìm thấy video nào trong thư mục.\n\nHỗ trợ: {', '.join(VIDEO_EXTS)}")
            return
        
        # Cập nhật UI
        self.folder_label.config(text=folder, foreground="black")
        self.video_listbox.delete(0, tk.END)
        for video in self.videos:
            self.video_listbox.insert(tk.END, os.path.basename(video))
        
        self.start_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"✅ Tìm thấy {len(self.videos)} video", foreground="green")
    
    def start_processing(self):
        if not self.videos:
            return
        
        self.is_processing = True
        self.processed_count = 0
        
        # Cập nhật UI
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.video_listbox.config(state=tk.DISABLED)
        self.status_label.config(text="🔴 Đang xử lý...", foreground="red")
        
        # Chạy trong thread
        threading.Thread(target=self.process_all, daemon=True).start()
    
    def process_all(self):
        for idx, video_path in enumerate(self.videos, start=1):
            if not self.is_processing:
                break
            
            # Cập nhật progress
            progress = (idx - 1) / len(self.videos) * 100
            self.root.after(0, lambda p=progress: self.progress_var.set(p))
            
            # Xử lý video
            ok = process_video(video_path)
            if ok:
                self.processed_count += 1
                self.video_listbox.itemconfig(idx - 1, fg="green")
            else:
                self.video_listbox.itemconfig(idx - 1, fg="red")
        
        # Hoàn tất
        self.root.after(0, self.finish_processing)
    
    def finish_processing(self):
        self.is_processing = False
        self.progress_var.set(100)
        
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.video_listbox.config(state=tk.NORMAL)
        
        msg = f"✅ Hoàn tất! Xử lý thành công {self.processed_count}/{len(self.videos)} video"
        self.status_label.config(text=msg, foreground="green")
        messagebox.showinfo("Thông báo", msg)
    
    def stop_processing(self):
        self.is_processing = False
        self.status_label.config(text="⏸️ Dừng theo yêu cầu", foreground="orange")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)


def main():
    try:
        root = tk.Tk()
        app = NhanDienGUI(root)
        root.mainloop()
    except Exception as e:
        import traceback
        print("\n" + "="*70)
        print("❌ LỖI KHÔNG MONG MUỐN:")
        print("="*70)
        traceback.print_exc()
        print("="*70)
        input("\nNhấn Enter để thoát...")


if __name__ == "__main__":
    main()
