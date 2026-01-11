import os
import re
import time
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === CẤU HÌNH ===
SRT_INPUT_DIR = "SourceTruyen/aSRT"
OUTPUT_DIR = "SourceTruyen/Outputs"
FIREFOX_PROFILE_PATH = r"C:\\Users\\PC\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\wyo2tlat.GPT Chị Thảo"
GECKODRIVER_PATH = r"D:\\Python\\GetLinktoText\\geckodriver.exe"
CHATGPT_URL = "https://chatgpt.com/g/g-p-685e66fce9808191a6d242086700558d-youtube-hai/project"
GROUP_SIZE = 10  # Gửi 10 block một lần
START_BLOCK_INDEX = 1121  # block số 541 trong file
END_BLOCK_INDEX = 1324    # block số 621 trong file

# === KHỞI TẠO FIREFOX ===
def init_driver():
    options = Options()
    options.add_argument("-profile")
    options.add_argument(FIREFOX_PROFILE_PATH)
    service = Service(GECKODRIVER_PATH)
    driver = webdriver.Firefox(service=service, options=options)
    driver.get(CHATGPT_URL)
    time.sleep(8)
    return driver

# === ĐỌC FILE SRT THEO BLOCK ===
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

# === GỬI NHÓM BLOCK (10 BLOCK 1 LẦN) ===
def send_batch_to_gpt(driver, group):
    def prepare_prompt(group):
        line_counts = []
        marked_texts = []
        for i, block in enumerate(group):
            lines = block[2:] if len(block) >= 3 else []
            line_counts.append(len(lines))
            marked_texts.append(f"###BLOCK-{i+1}-LINES-{len(lines)}###")
            marked_texts.extend(lines)
        return line_counts, "\n".join(marked_texts)

    def send_prompt_and_parse(prompt, line_counts):
        textarea = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )
        textarea.clear()
        content = (
            "Bạn là chuyên gia dịch từ tiếng Trung sang tiếng Việt 1 chút hài hước vui vẻ. câu trả lời chỉ đoạn chat này viết ngoài code block\n"
            "Không thêm số dòng hay timestamp vào phần dịch.\n"
            "Giữ nguyên tên nhân vật, địa danh, tông môn, công pháo để tên hán việt không dịch nghĩa  "
            "Thay thế các từ nhạy cảm, bạo lực theo quy định: \n"
            "- Giết → Giớt \n"
            "- Giết chết → giớt chớt \n"
            "- Chết → chớt \n"
            "- Chó → c hó \n"
            "- Cướp → hốt sạch\n"
            "- Tàn sát → xóa sổ \n"
            "- Tự tử → đi chơi xa \n"
            "- Hãm hiếp → nhãm nhiếp \n"
            "- vi → Vi , xi - Xi (viết hoa chữ V,X) \n"
            "không tự ý cách điệu và chấm lung tung \n"
            "câu trả lời ra phải đúng chuẩn file .srt QUAN TRỌNG LƯU Ý \n"
            "sau đây tôi sẽ bắt đầu gửi "f"{GROUP_SIZE}" " nội dung tự động chỉ viết câu tả lời, không cần giao tiếp với tôi \n"
            f"{prompt}"  # 🟢 Bổ sung dòng này!
        )
        textarea.send_keys(content)
        textarea.send_keys("\ue007")

        WebDriverWait(driver, 300).until_not(
            EC.presence_of_element_located((By.XPATH, "//button[@data-testid='stop-button']"))
        )

        messages = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        last_reply = messages[-1].text.strip()
        result_lines = [line.strip() for line in last_reply.split("\n") if line.strip()]

        result_group = []
        idx = 0
        for i, count in enumerate(line_counts):
            while idx < len(result_lines) and not result_lines[idx].startswith(f"###BLOCK-{i+1}-LINES-"):
                idx += 1
            idx += 1
            lines = result_lines[idx:idx + count]
            if len(lines) < count:
                return None  # báo lỗi
            result_group.append(lines)
            idx += count
        return result_group

    try:
        line_counts, prompt = prepare_prompt(group)

        # Lần gửi 1
        result_group = send_prompt_and_parse(prompt, line_counts)
        if result_group is not None:
            return result_group

        print("⚠️ GPT trả về thiếu dòng, đang gửi lại...")
        time.sleep(2)

        # Lần gửi 2
        prompt2 = "nội dung vừa gửi bị thiếu block hãy viết lại 10 block tôi vừa gửi"
        result_group = send_prompt_and_parse(prompt2, line_counts)
        if result_group is not None:
            print("✅ Gửi lại thành công.")
            return result_group

        print("❌ GPT vẫn trả về thiếu dòng sau khi gửi lại. Ngưng chương trình.")
        return None  # sẽ khiến vòng ngoài dừng

    except Exception as e:
        print(f"❌ Lỗi khi gửi GPT: {e}")
        return None
# === GHI FILE KẾT QUẢ ===
def write_translated_srt(blocks, translated_lines_all, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for block, trans_lines in zip(blocks, translated_lines_all):
            f.write(f"{block[0]}\n")
            f.write(f"{block[1]}\n")
            for line in trans_lines:
                f.write(f"{line}\n")
            f.write("\n")

# === CHẠY CHO TOÀN BỘ FILE ===
def translate_all_srt_files():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    driver = init_driver()

    for filename in os.listdir(SRT_INPUT_DIR):
        if filename.endswith(".srt"):
            input_path = os.path.join(SRT_INPUT_DIR, filename)
            output_path = os.path.join(OUTPUT_DIR, filename.replace(".srt", "_translated.srt"))

            print(f"\n🔄 Đang xử lý file: {filename}")
            blocks = read_srt_blocks(input_path)
            translated_blocks = []

            start_group = (START_BLOCK_INDEX // GROUP_SIZE) * GROUP_SIZE
            end_group = ((END_BLOCK_INDEX + 1) // GROUP_SIZE) * GROUP_SIZE

            for i in range(start_group, min(end_group, len(blocks)), GROUP_SIZE):
                group = blocks[i:i + GROUP_SIZE]
                print(f"   ➤ Gửi nhóm block {i + 1} đến {i + len(group)}")
                result_group = send_batch_to_gpt(driver, group)
                if result_group is None:
                    print("⛔ Dừng chương trình do lỗi không thể sửa.")
                    break
                translated_blocks.extend(result_group)
                time.sleep(3)

            write_translated_srt(blocks[start_group:], translated_blocks, output_path)

    driver.quit()
    print("\n✅ Hoàn tất dịch tất cả file trong thư mục.")

if __name__ == "__main__":
    translate_all_srt_files()