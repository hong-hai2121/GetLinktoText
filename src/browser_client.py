import subprocess
import threading
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src import config
from src.notifications import play_sound

# Global driver dùng chung từ khi khởi động
global_driver = None

DRIVER_LOCK = threading.Lock()
FIREFOX_INIT_EVENT = threading.Event()
FIREFOX_INIT_IN_PROGRESS = False
FIREFOX_CMD_PATH = r"C:\Program Files\Mozilla Firefox\firefox.exe"
FIREFOX_CMD_URL = "https://chatgpt.com/"
FIREFOX_CMD_WAIT_SECONDS = 15


def is_driver_alive(drv):
    try:
        if drv is None:
            return False
        _ = drv.current_url
        return True
    except Exception:
        return False


def init_firefox():
    """Khởi tạo trình duyệt Firefox với Selenium và mở ChatGPT."""
    options = FirefoxOptions()
    options.add_argument("-profile")
    options.add_argument(f"{config.FIREFOX_PROFILE_PATH}")
    service = FirefoxService(executable_path=config.GECKODRIVER_PATH)
    driver = webdriver.Firefox(service=service, options=options)
    driver.get("https://chatgpt.com/")
    time.sleep(7)
    return driver


def restart_firefox():
    """Đóng Firefox hiện tại, mở bằng CMD 15s, tắt, rồi mở lại bằng Selenium."""
    global global_driver, FIREFOX_INIT_IN_PROGRESS

    with DRIVER_LOCK:
        FIREFOX_INIT_IN_PROGRESS = True
        FIREFOX_INIT_EVENT.clear()

    try:
        if global_driver is not None:
            try:
                print("🔴 Đang đóng Firefox...")
                try:
                    global_driver.quit()
                except Exception:
                    pass
                time.sleep(1)
            except Exception as e:
                print(f"⚠️ Lỗi khi đóng Firefox: {e}")
            finally:
                global_driver = None

        try:
            subprocess.run(["taskkill", "/F", "/IM", "firefox.exe"], timeout=2)
            time.sleep(2)
        except Exception:
            pass

        print("🧹 Đang mở Firefox bằng CMD trong 15 giây...")
        cmd_process = None
        try:
            cmd_process = subprocess.Popen([FIREFOX_CMD_PATH, FIREFOX_CMD_URL])
            time.sleep(FIREFOX_CMD_WAIT_SECONDS)
        except Exception as e:
            print(f"⚠️ Lỗi khi mở Firefox bằng CMD: {e}")
        finally:
            try:
                subprocess.run(["taskkill", "/F", "/IM", "firefox.exe"], timeout=4)
            except Exception:
                pass
            if cmd_process is not None:
                try:
                    cmd_process.wait(timeout=2)
                except Exception:
                    pass

        print("🌐 Đang mở Firefox mới bằng Selenium...")
        time.sleep(1)
        drv = init_firefox()

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
        with DRIVER_LOCK:
            FIREFOX_INIT_IN_PROGRESS = False
        FIREFOX_INIT_EVENT.set()


def get_video_title_tiktok(url, browser):
    """Lấy tiêu đề video bằng danh sách XPath."""
    try:
        browser.execute_script("window.open('about:blank', '_blank');")
        browser.switch_to.window(browser.window_handles[-1])
        browser.get(url)
        wait = WebDriverWait(browser, 8)
        xpaths = [
            "/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/div[2]/div[1]/div/h1",
            "/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/div[2]/div[1]/div/div[2]",
            "/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div/div[2]/div/div/div/div/div/div/div[2]/div[1]/div/div/div[2]/div/div/div[2]/span/div",
        ]
        for xpath in xpaths:
            try:
                title_element = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
                title = title_element.text.strip()
                print(f"✅ Tiêu đề video: {title}")
                browser.close()
                browser.switch_to.window(browser.window_handles[0])
                return title
            except Exception:
                print(f"⚠️ Không tìm thấy tiêu đề với XPath: {xpath}: ")

        print("❌ Không thể lấy tiêu đề với cả hai XPath.")
        browser.close()
        browser.switch_to.window(browser.window_handles[0])
        return "Không thể lấy tiêu đề"
    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề: {e}")
        play_sound("error")
        return "Không thể lấy tiêu đề"


