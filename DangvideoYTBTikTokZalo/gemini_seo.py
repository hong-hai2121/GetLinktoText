# -*- coding: utf-8 -*-
"""Gửi bản bóc băng lên Gemini (gemini.google.com/app) qua Playwright + Playwright Extension để
nhận về nội dung SEO (PHẦN 2: tags & hashtag; PHẦN 3: tiêu đề + mô tả chuẩn SEO).

Luồng: mở Gemini trong trình duyệt/profile cấu hình ở config.json mục platforms["gemini"] (mặc định
dùng profile Zalo - Cốc Cốc vì tài khoản Gemini đăng nhập ở đó) -> "Cuộc trò chuyện mới" -> gửi
PROMPT_HE_THONG một lần -> gửi bản bóc băng -> chờ Gemini trả lời xong -> lấy chữ -> tách phần.
"""
import re
import time

GEMINI_URL = "https://gemini.google.com/app"

# Prompt do user soạn (15/10/2026) — gửi MỘT lần ở đầu mỗi cuộc trò chuyện mới, giữ nguyên văn.
PROMPT_HE_THONG = """Bạn là chuyên gia biên tập và tối ưu hóa nội dung y khoa tiêu hóa (dạ dày, trào ngược, HP, đại tràng) cho kênh YouTube của Bác sĩ Hội.

NHIỆM VỤ:
Tôi sẽ gửi bản ghi âm bóc băng giọng nói (Speech-to-Text) còn thô, chứa nhiều lỗi chính tả và thuật ngữ y khoa bị nhận diện sai. Bạn hãy tự động sửa toàn bộ các lỗi này và xuất nội dung chuẩn SEO.

QUY TẮC ĐẦU RA BẮT BUỘC:
- CHỈ XUẤT ĐÚNG 2 PHẦN: PHẦN 2 VÀ PHẦN 3.
- TUYỆT ĐỐI KHÔNG xuất Phần 1, không viết lời chào, không giải thích hay nhận xét dài dòng bên ngoài.

CẤU TRÚC CHI TIẾT 2 PHẦN:

### PHẦN 2 — TAGS & HASHTAG
- Đặt toàn bộ trong 1 khối code (text) để tiện sao chép 1 chạm.
- Dung lượng: Từ 300 đến 400 ký tự.
- Bao gồm từ khóa chủ đề, triệu chứng, giải pháp và đuôi cố định:
  ... bệnh trào ngược, bác sĩ hội, bác sĩ hội dạ dày, bác sĩ hội trào ngược, bác sĩ hội tiêu hóa, sức khỏe, tiêu hóa, bệnh dạ dày

### PHẦN 3 — MÔ TẢ CHUẨN SEO
Trình bày đầy đủ nội dung bài đăng theo đúng thứ tự sau:
1. Dòng đầu tiên: Tiêu đề video chuẩn SEO (chứa từ khóa chính ở 35 ký tự đầu, kết thúc bằng " | Bác sĩ Hội").
2. Đoạn dẫn nhập (2-3 câu): Nêu bật vấn đề/thói quen sai lầm và giải thích cơ chế phục hồi khoa học.
3. Mốc thời gian (Chapters): Định dạng "00:00 - ..." khớp theo từng ý chính trong bài.
4. Bộ 3 câu hỏi đánh trúng tâm lý người bệnh (dùng icon ✅).
5. KHỐI THÔNG TIN LIÊN HỆ MẶC ĐỊNH (giữ nguyên văn 100%, không thay đổi bất kỳ ký tự nào):

💬 Liên hệ trực tiếp với Bác sĩ Hội nếu bạn đang gặp vấn đề về dạ dày (viêm loét, trào ngược, nhiễm HP mãi không khỏi):

📱 Zalo Bác sĩ Hội: https://zalo.me/0356339115
   (hoặc lưu số: 0356339115)
💌 Nhắn tin Messenger: https://m.me/61570817367856
👥 Facebook: https://www.facebook.com/profile.php?id=61570817367856
👨‍⚕️ Nhóm Phục hồi dạ dày từ gốc: https://zalo.me/g/hxqwio935
▶️ Đăng ký kênh YouTube: https://www.youtube.com/@Bacsihoiofficial

👉 Do bác sĩ đang điều trị trực tiếp tại trung tâm Tiêu hóa nên không tiện nghe máy - vui lòng nhắn tin để được phản hồi sớm nhất.

6. Cảnh báo y khoa (Disclaimer):
⚠️ Lưu ý: Nội dung video chỉ mang tính chất tham khảo, chia sẻ kinh nghiệm. Không thay thế chẩn đoán và điều trị của bác sĩ. Vui lòng thăm khám trực tiếp khi có triệu chứng bất thường.

7. Dãy Hashtags kết bài: #bacsihoi #suckhoe #bacsihoidaday #bacsihoitraonguoc ..."""


