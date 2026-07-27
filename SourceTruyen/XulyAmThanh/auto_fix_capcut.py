import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading


def center_on_screen(win, w=None, h=None):
    """Đưa cửa sổ ra giữa màn hình; bỏ trống w/h thì giữ kích thước hiện tại."""
    win.update_idletasks()
    w = w or max(win.winfo_width(), win.winfo_reqwidth())
    h = h or max(win.winfo_height(), win.winfo_reqheight())
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(w, sw), min(h, sh)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


# =========================
# Đọc danh sách project từ projects.txt
# =========================

def load_projects_list(list_file: Path):
    """Đọc mỗi dòng trong projects.txt là một đường dẫn thư mục project."""
    projects = []
    with list_file.open("r", encoding="utf-8") as f:
        for line in f:
            path = line.strip()
            if not path:
                continue
            projects.append(Path(path))
    return projects


def load_draft_content(project_dir: Path):
    """Đọc draft_content.json trong thư mục project."""
    draft_path = project_dir / "draft_content.json"
    with draft_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data, draft_path


# =========================
# Tính biên phải của timeline (timeline_end)
# =========================

def get_timeline_end(data):
    """
    Lấy thời điểm kết thúc lớn nhất của toàn bộ segment
    (video + audio) trong project.
    """
    max_end = 0
    tracks = data.get("tracks", [])
    for track in tracks:
        for seg in track.get("segments", []):
            tr = seg.get("target_timerange")
            if not tr:
                continue
            end = tr["start"] + tr["duration"]
            if end > max_end:
                max_end = end
    return max_end


# =========================
# Hàm kiểm tra overlap
# =========================

def is_overlap(seg_a, seg_b):
    """Kiểm tra 2 segment có đè nhau không (theo target_timerange)."""
    a = seg_a["target_timerange"]
    b = seg_b["target_timerange"]

    startA, endA = a["start"], a["start"] + a["duration"]
    startB, endB = b["start"], b["start"] + b["duration"]

    return max(startA, startB) < min(endA, endB)


# =========================
# Các hàm dời block
# =========================

def shift_suffix_right(segments, start_index, amount, timeline_end):
    """
    Dời cả block segments[start_index .. cuối] sang phải 'amount',
    không cho segment cuối cùng vượt quá timeline_end.
    Trả về lượng dịch thực tế.
    """
    if amount <= 0 or start_index >= len(segments):
        return 0

    block = segments[start_index:]
    # end lớn nhất trong block
    max_end_block = max(
        s["target_timerange"]["start"] + s["target_timerange"]["duration"]
        for s in block
    )
    max_shift = max(0, timeline_end - max_end_block)
    shift = min(amount, max_shift)

    if shift <= 0:
        return 0

    for s in block:
        s["target_timerange"]["start"] += shift

    return shift


def shift_prefix_left(segments, end_index, amount, min_start=0):
    """
    Dời cả block segments[0 .. end_index] sang trái 'amount',
    không cho segment đầu tiên có start < min_start (thường là 0).
    Trả về lượng dịch thực tế.
    """
    if amount <= 0 or end_index < 0:
        return 0

    block = segments[: end_index + 1]
    min_start_block = min(
        s["target_timerange"]["start"]
        for s in block
    )
    max_shift = max(0, min_start_block - min_start)
    shift = min(amount, max_shift)

    if shift <= 0:
        return 0

    for s in block:
        s["target_timerange"]["start"] -= shift

    return shift

def shift_block_right(segments, start_index, block_len, amount, timeline_end):
    """
    Dời một block liên tiếp bên phải:
      segments[start_index .. start_index + block_len - 1]
    sang phải 'amount', không vượt timeline_end và không đè segment kế tiếp.
    Trả về lượng dịch thực tế.
    """
    n = len(segments)
    if amount <= 0 or start_index >= n:
        return 0

    end_index = min(start_index + block_len - 1, n - 1)
    if end_index < start_index:
        return 0

    block = segments[start_index: end_index + 1]

    # Biên phải: không vượt timeline_end
    max_end_block = max(
        s["target_timerange"]["start"] + s["target_timerange"]["duration"]
        for s in block
    )
    max_shift = timeline_end - max_end_block

    # Tránh đè segment ngay sau block (nếu có)
    if end_index < n - 1:
        next_seg = segments[end_index + 1]
        next_start = next_seg["target_timerange"]["start"]
        last_seg = segments[end_index]
        last_end = last_seg["target_timerange"]["start"] + last_seg["target_timerange"]["duration"]
        max_shift = min(max_shift, next_start - last_end)

    max_shift = max(0, max_shift)
    shift = min(amount, max_shift)

    if shift <= 0:
        return 0

    for s in block:
        s["target_timerange"]["start"] += shift

    return shift


