# patch_from_logs_bulk.py
# Đọc file log gộp ALL_ERRORS.log có format:
#   FILE: <tên_file.srt>
#   B92 Nội dung đã sửa
# rồi vá vào file tương ứng.

import re, os, shutil
from pathlib import Path

ROOT = Path(r"D:\Python\GetLinktoText\SourceTruyen\Cleaned")  # thư mục chứa .srt
COMBINED_LOG = ROOT / "ALL_ERRORS.log"  # File log gộp

LOG_PATTERN = re.compile(r"^B\s*(\d+)\s+(.*)$", re.UNICODE)   # B699 <text>
FILE_PATTERN = re.compile(r"^FILE:\s*(.+\.srt)\s*$", re.IGNORECASE)  # FILE: <filename>
CJK_RE = re.compile(r"[\u3400-\u9FFF\uF900-\uFAFF]")

def read_combined_log_patches(log_path: Path) -> dict:
    """
    Đọc file log gộp có format:
    FILE: filename.srt
    B123 nội dung
    
    Trả về: {filename: {block_num: text}}
    """
    all_patches = {}
    current_file = None
    
    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("=") or line.startswith("⚠️") or line.startswith("🗑️") or line.startswith("❌") or line.startswith("🔂"):
                continue
            
            # Kiểm tra dòng FILE:
            file_match = FILE_PATTERN.match(line)
            if file_match:
                current_file = file_match.group(1).strip()
                if current_file not in all_patches:
                    all_patches[current_file] = {}
                continue
            
            # Kiểm tra dòng B<số>
            patch_match = LOG_PATTERN.match(line)
            if patch_match and current_file:
                idx = int(patch_match.group(1))
                txt = patch_match.group(2).replace("\\n", "\n").strip()
                all_patches[current_file][idx] = txt
    
    return all_patches

def read_srt_like_blocks(fp: Path):
    """Đọc file phụ đề kiểu SRT: [index][timestamp][lines...]"""
    with fp.open("r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\r\n") for ln in f]
    blocks, cur = [], []
    for ln in lines:
        if ln == "":
            if cur:
                blocks.append(cur); cur = []
        else:
            cur.append(ln)
    if cur: blocks.append(cur)

    parsed = []
    for b in blocks:
        if len(b) < 2:
            continue
        try:
            idx = int(b[0].strip())
        except ValueError:
            continue
        ts = b[1]
        body = b[2:] if len(b) > 2 else []
        parsed.append((idx, ts, body))
    return parsed

def write_srt_like_blocks(fp: Path, blocks):
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for idx, ts, body in blocks:
            f.write(f"{idx}\n{ts}\n")
            for ln in body:
                f.write(f"{ln}\n")
            f.write("\n")
    bak = fp.with_suffix(fp.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(fp, bak)
    tmp.replace(fp)

def patch_one_file(filename: str, patches: dict):
    """Vá các patches vào 1 file SRT cụ thể."""
    target = ROOT / filename
    if not target.exists():
        print(f"… Bỏ qua {filename}: không tìm thấy file")
        return

    if not patches:
        print(f"… {filename}: không có patch.")
        return

    blocks = read_srt_like_blocks(target)
    if not blocks:
        print(f"× {filename}: không đọc được block hợp lệ.")
        return

    index_to_pos = {idx: i for i, (idx, _, _) in enumerate(blocks)}
    total = len(patches); applied = 0; missing = []; cjk_left = []

    for idx, new_text in patches.items():
        pos = index_to_pos.get(idx)
        if pos is None:
            missing.append(idx); continue
        # thay nội dung block
        old_idx, ts, _ = blocks[pos]
        new_lines = new_text.split("\n") if new_text else [""]
        blocks[pos] = (old_idx, ts, new_lines)
        if any(CJK_RE.search(ln or "") for ln in new_lines):
            cjk_left.append(idx)
        applied += 1

    write_srt_like_blocks(target, blocks)
    print(f"✓ {filename}: vá {applied}/{total}. thiếu {missing or '-'}; CJK còn {cjk_left or '-'}")

def main():
    if not COMBINED_LOG.exists():
        print(f"❌ Không tìm thấy file log gộp: {COMBINED_LOG}")
        return
    
    # Đọc tất cả patches theo file
    all_patches = read_combined_log_patches(COMBINED_LOG)
    
    if not all_patches:
        print("Không có patch nào trong file log gộp.")
        return
    
    print(f"📄 Tìm thấy patches cho {len(all_patches)} file")
    
    # Vá từng file
    for filename, patches in all_patches.items():
        patch_one_file(filename, patches)
    
    print("🎉 Hoàn tất.")

if __name__ == "__main__":
    main()
