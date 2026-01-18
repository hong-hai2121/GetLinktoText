# ============================================================
# === Phiên bản cải tiến: Dịch file .SRT bằng ChatGPT tự động
# - Tự lưu tiến độ (.progress)
# - Tự resume khi chạy lại
# - Tự chuyển file gốc sang thư mục "old srt" sau khi hoàn tất
# ============================================================

import os
import time
import re
import random
import sys
import shutil
import json
import subprocess
from pathlib import Path
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ======== Cấu hình âm thanh cảnh báo ========
try:
    import winsound
    def beep(times=5, freq=1000, dur=500):
        for _ in range(times):
            try:
                winsound.Beep(freq, dur)
            except Exception:
                pass
            time.sleep(0.2)
except Exception:
    def beep(times=5, freq=1000, dur=500):
        pass  # Không có âm thanh trên hệ khác

# ======== Import đường dẫn profile Firefox ========
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from profiles_config import FIREFOX_PROFILE_PATH

# ======== Cấu hình chính ========
SRT_INPUT_DIR = "SourceTruyen/dSRT"       # Thư mục chứa file gốc
OUTPUT_DIR = "SourceTruyen/Outputs"        # Thư mục lưu file dịch
OLD_SRT_DIR = "SourceTruyen/old srt"       # Nơi lưu file gốc sau khi hoàn tất

GECKODRIVER_PATH = r"D:\\Python\\GetLinktoText\\geckodriver.exe"
CHATGPT_URL = "https://chatgpt.com/"

GROUP_SIZE = 60
START_BLOCK_INDEX = 0       # Mặc định (không cần chỉnh, sẽ được override khi resume)
END_BLOCK_INDEX = None      #  None  
SEND_INSTRUCTION_BEFORE = True
INSTRUCTION_MODE = "xianxia"
STOP_ON_MISSING = True
RESPONSE_TIMEOUT = 180
FIREFOX_RESTART_WAIT = 15

# ======== Hướng dẫn dịch (instruction) ========
INSTRUCTION_FIRST = (
    "Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt.\n"
    "Mỗi đoạn được đánh dấu bằng B[x]. Hãy dịch theo các yêu cầu sau:\n\n"
    "- Giữ bối cảnh tu tiên cổ đại nhưng dùng từ dễ hiểu, tự nhiên với người Việt hiện đại; ưu tiên câu ngắn, rõ ràng.\n"
    "- Đây là văn bản dùng để đọc TTS: không thêm ký tự thừa, không chèn biểu tượng, không tự ý xuống dòng giữa câu.\n"
    "- Tên nhân vật, tông môn, cảnh giới, công pháp, pháp bảo, địa danh, chiêu thức... giữ nguyên âm Hán-Việt (ví dụ: 老秦 -> Lão Tần), không Việt hóa tên riêng.\n"
    "- Các khái niệm tu luyện có thể dùng Hán-Việt nhưng trong mỗi câu chỉ nên có tối đa 1–2 từ Hán-Việt “nặng”, còn lại ưu tiên tiếng Việt phổ thông để người nghe dễ hiểu.\n"
    "- Phân biệt đúng ngữ cảnh xưng hô; giữ đúng vai vế và nhất quán trong cùng một mối quan hệ (sư phụ – đệ tử, sư huynh – sư muội, tiền bối – vãn bối, v.v.).\n"
    "- Hội thoại: dịch đúng từng lời, giữ rõ ai đang nói và ngữ khí phù hợp bối cảnh.\n"
    "- Có thể tách một câu tiếng Trung dài thành 2–3 câu tiếng Việt ngắn hơn cho dễ hiểu, nhưng không được thêm hoặc bớt ý nghĩa.\n"
    "- Mỗi block B[x] nhận vào phải được trả lại thành đúng một dòng, không tách thành nhiều block mới.\n"
    "- Dịch sát nghĩa, không thêm thắt nội dung, giữ nguyên thứ tự các block.\n"
    "- Mỗi block được trả lời trên 1 hàng riêng biệt; trả lại đúng số block tương ứng với đầu vào (không gộp, không thiếu, không thừa, không tương tác thêm với tôi).\n"
    "- Suy nghĩ kỹ trước khi trả lời để bản dịch mạch lạc, dễ nghe và chính xác.\n"
)