def send_to_chatgpt(driver, text, mode="clean"):
    """Gửi nội dung đến ChatGPT.

    mode="clean": chỉnh sửa transcript.
    mode="title": gợi ý đặt tên video.
    mode="raw": gửi nguyên văn text (không tự thêm hướng dẫn).
    """
    try:
        if driver is None:
            print("❌ Lỗi: Driver là None, không thể gửi đến ChatGPT.")
            return None

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
                "không rút gọn hay thay đổi ý nghĩa, phù hợp với mô hình TTS, thay Bác sĩ x thành bác sĩ Hội\n\n"
                + text
            )

        try:
            textarea = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
            )
        except Exception as e:
            print(f"❌ Lỗi: Không tìm thấy ô nhập câu hỏi - {e}")
            print("💡 Kiểm tra xem ChatGPT có mở bình thường không, hoặc hãy khởi động lại Firefox.")
            return None

        initial_messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        initial_count = len(initial_messages)

        textarea.clear()
        textarea.send_keys(prompt)
        textarea.send_keys("\ue007")

        max_wait_time = 180
        check_interval = 5
        stable_time = 30
        stop_button_xpath = "//button[@data-testid='stop-button']"

        print("⌛ Đang chờ phản hồi từ ChatGPT (tối đa 3 phút)...")

        start_time = time.time()
        chatgpt_started_typing = False

        while time.time() - start_time < max_wait_time:
            stop_button = driver.find_elements(By.XPATH, stop_button_xpath)
            if stop_button:
                print("✅ ChatGPT bắt đầu phản hồi! Chuyển sang bước tiếp theo.")
                chatgpt_started_typing = True
                break
            time.sleep(check_interval)

        if not chatgpt_started_typing:
            print("❌ ChatGPT không phản hồi sau 3 phút, bỏ qua video này.")
            return None

        while True:
            time.sleep(check_interval)
            stop_button = driver.find_elements(By.XPATH, stop_button_xpath)

            if not stop_button:
                print("✅ ChatGPT đã dừng gõ. Lấy ngay nội dung hiện tại...")
                break

        retry_attempts = 3
        attempt = 0

        while attempt < retry_attempts:
            messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
            new_messages = messages[initial_count:]
            final_content = "\n".join([msg.text.strip() for msg in new_messages])

            if final_content.strip():
                print("✅ Đã nhận được nội dung từ GPT.")
                break
            attempt += 1
            print(
                f"⚠ Cảnh báo: Nội dung trống! Chờ thêm 30 giây để thử lại lần {attempt}/{retry_attempts}..."
            )
            time.sleep(30)

        print("📩 ChatGPT ĐÃ TRẢ LỜI XONG LẤY NỘI DUNG:")

        stable_counter = 0
        last_content = final_content

        while stable_counter < stable_time:
            time.sleep(check_interval)

            messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
            new_messages = messages[initial_count:]
            current_content = "\n".join([msg.text.strip() for msg in new_messages])

            if current_content == last_content:
                stable_counter += check_interval
                print(f"⚖ Nội dung không thay đổi, chờ thêm {stable_time - stable_counter}s để xác nhận...")
            else:
                stable_counter = 0
                print("🔄 Nội dung thay đổi, cập nhật lại!")
                last_content = current_content
                final_content = current_content

        if final_content:
            print("✅ Nội dung cuối cùng đã ổn định, trả về kết quả.")
            return final_content

        print("❌ Lỗi: Không lấy được phản hồi từ ChatGPT.")
        return None

    except Exception as e:
        print(f"❌ Lỗi khi gửi câu hỏi: {e}")
        return None
