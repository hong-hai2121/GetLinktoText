import os
import time
import re
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import random

# === CẤU HÌNH ===
SRT_INPUT_DIR = "SourceTruyen/aSRT"
OUTPUT_DIR = "SourceTruyen/Outputs"
FIREFOX_PROFILE_PATH = r"C:\\Users\\PC\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\wyo2tlat.GPT Chị Thảo"
GECKODRIVER_PATH = r"D:\\Python\\GetLinktoText\\geckodriver.exe"
CHATGPT_URL = "https://chatgpt.com/"
GROUP_SIZE = 8
OVERLAP_STEP = 2
MIN_GROUP_SIZE = 2
MAX_RETRY = 3
RETRY_DELAY = 3
START_BLOCK_INDEX = 836
END_BLOCK_INDEX = None
SEND_COUNT = 0


INSTRUCTION_FIRST = (
    f"Sau đây tôi sẽ gửi {GROUP_SIZE} đoạn văn bản cần dịch sang tiếng Việt. "
    f"Mỗi đoạn được đánh dấu bằng [BLOCK-x]. Dịch ngắn gọn, phong cách tu tiên, dùng từ Hán Việt và điều chỉnh sao cho phù hợp với bối cảnh câu trước và câu sau.\n"
)

def init_driver():
    options = Options()
    options.add_argument("-profile")
    options.add_argument(FIREFOX_PROFILE_PATH)
    service = Service(GECKODRIVER_PATH)
    driver = webdriver.Firefox(service=service, options=options)
    driver.get(CHATGPT_URL)
    print("🚀 Trình duyệt đã mở và điều hướng đến ChatGPT.")
    time.sleep(8)
    return driver

def read_srt_blocks(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines()]
    blocks = []
    block = []
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

def append_translated_srt(original_blocks, translated_lines, output_path, offset):
    with open(output_path, "a", encoding="utf-8") as f:
        for j, trans_lines in enumerate(translated_lines):
            block = original_blocks[j]
            if len(block) < 2:
                continue
            index = offset + j + 1
            timestamp = block[1]
            f.write(f"{index}\n")
            f.write(f"{timestamp}\n")
            for line in trans_lines:
                f.write(f"{line}\n")
            f.write("\n")

def send_batch_to_gpt(driver, group):
    def prepare_prompt(group):
        line_counts = []
        marked_texts = []
        for i, block in enumerate(group):
            lines = block[2:] if len(block) >= 3 else []
            line_counts.append(len(lines))
            marked_texts.append(f"###BLOCK-{i+1}-LINES-{len(lines)}###\n")
            marked_texts.extend(lines)
        return line_counts, "\n".join(marked_texts)

    def send_prompt_and_parse(prompt, line_counts, instruction):
        global SEND_COUNT
        SEND_COUNT += 1  # tăng số lần gửi

        textarea = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )

        textarea.clear()

        # ✅ Chỉ thêm instruction mỗi 10 lần (lần 1, 11, 21...)
        if SEND_COUNT % 10 == 1:
            content = instruction + "\n" + prompt
        else:
            content = prompt
        textarea.send_keys(content)

        time.sleep(random.uniform(1, 2))
        textarea.send_keys("\ue007")
        time.sleep(random.uniform(5, 10))
        WebDriverWait(driver, 500).until_not(
            EC.presence_of_element_located((By.XPATH, "//button[@data-testid='stop-button']"))
        )

        messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")

        if not messages:
            print("❌ GPT không phản hồi.")
            return None

        last_reply = messages[-1].text.strip().splitlines()
        block_map = {}
        current_block = None

        for line in last_reply:
            line = line.strip()
            match = re.match(r"(###BLOCK-\d+-LINES-\d+###)(.*)", line)
            if match:
                marker, content = match.groups()
                current_block = marker
                block_map[current_block] = []
                if content.strip():
                    block_map[current_block].append(content.strip())
            elif current_block:
                block_map[current_block].append(line)

        result_group = []
        for i, expected_lines in enumerate(line_counts):
            header = f"###BLOCK-{i+1}-LINES-{expected_lines}###"
            if header not in block_map:
                print(f"⚠️ Thiếu block: {header}")
                return result_group  # Trả về phần đã có để retry
            lines = block_map[header]
            result_group.append(lines)

        print(f"✅ GPT phản hồi {len(result_group)} block / kỳ vọng {len(line_counts)}")
        return result_group


    try:
        line_counts, prompt = prepare_prompt(group)
        print(f"📤 Gửi {len(group)} block, tổng dòng: {sum(line_counts)}")
        return send_prompt_and_parse(prompt, line_counts, INSTRUCTION_FIRST)
    except Exception as e:
        print(f"❌ Lỗi khi gửi GPT: {e}")
        return None

