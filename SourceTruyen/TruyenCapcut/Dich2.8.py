# === Nhúng thư viện cần thiết ===
import os
import time
import re
import random
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === Cấu hình cố định ===
SRT_INPUT_DIR = "SourceTruyen/aSRT"  # Thư mục chứa các file .srt gốc
OUTPUT_DIR = "SourceTruyen/Outputs"  # Thư mục lưu file dịch

# ==== Danh sách Hồ Sơ ====== #
profiles = {
    "Profile01": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\jf2te79d.default-release",
    "Profile02": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\qo4o211a.5",
    "Profile03": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\nmfygyzt.2",
    "ProfileGPT": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\wyo2tlat.GPT Chị Thảo"
}

# Chọn profile cần dùng
selected_profile = profiles["Profile01"]  # hoặc "Profile01", "Profile02"...

FIREFOX_PROFILE_PATH = selected_profile
GECKODRIVER_PATH = r"D:\\Python\\GetLinktoText\\geckodriver.exe"  # Đường dẫn geckodriver
CHATGPT_URL = "https://chatgpt.com/"  # Trang ChatGPT

GROUP_SIZE = 14           # Số block gửi mỗi lượt
OVERLAP_STEP = 2         # Nếu GPT trả thiếu → lùi về n block
MIN_GROUP_SIZE = 2       # Không chia nhỏ hơn n block khi lỗi
START_BLOCK_INDEX = 0  # Vị trí bắt đầu xử lý trong file
END_BLOCK_INDEX = None   # Vị trí kết thúc (None = chạy đến cuối)

# Prompt hướng dẫn GPT (chỉ chèn mỗi 10 lần gửi)
INSTRUCTION_FIRST = (
    "Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt. "
    "Mỗi đoạn được đánh dấu bằng ###BLOCK-x-LINES-y###. Hãy dịch:\n\n"
    "- Theo văn phong tu tiên cổ đại, dùng từ ngắn ngọn nhưng dễ hiểu khống quá dài so với văn bản gốc.\n"
    "đây là văn bản dùng để đọc TTS không thêm kí tự lung tung vào"
    "- Giữ nguyên tên nhân vật, tông môn, cảnh giới, chiêu thức, v.v... bằng chữ Hán Việt. "
    "Không phiên âm hoặc Việt hóa tên riêng.\n"
    "- Phân biệt đúng ngữ cảnh xưng hô (ví dụ:  tỷ - đệ, sư phụ - đệ tử, ...), "
    "đảm bảo dịch đúng ngôi xưng theo từng đoạn hội thoại.\n"
    "- Nếu nhân vật A đang gọi nhân vật B là 'cha', 'sư phụ', 'sư tỷ',... thì phải giữ đúng ý và quan hệ. "
    "Không dịch nhầm thành 'cô ấy', 'anh ta' hoặc lẫn vai trò.\n"
    "- Nếu có hội thoại, dịch đúng từng lời nói và ngữ khí, có thể dùng từ như 'ngươi', 'ta', 'lão phu', "
    "'bổn tọa', 'tiểu tử', 'đạo hữu', v.v. nếu phù hợp với bối cảnh.\n"
    "- Dịch sát nghĩa, không thêm thắt nội dung. Giữ nguyên trật tự đoạn.\n"
    "- Trả lại đúng số đoạn tương ứng với các block đã nhận. Không gộp, không thiếu, không tương tác với tôi.\n"
)

# === Nếu base_path đã tồn tại, thêm hậu tố .1, .2, ... để tránh ghi đè. ===
def get_available_filename(base_path):
    """
    Nếu base_path đã tồn tại, thêm hậu tố .1, .2, ... để tránh ghi đè.
    """
    if not os.path.exists(base_path):
        return base_path

    base, ext = os.path.splitext(base_path)
    counter = 1
    while True:
        new_path = f"{base}.{counter}{ext}"
        if not os.path.exists(new_path):
            return new_path
        counter += 1

