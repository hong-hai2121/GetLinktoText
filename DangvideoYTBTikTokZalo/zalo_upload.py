# -*- coding: utf-8 -*-
"""Đăng video lên Zalo Video Creator Center (video.zalo.me/creator/video) qua Cốc Cốc/Chrome thật +
Playwright Extension.

Các bước (đã làm tay và xác nhận trên kênh thật 15/10/2026):
  1. Mở trang Video, bấm nút "Đăng video" (sidebar) -> modal có input[name=file]
     (accept video/mp4, video/quicktime; từ 720p; tối đa 500 MB) -> nạp file qua CDP.
  2. Form hiện ra: ô "Nội dung video" (div.input-conteneditable, tối đa 4000 ký tự) -> chèn
     tiêu đề + hashtag (Zalo tự nhận #hashtag trong chữ, không cần Enter).
  3. "Hẹn giờ đăng video": input[placeholder="Chọn thời điểm"] mở lịch Ant Design
     (.ant-picker-dropdown): bấm ô ngày [title=YYYY-MM-DD], cột giờ, cột phút, nút OK
     -> ô hiện "DD-MM-YYYY HH:MM".
  4. Nút "Đăng video" của FORM (nút ant-btn-primary nằm thấp nhất; nút trên cùng là sidebar).
     Xong Zalo chuyển sang danh sách ?type=scheduled, dòng mới "Chờ công khai <ngày giờ>".
"""
import re
import time

from dang_common import clear_and_insert, norm_space, set_file_via_cdp, wait_until

CREATOR_URL = "https://video.zalo.me/creator/video"
SCHEDULED_URL = "https://video.zalo.me/creator/video?type=scheduled"
SEL_CONTENT = "div.input-conteneditable"
SEL_TIME_INPUT = 'input[placeholder="Chọn thời điểm"]'
RE_DANG = re.compile(r"^\s*Đăng video\s*$")


def _check_logged_in(page):
    if "login" in page.url or page.locator('text=/Đăng nhập/').filter(visible=True).count() > 1:
        raise RuntimeError("Chưa đăng nhập Zalo Video trong profile này — hãy đăng nhập rồi chạy lại.")


def _nut_dang_form(page):
    """Nút 'Đăng video' của form = nút ant-btn-primary có chữ đó nằm THẤP NHẤT (sidebar ở trên)."""
    cands = page.locator("button.ant-btn-primary").filter(has_text=RE_DANG).filter(visible=True)
    best, best_y = None, -1
    for i in range(cands.count()):
        bb = cands.nth(i).bounding_box()
        if bb and bb["y"] > best_y:
            best, best_y = cands.nth(i), bb["y"]
    return best


def _wait_form_ready(page, log, timeout_sec=1800):
    log("Đang chờ Zalo nhận file...")
    box = page.locator(SEL_CONTENT).first
    box.wait_for(state="visible", timeout=180000)

    def san_sang():
        btn = _nut_dang_form(page)
        return btn is not None and not btn.is_disabled()
    wait_until(san_sang, timeout_sec, every=3, desc="Zalo xử lý file")
    log("✓ Zalo đã nhận file, form sẵn sàng.")


def _fill_content(page, content, hashtags, log):
    box = page.locator(SEL_CONTENT).first
    text = content.strip()
    tags = " ".join(t if t.startswith("#") else "#" + t for t in (hashtags or []) if t.strip())
    if tags:
        text = text + " " + tags
    log(f"Điền nội dung: {text[:120]}")
    clear_and_insert(page, box, text, log, "ô nội dung Zalo")
    page.wait_for_timeout(800)
    doc = norm_space(box.inner_text())
    muon = norm_space(text)
    # Zalo tô đậm hashtag / thêm ký tự vô hình -> so MỀM: phải bắt đầu bằng tiêu đề và có đủ hashtag
    thieu = [t for t in tags.split() if t.lower() not in doc.lower()]
    if not doc.lower().startswith(norm_space(content).lower()[:60].lower()) or thieu:
        raise RuntimeError(f"Ô nội dung không khớp. Trong ô: {doc[:200]!r} | Mong muốn: {muon[:200]!r} | thiếu hashtag: {thieu}")
    if doc != muon:
        log(f"  (ô hiện khác chút về khoảng trắng/định dạng, chấp nhận) {doc[:100]!r}")
    log("✓ Nội dung đã điền.")