def shift_block_left(segments, end_index, block_len, amount, min_start=0):
    """
    Dời một block liên tiếp bên trái:
      segments[end_index - block_len + 1 .. end_index]
    sang trái 'amount', không cho segment đầu tiên < min_start
    và không đè segment ngay trước block.
    Trả về lượng dịch thực tế.
    """
    n = len(segments)
    if amount <= 0 or end_index < 0:
        return 0

    end_index = min(end_index, n - 1)
    start_index = max(0, end_index - block_len + 1)
    if start_index > end_index:
        return 0

    block = segments[start_index: end_index + 1]

    # Biên trái: không < min_start
    min_start_block = min(
        s["target_timerange"]["start"]
        for s in block
    )
    max_shift = min_start_block - min_start

    # Tránh đè segment ngay trước block (nếu có)
    if start_index > 0:
        prev_seg = segments[start_index - 1]
        prev_end = prev_seg["target_timerange"]["start"] + prev_seg["target_timerange"]["duration"]
        first_seg = segments[start_index]
        first_start = first_seg["target_timerange"]["start"]
        max_shift = min(max_shift, first_start - prev_end)

    max_shift = max(0, max_shift)
    shift = min(amount, max_shift)

    if shift <= 0:
        return 0

    for s in block:
        s["target_timerange"]["start"] -= shift

    return shift

# =========================
# Xử lý 1 cặp C, D với ưu tiên 1–4
# =========================

def resolve_pair_with_blocks(segments, idx, timeline_end):
    """
    Xử lý cặp (C = segments[idx], D = segments[idx+1]) theo luật:

      Có A B C D E F (…):
        1. Đẩy D qua phải (1 audio bên phải)
        2. Nếu còn đè, đẩy C qua trái (1 audio bên trái)
        3. Nếu vẫn còn, đẩy block D,E (2 audio bên phải)
        4. Nếu vẫn còn, đẩy block C,B (2 audio bên trái)
        5. Nếu vẫn còn, đẩy block D,E,F (3 audio bên phải)
           rồi block C,B,A (3 audio bên trái)
        ...

      Ràng buộc:
        - Segment đầu tiên không < 0
        - Segment cuối cùng không > timeline_end

      Trả về True nếu có thay đổi.
    """
    if idx < 0 or idx + 1 >= len(segments):
        return False

    C = segments[idx]
    D = segments[idx + 1]

    def overlap():
        return is_overlap(C, D)

    if not overlap():
        return False

    changed = False

    # Số lượng segment mỗi bên
    left_count = idx + 1          # A..C
    right_count = len(segments) - (idx + 1)  # D..F..
    max_k = max(left_count, right_count)

    for k in range(1, max_k + 1):
        moved_this_k = False

        # ----------------------
        # Bước k: ĐẨY BLOCK BÊN PHẢI (D, E, ..., độ dài k)
        # ----------------------
        if overlap() and right_count >= k:
            c_tr = C["target_timerange"]
            d_tr = D["target_timerange"]
            endC = c_tr["start"] + c_tr["duration"]
            startD = d_tr["start"]
            need = endC - startD  # >0 thì đang đè

            if need > 0:
                used = shift_block_right(
                    segments, idx + 1, k, need, timeline_end
                )
                if used > 0:
                    changed = True
                    moved_this_k = True

        if not overlap():
            return changed

        # ----------------------
        # Bước k: ĐẨY BLOCK BÊN TRÁI (C, B, ..., độ dài k)
        # ----------------------
        if overlap() and left_count >= k:
            c_tr = C["target_timerange"]
            d_tr = D["target_timerange"]
            endC = c_tr["start"] + c_tr["duration"]
            startD = d_tr["start"]
            need = endC - startD

            if need > 0:
                used = shift_block_left(
                    segments, idx, k, need, min_start=0
                )
                if used > 0:
                    changed = True
                    moved_this_k = True

        if not overlap():
            return changed

        # Nếu với block size k mà không đẩy được gì thì
        # thử tăng k, không làm gì thêm ở vòng này.
        if not moved_this_k:
            continue

    # Hết mọi k mà vẫn còn overlap thì đành chịu,
    # nhưng nếu có đẩy được gì trong quá trình thì vẫn trả về True.
    return changed

