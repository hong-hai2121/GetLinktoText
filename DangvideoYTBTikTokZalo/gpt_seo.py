# -*- coding: utf-8 -*-
"""Viết nội dung SEO bằng ChatGPT qua Codex CLI (hoi_gpt.py ở thư mục cha, tài khoản ChatGPT đang đăng
nhập trên máy, không cần API key) — lựa chọn thứ hai bên cạnh Gemini qua trình duyệt (gemini_seo).

Khác Gemini (một cuộc trò chuyện dùng chung, prompt gửi 1 lần): với CLI KHÔNG giữ hội thoại — MỖI VIDEO
LÀ MỘT YÊU CẦU TRỌN VẸN (PROMPT_GPT + bản nhận diện giọng nói trong cùng một lần gửi, user 26/10/2026).
PROMPT_GPT riêng cho GPT: cấm dẫn nguồn/link/markdown, cấm giọng rào đón; kết quả tách bằng
gemini_seo.tach_ket_qua (cùng định dạng PHẦN 2 / PHẦN 3).
"""
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR.parent))          # hoi_gpt.py + cli_chung.py nằm ở GetLinktoText/
import hoi_gpt                                    # noqa: E402

from gemini_seo import SO_LAN_THU, tach_ket_qua   # noqa: E402

CHO_MOI_CAU_S = 600

# Prompt riêng cho ChatGPT (26/10/2026). Khối liên hệ + cảnh báo KHÔNG bắt GPT viết: tach_ket_qua tự ghép
# nguyên văn (KHOI_LIEN_HE, CANH_BAO) nên không sợ GPT chép sai.
PROMPT_GPT = """Bạn là biên tập viên nội dung cho kênh YouTube "Bác sĩ Hội" — bác sĩ chuyên khoa tiêu hóa (dạ dày, trào ngược, vi khuẩn HP, đại tràng). Khán giả là cô chú trung niên.

Tôi gửi bản NHẬN DIỆN GIỌNG NÓI thô của một video (Speech-to-Text, có mốc [mm:ss] đầu mỗi đoạn), còn lỗi chính tả và thuật ngữ y khoa bị nghe sai. Hãy hiểu đúng nội dung bác sĩ nói trong video rồi viết nội dung đăng YouTube.

NGUYÊN TẮC VIẾT (bắt buộc, vi phạm là hỏng):
1. CHỈ dựa vào nội dung trong bản nhận diện. KHÔNG thêm kiến thức ngoài video, KHÔNG dẫn nguồn, KHÔNG viết "Tham khảo", KHÔNG chèn link, KHÔNG nhắc tên tổ chức (NIDDK, WHO, Bộ Y tế...), KHÔNG chú thích.
2. Giọng văn là lời Bác sĩ Hội nói với cô chú: thân mật, gần gũi, khẳng định đúng như bác sĩ nói trong video. Gọi người xem là "cô chú". KHÔNG rào đón kiểu "có thể", "ở một số người", "cân nhắc theo khả năng dung nạp", "chưa được chứng minh", "nên tham khảo ý kiến bác sĩ". KHÔNG tự thêm lưu ý hay cảnh báo y khoa (hệ thống tự thêm sau).
3. Thuần văn bản: trong PHẦN 3 KHÔNG dùng markdown (không **, không [chữ](link), không gạch đầu dòng, không tiêu đề ###). Không dùng tiếng Anh, trừ tên thuốc và thuật ngữ quốc tế.
4. Sửa đúng thuật ngữ y khoa, tên thuốc, tên bệnh mà Speech-to-Text nghe sai.

ĐẦU RA: xuất đúng 2 phần dưới đây, không lời chào, không giải thích gì thêm.

### PHẦN 2 — TAGS & HASHTAG
Một khối code (```text) chứa 12–16 từ khóa YouTube cách nhau bằng dấu phẩy, tổng 300–400 ký tự: từ khóa chủ đề, triệu chứng, giải pháp trong video, rồi kết thúc bằng đuôi cố định: bệnh trào ngược, bác sĩ hội, bác sĩ hội dạ dày, bác sĩ hội trào ngược, bác sĩ hội tiêu hóa, sức khỏe, tiêu hóa, bệnh dạ dày. Trong khối này KHÔNG có dấu #, KHÔNG có hashtag.

### PHẦN 3 — MÔ TẢ CHUẨN SEO
Viết đúng thứ tự sau, các khối cách nhau một dòng trống:
1. Dòng đầu tiên: tiêu đề video chuẩn SEO, từ khóa chính nằm trong 35 ký tự đầu, tối đa 90 ký tự, kết thúc bằng " | Bác sĩ Hội".
2. Đoạn dẫn nhập 2–3 câu: nêu vấn đề hoặc thói quen sai mà cô chú hay gặp và điều bác sĩ hướng dẫn trong video; viết chắc chắn, hấp dẫn, đúng ý video.
3. Mốc thời gian: mỗi dòng "mm:ss - nội dung", lấy đúng mốc [mm:ss] trong bản nhận diện, 5–8 mốc.
4. Ba câu hỏi đánh trúng nỗi lo của cô chú, mỗi câu một dòng, bắt đầu bằng "✅ ".
5. Dòng cuối cùng: dãy hashtag, bắt đầu bằng #bacsihoi #suckhoe #bacsihoidaday #bacsihoitraonguoc rồi thêm 4–8 hashtag theo chủ đề video, viết liền không dấu.
KHÔNG viết khối liên hệ, KHÔNG viết lưu ý/cảnh báo — hệ thống tự ghép sau."""


