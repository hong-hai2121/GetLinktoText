import os
import yt_dlp
import whisper
import torch
import subprocess
import shutil
import sys
import openai  # Thư viện OpenAI API
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager
from docx import Document  # Thư viện xử lý file Word
from docx.shared import RGBColor  # Dùng để tạo màu sắc
import re
import time
from docx.shared import Pt
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.keys import Keys


# ✅ Đường dẫn đến GeckoDriver
geckodriver_path = r"D:\Python\GetLinktoText\geckodriver.exe"

# ✅ Đường dẫn đến profile Firefox đã đăng nhập ChatGPT
firefox_profile_path = r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\kt92li14.GPT_DEEPSEEK"

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

# Khởi tạo trình duyệt Selenium
def init_chrome():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Chạy không giao diện
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")  # Mở rộng kích thước trình duyệt
    #service = Service(ChromeDriverManager().install())
    #return webdriver.Chrome(service=service, options=chrome_options)

    # 📌 Tự động tải ChromeDriver phiên bản phù hợp
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
        
    return driver

# ================= Hàm xử lý =================
def init_firefox():
    """Khởi tạo trình duyệt Firefox với Selenium và mở ChatGPT."""
    options = Options()
    options.add_argument(f"-profile")
    options.add_argument(f"{firefox_profile_path}")
    
    service = Service(geckodriver_path)
    driver = webdriver.Firefox(service=service, options=options)
    driver.get("https://chat.openai.com/")
    
    time.sleep(7)  # Chờ trang ChatGPT tải xong
    return driver

def send_to_chatgpt(driver, text):
    """Gửi nội dung đến ChatGPT và lấy câu trả lời."""
    try:
        # 📌 Thêm yêu cầu trước nội dung
        prompt = (
            "giữ nguyên nội dung gốc viết lại câu văn chôi chảy mạch lạc dễ tiếp thu về kiến thức y khoa cho người nghe, kiểm tra chính tả câu văn có nghĩa, viết thành 1 đoạn, thêm dấu câu, thay Bác sĩ x thành bác sĩ Hội: .\n\n"
            "Dưới đây là nội dung cần chỉnh sửa:\n\n"
            f"{text}"  # Gửi nội dung gốc kèm theo yêu cầu
        )
        # 📌 Tìm khung nhập tin nhắn
        textarea = driver.find_element(By.XPATH, '//*[@id="prompt-textarea"]')
        textarea.clear()
        textarea.send_keys(prompt)
        textarea.send_keys(Keys.RETURN)  # Nhấn Enter để gửi

        # ⏳ Chờ phản hồi
        time.sleep(60)

        # 📌 Lấy câu trả lời từ ChatGPT
        messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        if messages:
            return messages[-1].text  # Lấy câu trả lời mới nhất
        return "❌ Không lấy được câu trả lời!"
    except Exception as e:
        return f"❌ Lỗi khi gửi câu hỏi: {str(e)}"

def clean_link(line):
    """Loại bỏ số thứ tự trước link (VD: '23. https://facebook.com/video')"""
    match = re.search(r'(\d+)\.\s*(https?://\S+)', line)
    if match:
        return int(match.group(1)), match.group(2)
    return None, line.strip()

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

def get_video_title(url):
    """Lấy tiêu đề video bằng Selenium với 2 XPath"""
    browser = init_chrome()
    try:
        browser.get(url)

        wait = WebDriverWait(browser, 10)

        # 📌 Danh sách 2 XPath để thử
        xpaths = [
            '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div/div[2]/div/div/div/div/div/div/div[2]/div[1]/div/div[1]/div[2]/div/div/div[2]/span/div',
            '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[2]/div[1]/div/div/div[2]/div[1]/div[3]/div/span/div/div'
        ]

        for xpath in xpaths:
            try:
                title_element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                title = title_element.text.strip()
                print(f"✅ Tiêu đề video: {title}")
                return title
            except:
                print(f"⚠️ Không tìm thấy tiêu đề với XPath: {xpath}")

        print("❌ Không thể lấy tiêu đề với cả hai XPath.")
        return "Không thể lấy tiêu đề"

    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề: {e}")
        return "Không thể lấy tiêu đề"
    finally:
        browser.quit()
        
