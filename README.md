# GetLinktoText

Repo gom nhiều tool, mỗi tool một thư mục. Tool gốc **GetTextFromLink** (lấy chữ từ
link video bằng Whisper) nằm trọn trong `GetTextFromLink/`.

## GetTextFromLink

Mọi thứ của tool nằm trong `GetTextFromLink/`:

- `GetTextFromLink.py`: entrypoint GUI. Chạy từ gốc repo: `venv\Scripts\python GetTextFromLink\GetTextFromLink.py`.
- `run_lnk.pyw` + `GetTextFromLink.lnk`: mở GUI qua shortcut, không hiện console; xuất `final_result_lnk.docx`, log ra `lnk_run.log`.
- `config.py`, `profiles_config.py`: đường dẫn dữ liệu và profile Firefox. Các tool khác
  (`ReelStats/`, `scripts/`, `SourceTruyen/SRTUI/`) import 2 file này bằng cách thêm
  `GetTextFromLink/` vào `sys.path`.
- `src/`: mã runtime (pipeline, GUI, nhận diện, xuất Word).
- `cli.py`, `main.py`, `app.py`, `test_run_gui.py`: entrypoint phụ (dòng lệnh, Flask, test GUI).
- `geckodriver.exe`, `GetTextFromLink.ico`: tài nguyên.
- `whisper_cache/`: model Whisper, dùng chung với `DangvideoYTBTikTokZalo/` và `GoogleFlowGhepVideo/`.
- `linkgettoText.txt`, `processed_links.txt`, `failed_links.txt`, `output_videos/`, `final_result*.docx`: dữ liệu vào/ra, không đưa lên Git.
- `GetTextFromLink_Package/`: đóng gói bộ cài Windows (xem dưới).

## Bộ cài Windows

Bản CPU dành cho Windows 10/11 x64, kèm Python, FFmpeg, geckodriver và model
`large-v3-turbo`. Máy đích không cần cài Python/CUDA. Chuyển file
`GetTextFromLink/GetTextFromLink_Package/dist/installer/GetTextFromLink-Setup-1.0.1-CPU-x64.exe` sang máy khác và chạy để cài.
Hướng dẫn sử dụng: [HUONG_DAN.html](GetTextFromLink/GetTextFromLink_Package/packaging/HUONG_DAN.html).

Toàn bộ phần đóng gói được gom trong `GetTextFromLink/GetTextFromLink_Package/`
(đường dẫn dưới đây tính từ thư mục đó):

- `.build-gettext/`: môi trường Python dùng để build, không đưa lên Git.
- `build/`: tài nguyên, file trung gian và báo cáo kiểm tra, không đưa lên Git.
- `dist/GetTextFromLink/`: bản chạy trực tiếp (cần giữ cả thư mục).
- `dist/installer/`: file bộ cài `.exe` để gửi sang máy khác.
- `packaging/`, `GetTextFromLink.spec`, `Build_GetTextFromLink.cmd`: cấu hình và script build.
- `logs/`: nhật ký build, không đưa lên Git.

Để tạo lại bộ cài trên máy phát triển: cài Python 3.12 x64 và Inno Setup 6/7,
sau đó chạy `GetTextFromLink/GetTextFromLink_Package/Build_GetTextFromLink.cmd` hoặc
`py -3.12 GetTextFromLink/GetTextFromLink_Package/packaging/build_installer.py`.
Script tạo môi trường riêng `GetTextFromLink_Package/.build-gettext`, lấy FFmpeg thật (không lấy shim
Chocolatey), model trong `GetTextFromLink/whisper_cache`, và chỉ đóng gói các tài nguyên đã chỉ định.
Có thể truyền `--ffmpeg-dir PATH_TO_BIN` và `--model-dir PATH_TO_MODEL`.
Danh sách phiên bản đã dùng được lưu trong `GetTextFromLink_Package/packaging/requirements-lock.txt`.

Mở terminal trong `GetTextFromLink/GetTextFromLink_Package`, chạy
`.build-gettext\Scripts\python.exe packaging\verify_installer.py` để kiểm tra bộ cài:
script cài vào thư mục thử, kiểm tra giao diện/model offline/Word với đường dẫn tiếng
Việt và PATH sạch, rồi gỡ bản thử. Script từ chối chạy nếu tài khoản Windows đã cài
GetTextFromLink. Khi có `build/test-data/speech.wav` bên trong thư mục tổng, kiểm tra thêm luồng
FFmpeg → nhận diện CPU → xuất Word. Báo cáo nằm trong `GetTextFromLink_Package/build/verification`.

Bản cài đặt lưu dữ liệu ở `%LOCALAPPDATA%\GetTextFromLink`, model đi kèm được đọc
trực tiếp từ thư mục cài đặt. Chạy file Python gốc vẫn giữ đường dẫn dữ liệu hiện có
và dùng GPU nếu PyTorch/CUDA đã sẵn sàng. Firefox và đăng nhập trên máy đích chỉ cần
cho chức năng ChatGPT hoặc video yêu cầu cookie; nhận diện file cục bộ dùng được offline.

## Mục đích thư mục

- `GetTextFromLink/`: Tool lấy chữ từ link video (xem mục trên) — mã runtime `src/`, config, dữ liệu, model và bộ đóng gói.
- `scripts/`: Script phụ trợ/tiện ích để chạy tay (thu thập dữ liệu, xử lý âm thanh/video, gửi nội dung).
- `experiments/`: Thử nghiệm hoặc script test nhanh (ví dụ: kiểm tra driver, thử logic mới).
- `SourceTruyen/`: Bộ script riêng cho luồng xử lý truyện/CapCut.
- `backup/`: Lưu trữ bản sao hoặc dữ liệu tạm.
- Các thư mục khác (`ADS*`, `DangvideoYTBTikTokZalo/`, `GoogleFlowGhepVideo/`, `HoaDonMISA/`, `ReelStats/`, `vietlot655/`...): mỗi tool một thư mục riêng.

Ở thư mục gốc chỉ còn `venv/` dùng chung và bộ "Kết nối AI" (`ket_noi_ai.py`, `hoi_claude.py`, `hoi_gpt.py`, `hoi_gemini.py`, `cli_chung.py`, `mo_ket_noi_ai.bat`).
