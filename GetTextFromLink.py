import os
import yt_dlp
import subprocess
import shutil
import re
import time
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
from docx import Document  
from docx.shared import RGBColor, Pt  
from pydub import AudioSegment
from collections import Counter
from profiles_config import get_profile
import gc
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import platform
import sys

# ================= Cấu hình =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LINKS_FILE = os.path.join(BASE_DIR, "linkgettoText.txt")
OUTPUT_WORD_FILE = os.path.join(BASE_DIR, "final_result.docx")
WHISPER_MODEL_PATH = "whisper_cache"  # Thư mục lưu mô hình Whisper
OUTPUT_VIDEO_DIR = "output_videos"  # Thư mục lưu video tải xuống
MODEL_NAME = "medium"  # Đặt đúng tên file mô hình đã có (large-v3,medium,small)
FFMPEG_PATH = shutil.which("ffmpeg")  # Kiểm tra ffmpeg

# ================= Thông báo âm thanh =================
def play_sound(sound_type="success"):
    """
    Phát âm thanh thông báo
    sound_type: "success" (hoàn thành), "error" (lỗi), "warning" (cảnh báo)
    """
    try:
        if platform.system() == "Windows":
            import winsound
            if sound_type == "success":
                # 3 tiếng beep ngắn cho thành công
                for _ in range(3):
                    winsound.Beep(1000, 200)  # Tần số 1000Hz, thời lượng 200ms
                    time.sleep(0.1)
            elif sound_type == "error":
                # 2 tiếng beep dài cho lỗi
                for _ in range(2):
                    winsound.Beep(400, 300)  # Tần số 400Hz, thời lượng 300ms
                    time.sleep(0.1)
            elif sound_type == "warning":
                # 1 tiếng beep cho cảnh báo
                winsound.Beep(800, 200)
        elif platform.system() == "Darwin":  # macOS
            os.system('afplay /System/Library/Sounds/Glass.aiff' if sound_type != "error" else 'afplay /System/Library/Sounds/Sosumi.aiff')
        elif platform.system() == "Linux":
            # Dùng paplay hoặc beep trên Linux
            try:
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"], timeout=2)
            except:
                os.system("beep")
    except Exception as e:
        print(f"⚠️ Lỗi khi phát âm thanh: {e}")

# Cấu hình chia nhỏ audio khi bật gợi ý đặt tên
CHUNK_LENGTH_MS = 3 * 60 * 1000  # 3 phút/đoạn
DEFAULT_MAX_CHUNKS = 2  # Mặc định nhận diện 5 đoạn đầu

# Global driver dùng chung từ khi khởi động
# Global driver dùng chung từ khi khởi động
global_driver = None

# --- NEW: chống mở firefox 2 lần ---
DRIVER_LOCK = threading.Lock()
FIREFOX_INIT_EVENT = threading.Event()
FIREFOX_INIT_IN_PROGRESS = False

def is_driver_alive(drv):
    try:
        if drv is None:
            return False
        _ = drv.current_url
        return True
    except Exception:
        return False
    
CHECK_TITLE_BLACKLIST = False  # Đổi thành False nếu không muốn kiểm tra tiêu đề True
BLACKLIST_KEYWORDS2 = [
    "da căng bóng","sáng da","da trẻ","da bóng","sạch da","da","nám",
    "nấm","n.ấm","n ấm","n .ấm",
    "nám", "n .ám","n ám","n.ám",
    "mụn","m .ụn","m ụn","m.ụn",
    "serum",
    "skincare",
    "tẩy trang",
    # Thêm các từ khóa bạn muốn chặn vào đây
]

BLACKLIST_KEYWORDS = []


if FFMPEG_PATH is None:
    print("⚠️ ffmpeg không có trong PATH. Hãy cài đặt ffmpeg để tiếp tục.")
    exit(1)

device = "cpu"  # hoặc "unknown"
    
# Tạo thư mục nếu chưa có
os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)

# Không load model ngay - để GUI load khi cần
model = None
model2 = None


USE_TITLE_MODE = False  # Bật/tắt chế độ gợi ý đặt tên + chia nhỏ audio
MAX_CHUNKS_RUNTIME = DEFAULT_MAX_CHUNKS

# Khi USE_TITLE_MODE=True:
# - "title_only": chỉ gửi Yêu cầu 1 (tiêu đề)
# - "content_only": chỉ lưu nội dung transcript đã gộp từ các chunk
# - "full": gửi đủ 3 yêu cầu (tiêu đề + mô tả + tag)
TITLE_MODE_SUBMODE = "full"

# Xóa tất cả file trong thư mục nhưng giữ lại thư mục
def clear_output_directory(directory):
    if os.path.exists(directory):
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)  # Xóa file hoặc symbolic link
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)  # Xóa thư mục con nếu có
            except Exception as e:
                print(f"⚠️ Lỗi khi xóa {file_path}: {e}")

# Gọi hàm xóa file trong thư mục output_video trước khi bắt đầu xử lý
clear_output_directory(OUTPUT_VIDEO_DIR)

# ✅ Cấu hình Firefox để gửi nội dung đến GPT
from profiles_config import FIREFOX_PROFILE_PATH

GECKODRIVER_PATH = r"D:\Python\GetLinktoText\geckodriver.exe"


def clean_link(line: str, fallback_index: int | None = None):
    """
    Nếu dòng có dạng '12. https://...' -> trả (12, url)
    Nếu không có số thứ tự:
      - Nếu có fallback_index: dùng fallback_index
      - Nếu không: tự tăng bộ đếm nội bộ (giống cách cũ nhưng không dùng mutable default arg)
    """
    match = re.match(r'^\s*(\d+)[\.\s]+\s*(https?://\S+)', line)
    if match:
        return int(match.group(1)), match.group(2)

    # không có số thứ tự
    if fallback_index is not None:
        return fallback_index, line.strip()

    # fallback cuối cùng: tự đếm (tránh counter=[0])
    if not hasattr(clean_link, "_counter"):
        clean_link._counter = 0
    clean_link._counter += 1
    return clean_link._counter, line.strip()




def init_firefox():
    """Khởi tạo trình duyệt Firefox với Selenium và mở ChatGPT."""
    options = FirefoxOptions()
    options.add_argument(f"-profile")
    options.add_argument(f"{FIREFOX_PROFILE_PATH}")
    service = FirefoxService(executable_path=GECKODRIVER_PATH)
    driver = webdriver.Firefox(service=service, options=options)
    # 🔽 Thu nhỏ cửa sổ ngay sau khi mở
    #driver.minimize_window()
    driver.get("https://chatgpt.com/")
    time.sleep(7)
    return driver

