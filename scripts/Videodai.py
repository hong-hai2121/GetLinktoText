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
OUTPUT_WORD_FILE = "final_result2.docx"  # Xuất kết quả ra file Word
WHISPER_MODEL_PATH = "whisper_cache"  # Thư mục lưu mô hình Whisper
OUTPUT_VIDEO_DIR = "output_videos"  # Thư mục lưu video tải xuống
MODEL_NAME = "medium"  # Đặt đúng tên file mô hình đã có (large-v3,medium,small)
FFMPEG_PATH = shutil.which("ffmpeg")  # Kiểm tra ffmpeg

USE_LINKS_FROM_FILE = False  # 🔁 Đổi thành True nếu muốn xử lý từ link trong file False
#LOCAL_VIDEO_DIR = r"D:\video edit\Video YOUTUBE"  # Thư mục chứa video có sẵn D:\video edit\Video Live Page  Video YOUTUBE
LOCAL_VIDEO_DIR = r"D:\video edit\Video Live Page"
#LOCAL_VIDEO_DIR = r"D:\truyen\1108\done"


# ===== Cấu hình chia audio =====
# Độ dài mỗi đoạn khi chia (ms). Bạn đang dùng 2 phút trong code cũ:
CHUNK_LENGTH_MS = 3 * 60 * 1000  # 2 phút/đoạn

# Giới hạn số đoạn cần xử lý:
# - Đặt = 5  → chỉ xử lý 5 đoạn đầu
# - Đặt = None → xử lý FULL đến hết file
MAX_CHUNKS = 5  # đổi thành None để chạy full


CHECK_TITLE_BLACKLIST = True  # Đổi thành False nếu không muốn kiểm tra tiêu đề True False
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

# Tạo thư mục nếu chưa có
os.makedirs(WHISPER_MODEL_PATH, exist_ok=True)
os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
# Gọi hàm xóa file trong thư mục output_video trước khi bắt đầu xử lý
clear_output_directory(OUTPUT_VIDEO_DIR)
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


# ✅ Cấu hình Firefox để gửi nội dung đến GPT
GECKODRIVER_PATH = r"D:\Python\GetLinktoText\geckodriver.exe"
FIREFOX_PROFILE_PATH = r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\wyo2tlat.GPT Chị Thảo" #C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\kt92li14.GPT_DEEPSEEK

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
    #options.add_argument("--headless")
    options.add_argument(f"{FIREFOX_PROFILE_PATH}")
    #service = FirefoxService(GeckoDriverManager().install())
    #driver = webdriver.Firefox(service=service, options=options)
    service = FirefoxService(executable_path=GECKODRIVER_PATH)
    driver = webdriver.Firefox(service=service, options=options)
    # 🔽 Thu nhỏ cửa sổ ngay sau khi mở
    #driver.minimize_window()
    driver.get("https://chatgpt.com/c/68353e03-fcb4-8001-816d-88fcba5dcaf8")
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
            '/html/head/title'
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
    
def split_audio(audio_path, chunk_length_ms=10 * 60 * 1000, max_chunks=None):
    """
    Chia file âm thanh thành các đoạn nhỏ có độ dài chunk_length_ms.
    Nếu max_chunks != None, chỉ tạo tối đa max_chunks đoạn (từ đầu).
    """
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
        return []
    
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
    SPAM_KEYWORDS2 = [
        "Hãy subscribe cho kênh Ghiền Mì Gõ để",
        "hãy subscribe cho kênh ghiền mì gõ để",
        "kênh Ghiền Mì Gõ"
    ]

    SPAM_KEYWORDS = []

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
            return False #True

    # 🔹 Giữ lại kiểm tra tổng thể
    sentence_counts = Counter(sentences)
    repeated_sentences = sum(1 for count in sentence_counts.values() if count > 2)
    if len(sentences) > 0 and (repeated_sentences / len(sentences)) > 0.1:
        print("⚠️ Phát hiện lỗi: Quá nhiều câu bị lặp lại!")
        return False #True

    return False

