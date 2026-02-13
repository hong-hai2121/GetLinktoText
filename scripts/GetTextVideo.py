import os
from pyexpat import model
import yt_dlp
import whisper
import torch
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
import gc

# ================= Cấu hình =================
LINKS_FILE = "linkgettoText.txt"  # File chứa danh sách link video
OUTPUT_WORD_FILE = "final_result.docx"  # Xuất kết quả ra file Word
WHISPER_MODEL_PATH = "whisper_cache"  # Thư mục lưu mô hình Whisper
OUTPUT_VIDEO_DIR = "output_videos"  # Thư mục lưu video tải xuống
MODEL_NAME = "medium"  # Đặt đúng tên file mô hình đã có (large-v3,medium,small)
FFMPEG_PATH = shutil.which("ffmpeg")  # Kiểm tra ffmpeg


SHOW_TIMESTAMPS = False   # True = thêm [MM:SS] trước mỗi câu, False = bỏ, True = thêm

CHECK_TITLE_BLACKLIST = False  # Đổi thành False nếu không muốn kiểm tra tiêu đề True
BLACKLIST_KEYWORDS2 = [
    "da căng bóng","sáng da","da trẻ","da bóng","sạch da","da","nám",
    "nấm","n.ấm","n ấm","n .ấm"
    "nám", "n .ám","n ám","n.ám"
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

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"✅ Whisper sẽ chạy trên {'GPU' if device == 'cuda' else 'CPU'}")
#torch.cuda.set_per_process_memory_fraction(0.5, 0)
#if device == "cuda":
    #torch.cuda.set_per_process_memory_fraction(0.7, 0)  # Giới hạn PyTorch chỉ sử dụng tối đa 50% VRAM
    
# Tạo thư mục nếu chưa có
os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)

# ✅ Xóa nội dung cũ trong file Word khi bắt đầu một phiên mới
if os.path.exists(OUTPUT_WORD_FILE):
    doc = Document()
    doc.save(OUTPUT_WORD_FILE)
    print("🗑️ File Word đã được xóa nội dung cũ để bắt đầu phiên mới.")

# Kiểm tra mô hình Whisper đã có chưa
whisper_model_path = os.path.join(WHISPER_MODEL_PATH, f"{MODEL_NAME}.pt")
if os.path.exists(whisper_model_path):
    print(f"✅ Mô hình Whisper '{MODEL_NAME}' đã có, không cần tải lại.")
else:
    print(f"🔄 Tải mô hình Whisper '{MODEL_NAME}'...")
model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)

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
GECKODRIVER_PATH = r"D:\Python\GetLinktoText\geckodriver.exe"
FIREFOX_PROFILE_PATH = r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\wyo2tlat.GPT Chị Thảo" #C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\kt92li14.GPT_DEEPSEEK

def clean_link(line, counter=[0]):
    # Nhận dạng "1. <link>" hoặc "1 <link>"
    m = re.match(r'^\s*(\d+)[\.\s]+\s*(.+?)\s*$', line)
    if m:
        counter[0] = int(m.group(1))
        raw = m.group(2).strip()
    else:
        counter[0] += 1
        raw = line.strip()

    # Bóc ngoặc kép đơn/đôi ở hai đầu nếu có
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()

    return counter[0], raw

def normalize_local_path(p):
    # Thay \\\", bóc dư thừa, mở rộng ~, biến môi trường, và chuẩn hóa dấu \
    p = p.strip().strip('"').strip("'")
    p = os.path.expanduser(os.path.expandvars(p))
    return os.path.normpath(p)

def is_local_video(path):
    exts = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mp3", ".wav"}
    p = normalize_local_path(path)
    return os.path.isfile(p) and os.path.splitext(p)[1].lower() in exts

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
        title = "đây là video chỉ lấy text không có tiêu đề"
        return title

    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề bằng yt_dlp: {e}")
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
        return None
    
def download_video2(video_url, output_path):
    """Tải video về thư mục output_video"""
    try:
        ydl_opts = {"quiet": True, "outtmpl": output_path}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print("✅ Video đã được tải xuống thành công.")
        return output_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
        return None
    
