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
    "Profile02": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\qo4o211a.5", 
    "Profile03": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\nmfygyzt.2",
    "Profile04": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\uqiowz8o.3",
    "Profile05": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\42alfg11.4",#x
    "Profile06": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\mef4v4wh.6" #x
    
}
# Chọn profile cần dùng
selected_profile = profiles["Profile05"]  # hoặc "Profile01", "Profile02", ...

FIREFOX_PROFILE_PATH = selected_profile
GECKODRIVER_PATH = r"D:\\Python\\GetLinktoText\\geckodriver.exe"  # Đường dẫn geckodriver
CHATGPT_URL = "https://chatgpt.com/?model=gpt-5-thinking"        # Trang ChatGPT

GROUP_SIZE = 70            # Số block gửi mỗi lượt
MIN_GROUP_SIZE = 2         # Không chia nhỏ hơn n block khi lỗi
START_BLOCK_INDEX = 714   # Vị trí bắt đầu xử lý trong file (index 0-based)
END_BLOCK_INDEX = None     # Vị trí kết thúc (None = chạy đến cuối)

# === Cấu hình gửi instruction trước ===
SEND_INSTRUCTION_BEFORE = True   # Gửi instruction trước rồi mới gửi nội dung
INSTRUCTION_MODE = "xianxia"       # "xianxia" (tu tiên) hoặc "drama"

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
    "- mỗi block được trả lời trên 1 hàng riêng biệt"
    "- Trả lại đúng số đoạn tương ứng với các block đã nhận. Không gộp, không thiếu, không tương tác với tôi.\n"
    "- suy nghĩ lâu hơn để trả lời chính xác hơn"
)

