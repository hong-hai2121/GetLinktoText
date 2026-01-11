# === Nhúng thư viện cần thiết ===
import os
import time
import re
import random
import winsound
import sys
import hashlib
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === Cấu hình cố định ===
SRT_INPUT_DIR = "SourceTruyen/aSRT"   # Thư mục chứa các file .srt gốc
OUTPUT_DIR = "SourceTruyen/Outputs"   # Thư mục lưu file dịch

# ==== Danh sách Hồ Sơ ====== #
profiles = {
    "Profile01": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\jf2te79d.default-release",
    "Profile02": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\qo4o211a.5", #
    "Profile03": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\nmfygyzt.2",
    "ProfileGPT": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\wyo2tlat.GPT Chị Thảo",
    "Profile05": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\42alfg11.4",
    "Profile06": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\mef4v4wh.6"
    
}
# Chọn profile cần dùng
selected_profile = profiles["Profile03"]  # hoặc "Profile01", "Profile02", ...

FIREFOX_PROFILE_PATH = selected_profile
GECKODRIVER_PATH = r"D:\\Python\\GetLinktoText\\geckodriver.exe"  # Đường dẫn geckodriver
CHATGPT_URL = "https://chatgpt.com/?model=gpt-5-thinking"        # Trang ChatGPT

GROUP_SIZE = 70            # Số block gửi mỗi lượt
MIN_GROUP_SIZE = 2         # Không chia nhỏ hơn n block khi lỗi
START_BLOCK_INDEX = 210   # Vị trí bắt đầu xử lý trong file (index 0-based)
END_BLOCK_INDEX = None     # Vị trí kết thúc (None = chạy đến cuối)

# === Cấu hình gửi instruction trước ===
SEND_INSTRUCTION_BEFORE = True   # Gửi instruction trước rồi mới gửi nội dung
INSTRUCTION_MODE = "drama"       # "xianxia" (tu tiên) hoặc "drama"

# === Cấu hình dừng ngay khi thiếu block ===
STOP_ON_MISSING = True  # True = beep xong dừng chương trình

