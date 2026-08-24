# myedit — audio giọng nói → video có ảnh minh họa

Đưa vào 1 file audio (giọng đọc của bạn), nhận về 1 video: audio gốc + ảnh
minh họa lấy từ kho ảnh stock, mỗi cảnh 8-20 giây có hiệu ứng zoom nhẹ.

## Chuỗi xử lý

| Bước | File | Việc làm | Kết quả |
|------|------|----------|---------|
| 1 | `nhandien_audio.py` | faster-whisper (large-v3-turbo, offline từ `../whisper_cache`) | `transcript.json` |
| 2 | `chia_canh.py` | Gemini API chia cảnh + sinh từ khóa ảnh tiếng Anh | `canh.json` |
| 3 | `tai_anh.py` | tải ảnh Pexels / Pixabay / Openverse, crop 1920x1080 | `anh/canh_*.jpg` |
| 4 | `ghep_video.py` | ffmpeg Ken Burns từng cảnh rồi nối + ghép audio | `video_ra.mp4` |

Chạy cả chuỗi (dùng venv gốc repo):

```
D:\Python\GetLinktoText\venv\Scripts\python.exe chay.py mau\audio_mau.m4a
```

Bước nào có kết quả rồi thì tự bỏ qua — muốn làm lại thì xóa file kết quả
của bước đó (xóa vào Thùng rác cho an toàn).

## Key cần điền vào `.env` gốc repo

- `GEMINI_API_KEY` — bắt buộc cho bước 2. Lấy miễn phí: https://aistudio.google.com/apikey
  (chưa có key vẫn dùng được: bước 2 sẽ xuất `prompt_chia_canh.txt` để dán tay
  vào Gemini web, rồi nhập lại bằng `chia_canh.py ... --nhap <file>`)
- `PEXELS_API_KEY` — nên có, ảnh đẹp nhất. Miễn phí 200 lượt/giờ: https://www.pexels.com/api/
- `PIXABAY_API_KEY` — dự phòng. Miễn phí: https://pixabay.com/api/docs/

Không có key ảnh nào thì rơi về Openverse (không cần key nhưng giới hạn chặt);
cảnh không tìm được ảnh sẽ tự vẽ thẻ chữ nền tối để video không thủng lỗ.

## Hướng phát triển tiếp

- Phụ đề: mượn kho kiểu sub `kieusub.py` bên OmniVoice (chỉ mượn ý tưởng,
  không liên kết cài đặt).
- "AI duyệt ảnh": bước tùy chọn cho AI nhìn từng ảnh đã tải, đánh giá có khớp
  nội dung cảnh không, không khớp thì đổi từ khóa tìm lại.
- Giao diện web giống myvoice/myvideo khi pipeline đã chạy ổn.
