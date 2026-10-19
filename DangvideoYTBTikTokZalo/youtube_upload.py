# -*- coding: utf-8 -*-
"""Tự động đăng video lên YouTube Studio qua CDP (Playwright).

Luồng: mở trang upload -> chọn file -> điền tiêu đề/mô tả -> chọn danh sách phát
-> điền thẻ -> chọn đối tượng trẻ em -> Tiếp (x3) -> chế độ hiển thị -> chờ tải
xong -> Lưu/Xuất bản.
Các selector dùng id ổn định của Studio, chữ hiển thị bắt cả tiếng Việt lẫn Anh.
"""
import os
import re
import time
from datetime import date, datetime, timedelta

UPLOAD_URL = "https://www.youtube.com/upload"
STUDIO_URL = "https://studio.youtube.com/"

MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_EN_FULL = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"]

# JS tìm ô <input type=file> của Studio, xuyên qua shadow DOM (document.querySelector thường không thấy)
_FIND_FILE_INPUT_JS = """(() => {
  const deep = (root, sel) => {
    const hit = root.querySelector(sel);
    if (hit) return hit;
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) { const r = deep(el.shadowRoot, sel); if (r) return r; }
    }
    return null;
  };
  const picker = deep(document, 'ytcp-uploads-file-picker');
  return (picker && deep(picker, 'input[type=file]')) || deep(document, 'input[type=file]');
})()"""


def _set_file_via_cdp(video_path, log):
    """Nạp file bằng DOM.setFileInputFiles gửi thẳng qua relay (không giới hạn 50 MB).

    Playwright từ chối chuyển file lớn tới trình duyệt nó coi là 'không cùng máy'
    (connect_over_cdp). Gửi ĐƯỜNG DẪN file qua CDP — đúng cách Playwright làm với trình duyệt
    cục bộ — thì không giới hạn; cần extension được bật 'Cho phép truy cập URL tệp'."""
    from chrome_cdp import cdp_send
    res = cdp_send("Runtime.evaluate", {"expression": _FIND_FILE_INPUT_JS, "returnByValue": False})
    obj = (res or {}).get("result") or {}
    if not obj.get("objectId"):
        raise RuntimeError("không tìm thấy ô chọn tệp trên trang upload")
    try:
        cdp_send("DOM.setFileInputFiles",
                 {"objectId": obj["objectId"], "files": [os.path.abspath(video_path)]})
    except Exception as e:
        if "Not allowed" in str(e):
            raise RuntimeError("Chrome từ chối đọc file (Not allowed) — hãy bật 'Cho phép truy cập "
                               "URL tệp' cho Playwright Extension trong chrome://extensions") from e
        raise


def _log_default(msg):
    print(msg)


def _dismiss_popups(page):
    """Đóng các hộp thoại vặt nếu có (nhắc nhở, giới thiệu tính năng...)."""
    for sel in [
        'ytcp-auth-confirmation-dialog ytcp-button',
        'tp-yt-paper-dialog #dismiss-button',
        'ytcp-button#dismiss-button',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=300):
                loc.click(timeout=1000)
        except Exception:
            pass


def _check_logged_in(page, log):
    """Nếu bị đưa về trang đăng nhập Google thì báo lỗi rõ ràng."""
    if "accounts.google.com" in page.url:
        raise RuntimeError(
            "Profile Chrome này chưa đăng nhập YouTube. Hãy đăng nhập Google ngay trong "
            "tab Chrome đang mở (chỉ cần 1 lần, Chrome sẽ ghi nhớ) rồi bấm Đăng lại.")


def _fill_textbox(page, container_ids, text, log):
    """container_ids: các ID có thể của ô nhập (Studio đổi ID theo thời gian: title-textbox ->
    title-textarea); khớp cái nào có trong DOM thì dùng."""
    sel = ", ".join(f'ytcp-uploads-dialog #{cid} #textbox' for cid in container_ids)
    box = page.locator(sel).first
    box.wait_for(state="visible", timeout=60000)
    # Studio tự điền tên file vào tiêu đề -> xoá sạch và KIỂM TRA trống trước khi gõ (dang_common.clear_field)
    from dang_common import clear_field
    clear_field(page, box, log, "ô " + container_ids[0])
    box.fill(text)
    page.wait_for_timeout(300)
    got = " ".join(box.inner_text().split())
    if not got.startswith(" ".join(text.split())[:40]):
        # fill không ăn (hiếm) -> gõ lại bằng insert_text
        clear_field(page, box, log, "ô " + container_ids[0])
        page.keyboard.insert_text(text)


def _norm(s):
    """Chuẩn hoá tên để so khớp: thường hoá, bỏ dấu câu/gạch nối, gộp khoảng trắng
    ('Dạ Dày - Tiêu Hóa' == 'dạ dày tiêu hóa')."""
    return re.sub(r"[\W_]+", " ", (s or "").lower(), flags=re.UNICODE).strip()