# INSTRUCTION_FIRST_Darama = (
#     "Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt. câu dịch không quá dài và không quá ngắn so với số từ của văn gốc"
#     "Mỗi đoạn được đánh dấu bằng B[x]. Hãy dịch:\n\n"
#     "- Bối cảnh: drama gia đình – trùng sinh làm lại cuộc đời (hiện đại). Dùng từ ngắn gọn, dễ hiểu, giữ nhịp cảm xúc căng thẳng nhưng không dài hơn đáng kể so với bản gốc; văn bản dùng để đọc TTS nên không thêm ký tự lạ.\n"
#     "- Tên nhân vật, gia tộc, công ty, trường lớp, địa danh… chuyển sang âm Hán-Việt (ví dụ: 赵氏 → Triệu thị). Không phiên âm kiểu pinyin, không Việt hóa tuỳ tiện.\n"
#     "- Phân biệt đúng ngữ cảnh xưng hô gia đình và xã hội: con–cha/mẹ, anh–em, chị–em, vợ–chồng, mẹ chồng–nàng dâu, cha chồng–con dâu, sếp–nhân viên, cô/chú/dì/bác–cháu… Duy trì nhất quán vai vế giữa “kiếp trước” và “kiếp này”.\n"
#     "- Nếu nhân vật A gọi B là 'mẹ', 'cha', 'mẹ chồng', 'anh rể', 'em dâu', v.v. thì phải giữ đúng quan hệ đó; không đổi thành đại từ chung như 'cô ấy', 'anh ta'.\n"
#     "- Hội thoại: dịch đúng từng lời và ngữ khí. Ưu tiên đại từ hiện đại hợp bối cảnh như 'anh', 'em', 'tôi', 'cậu', 'cô', 'chú', 'bác', 'con', 'mẹ', 'ba/cha'. Tránh lối xưng hô cổ ('lão phu', 'bổn tọa') trừ khi bản gốc cố ý dùng.\n"
#     "- Thuật ngữ trùng sinh: các khái niệm 'kiếp trước/kiếp này', 'trọng sinh', 'chuộc lỗi', 'báo thù/hoàn báo', 'đổi mệnh'… phải chuyển nghĩa chính xác; không thêm thắt tình tiết.\n"
#     "- Dịch sát nghĩa, giữ nguyên trật tự từng đoạn và ký hiệu B[x]. Không thêm bình luận hay lời dẫn.\n"
#     "- Trả lại đúng số đoạn tương ứng với các block đã nhận. Không gộp, không thiếu, không tương tác với tôi.\n"
#     "- không hỏi lại tôi. không tương tác với tôi cần dịch là đủ.\n"
# )
INSTRUCTION_FIRST_Darama = (
    """Sau đây tôi sẽ gửi các đoạn văn tiếng Trung cần dịch sang tiếng Việt. Câu dịch không quá dài cũng không quá ngắn so với văn gốc, dùng để đọc TTS (không thêm ký tự lạ/emoji/markdown).

Định dạng block:
- Mỗi block sẽ có tiêu đề theo dạng: B{GLOBAL_INDEX}#{ID}. Ví dụ: B216#A1B2C3D4
- Bạn PHẢI trả lại từng block theo đúng tiêu đề đó (giữ nguyên số và ID), theo đúng thứ tự đã nhận.
- Không gộp, không bỏ, không đổi số hay ID; số lượng block trả về phải đúng bằng số header đã nhận.
- Tuyệt đối KHÔNG lặp lại nội dung dịch giữa các block có ID khác nhau. Nếu thấy có nguy cơ trùng, hãy diễn đạt lại sát nghĩa.

Yêu cầu dịch (bối cảnh drama hiện đại – trùng sinh làm lại cuộc đời):
- Dùng từ ngắn gọn, dễ hiểu; giữ nhịp cảm xúc căng thẳng; không dài hơn đáng kể so với bản gốc.
- Tên nhân vật, gia tộc, công ty, trường lớp, địa danh… chuyển sang âm Hán–Việt (ví dụ: 赵氏 → Triệu thị). Không phiên âm pinyin, không Việt hoá tuỳ tiện.
- Phân biệt đúng ngữ cảnh xưng hô gia đình – xã hội: con–cha/mẹ, anh–em, chị–em, vợ–chồng, mẹ chồng–nàng dâu, cha chồng–con dâu, sếp–nhân viên, cô/chú/dì/bác–cháu… Giữ nhất quán vai vế giữa “kiếp trước” và “kiếp này”.
- Nếu nhân vật A gọi B là 'mẹ', 'cha', 'mẹ chồng', 'anh rể', 'em dâu'… thì phải giữ đúng quan hệ; không đổi thành đại từ chung như 'cô ấy', 'anh ta'.
- Hội thoại: dịch đúng từng lời và ngữ khí; ưu tiên đại từ hiện đại như 'anh', 'em', 'tôi', 'cậu', 'cô', 'chú', 'bác', 'con', 'mẹ', 'ba/cha'. Tránh lối xưng hô cổ trừ khi bản gốc cố ý dùng.
- Thuật ngữ trùng sinh ('kiếp trước/kiếp này', 'trọng sinh', 'chuộc lỗi', 'báo thù/hoàn báo', 'đổi mệnh'…) phải chuyển nghĩa chính xác; không thêm thắt tình tiết.
- Dịch sát nghĩa, giữ nguyên trật tự từng đoạn; không thêm bình luận hay lời dẫn.
- Chỉ trả kết quả các block theo đúng tiêu đề B{GLOBAL}#ID như đã nhận.
- mỗi block được trả lời trên 1 hàng riêng biệt
- Trả lại đúng số đoạn tương ứng với các block đã nhận. Không gộp, không thiếu, không tương tác với tôi.
- suy nghĩ lâu hơn để trả lời chính xác hơn """
)

# === PATCH: Helpers tạo ID duy nhất cho từng block nguồn (theo nội dung) ===
def _norm_text_for_hash(lines):
    s = "\n".join(lines).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _hash_lines(lines):
    return hashlib.md5(_norm_text_for_hash(lines).encode("utf-8")).hexdigest()