# Thiết lập API key        
#client = openai.OpenAI(api_key=os.getenv("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"))
os.environ["OPENAI_API_KEY"] = "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"
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def refine_text_with_gpt(text):
    """Gửi transcript đến GPT để chỉnh sửa chính tả và cải thiện nội dung."""
    prompt = (
        "bỏ qua các yêu cầu trước đó đây là nội dung mới. Hãy giữ nguyên nội dung gốc, chỉnh sửa ngữ cảnh "
        "Đồng thời, thay thế 'Bác sĩ x' thành 'bác sĩ Hội'. Dưới đây là nội dung cần chỉnh sửa:\n\n"
        f"""{text}"""
    )
    
    try:
        # 📌 In câu hỏi gửi đi
        print("\n📝 Câu hỏi gửi đi:")
        print(prompt)
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "system", "content": "Bạn là một chuyên gia ngôn ngữ. Hãy chỉ sửa lỗi ngữ cảnh, lỗi chính tả, lỗi ngữ pháp và dấu câu trong văn bản mà không thay đổi câu văn đúng. Giữ nguyên văn phong, ý nghĩa và không làm thay đổi cấu trúc của câu."},
                      {"role": "user", "content": prompt}],
            temperature=0
        )
        # 📌 In câu trả lời nhận về
        print("\n✅ Câu trả lời nhận về:")
        print(response.choices[0].message.content.strip())
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Lỗi khi gọi API GPT: {e}")
        return text  # Nếu lỗi, trả về văn bản gốc không chỉnh sửa
    
def process_video(index, link, doc, driver):
    """Xử lý một video và ghi vào file Word với nội dung đã chỉnh sửa bởi GPT."""
    video_number, link = clean_link(link)
    if video_number is None:
        video_number = index  # Nếu không có số thứ tự, lấy số tự động

    print(f"\n🎥 Đang xử lý video {video_number}: {link}")

    fb_video_url = get_facebook_video_url(link)
    if not fb_video_url:
        return None

    title = get_video_title(link)
    video_filename = f"video_{video_number}.mp4"
    video_path = os.path.join(OUTPUT_VIDEO_DIR, video_filename)

    if not download_video(fb_video_url, video_path):
        return None

    audio_path = f"audio_{video_number}.wav"
    if not extract_audio(video_path, audio_path):
        return None

    transcript = transcribe_whisper(audio_path)
    os.remove(audio_path)
    #print("📝 Đang Gọi API GPT để chỉnh sửa nội dung...")
    # 📝 Gọi API GPT để chỉnh sửa nội dung
    #efined_text = refine_text_with_gpt(transcript)

    #không gọi api nữa
    #refined_text = transcript

    print("📝 Đang gửi nội dung đến ChatGPT...")
    refined_text = send_to_chatgpt(driver, transcript)

    # Ghi vào file Word
    link_paragraph = doc.add_paragraph()
    link_run = link_paragraph.add_run(f"{video_number}. {link}")
    link_run.font.color.rgb = RGBColor(255, 0, 0)  # Màu đỏ
    link_run.font.size = Pt(12)

    title_paragraph = doc.add_paragraph()
    title_run = title_paragraph.add_run("Tiêu đề: ")
    title_run.bold = True
    title_run.font.size = Pt(12)
    title_paragraph.add_run(title)

    content_paragraph = doc.add_paragraph()
    content_run = content_paragraph.add_run("Nội dung:\n")
    content_run.bold = True
    content_run.font.size = Pt(12)
    content_paragraph.add_run(refined_text)

    doc.add_paragraph("=" * 40)  # Dòng phân cách

def process_videos():
    """Xử lý tất cả video và lưu vào file Word"""
    doc = Document()

    # 📌 Khởi động Selenium
    driver = init_firefox()

    with open(LINKS_FILE, "r", encoding="utf-8") as file:
        links = [line.strip() for line in file.readlines() if line.strip()]

    for idx, link in enumerate(links, start=1):
        process_video(idx, link, doc, driver)

    doc.save(OUTPUT_WORD_FILE)
    print(f"🎉 Hoàn thành tất cả video! Kết quả đã lưu vào {OUTPUT_WORD_FILE}")

if __name__ == "__main__":
    process_videos()
