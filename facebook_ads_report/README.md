# Facebook Ads Report Tool

Tự động lấy dữ liệu Facebook Ads và lưu vào Google Sheets.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Thiết lập Google Credentials (bắt buộc)

Script cần file `credentials.json` để ghi vào Google Sheets.

### Bước 1 — Tạo Google Cloud Project & kích hoạt API

1. Truy cập https://console.cloud.google.com/
2. Tạo project mới (hoặc dùng project sẵn có)
3. Vào **APIs & Services → Library**
4. Tìm và **Enable** hai API:
   - `Google Sheets API`
   - `Google Drive API`

### Bước 2 — Tạo Service Account

1. Vào **APIs & Services → Credentials**
2. Nhấn **Create Credentials → Service Account**
3. Đặt tên bất kỳ → **Create and continue → Done**
4. Click vào Service Account vừa tạo
5. Vào tab **Keys → Add Key → Create new key → JSON**
6. File JSON sẽ tự tải về → **đổi tên thành `credentials.json`**
7. Đặt file `credentials.json` vào cùng thư mục với `main.py`

### Bước 3 — Chia sẻ Google Sheet với Service Account

1. Mở file `credentials.json`, tìm trường `"client_email"` (dạng `xxx@xxx.iam.gserviceaccount.com`)
2. Mở Google Sheet cần ghi dữ liệu
3. Nhấn **Share** → nhập email của Service Account → chọn **Editor** → **Send**

## Chạy

```bash
python main.py
```

## Kết quả

Google Sheet sẽ có 2 tab:

| Tab | Nội dung |
|-----|----------|
| **Chi tiêu theo ngày** | Ngày, Chi tiêu, Hiển thị, Click, CPM, CPC |
| **Chi tiết Campaign** | Tên, Trạng thái, Ngày bắt đầu/kết thúc, Chi tiêu, Kết quả, CPA, ROAS |

## Lưu ý Access Token

Access Token Facebook có thời hạn. Nếu gặp lỗi `Invalid OAuth access token`, hãy tạo token mới tại:
https://developers.facebook.com/tools/explorer/
