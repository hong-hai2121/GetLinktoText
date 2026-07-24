# GetTextLargeV3

Bản sao chức năng của **GetTextFromLink** (tải video Facebook/TikTok → tách audio →
nhận diện giọng nói bằng Whisper → xuất Word, kèm tùy chọn gửi ChatGPT qua Firefox),
nhưng **chỉ dùng đúng một model**: checkpoint OpenAI‑Whisper `large-v3.pt`.

## Khác biệt so với bản gốc

| | Bản gốc (GetLinktoText) | Bản này (GetTextLargeV3) |
|---|---|---|
| Engine | `faster-whisper` | `openai-whisper` |
| Model | `large-v3-turbo` (+ chọn được tiny…large trong GUI) | **cố định `large-v3.pt`**, không chọn model khác |
| Nguồn model | tải theo tên vào `whisper_cache/` | nạp thẳng từ file `whisper_cache/large-v3.pt` |

Model được đặt tại: `whisper_cache/large-v3.pt` (~2.9 GB, đã copy sẵn vào dự án).
Đường dẫn khai báo ở `config.py` → `WHISPER_MODEL_FILE`.

## Cách chạy

Dùng chung virtualenv của thư mục cha (`../venv`), nơi đã cài `openai-whisper`,
`torch` (CUDA 12.1), `faster-whisper`, `yt-dlp`, `selenium`, `pydub`, `python-docx`…

```powershell
# GUI (khuyến nghị)
..\venv\Scripts\python.exe GetTextFromLink.py

# GUI ẩn cửa sổ đen (dùng cho shortcut .lnk)
..\venv\Scripts\pythonw.exe run_lnk.pyw

# Không GUI (CLI) — đọc link từ linkgettoText.txt
..\venv\Scripts\python.exe cli.py
```

Yêu cầu ngoài Python: **ffmpeg** trong PATH, **geckodriver.exe** (đã kèm) và Firefox
(chỉ cần khi bật chế độ gửi ChatGPT).

## Quy trình

1. Đọc danh sách link trong `linkgettoText.txt`.
2. Tải video (Facebook/TikTok) hoặc dùng file local.
3. `ffmpeg` tách audio 16kHz mono.
4. `openai-whisper` (large-v3.pt) nhận diện tiếng Việt.
5. Xuất kết quả ra `final_result.docx` (hoặc `final_result_lnk.docx` khi chạy qua `.lnk`).

## Ghi chú kỹ thuật

- `src/services/get_text.py` → `load_model()` luôn nạp `WHISPER_MODEL_FILE`, bỏ qua
  tên model được truyền vào.
- `src/transcribe.py` dùng API `model.transcribe(...)` của openai-whisper (đã bỏ
  `vad_filter`/`vad_parameters` vốn là tham số riêng của faster-whisper) và **không**
  còn cơ chế tự đổi sang model khác khi phát hiện lặp từ.
- Chạy GPU tự động nếu `torch.cuda.is_available()`; nếu không thì chạy CPU.

Muốn tạm dùng file `.pt` ở nơi khác (ví dụ file gốc trong `../whisper_cache/`):

```powershell
$env:WHISPER_MODEL_FILE = "D:\Python\GetLinktoText\whisper_cache\large-v3.pt"
..\venv\Scripts\python.exe GetTextFromLink.py
```
