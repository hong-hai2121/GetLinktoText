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
