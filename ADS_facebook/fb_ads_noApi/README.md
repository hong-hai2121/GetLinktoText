# fb_ads_noApi — Nhập FB Billing vào Google Sheet, không cần Facebook API

Thư mục **độc lập**: có sẵn `service_account.json`, không phụ thuộc `fb_ads_accounts`
(không đọc FB token, không tra tab "TKQC API").

## Chạy

Nhấp đúp **`run.bat`** (dùng venv `GetLinktoText\venv`), hoặc:

```bat
cd D:\Python\GetLinktoText\ADS_facebook\fb_ads_noApi
python fb_billing_import_web.py
```

Cài thư viện nếu thiếu: `pip install -r requirements.txt`. App chạy server nội bộ rồi tự mở **tab Chrome**
(không có Chrome thì mở trình duyệt mặc định). Đóng tab hoặc bấm **Thoát** trên trang là server tự tắt.

## Luồng dùng

1. **Google Sheet đích** — mặc định *Dùng sheet có sẵn*: dán link đầy đủ hoặc ID (tool tự bóc ID), đặt tên gợi nhớ
   ở ô bên cạnh; danh sách **Đã dùng gần đây** liệt kê các sheet đã kết nối (sửa tên ngay trong ô, bấm *Dùng* để
   kết nối, ✕ để bỏ khỏi danh sách). Hoặc *Tạo mới* với tên `Báo cáo ADS tháng x`. Bấm **Kết nối**.
   - Service account **không tạo được file mới** (Google bỏ dung lượng Drive của service account,
     lỗi `403 storage quota`). Tool sẽ hiện hướng dẫn: **Mở sheets.new** → đặt tên → **Share** cho
     email service account (nút Copy) quyền Editor → dán link → Kết nối.
2. **Import file** — thêm chung mọi file (hoặc kéo thả), tool **tự phân loại theo tên file**:
   - có `_fb_billing` → **Billing** (extension FB Billing Scraper): tab = phần tên trước `_fb_billing`
     (`…_CHI_TIET_…` → `<tên> Chi tiết`); upsert theo `ID giao dịch`; chỉ giữ `Đã thanh toán`; loại dòng khác tháng
     (theo đa số, tắt được); cột tiền ghi thành số; cột ID định dạng TEXT.
   - còn lại → **Báo cáo Ads Manager** (`<Tên-TK>-Nhóm-quảng-cáo-<từ>-<đến>.xlsx`, cấp Nhóm quảng cáo / Chiến dịch /
     Quảng cáo): chỉ giữ dòng `Số tiền đã chi tiêu (VND)` khác 0; tab = **`Camp <tên tài khoản>`** (tên khớp chính tả với
     tab billing `<tên> (<ID>)`, sửa được); mỗi lần import **ghi đè toàn bộ tab**.
   Bấm **Import tất cả** ở thanh dưới: cả hai loại chạy trong một lượt.
3. **Bảng tổng hợp** — chọn tháng, bấm **Tạo / cập nhật Tổng Hợp T{m}**: nhân bản mẫu `Tổng Hợp T6`
   (sheet đích chưa có mẫu thì tự chép từ sheet mẫu trong settings), điền dòng 1.1 Ngân sách được duyệt (tab billing,
   lọc theo tháng) và 1.3 Ngân sách thực tế Camp đã tiêu (tổng `Số tiền đã chi tiêu*` của tab `Camp <tên TK>`).
   Chạy lại chỉ cập nhật hàng 1 + dòng 1.1 + 1.3.

Danh sách sheet đã dùng (`sheets`: id, tên gợi nhớ, tiêu đề, lần dùng cuối), email chia sẻ và sheet mẫu
(`template_sheet_id`) được nhớ ở `%USERPROFILE%\.fb_ads_noApi.json`.

## File

| File | Vai trò |
|---|---|
| `fb_billing_import_web.py` | App chính — server HTTP nội bộ + mở tab Chrome |
| `ui/index.html` | Giao diện HTML/CSS/JS thuần, offline, chọn file bằng nút upload hoặc kéo thả |
| `billing_core.py` | Đọc file, lọc, so cột, upsert, kết nối Google |
| `tong_hop.py` | Tạo tab `Tổng Hợp T{m}` nhân bản từ mẫu `Tổng Hợp T6`, điền dòng 1.1 (lọc theo tháng) và 1.3 (tab Camp). `python tong_hop.py --sheet <ID> --month 8` |
| `fb_billing_import_tk.py` | Bản dự phòng Tkinter (cửa sổ desktop) |
| `service_account.json` | Khóa service account (đã ignore trong git) |
