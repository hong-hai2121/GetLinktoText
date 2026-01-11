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

# ================= Cấu hình =================
LINKS_FILE = "linkgettoText.txt"  # File chứa danh sách link video
OUTPUT_WORD_FILE = "final_result.docx"  # Xuất kết quả ra file Word
WHISPER_MODEL_PATH = "whisper_cache"  # Thư mục lưu mô hình Whisper
OUTPUT_VIDEO_DIR = "output_videos"  # Thư mục lưu video tải xuống
MODEL_NAME = "medium"  # Đặt đúng tên file mô hình đã có (large-v3,medium,small)
FFMPEG_PATH = shutil.which("ffmpeg")  # Kiểm tra ffmpeg

if FFMPEG_PATH is None:
    print("⚠️ ffmpeg không có trong PATH. Hãy cài đặt ffmpeg để tiếp tục.")
    exit(1)

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"✅ Whisper sẽ chạy trên {'GPU' if device == 'cuda' else 'CPU'}")
torch.cuda.set_per_process_memory_fraction(0.8, 0)
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
    # 🔽 Thu nhỏ cửa sổ ngay sau khi mở
    driver.minimize_window()
    driver.get("https://chat.openai.com/")
    time.sleep(7)
    return driver
    


def get_video_title_facebook(url, browser):
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
                print(f"⚠️ Không tìm thấy tiêu đề với XPath: {xpath}: ")
                
        print("❌ Không thể lấy tiêu đề với cả hai XPath.")
        browser.close()
        browser.switch_to.window(browser.window_handles[0])
        return "Không thể lấy tiêu đề"
    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề: {e}")
        return "Không thể lấy tiêu đề"

def get_video_title_tiktok(url, browser):
    """Lấy tiêu đề video bằng danh sách XPath."""
    try:
        browser.execute_script("window.open('about:blank', '_blank');")
        browser.switch_to.window(browser.window_handles[-1])
        browser.get(url)
        wait = WebDriverWait(browser, 10)
        xpaths = [
            '/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/div[2]/div[1]/div/h1/span[1]',
            '/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/div[2]/div[1]/div/h1'
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
    """Tải video từ TikTok hoặc YouTube"""
    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
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
    
def transcribe_whisper(audio_path):
    """Nhận diện giọng nói bằng Whisper"""

    print("📝 Đang kiểm tra thời lượng file âm thanh...")
    
    duration = get_audio_duration(audio_path)
    
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None
    
    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    if duration > 900:  # 900 giây = 15 phút
        print("❌ File audio dài hơn 15 phút, không thể nhận diện.")
        return None
    
    print("📝 Đang nhận diện giọng nói...")
    result = model.transcribe(audio_path, language="vi")
    return result["text"]

def send_to_chatgpt(driver, text):
    """Gửi nội dung đến ChatGPT và lấy câu trả lời mới nhất khi nội dung ổn định."""
    try:
        prompt = f"giữ nguyên nội dung gốc, sửa kiểm chính tả cho văn bản tiếng việt kèm 1 số từ tiếng anh nếu có, kiểm tra câu văn có nghĩa, viết thành 1 đoạn, thêm dấu câu, thay Bác sĩ x thành bác sĩ Hội:\n\n{text}"
        
        try:
            textarea = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
            )
        except Exception as e:
            print(f"❌ Lỗi: Không tìm thấy ô nhập câu hỏi - {e}")
            print("⛔ Dừng chương trình do lỗi nhập câu hỏi!")
            exit(1)

        # Đếm số lượng tin nhắn hiện tại trước khi gửi câu hỏi
        initial_messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        initial_count = len(initial_messages)

        textarea.clear()
        textarea.send_keys(prompt)
        textarea.send_keys("\ue007")  # Nhấn Enter để gửi
        
        max_wait_time = 660  # Chờ tối đa 6 phút
        stable_time = 30  # Thời gian cần nội dung ổn định (giây)
        check_interval = 13  # Kiểm tra mỗi 5 giây
        
        last_content = ""
        stable_counter = 0
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            time.sleep(check_interval if stable_counter == 0 else stable_time)
            messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
            
            if len(messages) > initial_count:  # Chỉ lấy tin nhắn mới
                new_messages = messages[initial_count:]
                current_content = "\n".join([msg.text.strip() for msg in new_messages])  # ✅ Lấy tất cả tin nhắn
                
                print(f"📩 Đang nhận phản hồi mới từ ChatGPT ({int(time.time() - start_time)}s):...")

                if current_content == last_content:
                    stable_counter += check_interval
                    print(f"⚖ Nội dung không thay đổi, đợi {stable_time}s để xác nhận.")
                    if stable_counter >= stable_time:
                        print(f"✅ Nội dung đã ổn định sau {int(time.time() - start_time)}s, trả về kết quả.")
                        return current_content  # ✅ Trả về toàn bộ nội dung
                else:
                    stable_counter = 0  # Reset nếu nội dung thay đổi
                    print("🔄 Phát hiện nội dung thay đổi, reset thời gian chờ.")

                last_content = current_content
        
        print("⚠️ Nội dung chưa ổn định hoàn toàn nhưng đã hết thời gian chờ. Trả về kết quả cuối cùng.")
        return last_content if last_content else f"❌ Lỗi khi gửi câu hỏi nội dung gốc là: {text}"
    
    except Exception as e:
        print(f"❌ Lỗi khi gửi câu hỏi: {e}")
        print("⛔ Dừng chương trình do lỗi không xác định khi gửi câu hỏi!")
        exit(1)
    
    except Exception as e:
        print(f"❌ Lỗi khi gửi câu hỏi: {e}")
        print("⛔ Dừng chương trình do lỗi không xác định khi gửi câu hỏi!")
        exit(1)