# =========================
# Gom toàn bộ audio segments trên mọi track audio
# =========================

def collect_all_audio_segments(data):
    """
    Gom tất cả segment của các track type = 'audio'
    (mọi track_render_index: 1, 2, 3, ...).
    """
    segments = []
    tracks = data.get("tracks", [])
    audio_track_count = 0

    for track in tracks:
        if track.get("type") != "audio":
            continue
        audio_track_count += 1
        for s in track.get("segments", []):
            if s.get("visible", True) and "target_timerange" in s:
                segments.append(s)

    print(f"  Tìm thấy {audio_track_count} track audio với {len(segments)} segment.")
    return segments


# =========================
# Xử lý tất cả audio (đa vòng)
# =========================

def process_all_audio_segments(data, timeline_end):
    """
    Xử lý overlap cho toàn bộ audio segments trên tất cả track audio
    theo chiến lược nhiều vòng:

      - Vòng ngoài: lặp lại cho đến khi không còn thay đổi
      - Trong mỗi vòng:
          * Sort theo start
          * Quét từng cặp (C, D) liên tiếp
          * Nếu overlap -> gọi resolve_pair_with_blocks
          * Nếu có thay đổi -> break, sort lại ở vòng sau
    """
    segments = collect_all_audio_segments(data)
    if len(segments) <= 1:
        print("  Ít hơn 2 segment audio, bỏ qua.")
        return False

    MAX_ITER = 300
    for iteration in range(1, MAX_ITER + 1):
        segments.sort(key=lambda s: s["target_timerange"]["start"])
        changed_any = False

        # dùng snapshot để phát hiện case "không đổi gì"
        before_positions = [
            s["target_timerange"]["start"] for s in segments
        ]

        for i in range(len(segments) - 1):
            C = segments[i]
            D = segments[i + 1]

            if not is_overlap(C, D):
                continue

            print(f"  [Vòng {iteration}] Xử lý cặp overlap {C.get('id')} & {D.get('id')}")
            if resolve_pair_with_blocks(segments, i, timeline_end):
                changed_any = True
                break  # sort lại rồi xử tiếp ở vòng sau

        after_positions = [
            s["target_timerange"]["start"] for s in segments
        ]

        if not changed_any or after_positions == before_positions:
            print("  Không còn thay đổi, dừng.")
            return True

    print("  ⚠ Đạt MAX_ITER, dừng để tránh lặp vô tận.")
    return True

def set_segment_volume_only(
    data,
    target_volume=2.818382740020754,
    only_track_render_index=2
):
    """
    CHỈ chỉnh seg["volume"] trong tracks[].segments[]
    - Chỉ áp dụng cho segment có track_render_index = only_track_render_index
    - Không chỉnh bất kỳ field nào khác
    """
    changed = 0

    for track in data.get("tracks", []):
        for seg in track.get("segments", []):
            if not isinstance(seg, dict):
                continue

            # chỉ đúng audio segment mong muốn
            tri = seg.get("track_render_index")
            if tri is None or tri < only_track_render_index:
                continue


            if "volume" not in seg:
                continue

            try:
                current = float(seg["volume"])
            except Exception:
                continue

            # nếu volume khác target thì set
            if abs(current - target_volume) > 1e-12:
                seg["volume"] = float(target_volume)
                changed += 1

    print(f"  Volume: set {changed} segment -> volume = {target_volume}")
    return changed > 0