# ----- khối cố định (nguyên văn theo yêu cầu user): luôn thay vào mô tả, không tin Gemini chép lại đúng -----
KHOI_LIEN_HE = """💬 Liên hệ trực tiếp với Bác sĩ Hội nếu bạn đang gặp vấn đề về dạ dày (viêm loét, trào ngược, nhiễm HP mãi không khỏi):

📱 Zalo Bác sĩ Hội: https://zalo.me/0356339115
   (hoặc lưu số: 0356339115)
💌 Nhắn tin Messenger: https://m.me/61570817367856
👥 Facebook: https://www.facebook.com/profile.php?id=61570817367856
👨‍⚕️ Nhóm Phục hồi dạ dày từ gốc: https://zalo.me/g/hxqwio935
▶️ Đăng ký kênh YouTube: https://www.youtube.com/@Bacsihoiofficial

👉 Do bác sĩ đang điều trị trực tiếp tại trung tâm Tiêu hóa nên không tiện nghe máy - vui lòng nhắn tin để được phản hồi sớm nhất."""
CANH_BAO = ("⚠️ Lưu ý: Nội dung video chỉ mang tính chất tham khảo, chia sẻ kinh nghiệm. "
            "Không thay thế chẩn đoán và điều trị của bác sĩ. Vui lòng thăm khám trực tiếp khi có triệu chứng bất thường.")
DUOI_TAGS = ("bệnh trào ngược, bác sĩ hội, bác sĩ hội dạ dày, bác sĩ hội trào ngược, "
             "bác sĩ hội tiêu hóa, sức khỏe, tiêu hóa, bệnh dạ dày")
HASHTAG_CO_DINH = ["#bacsihoi", "#suckhoe", "#bacsihoidaday", "#bacsihoitraonguoc"]
TAGS_TOI_DA = 490          # ngưỡng an toàn dưới giới hạn 500 của YouTube (youtube_upload lọc lại lần nữa theo cách đếm Studio)
TIEU_DE_TOI_DA = 100       # giới hạn YouTube
DUOI_TIEU_DE = "| Bác sĩ Hội"


def _sach(l):
    """Bỏ markdown/đánh dấu đầu-cuối dòng: ###, **, `, '- ' ..."""
    s = l.strip()
    s = re.sub(r"^[#>*\-\s`]+", "", s)
    s = re.sub(r"[*`\s]+$", "", s)
    return s.strip()


def _la_dong_hashtag(l):
    s = l.strip()
    return bool(s) and len(re.findall(r"#\w+", s)) >= 2 and len(re.sub(r"#\w+", "", s).strip()) <= 2