INSTRUCTION_FIRST_AnhViet = (
    "Sau đây tôi sẽ gửi các đoạn văn tiếng anh cần dịch sang tiếng Việt. "
    "Mỗi đoạn được đánh dấu bằng B[x]. Hãy dịch theo các yêu cầu sau:\n\n"
    "- Đây là văn bản dùng để đọc TTS: không thêm ký tự thừa, không chèn biểu tượng, không tự ý xuống dòng giữa câu.\n"
    "- Mỗi block B[x] nhận vào phải được trả lại thành đúng một dòng, không tách thành nhiều block mới.\n"
    "- Dịch sát nghĩa, không thêm thắt nội dung, giữ nguyên thứ tự các block.\n"
    "- Mỗi block được trả lời trên 1 hàng riêng biệt; trả lại đúng số block tương ứng với đầu vào (không gộp, không thiếu, không thừa, không tương tác thêm với tôi).\n"
    "- Suy nghĩ kỹ trước khi trả lời để bản dịch mạch lạc, dễ nghe và chính xác.\n"
)
INSTRUCTION_FIRST_Darama = (
    "Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt. "
    "Câu dịch không quá dài cũng không quá ngắn so với văn gốc; dùng để đọc TTS (không thêm ký tự lạ/emoji/markdown).\n\n"
    "Định dạng block:\n"
    "- Mỗi block có tiêu đề: B{GLOBAL_INDEX}. Ví dụ: B216\n"
    "- Bạn PHẢI trả lại từng block theo đúng tiêu đề đó, đúng thứ tự đã nhận.\n"
    "- Không gộp, không bỏ; số lượng block trả về phải đúng bằng số header đã nhận.\n\n"
    "- Yêu cầu dịch (drama hiện đại – trùng sinh):\n"
    "- Từ ngắn gọn, dễ hiểu; nhịp cảm xúc căng; không dài quá đáng.\n"
    "- Tên riêng sang âm Hán–Việt; không pinyin; không Việt hoá tuỳ tiện.\n"
    "- Phân biệt đúng xưng hô gia đình – xã hội; nhất quán giữa kiếp trước/kiếp này.\n"
    "- Khi gặp từ xưng hô hoặc thân tộc (như 爸爸, 妈妈, 叔叔, 阿姨...), hãy dịch theo quan hệ gia đình Việt.\n"
    "- Dịch sát nghĩa, giữ nguyên trật tự; không bình luận.\n"
    "- Mỗi block một dòng; không gộp, không thiếu; không tương tác với tôi.\n"
    "- Suy nghĩ lâu hơn để trả lời chính xác hơn."
)


# ======== Cấu hình thư mục lưu tiến độ ========
PROGRESS_DIR = Path("SourceTruyen/.progress")
PROGRESS_DIR.mkdir(parents=True, exist_ok=True)

def _progress_path(input_path: str) -> Path:
    """Tạo đường dẫn file tiến độ (.json) tương ứng"""
    name = Path(input_path).name + ".json"
    return PROGRESS_DIR / name

def save_progress(input_path: str, next_index: int):
    """Lưu tiến độ (block sắp dịch tiếp theo)"""
    _progress_path(input_path).write_text(json.dumps(
        {"next_index": next_index}, ensure_ascii=False), encoding="utf-8")

def load_progress(input_path: str) -> int | None:
    """Đọc tiến độ cũ (nếu có)"""
    p = _progress_path(input_path)
    if p.exists():
        try:
            return int(json.loads(p.read_text(encoding="utf-8"))["next_index"])
        except Exception:
            return None
    return None

def clear_progress(input_path: str):
    """Xóa file tiến độ sau khi dịch xong"""
    p = _progress_path(input_path)
    if p.exists():
        p.unlink()

# ======== Hàm tạo file không ghi đè ========
def get_available_filename(base_path):
    if not os.path.exists(base_path):
        return base_path
    base, ext = os.path.splitext(base_path)
    counter = 1
    while True:
        new_path = f"{base}.{counter}{ext}"
        if not os.path.exists(new_path):
            return new_path
        counter += 1

# ======== Chuyển file gốc vào thư mục lưu trữ ========
def move_to_archive(src_path, archive_dir):
    os.makedirs(archive_dir, exist_ok=True)
    base = os.path.basename(src_path)
    dst = os.path.join(archive_dir, base)
    if os.path.exists(dst):
        name, ext = os.path.splitext(base)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = os.path.join(archive_dir, f"{name}.{stamp}{ext}")
    shutil.move(src_path, dst)
    return dst