def set_video_track_attribute_and_volume(
    data,
    target_track_attribute=1,
    target_attribute=1,
    target_volume=0.0,
    only_track_type="video",
):
    """
    Set 3 field theo yêu cầu:
      - track["attribute"] = 1
      - segment["track_attribute"] = 1
      - segment["volume"] = 0.0

    Mặc định chỉ áp dụng cho track có type="video".
    """
    track_changed = 0
    seg_changed = 0

    for track in data.get("tracks", []):
        if not isinstance(track, dict):
            continue

        if only_track_type and track.get("type") != only_track_type:
            continue

        # 1) track.attribute
        if "attribute" in track:
            if track.get("attribute") != target_attribute:
                track["attribute"] = int(target_attribute)
                track_changed += 1

        # 2) segments: track_attribute + volume
        for seg in track.get("segments", []):
            if not isinstance(seg, dict):
                continue

            if "track_attribute" in seg and seg.get("track_attribute") != target_track_attribute:
                seg["track_attribute"] = int(target_track_attribute)
                seg_changed += 1

            if "volume" in seg:
                try:
                    cur = float(seg["volume"])
                except Exception:
                    continue
                if abs(cur - float(target_volume)) > 1e-12:
                    seg["volume"] = float(target_volume)
                    seg_changed += 1

    print(
        f"  VideoFlags: updated {track_changed} track(s) attribute -> {target_attribute}; "
        f"updated {seg_changed} segment field(s) (track_attribute/volume)."
    )
    return (track_changed + seg_changed) > 0

