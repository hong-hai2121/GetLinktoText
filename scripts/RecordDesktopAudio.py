# -*- coding: utf-8 -*-
"""
RecordDesktopAudio.py

Chức năng:
- Ghi âm thanh desktop (âm thanh đang phát trên máy tính)
- Nhận diện giọng nói bằng Whisper (tiếng Trung)
- Lưu transcript vào file TXT

Yêu cầu:
- Windows: cài soundcard (pip install soundcard)
- Whisper (pip install openai-whisper)
- torch, numpy, soundfile
"""

import os
import sys
import time
import torch
import whisper
import numpy as np
from datetime import datetime

# Kiểm tra thư viện ghi âm
try:
    import soundcard as sc
    import soundfile as sf
except ImportError:
    print("❌ Cần cài đặt: pip install soundcard soundfile")
    sys.exit(1)

# Kiểm tra thư viện GUI
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    import threading
except ImportError:
    print("❌ Cần cài đặt tkinter")
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


# ================= CẤU HÌNH =================
WHISPER_MODEL_PATH = "whisper_cache"
MODEL_NAME = "large-v3"  # large-v3, medium, small
OUTPUT_DIR = "output_videos"
SAMPLE_RATE = 16000  # Whisper yêu cầu 16kHz

# Kiểm tra GPU
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"✅ Whisper sẽ chạy trên {'GPU' if device == 'cuda' else 'CPU'}")

# Tạo thư mục
os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Xóa tất cả file trong OUTPUT_DIR khi bắt đầu
def clear_output_directory():
    if os.path.exists(OUTPUT_DIR):
        for file in os.listdir(OUTPUT_DIR):
            file_path = os.path.join(OUTPUT_DIR, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"⚠️ Không thể xóa {file_path}: {e}")

# KHÔNG xóa file ngay startup - để giữ lại kết quả lần trước
# Nếu muốn xóa, bỏ comment dòng dưới
# print("🗑️ Đang xóa file cũ trong thư mục output_videos...")
# clear_output_directory()
# print("✅ Đã xóa xong.")

# Model sẽ được load khi cần thiết (lazy loading)
model = None


def list_audio_devices():
    """Liệt kê tất cả thiết bị âm thanh"""
    print("\n📢 Danh sách thiết bị âm thanh:")
    mics = sc.all_microphones(include_loopback=True)
    for idx, mic in enumerate(mics):
        loopback = " [LOOPBACK]" if mic.isloopback else ""
        print(f"  [{idx}] {mic.name}{loopback}")
    return mics


def get_default_loopback():
    """Lấy thiết bị loopback mặc định (ghi âm desktop)"""
    loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    if not loopbacks:
        print("❌ Không tìm thấy thiết bị loopback (ghi âm desktop).")
        print("💡 Bật 'Stereo Mix' trong Windows Sound Settings.")
        return None
    return loopbacks[0]


def record_audio(device, duration_sec, output_path):
    """
    Ghi âm từ thiết bị trong duration_sec giây
    Lưu file WAV tại output_path
    """
    print(f"\n🎙️ Đang ghi âm {duration_sec} giây từ: {device.name}")
    print("⏱️ Bắt đầu ghi...")
    
    start_time = time.time()
    
    with device.recorder(samplerate=SAMPLE_RATE, channels=1) as mic:
        audio_data = []
        while time.time() - start_time < duration_sec:
            data = mic.record(numframes=SAMPLE_RATE)  # Ghi 1 giây
            audio_data.append(data)
            elapsed = int(time.time() - start_time)
            remaining = duration_sec - elapsed
            print(f"    ⏳ Đã ghi: {elapsed}s / {duration_sec}s (còn {remaining}s)", end="\r")
    
    print("\n✅ Ghi âm hoàn tất!")
    
    # Ghép và lưu file
    audio_array = np.concatenate(audio_data, axis=0)
    audio_array = audio_array.flatten()  # Chuyển về 1D
    
    sf.write(output_path, audio_array, SAMPLE_RATE)
    print(f"💾 Đã lưu file: {output_path}")
    
    return output_path