def _tach_tags(p2, toan_bo):
    """Thẻ YouTube: ưu tiên khối ``` ``` trong PHẦN 2; không có thì dòng có >= 3 dấu phẩy dài nhất.
    Ép đuôi cố định, cắt <= 500 ký tự tại dấu phẩy."""
    nguon = p2 or toan_bo
    m = re.search(r"```[a-zA-Z]*\s*\n(.*?)```", nguon, re.S)
    if m:
        cand = [l.strip() for l in m.group(1).splitlines() if l.count(",") >= 2]
    else:
        cand = [_sach(l) for l in nguon.splitlines() if l.count(",") >= 3]
    cand = [c for c in cand if not re.match(r"^(plaintext|text)$", c, re.I)]
    if not cand:
        return ""
    tags = max(cand, key=len).strip().strip("`")
    tags = re.sub(r"^(plaintext|text)\s*", "", tags, flags=re.I).strip().rstrip(",").strip()
    if "bác sĩ hội" not in tags.lower():
        tags = tags + ", " + DUOI_TAGS
    # dọn khoảng trắng quanh dấu phẩy, bỏ trùng (không phân biệt hoa thường)
    seen, out = set(), []
    for t in [x.strip() for x in tags.split(",") if x.strip()]:
        if t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    # quá 500 ký tự: bỏ bớt thẻ ở PHẦN TRƯỚC, giữ nguyên đuôi cố định (bác sĩ hội... bệnh dạ dày)
    duoi = [x.strip() for x in DUOI_TAGS.split(",")]
    duoi_lower = {x.lower() for x in duoi}
    dau = [t for t in out if t.lower() not in duoi_lower]
    cuoi = [t for t in out if t.lower() in duoi_lower] or duoi
    while dau and len(", ".join(dau + cuoi)) > TAGS_TOI_DA:
        dau.pop()
    return ", ".join(dau + cuoi)


def _tach_tieu_de(lines, toan_bo):
    """Tiêu đề: dòng đầu PHẦN 3 kết thúc '| Bác sĩ Hội' (bỏ markdown), <= 100 ký tự; không có thì tìm
    cả câu trả lời. Trả về (tiêu đề, chỉ số dòng trong lines hoặc -1)."""
    def ok(s):
        return s.endswith(DUOI_TIEU_DE) and 15 <= len(s) <= TIEU_DE_TOI_DA and not s.startswith(("💬", "📱", "▶", "👉", "⚠"))
    for k, l in enumerate(lines):
        s = _sach(l)
        if ok(s):
            return s, k
    for l in toan_bo.splitlines():
        s = _sach(l)
        if ok(s):
            return s, -1
    return "", -1


def _tach_hashtags(p3_lines, toan_bo):
    """Hashtag: dòng cuối toàn hashtag; không có thì gom hashtag ở 5 dòng cuối; luôn có 4 thẻ cố định đứng đầu."""
    tim = [l for l in p3_lines if _la_dong_hashtag(l)]
    nguon = tim[-1] if tim else " ".join(p3_lines[-5:] if p3_lines else toan_bo.splitlines()[-5:])
    tags = [t.lower() for t in re.findall(r"#\w+", nguon)]
    out = list(HASHTAG_CO_DINH)
    for t in tags:
        if t not in out:
            out.append(t)
    return out[:12]