def is_tiktok_link(url):
    """Kiểm tra xem một URL có phải là liên kết TikTok hay không"""
    tiktok_pattern = re.compile(r"tiktok", re.IGNORECASE)
    return bool(tiktok_pattern.search(url))

def process_video(index, link, doc, driver, browser):
    video_number, link = clean_link(link)
    video_number = video_number if video_number is not None else index
    print(f"\n🎥 Đang xử lý video {video_number}: {link}")

    checklinktiktok = 1 if is_tiktok_link(link) else 0
    print(f"{link} -> TikTok: {checklinktiktok}")

    if checklinktiktok == 0:
        title = get_video_title_facebook(link, browser)
    else:
        title = get_video_title_tiktok(link, browser)
        
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
    print(f"❌ transcript của video: {transcript}")
    #os.remove(audio_path)
    # Lưu transcript vào file TXT theo số thứ tự video
    transcript_filename = f"transcript_{video_number}.txt"
    transcript_path = os.path.join(OUTPUT_VIDEO_DIR, transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as f:
        if transcript is None:
            print("⚠ Không có transcript, bỏ qua xử lý văn bản.")
            transcript = ""
            #return None  # Ngăn lỗi tiếp tục xảy ra
        formatted_transcript = transcript.replace(". ", ".\n")  # Xuống dòng sau mỗi câu
        f.write(formatted_transcript)

    print(f"💾 Đã lưu transcript vào: {transcript_path}")

    if transcript:  # Kiểm tra nếu transcript không rỗng
        print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
        refined_text = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
        time.sleep(3)
    else:
        print(f"⚠️ Video {video_number} không có transcript, bỏ qua gửi đến ChatGPT.")
        refined_text = "Dây là video quá dài để lấy nội dung."

    # print(f"📝 Đang gửi nội dung video {video_number} đến ChatGPT...")
    # c = send_to_chatgpt(driver, transcript)  # Gửi đúng nội dung video hiện tại
    time.sleep(5)
    # Lưu kết quả ngay lập tức vào file Word
    doc.add_paragraph(f"{video_number}. {link}").runs[0].font.color.rgb = RGBColor(255, 0, 0)
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
        time.sleep(5)

def process_videos():
    # ✅ Nếu file tồn tại, mở file hiện có; nếu không, tạo file mới
    if os.path.exists(OUTPUT_WORD_FILE):
        doc = Document(OUTPUT_WORD_FILE)
    else:
        doc = Document()
        doc.save(OUTPUT_WORD_FILE)  # Đảm bảo file tồn tại

    driver = init_firefox()
    firefox_options = FirefoxOptions()
    firefox_options.add_argument("--headless")
    browser = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=firefox_options)
    with open("linkgettoText.txt", "r", encoding="utf-8") as file:
        links = [line.strip() for line in file.readlines() if line.strip()]
    # Giới hạn chỉ lấy 50 link đầu tiên
    links = links[0:2]
    for idx, link in enumerate(links, start=1):
        print(f"🔄 Đang xử lý video {idx}/{len(links)}...")
        process_video(idx, link, doc, driver, browser)  # ✅ Truyền `doc` vào
    
    driver.quit()
    browser.quit()
    print("🎉 Hoàn thành tất cả video! Kết quả đã lưu vào final_result.docx")

if __name__ == "__main__":
    process_videos()