def restart_firefox():
    """Đóng Firefox hiện tại (nếu có) và mở lại cái mới (không mở trùng)."""
    global global_driver, FIREFOX_INIT_IN_PROGRESS

    # 1) Báo cho toàn chương trình biết: đang restart -> đừng ai tự mở thêm
    with DRIVER_LOCK:
        FIREFOX_INIT_IN_PROGRESS = True
        FIREFOX_INIT_EVENT.clear()

    try:
        # 2) Đóng driver hiện tại nếu có
        if global_driver is not None:
            try:
                print("🔴 Đang đóng Firefox...")
                try:
                    global_driver.quit()
                except:
                    pass
                time.sleep(1)
            except Exception as e:
                print(f"⚠️ Lỗi khi đóng Firefox: {e}")
            finally:
                global_driver = None

        # 3) Force kill firefox.exe (Windows) nếu còn sót
        try:
            subprocess.run(["taskkill", "/F", "/IM", "firefox.exe"], timeout=2)
            time.sleep(2)
        except:
            pass

        # 4) Mở Firefox mới
        print("🌐 Đang mở Firefox mới...")
        time.sleep(1)
        drv = init_firefox()

        # 5) Gán lại driver toàn cục
        with DRIVER_LOCK:
            global_driver = drv

        print("✅ Firefox đã khởi động lại thành công!")
        play_sound("success")
        return True

    except Exception as e:
        print(f"❌ Lỗi khi khởi động lại Firefox: {e}")
        play_sound("error")
        with DRIVER_LOCK:
            global_driver = None
        return False

    finally:
        # 6) Báo: restart đã xong (thành công hay thất bại cũng phải set event)
        with DRIVER_LOCK:
            FIREFOX_INIT_IN_PROGRESS = False
        FIREFOX_INIT_EVENT.set()

    
def check_title_blacklist(title):
    """Kiểm tra xem tiêu đề có chứa từ khóa trong danh sách cấm hay không, bỏ qua phần từ # đến cuối"""
    if not title or title == "Không thể lấy tiêu đề":
        return False  # Nếu không có tiêu đề, không chặn
    
    # Cắt bỏ phần từ # đến cuối tiêu đề
    title_clean = title.split("#")[0].strip() if "#" in title else title
    title_lower = title_clean.lower()  # Chuyển về chữ thường để so sánh
    
    for keyword in BLACKLIST_KEYWORDS:
        keyword_lower = keyword.lower()  # Chuyển từ khóa về chữ thường
        if keyword_lower in title_lower:
            print(f"⚠️ Tiêu đề '{title}' chứa từ khóa cấm '{keyword}' (phần kiểm tra: '{title_clean}'), bỏ qua video.")
            return True
    return False

def get_video_title_facebook(url, browser=None):  # vẫn giữ tham số browser để tương thích code cũ
    """
    Lấy tiêu đề video Facebook bằng yt_dlp mà không cần dùng trình duyệt Selenium.
    """
    try:
        print(f"🔍 Đang xử lý: {url}")
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('description', 'Video không có tiêu đề')
            print(f"🎬 Tiêu đề gốc: {title}")

            # Làm sạch tiêu đề
            title_cleaned = title

            # Xóa từ đầu đến "views"
            title_cleaned = re.sub(r'^.*?views', '', title_cleaned, flags=re.IGNORECASE)

            # Xóa tiếp từ đầu đến "reaction" hoặc "reactions"
            title_cleaned = re.sub(r'^.*?reactions?', '', title_cleaned, flags=re.IGNORECASE)

            # Xóa phần từ dấu # trở đi
            #title_cleaned = re.sub(r'#.*$', '', title_cleaned)

            # Xóa ký tự không hợp lệ trong tên file
            title = re.sub(r'[\\/*?:"<>|]', '', title_cleaned).strip()

            print(f"✅ Tiêu đề đã làm sạch: {title}")
            return title

    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề bằng yt_dlp: {e}")
        return "Không thể lấy tiêu đề"
    
def get_video_title_tiktok(url, browser):
    """Lấy tiêu đề video bằng danh sách XPath."""
    try:
        browser.execute_script("window.open('about:blank', '_blank');")
        browser.switch_to.window(browser.window_handles[-1])
        browser.get(url)
        wait = WebDriverWait(browser, 8)
        xpaths = [
            '/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/div[2]/div[1]/div/h1',
            '/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/div[2]/div[1]/div/div[2]',
            '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div/div[2]/div/div/div/div/div/div/div[2]/div[1]/div/div/div[2]/div/div/div[2]/span/div'
        ]
        #time.sleep(7000)
        for xpath in xpaths:
            try:
                title_element = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
                title = title_element.text.strip()
                print(f"✅ Tiêu đề video: {title}")
                browser.close()
                browser.switch_to.window(browser.window_handles[0])
                return title
            except:
                print(f"⚠️ Không tìm thấy tiêu đề với XPath: {xpath}: ")
                
        print("❌ Không thể lấy tiêu đề với cả hai XPath.")
        browser.close()
        browser.switch_to.window(browser.window_handles[0])
        return "Không thể lấy tiêu đề"
    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề: {e}")
        play_sound("error")
        return "Không thể lấy tiêu đề"