def tach_ket_qua(text):
    """Tách câu trả lời Gemini thành nội dung dùng được, có kiểm tra để không lấy nhầm khi Gemini
    trả lời lệch định dạng. Trả về dict:
      tieu_de        : 1 dòng, kết thúc '| Bác sĩ Hội', <= 100 ký tự           (YouTube + TikTok + Zalo)
      tags           : thẻ YouTube, có đuôi cố định, <= 500 ký tự
      mo_ta          : phần mô tả (dẫn nhập + chapters + 3 câu hỏi) + KHỐI LIÊN HỆ CHUẨN + CẢNH BÁO + hashtag
      mo_ta_youtube  : tieu_de + dòng trống + mo_ta
      hashtags       : danh sách #..., 4 thẻ cố định đứng đầu                 (TikTok + Zalo: tieu_de + hashtag)
      noi_dung_ngan  : tieu_de + ' ' + hashtag
    Thiếu tiêu đề / thẻ / phần dẫn nhập -> ValueError (để tao_noi_dung mở chat mới làm lại)."""
    t = text.replace("\r", "")
    i2 = re.search(r"PHẦN\s*2", t, re.I)
    i3 = re.search(r"PHẦN\s*3", t, re.I)
    p2 = t[i2.end():i3.start()] if (i2 and i3 and i3.start() > i2.end()) else (t[i2.end():] if i2 and not i3 else "")
    p3 = t[i3.end():] if i3 else t
    tags = _tach_tags(p2, t)

    lines = [l.rstrip() for l in p3.splitlines() if l.strip()]
    lines = [l for l in lines if not re.match(r"^\s*[-—:#*]*\s*(MÔ TẢ CHUẨN SEO|TAGS\s*&|TAGS & HASHTAG)", _sach(l), re.I)]
    tieu_de, k = _tach_tieu_de(lines, t)
    than = lines[k + 1:] if k >= 0 else lines
    # phần thân = từ sau tiêu đề tới TRƯỚC khối liên hệ (💬) / cảnh báo (⚠) / dòng hashtag
    cat = len(than)
    for i, l in enumerate(than):
        s = l.strip()
        if s.startswith(("💬", "📱", "💌", "👥", "👨", "▶", "👉", "⚠")) or _la_dong_hashtag(s) or "zalo.me/0356339115" in s:
            cat = i
            break
    than = [_sach(l) if not re.match(r"^\s*\d{1,2}:\d{2}\s*-", l) and not l.strip().startswith("✅") else l.strip()
            for l in than[:cat]]
    than = [l for l in than if l and not re.match(r"^(plaintext|text)$", l, re.I)]
    hashtags = _tach_hashtags(lines, t)

    thieu = []
    if not tieu_de:
        thieu.append("tiêu đề (dòng kết thúc '| Bác sĩ Hội')")
    if not tags:
        thieu.append("thẻ (PHẦN 2)")
    if sum(len(l) for l in than) < 150:
        thieu.append("mô tả (dẫn nhập/chapters)")
    if thieu:
        raise ValueError("Gemini trả lời lệch định dạng, thiếu: " + "; ".join(thieu))

    # ghép mô tả: thân (dòng trống giữa dẫn nhập / chapters / 3 câu hỏi) + khối liên hệ chuẩn +
    # cảnh báo + hashtag
    def loai(l):
        if re.match(r"^\d{1,2}:\d{2}\s*-", l):
            return "chapter"
        if l.startswith("✅"):
            return "hoi"
        return "van"
    buf, truoc = [], None
    for l in than:
        lo = loai(l)
        if buf and lo != truoc:
            buf.append("")
        buf.append(l)
        truoc = lo
    body = "\n".join(buf)
    mo_ta = body.strip() + "\n\n" + KHOI_LIEN_HE + "\n\n" + CANH_BAO + "\n\n" + " ".join(hashtags)
    mo_ta = re.sub(r"\n{3,}", "\n\n", mo_ta)
    return dict(tieu_de=tieu_de, tags=tags, mo_ta=mo_ta, mo_ta_youtube=tieu_de + "\n\n" + mo_ta,
                hashtags=hashtags, noi_dung_ngan=tieu_de + " " + " ".join(hashtags), tho=text)


# ----- điều khiển trang Gemini (selector dò thật 15/10/2026, giao diện tiếng Việt) -----
SEL_INPUT = 'div.ql-editor[contenteditable="true"], rich-textarea div[contenteditable="true"]'
SEL_SEND = 'button[aria-label*="Gửi tin nhắn" i], button[aria-label*="Send message" i], button.send-button'
SEL_STOP = 'button[aria-label*="Ngừng" i], button[aria-label*="Dừng" i], button[aria-label*="Stop" i]'   # "Ngừng tạo câu trả lời"
SEL_RESPONSE = 'model-response'                 # mỗi câu trả lời = 1 <model-response> (bên trong có message-content)
SEL_RESPONSE_TEXT = 'message-content'
SEL_NEW_CHAT = 'a[href="/app"], [aria-label*="Cuộc trò chuyện mới" i], [aria-label*="New chat" i]'


def _text_cua(resp_el):
    mc = resp_el.locator(SEL_RESPONSE_TEXT)
    txt = mc.first.inner_text() if mc.count() else resp_el.inner_text()
    return re.sub(r"^\s*Gemini đã nói\s*", "", txt).strip()