# === Prompt hướng dẫn (2 biến — chọn bởi INSTRUCTION_MODE) ===
INSTRUCTION_FIRST = (
    "Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt. "
    "Mỗi đoạn được đánh dấu bằng B[x]. Hãy dịch:\n\n"
    "- Theo văn phong tu tiên cổ đại, dùng từ ngắn ngọn nhưng dễ hiểu khống quá dài so với văn bản gốc.\n"
    "đây là văn bản dùng để đọc TTS không thêm kí tự lung tung vào\n"
    "- Tên nhân vật, tông môn, cảnh giới, chiêu thức, v.v... bằng âm Hán-Việt (ví dụ:  老秦 là Lão Tần). "
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

INSTRUCTION_FIRST_Darama = (
    "Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt. câu dịch không quá dài và không quá ngắn so với số từ của văn gốc"
    "Mỗi đoạn được đánh dấu bằng B[x]. Hãy dịch:\n\n"
    "- Bối cảnh: drama gia đình – trùng sinh làm lại cuộc đời (hiện đại). Dùng từ ngắn gọn, dễ hiểu, giữ nhịp cảm xúc căng thẳng nhưng không dài hơn đáng kể so với bản gốc; văn bản dùng để đọc TTS nên không thêm ký tự lạ.\n"
    "- Tên nhân vật, gia tộc, công ty, trường lớp, địa danh… chuyển sang âm Hán-Việt (ví dụ: 赵氏 → Triệu thị). Không phiên âm kiểu pinyin, không Việt hóa tuỳ tiện.\n"
    "- Phân biệt đúng ngữ cảnh xưng hô gia đình và xã hội: con–cha/mẹ, anh–em, chị–em, vợ–chồng, mẹ chồng–nàng dâu, cha chồng–con dâu, sếp–nhân viên, cô/chú/dì/bác–cháu… Duy trì nhất quán vai vế giữa “kiếp trước” và “kiếp này”.\n"
    "- Nếu nhân vật A gọi B là 'mẹ', 'cha', 'mẹ chồng', 'anh rể', 'em dâu', v.v. thì phải giữ đúng quan hệ đó; không đổi thành đại từ chung như 'cô ấy', 'anh ta'.\n"
    "- Hội thoại: dịch đúng từng lời và ngữ khí. Ưu tiên đại từ hiện đại hợp bối cảnh như 'anh', 'em', 'tôi', 'cậu', 'cô', 'chú', 'bác', 'con', 'mẹ', 'ba/cha'. Tránh lối xưng hô cổ ('lão phu', 'bổn tọa') trừ khi bản gốc cố ý dùng.\n"
    "- Thuật ngữ trùng sinh: các khái niệm 'kiếp trước/kiếp này', 'trọng sinh', 'chuộc lỗi', 'báo thù/hoàn báo', 'đổi mệnh'… phải chuyển nghĩa chính xác; không thêm thắt tình tiết.\n"
    "- Dịch sát nghĩa, giữ nguyên trật tự từng đoạn và ký hiệu B[x]. Không thêm bình luận hay lời dẫn.\n"
    "- Trả lại đúng số đoạn tương ứng với các block đã nhận. Không gộp, không thiếu, không tương tác với tôi.\n"
    "- không hỏi lại tôi. không tương tác với tôi cần dịch là đủ.\n"
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
        self.send_count = 0                # Số lần đã gửi prompt
        self.instruction_sent = False      # Đã gửi instruction chưa
        self.driver = self.init_driver()   # Mở trình duyệt

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

    # === Gửi 1 tin nhắn vào ChatGPT ===
    def send_message(self, text):
        textarea = WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )
        textarea.clear()
        textarea.send_keys(text)
        time.sleep(random.uniform(3, 5))
        textarea.send_keys("\ue007")  # Enter

    # === Chờ ChatGPT trả lời xong ===
    def wait_until_complete(self):
        WebDriverWait(self.driver, 600).until_not(
            EC.presence_of_element_located((By.XPATH, "//button[@data-testid='stop-button']"))
        )

    # === Lấy instruction theo mode ===
    def get_instruction_text(self):
        return INSTRUCTION_FIRST_Darama if INSTRUCTION_MODE.lower() == "drama" else INSTRUCTION_FIRST

    # === Gửi instruction một lần trước khi đổ nội dung ===
    def ensure_instruction_sent(self):
        if self.instruction_sent or not SEND_INSTRUCTION_BEFORE:
            return
        print("📢 Gửi yêu cầu hướng dẫn ban đầu…")
        self.send_message(self.get_instruction_text())
        self.wait_until_complete()
        self.instruction_sent = True

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
        def _clean(s: str) -> str:
            # Xóa dấu đầu dòng kiểu ": ", "： ", "- ", "– ", "— ", "• "
            s = re.sub(r"^\s*[:：\-\–\—•·]\s*", "", s)
            return s
        
        with open(output_path, "a", encoding="utf-8") as f:
            for j, trans_lines in enumerate(translated_lines):
                block = original_blocks[j]
                if len(block) < 2:
                    continue
                index = offset + j + 1   # SRT index tăng dần
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
            marked_texts.append(f"B{i+1}\n")
            marked_texts.extend(lines)
        return line_counts, "\n".join(marked_texts)

    # === Gửi prompt đến ChatGPT, phân tích và trả kết quả ===
    def send_to_gpt(self, prompt, line_counts):
        self.send_count += 1

        # Chỉ gửi phần nội dung (KHÔNG chèn instruction ở đây)
        self.send_message(prompt)
        self.wait_until_complete()
        time.sleep(2)
        messages = self.driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        if not messages:
            return None

        reply = messages[-1].text.strip().splitlines()

        # Nếu phản hồi chứa dấu hiệu lỗi giới hạn
        full_reply_text = "\n".join(reply)
        if "bạn đã đạt giới hạn sử dụng" in full_reply_text.lower() or "Thử lại" in full_reply_text:
            print("🚫 GPT đã đạt giới hạn sử dụng GPT-4. Dừng chương trình.")
            exit(1)

        # Tách từng block trong phản hồi
        block_map, current_block = {}, None
        for line in reply:
            match = re.match(r"(B\d+)(.*)", line)
             # B1: xxx   |  B1：xxx  |  B1 - xxx  |  B1.xxx  |  B1 ) xxx
            m = re.match(r"^\s*(B\d+)\s*[:：.\-\–\—\)]?\s*(.*)$", line)
            if m:
                marker, content = m.group(1), m.group(2)
                current_block = marker
                block_map[current_block] = []
                if content:
                    block_map[current_block].append(content)
            elif current_block:
                block_map[current_block].append(line)

        # Gom kết quả theo block (ưu tiên B1, B2,...; fallback định dạng cũ nếu có)
        result = []
        for i, expected_lines in enumerate(line_counts):
            short_header  = f"B{i+1}"
            legacy_header = f"###BLOCK-{i+1}-LINES-{expected_lines}###"

            if short_header in block_map:
                result.append(block_map[short_header])
            elif legacy_header in block_map:
                result.append(block_map[legacy_header])
            else:
                if len(line_counts) == 1:
                    print("ℹ️ GPT không trả header, nhưng chỉ có 1 block → lấy toàn bộ làm kết quả.")
                    cleaned_reply = [line for line in reply if line.strip()]
                    result.append(cleaned_reply)
                else:
                    print(f"⚠️ Thiếu block: {short_header} (legacy: {legacy_header})")
                    return result
        return result
    
    def stop_after_beep(self, message="⛔ Thiếu block: dừng theo cấu hình STOP_ON_MISSING=True"):
        # Phát beep 3 lần
        for _ in range(5):
            winsound.Beep(1000, 500)
            time.sleep(0.2)
        print(message)
        # Đóng trình duyệt nếu còn mở
        try:
            self.driver.quit()
        except Exception:
            pass
        # Thoát chương trình
        raise SystemExit(1)
    
    # === Dịch từng file .srt một ===
    def translate_file(self, input_path, output_path, start_index=0):
        # Gửi instruction một lần trước khi bắt đầu file (nếu bật)
        self.ensure_instruction_sent()

        blocks = self.read_srt_blocks(input_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if os.path.exists(output_path):
            os.remove(output_path)

        print(f"📚 Tổng block: {len(blocks)}")
        total_blocks = len(blocks)

        # Phạm vi xử lý theo START_BLOCK_INDEX và END_BLOCK_INDEX
        i = max(start_index or 0, 0)
        end_limit = END_BLOCK_INDEX if END_BLOCK_INDEX is not None else total_blocks
        end_limit = max(0, min(end_limit, total_blocks))

        if i >= end_limit:
            print("⚠️ Phạm vi xử lý rỗng. Kiểm tra START_BLOCK_INDEX/END_BLOCK_INDEX.")
            return

        group_size = GROUP_SIZE
        batch_start = i

        while i < end_limit:
            end_idx = min(i + group_size, end_limit)
            group = blocks[i:end_idx]
            print(f"   ➤ Gửi block {i+1} → {end_idx}")

            line_counts, prompt = self.prepare_prompt(group)
            result_group = self.send_to_gpt(prompt, line_counts)

            # Nếu thiếu block → không lưu, fallback từng block
            if (not result_group) or (len(result_group) != len(group)):
                if STOP_ON_MISSING:
                    # Beep rồi dừng ngay, KHÔNG fallback, KHÔNG ghi gì thêm
                    self.stop_after_beep("⛔ GPT trả thiếu block, dừng để bạn chỉnh START_BLOCK_INDEX rồi chạy tiếp.")
                # Nếu muốn tiếp tục tự fallback, đặt STOP_ON_MISSING=False
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

            # ======= (Tuỳ chọn) Nghỉ giữa các batch lớn để tránh spam =======
            if (i - batch_start) >= 500:
                print("🕐 Đã xử lý 500 block – nghỉ ngắn để an toàn.")
                # time.sleep(300)  # 5 phút = 300 giây
                batch_start = i

    # === Dịch tất cả các file .srt trong thư mục ===
    def run(self):
        first_file = True  # chỉ áp dụng START_BLOCK_INDEX cho file đầu tiên
        for filename in os.listdir(SRT_INPUT_DIR):
            if not filename.endswith(".srt"):
                continue
            print(f"\n🔄 Xử lý file: {filename}")
            input_path = os.path.join(SRT_INPUT_DIR, filename)
            base_output_path = os.path.join(OUTPUT_DIR, filename.replace(".srt", "_translated.srt"))
            output_path = get_available_filename(base_output_path)

            # Xác định start index cho file này
            start_index = START_BLOCK_INDEX if first_file else 0
            self.translate_file(input_path, output_path, start_index)
            first_file = False  # từ file thứ 2 trở đi thì =0

        self.driver.quit()
        print("\n🎉 Đã hoàn tất tất cả file.")

# === Bắt đầu chương trình ===
if __name__ == "__main__":
    Translator().run()
