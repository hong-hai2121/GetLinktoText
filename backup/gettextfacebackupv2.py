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

# ================= Cấu hình =================
LINKS_FILE = "linkgettoText.txt"  # File chứa danh sách link video
OUTPUT_WORD_FILE = "final_result.docx"  # Xuất kết quả ra file Word
WHISPER_MODEL_PATH = "whisper_cache"  # Thư mục lưu mô hình Whisper
OUTPUT_VIDEO_DIR = "output_videos"  # Thư mục lưu video tải xuống
MODEL_NAME = "large-v3"  # Đặt đúng tên file mô hình đã có (large-v3,medium,small)
FFMPEG_PATH = shutil.which("ffmpeg")  # Kiểm tra ffmpeg

if FFMPEG_PATH is None:
    print("⚠️ ffmpeg không có trong PATH. Hãy cài đặt ffmpeg để tiếp tục.")
    exit(1)

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"✅ Whisper sẽ chạy trên {'GPU' if device == 'cuda' else 'CPU'}")

#if device == "cuda":
    #torch.cuda.set_per_process_memory_fraction(0.7, 0)  # Giới hạn PyTorch chỉ sử dụng tối đa 50% VRAM
    
# Tạo thư mục nếu chưa có
os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)

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
FIREFOX_PROFILE_PATH = r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\kt92li14.GPT_DEEPSEEK"

def clean_link(line):
    """Loại bỏ số thứ tự trước link (VD: '23. https://facebook.com/video')"""
    match = re.search(r'(\d+)\.\s*(https?://\S+)', line)
    if match:
        return int(match.group(1)), match.group(2)
    return None, line.strip()

def init_firefox():
    """Khởi tạo trình duyệt Firefox với Selenium và mở ChatGPT."""
    options = FirefoxOptions()
    options.add_argument(f"-profile")
    #options.add_argument("--headless")
    options.add_argument(f"{FIREFOX_PROFILE_PATH}")
    service = FirefoxService(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)
    driver.get("https://chat.openai.com/")
    time.sleep(7)
    return driver

def send_to_chatgpt(driver, text):
    """Gửi nội dung đến ChatGPT và lấy câu trả lời."""
    try:
        prompt = f"giữ nguyên nội dung gốc, kiểm tra chính tả câu văn có nghĩa, viết thành 1 đoạn, thêm dấu câu, thay Bác sĩ x thành bác sĩ Hội:\n\n{text}"
        textarea = driver.find_element(By.XPATH, '//*[@id="prompt-textarea"]')
        textarea.clear()
        textarea.send_keys(prompt)
        textarea.send_keys("\ue007")  # Nhấn Enter để gửi
        time.sleep(60)
        messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        return messages[-1].text if messages else "❌ Không lấy được câu trả lời!"
    except Exception as e:
        return f"❌ Lỗi khi gửi câu hỏi: {str(e)}"

def get_video_title(url, browser):
    """Lấy tiêu đề video bằng danh sách XPath."""
    try:
        browser.execute_script("window.open('about:blank', '_blank');")
        browser.switch_to.window(browser.window_handles[-1])
        browser.get(url)
        wait = WebDriverWait(browser, 10)
        xpaths = [
            '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div/div[2]/div/div/div/div/div/div/div[2]/div[1]/div/div[1]/div[2]/div/div/div[2]/span/div',
            '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[2]/div[1]/div/div/div[2]/div[1]/div[3]/div/span/div/div'
        ]
        for xpath in xpaths:
            try:
                title_element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                title = title_element.text.strip()
                print(f"✅ Tiêu đề video: {title}")
                browser.close()
                browser.switch_to.window(browser.window_handles[0])
                return title
            except:
                print(f"⚠️ Không tìm thấy tiêu đề với XPath: {xpath}")
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
        return output_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
        return None

def extract_audio(video_path, output_wav):
    """Trích xuất âm thanh từ video"""
    command = [FFMPEG_PATH, "-i", video_path, "-ac", "1", "-ar", "16000", "-y", output_wav, "-vn"]
    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return output_wav
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi trích xuất âm thanh: {e}")
        return None

def transcribe_whisper(audio_path):
    """Nhận diện giọng nói bằng Whisper"""
    print("📝 Đang nhận diện giọng nói...")
    result = model.transcribe(audio_path, language="vi")
    return result["text"]

def process_video(index, link, doc, driver, browser):
    video_number, link = clean_link(link)
    video_number = video_number if video_number is not None else index
    print(f"\n🎥 Đang xử lý video {video_number}: {link}")
    fb_video_url = get_facebook_video_url(link)
    if not fb_video_url:
        return None
    title = get_video_title(link, browser)
    video_filename = f"video_{video_number}.mp4"
    video_path = os.path.join(OUTPUT_VIDEO_DIR, video_filename)
    if not download_video(fb_video_url, video_path):
        return None
    audio_path = f"audio_{video_number}.wav"
    if not extract_audio(video_path, audio_path):
        return None
    transcript = transcribe_whisper(audio_path)  # Đảm bảo transcript được tạo riêng cho từng video
    os.remove(audio_path)
    print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
    refined_text = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
    doc.add_paragraph(f"{video_number}. {link}").runs[0].font.color.rgb = RGBColor(255, 0, 0)
    doc.add_paragraph(f"Tiêu đề: {title}")
    doc.add_paragraph(f"Nội dung:\n{refined_text}")
    doc.add_paragraph("=" * 40)

def process_videos():
    doc = Document()
    driver = init_firefox()
    firefox_options = FirefoxOptions()
    firefox_options.add_argument("--headless")
    browser = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=firefox_options)
    with open("linkgettoText.txt", "r", encoding="utf-8") as file:
        links = [line.strip() for line in file.readlines() if line.strip()]
    for idx, link in enumerate(links, start=1):
        print(f"🔄 Đang xử lý video {idx}/{len(links)}...")
        process_video(idx, link, doc, driver, browser)
    doc.save("final_result.docx")
    driver.quit()
    browser.quit()
    print("🎉 Hoàn thành tất cả video! Kết quả đã lưu vào final_result.docx")

if __name__ == "__main__":
    process_videos()
