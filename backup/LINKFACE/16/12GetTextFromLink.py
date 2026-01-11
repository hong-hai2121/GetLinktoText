import os
from pyexpat import model  # ❌ import này không dùng đến import model
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
from profiles_config import get_profile
import gc
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ================= Cấu hình =================
LINKS_FILE = "linkgettoText.txt"  # File chứa danh sách link video
OUTPUT_WORD_FILE = "final_result.docx"  # Xuất kết quả ra file Word
WHISPER_MODEL_PATH = "whisper_cache"  # Thư mục lưu mô hình Whisper
OUTPUT_VIDEO_DIR = "output_videos"  # Thư mục lưu video tải xuống
MODEL_NAME = "medium"  # Đặt đúng tên file mô hình đã có (large-v3,medium,small)
FFMPEG_PATH = shutil.which("ffmpeg")  # Kiểm tra ffmpeg
import sys
from pathlib import Path
# Thêm thư mục gốc dự án vào PYTHONPATH để import được profiles_config.py
PROJECT_ROOT = Path(r"D:\Python\GetLinktoText")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
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
    
# Tạo thư mục nếu chưa có
os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)

# Không load model ngay - để GUI load khi cần
model = None

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


def clean_link(line, counter=[0]):
    match = re.match(r'^\s*(\d+)[\.\s]+\s*(https?://\S+)', line)
    if match:
        counter[0] = int(match.group(1))  # Cập nhật lại số thứ tự hiện tại
        return counter[0], match.group(2)
    else:
        counter[0] += 1
        return counter[0], line.strip()


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

def transcribe_whisper(audio_path):
    """Nhận diện giọng nói bằng Whisper"""

    global model, model2  # Lặp lại nhiều lần, khó quản lý

    print("📝 Đang kiểm tra thời lượng file âm thanh...")

    duration = get_audio_duration(audio_path)
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None

    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    if duration > 900:  # 900 giây = 15 phút
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
    result = model.transcribe(audio_path, language="vi")
    #result = model.transcribe(audio_path)
    transcript = result["text"]

    # 🔹 Kiểm tra lỗi lặp từ
    if detect_repetition(transcript):
        print("🔄 Phát hiện lỗi lặp từ, chuyển sang model 'large-v3' và nhận diện lại...")

        MODEL_NAME2 = "large-v3"
        whisper_model_path = os.path.join(WHISPER_MODEL_PATH, f"{MODEL_NAME2}.pt")
        if os.path.exists(whisper_model_path):
            print(f"✅ Mô hình Whisper '{MODEL_NAME}' đã có, không cần tải lại.")
        else:
            print(f"🔄 Tải mô hình Whisper '{MODEL_NAME}'...")
        # 🔹 Kiểm tra model2 đã tồn tại hay chưa, nếu chưa thì tải
        if 'model2' not in globals() or model2 is None:
            print(f"🔄 Đang tải model large-v3...")
            model2 = whisper.load_model(MODEL_NAME2, download_root=WHISPER_MODEL_PATH).to(device)
            print("✅ Model large-v3 đã tải thành công.")

        # 🔹 Sau khi tải xong, mới xóa model medium
        if 'model' in globals():
            print("🗑️ Đang xóa model medium khỏi bộ nhớ GPU để giải phóng tài nguyên...")
            del model
            torch.cuda.empty_cache()
            gc.collect()
            print("✅ Model medium đã được xóa.")

        # 🔹 Chạy nhận diện lại với model2 (large-v3)
        print(f"📝 Chạy lại nhận diện giọng nói với model '{MODEL_NAME2}'...")
        result = model2.transcribe(audio_path, language="vi")
        transcript = result["text"]

    return transcript