def _cho_tra_loi_xong(page, so_truoc, log, timeout_sec=600):
    """Chờ câu trả lời mới: số <model-response> tăng, nút 'Ngừng tạo câu trả lời' biến mất, và chữ
    không đổi qua 3 lần đọc liên tiếp (1,5 s/lần). Gemini có lúc "suy nghĩ" 2-3 phút trước khi
    gõ chữ đầu tiên (đã gặp 15/10/2026) nên mặc định chờ tới 10 phút, cứ 30 s báo một lần."""
    t0 = time.time()
    deadline = t0 + timeout_sec
    last, on_dinh, bao = None, 0, 0
    while time.time() < deadline:
        resp = page.locator(SEL_RESPONSE)
        n = resp.count()
        dang_tao = page.locator(SEL_STOP).filter(visible=True).count() > 0
        if n > so_truoc:
            txt = _text_cua(resp.nth(n - 1))
            if not dang_tao and txt == last and len(txt) > 20:
                on_dinh += 1
                if on_dinh >= 3:
                    return txt
            else:
                on_dinh = 0
                last = txt
        da = int(time.time() - t0)
        if da // 30 > bao:
            bao = da // 30
            log(f"    ... vẫn chờ Gemini ({da}s, {'đang tạo' if dang_tao else 'chưa thấy trả lời'}, {n - so_truoc} câu trả lời mới)")
        time.sleep(1.5)
    raise RuntimeError(f"Gemini không trả lời xong trong {timeout_sec}s.")


def gui_mot_tin(page, noi_dung, log, timeout_sec=600):
    box = page.locator(SEL_INPUT).first
    box.wait_for(state="visible", timeout=30000)
    so_truoc = page.locator(SEL_RESPONSE).count()
    box.click()
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(noi_dung)
    page.wait_for_timeout(800)
    page.locator(SEL_SEND).first.click()
    log(f"  đã gửi {len(noi_dung)} ký tự, chờ Gemini...")
    return _cho_tra_loi_xong(page, so_truoc, log, timeout_sec=timeout_sec)


CHO_MOI_CAU_S = 300        # giây chờ tối đa mỗi câu trả lời trước khi coi là "suy nghĩ quá lâu"
SO_LAN_THU = 2             # quá lâu / không lấy được kết quả -> mở chat MỚI làm lại 1 lần, vẫn hỏng thì bỏ
VIDEO_TOI_DA_MOI_CHAT = 20 # một cuộc trò chuyện dùng cho nhiều video; quá số này mới mở chat mới (trang Gemini quá nặng)


def _chat_moi(page, log):
    """Về trang Gemini và bắt đầu cuộc trò chuyện mới (bỏ cuộc cũ, kể cả đang tạo dở)."""
    try:
        nut = page.locator(SEL_STOP).filter(visible=True).first
        if nut.count():
            nut.click(timeout=3000)          # đang tạo dở thì dừng
            page.wait_for_timeout(800)
    except Exception:
        pass
    page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    try:
        nc = page.locator(SEL_NEW_CHAT).first
        if nc.count() and nc.is_visible():
            nc.click()
            page.wait_for_timeout(1500)
    except Exception:
        pass
    page.locator(SEL_INPUT).first.wait_for(state="visible", timeout=30000)


