import os, json, shutil, re
from copy import deepcopy

# ========= CẤU HÌNH STYLE CHUNG CHO SUBTITLE =========
STYLE = {
    "types": {"subtitle"},          # muốn áp cho subtitle; thêm "text" nếu cần: {"subtitle","text"}
    "size": 12.0,                   # cỡ chữ
    "text_color_hex": "#FFFFFF",    # màu chữ ngoài
    "text_color_rgb": (1.0, 1.0, 1.0),  # màu chữ dạng 0..1 để ghi vào content

    # font (nếu muốn dùng font hệ thống thì để None)
    "font_path": None,
    "font_resource_id": None,

    # stroke / viền (nếu không cần viền thì để None)
    "stroke_color_rgb": None,
    "stroke_width": None,

    "bold": None,           # True/False nếu muốn ép bold
    "italic_degree": None,  # số nếu muốn ép nghiêng
}

# ========= CẤU HÌNH SỬA CHỮ TIẾNG VIỆT =========
# Các từ/ cụm từ muốn thay cố định (regex, phân biệt từ nguyên bằng \b)
REPLACEMENTS = {
    # ví dụ: số đặc biệt
    r"\bTam\b": "3",

    # sửa viết hoa sai
    r"\bVI\b": "vi",

    # bạn muốn thêm gì thì thêm ở đây, ví dụ:
    # r"\bVI sinh\b": "vi sinh",
    # r"\bTP\b": "TP.",  # v.v...
}

# Các từ viết hoa CHO PHÉP giữ nguyên (acronym)
KEEP_UPPER = {"DNA", "HIV", "AI", "CMH", "USA"}

# Rule theo ngữ cảnh – ví dụ: "men VI sinh" -> "men vi sinh"
CONTEXT_RULES = [
    (
        re.compile(r"(?i)\bmen\s+VI\s+sinh\b"),
        lambda m: m.group(0).lower()   # cả cụm "men vi sinh" đưa về thường
    ),
    # có thể thêm rule khác ở đây
]

# Đường dẫn file danh sách project
PROJECT_LIST_PATH = r"D:\Python\GetLinktoText\SourceTruyen\XulyAmThanh\projects.txt"
# ======================================================


def try_parse_json_string(s):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        return json.loads(s)
    except Exception:
        return None