def _pick_playlist(page, name, log):
    log(f"Chọn danh sách phát: {name}")
    trig = page.locator(
        'ytcp-video-metadata-playlists ytcp-dropdown-trigger, '
        'ytcp-video-metadata-playlists ytcp-text-dropdown-trigger').first
    trig.scroll_into_view_if_needed()
    trig.click()

    # Host <ytcp-playlist-dialog> cao 0px -> chờ hộp thoại bên trong nó
    dialog = page.locator('ytcp-playlist-dialog tp-yt-paper-dialog#dialog').first
    dialog.wait_for(state="visible", timeout=15000)

    # Mỗi dòng: <ytcp-ve>tên</ytcp-ve> + <ytcp-checkbox-lit id="checkbox-N">, theo thứ tự.
    # Danh sách tải về sau khi hộp thoại mở -> chờ dòng đầu tiên thay vì ngủ cố định.
    rows = dialog.locator('#playlists-list ytcp-ve')
    try:
        rows.first.wait_for(state="attached", timeout=15000)
    except Exception:
        snippet = re.sub(r"\s+", " ", dialog.inner_text(timeout=2000))[:300]
        raise RuntimeError(f"Hộp thoại playlist không hiện danh sách. Nội dung thấy được: {snippet!r}")
    page.wait_for_timeout(300)
    names = [t.strip() for t in rows.all_inner_texts()]
    want = _norm(name)
    idx = next((i for i, n in enumerate(names) if _norm(n) == want), None)
    if idx is None:  # khớp một phần
        cands = [i for i, n in enumerate(names) if want and (want in _norm(n) or _norm(n) in want)]
        if cands:
            idx = cands[0]
            if len(cands) > 1:
                log(f"  (có {len(cands)} playlist gần giống, lấy: {names[idx]})")
    if idx is None:
        raise RuntimeError(f"Không tìm thấy danh sách phát '{name}'. Kênh đang có: "
                           + "; ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
    if _norm(names[idx]) != want:
        log(f"  Khớp gần đúng: '{names[idx]}'")

    box = dialog.locator(f'#checkbox-{idx}').first
    if box.count():
        box.scroll_into_view_if_needed()
        box.click()
    else:
        rows.nth(idx).click()
    page.wait_for_timeout(400)

    done = dialog.locator('ytcp-button.done-button').or_(
        dialog.locator('ytcp-button', has_text=re.compile(r"^\s*(Xong|Done)\s*$", re.I)))
    done.first.click()
    page.wait_for_timeout(800)
    try:
        chosen = trig.inner_text(timeout=3000).strip()
        log(f"✓ Đã chọn danh sách phát: {chosen or names[idx]}")
    except Exception:
        log("✓ Đã chọn danh sách phát.")


TAGS_LIMIT = 500  # Studio: tổng ký tự của mọi thẻ, hiện ở #tags-count dạng "527/500"


def _tags_count(container):
    """Đọc bộ đếm '<đã dùng>/<giới hạn>' dưới ô thẻ. Trả về (đã dùng, giới hạn); không đọc được -> (None, 500)."""
    try:
        txt = container.locator('#tags-count').first.inner_text(timeout=2000)
        m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, TAGS_LIMIT


def _remove_last_tag(page, container, tag_input):
    """Gỡ thẻ (chip) cuối cùng; trả về True nếu bộ đếm thực sự giảm."""
    before, _ = _tags_count(container)
    for cach in ("nut-x-tren-chip", "backspace", "backspace"):
        try:
            if cach == "nut-x-tren-chip":
                chip = container.locator('ytcp-chip, ytcp-free-text-chip, .chip').last
                if chip.count() == 0:
                    continue
                btn = chip.locator('ytcp-icon-button, button').first
                if btn.count() == 0:
                    continue
                btn.click(timeout=2000)
            else:
                # Chip bar: Backspace trong ô trống xoá chip cuối (có bản cần 2 lần: chọn rồi xoá)
                tag_input.click()
                page.keyboard.press("Backspace")
        except Exception:
            continue
        page.wait_for_timeout(300)
        after, _ = _tags_count(container)
        if before is None or (after is not None and after < before):
            return True
    return False


TAGS_NHAP_TOI_DA = 490     # ngưỡng an toàn dưới 500 của Studio: lọc trong code TRƯỚC khi nhập


def studio_tag_count(tags):
    """Cách Studio đếm (đo thật 15/10/2026: 16 thẻ, 396 ký tự chữ -> Studio báo 413/500):
    mỗi thẻ = số ký tự + 2 nếu có dấu cách (Studio bọc ngoặc kép), cộng 1 dấu phẩy giữa các thẻ."""
    tags = [t for t in tags if t]
    if not tags:
        return 0
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + (len(tags) - 1)


def loc_the_truoc_khi_nhap(tags, log, toi_da=TAGS_NHAP_TOI_DA):
    """Bỏ các từ khóa làm tổng vượt `toi_da` (theo cách đếm của Studio) NGAY TRONG CODE, trước khi gõ.
    Giữ thứ tự, bỏ từ cuối danh sách trở lên; không bao giờ bỏ 'bác sĩ hội' nếu còn chỗ."""
    tags = [t.strip() for t in tags if t and t.strip()]
    giu = list(tags)
    bo = []
    while giu and studio_tag_count(giu) > toi_da:
        # bỏ thẻ cuối cùng KHÔNG thuộc đuôi thương hiệu trước; hết thì mới bỏ từ cuối
        idx = next((i for i in range(len(giu) - 1, -1, -1) if "bác sĩ hội" not in giu[i].lower()), len(giu) - 1)
        bo.append(giu.pop(idx))
    if bo:
        log(f"  Bỏ {len(bo)} từ khóa để tổng <= {toi_da} ký tự (Studio đếm): {', '.join(reversed(bo))}")
    log(f"  Thẻ sẽ nhập: {len(giu)} thẻ, {studio_tag_count(giu)}/{toi_da} ký tự (cách đếm Studio)")
    return giu


def _fill_tags(page, tags, log):
    tags = loc_the_truoc_khi_nhap(tags, log)
    log(f"Điền thẻ: {', '.join(tags)}")
    container = page.locator('ytcp-form-input-container#tags-container').first
    # Ô thẻ nằm trong phần nâng cao -> bấm "Hiện chế độ cài đặt nâng cao" nếu chưa mở
    if not container.is_visible():
        toggle = page.locator('ytcp-video-metadata-editor #toggle-button').first
        toggle.scroll_into_view_if_needed()
        toggle.click()
        container.wait_for(state="visible", timeout=15000)
        page.wait_for_timeout(500)
    container.scroll_into_view_if_needed()

    # 1) Xoá hết thẻ có sẵn (Studio tự nạp thẻ mặc định của kênh) bằng nút X "Xoá tất cả"
    clear = container.locator('#clear-button').first
    if clear.count() and clear.is_visible():
        clear.click()
        page.wait_for_timeout(400)
        used, limit = _tags_count(container)
        log(f"  Đã xoá thẻ có sẵn ({used if used is not None else '?'}/{limit}).")

    # 2) Thêm từng thẻ (dấu phẩy để chốt thẻ), kiểm tra giới hạn sau mỗi thẻ
    tag_input = container.locator('input#text-input, input').first
    tag_input.wait_for(state="visible", timeout=10000)
    from dang_common import clear_field
    clear_field(page, tag_input, log, "ô nhập thẻ")       # xoá chữ dở trong ô trước khi gõ
    added, dropped = [], []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        if dropped:  # đã đầy -> không cố thêm nữa
            dropped.append(t)
            continue
        page.keyboard.type(t)
        page.keyboard.press(",")
        page.wait_for_timeout(300)
        used, limit = _tags_count(container)
        if used is not None and used > limit:
            log(f"  Thẻ '{t}' làm vượt giới hạn ({used}/{limit}) -> gỡ ra.")
            if not _remove_last_tag(page, container, tag_input):
                log("  ⚠ Không gỡ được thẻ cuối bằng tự động — hãy kiểm tra ô thẻ trong Chrome.")
            dropped.append(t)
            continue
        added.append(t)

    used, limit = _tags_count(container)
    if used is not None and used > limit:
        log(f"  ⚠ Thẻ vẫn vượt giới hạn: {used}/{limit} — Studio sẽ không cho Tiếp.")
    if dropped:
        log(f"  Bỏ qua vì hết chỗ: {', '.join(dropped)}")
    log(f"✓ Đã điền {len(added)} thẻ" + (f" ({used}/{limit})." if used is not None else "."))


def _answer_altered_content(page, log):
    """Mục 'Nội dung bị thay đổi' (công bố nội dung AI) nếu kênh có -> chọn 'Không'."""
    try:
        section = page.locator('ytcp-video-metadata-altered-content')
        if section.count() == 0:
            return
        radio = section.locator('tp-yt-paper-radio-button').filter(
            has_text=re.compile(r"^\s*(Không|No)\s*$", re.I)).first
        if radio.is_visible():
            radio.click()
            log("✓ Nội dung bị thay đổi: chọn 'Không'.")
    except Exception:
        pass


def _set_kids(page, made_for_kids, log):
    name = "VIDEO_MADE_FOR_KIDS_MFK" if made_for_kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
    radio = page.locator(f'tp-yt-paper-radio-button[name="{name}"]').first
    radio.scroll_into_view_if_needed()
    radio.click()
    log("✓ Đối tượng: " + ("Dành cho trẻ em" if made_for_kids else "Không dành cho trẻ em"))


def _wait_upload_done(page, log, timeout_sec=3600):
    """Chờ tải hết byte video lên (bắt buộc trước khi lưu & đóng)."""
    log("Đang chờ video tải lên xong...")
    label = page.locator('ytcp-video-upload-progress .progress-label').first
    deadline = time.time() + timeout_sec
    last_txt = ""
    while time.time() < deadline:
        try:
            txt = label.inner_text(timeout=5000).strip()
        except Exception:
            txt = ""
        if txt and txt != last_txt:
            log(f"  [{txt}]")
            last_txt = txt
        # Hết chữ "Đang tải/Uploading" nghĩa là byte đã lên xong (sang Đang xử lý/kiểm tra)
        if txt and not re.search(r"Đang tải|Uploading", txt, re.I):
            log("✓ Video đã tải lên máy chủ xong.")
            return
        time.sleep(3)
    raise RuntimeError("Hết giờ chờ video tải lên.")


def get_channel_info(page, log=_log_default):
    """Vào Studio, cho biết đã đăng nhập chưa + tên kênh + link kênh (dùng cho nút 'Kiểm tra kết nối')."""
    page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    url = page.url
    if "accounts.google.com" in url:
        return {"logged_in": False, "name": "", "url": url, "public_url": ""}
    name = ""
    try:
        name = page.locator("#account-name, ytcp-navigation-drawer #entity-name").first \
            .inner_text(timeout=10000).strip()
    except Exception:
        pass
    m = re.search(r"/channel/(UC[\w-]+)", url)
    cid = m.group(1) if m else ""
    return {"logged_in": True, "name": name,
            "url": f"https://studio.youtube.com/channel/{cid}" if cid else url,
            "public_url": f"https://www.youtube.com/channel/{cid}" if cid else ""}


def _round_15(dt):
    """Studio liệt kê giờ theo bước 15 phút -> làm tròn tới mốc gần nhất."""
    q = (dt.minute + 7) // 15 * 15
    return dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=q)