def translate_all_srt_files():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    driver = init_driver()

    for filename in os.listdir(SRT_INPUT_DIR):
        if filename.endswith(".srt"):
            input_path = os.path.join(SRT_INPUT_DIR, filename)
            output_path = os.path.join(OUTPUT_DIR, filename.replace(".srt", "_translated.srt"))
            if os.path.exists(output_path):
                os.remove(output_path)

            print(f"\n🔄 Đang xử lý file: {filename}")
            blocks = read_srt_blocks(input_path)
            print(f"📚 Tổng block: {len(blocks)}")

            i = START_BLOCK_INDEX
            group_size = GROUP_SIZE
            retry_count = 0
            missing_retry = 0  # Đếm số lần GPT trả thiếu liên tiếp

            while i < (END_BLOCK_INDEX + 1 if END_BLOCK_INDEX is not None else len(blocks)):
                end_idx = min(i + group_size, len(blocks))
                group = blocks[i:end_idx]
                print(f"   ➤ Gửi nhóm block {i + 1} đến {end_idx}")

                result_group = send_batch_to_gpt(driver, group)

                # ====== Trường hợp GPT không trả lời ======
                if result_group is None or len(result_group) == 0:
                    print(f"❌ GPT không phản hồi tại block {i+1}-{end_idx}. Dừng chương trình.")
                    try:
                        driver.quit()
                    except:
                        pass
                    exit(1)

                # ====== Trường hợp GPT trả đủ ======
                if len(result_group) == len(group):
                    append_translated_srt(group, result_group, output_path, i)
                    print(f"💾 Đã lưu block {i + 1} đến {i + len(result_group)}")
                    i += len(result_group)
                    group_size = GROUP_SIZE
                    retry_count = 0
                    missing_retry = 0

                # ====== Trường hợp GPT trả thiếu ======
                else:
                    missing_retry += 1
                    print(f"⚠️ GPT trả thiếu block ({len(result_group)} / {len(group)}) - Lùi về {OVERLAP_STEP} block. Số lần thiếu liên tiếp: {missing_retry}")
                    if missing_retry >= 2:
                        print(f"🚨 GPT trả thiếu 2 lần liên tiếp tại file {filename}, block {i+1}-{end_idx}. Dừng chương trình để tránh vòng lặp vô tận.")
                        try:
                            driver.quit()
                        except:
                            pass
                        exit(1)
                    i = max(0, i - OVERLAP_STEP)
                    group_size = max(MIN_GROUP_SIZE, group_size - OVERLAP_STEP)
                    time.sleep(RETRY_DELAY)



            print(f"✅ Đã hoàn tất dịch file: {output_path}")

    driver.quit()
    print("\n🎉 Hoàn tất dịch tất cả file trong thư mục.")

if __name__ == "__main__":
    translate_all_srt_files()



# Dịch đoạn văn sau theo phong cách tu tiên, sử dụng từ Hán Việt và giữ nguyên bối cảnh của câu trước và câu sau. Mỗi đoạn được đánh dấu bằng định dạng ###BLOCK-{i+1}-LINES-{i+1}###. Chỉ trả lại bản dịch, không cần giải thích hay thêm thông tin nào khác ngoài phần dịch.

# - Giữ nguyên các tên nhân vật (ví dụ: Lý Trường Sinh, Hàn Thiên), địa danh (ví dụ: Thiên Vân Tông, Bắc Vực), chiêu thức, công pháp (ví dụ: Cửu Dương Chân Kinh, Thiên Ma Tán Công), và cảnh giới (ví dụ: Trúc Cơ, Kim Đan, Nguyên Anh) bằng Hán Việt.
# - Nếu đoạn văn có thuật ngữ hoặc các yếu tố quan trọng, hãy dịch sao cho phù hợp với bối cảnh của câu trước và câu sau mà không làm sai lệch ý nghĩa.
# - Không dịch các thuật ngữ Hán Việt sang tiếng Việt, chỉ giữ nguyên khi cần thiết.