def get_facebook_video_url(video_url):
    """Lấy URL thực tế của video Facebook bằng yt-dlp"""
    try:
        ydl_opts = {"quiet": True, "format": "bestaudio/best"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info["url"]
    except Exception as e:
        print(f"❌ Lỗi khi lấy video URL: {e}")
        play_sound("error")
        return None
    
def download_video(video_url, output_path):
    """Tải video về thư mục output_video"""
    try:
        ydl_opts = {"quiet": True, "outtmpl": output_path}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print("✅ Video đã được tải xuống thành công.")
        return output_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
        play_sound("error")
        return None

def download_videoTIKTOK(video_url, output_path):
    """Tải video TikTok bằng cookies từ Firefox (đăng nhập sẵn)"""
    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
        "cookiesfrombrowser": ("firefox",),  # Lấy cookie từ Firefox
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print(f"✅ Video đã tải thành công: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
        play_sound("error")
        return None
 
def extract_audio(video_path, output_wav):
    """Trích xuất âm thanh từ video"""
    command = [FFMPEG_PATH, "-i", video_path, "-ac", "1", "-ar", "16000", "-y", output_wav, "-vn"]
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print(f"✅ Âm thanh đã trích xuất thành công: {output_wav}")
        return output_wav
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi trích xuất âm thanh: {e}")
        play_sound("error")
        return None
    
def extract_audioTIKTOK(video_path, audio_path):
    """Trích xuất âm thanh từ video"""
    command = [FFMPEG_PATH, "-i", video_path, "-ac", "1", "-ar", "16000", "-y", audio_path, "-vn"]
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print(f"✅ Âm thanh đã trích xuất thành công: {audio_path}")
        return audio_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi trích xuất âm thanh: {e}")
        play_sound("error")
        return None

def split_audio(audio_path, chunk_length_ms=180000, max_chunks=None):
    """Chia file audio thành các đoạn nhỏ; giới hạn số đoạn nếu max_chunks được đặt."""
    try:
        audio = AudioSegment.from_file(audio_path)
        chunks = []
        for idx, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
            if max_chunks is not None and idx >= max_chunks:
                break
            end_ms = start_ms + chunk_length_ms
            chunk = audio[start_ms:end_ms]
            chunk_path = f"{audio_path}_chunk_{idx}.wav"
            chunk.export(chunk_path, format="wav")
            chunks.append(chunk_path)
        return chunks
    except Exception as e:
        print(f"❌ Lỗi khi chia nhỏ file âm thanh: {e}")
        play_sound("error")
        return []

def get_audio_duration(audio_path):
    """Lấy thời lượng của file audio (đơn vị giây)."""
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000  # Chuyển từ mili-giây sang giây
    except Exception as e:
        print(f"❌ Lỗi khi lấy thời lượng file audio: {e}")
        play_sound("error")
        return None

def detect_repetition(transcript):
    if not transcript:
        return False
    
    # ✅ Điều kiện đặc biệt: chứa từ khoá quảng bá spam
    SPAM_KEYWORDS = [
        "Hãy subscribe cho kênh Ghiền Mì Gõ để",
        "hãy subscribe cho kênh ghiền mì gõ để",
        "kênh Ghiền Mì Gõ"
    ]

    for spam in SPAM_KEYWORDS:
        if spam.lower() in transcript.lower():
            print(f"⚠️ Phát hiện nội dung spam hoặc lặp dạng quảng bá: '{spam}'")
            play_sound("warning")
            return True

    words = transcript.split()
    sentences = re.split(r'[\n.!?]', transcript)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 🔹 Phát hiện câu lặp liên tiếp
    repeat_threshold = 3  # Nếu một câu giống nhau lặp liên tiếp 3 lần → lỗi
    repeat_count = 1
    last_sentence = None

    for sentence in sentences:
        if sentence == last_sentence:
            repeat_count += 1
        else:
            repeat_count = 1
        last_sentence = sentence

        if repeat_count >= repeat_threshold:
            print(f"⚠️ Phát hiện câu lặp liên tiếp {repeat_count} lần: {sentence}")
            play_sound("warning")
            return False

    # 🔹 Giữ lại kiểm tra tổng thể
    sentence_counts = Counter(sentences)
    repeated_sentences = sum(1 for count in sentence_counts.values() if count > 2)
    if len(sentences) > 0 and (repeated_sentences / len(sentences)) > 0.1:
        print("⚠️ Phát hiện lỗi: Quá nhiều câu bị lặp lại!")
        play_sound("warning")
        return False

    return False

def transcribe_whisper(audio_path, use_chunks=False, max_chunks=None):
    """Nhận diện giọng nói bằng Whisper; hỗ trợ chia nhỏ và chỉ lấy max_chunks đoạn đầu."""

    global model, model2

    print("📝 Đang kiểm tra thời lượng file âm thanh...")

    duration = get_audio_duration(audio_path)
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None

    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    if not use_chunks and duration > 900:  # 15 phút
        print("❌ File audio dài hơn 15 phút, không thể nhận diện.")
        return None

    # Xóa model2 khi quay lại medium (an toàn hơn: set None + giải phóng VRAM)
    if 'model2' in globals() and globals().get('model2') is not None:
        print("🗑️ Đang xóa model large-v3 khỏi bộ nhớ GPU để quay lại medium...")
        try:
            globals()['model2'] = None
        except Exception as e:
            print(f"⚠️ Không thể xóa model2: {e}")
        try:
            if device == 'cuda':
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
        print("✅ Model large-v3 đã được xóa.")

    # Đảm bảo model medium có sẵn
    if 'model' not in globals() or model is None:
        print("🔄 Đang tải lại model medium...")
        model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
        print("✅ Model medium đã tải thành công.")

    def transcribe_one(path):
        global model
        result_local = model.transcribe(path, language="vi")
        text_local = result_local["text"]
        if detect_repetition(text_local):
            print("🔄 Phát hiện lỗi lặp từ, chuyển sang model 'large-v3'...")
            MODEL_NAME2 = "large-v3"
            if 'model2' not in globals() or model2 is None:
                print("⏳ Đang tải model large-v3 (lần đầu tiên sẽ mất 5-10 phút, vui lòng chờ...)...")
                print("🗑️ Giải phóng model medium để tiết kiệm VRAM...")
                del model  # Xóa model medium ngay
                model = None
                model2 = None

                torch.cuda.empty_cache()
                gc.collect()
                try:
                    model2 = whisper.load_model(MODEL_NAME2, download_root=WHISPER_MODEL_PATH).to(device)
                    print("✅ Model large-v3 đã tải thành công!")
                except Exception as e:
                    print(f"❌ Lỗi khi tải model large-v3: {e}")
                    print("⚠️ Quay lại model medium...")
                    model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
                    return text_local.strip()
            print("🔄 Đang nhận diện lại với model large-v3...")
            text_local = model2.transcribe(path, language="vi")["text"]
            torch.cuda.empty_cache()
            gc.collect()
        return text_local.strip()

    if use_chunks:
        max_take = max_chunks if (max_chunks and max_chunks > 0) else DEFAULT_MAX_CHUNKS
        chunk_paths = split_audio(audio_path, chunk_length_ms=CHUNK_LENGTH_MS, max_chunks=max_take)
        full_text_parts = []
        for idx, chunk_path in enumerate(chunk_paths, start=1):
            print(f"🧩 Đang xử lý đoạn {idx}/{len(chunk_paths)}: {chunk_path}")
            try:
                text_chunk = transcribe_one(chunk_path)
                full_text_parts.append(text_chunk)
            except Exception as e:
                print(f"❌ Lỗi khi xử lý đoạn {idx}: {e}")
            finally:
                # Xóa file chunk ngay để tiết kiệm disk space
                try:
                    if os.path.exists(chunk_path):
                        os.remove(chunk_path)
                        print(f"🗑️ Đã xóa chunk: {chunk_path}")
                except Exception as e:
                    print(f"⚠️ Không thể xóa {chunk_path}: {e}")
                # Giải phóng bộ nhớ sau mỗi chunk
                gc.collect()
                if device == "cuda":
                    torch.cuda.empty_cache()
        return " ".join(full_text_parts).strip()

    # Không chia nhỏ
    print("📝 Đang nhận diện giọng nói bằng Whisper ...")
    transcript = transcribe_one(audio_path)
    
    # Giải phóng bộ nhớ ngay sau khi transcribe xong
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    
    return transcript


def send_to_chatgpt(driver, text, mode="clean"):
    """Gửi nội dung đến ChatGPT.

    mode="clean": chỉnh sửa transcript.
    mode="title": gợi ý đặt tên video.
    mode="raw": gửi nguyên văn text (không tự thêm hướng dẫn).
    """
    try:
        # Kiểm tra driver có hợp lệ không
        if driver is None:
            print("❌ Lỗi: Driver là None, không thể gửi đến ChatGPT.")
            return None
        
        # Kiểm tra kết nối driver
        try:
            driver.current_url
        except Exception as e:
            print(f"❌ Lỗi: Firefox đã bị đóng hoặc không kết nối được - {e}")
            print("💡 Hãy nhấn nút 'Khởi động lại Firefox' trước khi tiếp tục xử lý.")
            return None
        
        if mode == "raw":
            prompt = text
        elif mode == "title":
            prompt = f"đặt tiêu đề cho video có nội dung là:\n\n{text}"
        else:
            prompt = (
                "không áp dụng yêu cầu trước đó. chỉ viết nội dung đã chỉnh sửa, không ghi phần thông báo như “Đã sửa” hay mô tả gì thêm, "
                "viết thành 1 đoạn không thêm icon, Sửa lỗi chính tả, kiểm tra câu văn có nghĩa, thêm dấu câu nếu cần, nhưng giữ nguyên nội dung gốc, "
                "không rút gọn hay thay đổi ý nghĩa, phù hợp với mô hình TTS, thay Bác sĩ x thành bác sĩ Hội\n\n" + text
            )

        # Tìm ô nhập liệu của ChatGPT
        try:
            textarea = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
            )
        except Exception as e:
            print(f"❌ Lỗi: Không tìm thấy ô nhập câu hỏi - {e}")
            print("💡 Kiểm tra xem ChatGPT có mở bình thường không, hoặc hãy khởi động lại Firefox.")
            return None

        # Đếm số tin nhắn trước khi gửi yêu cầu
        initial_messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        initial_count = len(initial_messages)

        # Gửi nội dung
        textarea.clear()
        textarea.send_keys(prompt)
        textarea.send_keys("\ue007")  # Nhấn Enter để gửi

        # **Cấu hình thời gian chờ**
        max_wait_time = 180  # 3 phút là quá lâu
        check_interval = 5  # ⏳ Kiểm tra mỗi 5 giây
        stable_time = 30  # ⏳ Chờ 30 giây để kiểm tra nội dung có thay đổi không
        stop_button_xpath = "//button[@data-testid='stop-button']"  # Kiểm tra phản hồi của ChatGPT

        print("⌛ Đang chờ phản hồi từ ChatGPT (tối đa 3 phút)...")

        start_time = time.time()
        chatgpt_started_typing = False

        # **Bước 1: Chờ ChatGPT bắt đầu phản hồi, tối đa 3 phút**
        while time.time() - start_time < max_wait_time:
            stop_button = driver.find_elements(By.XPATH, stop_button_xpath)
            if stop_button:  # Nếu ChatGPT bắt đầu gõ, thoát vòng lặp ngay
                print("✅ ChatGPT bắt đầu phản hồi! Chuyển sang bước tiếp theo.")
                chatgpt_started_typing = True
                break
            time.sleep(check_interval)
            
        # Nếu sau 3 phút ChatGPT vẫn chưa phản hồi, bỏ qua video này
        if not chatgpt_started_typing:
            print("❌ ChatGPT không phản hồi sau 3 phút, bỏ qua video này.")
            return None

        # **Bước 2: Chờ đến khi ChatGPT gõ xong (`stop-button` biến mất)**
        while True:
            time.sleep(check_interval)
            stop_button = driver.find_elements(By.XPATH, stop_button_xpath)

            if not stop_button:  # Nếu ChatGPT dừng gõ
                print("✅ ChatGPT đã dừng gõ. Lấy ngay nội dung hiện tại...")
                break

        # **Bước 3: Kiểm tra nội dung có bị rỗng hay không**
        retry_attempts = 3  # Số lần thử lại tối đa nếu nội dung trống
        attempt = 0

        while attempt < retry_attempts:
            # Lấy nội dung hiện tại
            messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
            new_messages = messages[initial_count:]  # Chỉ lấy tin nhắn mới
            final_content = "\n".join([msg.text.strip() for msg in new_messages])

            if final_content.strip():  # Nếu nội dung không trống, trả về ngay
                print("✅ Đã nhận được nội dung từ GPT.")
                break  # Dừng vòng lặp ngay lập tức
            else:
                attempt += 1
                print(f"⚠ Cảnh báo: Nội dung trống! Chờ thêm 30 giây để thử lại lần {attempt}/{retry_attempts}...")
                time.sleep(30)  # Chờ thêm 30 giây trước khi thử lại

        print("📩 ChatGPT ĐÃ TRẢ LỜI XONG LẤY NỘI DUNG:")
        #print(final_content)

        # **Bước 4: Kiểm tra nội dung có thay đổi trong 30 giây không**
        stable_counter = 0
        last_content = final_content  # Nội dung vừa lấy ngay sau khi ChatGPT dừng gõ

        while stable_counter < stable_time:
            time.sleep(check_interval)

            # Lấy nội dung mới
            messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
            new_messages = messages[initial_count:]  # Chỉ lấy tin nhắn mới
            current_content = "\n".join([msg.text.strip() for msg in new_messages])

            if current_content == last_content:
                stable_counter += check_interval
                print(f"⚖ Nội dung không thay đổi, chờ thêm {stable_time - stable_counter}s để xác nhận...")
            else:
                stable_counter = 0  # Reset nếu nội dung thay đổi
                print("🔄 Nội dung thay đổi, cập nhật lại!")
                last_content = current_content  # Cập nhật nội dung mới nhất
                final_content = current_content

        # **Bước 5: Trả về nội dung cuối cùng sau khi ổn định**
        if final_content:
            print("✅ Nội dung cuối cùng đã ổn định, trả về kết quả.")
            return final_content
        else:
            print("❌ Lỗi: Không lấy được phản hồi từ ChatGPT.")
            return None

    except Exception as e:
        print(f"❌ Lỗi khi gửi câu hỏi: {e}")
        return None
    
def is_tiktok_link(url):
    """Kiểm tra xem một URL có phải là liên kết TikTok hay không"""
    tiktok_pattern = re.compile(r"tiktok", re.IGNORECASE)
    return bool(tiktok_pattern.search(url))

def save_refined_text(refined_text, video_number):
    refined_text_filename = f"refined_text_{video_number}.txt"
    refined_text_path = os.path.join(OUTPUT_VIDEO_DIR, refined_text_filename)

    with open(refined_text_path, "w", encoding="utf-8") as f:
        if refined_text is None:
            print("⚠ Không có refined_text, bỏ qua xử lý văn bản.")
            refined_text = ""
        formatted_refined_text = refined_text.replace(". ", ".\n")  # Xuống dòng sau mỗi câu
        f.write(formatted_refined_text)

def format_transcript_by_spaces(transcript, spaces_per_line=15):
    """Định dạng transcript để xuống dòng sau mỗi 15 dấu cách."""
    space_count = 0
    formatted_text = ""
    
    for char in transcript:
        formatted_text += char
        if char == " ":
            space_count += 1
        if space_count == spaces_per_line:
            formatted_text += "\n"
            space_count = 0  # Reset bộ đếm

    return formatted_text
        
def process_video(index, link, doc, driver, browser):
    video_number, link = clean_link(link, index)
    # Loại bỏ dấu nháy nếu người dùng copy nguyên chuỗi có ""
    link = link.strip().strip('"').strip("'")
    video_number = video_number if video_number is not None else index
    print(f"\n🎥 Đang xử lý video {video_number}: {link}")
    # Nhận diện loại nguồn: file local hay link online
    is_local_file = os.path.exists(link) and os.path.isfile(link)

    if is_local_file:
        print(f"📁 Phát hiện file local: {link}")
        title = os.path.splitext(os.path.basename(link))[0]
        video_path = link
        audio_filename = f"audio_{video_number}.wav"
        audio_path = os.path.join(OUTPUT_VIDEO_DIR, audio_filename)
    else:
        checklinktiktok = 1 if is_tiktok_link(link) else 0
        print(f"{link} -> TikTok: {checklinktiktok}")

        # Lấy tiêu đề video online
        if checklinktiktok == 0:
            title = get_video_title_facebook(link, browser)
        else:
            title = get_video_title_facebook(link, browser)  # có thể thay bằng get_video_title_tiktok nếu cần
        
        # Kiểm tra tiêu đề có chứa từ khóa cấm không
        if CHECK_TITLE_BLACKLIST and check_title_blacklist(title):
            print(f"⛔ Bỏ qua video {video_number} do tiêu đề không phù hợp.")
            return  # Thoát hàm, không xử lý tiếp
        
        # Tiếp tục xử lý nếu tiêu đề hợp lệ
        if checklinktiktok == 0:
            fb_video_url = get_facebook_video_url(link)
            if not fb_video_url:
                return None
        
        video_filename = f"video_{video_number}.mp4"
        video_path = os.path.join(OUTPUT_VIDEO_DIR, video_filename)

        if checklinktiktok == 0:
            print(f"\n🎥 ĐANG TẢI VIDEO LINK FACEBOOK")
            if not download_video(fb_video_url, video_path):
                return None
        
        if checklinktiktok == 1:
            print(f"\n🎥 ĐANG TẢI VIDEO LINK TIKTOK")
            if not download_videoTIKTOK(link, video_path):
                return None
        audio_filename = f"audio_{video_number}.wav"
        audio_path = os.path.join(OUTPUT_VIDEO_DIR, audio_filename)

    if os.path.exists(video_path):
        print(f"🎥 Video đã sẵn sàng: {video_path}")
    else:
        print(f"❌ Lỗi! Video chưa được sẵn sàng tại {video_path}")
        return None
    if not extract_audio(video_path, audio_path):
        return None
    
    if os.path.exists(audio_path):
        print(f"🎵 Âm thanh đã lưu tại: {audio_path}")
    else:
        print(f"❌ Lỗi! Âm thanh chưa được lưu vào {audio_path}")
        return None

    transcript = transcribe_whisper(audio_path, use_chunks=USE_TITLE_MODE, max_chunks=MAX_CHUNKS_RUNTIME)
    # Lưu transcript vào file TXT theo số thứ tự video
    transcript_filename = f"transcript_{video_number}.txt"
    transcript_path = os.path.join(OUTPUT_VIDEO_DIR, transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as f:
        if transcript is None:
            print("⚠ Không có transcript, bỏ qua xử lý văn bản.")
            transcript = ""
            #return None  # Ngăn lỗi tiếp tục xảy ra
        #formatted_transcript = transcript.replace(". ", ".\n")  # Xuống dòng sau mỗi câu
        formatted_transcript = format_transcript_by_spaces(transcript, spaces_per_line=25)
        f.write(formatted_transcript)

    print(f"💾 Đã lưu transcript vào: {transcript_path}")

    # Xóa file audio ngay để tiết kiệm disk space
    try:
        if os.path.exists(audio_path):
            os.remove(audio_path)
            print(f"🗑️ Đã xóa file âm thanh: {audio_path}")
    except Exception as e:
        print(f"⚠️ Không thể xóa audio: {e}")
    
    # Xóa file video nếu là file local thì không xóa
    if not is_local_file and os.path.exists(video_path):
        try:
            os.remove(video_path)
            print(f"🗑️ Đã xóa file video: {video_path}")
        except Exception as e:
            print(f"⚠️ Không thể xóa video: {e}")
    
    # Giải phóng garbage collection
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    # Khi dùng title_mode: chỉ lưu transcript, không gửi GPT ngay
    if USE_TITLE_MODE:
        print(f"📁 Chế độ chia nhỏ: sẽ xử lý GPT sau khi nhận diện xong tất cả...")
        refined_text = None
        title_suggestion = None
    elif transcript:  # Kiểm tra nếu transcript không rỗng
        print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
        refined_text = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
        save_refined_text(refined_text, video_number)
        title_suggestion = None
    else:
        print(f"⚠️ Video {video_number} không có transcript, bỏ qua gửi đến ChatGPT.")
        refined_text = "Dây là video quá dài để lấy nội dung."
        title_suggestion = None

    # print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
    # c = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
    # Lưu kết quả ngay lập tức vào file Word
    #doc.add_paragraph(f"{video_number}. {link}").runs[0].font.color.rgb = RGBColor(255, 0, 0)
    para = doc.add_paragraph()
    run = para.add_run(f"{video_number}. {link}")
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.size = Pt(11)  # tùy chỉnh
    doc.add_paragraph(f"Tiêu đề: {title}")
    if title_suggestion:
        doc.add_paragraph(f"Tiêu đề gợi ý: {title_suggestion}")

    if transcript:  # Chỉ thêm nội dung nếu có transcript
        if refined_text:
            doc.add_paragraph(f"Nội dung:\n{refined_text}")
        elif not USE_TITLE_MODE or (USE_TITLE_MODE and TITLE_MODE_SUBMODE == "content_only"):
            # Nếu chọn chế độ chỉ lưu nội dung, ghi transcript trực tiếp vào Word và bỏ qua GPT
            doc.add_paragraph(f"Nội dung:\n{transcript}")
    else:
        doc.add_paragraph(f"Nội dung: (Video quá dài để lấy nội dung)")

    doc.add_paragraph("=" * 40)

    try:
        doc.save(OUTPUT_WORD_FILE)
        print("💾 Đã lưu kết quả thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file Word: {e}")
    finally:
        print("✅ Hoàn thành xử lý video, tiếp tục với video tiếp theo!")

def process_videos():
    global USE_TITLE_MODE, global_driver, TITLE_MODE_SUBMODE
    global model, model2, torch  # ✅ thêm model2 (và torch nếu dùng torch.cuda.empty_cache)

    doc = Document()
    doc.save(OUTPUT_WORD_FILE)

    # driver toàn cục
    driver = global_driver

    need_gpt = (not USE_TITLE_MODE) or (USE_TITLE_MODE and TITLE_MODE_SUBMODE != "content_only")

    if need_gpt:
        # 1) nếu thread nền đang mở firefox thì chờ nó xong
        with DRIVER_LOCK:
            in_progress = FIREFOX_INIT_IN_PROGRESS

        if (driver is None or not is_driver_alive(driver)) and in_progress:
            print("⏳ Firefox đang khởi động (thread nền). Đang chờ...")
            FIREFOX_INIT_EVENT.wait(timeout=90)  # chờ tối đa 90s
            driver = global_driver

        # 2) nếu vẫn chưa có thì mới tự mở (fallback)
        if driver is None or not is_driver_alive(driver):
            print("🌐 Chưa có Firefox/driver. Tự mở Firefox để dùng GPT...")
            driver = init_firefox()
            global_driver = driver


    
    with open(LINKS_FILE, "r", encoding="utf-8") as file:
        links = [line.strip() for line in file.readlines() if line.strip()]
    # Giới hạn chỉ lấy 50 link đầu tiên
    #inks = links[0:4]
    for idx, raw_line in enumerate(links, start=1):
        video_number, link = clean_link(raw_line)  # lấy đúng số
        print(f"🔄 Đang xử lý video {idx}/{len(links)} (ID={video_number})...")

        if USE_TITLE_MODE:
            process_video(idx, raw_line, doc, None, None)  # vẫn truyền raw_line cũng được
            transcript_file = os.path.join(OUTPUT_VIDEO_DIR, f"transcript_{video_number}.txt")
        else:
            process_video(idx, raw_line, doc, driver, driver)
            transcript_file = None

        if USE_TITLE_MODE and transcript_file and os.path.exists(transcript_file):
            with open(transcript_file, "r", encoding="utf-8") as f:
                current_transcript = f.read().strip()
                
                if current_transcript:
                    # Nếu chọn chế độ chỉ lấy nội dung, bỏ qua toàn bộ bước gửi GPT
                    if TITLE_MODE_SUBMODE == "content_only":
                        print(f"\n📝 Chế độ Nội dung: đã lưu transcript cho video {idx}, bỏ qua gửi GPT.")
                        # File Word đã được ghi transcript ngay khi xử lý video
                        try:
                            os.remove(transcript_file)
                            print(f"🗑️ Đã xóa file transcript: {transcript_file}")
                        except Exception as e:
                            print(f"⚠️ Không thể xóa transcript: {e}")
                        continue

                    print(f"\n📝 Đang xử lý GPT cho video {idx}...")
                    print("🔄 Sử dụng Firefox đã được mở từ khi khởi động...")
                    
                    # Yêu cầu 1: 5 tiêu đề cho kênh Haio6VietSub
                    print(f"\n🎯 Yêu cầu 1: Gợi ý 5 tiêu đề cho video {idx}...")
                    title_prompt = (
                        "Dựa trên nội dung video sau, hãy đề xuất 5 tiêu đề hấp dẫn, phù hợp cho kênh Haio6VietSub. "
                        "Mỗi tiêu đề trên một dòng, không ghi số thứ tự:\n\n" + current_transcript
                    )
                    titles_result = send_to_chatgpt(driver, title_prompt, mode="raw")
                    if titles_result:
                        para = doc.add_paragraph()
                        para_run = para.add_run(f"🎯 5 Tiêu đề gợi ý cho video {idx}:")
                        para_run.bold = True
                        doc.add_paragraph(titles_result)

                    # Nếu chỉ cần tiêu đề thì dừng ở yêu cầu 1
                    if TITLE_MODE_SUBMODE == "title_only":
                        doc.save(OUTPUT_WORD_FILE)
                        # Xóa file transcript để tiết kiệm disk
                        try:
                            os.remove(transcript_file)
                            print(f"🗑️ Đã xóa file transcript: {transcript_file}")
                        except Exception as e:
                            print(f"⚠️ Không thể xóa transcript: {e}")
                        print(f"✅ Video {idx}: Chế độ Tiêu đề - đã xong sau Yêu cầu 1.")
                        continue
                    
                    # Yêu cầu 2: Mô tả + hashtag
                    print(f"\n📝 Yêu cầu 2: Viết mô tả video {idx} và hashtag...")
                    desc_prompt = (
                        "Viết mô tả video (1-2 đoạn ngắn gọn) và thêm 5-10 hashtag phù hợp cho kênh Haio6VietSub, "
                        "dựa trên nội dung:\n\n" + current_transcript
                    )
                    desc_result = send_to_chatgpt(driver, desc_prompt, mode="raw")
                    if desc_result:
                        para = doc.add_paragraph()
                        para_run = para.add_run(f"📝 Mô tả + Hashtag cho video {idx}:")
                        para_run.bold = True
                        doc.add_paragraph(desc_result)
                    
                    # Yêu cầu 3: Tag (tối đa 500 kí tự)
                    print(f"\n🏷️ Yêu cầu 3: Viết thẻ tag cho video {idx} (tối đa 500 kí tự)...")
                    tag_prompt = (
                        "Viết một danh sách các thẻ tag mô tả video này, tối đa 500 kí tự, phù hợp cho kênh Haio6VietSub, "
                        "ngăn cách bằng dấu phẩy. Dựa trên nội dung:\n\n" + current_transcript
                    )
                    tag_result = send_to_chatgpt(driver, tag_prompt, mode="raw")
                    if tag_result:
                        para = doc.add_paragraph()
                        para_run = para.add_run(f"🏷️ Tags cho video {idx}:")
                        para_run.bold = True
                        doc.add_paragraph(tag_result)
                    
                    # Lưu sau mỗi video
                    doc.save(OUTPUT_WORD_FILE)
                    
                    # Xóa file transcript để tiết kiệm disk
                    try:
                        os.remove(transcript_file)
                        print(f"🗑️ Đã xóa file transcript: {transcript_file}")
                    except Exception as e:
                        print(f"⚠️ Không thể xóa transcript: {e}")
                    
                    print(f"✅ Đã lưu kết quả video {idx} vào {OUTPUT_WORD_FILE}")
                    
                    # Giải phóng bộ nhớ sau mỗi video
                    gc.collect()
                    if device == "cuda":
                        torch.cuda.empty_cache()
    
    # ================= cuối hàm =================
    print("\n🧹 Giải phóng bộ nhớ...")

    if model is not None:
        del model
        model = None

    if model2 is not None:          # ✅ không dùng 'model2' in globals()
        del model2
        model2 = None

    if device == "cuda":
        torch.cuda.empty_cache()
    gc.collect()

    print("✅ Bộ nhớ đã được giải phóng.")
    
    print("🎉 Hoàn thành tất cả video! Kết quả đã lưu vào final_result.docx")
    play_sound("success")  # Thông báo âm thanh khi hoàn thành

# ================= GUI =================
class GetTextApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GetTextFromLink - GUI")
        self.view_var = tk.StringVar(value="log")  # log / links / result
        W, H = 1200, 650
        self.root.geometry(f"{W}x{H}")
        self.center_window(W, H)
        self.root.minsize(W, H)

        # ===== Variables =====
        self.selected_model = tk.StringVar(value=MODEL_NAME)

        # View: mặc định hiện Nhật ký
        self.show_log_var = tk.BooleanVar(value=True)
        self.show_links_var = tk.BooleanVar(value=False)
        self.show_result_var = tk.BooleanVar(value=False)  # Nội dung Word

        # Title mode
        self.title_mode_var = tk.BooleanVar(value=False)
        self.title_only_var = tk.BooleanVar(value=False)
        self.desc_mode_var = tk.BooleanVar(value=True)
        self.content_mode_var = tk.BooleanVar(value=False)
        self.max_chunks_var = tk.IntVar(value=DEFAULT_MAX_CHUNKS)

        self.build_ui()
        self.load_links()

    def center_window(self, w: int = 1200, h: int = 650):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ================= UI =================
    def build_ui(self):
        # clear toàn bộ UI cũ (tránh dư nút)
        for child in self.root.winfo_children():
            child.destroy()

        # Root layout: 2 hàng (top / main)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)

        # ================= TOP: Cấu hình (trái) + Thao tác (phải) =================
        top = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        # --- Cấu hình (TRÁI) ---
        info_frame = ttk.LabelFrame(top, text="Cấu hình", padding=10)
        info_frame.grid(row=0, column=0, sticky="ew")
        info_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(info_frame, text=f"Thư mục lưu video: {OUTPUT_VIDEO_DIR}").grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Label(info_frame, text=f"File Word kết quả: {OUTPUT_WORD_FILE}").grid(row=1, column=0, sticky="w", pady=(0, 2))
        ttk.Label(info_frame, text=f"Thiết bị: {'GPU' if device == 'cuda' else 'CPU'}").grid(row=2, column=0, sticky="w", pady=(0, 6))

        model_row = ttk.Frame(info_frame)
        model_row.grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Label(model_row, text="Model Whisper:").pack(side="left", padx=(0, 8))
        ttk.Combobox(
            model_row,
            textvariable=self.selected_model,
            values=["tiny", "base", "small", "medium", "large-v3"],
            state="readonly",
            width=12,
        ).pack(side="left")

        title_row = ttk.Frame(info_frame)
        title_row.grid(row=4, column=0, sticky="w", pady=(0, 2))
        self.title_checkbox = ttk.Checkbutton(
            title_row,
            text="Chia nhỏ audio + Tiêu đề/Mô tả/Tag",
            variable=self.title_mode_var,
            command=self.on_title_toggle,
        )
        self.title_checkbox.pack(side="left")

        ttk.Label(title_row, text="  Số đoạn đầu nhận diện:").pack(side="left", padx=(10, 6))
        self.max_chunks_spin = ttk.Spinbox(
            title_row, from_=1, to=50, width=5, textvariable=self.max_chunks_var, state="disabled"
        )
        self.max_chunks_spin.pack(side="left")

        submode_row = ttk.Frame(info_frame)
        submode_row.grid(row=5, column=0, sticky="w", padx=(18, 0), pady=(2, 0))
        self.sub_title_cb = ttk.Checkbutton(
            submode_row, text="Tiêu đề", variable=self.title_only_var, command=self.on_submode_title, state="disabled"
        )
        self.sub_title_cb.pack(side="left", padx=(0, 12))
        self.sub_desc_cb = ttk.Checkbutton(
            submode_row, text="Mô tả", variable=self.desc_mode_var, command=self.on_submode_desc, state="disabled"
        )
        self.sub_desc_cb.pack(side="left", padx=(0, 12))
        self.sub_content_cb = ttk.Checkbutton(
            submode_row, text="Nội dung", variable=self.content_mode_var, command=self.on_submode_content, state="disabled"
        )
        self.sub_content_cb.pack(side="left")

        # --- Thao tác (PHẢI) ---
        action_frame = ttk.LabelFrame(top, text="Thao tác", padding=10)
        action_frame.grid(row=0, column=1, sticky="ne", padx=(10, 0))
        action_frame.grid_columnconfigure(0, weight=1)
        action_frame.grid_columnconfigure(1, weight=1)

        self.start_btn = ttk.Button(action_frame, text="▶ Bắt đầu xử lý", command=self.start_process, width=22)
        self.start_btn.grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="ew")

        self.restart_firefox_btn = ttk.Button(action_frame, text="♻ Khởi động lại Firefox", command=self.restart_firefox_async, width=22)
        self.restart_firefox_btn.grid(row=0, column=1, pady=(0, 8), sticky="ew")

        self.save_btn = ttk.Button(action_frame, text="💾 Lưu danh sách", command=self.save_links, width=22)
        self.save_btn.grid(row=1, column=0, padx=(0, 8), sticky="ew")

        self.reload_btn = ttk.Button(action_frame, text="🔄 Tải lại danh sách", command=self.load_links, width=22)
        self.reload_btn.grid(row=1, column=1, sticky="ew")

        # ================= MAIN =================
        main = ttk.LabelFrame(self.root, text="Danh sách", padding=10)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # ====== Notebook (3 tab) ======
        self.nb = ttk.Notebook(main)
        self.nb.grid(row=1, column=0, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        tab_log = ttk.Frame(self.nb)
        tab_links = ttk.Frame(self.nb)
        tab_result = ttk.Frame(self.nb)

        self.nb.add(tab_log, text="Nhật ký")
        self.nb.add(tab_links, text="Danh sách link")
        self.nb.add(tab_result, text="Nội dung Word")

        # mỗi tab dùng grid full
        for tab in (tab_log, tab_links, tab_result):
            tab.grid_rowconfigure(0, weight=1)
            tab.grid_columnconfigure(0, weight=1)

        # Textboxes
        self.log_text = scrolledtext.ScrolledText(tab_log, wrap=tk.WORD)
        self.links_text = scrolledtext.ScrolledText(tab_links, wrap=tk.WORD)
        self.result_text = scrolledtext.ScrolledText(tab_result, wrap=tk.WORD)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.links_text.grid(row=0, column=0, sticky="nsew")
        self.result_text.grid(row=0, column=0, sticky="nsew")

        # mặc định tab Nhật ký
        self.nb.select(tab_log)

        # Khi đổi tab thì load đúng nội dung
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab_changed)
    
    def on_tab_changed(self, event=None):
        tab_text = self.nb.tab(self.nb.select(), "text")

        if tab_text == "Danh sách link":
            self.links_text.config(state="normal")
            self.links_text.delete("1.0", "end")
            self.load_links()
            self.links_text.see("1.0")

        elif tab_text == "Nội dung Word":
            self.result_text.config(state="normal")
            self.result_text.delete("1.0", "end")
            self.load_result_docx()
            self.result_text.see("1.0")

        else:
            # Nhật ký: không clear để giữ lịch sử
            self.log_text.see(tk.END)

    # ================= File I/O =================
    def load_links(self):
        """Tải danh sách link từ file. Ưu tiên path bạn đưa: D:\\Python\\GetLinktoText\\linkgettoText.txt"""
        candidates = [
            r"D:\Python\GetLinktoText\linkgettoText.txt",
            LINKS_FILE,
            os.path.abspath(LINKS_FILE),
        ]
        path = next((p for p in candidates if p and os.path.exists(p)), None)

        self.links_text.delete(1.0, tk.END)

        if not path:
            self.log(f"⚠️ Không tìm thấy file link (linkgettoText.txt).")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.links_text.insert(1.0, content)
            link_count = len([l for l in content.splitlines() if l.strip()])
            self.log(f"✅ Đã tải {link_count} link từ {path}")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải link: {e}")

    def save_links(self):
        try:
            content = self.links_text.get(1.0, tk.END).strip()
            with open(LINKS_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            link_count = len([l for l in content.splitlines() if l.strip()])
            self.log(f"💾 Đã lưu {link_count} link vào {os.path.abspath(LINKS_FILE)}")
        except Exception as e:
            self.log(f"❌ Lỗi khi lưu link: {e}")
            messagebox.showerror("Lỗi", f"Không thể lưu file: {e}")

    def load_result_docx(self):
        """
        Load nội dung từ file Word final_result.docx và đổ vào result_text.
        Ưu tiên đúng path bạn yêu cầu: D:\\Python\\GetLinktoText\\final_result.docx
        """
        candidates = [
            r"D:\Python\GetLinktoText\final_result.docx",
            OUTPUT_WORD_FILE,
            os.path.abspath(OUTPUT_WORD_FILE),
        ]
        docx_path = next((p for p in candidates if p and os.path.exists(p)), None)

        self.result_text.delete(1.0, tk.END)

        if not docx_path:
            self.log("⚠️ Không tìm thấy file Word kết quả (final_result.docx).")
            self.result_text.insert(1.0, "(Chưa có final_result.docx)")
            return

        try:
            doc = Document(docx_path)
            lines = []
            for p in doc.paragraphs:
                t = (p.text or "").rstrip()
                if t:
                    lines.append(t)

            content = "\n".join(lines)
            self.result_text.insert(1.0, content if content else "(File Word rỗng)")
            self.log(f"✅ Đã tải nội dung Word: {docx_path} ({len(lines)} dòng)")
        except Exception as e:
            self.log(f"❌ Lỗi khi đọc Word: {e}")
            self.result_text.insert(1.0, f"(Lỗi đọc Word: {e})")

    # ================= Title mode toggle =================
    def on_title_toggle(self):
        if self.title_mode_var.get():
            self.max_chunks_spin.configure(state="normal")
            self.sub_title_cb.configure(state="normal")
            self.sub_desc_cb.configure(state="normal")
            self.sub_content_cb.configure(state="normal")

            # đảm bảo ít nhất 1 mode được bật
            if not (self.title_only_var.get() or self.desc_mode_var.get() or self.content_mode_var.get()):
                self.desc_mode_var.set(True)
        else:
            self.max_chunks_spin.configure(state="disabled")
            self.sub_title_cb.configure(state="disabled")
            self.sub_desc_cb.configure(state="disabled")
            self.sub_content_cb.configure(state="disabled")

            self.title_only_var.set(False)
            self.desc_mode_var.set(True)
            self.content_mode_var.set(False)

    def on_submode_title(self):
        self.title_only_var.set(True)
        self.desc_mode_var.set(False)
        self.content_mode_var.set(False)

    def on_submode_desc(self):
        self.desc_mode_var.set(True)
        self.title_only_var.set(False)
        self.content_mode_var.set(False)

    def on_submode_content(self):
        self.content_mode_var.set(True)
        self.title_only_var.set(False)
        self.desc_mode_var.set(False)

    # ================= Firefox control =================
    def restart_firefox_async(self):
        self.restart_firefox_btn.config(state="disabled")
        threading.Thread(target=self.restart_firefox_thread, daemon=True).start()

    def restart_firefox_thread(self):
        try:
            ok = restart_firefox()
            self.log("✅ Firefox đã khởi động lại thành công!" if ok else "❌ Lỗi khi khởi động lại Firefox")
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")
        finally:
            self.root.after(0, lambda: self.restart_firefox_btn.config(state="normal"))

    # ================= Logging =================
    def log(self, message: str):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.root.after(0, _append)

    # ================= Run pipeline =================
    def start_process(self):
        self.save_links()
        # Reload links widget (in case file changed) and switch to Log tab so user sees progress
        try:
            self.load_links()
        except Exception:
            pass
        try:
            self.nb.select(0)
        except Exception:
            pass
        self.start_btn.config(state="disabled")
        threading.Thread(target=self.run_pipeline_thread, daemon=True).start()

    def run_pipeline_thread(self):
        global MODEL_NAME, model
        global USE_TITLE_MODE, MAX_CHUNKS_RUNTIME, TITLE_MODE_SUBMODE
        global device, whisper, torch

        try:
            import torch as _torch
            import whisper as _whisper
            torch = _torch
            whisper = _whisper
        except Exception as e:
            self.log(f"❌ Không import được torch/whisper: {e}")
            messagebox.showerror("Lỗi", f"Không import được torch/whisper: {e}")
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.log(f"✅ Whisper sẽ chạy trên {'GPU' if device=='cuda' else 'CPU'}")

        selected = self.selected_model.get()
        USE_TITLE_MODE = self.title_mode_var.get()

        if USE_TITLE_MODE:
            if self.title_only_var.get():
                TITLE_MODE_SUBMODE = "title_only"
            elif self.content_mode_var.get():
                TITLE_MODE_SUBMODE = "content_only"
            else:
                TITLE_MODE_SUBMODE = "full"

        try:
            MAX_CHUNKS_RUNTIME = int(self.max_chunks_var.get())
            if MAX_CHUNKS_RUNTIME <= 0:
                MAX_CHUNKS_RUNTIME = DEFAULT_MAX_CHUNKS
        except Exception:
            MAX_CHUNKS_RUNTIME = DEFAULT_MAX_CHUNKS

        # load / reload whisper model nếu cần
        try:
            if model is None or selected != MODEL_NAME:
                self.log(f"🔄 Đang tải model '{selected}'...")
                if model is not None:
                    del model
                    if device == "cuda":
                        torch.cuda.empty_cache()
                    gc.collect()

                MODEL_NAME = selected
                model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
                self.log(f"✅ Đã tải model '{MODEL_NAME}' thành công")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải model: {e}")
            play_sound("error")
            messagebox.showerror("Lỗi", f"Không thể tải model: {e}")
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            return

        import builtins
        original_print = builtins.print

        def gui_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            self.log(msg)
            return original_print(*args, **kwargs)

        builtins.print = gui_print
        try:
            self.log("=== BẮT ĐẦU XỬ LÝ ===")
            process_videos()
            self.log("=== HOÀN TẤT ===")
            play_sound("success")
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")
            play_sound("error")
            messagebox.showerror("Lỗi", str(e))
        finally:
            builtins.print = original_print
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            # Ensure the UI shows the log tab and scrolls to bottom so the user sees final messages
            try:
                self.root.after(0, lambda: self.nb.select(0))
                self.root.after(0, lambda: self.log_text.see(tk.END))
            except Exception:
                pass


def launch_gui():
    global global_driver
    
    def open_firefox_async():
        """Mở Firefox trong background thread (an toàn, không mở trùng)."""
        global global_driver, FIREFOX_INIT_IN_PROGRESS

        # Nếu đã có driver sống hoặc đang init thì thôi
        with DRIVER_LOCK:
            if is_driver_alive(global_driver):
                print("✅ Firefox đã sẵn sàng (đã có driver).")
                FIREFOX_INIT_EVENT.set()
                return
            if FIREFOX_INIT_IN_PROGRESS:
                print("⏳ Firefox đang được khởi tạo, không mở thêm.")
                return
            FIREFOX_INIT_IN_PROGRESS = True
            FIREFOX_INIT_EVENT.clear()

        try:
            print("🌐 Đang mở Firefox...")
            drv = init_firefox()
            with DRIVER_LOCK:
                global_driver = drv
            print("✅ Firefox đã sẵn sàng!")
        except Exception as e:
            print(f"❌ Lỗi mở Firefox: {e}")
        finally:
            with DRIVER_LOCK:
                FIREFOX_INIT_IN_PROGRESS = False
            FIREFOX_INIT_EVENT.set()

    
    # Mở Firefox trong background thread để không chặn GUI
    firefox_thread = threading.Thread(target=open_firefox_async, daemon=True)
    firefox_thread.start()
    
    # Tạo GUI ngay lập tức không cần chờ Firefox khởi động
    print("🎨 Đang khởi động giao diện...")
    root = tk.Tk()
    app = GetTextApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()

def retry(func, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)  # exponential backoff