def _format_date_like(sample, when):
    """Gõ ngày theo đúng định dạng Studio đang hiển thị (locale máy): lấy chuỗi mẫu (thường là
    hôm nay, vd. '13 thg 10, 2026' hoặc 'Oct 13, 2026'), thay số/tháng bằng ngày cần đặt."""
    s = (sample or "").strip()
    if not s or not re.search(r"\d", s):
        return when.strftime("%d/%m/%Y")
    today = date.today()
    month_word = False
    for names in (MONTHS_EN_FULL, MONTHS_EN):
        for name in names:
            if re.search(rf"\b{name}\b", s):
                s = re.sub(rf"\b{name}\b", names[when.month - 1], s)
                month_word = True
                break
        if month_word:
            break
    nums = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\d+", s)]
    roles = {}
    rest = []
    for i, (_a, _b, txt) in enumerate(nums):
        if len(txt) == 4:
            roles[i] = when.year
        else:
            rest.append(i)
    if month_word:
        if rest:
            roles[rest[0]] = when.day
    elif len(rest) >= 2:
        a, b = int(nums[rest[0]][2]), int(nums[rest[1]][2])
        if a == today.month and b == today.day and a != b:
            roles[rest[0]], roles[rest[1]] = when.month, when.day
        else:  # mặc định ngày trước tháng (vi)
            roles[rest[0]], roles[rest[1]] = when.day, when.month
    elif len(rest) == 1:
        roles[rest[0]] = when.day
    out, last = [], 0
    for i, (a, b, txt) in enumerate(nums):
        out.append(s[last:a])
        val = roles.get(i)
        if val is None:
            out.append(txt)
        else:
            out.append(f"{val:02d}" if (len(txt) == 2 and txt[0] == "0") else str(val))
        last = b
    out.append(s[last:])
    return "".join(out)