def download_video(video_url):
    """Tải video và trả về đường dẫn file đã lưu"""
    ydl_opts = {
        "quiet": True,
        "outtmpl": os.path.join(OUTPUT_VIDEO_DIR, "%(title).200s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4"
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            file_path = ydl.prepare_filename(info)  # lấy tên file thực tế
            return file_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
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
        return None

def get_audio_duration(audio_path):
    """Lấy thời lượng của file audio (đơn vị giây)."""
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000  # Chuyển từ mili-giây sang giây
    except Exception as e:
        print(f"❌ Lỗi khi lấy thời lượng file audio: {e}")
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
            return True

    # 🔹 Giữ lại kiểm tra tổng thể
    sentence_counts = Counter(sentences)
    repeated_sentences = sum(1 for count in sentence_counts.values() if count > 2)
    if len(sentences) > 0 and (repeated_sentences / len(sentences)) > 0.1:
        print("⚠️ Phát hiện lỗi: Quá nhiều câu bị lặp lại!")
        return True

    return False

def format_segments_with_timestamps(segments):
    """Chuyển các đoạn thành văn bản, có thể kèm hoặc bỏ timestamp."""
    parts = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue

        if SHOW_TIMESTAMPS:
            start_time = int(seg["start"])
            minutes = start_time // 60
            seconds = start_time % 60
            timestamp = f"[{minutes:02}:{seconds:02}]"
            parts.append(f"{timestamp} {text}")
        else:
            parts.append(text)

    # ❗ Nếu có timestamp thì vẫn xuống dòng từng segment
    # ❗ Nếu KHÔNG timestamp (SHOW_TIMESTAMPS = False) thì nối bằng dấu cách thành 1 đoạn
    if SHOW_TIMESTAMPS:
        return "\n".join(parts)
    else:
        return " ".join(parts)

def transcribe_whisper(audio_path):
    """Nhận diện giọng nói bằng Whisper kèm thời gian mỗi câu"""

    global model, model2  # Khai báo model và model2 là biến toàn cục

    print("📝 Đang kiểm tra thời lượng file âm thanh...")

    duration = get_audio_duration(audio_path)
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None

    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    if duration > 9000:  # 900 giây = 15 phút
        print("❌ File audio dài hơn 15 phút, không thể nhận diện.")
        return None

    # 🔸 Xóa model2 (large-v3) trước khi quay lại medium
    if 'model2' in globals():
        print("🗑️ Đang xóa model large-v3 khỏi bộ nhớ GPU để quay lại medium...")
        del model2
        torch.cuda.empty_cache()
        gc.collect()
        print("✅ Model large-v3 đã được xóa.")

    # 🔹 Kiểm tra model medium đã tồn tại hay chưa, nếu chưa thì tải lại
    if 'model' not in globals() or model is None:
        print("🔄 Đang tải lại model medium...")
        model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
        print("✅ Model medium đã tải thành công.")

    print(f"📝 Đang nhận diện giọng nói bằng Whisper ...")
    result = model.transcribe(audio_path, language="vi", verbose=False, word_timestamps=False)

    # 👉 Bản transcript lần 1 với medium
    transcript_with_timestamps = format_segments_with_timestamps(result["segments"])

    # 🔹 Kiểm tra lỗi lặp từ
    if detect_repetition(result["text"]):
        print("🔄 Phát hiện lỗi lặp từ, chuyển sang model 'large-v3' và nhận diện lại...")

        # 💾 Lưu lại bản lần 1 (medium) vào output_videos để debug / so sánh
        try:
            base = os.path.splitext(os.path.basename(audio_path))[0]
            debug_path = os.path.join(OUTPUT_VIDEO_DIR, f"{base}_medium_first.txt")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(transcript_with_timestamps)
            print(f"💾 Đã lưu bản nhận diện lần 1 (medium) tại: {debug_path}")
        except Exception as e:
            print(f"⚠️ Không lưu được bản medium lần 1: {e}")

        MODEL_NAME2 = "large-v3"
        whisper_model_path = os.path.join(WHISPER_MODEL_PATH, f"{MODEL_NAME2}.pt")
        if os.path.exists(whisper_model_path):
            print(f"✅ Mô hình Whisper '{MODEL_NAME2}' đã có, không cần tải lại.")
        else:
            print(f"🔄 Tải mô hình Whisper '{MODEL_NAME2}'...")

        if 'model2' not in globals() or model2 is None:
            print(f"🔄 Đang tải model large-v3...")
            model2 = whisper.load_model(MODEL_NAME2, download_root=WHISPER_MODEL_PATH).to(device)
            print("✅ Model large-v3 đã tải thành công.")

        if 'model' in globals():
            print("🗑️ Đang xóa model medium khỏi bộ nhớ GPU để giải phóng tài nguyên...")
            del model
            torch.cuda.empty_cache()
            gc.collect()
            print("✅ Model medium đã được xóa.")

        print(f"📝 Chạy lại nhận diện giọng nói với model '{MODEL_NAME2}'...")
        result = model2.transcribe(audio_path, language="vi", verbose=False, word_timestamps=False)
        transcript_with_timestamps = format_segments_with_timestamps(result["segments"])

    return transcript_with_timestamps

def send_to_chatgpt(driver, text):
    """Gửi nội dung đến ChatGPT, lấy kết quả ngay khi ChatGPT dừng gõ, kiểm tra 30 giây để cập nhật nếu có thay đổi."""
    try:
        prompt = (
            "không áp dụng yêu cầu trước đó. chỉ viết nội dung đã chỉnh sửa, không ghi phần thông báo như “Đã sửa” hay mô tả gì thêm, "
            "viết thành 1 đoạn không thêm icon, Sửa lỗi chính tả, kiểm tra câu văn có nghĩa, thêm dấu câu nếu cần, nhưng giữ nguyên nội dung gốc, "
            "không rút gọn hay thay đổi ý nghĩa, phù hợp với mô hình TTS, thay Bác sĩ x thành bác sĩ Hội. "
            "Ưu tiên sửa lỗi chính tả các từ/thuật ngữ tiếng Anh. "
            "Quy tắc tiếng Anh: nếu là thuật ngữ/viết tắt (ví dụ: REM, cortisol, goitrogen, omega-3, HbA1c…), hãy viết đúng chuẩn; "
            "nếu nghi ngờ do TTS nghe sai, hãy chọn cách viết tiếng Anh phổ biến nhất trong ngữ cảnh; không dịch sang tiếng Việt trừ khi bản gốc đã có dịch. "
            "Giữ nguyên số liệu/ký hiệu (ví dụ: 2 x 10, 40–60%).\n\n"
            + text
        )
        # Tìm ô nhập liệu của ChatGPT
        try:
            textarea = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
            )
        except Exception as e:
            print(f"❌ Lỗi: Không tìm thấy ô nhập câu hỏi - {e}")
            return None

        # Đếm số tin nhắn trước khi gửi yêu cầu
        initial_messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        initial_count = len(initial_messages)

        # Gửi nội dung
        textarea.clear()
        textarea.send_keys(prompt)
        textarea.send_keys("\ue007")  # Nhấn Enter để gửi

        # **Cấu hình thời gian chờ**
        max_wait_time = 180  # ⏳ Chờ tối đa 3 phút (180 giây) để ChatGPT phản hồi
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
        
def is_local_video(path):
    exts = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in exts

def is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))

