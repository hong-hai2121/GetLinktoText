# GetLinktoText

## Bộ cài Windows

Bản CPU dành cho Windows 10/11 x64, kèm Python, FFmpeg, geckodriver và model
`large-v3-turbo`. Máy đích không cần cài Python/CUDA. Chuyển file
`GetTextFromLink_Package/dist/installer/GetTextFromLink-Setup-1.0.0-CPU-x64.exe` sang máy khác và chạy để cài.
Hướng dẫn sử dụng: [HUONG_DAN.html](GetTextFromLink_Package/packaging/HUONG_DAN.html).

Toàn bộ phần đóng gói được gom trong `GetTextFromLink_Package/`:

- `.build-gettext/`: môi trường Python dùng để build, không đưa lên Git.
- `build/`: tài nguyên, file trung gian và báo cáo kiểm tra, không đưa lên Git.
- `dist/GetTextFromLink/`: bản chạy trực tiếp (cần giữ cả thư mục).
- `dist/installer/`: file bộ cài `.exe` để gửi sang máy khác.
- `packaging/`, `GetTextFromLink.spec`, `Build_GetTextFromLink.cmd`: cấu hình và script build.
- `logs/`: nhật ký build, không đưa lên Git.

Để tạo lại bộ cài trên máy phát triển: cài Python 3.12 x64 và Inno Setup 6/7,
sau đó chạy `GetTextFromLink_Package/Build_GetTextFromLink.cmd` hoặc
`py -3.12 GetTextFromLink_Package/packaging/build_installer.py`.
Script tạo môi trường riêng `GetTextFromLink_Package/.build-gettext`, lấy FFmpeg thật (không lấy shim
Chocolatey), model trong `whisper_cache`, và chỉ đóng gói các tài nguyên đã chỉ định.
Có thể truyền `--ffmpeg-dir PATH_TO_BIN` và `--model-dir PATH_TO_MODEL`.
Danh sách phiên bản đã dùng được lưu trong `GetTextFromLink_Package/packaging/requirements-lock.txt`.

Mở terminal trong `GetTextFromLink_Package`, chạy
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

- `src/`: Mã chạy chính (runtime) cho ứng dụng, nơi chứa pipeline, GUI và các thành phần core.
- `scripts/`: Script phụ trợ/tiện ích để chạy tay (thu thập dữ liệu, xử lý âm thanh/video, gửi nội dung).
- `experiments/`: Thử nghiệm hoặc script test nhanh (ví dụ: kiểm tra driver, thử logic mới).
- `SourceTruyen/`: Bộ script riêng cho luồng xử lý truyện/CapCut.
- `backup/`: Lưu trữ bản sao hoặc dữ liệu tạm.

Các file còn lại ở thư mục gốc là entrypoint hoặc tài nguyên dữ liệu phục vụ cho việc chạy ứng dụng.