def _set_schedule(page, when, log):
    """Chế độ 'Lên lịch' của YouTube ở bước Chế độ hiển thị: chọn radio SCHEDULE, đặt ngày + giờ.

    Mã này được viết theo cấu trúc Studio đã biết nhưng CHƯA kiểm chứng trên kênh thật, nên mỗi
    bước đều đọc lại chữ Studio hiển thị; lệch là dừng (raise) để KHÔNG bấm Lưu."""
    when = _round_15(when)
    log(f"Lên lịch công bố: {when:%d/%m/%Y %H:%M}")
    # Studio có 2 giao diện: (cũ) radio SCHEDULE trong nhóm chế độ hiển thị; (mới, 10/2026) khung
    # riêng "Lên lịch" (ytcp-video-visibility-select #second-container, p#visibility-title) bên
    # dưới khung "Lưu hoặc xuất bản" — bấm vào khung đó mới hiện ytcp-datetime-picker.
    radio = page.locator('tp-yt-paper-radio-button[name="SCHEDULE"]').first
    try:
        radio.wait_for(state="visible", timeout=3000)
        radio.scroll_into_view_if_needed()
        radio.click()
        log("  (giao diện cũ: radio Lên lịch)")
    except Exception:
        khung = page.locator('ytcp-video-visibility-select p#visibility-title, p#visibility-title').filter(
            has_text=re.compile(r"Lên lịch|Schedule", re.I)).first
        khung.wait_for(state="attached", timeout=15000)
        khung.scroll_into_view_if_needed()
        khung.click()
        log("  (giao diện mới: khung Lên lịch)")
    page.wait_for_timeout(1000)
    picker = page.locator('ytcp-datetime-picker').first
    picker.wait_for(state="attached", timeout=15000)

    # --- Ngày: nếu ô ngày đã đúng thì thôi; không thì mở hộp chọn, gõ theo định dạng đang hiển thị ---
    date_trig = picker.locator('#datepicker-trigger').first
    date_trig.scroll_into_view_if_needed()
    shown0 = re.sub(r"\s+", " ", date_trig.inner_text(timeout=3000)).strip()
    digits0 = re.findall(r"\d+", shown0)
    if (str(when.day) in digits0 and str(when.year) in shown0
            and (str(when.month) in digits0 or f"{when.month:02d}" in digits0)):
        log(f"  Ngày đang hiện '{shown0}' đã đúng.")
    else:
        date_trig.click()
        page.wait_for_timeout(600)
        date_input = page.locator('ytcp-date-picker input, ytcp-date-picker tp-yt-paper-input input').first
        date_input.wait_for(state="visible", timeout=10000)
        sample = ""
        try:
            sample = date_input.input_value(timeout=2000)
        except Exception:
            pass
        if not sample:
            sample = shown0
        text = _format_date_like(sample, when)
        log(f"  Ngày: mẫu '{sample.strip()}' -> gõ '{text}'")
        date_input.click()
        page.keyboard.press("Control+a")
        page.keyboard.type(text)
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)

    # --- Giờ ---
    hhmm = f"{when:%H:%M}"
    hhmm_12 = when.strftime("%I:%M %p").lstrip("0")
    time_trig = picker.locator('#time-of-day-trigger').first
    time_box = picker.locator('#time-of-day-container input').first
    if time_trig.count():
        # giao diện cũ: danh sách bước 15 phút
        time_trig.scroll_into_view_if_needed()
        time_trig.click()
        page.wait_for_timeout(600)
        item = page.locator('tp-yt-paper-item').filter(
            has_text=re.compile(rf"^\s*({re.escape(hhmm)}|{re.escape(hhmm_12)})\s*$", re.I)).first
        try:
            item.wait_for(state="visible", timeout=5000)
            item.scroll_into_view_if_needed()
            item.click()
        except Exception:
            tin = page.locator('ytcp-datetime-picker input[type="text"], ytcp-time-of-day-picker input').first
            tin.wait_for(state="visible", timeout=5000)
            tin.click()
            page.keyboard.press("Control+a")
            page.keyboard.type(hhmm)
            page.keyboard.press("Enter")
        page.wait_for_timeout(800)
        shown_time = re.sub(r"\s+", " ", time_trig.inner_text(timeout=3000)).strip()
    else:
        # giao diện mới: ô text gõ thẳng HH:MM + Enter (đã xác nhận 15/10/2026)
        time_box.wait_for(state="visible", timeout=10000)
        time_box.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Control+a")
        page.keyboard.type(hhmm, delay=60)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
        shown_time = (time_box.input_value(timeout=3000) or "").strip()

    # --- Xác minh bằng chữ Studio hiển thị ---
    shown_date = re.sub(r"\s+", " ", date_trig.inner_text(timeout=3000)).strip()
    log(f"  Studio hiển thị: ngày '{shown_date}', giờ '{shown_time}'")
    digits = re.findall(r"\d+", shown_date)
    ok_date = (str(when.day) in digits or f"{when.day:02d}" in digits) and str(when.year) in shown_date
    ok_time = hhmm in shown_time or hhmm_12.lower() in shown_time.lower()
    if not (ok_date and ok_time):
        raise RuntimeError(f"Không đặt được lịch: Studio hiển thị '{shown_date} {shown_time}', "
                           f"cần {when:%d/%m/%Y %H:%M}. Đã dừng, chưa bấm Lưu.")
    log("✓ Đã đặt lịch công bố.")