def process_video(index, link, doc):
    video_number, link = clean_link(link)
    print(f"\n🎥 Đang xử lý video {video_number}: {link}")

    video_path = None
    title = None

    # 1) LOCAL trước
    if is_local_video(link):
        video_path = normalize_local_path(link)
        title = os.path.splitext(os.path.basename(video_path))[0]
        print("📂 Nguồn: LOCAL")
    # 2) Sau đó mới tới URL
    elif is_url(link):
        if is_tiktok_link(link):
            print("🌐 Nguồn: TikTok")
            outtmpl = os.path.join(OUTPUT_VIDEO_DIR, "%(title).200s.%(ext)s")
            video_path = download_videoTIKTOK(link, outtmpl)
        else:
            print("🌐 Nguồn: Facebook")
            fb_video_url = get_facebook_video_url(link)
            if not fb_video_url:
                print("❌ Không lấy được URL Facebook thực. Bỏ qua.")
                return
            video_path = download_video(fb_video_url)
        if not video_path:
            print("❌ Tải video thất bại. Bỏ qua.")
            return
        title = os.path.splitext(os.path.basename(video_path))[0]
    else:
        # Không phải local, cũng không phải URL hợp lệ
        print("❌ Dòng không phải đường dẫn local hay URL. Bỏ qua.")
        return

    # 3) (Tuỳ chọn) lọc tiêu đề
    if CHECK_TITLE_BLACKLIST and check_title_blacklist(title):
        print(f"⛔ Bỏ qua video {video_number} do tiêu đề không phù hợp.")
        return

    # 4) Trích âm thanh
    audio_filename = f"audio_{video_number}.wav"
    audio_path = os.path.join(OUTPUT_VIDEO_DIR, audio_filename)
    if not extract_audio(video_path, audio_path):
        print("❌ Trích âm thanh thất bại. Bỏ qua.")
        return

    # 5) Whisper
    transcript = transcribe_whisper(audio_path) or ""
    with open(os.path.join(OUTPUT_VIDEO_DIR, f"transcript_{video_number}.txt"), "w", encoding="utf-8") as f:
        f.write(transcript)

    # 6) Ghi Word
    para = doc.add_paragraph()
    run = para.add_run(f"{video_number}. {link}")
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.size = Pt(11)
    doc.add_paragraph(f"Tiêu đề: {title}")
    doc.add_paragraph(f"Nội dung:\n{transcript}" if transcript else "Nội dung: (không có)")
    doc.add_paragraph("=" * 40)

    try:
        doc.save(OUTPUT_WORD_FILE)
        print("💾 Đã lưu kết quả vào Word.")
    except Exception as e:
        print(f"❌ Lỗi khi lưu Word: {e}")
    finally:
        print("✅ Hoàn thành video này.")

