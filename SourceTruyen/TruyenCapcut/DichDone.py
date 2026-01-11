import os
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
CHATGPT_URL = "https://chatgpt.com/g/g-p-685e66fce9808191a6d242086700558d-youtube-hai/c/68838fbc-c24c-8326-8f16-762b4754dfa6"
GROUP_SIZE = 15
START_BLOCK_INDEX = 0
END_BLOCK_INDEX = 1171

# === HƯỚNG DẪN GPT ===
INSTRUCTION_FIRST = (
    # "Bạn là chuyên gia dịch từ tiếng Trung sang tiếng Việt. Câu trả lời chỉ đoạn chat này viết ngoài code block.\n"
    # "Không thêm số dòng hay timestamp vào phần dịch.\n"
    # "Giữ nguyên tên nhân vật, địa danh, tông môn, công pháo để tên Hán Việt không dịch nghĩa.\n"
    # "Thay thế các từ nhạy cảm, bạo lực theo quy định:\n"
    # "- Giết → Giớt\n"
    # "- Giết chết → giớt chớt\n"
    # "- Chết → chớt\n"
    # "- Chó → c hó\n"
    # "- Cướp → hốt sạch\n"
    # "- Tàn sát → xóa sổ\n"
    # "- Tự tử → đi chơi xa\n"
    # "- Hãm hiếp → nhãm nhiếp\n"
    # "- vi → Vi, xi - Xi (viết hoa chữ V, X)\n"
    # "Không tự ý cách điệu và chấm lung tung.\n"
    # "Câu trả lời ra phải đúng chuẩn file .srt. QUAN TRỌNG LƯU Ý:\n"
    f"Sau đây tôi sẽ bắt đầu gửi {GROUP_SIZE} nội dung. Tự động chỉ viết câu trả lời bình thường không đưa vào block code, không cần giao tiếp với tôi.\n"
)

INSTRUCTION_RETRY = (
    f"Nội dung vừa gửi bị thiếu block. Hãy viết lại đầy đủ đúng block tôi vừa gửi. Giữ đúng định dạng block line 1 dòng nội dung 1 dòng.\n"
)

# === KHỞI TẠO FIREFOX ===
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