def _get_video_link(page):
    try:
        a = page.locator('ytcp-uploads-dialog a#video-link, ytcp-video-info a, .video-url-fadeable a').first
        return a.get_attribute("href", timeout=3000)
    except Exception:
        return None


def upload_video(page, video_path, title, description, playlist=None, tags=None,
                 visibility="PRIVATE", made_for_kids=False, log=_log_default, dry_run=False,
                 schedule_at=None):
    """Thực hiện toàn bộ luồng đăng video.

    visibility: PRIVATE | UNLISTED | PUBLIC | SCHEDULE (kèm schedule_at=datetime: YouTube tự
    công khai đúng giờ đó, máy không cần mở).
    dry_run=True: làm hết mọi bước (kể cả chọn chế độ hiển thị / đặt lịch) rồi DỪNG trước nút
    Lưu/Lên lịch cuối cùng; hộp thoại để mở trong Chrome cho người dùng kiểm tra. Studio vẫn
    tải byte lên và giữ video dạng bản nháp chưa đăng — xoá được trong mục Nội dung."""
    if visibility == "SCHEDULE" and not schedule_at:
        raise ValueError("visibility=SCHEDULE cần schedule_at (datetime)")
    tags = tags or []

    log("Mở trang tải video lên YouTube Studio...")
    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    _check_logged_in(page, log)
    _dismiss_popups(page)

    # --- Chọn file ---
    log(f"Chọn file: {video_path}")
    file_input = page.locator('ytcp-uploads-file-picker input[type="file"]').first
    file_input.wait_for(state="attached", timeout=30000)
    try:
        _set_file_via_cdp(video_path, log)  # đường chính: đường dẫn file qua CDP, không giới hạn dung lượng
    except Exception as e:
        log(f"  (CDP trực tiếp không được: {e} — thử cách của Playwright, giới hạn 50 MB)")
        try:
            file_input.set_input_files(video_path, timeout=15000)
        except Exception:
            # Dự phòng: bấm nút 'Chọn tệp' và bắt hộp thoại chọn file
            with page.expect_file_chooser(timeout=15000) as fc:
                page.locator('#select-files-button, ytcp-uploads-file-picker ytcp-button').first.click()
            fc.value.set_files(video_path)
    log("✓ Đã nạp file, chờ hộp thoại chi tiết...")

    # Host <ytcp-uploads-dialog> không có khung nên Playwright coi là 'hidden' dù nội dung đang
    # hiện; chờ theo bước workflow: DETAILS / có video-id = Studio đã nhận file, hộp chi tiết đã mở.
    page.locator('ytcp-uploads-dialog[workflow-step="DETAILS"], ytcp-uploads-dialog[video-id]') \
        .first.wait_for(state="attached", timeout=120000)
    page.wait_for_timeout(2500)  # chờ Studio tự điền tiêu đề mặc định

    # --- Tiêu đề & mô tả ---
    log(f"Điền tiêu đề: {title}")
    _fill_textbox(page, ("title-textarea", "title-textbox"), title, log)
    log("Điền nội dung mô tả...")
    _fill_textbox(page, ("description-textarea", "description-textbox"), description, log)

    # --- Danh sách phát ---
    if playlist:
        _pick_playlist(page, playlist, log)

    # --- Đối tượng trẻ em (bắt buộc) ---
    _set_kids(page, made_for_kids, log)

    # --- Thẻ (trong 'Hiển thị thêm') ---
    if tags:
        _fill_tags(page, tags, log)
    _answer_altered_content(page, log)

    video_link = _get_video_link(page)
    if video_link:
        log(f"Link video: {video_link}")

    # --- Bấm Tiếp qua 3 bước ---
    for i in range(3):
        nxt = page.locator('ytcp-uploads-dialog #next-button').first
        nxt.wait_for(state="visible", timeout=30000)
        nxt.click()
        log(f"✓ Tiếp ({i + 1}/3)")
        page.wait_for_timeout(1500)

    # --- Chế độ hiển thị / Lên lịch ---
    if visibility == "SCHEDULE":
        _set_schedule(page, schedule_at, log)
    else:
        vis_names = {"PRIVATE": "Riêng tư", "UNLISTED": "Không công khai", "PUBLIC": "Công khai"}
        log(f"Chế độ hiển thị: {vis_names.get(visibility, visibility)}")
        radio = page.locator(f'tp-yt-paper-radio-button[name="{visibility}"]').first
        radio.scroll_into_view_if_needed()
        radio.click()
        page.wait_for_timeout(500)

    if dry_run:
        shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chay_thu_gan_nhat.png")
        try:
            page.screenshot(path=shot)
            log(f"Ảnh chụp hộp thoại lúc dừng: {shot}")
        except Exception:
            pass
        log("⏸ CHẠY THỬ: đã làm hết các bước — DỪNG trước nút Lưu/Lên lịch cuối cùng. "
            "Hộp thoại vẫn mở trong Chrome để bạn kiểm tra; video đang ở dạng bản nháp, CHƯA đăng.")
        return video_link

    # --- Chờ tải lên xong rồi mới Lưu ---
    _wait_upload_done(page, log)

    done_btn = page.locator('ytcp-uploads-dialog #done-button').first
    done_btn.click()
    log("✓ Đã bấm Lưu/Xuất bản.")

    video_link = _sau_khi_luu(page, done_btn, video_link, log)

    log("🎉 HOÀN TẤT! Video đã được đăng" +
        (f" — {video_link}" if video_link else "") +
        ". (YouTube sẽ tự xử lý độ phân giải trong nền.)")
    return video_link


