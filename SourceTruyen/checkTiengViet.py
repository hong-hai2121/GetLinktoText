import os
import re
from collections import defaultdict

# =========================
# CẤU HÌNH CHUNG
# =========================
OUTPUTS_DIR = r"SourceTruyen/Outputs"
CLEANED_DIR = r"SourceTruyen/Cleaned"
OLD_SRT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\old srt"
COMBINED_LOG_FILE = r"SourceTruyen/Cleaned/ALL_ERRORS.log"  # File log gộp chung

# Với block BÌNH THƯỜNG (không thiếu), có >= 2 dòng thoại thì xóa dòng nội dung thứ 2?
DELETE_SECOND_CONTENT_LINE = True
LOG_DUP_SUMMARY = False
DUPLICATE_MIN_CHARS = 1  # tăng 4–5 để bớt báo các câu ngắn kiểu "Vâng."

REPLACEMENTS = {
    "giết chết": "giớt chớt",
    "giết": "giớt",
    "chết": "chớt",
    "vi": "Vi",
    "xi": "Xi",
    '"': "",
}

# Các hậu tố “dịch/clean” phổ biến cần cắt bỏ để truy ra tên gốc (để lấy nội dung gốc ghi LOG)
COMMON_SUFFIXES = [
    r"_translated", r"_translate", r"_cleaned", r"_clean", r"_vi", r"_vn",
    r"_out", r"_final", r"_fixed", r"_edit", r"_edited", r"_output"
]

# =========================
# HÀM TIỆN ÍCH
# =========================
def contains_chinese(text: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)

def replace_words_case_insensitive(text: str, replacements: dict) -> str:
    t = text
    for old, new in replacements.items():
        pattern = re.compile(rf"\b{re.escape(old)}\b", flags=re.IGNORECASE)
        t = pattern.sub(new, t)
    return t

# Phát hiện các biến thể “gạch dài”: ——, —, ―, ⸺, ⸻
LONG_DASH_DETECT_RE = re.compile(r'(\u2014{2}|[\u2014\u2015\u2E3A\u2E3B])')
def has_long_dash(text: str) -> bool:
    return bool(LONG_DASH_DETECT_RE.search(text))