def write_final_srt_from_translation(original_blocks, translated_blocks, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for i, block in enumerate(original_blocks):
            if len(block) < 2:
                continue  # skip nếu thiếu số block hoặc timestamp

            index = block[0]          # Số thứ tự block: 1, 2, 3,...
            timestamp = block[1]      # Dòng thời gian SRT
            translation_lines = translated_blocks[i] if i < len(translated_blocks) else ["(thiếu dòng)"]

            f.write(f"{index}\n")
            f.write(f"{timestamp}\n")
            for line in translation_lines:
                f.write(f"{line}\n")
            f.write("\n")

# === GỬI BLOCK CHO GPT ===
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

    def send_prompt_and_parse(prompt, line_counts, instruction):
        textarea = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )
        textarea.clear()
        content = instruction + "\n" + prompt
        textarea.send_keys(content)
        textarea.send_keys("\ue007")

        WebDriverWait(driver, 300).until_not(
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
            if line.startswith("###BLOCK-") and "###" in line:
                current_block = line
                block_map[current_block] = []
            elif current_block:
                block_map[current_block].append(line)

        # Kiểm tra tổng số block khớp với line_counts
        if len(block_map) != len(line_counts):
            print(f"❌ Số lượng block phản hồi không khớp: {len(block_map)} / {len(line_counts)}")
            return None

        result_group = []
        for i, expected_lines in enumerate(line_counts):
            header = f"###BLOCK-{i+1}-LINES-{expected_lines}###"
            if header not in block_map:
                print(f"❌ Thiếu block: {header}")
                return None
            lines = block_map[header]
            if len(lines) != expected_lines:
                print(f"❌ Sai số dòng ở block {i+1}: có {len(lines)} dòng, kỳ vọng {expected_lines}")
                return None
            result_group.append(lines)

        print(f"✅ GPT phản hồi hợp lệ với {len(result_group)} block.")
        return result_group  # ✅ Sau vòng lặp, mới return kết quả
    try:
        line_counts, prompt = prepare_prompt(group)
        print(f"📤 Gửi {len(group)} block, tổng dòng: {sum(line_counts)}")

        # Lần gửi 1
        result_group = send_prompt_and_parse(prompt, line_counts, INSTRUCTION_FIRST)
        if result_group is not None:
            return result_group

        print("⚠️ GPT trả về thiếu dòng, đang gửi lại...")
        time.sleep(2)

        # Gửi lại
        result_group = send_prompt_and_parse(prompt, line_counts, INSTRUCTION_RETRY)
        if result_group is not None:
            print("✅ Gửi lại thành công.")
            return result_group

        print("❌ GPT vẫn trả về thiếu dòng sau khi gửi lại.")
        return None

    except Exception as e:
        print(f"❌ Lỗi khi gửi GPT: {e}")
        return None

def append_translated_srt(original_blocks, translated_lines, output_path, offset):
    with open(output_path, "a", encoding="utf-8") as f:
        for j, trans_lines in enumerate(translated_lines):
            block = original_blocks[j]
            if len(block) < 2:
                continue  # bỏ qua block lỗi

            # Tính lại số thứ tự block thật theo offset
            index = offset + j + 1
            timestamp = block[1]

            f.write(f"{index}\n")
            f.write(f"{timestamp}\n")
            for line in trans_lines:
                f.write(f"{line}\n")
            f.write("\n")
            
# === CHẠY TOÀN BỘ FILE ===
def translate_all_srt_files():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    driver = init_driver()

    for filename in os.listdir(SRT_INPUT_DIR):
        if filename.endswith(".srt"):
            input_path = os.path.join(SRT_INPUT_DIR, filename)
            output_path = os.path.join(OUTPUT_DIR, filename.replace(".srt", "_translated.srt"))

            # 🔁 Nếu file đã tồn tại, xóa để ghi mới
            if os.path.exists(output_path):
                os.remove(output_path)

            print(f"\n🔄 Đang xử lý file: {filename}")
            blocks = read_srt_blocks(input_path)
            print(f"📚 Tổng block: {len(blocks)}")

            start_idx = START_BLOCK_INDEX
            end_idx = END_BLOCK_INDEX + 1
            start_group = start_idx

            for i in range(start_idx, min(end_idx, len(blocks)), GROUP_SIZE):
                group = blocks[i:i + GROUP_SIZE]
                print(f"   ➤ Gửi nhóm block {i + 1} đến {i + len(group)}")
                result_group = send_batch_to_gpt(driver, group)

                if result_group is None:
                    print("⛔ Dừng chương trình do lỗi không thể sửa.")
                    print("⏹ Bạn có thể chạy lại từ block:", i)
                    break

                # ✅ Ghi nối từng nhóm block vào file đích
                append_translated_srt(group, result_group, output_path, i)
                print(f"💾 Đã lưu nhóm block {i+1} đến {i + len(group)} vào file.")
                time.sleep(2)

            print(f"✅ Đã lưu xong tất cả nhóm cho file: {output_path}")

    driver.quit()
    print("\n🎉 Hoàn tất dịch tất cả file trong thư mục.")



if __name__ == "__main__":
    translate_all_srt_files()



#✅ TÓM TẮT TOÀN BỘ YÊU CẦU DỊCH SRT TIÊN HIỆP DÙNG TTS
# 1. Phong cách dịch

#     Dịch súc tích, không rườm rà, không văn vẻ cổ trang dài dòng.

#     Giữ đúng tinh thần tiên hiệp, tu luyện, hành tẩu giang hồ.

# 2. Định dạng trả lời

#     Trả lời theo định dạng chuẩn hệ thống yêu cầu, mỗi block bắt đầu bằng:

###BLOCK-x-LINES-y###
# <dòng dịch 1>
# <dòng dịch 2>
# ...

# Ví dụ:

#     ###BLOCK-3-LINES-2###
#     Hắn vừa bước vào Trúc Cơ.
#     Không ngờ đã có thể đỡ một đòn của Nguyên Anh.

#     KHÔNG thêm lời giải thích, chào hỏi, dòng trắng, hay tiêu đề nào khác ngoài định dạng trên.

# 3. Yêu cầu về từ ngữ

#     Giữ nguyên toàn bộ Hán Việt cho:

#         Tên nhân vật (Ví dụ: Lý Trường Sinh, Hàn Thiên)

#         Địa danh (Ví dụ: Thiên Vân Tông, Bắc Vực)

#         Chiêu thức, công pháp (Ví dụ: Cửu Dương Chân Kinh, Thiên Ma Tán Công)

#         Cảnh giới (Trúc Cơ, Kim Đan, Nguyên Anh, Độ Kiếp, Phi Thăng...)

#     Không dịch nghĩa hoặc phèn hóa các thuật ngữ Hán Việt nêu trên.

#     Không cách điệu từ ngữ nhạy cảm (không chấm giữa các âm tiết như “c.h.ết”).

#     Từ nhạy cảm duy nhất được thay thế:

#         “Chó” → “cờ hó”

# 4. Mục tiêu đầu ra

#     Dùng văn bản đầu ra để chuyển thành giọng đọc TTS → cần ngắn gọn, rõ nghĩa, dễ phát âm.

# 5. Số block mỗi lần xử lý

#     Mỗi batch dịch gồm đúng 10 block từ file .srt.

#     các câu trả lời bình thường không để trong block