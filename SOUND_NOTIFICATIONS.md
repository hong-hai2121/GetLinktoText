# Thông Báo Âm Thanh - GetTextFromLink

## Mô Tả
Chương trình đã được thêm tính năng phát thông báo âm thanh (sound notifications) để thông báo khi:
- ✅ **Hoàn thành thành công** - Phát 3 tiếng beep ngắn (tần số 1000Hz)
- ❌ **Lỗi xảy ra** - Phát 2 tiếng beep dài (tần số 400Hz)
- ⚠️ **Cảnh báo** - Phát 1 tiếng beep (tần số 800Hz)

## Các Điểm Phát Thông Báo Âm Thanh

### Thành Công (Success) - 3 tiếng beep ngắn
- Khi hoàn thành xử lý tất cả video
- Khi gửi nội dung thành công đến ChatGPT

### Lỗi (Error) - 2 tiếng beep dài
- Lỗi khi tải model Whisper
- Lỗi khi lấy tiêu đề video
- Lỗi khi lấy URL video
- Lỗi khi tải video (Facebook hoặc TikTok)
- Lỗi khi trích xuất âm thanh
- Lỗi khi chia nhỏ file âm thanh
- Lỗi khi lấy thời lượng file âm thanh
- Lỗi trong quá trình xử lý chung

### Cảnh Báo (Warning) - 1 tiếng beep
- Phát hiện nội dung spam hoặc lặp
- Phát hiện câu lặp liên tiếp
- Phát hiện quá nhiều câu bị lặp

## Hỗ Trợ Các Hệ Điều Hành

### Windows
- Sử dụng `winsound.Beep()` - hỗ trợ tần số và thời lượng tùy chỉnh

### macOS
- Sử dụng hệ thống âm thanh `afplay`
- Success: Glass.aiff
- Error: Sosumi.aiff

### Linux
- Sử dụng `paplay` nếu có
- Hoặc fallback đến lệnh `beep` hệ thống

## Thay Đổi Code

### 1. Thêm Import
```python
import platform
import sys
```

### 2. Hàm play_sound()
```python
def play_sound(sound_type="success"):
    """
    Phát âm thanh thông báo
    sound_type: "success" (hoàn thành), "error" (lỗi), "warning" (cảnh báo)
    """
    # Mã hiện thực cho các hệ điều hành khác nhau
```

### 3. Các Lệnh Gọi Hàm
Hàm `play_sound()` được gọi ở:
- `run_pipeline_thread()` - Khi hoàn thành hay có lỗi xử lý
- `process_videos()` - Khi hoàn thành tất cả video
- Các hàm xử lý lỗi trong việc tải video, trích xuất âm thanh, v.v.
- Hàm `detect_repetition()` - Khi phát hiện lỗi lặp

## Cách Sử Dụng

Chương trình sẽ tự động phát âm thanh mà không cần cấu hình thêm. Bạn sẽ nghe được:

1. **Khi khởi động xử lý:**
   - Nếu lỗi tải model → Nghe 2 tiếng beep dài
   
2. **Trong quá trình xử lý:**
   - Nếu lỗi tải video → Nghe 2 tiếng beep dài
   - Nếu lỗi trích xuất âm thanh → Nghe 2 tiếng beep dài
   - Nếu phát hiện lỗi lặp → Nghe 1 tiếng beep
   
3. **Khi kết thúc:**
   - Nếu hoàn thành thành công → Nghe 3 tiếng beep ngắn
   - Nếu có lỗi trong quá trình xử lý → Nghe 2 tiếng beep dài

## Cấu Hình Âm Thanh

Nếu bạn muốn thay đổi tần số hoặc thời lượng, hãy chỉnh sửa các thông số trong hàm `play_sound()`:

```python
# Success
winsound.Beep(1000, 200)  # 1000Hz, 200ms

# Error
winsound.Beep(400, 300)   # 400Hz, 300ms

# Warning
winsound.Beep(800, 200)   # 800Hz, 200ms
```

## Lợi Ích

✅ Giúp bạn biết ngay khi có lỗi mà không cần phải nhìn màn hình
✅ Thông báo khi quá trình xử lý hoàn thành
✅ Cảnh báo khi phát hiện lỗi trong dữ liệu (lặp, spam)
✅ Hỗ trợ đa nền tảng (Windows, macOS, Linux)