# ----- sau nút Lưu/Lên lịch cuối cùng -----
# hộp KẾT QUẢ (hiện sau khi hộp tải lên đã đóng): 'Đã lên lịch cho video' (có link, nút Đóng — ảnh
# dom_dump/youtube/xong_1_sau_bam.png) / 'Video đã xuất bản' / 'Video vẫn đang xử lý'
RE_HOP_KET_QUA = re.compile(r"Đã lên lịch cho video|đã lên lịch|đã xuất bản|Video published|Video scheduled|"
                            r"vẫn đang xử lý|still processing", re.I)
# nút ĐỒNG Ý trong popup xác nhận (Studio hỏi thêm sau khi bấm Lưu, vd. quá trình kiểm tra chưa xong,
# nhắc về đường liên kết / nội dung...). Không bao giờ bấm nút huỷ / quay lại.
RE_NUT_DONG_Y = re.compile(r"^\s*(Xác nhận|Đồng ý|Tiếp tục|Vẫn \S.*|Lên lịch|Xuất bản|Lưu|Đã hiểu|Được|Có|OK|Đóng|"
                           r"Confirm|Continue|Schedule.*|Publish.*|Save|Got it|Yes|Okay|Proceed|Close)\s*$", re.I)
RE_NUT_TU_CHOI = re.compile(r"hủy|huỷ|quay lại|bỏ|không|cancel|back|dismiss|later|để sau", re.I)
POPUP_SHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popup_youtube_gan_nhat.png")


def _hop_tai_len_dang_mo(done_btn):
    """Hộp thoại tải lên (ytcp-uploads-dialog) còn mở không = nút Lưu/Lên lịch còn nhìn thấy."""
    try:
        return done_btn.is_visible(timeout=1500)
    except Exception:
        return False


def _hop_ket_qua(page):
    """Hộp kết quả đang hiện -> (locator, chữ); không -> (None, '')."""
    try:
        kq = page.locator('tp-yt-paper-dialog').filter(visible=True).filter(has_text=RE_HOP_KET_QUA)
        for i in range(kq.count()):
            d = kq.nth(i)
            if d.locator('#done-button').count():       # chính hộp tải lên -> không phải
                continue
            return d, " ".join(d.inner_text(timeout=3000).split())
    except Exception:
        pass
    return None, ""


def _dong_hop_ket_qua(page, hop, log):
    for sel in ['ytcp-uploads-still-processing-dialog #close-button',
                'ytcp-uploads-still-processing-dialog ytcp-button',
                'ytcp-uploads-share-dialog #close-icon-button',
                '#close-button', '#close-icon-button']:
        try:
            btn = (hop if sel.startswith('#') else page).locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=3000)
                return True
        except Exception:
            pass
    try:
        dong = hop.locator('ytcp-button, button').filter(has_text=re.compile(r"^\s*(Đóng|Close)\s*$")).filter(visible=True).first
        if dong.count():
            dong.click(timeout=3000)
            return True
    except Exception:
        pass
    log("  ⚠ Không thấy nút Đóng của hộp kết quả — bỏ qua (video đã lưu).")
    return False


