# GetLinktoText

## Bộ cài Windows

Bản CPU dành cho Windows 10/11 x64, kèm Python, FFmpeg, geckodriver và model
`large-v3-turbo`. Máy đích không cần cài Python/CUDA. Chuyển file
`dist/installer/GetTextFromLink-Setup-1.0.0-CPU-x64.exe` sang máy khác và chạy để cài.
Hướng dẫn sử dụng: [packaging/HUONG_DAN.html](packaging/HUONG_DAN.html).

Để tạo lại bộ cài trên máy phát triển: cài Python 3.12 x64 và Inno Setup 6/7,
sau đó chạy `Build_GetTextFromLink.cmd` hoặc `py -3.12 packaging/build_installer.py`.
Script tạo môi trường riêng `.build-gettext`, lấy FFmpeg thật (không lấy shim
Chocolatey), model trong `whisper_cache`, và chỉ đóng gói các tài nguyên đã chỉ định.
Có thể truyền `--ffmpeg-dir PATH_TO_BIN` và `--model-dir PATH_TO_MODEL`.
Danh sách phiên bản đã dùng được lưu trong `packaging/requirements-lock.txt`.

Kiểm tra bộ cài bằng `.build-gettext\Scripts\python.exe packaging\verify_installer.py`:
script cài vào thư mục thử, kiểm tra giao diện/model offline/Word với đường dẫn tiếng
Việt và PATH sạch, rồi gỡ bản thử. Script từ chối chạy nếu tài khoản Windows đã cài
GetTextFromLink. Khi có `build/gettext/test-data/speech.wav`, kiểm tra thêm luồng
FFmpeg → nhận diện CPU → xuất Word. Báo cáo nằm trong `build/gettext/verification`.

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