class PhienGPT:
    """Cùng giao diện với gemini_seo.PhienGemini (tao_noi_dung, so_video) nhưng KHÔNG giữ hội thoại:
    mỗi video = một lần gọi `codex exec` với PROMPT_GPT + bản nhận diện. Hỏng thì gửi lại đúng 1 lần."""

    def __init__(self, log=print, model=None):
        self.log = log
        self.model = model or None
        self.so_video = 0

    def _gui(self, ban_nhan_dien):
        self.log(f"Gửi ChatGPT (Codex CLI) video thứ {self.so_video + 1}: prompt + bản nhận diện {len(ban_nhan_dien)} ký tự "
                 "trong MỘT yêu cầu...")
        r = hoi_gpt.hoi(PROMPT_GPT + "\n\nBẢN NHẬN DIỆN GIỌNG NÓI:\n\n" + ban_nhan_dien,
                        model=self.model, thu_muc=APP_DIR, thoi_gian=CHO_MOI_CAU_S)
        tl = r.text
        self.log(f"  ChatGPT trả lời {len(tl)} ký tự" + (f" (model {r.model})" if r.model else "") + ".")
        kq = tach_ket_qua(tl)
        if not kq["tieu_de"] or len(kq["mo_ta"]) < 300 or not kq["tags"]:
            raise RuntimeError(f"Câu trả lời không đủ phần (tiêu đề {bool(kq['tieu_de'])}, mô tả {len(kq['mo_ta'])} ký tự, "
                               f"tags {len(kq['tags'])} ký tự)")
        return kq

    def tao_noi_dung(self, ban_nhan_dien):
        loi_cuoi = None
        for lan in range(1, SO_LAN_THU + 1):
            try:
                kq = self._gui(ban_nhan_dien)
                self.so_video += 1
                self.log(f"✓ Nhận kết quả: tiêu đề {kq['tieu_de']!r}, tags {len(kq['tags'])} ký tự, mô tả {len(kq['mo_ta'])} ký tự, "
                         f"{len(kq['hashtags'])} hashtag")
                return kq
            except Exception as e:              # noqa: BLE001
                loi_cuoi = e
                if lan < SO_LAN_THU:
                    self.log(f"⚠ Lần {lan} hỏng ({str(e)[:160]}) -> gửi lại.")
                else:
                    self.log(f"✗ Lần {lan} vẫn hỏng ({str(e)[:160]}) -> bỏ qua video này.")
        raise RuntimeError(f"ChatGPT không cho kết quả sau {SO_LAN_THU} lần: {loi_cuoi}")


def trang_thai():
    """Trạng thái Codex CLI / đăng nhập ChatGPT (dict của hoi_gpt.trang_thai) — cho nút Kiểm tra + đèn trạng thái."""
    try:
        return hoi_gpt.trang_thai()
    except Exception as e:                      # noqa: BLE001
        return {"ok": False, "ghi_chu": str(e)[:300]}


def danh_sach_model():
    try:
        return hoi_gpt.danh_sach_model()
    except Exception:                           # noqa: BLE001
        return []