def normalize_dialogue(text: str) -> str:
    t = text.strip().lower()
    # bỏ ngoặc kép unicode
    t = re.sub(r'[“”"“”‘’\'\u2018\u2019\u201c\u201d]', '', t)
    # coi dấu câu + các dạng gạch là phân cách
    t = re.sub(r'[.,!?;:…\u2014\u2015\u2E3A\u2E3B\u2013\uFF0D\u2212\uFE58\uFE63\-]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()  # co khoảng trắng
    return t

def ensure_utf8_read(path: str) -> list:
    """Đọc file với UTF-8 (chịu BOM)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.readlines()
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()

def smart_join(*parts) -> str:
    return os.path.normpath(os.path.join(*parts))

# =========================
# TÌM FILE GỐC TỪ TÊN FILE HIỆN TẠI
# =========================
def guess_original_candidates(base_name: str) -> list[str]:
    stem, _ = os.path.splitext(base_name)
    candidate_stems = set()

    for suf in COMMON_SUFFIXES:
        pattern = re.compile(re.escape(suf) + r'$', flags=re.IGNORECASE)
        stripped = pattern.sub('', stem)
        candidate_stems.add(stripped)

    candidate_stems.add(stem)

    m = re.match(r'^(\d+)', stem)
    if m:
        candidate_stems.add(m.group(1))

    candidates = sorted({c + ".srt" for c in candidate_stems if c}, key=len)
    return candidates

def find_original_path(translated_path: str, old_srt_dir: str) -> str | None:
    base_name = os.path.basename(translated_path)
    candidates = guess_original_candidates(base_name)

    for cand in candidates:
        p = smart_join(old_srt_dir, cand)
        if os.path.exists(p):
            return p

    # fallback: lấy đuôi số nếu có
    stem, _ = os.path.splitext(base_name)
    m = re.match(r'.*?(\d+)$', stem)
    if m:
        p = smart_join(old_srt_dir, m.group(1) + ".srt")
        if os.path.exists(p):
            return p

    return None

# =========================
# ĐỌC FILE GỐC THÀNH MAP BLOCK
# =========================
def load_original_blocks(original_path: str) -> dict[int, list]:
    if not original_path or not os.path.exists(original_path):
        return {}

    lines = ensure_utf8_read(original_path)

    blocks = {}
    inside_block = []
    block_number = None

    for line in lines + ["\n"]:
        if line.strip() == "":
            if inside_block and block_number is not None:
                content_lines = [l.rstrip("\n") for l in inside_block[2:]]
                blocks[block_number] = content_lines
                inside_block = []
                block_number = None
        else:
            inside_block.append(line)
            if block_number is None and line.strip().isdigit():
                block_number = int(line.strip())

    return blocks

def pick_original_content_for_log(block_no: int,
                                  original_blocks: dict[int, list]) -> str:
    """
    Lấy các dòng ưu tiên có tiếng Trung; nếu không có, lấy các dòng không rỗng.
    Nối bằng ' | '. Nếu không có gì, trả '(không có nội dung gốc)'.
    """
    if not original_blocks or block_no not in original_blocks:
        return "(không có nội dung gốc)"

    lines = original_blocks[block_no]
    zh_lines = [l.strip() for l in lines if contains_chinese(l)]
    picked = zh_lines if zh_lines else [l.strip() for l in lines if l.strip()]
    return " | ".join(picked) if picked else "(không có nội dung gốc)"

# =========================
# XỬ LÝ 1 FILE
# =========================
def process_single_srt_file(input_path: str,
                            output_srt_path: str,
                            combined_log_lines: list,
                            replacements: dict,
                            duplicate_min_chars: int = DUPLICATE_MIN_CHARS,
                            delete_second_content_line: bool = DELETE_SECOND_CONTENT_LINE,
                            old_srt_dir: str = OLD_SRT_DIR):
    lines = ensure_utf8_read(input_path)
    
    # Lấy tên file để đánh dấu trong log gộp
    srt_filename = os.path.basename(output_srt_path)

    output_lines = []
    log_lines = []

    # Tham chiếu file gốc chỉ để LOG: không in thêm dòng ℹ️ dư thừa
    original_path = find_original_path(input_path, old_srt_dir)
    original_blocks = load_original_blocks(original_path) if original_path else {}
    if not original_path:
        log_lines.append("⚠️ Không tìm thấy file gốc tương ứng trong thư mục 'old srt'.")

    # Dùng để phát hiện trùng lặp
    duplicate_index = defaultdict(list)

    # Lưu các block thiếu
    missing_blocks = []

    block_number = None
    inside_block = []

    for line in lines + ["\n"]:  # thêm dòng trắng để xử lý block cuối
        if line.strip() == "":
            if inside_block:
                is_missing = False

                if block_number is not None:
                    # Nội dung raw để kiểm tra
                    content_lines_raw = [l.rstrip("\n") for l in inside_block[2:]]

                    # Cảnh báo tiếng Trung + dấu gạch dài trong bản đang xử lý (nếu có)
                    for content_line in content_lines_raw:
                        if contains_chinese(content_line):
                            log_lines.append(f"⚠️ Block {block_number} chứa tiếng Trung: {content_line.strip()}")
                        if has_long_dash(content_line):
                            log_lines.append(f"⚠️ Block {block_number} chứa tiếng Trung (——): {content_line.strip()}")

                    # Thiếu nội dung nếu <3 dòng hoặc mọi dòng nội dung rỗng sau normalize
                    has_meaningful_text = any(normalize_dialogue(l) != "" for l in content_lines_raw)
                    if len(inside_block) < 3 or not has_meaningful_text:
                        is_missing = True
                        missing_blocks.append(block_number)
                        # Ghi LOG theo format mới:
                        original_text = pick_original_content_for_log(block_number, original_blocks)
                        log_lines.append(
                            f"❌ Block {block_number} thiếu nội dung sau timestamp → {original_text}"
                        )

                    # Nếu KHÔNG thiếu: áp dụng các xử lý bình thường
                    if not is_missing:
                        # Xóa dòng nội dung thứ 2 (nếu bật) – chỉ khi hiện có ≥ 2 dòng nội dung
                        if delete_second_content_line and len(inside_block) >= 4:
                            deleted_line = inside_block[3]  # dòng nội dung thứ 2
                            log_lines.append(
                                f"🗑️ Đã xóa dòng nội dung thứ 2 của block {block_number}: {deleted_line.strip()}"
                            )
                            del inside_block[3]

                        # Clean & replace cho các dòng nội dung
                        for i, content_line in enumerate(inside_block):
                            if i >= 2:
                                clean_line = content_line.replace('"', '')
                                clean_line = replace_words_case_insensitive(clean_line, replacements)
                                inside_block[i] = clean_line

                        # Kiểm tra trùng lặp sau khi clean + replace
                        for content_line in inside_block[2:]:
                            raw = content_line.strip()
                            if not raw:
                                continue
                            norm = normalize_dialogue(raw)
                            if len(norm) < duplicate_min_chars:
                                continue
                            # KHÔNG ghi log từng lần trùng (tránh dư thừa) → chỉ tổng hợp cuối cùng
                            duplicate_index[norm].append({"block": block_number, "text": raw})

                    # Nếu THIẾU: tuyệt đối KHÔNG đụng vào nội dung block

                # Ghi block ra output (nguyên trạng nếu thiếu)
                output_lines.extend(inside_block)
                output_lines.append("\n")
                inside_block = []
                block_number = None
        else:
            inside_block.append(line)
            if block_number is None and line.strip().isdigit():
                block_number = int(line.strip())

    # Ghi file phụ đề đã xử lý
    os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
    with open(output_srt_path, "w", encoding="utf-8") as out:
        out.writelines(output_lines)

    # Tổng hợp nhóm trùng lặp (tùy chọn in ra)
    if LOG_DUP_SUMMARY:
        groups = []
        for norm_text, entries in duplicate_index.items():
            if len(entries) > 1:
                blocks = sorted({e["block"] for e in entries})
                sample = entries[0]["text"]
                groups.append((sample, blocks, len(entries)))

        if groups:
            log_lines.append("\n==== TỔNG HỢP CÂU THOẠI BỊ LẶP ====")
            for sample, blocks, count in sorted(groups, key=lambda x: (-x[2], x[1])):
                log_lines.append(f"🔂 \"{sample}\" → xuất hiện {count} lần ở các block: {', '.join(map(str, blocks))}")


    # Tổng hợp block thiếu
    if missing_blocks:
        log_lines.append("\n==== TỔNG HỢP BLOCK THIẾU NỘI DUNG ====")
        log_lines.append("Các block: " + ", ".join(map(str, sorted(missing_blocks))))

    # Thêm log của file này vào log gộp chung (nếu có lỗi)
    if log_lines:
        combined_log_lines.append(f"\n{'='*80}")
        combined_log_lines.append(f"FILE: {srt_filename}")
        combined_log_lines.append(f"{'='*80}")
        combined_log_lines.extend(log_lines)

    print(f"✅ Đã xử lý: {os.path.basename(input_path)}")

# =========================
# XỬ LÝ TOÀN THƯ MỤC
# =========================
def process_all_srt_files(input_folder: str,
                          output_folder: str,
                          replacements: dict,
                          duplicate_min_chars: int = DUPLICATE_MIN_CHARS,
                          old_srt_dir: str = OLD_SRT_DIR,
                          combined_log_file: str = COMBINED_LOG_FILE):
    os.makedirs(output_folder, exist_ok=True)
    srt_files = [f for f in os.listdir(input_folder) if f.lower().endswith(".srt")]
    
    # List để gộp tất cả log
    combined_log_lines = []
    combined_log_lines.append("="*80)
    combined_log_lines.append("TỔNG HỢP TẤT CẢ LỖI TỪ CÁC FILE TRANSLATED")
    combined_log_lines.append(f"Tổng số file: {len(srt_files)}")
    combined_log_lines.append("="*80)

    for filename in srt_files:
        input_path = smart_join(input_folder, filename)
        output_srt_path = smart_join(output_folder, filename)

        process_single_srt_file(
            input_path=input_path,
            output_srt_path=output_srt_path,
            combined_log_lines=combined_log_lines,
            replacements=replacements,
            duplicate_min_chars=duplicate_min_chars,
            delete_second_content_line=DELETE_SECOND_CONTENT_LINE,
            old_srt_dir=old_srt_dir
        )

    # Ghi file log gộp
    if len(combined_log_lines) > 4:  # Có lỗi (nhiều hơn header)
        os.makedirs(os.path.dirname(combined_log_file), exist_ok=True)
        with open(combined_log_file, "w", encoding="utf-8") as f:
            for line in combined_log_lines:
                f.write(line + "\n")
        print(f"\n📝 Đã ghi log gộp vào: {combined_log_file}")
    else:
        print(f"\n✅ Không có lỗi nào!")
        # Xóa file log cũ nếu có
        try:
            if os.path.exists(combined_log_file):
                os.remove(combined_log_file)
        except OSError:
            pass

    print(f"🎉 Đã xử lý {len(srt_files)} file trong thư mục '{input_folder}'")

# =========================
# CHẠY
# =========================
if __name__ == "__main__":
    process_all_srt_files(
        input_folder=OUTPUTS_DIR,
        output_folder=CLEANED_DIR,
        replacements=REPLACEMENTS,
        duplicate_min_chars=DUPLICATE_MIN_CHARS,
        old_srt_dir=OLD_SRT_DIR
    )