def dump_json_string(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def normalize_text(txt: str) -> str:
    """Sửa chính tả đơn giản: áp context rules, replacements, rồi hạ hoa không cần thiết."""
    if not isinstance(txt, str) or not txt.strip():
        return txt

    out = txt

    # 1) áp các rule theo ngữ cảnh trước (ví dụ "men VI sinh")
    for rx, repl_fn in CONTEXT_RULES:
        out = rx.sub(repl_fn, out)

    # 2) thay thế theo từ điển regex (Tam -> 3, VI -> vi, ...)
    for pattern, repl in REPLACEMENTS.items():
        out = re.sub(pattern, repl, out, flags=re.UNICODE)

    # 3) hạ chữ hoa toàn từ, trừ acronym trong KEEP_UPPER
    words = re.split(r"(\s+)", out)  # giữ cả khoảng trắng
    fixed = []
    for w in words:
        if w.strip() == "":
            fixed.append(w)
            continue
        # bỏ dấu câu ở 2 đầu để check acronym
        core = re.sub(r"(^\W+|\W+$)", "", w)
        if core.isupper() and core in KEEP_UPPER:
            fixed.append(w)  # giữ nguyên
        elif core.isupper() and len(core) >= 2:
            # ví dụ "VI", "MEN", "SINH" -> vi, men, sinh
            fixed.append(w.replace(core, core.lower()))
        else:
            fixed.append(w)
    out = "".join(fixed)

    return out

def set_style_in_rich_content(content_obj):
    if not isinstance(content_obj, dict):
        return content_obj

    # sửa text chính
    if "text" in content_obj:
        content_obj["text"] = normalize_text(content_obj["text"])

    styles = content_obj.get("styles")
    if isinstance(styles, list):
        for st in styles:
            if not isinstance(st, dict):
                continue

            if STYLE["size"] is not None:
                st["size"] = float(STYLE["size"])

            if STYLE["bold"] is not None:
                st["bold"] = bool(STYLE["bold"])

            if STYLE["italic_degree"] is not None:
                st["italic_degree"] = int(STYLE["italic_degree"])

            if STYLE["text_color_rgb"] is not None:
                r, g, b = STYLE["text_color_rgb"]
                fill = st.setdefault("fill", {})
                fill.setdefault("content", {})
                fill["content"]["render_type"] = "solid"
                fill["content"]["solid"] = {"color": [r, g, b]}
                if "alpha" not in fill:
                    fill["alpha"] = 1.0

            if STYLE["font_path"] is not None or STYLE["font_resource_id"] is not None:
                font = st.setdefault("font", {})
                if STYLE["font_path"] is not None:
                    font["path"] = STYLE["font_path"]
                if STYLE["font_resource_id"] is not None:
                    font["id"] = STYLE["font_resource_id"]

            if STYLE["stroke_color_rgb"] is not None or STYLE["stroke_width"] is not None:
                strokes = st.setdefault("strokes", [])
                if not strokes:
                    strokes.append({})
                for sk in strokes:
                    if not isinstance(sk, dict):
                        continue
                    content = sk.setdefault("content", {})
                    content.setdefault("solid", {})
                    content["render_type"] = "solid"
                    if STYLE["stroke_color_rgb"] is not None:
                        sr, sg, sb = STYLE["stroke_color_rgb"]
                        content["solid"]["color"] = [sr, sg, sb]
                    if STYLE["stroke_width"] is not None:
                        sk["width"] = float(STYLE["stroke_width"])

    return content_obj

def apply_to_item(item):
    if not isinstance(item, dict):
        return item

    t = item.get("type")
    if t not in STYLE["types"]:
        return item

    # sửa recognize_text (text gốc của subtitle)
    if "recognize_text" in item:
        item["recognize_text"] = normalize_text(item["recognize_text"])

    # field ngoài
    if STYLE["size"] is not None:
        item["font_size"] = float(STYLE["size"])

    if STYLE["text_color_hex"] is not None:
        item["text_color"] = STYLE["text_color_hex"]
        item["use_effect_default_color"] = False

    if STYLE["font_path"] is not None:
        item["font_path"] = STYLE["font_path"]
    if STYLE["font_resource_id"] is not None:
        item["font_resource_id"] = STYLE["font_resource_id"]
        item["font_id"] = STYLE["font_resource_id"]

    if STYLE["italic_degree"] is not None:
        item["italic_degree"] = int(STYLE["italic_degree"])
    if STYLE["bold"] is not None:
        item["bold_width"] = 0.008 if STYLE["bold"] else 0.0

    # content + base_content (JSON string)
    for key in ["content", "base_content"]:
        raw = item.get(key)
        parsed = try_parse_json_string(raw)
        if parsed is None:
            continue
        parsed = set_style_in_rich_content(parsed)
        item[key] = dump_json_string(parsed)

    return item

def walk_and_apply(obj):
    if isinstance(obj, dict):
        obj = apply_to_item(obj)
        for k, v in list(obj.items()):
            obj[k] = walk_and_apply(v)
        return obj
    if isinstance(obj, list):
        return [walk_and_apply(x) for x in obj]
    return obj

def find_draft_content_json(project_path):
    direct = os.path.join(project_path, "draft_content.json")
    if os.path.isfile(direct):
        return direct
    for root, dirs, files in os.walk(project_path):
        if "draft_content.json" in files:
            return os.path.join(root, "draft_content.json")
    return None

def process_one_project(project_path):
    project_path = project_path.strip().strip('"')
    if not project_path:
        return

    if not os.path.exists(project_path):
        print(f"[SKIP] Not found: {project_path}")
        return

    json_path = find_draft_content_json(project_path)
    if not json_path:
        print(f"[SKIP] No draft_content.json in: {project_path}")
        return

    backup_path = json_path + ".bak_auto"
    shutil.copy2(json_path, backup_path)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_data = walk_and_apply(deepcopy(data))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False)

    print(f"[OK] Applied style + VN fixes: {json_path}")

def main():
    txt_path = PROJECT_LIST_PATH
    if not os.path.isfile(txt_path):
        raise FileNotFoundError(txt_path)

    with open(txt_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip()]

    print(f"Found {len(lines)} project paths in projects.txt")

    for p in lines:
        process_one_project(p)

    print("DONE batch apply.")

if __name__ == "__main__":
    main()