class PhienGemini:
    """MỘT cuộc trò chuyện Gemini dùng chung cho cả loạt video (yêu cầu user 19/10/2026): prompt hệ
    thống gửi đúng 1 lần ở đầu chat, mỗi video sau chỉ gửi bản bóc băng — không đóng/mở lại, không
    điền lại prompt. Chỉ mở chat mới khi: chưa có chat, Gemini trả lời hỏng (suy nghĩ quá lâu /
    lệch định dạng), hoặc chat đã làm quá VIDEO_TOI_DA_MOI_CHAT video.

    Dùng:  phien = PhienGemini(page, log);  kq = phien.tao_noi_dung(ban_boc_bang)  (gọi lặp cho từng video)."""

    def __init__(self, page, log=print):
        self.page = page
        self.log = log
        self.san_sang = False       # đã có chat + đã gửi prompt hệ thống
        self.so_video = 0           # số video đã làm trong chat hiện tại
        self.tong_chat = 0          # số chat đã mở trong phiên (để báo nhật ký)

    def _bat_dau_chat(self):
        self.san_sang = False
        self.tong_chat += 1
        self.log("Mở Gemini, tạo cuộc trò chuyện mới" + (f" (chat thứ {self.tong_chat})" if self.tong_chat > 1 else "") + "...")
        _chat_moi(self.page, self.log)
        self.log("Gửi prompt hệ thống (1 lần cho cả cuộc trò chuyện)...")
        tl1 = gui_mot_tin(self.page, PROMPT_HE_THONG, self.log, timeout_sec=CHO_MOI_CAU_S)
        self.log(f"  Gemini đáp: {tl1[:80]!r}")
        self.san_sang = True
        self.so_video = 0

    def _gui_boc_bang(self, ban_boc_bang):
        # video thứ 2 trở đi: nhắc Gemini vẫn theo đúng quy tắc, chỉ xuất 2 phần, không nhắc video trước
        dau = "" if self.so_video == 0 else (
            "VIDEO TIẾP THEO — vẫn áp dụng đúng NHIỆM VỤ và QUY TẮC ĐẦU RA ở trên "
            "(chỉ xuất PHẦN 2 và PHẦN 3 cho bản bóc băng dưới đây, không nhắc lại video trước).\n\n")
        self.log(f"Gửi bản bóc băng (video thứ {self.so_video + 1} trong chat này)...")
        tl2 = gui_mot_tin(self.page, dau + "Bản bóc băng (Speech-to-Text thô, có mốc [mm:ss] đầu mỗi đoạn):\n\n" + ban_boc_bang,
                          self.log, timeout_sec=CHO_MOI_CAU_S)
        kq = tach_ket_qua(tl2)
        if not kq["tieu_de"] or len(kq["mo_ta"]) < 300 or not kq["tags"]:
            raise RuntimeError(f"Câu trả lời không đủ phần (tiêu đề {bool(kq['tieu_de'])}, mô tả {len(kq['mo_ta'])} ký tự, "
                               f"tags {len(kq['tags'])} ký tự)")
        return kq

    def tao_noi_dung(self, ban_boc_bang):
        """Bản bóc băng -> dict kết quả (xem tach_ket_qua), dùng lại chat đang có. Gemini suy nghĩ
        quá lâu hoặc trả lời thiếu phần thì mở chat mới (gửi lại prompt) làm lại đúng 1 lần; vẫn
        hỏng thì raise (bỏ qua video này; video kế sẽ bắt đầu bằng chat mới)."""
        loi_cuoi = None
        for lan in range(1, SO_LAN_THU + 1):
            try:
                if self.san_sang and self.so_video >= VIDEO_TOI_DA_MOI_CHAT:
                    self.log(f"Chat hiện tại đã làm {self.so_video} video -> mở chat mới cho nhẹ trang.")
                    self.san_sang = False
                if not self.san_sang:
                    self._bat_dau_chat()
                kq = self._gui_boc_bang(ban_boc_bang)
                self.so_video += 1
                self.log(f"✓ Nhận kết quả: tiêu đề {kq['tieu_de']!r}, tags {len(kq['tags'])} ký tự, mô tả {len(kq['mo_ta'])} ký tự, "
                         f"{len(kq['hashtags'])} hashtag")
                return kq
            except Exception as e:              # noqa: BLE001
                loi_cuoi = e
                self.san_sang = False           # lần sau (video này hoặc video kế) mở chat mới
                if lan < SO_LAN_THU:
                    self.log(f"⚠ Lần {lan} hỏng ({str(e)[:120]}) -> bỏ cuộc trò chuyện này, mở chat mới làm lại.")
                else:
                    self.log(f"✗ Lần {lan} vẫn hỏng ({str(e)[:120]}) -> bỏ qua video này.")
        raise RuntimeError(f"Gemini không cho kết quả sau {SO_LAN_THU} lần: {loi_cuoi}")


def tao_noi_dung(page, ban_boc_bang, log=print):
    """Một video, chat mới -> prompt hệ thống -> bản bóc băng (giữ cho script cũ trong dom_dump/noi_dung).
    App dùng PhienGemini để nhiều video chung một cuộc trò chuyện."""
    return PhienGemini(page, log).tao_noi_dung(ban_boc_bang)