def send_to_chatgpt(driver, text):
    """Gửi nội dung đến ChatGPT, lấy kết quả ngay khi ChatGPT dừng gõ, kiểm tra 30 giây để cập nhật nếu có thay đổi."""
    try:
        prompt = f"không áp dụng yêu cầu trước đó. chỉ viết nội dung đã chỉnh sửa, không ghi phần thông báo như “Đã sửa” hay mô tả gì thêm, viết thành 1 đoạn không thêm icon, Sửa lỗi chính tả, kiểm tra câu văn có nghĩa, thêm dấu câu nếu cần, nhưng giữ nguyên nội dung gốc, không rút gọn hay thay đổi ý nghĩa, phù hợp với mô hình TTS, thay Bác sĩ x thành bác sĩ Hội\n\n{text}"

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
    video_number, link = clean_link(link)
    video_number = video_number if video_number is not None else index
    print(f"\n🎥 Đang xử lý video {video_number}: {link}")

    checklinktiktok = 1 if is_tiktok_link(link) else 0
    print(f"{link} -> TikTok: {checklinktiktok}")

    # Lấy tiêu đề video
    if checklinktiktok == 0:
        title = get_video_title_facebook(link, browser)
    else:
        title = get_video_title_facebook(link, browser) #get_video_title_tiktok
        
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
        print(f"🎥 Video đã lưu tại: {video_path}")
    else:
        print(f"❌ Lỗi! Video chưa được lưu vào {video_path}")
    if not extract_audio(video_path, audio_path):
        return None
    
    if os.path.exists(audio_path):
        print(f"🎵 Âm thanh đã lưu tại: {audio_path}")
    else:
        print(f"❌ Lỗi! Âm thanh chưa được lưu vào {audio_path}")

    transcript = transcribe_whisper(audio_path)  # Đảm bảo transcript được tạo riêng cho từng video
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

    if transcript:  # Kiểm tra nếu transcript không rỗng
        print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
        refined_text = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
        save_refined_text(refined_text, video_number)
    else:
        print(f"⚠️ Video {video_number} không có transcript, bỏ qua gửi đến ChatGPT.")
        refined_text = "Dây là video quá dài để lấy nội dung."

    # print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
    # c = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
    # Lưu kết quả ngay lập tức vào file Word
    #doc.add_paragraph(f"{video_number}. {link}").runs[0].font.color.rgb = RGBColor(255, 0, 0)
    para = doc.add_paragraph()
    run = para.add_run(f"{video_number}. {link}")
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.size = Pt(11)  # tùy chỉnh
    doc.add_paragraph(f"Tiêu đề: {title}")

    if transcript:  # Chỉ thêm nội dung nếu có transcript
        doc.add_paragraph(f"Nội dung:\n{refined_text}")
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
    # ✅ Nếu file tồn tại, mở file hiện có; nếu không, tạo file mới
    if os.path.exists(OUTPUT_WORD_FILE):
        doc = Document(OUTPUT_WORD_FILE)
    else:
        doc = Document()
        doc.save(OUTPUT_WORD_FILE)  # Đảm bảo file tồn tại
    driver = init_firefox()  # Dùng trình duyệt đã mở sẵn
    with open("linkgettoText.txt", "r", encoding="utf-8") as file:
        links = [line.strip() for line in file.readlines() if line.strip()]
    # Giới hạn chỉ lấy 50 link đầu tiên
    #inks = links[0:4]
    for idx, link in enumerate(links, start=1):
        print(f"🔄 Đang xử lý video {idx}/{len(links)}...")
        process_video(idx, link, doc, driver, driver)  # ✅ Truyền `doc` vào
    driver.quit()
    print("🎉 Hoàn thành tất cả video! Kết quả đã lưu vào final_result.docx")

# ================= GUI =================


class GetTextApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GetTextFromLink - GUI")
        self.root.geometry("900x750")
        
        self.selected_model = tk.StringVar(value=MODEL_NAME)
        self.show_links_var = tk.BooleanVar(value=True)
        self.show_result_var = tk.BooleanVar(value=False)

        self.build_ui()
        self.load_links()

    def build_ui(self):
        # Frame cấu hình
        info_frame = ttk.LabelFrame(self.root, text="Cấu hình", padding=10)
        info_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(info_frame, text=f"Thư mục lưu video: {OUTPUT_VIDEO_DIR}").pack(anchor="w", pady=2)
        ttk.Label(info_frame, text=f"File Word kết quả: {OUTPUT_WORD_FILE}").pack(anchor="w", pady=2)
        ttk.Label(info_frame, text=f"Thiết bị: {'GPU' if device == 'cuda' else 'CPU'}").pack(anchor="w", pady=2)
        
        # Model selection
        model_frame = ttk.Frame(info_frame)
        model_frame.pack(fill="x", pady=5)
        ttk.Label(model_frame, text="Model Whisper:").pack(side="left", padx=5)
        model_combo = ttk.Combobox(model_frame, textvariable=self.selected_model, 
                                   values=["tiny", "base", "small", "medium", "large-v3"], 
                                   state="readonly", width=15)
        model_combo.pack(side="left", padx=5)
        
        # Frame danh sách link
        links_frame = ttk.LabelFrame(self.root, text=f"Danh sách link ({LINKS_FILE})", padding=10)
        links_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Toolbar với các nút
        links_toolbar = ttk.Frame(links_frame)
        links_toolbar.pack(fill="x", pady=(0, 5))
        
        ttk.Button(links_toolbar, text="💾 Lưu danh sách", 
                  command=self.save_links, width=15).pack(side="left", padx=2)
        ttk.Button(links_toolbar, text="🔄 Tải lại", 
                  command=self.load_links, width=15).pack(side="left", padx=2)
        ttk.Label(links_toolbar, text="(Mỗi link một dòng, có thể thêm số thứ tự: '1. https://...')").pack(side="left", padx=10)
        
        # Checkboxes ở hàng riêng
        checkbox_frame = ttk.Frame(links_frame)
        checkbox_frame.pack(fill="x", pady=(0, 5))
        ttk.Checkbutton(checkbox_frame, text="📋 Danh sách link", 
                       variable=self.show_links_var, command=self.on_links_checkbox).pack(side="left", padx=5)
        ttk.Checkbutton(checkbox_frame, text="📄 Kết quả (final_result.docx)", 
                       variable=self.show_result_var, command=self.on_result_checkbox).pack(side="left", padx=5)
        
        self.links_text = scrolledtext.ScrolledText(links_frame, wrap=tk.WORD, height=10)
        self.links_text.pack(fill="both", expand=True)

        # Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)

        self.start_btn = ttk.Button(control_frame, text="▶ Bắt đầu xử lý", command=self.start_process, width=25)
        self.start_btn.pack(side="left", padx=5)

        # Log area
        log_frame = ttk.LabelFrame(self.root, text="Nhật ký", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=8)
        self.log_text.pack(fill="both", expand=True)

    def load_links(self):
        """Tải danh sách link từ file"""
        try:
            if os.path.exists(LINKS_FILE):
                with open(LINKS_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                self.links_text.delete(1.0, tk.END)
                self.links_text.insert(1.0, content)
                link_count = len([l for l in content.split('\n') if l.strip()])
                self.log(f"✅ Đã tải {link_count} link từ {LINKS_FILE}")
            else:
                self.log(f"⚠️ File {LINKS_FILE} không tồn tại")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải link: {e}")
    
    def save_links(self):
        """Lưu danh sách link vào file"""
        try:
            content = self.links_text.get(1.0, tk.END).strip()
            with open(LINKS_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            link_count = len([l for l in content.split('\n') if l.strip()])
            self.log(f"💾 Đã lưu {link_count} link vào {LINKS_FILE}")
        except Exception as e:
            self.log(f"❌ Lỗi khi lưu link: {e}")
            messagebox.showerror("Lỗi", f"Không thể lưu file: {e}")
    
    def load_result(self):
        """Tải nội dung kết quả từ file Word"""
        try:
            if os.path.exists(OUTPUT_WORD_FILE):
                doc = Document(OUTPUT_WORD_FILE)
                content = []
                
                # Trích xuất tất cả nội dung từ các paragraph
                for para in doc.paragraphs:
                    text = para.text.strip()
                    if text:
                        content.append(text)
                
                # Nếu không có content, thử trích từ các bảng (nếu có)
                if not content and doc.tables:
                    for table in doc.tables:
                        for row in table.rows:
                            row_text = []
                            for cell in row.cells:
                                row_text.append(cell.text.strip())
                            if any(row_text):
                                content.append(" | ".join(row_text))
                
                result_text = "\n".join(content)
                self.links_text.delete(1.0, tk.END)
                
                if result_text:
                    self.links_text.insert(1.0, result_text)
                    self.log(f"✅ Đã tải {len(content)} dòng nội dung từ {OUTPUT_WORD_FILE}")
                else:
                    self.links_text.insert(1.0, "File kết quả trống")
                    self.log(f"⚠️ File {OUTPUT_WORD_FILE} không có nội dung")
            else:
                self.log(f"⚠️ File {OUTPUT_WORD_FILE} không tồn tại")
                self.links_text.delete(1.0, tk.END)
                self.links_text.insert(1.0, "File kết quả chưa được tạo")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải kết quả: {e}")
            self.links_text.delete(1.0, tk.END)
            self.links_text.insert(1.0, f"Lỗi: {str(e)}")
    
    def on_links_checkbox(self):
        """Xử lý khi click checkbox Danh sách link"""
        if self.show_links_var.get():
            # Đã check "Danh sách link" -> uncheck "Kết quả" và load links
            self.show_result_var.set(False)
            self.load_links()
        else:
            # Uncheck "Danh sách link" -> auto check "Kết quả"
            self.show_result_var.set(True)
            self.load_result()
    
    def on_result_checkbox(self):
        """Xử lý khi click checkbox Kết quả"""
        if self.show_result_var.get():
            # Đã check "Kết quả" -> uncheck "Danh sách link" và load result
            self.show_links_var.set(False)
            self.load_result()
        else:
            # Uncheck "Kết quả" -> auto check "Danh sách link"
            self.show_links_var.set(True)
            self.load_links()

    def log(self, message):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.root.after(0, _append)

    def start_process(self):
        # Lưu link trước khi xử lý
        self.save_links()
        self.start_btn.config(state="disabled")
        thread = threading.Thread(target=self.run_pipeline_thread, daemon=True)
        thread.start()

    def run_pipeline_thread(self):
        global MODEL_NAME, model
        
        # Tải hoặc cập nhật model theo model đã chọn
        selected = self.selected_model.get()
        
        try:
            # Nếu chưa có model hoặc model khác với model đã chọn
            if model is None or selected != MODEL_NAME:
                self.log(f"🔄 Đang tải model '{selected}'...")
                
                # Xóa model cũ nếu có
                if 'model' in globals() and model is not None:
                    del model
                    torch.cuda.empty_cache()
                    gc.collect()
                
                # Tải model mới
                MODEL_NAME = selected
                model = whisper.load_model(MODEL_NAME, download_root=WHISPER_MODEL_PATH).to(device)
                self.log(f"✅ Đã tải model '{MODEL_NAME}' thành công")
        except Exception as e:
            self.log(f"❌ Lỗi khi tải model: {e}")
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
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")
            messagebox.showerror("Lỗi", str(e))
        finally:
            builtins.print = original_print
            self.root.after(0, lambda: self.start_btn.config(state="normal"))


def launch_gui():
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