def _short_id(md5hex, n=8):
    return md5hex[:n]

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

        # === PATCH: lưu SourceID cho toàn bộ block nguồn của file hiện hành
        self.src_ids = []                  # index (0-based) -> short hash ID

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

    # === PATCH: Tạo prompt gồm các block đánh dấu bằng GLOBAL_INDEX + SourceID ===
    def prepare_prompt(self, group, global_offset):
        """
        group: danh sách block trong batch
        global_offset: vị trí i (0-based) của block đầu tiên trong group trong toàn file
        Trả về:
          - line_counts: số dòng nội dung gốc của từng block
          - prompt_text: văn bản prompt có header B{GLOBAL_INDEX}#{ID}
        """
        line_counts = []
        marked_texts = []
        for k, block in enumerate(group):
            lines = block[2:] if len(block) >= 3 else []
            line_counts.append(len(lines))
            global_idx_1b = global_offset + k + 1
            src_id = self.src_ids[global_offset + k] if (global_offset + k) < len(self.src_ids) else f"NA{global_idx_1b}"
            marked_texts.append(f"B{global_idx_1b}#{src_id}\n")
            marked_texts.extend(lines)

        guard = (
            "\n\n[LƯU Ý]\n"
            "- Mỗi block phải trả về đúng header đã nhận (B{GLOBAL_INDEX}#ID) mỗi block cần phải có một dòng duy nhất theo thứ tự tăng dần.\n"
            "- PHẢI echo lại đúng #ID ; không được đổi ID giữa các block.\n"
            # "- Tuyệt đối không lặp lại nội dung dịch giữa các block khác ID.\n"
        )
        return line_counts, "\n".join(marked_texts) + guard

    # === PATCH: Gửi prompt đến ChatGPT, phân tích THEO ID và trả kết quả ===
    def send_to_gpt(self, prompt, line_counts, expected_ids):
        """
        expected_ids: danh sách ID nguồn (theo thứ tự group) kỳ vọng nhận về.
        Kết quả: list[list[str]] theo đúng thứ tự expected_ids.
        """
        self.send_count += 1

        self.send_message(prompt)
        self.wait_until_complete()
        time.sleep(2)
        messages = self.driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        if not messages:
            return None

        reply_lines = messages[-1].text.strip().splitlines()
        full_reply_text = "\n".join(reply_lines)

        # Nếu phản hồi chứa dấu hiệu lỗi giới hạn
        if ("bạn đã đạt giới hạn sử dụng" in full_reply_text.lower()) or ("thử lại" in full_reply_text.lower()):
            print("🚫 GPT đã đạt giới hạn sử dụng hoặc lỗi. Dừng chương trình.")
            exit(1)

        # Parse: B{GLOBAL}#ID: ...
        header_re = re.compile(r"^\s*B(\d+)\s*#\s*([A-Fa-f0-9]{4,16})\s*[:：.\-–—\)]?\s*(.*)$")
        fallback_re = re.compile(r"^\s*B(\d+)\s*[:：.\-–—\)]?\s*(.*)$")  # nếu thiếu #ID

        block_map_by_id = {}
        current_id = None

        for line in reply_lines:
            m = header_re.match(line)
            if m:
                current_id = m.group(2)  # ID sau dấu #
                content = m.group(3)
                block_map_by_id[current_id] = []
                if content:
                    block_map_by_id[current_id].append(content)
                continue

            m2 = fallback_re.match(line)
            if m2:
                current_id = f"__noid__{len(block_map_by_id)}"
                content = m2.group(2)
                block_map_by_id[current_id] = []
                if content:
                    block_map_by_id[current_id].append(content)
                continue

            if current_id:
                block_map_by_id[current_id].append(line)

        # Trả kết quả đúng thứ tự expected_ids
        result = []
        for eid in expected_ids:
            if eid in block_map_by_id:
                result.append(block_map_by_id[eid])
            else:
                # fallback: lấy một block không ID nếu còn
                noid_keys = [k for k in block_map_by_id if k.startswith("__noid__")]
                if noid_keys:
                    k = sorted(noid_keys, key=lambda x: int(x.split("__noid__")[1]))[0]
                    result.append(block_map_by_id.pop(k))
                else:
                    print(f"⚠️ Thiếu block cho ID {eid}")
                    return None
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

        # === PATCH: Tạo SourceID ổn định cho toàn bộ file theo nội dung gốc ===
        self.src_ids = []
        for b in blocks:
            src_lines = b[2:] if len(b) >= 3 else []
            h = _hash_lines(src_lines)
            self.src_ids.append(_short_id(h))

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

            # === PATCH: expected_ids cho group hiện tại (theo vị trí toàn cục)
            expected_ids = [self.src_ids[g] for g in range(i, end_idx)]

            # prompt có B{GLOBAL}#ID
            line_counts, prompt = self.prepare_prompt(group, global_offset=i)
            result_group = self.send_to_gpt(prompt, line_counts, expected_ids)

            # Nếu thiếu block → không lưu, fallback từng block
            if (not result_group) or (len(result_group) != len(group)):
                if STOP_ON_MISSING:
                    # Beep rồi dừng ngay, KHÔNG fallback, KHÔNG ghi gì thêm
                    self.stop_after_beep("⛔ GPT trả thiếu block theo ID, dừng để bạn chỉnh START_BLOCK_INDEX rồi chạy tiếp.")
                # Nếu muốn tiếp tục tự fallback, đặt STOP_ON_MISSING=False
                print("❌ GPT trả thiếu block, fallback từng block lẻ theo ID.")
                fallback_result = []
                for idx, block in enumerate(group):
                    mini_expected = [expected_ids[idx]]
                    _, mini_prompt = self.prepare_prompt([block], global_offset=i+idx)
                    res = self.send_to_gpt(mini_prompt, [len(block[2:])], mini_expected)
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