def _nut_dong_y_trong(hop):
    """Nút đồng ý trong một hộp thoại: ưu tiên #confirm-button, rồi nút có chữ khớp RE_NUT_DONG_Y
    (không phải chữ huỷ/quay lại). Trả về (locator, tên) hoặc (None, '')."""
    try:
        b = hop.locator('#confirm-button').filter(visible=True).first
        if b.count():
            return b, b.inner_text(timeout=1000).strip() or "confirm"
    except Exception:
        pass
    for sel in ('ytcp-button', 'tp-yt-paper-button', 'button'):
        try:
            bs = hop.locator(sel).filter(visible=True)
            n = bs.count()
        except Exception:
            continue
        ung = []
        for k in range(n):
            b = bs.nth(k)
            try:
                t = " ".join(b.inner_text(timeout=1000).split())
            except Exception:
                continue
            if t and RE_NUT_DONG_Y.match(t) and not RE_NUT_TU_CHOI.search(t):
                ung.append((k, b, t))
        if ung:
            k, b, t = ung[-1]            # nút chính của Studio đứng cuối (bên phải)
            return b, t
    return None, ""


def _bam_popup_xac_nhan(page, log):
    """Popup xác nhận hiện SAU khi bấm Lưu trong lúc hộp tải lên còn mở (không phải hộp tải lên chính):
    chụp ảnh, ghi chữ ra nhật ký, bấm nút đồng ý. Trả về chữ popup đã bấm, hoặc '' nếu không có popup."""
    try:
        dlgs = page.locator('tp-yt-paper-dialog, ytcp-confirmation-dialog, [role="dialog"], [role="alertdialog"]').filter(visible=True)
        n = dlgs.count()
    except Exception:
        return ""
    for i in range(n):
        d = dlgs.nth(i)
        try:
            if d.locator('#done-button').count() or d.locator('#next-button').count():
                continue                                   # hộp tải lên chính
            txt = " ".join(d.inner_text(timeout=2000).split())
        except Exception:
            continue
        if not txt or len(txt) > 1500:
            continue
        nut, ten = _nut_dong_y_trong(d)
        if nut is None:
            log(f"  Studio hiện hộp thoại nhưng không thấy nút đồng ý: {txt[:160]!r}")
            continue
        try:
            page.screenshot(path=POPUP_SHOT)
        except Exception:
            pass
        log(f"  Studio hỏi thêm sau khi Lưu: {txt[:200]!r} -> bấm '{ten}' (ảnh: {POPUP_SHOT})")
        nut.click(timeout=5000)
        page.wait_for_timeout(1500)
        return txt
    return ""


def _sau_khi_luu(page, done_btn, video_link, log, timeout_sec=120):
    """Sau nút Lưu/Lên lịch, Studio có thể: (a) hiện POPUP cần xác nhận (user gặp 17-19/10/2026: không
    bấm thì video nằm nháp, chưa lên lịch) -> bấm đồng ý rồi chờ tiếp; (b) đóng hộp tải lên rồi hiện hộp
    'Đã lên lịch cho video' / 'đang xử lý' -> lấy link, bấm Đóng. CHỈ coi là xong khi hộp tải lên đã
    đóng; quá giờ mà vẫn mở -> raise (kèm ảnh chụp) chứ không báo HOÀN TẤT khống như trước."""
    t0 = time.time()
    da_bam = 0
    bam_lai = False
    def _xu_ly_hop_ket_qua(hop, txt):
        nonlocal video_link
        m = re.search(r"https://(?:youtu\.be|www\.youtube\.com|youtube\.com)/[\w\-?=&./]+", txt)
        if m:
            video_link = m.group(0)
        log(f"  Studio: {txt[:160]}")
        _dong_hop_ket_qua(page, hop, log)
        page.wait_for_timeout(1000)

    while time.time() - t0 < timeout_sec:
        page.wait_for_timeout(1500)
        # Hộp kết quả 'Đã lên lịch cho video' hiện ngay khi hộp tải lên còn nằm trong DOM 1-3 s nữa
        # (đo thật 19/10/2026) -> xét nó TRƯỚC, lấy link từ đó rồi Đóng
        hop, txt = _hop_ket_qua(page)
        if hop is not None:
            _xu_ly_hop_ket_qua(hop, txt)
            for _ in range(6):
                if not _hop_tai_len_dang_mo(done_btn):
                    break
                page.wait_for_timeout(1000)
            log("  Hộp thoại tải lên đã đóng." if not _hop_tai_len_dang_mo(done_btn)
                else "  (hộp tải lên vẫn còn trong DOM sau hộp kết quả — Studio đã lưu, coi như xong)")
            return video_link
        if not _hop_tai_len_dang_mo(done_btn):
            log("  Hộp thoại tải lên đã đóng.")
            for _ in range(4):                         # hộp kết quả có thể hiện trễ 1-5 s
                hop, txt = _hop_ket_qua(page)
                if hop is not None:
                    _xu_ly_hop_ket_qua(hop, txt)
                    break
                page.wait_for_timeout(1500)
            return video_link
        if da_bam < 3 and _bam_popup_xac_nhan(page, log):
            da_bam += 1
            continue
        # còn mở, không popup: có thể cú bấm đầu chưa ăn (Studio đang bận) -> bấm Lưu lại đúng 1 lần sau 10 s
        if not bam_lai and time.time() - t0 > 10:
            bam_lai = True
            try:
                if done_btn.is_enabled(timeout=1000):
                    done_btn.click(timeout=3000)
                    log("  (hộp tải lên vẫn mở sau 10 s -> bấm Lưu/Lên lịch lần nữa)")
            except Exception:
                pass
    shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loi_sau_luu_youtube.png")
    try:
        page.screenshot(path=shot)
    except Exception:
        pass
    raise RuntimeError(f"Đã bấm Lưu/Lên lịch nhưng hộp thoại tải lên vẫn mở sau {timeout_sec}s — có popup Studio chưa "
                       f"xác nhận được? Hãy xem tab Chrome và ảnh {shot}; bấm xác nhận bằng tay rồi 'Đăng lại lỗi' nếu cần.")


