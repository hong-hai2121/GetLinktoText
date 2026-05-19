# FB Ads Accounts → Google Sheets

Lấy danh sách tài khoản quảng cáo Facebook và ghi vào Google Sheet.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình Google Service Account

1. Vào [Google Cloud Console](https://console.cloud.google.com/)
2. Tạo project mới (hoặc chọn project có sẵn)
3. Bật 2 API:
   - **Google Sheets API**
   - **Google Drive API**
4. Tạo **Service Account**:
   - IAM & Admin → Service Accounts → Create Service Account
   - Đặt tên, nhấn Done
   - Vào service account vừa tạo → Keys → Add Key → JSON
   - Tải file JSON về, đổi tên thành `service_account.json`, đặt vào thư mục này
5. **Chia sẻ Google Sheet** với email của service account (dạng `xxx@project.iam.gserviceaccount.com`) với quyền **Editor**

## Cấu hình Facebook Access Token

- Điền **User Access Token** hoặc **System User Token** vào ô **I2** trong sheet
- Token cần có quyền: `ads_read`, `ads_management`
- Lấy token tại: https://developers.facebook.com/tools/explorer/

## Chạy

```bash
python main.py
```

## Dữ liệu ghi vào sheet "Tổng Hợp Các Tài Khoản Quảng Cáo"

| Cột | Nội dung |
|-----|----------|
| ID Tài Khoản | act_xxxxxxxxxx |
| Tên Tài Khoản | Tên hiển thị |
| Trạng Thái | Đang hoạt động / Đã tắt / ... |
| Tiền Tệ | VND / USD / ... |
| Múi Giờ | Asia/Ho_Chi_Minh / ... |
| Đã Chi (USD) | Tổng tiền đã tiêu |
| Số Dư | Số dư hiện tại |
| Business | Tên Business Manager |
| Cập Nhật Lúc | Thời điểm chạy script |
