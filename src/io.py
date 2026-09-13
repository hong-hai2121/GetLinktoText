import os
import shutil

from docx import Document


def clear_output_directory(directory):
    if os.path.exists(directory):
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"⚠️ Lỗi khi xóa {file_path}: {e}")


def read_links_from_candidates(candidates):
    path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not path:
        return None, "", 0

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    link_count = len([l for l in content.splitlines() if l.strip()])
    return path, content, link_count


def write_links(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    link_count = len([l for l in content.splitlines() if l.strip()])
    return link_count


# ── Link chưa lấy được (failed_links.txt): mỗi dòng "link<TAB># lý do" ──────


def _failed_link_key(line):
    return line.split("\t", 1)[0].strip()


def read_failed_lines(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def write_failed_lines(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def upsert_failed_link(path, link, reason=""):
    """Ghi một link lỗi vào file; link đã có sẵn thì chỉ cập nhật lý do."""
    link = (link or "").strip()
    if not link:
        return
    # Lý do có thể chứa xuống dòng (message của exception) -> ép về một dòng
    reason = " ".join(str(reason or "").split())
    if len(reason) > 200:
        reason = reason[:200] + "…"
    entry = f"{link}\t# {reason}" if reason else link

    lines = read_failed_lines(path)
    for i, line in enumerate(lines):
        if _failed_link_key(line) == link:
            lines[i] = entry
            break
    else:
        lines.append(entry)
    write_failed_lines(path, lines)


def remove_failed_links(path, links):
    """Bỏ các link khỏi file lỗi (đã lấy lại thành công / đã đưa về danh sách chạy)."""
    links = {l.strip() for l in links if l and l.strip()}
    if not links:
        return 0
    lines = read_failed_lines(path)
    kept = [line for line in lines if _failed_link_key(line) not in links]
    if len(kept) != len(lines):
        write_failed_lines(path, kept)
    return len(lines) - len(kept)


def read_docx_lines_from_candidates(candidates):
    docx_path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not docx_path:
        return None, []

    doc = Document(docx_path)
    lines = []
    for p in doc.paragraphs:
        t = (p.text or "").rstrip()
        if t:
            lines.append(t)
    return docx_path, lines