def transcribe_whisper(audio_path):
    """Nhận diện giọng nói bằng Whisper, chia nhỏ và lưu từng phần riêng, sau đó gộp lại."""

    global model, model2

    print("📝 Đang kiểm tra thời lượng file âm thanh...")

    duration = get_audio_duration(audio_path)
    if duration is None:
        print("❌ Không thể xác định thời lượng file audio.")
        return None

    print(f"⏳ Thời lượng file: {duration:.2f} giây")

    full_transcript = ""

    if duration > 180:  # dài hơn 3 phút thì chia đoạn
        print("⚠️ File audio dài hơn 3 phút, chia đoạn để xử lý...")

        # dùng cấu hình bạn đặt ở đầu file
        chunks = split_audio(
            audio_path,
            chunk_length_ms=CHUNK_LENGTH_MS,
            max_chunks=MAX_CHUNKS  # None = FULL, số nguyên = chỉ lấy bấy nhiêu đoạn đầu
        )

        for idx, chunk_path in enumerate(chunks):
            print(f"🧩 Đang xử lý đoạn {idx + 1}/{len(chunks)}: {chunk_path}")
            try:
                result = model.transcribe(chunk_path, language="vi")
                chunk_text = result["text"]

                if detect_repetition(chunk_text):
                    print("🔄 Lỗi lặp từ, chuyển sang model large-v3...")
                    if 'model2' not in globals() or model2 is None:
                        model2 = whisper.load_model("large-v3", download_root=WHISPER_MODEL_PATH).to(device)
                    chunk_text = model2.transcribe(chunk_path, language="vi")["text"]

                # Lưu từng đoạn transcript riêng
                chunk_txt_path = chunk_path.replace(".wav", ".txt")
                with open(chunk_txt_path, "w", encoding="utf-8") as f:
                    f.write(chunk_text.strip())

                # Gộp full transcript
                full_transcript += chunk_text.strip() + " "

                # (Tùy chọn) dọn file tạm cho nhẹ ổ:
                try:
                    os.remove(chunk_path)
                except Exception:
                    pass

                del result
                gc.collect()

            except Exception as e:
                print(f"❌ Lỗi khi xử lý đoạn {chunk_path}: {e}")
                continue

        return full_transcript.strip()
    else:
        print("📝 File ngắn, xử lý nguyên bản...")
        result = model.transcribe(audio_path, language="vi")
        transcript = result["text"]

        if detect_repetition(transcript):
            print("🔄 Lỗi lặp từ, chuyển sang model large-v3...")
            if 'model2' not in globals() or model2 is None:
                model2 = whisper.load_model("large-v3", download_root=WHISPER_MODEL_PATH).to(device)
            transcript = model2.transcribe(audio_path, language="vi")["text"]

        # Lưu bản đơn thành .txt riêng
        txt_path = audio_path.replace(".wav", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(transcript.strip())

        return transcript.strip()
    
def send_to_chatgpt(driver, text):
    """Gửi nội dung đến ChatGPT, lấy kết quả ngay khi ChatGPT dừng gõ, kiểm tra 30 giây để cập nhật nếu có thay đổi."""
    try:
        prompt = f"đặt tiêu đề cho video có nội dung là: \n\n{text}"

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
        
def process_video(index, link, doc):
    video_number, link = clean_link(link)
    # Làm sạch link: bỏ dấu nháy bao quanh nếu có
    link = link.strip().strip('"').strip("'")
    video_number = video_number if video_number is not None else index
    print(f"\n🎥 Đang xử lý video {video_number}: {link}")

    # ✅ Kiểm tra xem link là file path local hay URL
    is_local_file = os.path.exists(link) and os.path.isfile(link)

    # Heuristic bổ sung: nếu là chuỗi kiểu đường dẫn Windows và là file media, coi là local
    if not is_local_file:
        try:
            if re.match(r'^[A-Za-z]:\\', link) and link.lower().endswith((
                '.mp4', '.mov', '.mkv', '.avi', '.wav', '.mp3'
            )):
                is_local_file = True
        except Exception:
            pass

    if is_local_file:
        print(f"📁 Phát hiện file local: {link}")
        # Xử lý video local
        title = os.path.splitext(os.path.basename(link))[0]
        video_path = link
        audio_filename = f"audio_{video_number}.wav"
        audio_path = os.path.join(OUTPUT_VIDEO_DIR, audio_filename)
    else:
        print(f"🌐 Phát hiện URL online: {link}")
        # Xử lý video online
        checklinktiktok = 1 if is_tiktok_link(link) else 0
        print(f"{link} -> TikTok: {checklinktiktok}")
        
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

    transcript = transcribe_whisper(audio_path)  # Đảm bảo transcript được tạo riêng cho từng video
    # Lưu transcript vào file TXT theo số thứ tự video
    transcript_filename = f"transcript_{video_number}.txt"
    transcript_path = os.path.join(OUTPUT_VIDEO_DIR, transcript_filename)
    with open(transcript_path, "w", encoding="utf-8") as f:
        if transcript is None:
            print("⚠ Không có transcript, bỏ qua xử lý văn bản.")
            transcript = ""
     
        formatted_transcript = transcript
        f.write(formatted_transcript)

    print(f"💾 Đã lưu transcript vào: {transcript_path}")

    para = doc.add_paragraph()
    run = para.add_run(f"{video_number}. {link}")
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.size = Pt(11)  # tùy chỉnh
   

    if transcript:  # Chỉ thêm nội dung nếu có transcript
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

def process_video_local(index, video_path, doc):
    video_number = index
    title = os.path.splitext(os.path.basename(video_path))[0]
    audio_filename = f"audio_{video_number}.wav"
    audio_path = os.path.join(OUTPUT_VIDEO_DIR, audio_filename)

    if not extract_audio(video_path, audio_path):
        return

    transcript = transcribe_whisper(audio_path)

    para = doc.add_paragraph()
    run = para.add_run(f"{video_number}. {video_path}")
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.size = Pt(11)
    doc.add_paragraph(f"Tiêu đề: {title}")
    doc.add_paragraph(f"Nội dung:\n{transcript if transcript else '(Không thể nhận diện)'}")
    doc.add_paragraph("=" * 40)

    doc.save(OUTPUT_WORD_FILE)

def process_videos():
    if os.path.exists(OUTPUT_WORD_FILE):
        doc = Document(OUTPUT_WORD_FILE)
    else:
        doc = Document()
        doc.save(OUTPUT_WORD_FILE)

    # driver = init_firefox()

    if USE_LINKS_FROM_FILE:
        print("🔗 Đang sử dụng danh sách LINK để tải video...")
        with open(LINKS_FILE, "r", encoding="utf-8") as file:
            links = [line.strip() for line in file.readlines() if line.strip()]
        for idx, link in enumerate(links, start=1):
            print(f"🔄 Đang xử lý video {idx}/{len(links)} từ LINK...")
            process_video(idx, link, doc)
    else:
        print("📁 Đang sử dụng VIDEO CÓ SẴN trong thư mục local...")
        video_files = [f for f in os.listdir(LOCAL_VIDEO_DIR) if f.endswith(".mp4")]
        for idx, video_file in enumerate(video_files, start=1):
            video_path = os.path.join(LOCAL_VIDEO_DIR, video_file)
            print(f"🎥 Đang xử lý video local {idx}/{len(video_files)}: {video_path}")
            process_video_local(idx, video_path, doc)

    print("🎉 Hoàn thành tất cả video!")

if __name__ == "__main__":
    process_videos()