def apply_agbalumo_font_keep_colors(data):
    """
    GIỮ THEO TỪNG OBJECT:
      - content.text (mỗi object khác nhau)  ✅ giữ nguyên
      - styles[*].range (mỗi object khác nhau) ✅ giữ nguyên

    KHÔNG ĐỤNG:
      - fill màu chữ, strokes viền, alpha, width, ... trong content.styles

    CHỈ SET CỐ ĐỊNH:
      - content.styles[*].font.path / font.id
      - content.styles[*].size = 7.0
      - content.styles[*].useLetterColor = True

    OUTER (chỉ set nếu key tồn tại):
      - font_path, font_resource_id, font_size, font_source_platform, fonts
      - text_color, background_color, border_color, check_flag, fixed_width
    """

    # ====== FONT TEMPLATE ======
    TEMPLATE_FONT_PATH = r"C:/Users/PC/AppData/Local/CapCut/User Data/Cache/effect/7298970759609733634/9a37fa0c0e52ed421ae119a3402dd75a/Agbalumo.ttf"
    TEMPLATE_FONT_RESOURCE_ID = "7298970759609733634"
    TEMPLATE_FONT_SIZE = 7.0
    TEMPLATE_FONT_SOURCE_PLATFORM = 1

    TEMPLATE_FONTS_ITEM = {
        "category_id": "favoured",
        "category_name": "Yêu thích",
        "effect_id": TEMPLATE_FONT_RESOURCE_ID,
        "file_uri": "",
        "path": TEMPLATE_FONT_PATH,
        "request_id": "",
        "resource_id": TEMPLATE_FONT_RESOURCE_ID,
        "source_platform": TEMPLATE_FONT_SOURCE_PLATFORM,
        "team_id": "",
        "third_resource_id": "",
        "title": "Agbalumo",
    }

    # ====== OUTER TARGETS (đổi nếu muốn) ======
    TARGET_TEXT_COLOR = "#00ff18"
    TARGET_BACKGROUND_COLOR = "#000000"
    TARGET_BORDER_COLOR = "#ffffff"
    TARGET_CHECK_FLAG = 15
    TARGET_FIXED_WIDTH = 717.0505142211914

    def looks_like_text_content_json(s):
        # content kiểu string-json chứa "text" và "styles"
        return isinstance(s, str) and ("\"text\"" in s) and ("\"styles\"" in s)

    changed = 0

    def walk(obj):
        nonlocal changed

        if isinstance(obj, dict):
            # ===== TEXT NODE =====
            if "content" in obj and looks_like_text_content_json(obj["content"]):
                try:
                    inner = json.loads(obj["content"])
                except Exception:
                    inner = None

                if (
                    isinstance(inner, dict)
                    and isinstance(inner.get("text"), str)
                    and isinstance(inner.get("styles"), list)
                ):
                    styles = inner["styles"]
                    style_changed = False

                    # ✅ GIỮ inner["text"] nguyên
                    # ✅ GIỮ styles[*].range nguyên

                    for st in styles:
                        if not isinstance(st, dict):
                            continue

                        # ensure font dict exists
                        font = st.get("font")
                        if not isinstance(font, dict):
                            font = {}
                            st["font"] = font
                            style_changed = True

                        # set font path/id
                        if font.get("path") != TEMPLATE_FONT_PATH:
                            font["path"] = TEMPLATE_FONT_PATH
                            style_changed = True

                        if font.get("id") != TEMPLATE_FONT_RESOURCE_ID:
                            font["id"] = TEMPLATE_FONT_RESOURCE_ID
                            style_changed = True

                        # force size = 7.0 (không đụng range)
                        if not isinstance(st.get("size"), (int, float)) or float(st["size"]) != float(TEMPLATE_FONT_SIZE):
                            st["size"] = float(TEMPLATE_FONT_SIZE)
                            style_changed = True

                        # ensure useLetterColor = True
                        if st.get("useLetterColor") is not True:
                            st["useLetterColor"] = True
                            style_changed = True

                        # ❗ KHÔNG đụng fill / strokes / alpha / range

                    if style_changed:
                        # dump lại content; nội dung text/range vẫn giữ nguyên
                        obj["content"] = json.dumps(inner, ensure_ascii=False, separators=(",", ":"))
                        changed += 1

                    # ===== OUTER FIELDS (chỉ set nếu key tồn tại) =====
                    outer_changed = False

                    if "font_path" in obj and obj.get("font_path") != TEMPLATE_FONT_PATH:
                        obj["font_path"] = TEMPLATE_FONT_PATH
                        outer_changed = True

                    if "font_resource_id" in obj and obj.get("font_resource_id") != TEMPLATE_FONT_RESOURCE_ID:
                        obj["font_resource_id"] = TEMPLATE_FONT_RESOURCE_ID
                        outer_changed = True

                    if "font_size" in obj:
                        try:
                            if float(obj.get("font_size")) != float(TEMPLATE_FONT_SIZE):
                                obj["font_size"] = float(TEMPLATE_FONT_SIZE)
                                outer_changed = True
                        except Exception:
                            obj["font_size"] = float(TEMPLATE_FONT_SIZE)
                            outer_changed = True

                    if "font_source_platform" in obj:
                        try:
                            if int(obj.get("font_source_platform")) != int(TEMPLATE_FONT_SOURCE_PLATFORM):
                                obj["font_source_platform"] = int(TEMPLATE_FONT_SOURCE_PLATFORM)
                                outer_changed = True
                        except Exception:
                            obj["font_source_platform"] = int(TEMPLATE_FONT_SOURCE_PLATFORM)
                            outer_changed = True

                    # fonts list: giữ id cũ nếu có
                    if "fonts" in obj:
                        existing_font_id = None
                        if isinstance(obj.get("fonts"), list) and obj["fonts"]:
                            f0 = obj["fonts"][0]
                            if isinstance(f0, dict) and isinstance(f0.get("id"), str) and f0["id"]:
                                existing_font_id = f0["id"]

                        font_item = dict(TEMPLATE_FONTS_ITEM)
                        font_item["id"] = existing_font_id or ""

                        if obj.get("fonts") != [font_item]:
                            obj["fonts"] = [font_item]
                            outer_changed = True

                    # các field màu/flag/width: chỉ set nếu key tồn tại
                    if "text_color" in obj and obj.get("text_color") != TARGET_TEXT_COLOR:
                        obj["text_color"] = TARGET_TEXT_COLOR
                        outer_changed = True

                    if "background_color" in obj and obj.get("background_color") != TARGET_BACKGROUND_COLOR:
                        obj["background_color"] = TARGET_BACKGROUND_COLOR
                        outer_changed = True

                    if "border_color" in obj and obj.get("border_color") != TARGET_BORDER_COLOR:
                        obj["border_color"] = TARGET_BORDER_COLOR
                        outer_changed = True

                    if "check_flag" in obj and obj.get("check_flag") != TARGET_CHECK_FLAG:
                        obj["check_flag"] = TARGET_CHECK_FLAG
                        outer_changed = True

                    if "fixed_width" in obj:
                        try:
                            if float(obj.get("fixed_width")) != float(TARGET_FIXED_WIDTH):
                                obj["fixed_width"] = float(TARGET_FIXED_WIDTH)
                                outer_changed = True
                        except Exception:
                            obj["fixed_width"] = float(TARGET_FIXED_WIDTH)
                            outer_changed = True

                    if outer_changed and not style_changed:
                        changed += 1

            # recurse
            for v in obj.values():
                walk(v)

        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(data)
    print(f"  TextFontKeepColor: updated {changed} node(s)")
    return changed > 0