def process_videos():
    doc = Document(OUTPUT_WORD_FILE) if os.path.exists(OUTPUT_WORD_FILE) else Document()
    if not os.path.exists(OUTPUT_WORD_FILE):
        doc.save(OUTPUT_WORD_FILE)

    with open(LINKS_FILE, "r", encoding="utf-8") as file:
        links = [line.strip() for line in file if line.strip()]

    for idx, link in enumerate(links, start=1):
        print(f"🔄 Đang xử lý video {idx}/{len(links)}...")
        process_video(idx, link, doc)

    print(f"🎉 Hoàn thành. Kết quả ở {OUTPUT_WORD_FILE}")

if __name__ == "__main__":
    process_videos()


# ============================================================
# TÓM TẮT CHỨC NĂNG CHÍNH — PHIÊN BẢN ĐÃ CHỈNH SỬA
# ============================================================
# MỤC TIÊU:
#   - Xử lý danh sách video từ file linkgettoText.txt (mỗi dòng 1 mục).
#   - Hỗ trợ 3 nguồn: video LOCAL (ổ đĩa), Facebook, TikTok.
#   - Tải/nhận diện nguồn (nếu cần) → trích âm thanh (ffmpeg) → nhận dạng lời (Whisper) → xuất TXT + DOCX.
#
# DÒNG CHẢY CHÍNH:
#   1) process_videos():
#       - Đọc danh sách từ linkgettoText.txt.
#       - Lặp và gọi process_video(idx, link, doc) cho từng dòng.
#       - Lưu file Word tổng hợp final_result.docx.
#
#   2) process_video():
#       - clean_link() để lấy số thứ tự + giá trị link/đường dẫn.
#       - is_local_video(link)? → nếu True: dùng trực tiếp file local.
#       - Nếu không phải local:
#           + is_tiktok_link(link)? True → download_videoTIKTOK() (yt_dlp + cookies khi cần).
#           + Ngược lại coi là Facebook:
#               * get_facebook_video_url() lấy media URL thực.
#               * download_video() tải về (yt_dlp).
#       - extract_audio() trích WAV mono 16 kHz từ video (ffmpeg).
#       - transcribe_whisper() chạy Whisper:
#           + Mặc định model = "medium".
#           + Nếu detect_repetition() phát hiện lặp/spam → chuyển model "large-v3" và chạy lại.
#           + Xuất transcript có timestamp dạng [MM:SS] cho từng đoạn.
#       - Ghi:
#           + transcript_{n}.txt trong output_videos/.
#           + Gộp vào Word: số thứ tự + link/đường dẫn, "Tiêu đề" (từ tên file), "Nội dung" = transcript.
#           + Thêm dòng "==========" làm phân cách.
#
# THƯ MỤC/FILE QUAN TRỌNG:
#   - linkgettoText.txt  : danh sách đầu vào (link hoặc đường dẫn local).
#   - output_videos/     : nơi chứa video tải xuống, audio_*.wav, transcript_*.txt.
#   - whisper_cache/     : cache mô hình Whisper (medium, large-v3...).
#   - final_result.docx  : tổng hợp kết quả cuối (Word).
#
# THAM SỐ & CẤU HÌNH CHÍNH:
#   - MODEL_NAME = "medium"          : mô hình Whisper mặc định.
#   - CHECK_TITLE_BLACKLIST = False  : bật True nếu cần lọc tiêu đề.
#   - BLACKLIST_KEYWORDS             : danh sách từ khóa cấm (nếu bật lọc).
#   - FFMPEG_PATH = shutil.which("ffmpeg") : ffmpeg phải có trong PATH.
#
# HÀM CHÍNH (VAI TRÒ):
#   - process_videos()                 : điều phối toàn bộ phiên xử lý.
#   - process_video(index, link, doc)  : xử lý 1 mục (local/FB/TikTok → audio → Whisper → TXT/DOCX).
#   - is_local_video(path)             : nhận biết file video local theo phần mở rộng.
#   - is_tiktok_link(url)              : nhận biết đường dẫn TikTok.
#   - get_facebook_video_url(url)      : lấy media URL thực từ link Facebook (yt_dlp).
#   - download_video(url)              : tải video FB (bestvideo+bestaudio, mp4).
#   - download_videoTIKTOK(url, out)   : tải video TikTok (yt_dlp, có thể cần cookies Firefox).
#   - extract_audio(video, wav_path)   : ffmpeg trích WAV 16 kHz mono.
#   - transcribe_whisper(audio_path)   : chạy Whisper, thêm timestamp; tự fallback large-v3 khi lặp.
#   - detect_repetition(text)          : phát hiện câu lặp/quảng bá spam để nâng model.
#   - format_segments_with_timestamps(): ghép transcript kèm [MM:SS].
#   - clear_output_directory(dir)      : dọn sạch output_videos/ trước phiên (cẩn trọng dữ liệu cũ).
#
# CÁCH DÙNG (WORKFLOW):
#   1) Chuẩn bị ffmpeg và các thư viện: yt_dlp, whisper, torch, python-docx, pydub, v.v.
#   2) Điền danh sách vào linkgettoText.txt (ví dụ):
#        1. D:\Videos\phongvan1.mp4
#        2. https://www.facebook.com/watch/?v=1234567890
#        3. https://www.tiktok.com/@user/video/987654321
#   3) Chạy script: python your_script.py
#   4) Kết quả:
#        - output_videos/: video tải, audio_{n}.wav, transcript_{n}.txt
#        - final_result.docx: gộp toàn bộ transcript + link/đường dẫn + tiêu đề.
#
# GIỚI HẠN & LƯU Ý:
#   - transcribe_whisper() từ chối audio > 15 phút (900s). Cần cắt nhỏ nếu dài hơn.
#   - Dòng "from pyexpat import model" phải xóa để tránh đè biến model của Whisper.
#   - BLACKLIST_KEYWORDS2 trong bản gốc có lỗi thiếu dấu phẩy; nếu dùng, chuẩn hóa và gán:
#       BLACKLIST_KEYWORDS = BLACKLIST_KEYWORDS2; CHECK_TITLE_BLACKLIST = True
#   - Nhánh TikTok trong bản gốc cần gọi download_videoTIKTOK() đúng tham số outtmpl.
#   - Selenium / send_to_chatgpt() không còn dùng trong luồng chính → có thể bỏ để gọn dependency.
#   - Nếu dùng GPU: device = "cuda" khi torch.cuda.is_available(); cân nhắc giới hạn VRAM nếu cần.
#
# MỞ RỘNG NHANH (TÙY CHỌN):
#   - Thêm cắt nhỏ audio tự động khi > 15 phút rồi ghép transcript.
#   - Hỗ trợ thêm nguồn (YouTube) bằng yt_dlp.
#   - Tự động remux MKV→MP4 nếu cần hậu kỳ.
# ============================================================