# ======== Kiểm tra block thiếu nội dung ========
def is_missing_block_content(lines):
    if not lines:
        return True
    cleaned = []
    for s in lines:
        if s is None:
            continue
        s = re.sub(r"^\s*[:：\-\–\—•·]\s*", "", s).strip()
        cleaned.append(s)
    text = " ".join(cleaned).strip()
    if not text:
        return True
    if re.fullmatch(r"[.\u2026\s]+", text):
        return True
    if text in {"...", "…"}:
        return True
    return False


# ============================================================
# ================== CLASS TRANSLATOR =========================
# ============================================================

class Translator:
    def __init__(self):
        self.send_count = 0
        self.instruction_sent = False
        self.driver = self.init_driver()

    # ===== Khởi tạo Firefox driver =====
    def init_driver(self):
        try:
            return self._create_driver()
        except (TimeoutException, WebDriverException) as exc:
            print(f"⚠️ Không thể khởi tạo Firefox hoặc không thấy ô nhập: {exc}")
            self.restart_firefox_via_cmd()
            return self._create_driver()

    def _create_driver(self):
        options = Options()
        options.add_argument("-profile")
        options.add_argument(FIREFOX_PROFILE_PATH)
        service = Service(GECKODRIVER_PATH)
        driver = webdriver.Firefox(service=service, options=options)
        driver.get(CHATGPT_URL)
        print("🚀 Trình duyệt đã mở và điều hướng đến ChatGPT.")
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )
        return driver

    def restart_firefox_via_cmd(self):
        self._close_driver()
        print("🔁 Đang khởi động lại Firefox bằng lệnh CMD...")
        self._start_firefox_cmd()
        time.sleep(FIREFOX_RESTART_WAIT)
        self._kill_firefox_cmd()
        time.sleep(3)
        self._start_firefox_cmd()
        time.sleep(FIREFOX_RESTART_WAIT)
        self._kill_firefox_cmd()
        time.sleep(3)

    def _start_firefox_cmd(self):
        try:
            if os.name == "nt":
                subprocess.Popen(["cmd", "/c", "start", "", "firefox"], shell=False)
            else:
                subprocess.Popen(["firefox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _kill_firefox_cmd(self):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/IM", "firefox.exe", "/F"], check=False)
            else:
                subprocess.run(["pkill", "-f", "firefox"], check=False)
        except Exception:
            pass

    def _close_driver(self):
        if not self.driver:
            return
        try:
            self.driver.quit()
        except Exception:
            pass
        self.driver = None

    # ===== Gửi tin nhắn vào ChatGPT =====
    def send_message(self, text):
        try:
            textarea = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
            )
            textarea.clear()
            textarea.send_keys(text)
            time.sleep(random.uniform(5, 15))
            textarea.send_keys("\ue007")  # Enter
        except (TimeoutException, WebDriverException) as exc:
            print(f"⚠️ Không thấy ô nhập để gửi câu hỏi: {exc}")
            self.restart_firefox_via_cmd()
            self.driver = self._create_driver()
            textarea = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
            )
            textarea.clear()
            textarea.send_keys(text)
            time.sleep(random.uniform(5, 15))
            textarea.send_keys("\ue007")  # Enter

    # ===== Chờ ChatGPT trả lời xong =====
    def wait_until_complete(self):
        WebDriverWait(self.driver, RESPONSE_TIMEOUT).until_not(
            EC.presence_of_element_located((By.XPATH, "//button[@data-testid='stop-button']"))
        )

    # ===== Chọn hướng dẫn phù hợp =====
    def get_instruction_text(self):
        return INSTRUCTION_FIRST_Darama if INSTRUCTION_MODE.lower() == "drama" else INSTRUCTION_FIRST

    # ===== Làm sạch text phản hồi =====
    def _sanitize_reply_text(self, s: str) -> str:
        if not s:
            return ""
        s = re.sub(r"[\u200B\u200C\u200D\u2060\uFEFF\u00A0]", "", s)
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        return s

    # ===== Đọc phản hồi cuối cùng từ ChatGPT =====
    def _read_last_assistant_text(self):
        messages = self.driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        if not messages:
            return ""
        last = messages[-1]
        try:
            for _ in range(3):
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'end'});", last)
                time.sleep(0.2)
            buttons = last.find_elements(By.XPATH, ".//button[normalize-space()='Show more' or normalize-space()='Xem thêm']")
            for b in buttons:
                try:
                    self.driver.execute_script("arguments[0].click();", b)
                    time.sleep(0.2)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            txt = last.get_attribute("innerText")
            return txt if txt else (last.text or "")
        except Exception:
            return last.text or ""

    # ===== Gửi hướng dẫn trước khi dịch =====
    def ensure_instruction_sent(self):
        if self.instruction_sent or not SEND_INSTRUCTION_BEFORE:
            return
        print("📢 Gửi yêu cầu hướng dẫn ban đầu…")
        self.send_message(self.get_instruction_text())
        self.wait_until_complete()
        self.instruction_sent = True

    # ===== Đọc từng block trong file .srt =====
    def read_srt_blocks(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()]
        blocks, block = [], []
        for line in lines:
            if line == "":
                if block:
                    blocks.append(block)
                    block = []
            else:
                block.append(line)
        if block:
            blocks.append(block)
        return blocks

    # ===== Ghi kết quả bản dịch =====
    def write_translated_blocks(self, original_blocks, translated_lines, output_path, offset):
        with open(output_path, "a", encoding="utf-8") as f:
            for j, trans_lines in enumerate(translated_lines):
                block = original_blocks[j]
                if len(block) < 2:
                    continue
                index = offset + j + 1
                timestamp = block[1]
                f.write(f"{index}\n{timestamp}\n")
                for line in trans_lines:
                    f.write(f"{line}\n")
                f.write("\n")

    # ===== Tạo prompt gửi đến GPT =====
    def prepare_prompt(self, group, global_offset):
        line_counts = []
        marked_lines = []
        for k, block in enumerate(group):
            lines = block[2:] if len(block) >= 3 else []
            line_counts.append(len(lines))
            global_idx_1b = global_offset + k + 1
            marked_lines.append(f"B{global_idx_1b}\n")
            marked_lines.extend(lines)
        guard = (
            "\n\n[LƯU Ý]\n"
            "- Trả lại đúng số block, theo thứ tự B{GLOBAL_INDEX} như đã gửi.\n"
            "- Mỗi block một dòng duy nhất.\n"
        )
        return line_counts, "\n".join(marked_lines) + guard

    # ===== Khi gặp lỗi nghiêm trọng =====
    def stop_after_beep(self, message="⛔ Dừng do lỗi.", times=5, current_input=None, next_index=None):
        if current_input and next_index is not None:
            try:
                save_progress(current_input, next_index)
            except Exception:
                pass
        beep(times=times)
        print(message)
        try:
            self.driver.quit()
        except Exception:
            pass
        raise SystemExit(1)

    # ===== Gửi prompt đến ChatGPT và đọc kết quả =====
    def send_to_gpt(self, prompt, line_counts, expected_b_numbers, input_path, i):
        from collections import defaultdict
        self.send_count += 1
        self.current_input = input_path
        self.current_index = i

        try:
            self.send_message(prompt)
            self.wait_until_complete()
        except TimeoutException:
            print("⚠️ GPT không phản hồi trong 3 phút, thử khởi động lại Firefox...")
            self.restart_firefox_via_cmd()
            self.driver = self._create_driver()
            self.send_message(prompt)
            self.wait_until_complete()

        MAX_RETRY = 3
        retry_sleep = 5
        header_re = re.compile(r"^\s*B\s*(\d+)\s*[:：.\-–—\)]?\s*(.*)$", re.IGNORECASE)

        def parse_reply(text):
            text = self._sanitize_reply_text(text or "")
            reply_lines = [ln.rstrip("\r") for ln in text.splitlines()]
            blocks = defaultdict(list)
            order = []
            current_b = None
            for line in reply_lines:
                m = header_re.match(line)
                if m:
                    current_b = int(m.group(1))
                    order.append(current_b)
                    content = m.group(2)
                    if content:
                        blocks[current_b].append(content)
                elif current_b is not None:
                    blocks[current_b].append(line)
            return blocks, order

        full = self._read_last_assistant_text().strip()
        blocks_map, order = parse_reply(full)
        expected_count = len(expected_b_numbers)
        attempt = 0

        while len(order) < expected_count and attempt < MAX_RETRY:
            time.sleep(retry_sleep)
            newer = self._read_last_assistant_text().strip()
            if len(newer) > len(full):
                full = newer
                blocks_map, order = parse_reply(full)
            attempt += 1

        # Kiểm tra lỗi thiếu block
        if len(order) < expected_count:
            self.stop_after_beep(
                message=f"⛔ Số block gửi: {expected_count}, nhận: {len(order)}",
                times=3, current_input=input_path, next_index=i
            )

        result = [blocks_map.get(bnum, []) for bnum in expected_b_numbers]

        def _has_content(lines):
            return any((line or "").strip() for line in lines)

        received_valid = sum(1 for lines in result if _has_content(lines))
        if received_valid != expected_count:
            self.stop_after_beep(
                message=f"⛔ Nhận được {received_valid}/{expected_count} block hợp lệ.",
                times=3, current_input=input_path, next_index=i
            )
        return result

    # ===== Dịch từng file =====
    def translate_file(self, input_path, output_path, start_index=0):
        self.ensure_instruction_sent()

        blocks = self.read_srt_blocks(input_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if os.path.exists(output_path):
            os.remove(output_path)

        total_blocks = len(blocks)
        print(f"📚 Tổng block: {total_blocks}")

        i = max(start_index or 0, 0)
        end_limit = END_BLOCK_INDEX if END_BLOCK_INDEX else total_blocks
        end_limit = min(end_limit, total_blocks)

        if i >= end_limit:
            print("⚠️ Phạm vi xử lý rỗng. Kiểm tra cấu hình.")
            return

        group_size = GROUP_SIZE
        batch_start = i

        while i < end_limit:
            save_progress(input_path, i)  # lưu tiến độ trước khi gửi batch
            end_idx = min(i + group_size, end_limit)
            group = blocks[i:end_idx]
            print(f"   ➤ Gửi block {i+1} → {end_idx}")

            expected_b_numbers = [i + k + 1 for k in range(len(group))]
            line_counts, prompt = self.prepare_prompt(group, global_offset=i)
            result_group = self.send_to_gpt(prompt, line_counts, expected_b_numbers, input_path, i)

            # Kiểm tra thiếu
            missing_indices = [idx for idx, lines in enumerate(result_group) if is_missing_block_content(lines)]
            if missing_indices and STOP_ON_MISSING:
                miss_nums = [expected_b_numbers[idx] for idx in missing_indices]
                self.stop_after_beep(
                    f"⛔ Thiếu nội dung ở block: {miss_nums}", current_input=input_path, next_index=i
                )

            # Ghi file dịch
            self.write_translated_blocks(group, result_group, output_path, i)
            print(f"💾 Đã lưu block {i+1} → {i+len(result_group)}")

            i += len(result_group)
            save_progress(input_path, i)  # lưu sau batch
            if (i - batch_start) >= 500:
                print("🕐 Nghỉ ngắn sau 500 block.")
                batch_start = i

    # ===== Dịch tất cả file trong thư mục =====
    def run(self):
        first_file = True  # đánh dấu file đầu tiên

        for filename in os.listdir(SRT_INPUT_DIR):
            if not filename.endswith(".srt"):
                continue

            print(f"\n🔄 Xử lý file: {filename}")
            input_path = os.path.join(SRT_INPUT_DIR, filename)
            base_output_path = os.path.join(OUTPUT_DIR, filename.replace(".srt", "_translated.srt"))
            output_path = get_available_filename(base_output_path)

            # --- Lấy tiến độ hoặc START_BLOCK_INDEX ---
            resume = load_progress(input_path)

            # Nếu file đầu tiên thì dùng START_BLOCK_INDEX, file sau luôn từ 0
            if resume is not None:
                start_index = resume
                source = "progress"
            elif first_file:
                start_index = START_BLOCK_INDEX
                source = "START_BLOCK_INDEX"
            else:
                start_index = 0
                source = "0 (mặc định cho file tiếp theo)"

            print(f"▶️ Bắt đầu từ block: {start_index} (nguồn: {source})")

            # --- Chạy dịch ---
            self.translate_file(input_path, output_path, start_index)

            # --- Di chuyển file gốc nếu dịch xong ---
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                try:
                    archived = move_to_archive(input_path, OLD_SRT_DIR)
                    print(f"📦 Đã chuyển file gốc vào lưu trữ: {archived}")
                except Exception as e:
                    print(f"⚠️ Không thể chuyển file gốc: {e}")
            else:
                print("⚠️ File output rỗng, không chuyển sang lưu trữ.")

            clear_progress(input_path)
            first_file = False  # các file sau sẽ reset về 0

        self.driver.quit()
        print("\n🎉 Hoàn tất tất cả file.")

# ======== Chạy chương trình ========
if __name__ == "__main__":
    Translator().run()