def transcribe_chinese(audio_path):
    """Nhận diện giọng nói tiếng Trung bằng Whisper"""
    print(f"\n📝 Đang nhận diện giọng nói (tiếng Trung)...")
    
    result = model.transcribe(
        audio_path,
        language="zh",  # Tiếng Trung
        verbose=False,
        word_timestamps=False
    )
    
    transcript = result["text"].strip()
    print("✅ Nhận diện hoàn tất!")
    return transcript


def save_transcript(transcript, output_path):
    """Lưu transcript vào file TXT"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript)
    print(f"💾 Đã lưu transcript: {output_path}")


class RecorderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Ghi Âm Desktop & Nhận Diện Tiếng Trung")
        center_on_screen(self.root, 600, 500)
        self.root.resizable(False, False)
        
        # Biến trạng thái
        self.is_recording = False
        self.audio_data = []
        self.start_time = None
        self.elapsed_seconds = 0
        self.recording_thread = None
        self.device = None
        self.audio_path = None
        
        self.setup_ui()
        self.load_devices()
    
    def setup_ui(self):
        # Frame chính
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Tiêu đề
        title = ttk.Label(main_frame, text="🎙️ GHI ÂM DESKTOP", 
                         font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        # Chọn thiết bị
        device_frame = ttk.LabelFrame(main_frame, text="Thiết bị ghi âm", padding="10")
        device_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(device_frame, textvariable=self.device_var, 
                                         state="readonly", width=50)
        self.device_combo.pack(fill=tk.X)
        
        # Hiển thị thời gian
        time_frame = ttk.LabelFrame(main_frame, text="Thời gian ghi", padding="10")
        time_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.time_label = ttk.Label(time_frame, text="00:00", 
                                    font=("Arial", 36, "bold"),
                                    foreground="#2196F3")
        self.time_label.pack()
        
        # Trạng thái
        self.status_label = ttk.Label(main_frame, text="⚪ Sẵn sàng", 
                                      font=("Arial", 12))
        self.status_label.pack(pady=(0, 15))
        
        # Nút điều khiển
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(0, 15))
        
        self.start_btn = ttk.Button(button_frame, text="▶️ Bắt Đầu Ghi", 
                                    command=self.start_recording,
                                    width=20)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(button_frame, text="⏹️ Kết Thúc", 
                                   command=self.stop_recording,
                                   state=tk.DISABLED,
                                   width=20)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # Kết quả
        result_frame = ttk.LabelFrame(main_frame, text="Kết quả nhận diện", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        self.result_text = tk.Text(result_frame, height=8, width=70, wrap=tk.WORD,
                                   font=("Arial", 10))
        self.result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(result_frame, command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.config(yscrollcommand=scrollbar.set)
    
    def load_devices(self):
        """Tải danh sách thiết bị loopback"""
        try:
            devices = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
            if not devices:
                self.device_combo['values'] = ["Không tìm thấy thiết bị loopback"]
                self.device_combo.current(0)
                self.device_combo.config(state=tk.DISABLED)
                self.start_btn.config(state=tk.DISABLED)
                self.status_label.config(text="❌ Không tìm thấy thiết bị loopback", foreground="red")
                self.devices = []
                
                messagebox.showwarning("Cảnh báo", 
                                   "Không tìm thấy thiết bị loopback!\n\n"
                                   "Vui lòng bật Stereo Mix:\n"
                                   "1. Chuột phải icon loa > Sounds\n"
                                   "2. Tab Recording > Show Disabled Devices\n"
                                   "3. Enable Stereo Mix\n"
                                   "4. Set as Default Device\n\n"
                                   "Sau đó khởi động lại ứng dụng.")
                return
            
            device_names = [d.name for d in devices]
            self.device_combo['values'] = device_names
            self.device_combo.current(0)
            self.devices = devices
            
        except Exception as e:
            # Xử lý lỗi khi không thể lấy danh sách thiết bị
            self.device_combo['values'] = ["Lỗi khi lấy thiết bị âm thanh"]
            self.device_combo.current(0)
            self.device_combo.config(state=tk.DISABLED)
            self.start_btn.config(state=tk.DISABLED)
            self.status_label.config(text="❌ Lỗi khi tải thiết bị", foreground="red")
            self.devices = []
            
            messagebox.showerror("Lỗi", 
                               f"Không thể lấy danh sách thiết bị âm thanh!\n\n"
                               f"Lỗi: {str(e)}\n\n"
                               f"Vui lòng kiểm tra:\n"
                               f"- Thư viện soundcard đã cài đúng chưa\n"
                               f"- Driver âm thanh có hoạt động không")
    
    def update_timer(self):
        """Cập nhật đếm giây"""
        if self.is_recording:
            elapsed = int(time.time() - self.start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.time_label.config(text=f"{minutes:02d}:{seconds:02d}")
            self.root.after(100, self.update_timer)
    
    def record_worker(self):
        """Thread ghi âm"""
        try:
            selected_idx = self.device_combo.current()
            self.device = self.devices[selected_idx]
            
            with self.device.recorder(samplerate=SAMPLE_RATE, channels=1) as mic:
                while self.is_recording:
                    data = mic.record(numframes=SAMPLE_RATE // 10)  # 0.1s chunks
                    self.audio_data.append(data)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Lỗi ghi âm", str(e)))
            self.is_recording = False
    
    def start_recording(self):
        """Bắt đầu ghi âm"""
        self.is_recording = True
        self.audio_data = []
        self.start_time = time.time()
        
        # Cập nhật UI
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.device_combo.config(state=tk.DISABLED)
        self.status_label.config(text="🔴 Đang ghi âm...", foreground="red")
        self.result_text.delete(1.0, tk.END)
        
        # Bắt đầu thread ghi âm
        self.recording_thread = threading.Thread(target=self.record_worker, daemon=True)
        self.recording_thread.start()
        
        # Bắt đầu đếm giây
        self.update_timer()
    
    def stop_recording(self):
        """Kết thúc ghi âm và nhận diện"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        self.status_label.config(text="⏳ Đang xử lý...", foreground="orange")
        self.stop_btn.config(state=tk.DISABLED)
        
        # Đợi thread ghi âm kết thúc
        if self.recording_thread:
            self.recording_thread.join(timeout=2)
        
        # Xử lý audio trong thread riêng
        threading.Thread(target=self.process_audio, daemon=True).start()
    
    def process_audio(self):
        """Lưu và nhận diện audio"""
        try:
            # Ghép audio
            if not self.audio_data:
                self.root.after(0, lambda: messagebox.showwarning("Cảnh báo", 
                                                                  "Không có dữ liệu âm thanh!"))
                self.reset_ui()
                return
            
            audio_array = np.concatenate(self.audio_data, axis=0).flatten()
            
            # Lưu file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.audio_path = os.path.join(OUTPUT_DIR, f"desktop_audio_{timestamp}.wav")
            sf.write(self.audio_path, audio_array, SAMPLE_RATE)
            
            # Load model nếu chưa có (lazy loading)
            global model
            if model is None:
                print(f"🔄 Đang tải mô hình Whisper '{MODEL_NAME}'...")
                model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
                print("✅ Model đã tải xong.")
            
            # Nhận diện
            result = model.transcribe(
                self.audio_path,
                language="zh",
                verbose=False,
                word_timestamps=False
            )
            
            transcript = result["text"].strip()
            
            if transcript:
                # Lưu transcript
                transcript_path = os.path.join(OUTPUT_DIR, 
                                              f"transcript_{timestamp}.txt")
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write(transcript)
                
                # Hiển thị kết quả
                self.root.after(0, lambda: self.show_result(transcript))
            else:
                self.root.after(0, lambda: messagebox.showinfo("Thông báo", 
                                                               "Không nhận diện được nội dung!"))
            
            self.root.after(0, self.reset_ui)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Lỗi", str(e)))
            self.root.after(0, self.reset_ui)
    
    def show_result(self, transcript):
        """Hiển thị kết quả"""
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(1.0, transcript)
        self.status_label.config(text="✅ Hoàn tất!", foreground="green")
    
    def reset_ui(self):
        """Reset giao diện"""
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.device_combo.config(state="readonly")
        self.time_label.config(text="00:00")


def main():
    try:
        root = tk.Tk()
        app = RecorderGUI(root)
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