# ----- đọc lịch đã đặt (app xếp giờ video mới SAU video gần nhất đang lên lịch, user 19/10/2026) -----
RE_NGAY_VI = re.compile(r"(\d{1,2}) thg (\d{1,2}), (\d{4})")
RE_GIO_24 = re.compile(r"\b(\d{1,2}):(\d{2})\b")


RE_GIO_12 = re.compile(r"(\d{1,2}):(\d{2})\s*(SA|CH|AM|PM)", re.I)
RE_NGAY_EN = re.compile(r"\b(" + "|".join(MONTHS_EN) + r")\w*\s+(\d{1,2}),\s+(\d{4})")


def _gio_len_lich_trang_sua(page, vid, log):
    """Trang sửa video chỉ hiện 'Chế độ hiển thị: Đã lên lịch'; bấm vào ô đó mở hộp thoại
    ytcp-video-visibility-select có ngày ở #datepicker-trigger ('21 thg 10, 2026') và giờ ở
    #time-of-day-container input ('08:00') (dò thật 19/10/2026). Đọc xong bấm Escape, không đổi gì.
    Không phải video lên lịch / không đọc được -> None."""
    page.goto(f"https://studio.youtube.com/video/{vid}/edit", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    box = page.locator("ytcp-video-metadata-visibility").first
    box.wait_for(state="visible", timeout=20000)
    if not re.search(r"lên lịch|scheduled", box.inner_text(timeout=3000), re.I):
        return None
    box.scroll_into_view_if_needed()
    box.click()
    ngay_txt = gio_txt = ""
    try:
        picker = page.locator("ytcp-datetime-picker").first
        picker.wait_for(state="visible", timeout=10000)
        page.wait_for_timeout(800)
        ngay_txt = " ".join(picker.locator("#datepicker-trigger").first.inner_text(timeout=5000).split())
        gio_txt = (picker.locator("#time-of-day-container input").first.input_value(timeout=5000) or "").strip()
    finally:
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
    mn = RE_NGAY_VI.search(ngay_txt)
    if mn:
        y, mo, d = int(mn.group(3)), int(mn.group(2)), int(mn.group(1))
    else:
        me = RE_NGAY_EN.search(ngay_txt)
        if not me:
            log(f"  (YouTube {vid}: không hiểu ngày {ngay_txt!r})")
            return None
        y, mo, d = int(me.group(3)), MONTHS_EN.index(me.group(1)) + 1, int(me.group(2))
    m12 = RE_GIO_12.search(gio_txt)
    if m12:
        h = int(m12.group(1)) % 12 + (12 if m12.group(3).upper() in ("CH", "PM") else 0)
        mi = int(m12.group(2))
    else:
        mg = RE_GIO_24.search(gio_txt)
        if not mg:
            log(f"  (YouTube {vid}: không hiểu giờ {gio_txt!r})")
            return None
        h, mi = int(mg.group(1)), int(mg.group(2))
    return datetime(y, mo, d, h, mi)


def lich_da_dat(page, log=_log_default):
    """Datetime các video đang 'Đã lên lịch' ở CẢ tab Shorts lẫn tab Video của Studio: ngày lấy ở
    bảng, giờ lấy ở trang sửa từng video (không đọc được giờ thì lấy 23:59 ngày đó cho chắc chắn xếp
    sau). Trả về list đã sắp xếp."""
    page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    _check_logged_in(page, log)
    m = re.search(r"/channel/(UC[\w-]+)", page.url)
    if not m:
        raise RuntimeError("không lấy được id kênh từ địa chỉ Studio")
    cid = m.group(1)
    tim = []
    for tab in ("short", "upload"):
        page.goto(f"https://studio.youtube.com/channel/{cid}/videos/{tab}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        rows = page.locator("ytcp-video-row")
        for i in range(min(rows.count(), 40)):
            r = rows.nth(i)
            try:
                t = " ".join(r.inner_text(timeout=3000).split())
            except Exception:
                continue
            if not re.search(r"Đã lên lịch|Scheduled", t):
                continue
            vid = ""
            try:
                href = r.locator("a#video-title, a[href*='/video/']").first.get_attribute("href", timeout=2000) or ""
                mv = re.search(r"/video/([\w-]+)/", href)
                vid = mv.group(1) if mv else ""
            except Exception:
                pass
            mn = RE_NGAY_VI.search(t)
            ngay = date(int(mn.group(3)), int(mn.group(2)), int(mn.group(1))) if mn else None
            tim.append((tab, vid, ngay, t[:50]))
    out = set()
    for tab, vid, ngay, ten in tim:
        dt = None
        if vid:
            try:
                dt = _gio_len_lich_trang_sua(page, vid, log)
            except Exception:
                dt = None
        if dt is None and ngay is not None:
            dt = datetime.combine(ngay, datetime.min.time()).replace(hour=23, minute=59)
            log(f"  (YouTube: không đọc được giờ của '{ten}' -> coi là {dt:%d/%m %H:%M})")
        if dt is not None:
            out.add(dt)
    return sorted(out)