# === Định nghĩa lớp dịch file SRT bằng ChatGPT ===
class Translator:
    def __init__(self):
        self.send_count = 0           # Số lần đã gửi prompt
        self.driver = self.init_driver()  # Mở trình duyệt

    # === Khởi tạo Firefox driver và điều hướng đến ChatGPT ===
    def init_driver(self):
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

    # === Đọc từng block trong file .srt ===
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

    # === Ghi kết quả bản dịch vào file mới ===
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

    # === Tạo prompt gồm các block đánh dấu chuẩn cho GPT ===
    def prepare_prompt(self, group):
        line_counts = []
        marked_texts = []
        for i, block in enumerate(group):
            lines = block[2:] if len(block) >= 3 else []
            line_counts.append(len(lines))
            marked_texts.append(f"###BLOCK-{i+1}-LINES-{len(lines)}###\n")
            marked_texts.extend(lines)
        return line_counts, "\n".join(marked_texts)

    # === Gửi prompt đến ChatGPT, phân tích và trả kết quả ===
    def send_to_gpt(self, prompt, line_counts):
        self.send_count += 1

        textarea = WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )
        textarea.clear()

        if self.send_count % 10 == 1:
            prompt = INSTRUCTION_FIRST + "\n" + prompt

        textarea.send_keys(prompt)
        time.sleep(random.uniform(3, 5))
        textarea.send_keys("\ue007")  # Gửi prompt (phím Enter)

        WebDriverWait(self.driver, 300).until_not(
            EC.presence_of_element_located((By.XPATH, "//button[@data-testid='stop-button']"))
        )

        messages = self.driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        if not messages:
            return None

        reply = messages[-1].text.strip().splitlines()
        
        # Nếu phản hồi chứa dấu hiệu lỗi giới hạn GPT-4
        full_reply_text = "\n".join(reply)
        if "bạn đã đạt giới hạn sử dụng" in full_reply_text.lower() or "Thử lại" in full_reply_text:
            print("🚫 GPT đã đạt giới hạn sử dụng GPT-4. Dừng chương trình.")
            exit(1)

        # Tách từng block trong phản hồi
        block_map, current_block = {}, None
        for line in reply:
            match = re.match(r"(###BLOCK-\d+-LINES-\d+###)(.*)", line)
            if match:
                marker, content = match.groups()
                current_block = marker
                block_map[current_block] = []
                if content.strip():
                    block_map[current_block].append(content.strip())
            elif current_block:
                block_map[current_block].append(line)

        # Gom kết quả theo block
        result = []
        for i, expected_lines in enumerate(line_counts):
            header = f"###BLOCK-{i+1}-LINES-{expected_lines}###"
            if header in block_map:
                result.append(block_map[header])
            else:
                if len(line_counts) == 1:
                    # Chỉ gửi 1 block mà không có header → lấy toàn bộ phản hồi
                    print("ℹ️ GPT không trả header, nhưng chỉ có 1 block → lấy toàn bộ làm kết quả.")
                    cleaned_reply = [line for line in reply if line.strip()]
                    result.append(cleaned_reply)
                else:
                    print(f"⚠️ Thiếu block: {header}")
                    return result  # fallback
        return result

    # === Generator chia block động từng nhóm n block ===
    def generate_groups(self, blocks, start, group_size):
        i = start
        while i < len(blocks):
            yield i, blocks[i:i+group_size]
            i += group_size

    # === Dịch từng file .srt một ===
    def translate_file(self, input_path, output_path):
        blocks = self.read_srt_blocks(input_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if os.path.exists(output_path):
            os.remove(output_path)

        print(f"📚 Tổng block: {len(blocks)}")
        total_blocks = len(blocks)

        i = START_BLOCK_INDEX
        group_size = GROUP_SIZE
        batch_start = i

        while i < total_blocks:
            end_idx = min(i + group_size, total_blocks)
            group = blocks[i:end_idx]
            print(f"   ➤ Gửi block {i+1} → {end_idx}")

            line_counts, prompt = self.prepare_prompt(group)
            result_group = self.send_to_gpt(prompt, line_counts)

            # Nếu thiếu block → không lưu, fallback từng block
            if (not result_group) or (len(result_group) != len(group)):
                print("❌ GPT trả thiếu block, fallback từng block lẻ.")
                fallback_result = []
                for idx, block in enumerate(group):
                    _, mini_prompt = self.prepare_prompt([block])
                    res = self.send_to_gpt(mini_prompt, [len(block[2:])])
                    if res:
                        fallback_result.append(res[0])
                    else:
                        print(f"⚠️ Thiếu luôn block {i + idx + 1}, đánh dấu là BỊ THIẾU.")
                        fallback_result.append(["(BLOCK BỊ THIẾU)"])
                result_group = fallback_result

            self.write_translated_blocks(group, result_group, output_path, i)
            print(f"💾 Đã lưu block {i+1} → {i+len(result_group)}")


            i += len(result_group)
            group_size = GROUP_SIZE

            # ======= Kiểm tra nếu đã gửi xong 1 batch 500 block =======
            if (i - batch_start) >= 500:
                print("🕐 Đã xử lý 500 block – nghỉ 5 phút để tránh spam.")
                #time.sleep(300)  # 5 phút = 300 giây
                batch_start = i  # cập nhật lại mốc bắt đầu batch tiếp theo


    # === Dịch tất cả các file .srt trong thư mục ===
    def run(self):
        for filename in os.listdir(SRT_INPUT_DIR):
            if not filename.endswith(".srt"):
                continue
            print(f"\n🔄 Xử lý file: {filename}")
            input_path = os.path.join(SRT_INPUT_DIR, filename)
            base_output_path = os.path.join(OUTPUT_DIR, filename.replace(".srt", "_translated.srt"))
            output_path = get_available_filename(base_output_path)
            self.translate_file(input_path, output_path)

        self.driver.quit()
        print("\n🎉 Đã hoàn tất tất cả file.")
        
# === Bắt đầu chương trình ===
if __name__ == "__main__":
    Translator().run()