# =========================
# Xử lý từng project
# =========================

def process_project(project_dir: Path, backup=True):
    print(f"\n===== Xử lý project: {project_dir} =====")

    # 1️⃣ ĐỌC FILE draft_content.json
    data, draft_path = load_draft_content(project_dir)

    # 2️⃣ BACKUP FILE (nếu cần) — backup TRƯỚC khi chỉnh sửa
    if backup:
        backup_path = draft_path.with_suffix(".json.bak")
        if not backup_path.exists():
            backup_path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8"
            )

    # 3️⃣ TÍNH BIÊN TIMELINE ĐỂ XỬ LÝ CHỒNG LẤN AUDIO
    timeline_end = get_timeline_end(data)

    # 4️⃣ ÁP TEMPLATE FONT/STYLE CHO TOÀN BỘ TEXT (GIỮ NGUYÊN TEXT)
    text_template_changed = apply_agbalumo_font_keep_colors(data)

    # 5️⃣ ĐỔI 3 FIELD VIDEO: attribute / track_attribute / volume
    video_flags_changed = set_video_track_attribute_and_volume(
        data,
        target_track_attribute=1,
        target_attribute=1,
        target_volume=0.0,
        only_track_type="video",
    )

    # 6️⃣ SẮP XẾP/DỜI AUDIO TRÁNH ĐÈ LÊN NHAU
    audio_fixed = process_all_audio_segments(data, timeline_end)

    # 7️⃣ CHỈNH VOLUME (BƯỚC CŨ CỦA BẠN)
    volume_changed = set_segment_volume_only(
        data,
        target_volume=2.818382740020754,
        only_track_render_index=2
    )

    # 6️⃣ GHI LẠI FILE CHỈ KHI CÓ THAY ĐỔI
    if volume_changed or video_flags_changed or text_template_changed or audio_fixed:
        draft_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("  ✅ Đã cập nhật draft_content.json")
    else:
        print("  ⚠ Không có thay đổi nào cần ghi")



# =========================
# Hàm main
# =========================

import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import threading

BASE_PROJECT_DIR = Path(
    r"C:\Users\PC\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft"
)

