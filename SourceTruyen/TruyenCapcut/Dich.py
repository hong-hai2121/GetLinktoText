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
CHATGPT_URL = "https://chatgpt.com/g/g-p-68717d2ba4a88191a11271af984568dd-facebook-hai/project"
GROUP_SIZE = 14  # Gửi 15 block một lần

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
# Biến toàn cục để đánh dấu lần đầu tiên
first_prompt_sent = False

def send_batch_to_gpt(driver, group, is_first_run=True):
    global first_prompt_sent
    line_counts = []
    marked_texts = []

    for i, block in enumerate(group):
        lines = block[2:] if len(block) >= 3 else []
        line_counts.append(len(lines))
        marked_texts.append(f"###BLOCK-{i+1}-LINES-{len(lines)}###")
        marked_texts.extend(lines)

    # Ghép nội dung
    content = "\n".join(marked_texts)

    # Nếu là lần đầu thì thêm prompt hướng dẫn
    if is_first_run and not first_prompt_sent:
        first_prompt_sent = True
        prompt = (
            "Chỉ dịch phần lời thoại từ tiếng Trung sang tiếng Việt. câu trả lời chỉ đoạn chat này viết ngoài code block\n"
            "Giữ nguyên định dạng BLOCK (ví dụ: ###BLOCK-X-LINES-Y###) và đúng số dòng tương ứng từng BLOCK.\n"
            "Không thêm số dòng hay timestamp vào phần dịch.\n"
            "Giữ nguyên tên nhân vật, địa danh, tông môn, công pháo để tên hán việt không dịch nghĩa  "
            "(ví dụ: “Cố Vân” chứ không được dịch thành “Phụ Nữ”).\n"
            "Thay thế các từ nhạy cảm, bạo lực theo quy định: \n"
            "- Giết → Giớt \n"
            "- Giết chết → hất cẳng, xử lý triệt để, giớt chớt \n"
            "- Chết → bay màu, ra đi, ngủm, chớt \n"
            "- Chó → c hó \n"
            "- Cướp → hốt sạch, thu gom \n"
            "- Phản bội → đâm sau lưng \n"
            "- Tàn sát → xóa sổ \n"
            "- Tự tử → đi chơi xa \n"
            "- Hãm hiếp → nhãm nhiếp \n"
            "- vi → Vi (viết hoa chữ V) \n"
            "không tự ý cách điệu và chấm lung tung \n"
            "câu trả lời ra phải đúng chuẩn file .srt ví dụ như bên dưới này \n"
            "###BLOCK-1-LINES-1### \n"
            "Niệm tình ngươi từng lập công lớn cho Thánh địa \n"
            "###BLOCK-2-LINES-1### \n" 
            "Lập tức tự phế tu Vi \n"
            "sau đây tôi sẽ bắt đầu gửi nội dung tự động chỉ viết câu tả lời, không cần giao tiếp với tôi \n"
            f"{content}"  # 🟢 Bổ sung dòng này!
        )

    else:
        prompt = (
            "Thay thế các từ nhạy cảm, bạo lực theo quy định: \n"
            "- Giết → Giớt \n"
            "- Giết chết → hất cẳng, xử lý triệt để, giớt chớt \n"
            "- Chết → chớt \n"
            "- Chó → c hó \n"
            "- Cướp → hốt sạch \n"
            "- Phản bội → đâm sau lưng \n"
            "- Tàn sát → xóa sổ \n"
            "- Tự tử → đi chơi xa \n"
            "- Hãm hiếp → nhãm nhiếp \n"
            "- vi → VI, xi -> Xi (viết hoa chữ đầu) \n"
            f"{content}"
        )

    try:
        textarea = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="prompt-textarea"]'))
        )
        textarea.clear()
        textarea.send_keys(prompt)
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
            idx += 1  # Bỏ dòng đánh dấu
            lines = result_lines[idx:idx + count]
            if len(lines) < count:
                print(f"⚠️ Thiếu dòng trong BLOCK-{i+1}: mong đợi {count}, GPT trả về {len(lines)} dòng.")
                missing = count - len(lines)
                lines.extend(["( bị thiếu dòng )"] * missing)  # ✅ Thêm placeholder rõ ràng
            result_group.append(lines)
            idx += count

        return result_group

    except Exception as e:
        print(f"Lỗi khi gửi batch: {e}")
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

            for i in range(0, len(blocks), GROUP_SIZE):
                group = blocks[i:i + GROUP_SIZE]
                print(f"   ➤ Gửi nhóm block {i + 1} đến {i + len(group)}")
                result_group = send_batch_to_gpt(driver, group)
                if result_group is None:
                    print(f"⚠️  Bỏ qua nhóm {i//GROUP_SIZE + 1} của file {filename} do lỗi.")
                    continue
                translated_blocks.extend(result_group)
                time.sleep(3)

            write_translated_srt(blocks, translated_blocks, output_path)

    driver.quit()
    print("\n✅ Hoàn tất dịch tất cả file trong thư mục.")

if __name__ == "__main__":
    translate_all_srt_files()