def _set_schedule(page, when, log):
    when = when.replace(second=0, microsecond=0)
    log(f"Hẹn giờ đăng Zalo: {when:%d/%m/%Y %H:%M}")
    o = page.locator(SEL_TIME_INPUT).first
    o.wait_for(state="visible", timeout=30000)
    o.click()
    page.wait_for_timeout(800)
    pop = page.locator(".ant-picker-dropdown:not(.ant-picker-dropdown-hidden)").first
    pop.wait_for(state="visible", timeout=5000)
    title = when.strftime("%Y-%m-%d")
    for _ in range(14):
        cell = pop.locator(f'.ant-picker-cell-in-view[title="{title}"]')
        if cell.count():
            break
        pop.locator(".ant-picker-header-next-btn").first.click()
        page.wait_for_timeout(400)
    else:
        raise RuntimeError(f"không thấy ngày {title} trong lịch Zalo")
    cell.first.click()
    page.wait_for_timeout(500)
    cols = pop.locator(".ant-picker-time-panel-column")
    if cols.count() < 2:
        raise RuntimeError("lịch Zalo không có cột giờ/phút")
    for idx, gt in ((0, when.strftime("%H")), (1, when.strftime("%M"))):
        c = cols.nth(idx).locator(".ant-picker-time-panel-cell").filter(has_text=re.compile(rf"^\s*{gt}\s*$")).first
        c.scroll_into_view_if_needed()
        c.click()
        page.wait_for_timeout(400)
    pop.locator(".ant-picker-footer button").filter(has_text=re.compile(r"^\s*OK\s*$", re.I)).first.click()
    page.wait_for_timeout(1000)
    val = o.input_value()
    if val != when.strftime("%d-%m-%Y %H:%M"):
        raise RuntimeError(f"Không đặt được giờ Zalo: ô hiện {val!r}, cần {when:%d-%m-%Y %H:%M}")
    log(f"  ✓ Hẹn giờ {val}")


def upload_video(page, video_path, content, hashtags=(), schedule_at=None, log=print, dry_run=False):
    """Toàn bộ luồng Zalo Video. content: MỘT dòng (tiêu đề); hashtags nối sau bằng dấu cách.
    schedule_at: datetime -> hẹn giờ; None -> đăng ngay. dry_run: làm hết rồi DỪNG trước nút cuối."""
    log("Mở Zalo Video Creator Center...")
    page.goto(CREATOR_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    _check_logged_in(page)
    page.locator("button.ant-btn-primary").filter(has_text=RE_DANG).filter(visible=True).first.click()
    page.locator('input[name="file"], input[type=file]').first.wait_for(state="attached", timeout=30000)
    log(f"Chọn file: {video_path}")
    set_file_via_cdp(page, video_path, log)
    _wait_form_ready(page, log)
    _fill_content(page, content, list(hashtags or []), log)
    if schedule_at:
        _set_schedule(page, schedule_at, log)
    btn = _nut_dang_form(page)
    if btn is None:
        raise RuntimeError("không thấy nút 'Đăng video' của form")
    if dry_run:
        log("⏸ CHẠY THỬ: đã làm hết các bước — DỪNG trước nút 'Đăng video'. Tab vẫn mở để bạn kiểm tra.")
        return None
    btn.scroll_into_view_if_needed()
    btn.click()
    log("✓ Đã bấm 'Đăng video'.")
    # Zalo gửi video lên máy chủ sau khi bấm, ~7 s mới hiện toast "Đặt lịch thành công"/"Đăng thành công".
    # KHÔNG tải lại trang trong lúc này (sẽ cắt ngang yêu cầu -> không có bài). Chờ toast tới 90 s.
    thanh_cong = False
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            msg = " | ".join(norm_space(t) for t in page.locator(".ant-message, .ant-notification").all_inner_texts())
        except Exception:
            msg = ""
        if "thành công" in msg.lower():
            log(f"  Zalo báo: {msg[:80]}")
            thanh_cong = True
            break
        if re.search(r"lỗi|thất bại|không thành công", msg, re.I):
            raise RuntimeError(f"Zalo báo lỗi: {msg[:200]}")
        time.sleep(1)
    page.wait_for_timeout(2000)
    # xác nhận: danh sách đã đặt lịch / công khai có dòng chứa đầu nội dung
    dau = norm_space(content)[:40]
    try:
        page.goto(SCHEDULED_URL if schedule_at else CREATOR_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        body = norm_space(page.locator("body").inner_text())
        if dau in body:
            log("🎉 Zalo: " + ("đã hẹn giờ" if schedule_at else "đã đăng") + " — thấy trong danh sách.")
            return page.url
    except Exception:
        pass
    if thanh_cong:
        log("✓ Zalo đã báo thành công (danh sách có thể cập nhật chậm).")
        return page.url
    raise RuntimeError("Bấm Đăng video nhưng Zalo không báo thành công trong 90s — kiểm tra tab Zalo.")


# ----- đọc lịch đã đặt (app xếp giờ video mới SAU video gần nhất đang lên lịch, user 19/10/2026) -----
# cột "Giờ hẹn đăng" của danh sách hẹn giờ: nhận "19-10-2026 18:00", "19/10/2026 18:00" hoặc "18:00 19/10/2026"
RE_NGAY_GIO_ZALO = re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s+(\d{1,2}):(\d{2})|(\d{1,2}):(\d{2})\s+(\d{1,2})[-/](\d{1,2})[-/](\d{4})")


def lich_da_dat(page, log=print):
    """Danh sách datetime các bài Zalo đang hẹn giờ (mọi mốc giờ ở TƯƠNG LAI trên trang danh sách hẹn giờ)."""
    from datetime import datetime
    page.goto(SCHEDULED_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    _check_logged_in(page)
    body = page.locator("body").inner_text(timeout=15000)
    now = datetime.now()
    out = set()
    for m in RE_NGAY_GIO_ZALO.finditer(body):
        g = m.groups()
        d, mo, y, h, mi = (g[0], g[1], g[2], g[3], g[4]) if g[0] else (g[7], g[8], g[9], g[5], g[6])
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi))
        except ValueError:
            continue
        if dt > now:
            out.add(dt)
    return sorted(out)