def launch_gui():
    root = tk.Tk()
    root.title("CapCut Project Processor")
    center_on_screen(root, 780, 520)
    root.resizable(False, False)

    style = ttk.Style()
    style.theme_use("default")

    projects = []

    # ===== HEADER =====
    header = ttk.Label(
        root,
        text="CapCut Project Processor",
        font=("Segoe UI", 14, "bold")
    )
    header.pack(pady=12)

    # ===== MAIN FRAME =====
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)

    # ===== SELECT BUTTON =====
    def select_project():
        DEFAULT_DIR = r"C:\Users\PC\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft"

        # Select multiple draft_content.json files
        selected_files = filedialog.askopenfilenames(
            title="Chọn file draft_content.json từ các project CapCut (Ctrl/Shift để chọn nhiều)",
            initialdir=DEFAULT_DIR,
            filetypes=[("Draft Content", "draft_content.json"), ("All Files", "*.*")]
        )
        if not selected_files:
            return

        added_count = 0
        duplicates = 0
        invalid = 0

        for file_path in selected_files:
            p = Path(file_path).parent  # Get parent directory as project folder
            
            # Validate draft_content.json exists
            if not (p / "draft_content.json").exists():
                invalid += 1
                continue

            # Check for duplicates
            if p in projects:
                duplicates += 1
                continue

            projects.append(p)
            listbox.insert(tk.END, p.as_posix())
            added_count += 1

        # Show result summary
        if added_count > 0:
            msg = f"✅ Thêm {added_count} project"
            if duplicates > 0:
                msg += f"\n⚠️ {duplicates} project trùng (bỏ qua)"
            if invalid > 0:
                msg += f"\n❌ {invalid} file không hợp lệ (bỏ qua)"
            messagebox.showinfo("Kết quả", msg)
        else:
            if duplicates > 0:
                messagebox.showwarning("Trùng", "Tất cả project đã tồn tại trong danh sách")
            else:
                messagebox.showerror("Lỗi", "Không có file draft_content.json hợp lệ")

    def scan_parent_folder():
        DEFAULT_DIR = r"C:\Users\PC\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft"

        parent_path = filedialog.askdirectory(
            title="Chọn thư mục cha chứa nhiều project CapCut",
            initialdir=DEFAULT_DIR
        )
        if not parent_path:
            return

        parent = Path(parent_path)
        if not parent.is_dir():
            messagebox.showerror("Sai thư mục", "Đường dẫn không phải thư mục")
            return

        added_count = 0
        duplicates = 0
        invalid = 0

        for child in parent.iterdir():
            if not child.is_dir():
                continue
            draft_file = child / "draft_content.json"
            if not draft_file.exists():
                invalid += 1
                continue
            if child in projects:
                duplicates += 1
                continue
            projects.append(child)
            listbox.insert(tk.END, child.as_posix())
            added_count += 1

        if added_count > 0:
            msg = f"✅ Thêm {added_count} project"
            if duplicates > 0:
                msg += f"\n⚠️ {duplicates} project trùng (bỏ qua)"
            if invalid > 0:
                msg += f"\n❌ {invalid} thư mục không có draft_content.json"
            messagebox.showinfo("Kết quả", msg)
        else:
            if duplicates > 0:
                messagebox.showwarning("Trùng", "Tất cả project đã tồn tại trong danh sách")
            else:
                messagebox.showerror("Lỗi", "Không tìm thấy project hợp lệ trong thư mục đã chọn")

    ttk.Button(
        frame,
        text="📂 Select Project Folder",
        command=select_project
    ).pack(anchor="w", pady=6)

    ttk.Button(
        frame,
        text="📂 Quét thư mục cha (nhiều project)",
        command=scan_parent_folder
    ).pack(anchor="w", pady=6)

    # ===== LISTBOX + SCROLL =====
    list_frame = ttk.Frame(frame)
    list_frame.pack(fill="both", expand=True)

    scrollbar = ttk.Scrollbar(list_frame)
    scrollbar.pack(side="right", fill="y")

    listbox = tk.Listbox(
        list_frame,
        font=("Consolas", 10),
        yscrollcommand=scrollbar.set,
        selectmode=tk.EXTENDED,
        height=14
    )
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=listbox.yview)

    # ===== ACTION BUTTONS =====
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill="x", pady=10)

    def remove_selected():
        sel = listbox.curselection()
        if not sel:
            return
        for i in reversed(sel):
            listbox.delete(i)
            projects.pop(i)

    def edit_selected():
        sel = listbox.curselection()
        if len(sel) != 1:
            messagebox.showwarning("Chọn 1", "Chỉ chọn 1 project để sửa")
            return

        new_path = filedialog.askdirectory(
            title="Chọn project mới để thay thế"
        )
        if not new_path:
            return

        p = Path(new_path)
        if not (p / "draft_content.json").exists():
            messagebox.showerror("Sai project", "Không có draft_content.json")
            return

        idx = sel[0]
        projects[idx] = p
        listbox.delete(idx)
        listbox.insert(idx, p.as_posix())

    def run_projects():
        if not projects:
            messagebox.showwarning("Trống", "Chưa có project nào")
            return

        def worker():
            for p in projects:
                try:
                    process_project(p)
                except Exception as e:
                    print(f"❌ Lỗi {p}: {e}")
            messagebox.showinfo("Xong", "Đã xử lý xong tất cả project")

        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(btn_frame, text="➕ Add", command=select_project).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="✏️ Edit", command=edit_selected).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="❌ Remove", command=remove_selected).pack(side="left", padx=5)

    ttk.Button(
        btn_frame,
        text="▶ Run",
        command=run_projects
    ).pack(side="right", padx=5)

    root.mainloop()

if __name__ == "__main__":
    launch_gui()

