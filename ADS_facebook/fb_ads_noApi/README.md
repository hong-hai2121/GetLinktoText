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
     tab billing `<tên> (<ID>)`, sửa được; tên file bị mất dấu tiếng Việt kiểu `H_ng-H_i-01-…-Nh_m-qu_ng-c_o-…` vẫn
     khớp theo phần chữ ASCII còn lại nếu chỉ một tab khớp); mỗi lần import **ghi đè toàn bộ tab**.
   Bấm **Import tất cả** ở thanh dưới: cả hai loại chạy trong một lượt.
3. **Bảng tổng hợp** — chọn tháng, bấm **Tạo / cập nhật Tổng Hợp T{m}**: nhân bản mẫu `Tổng Hợp T6`
   (sheet đích chưa có mẫu thì tự chép từ sheet mẫu trong settings), điền dòng 1.1 Ngân sách được duyệt (tab billing,
   lọc theo tháng) và 1.3 Ngân sách thực tế Camp đã tiêu (tổng `Số tiền đã chi tiêu*` của tab `Camp <tên TK>`,
   chỉ các dòng hợp lệ: cột tên (`Tên nhóm quảng cáo`, báo cáo cấp Chiến dịch thì `Tên chiến dịch`) khác rỗng **và**
   cột ngân sách (`Ngân sách nhóm quảng cáo` / `Ngân sách chiến dịch`) khác 0 — chữ “Sử dụng ngân sách …” vẫn tính;
   dòng tổng của Ads Manager không được cộng).
   Dòng phụ (điền khi cột A có nhãn): Lệch = 1.1 + 1.2 − 1.3; CP Tổng = 1.1 + 1.2; Đơn = tổng `Lượt mua`;
   Doanh Số = tổng `Giá trị chuyển đổi lượt mua` (cùng quy tắc nhóm hợp lệ; tab Camp chưa có cột này → 0, cần
   thêm cột khi xuất báo cáo Ads Manager); Tỷ lệ CP = CP Tổng / Doanh Số (Doanh Số = 0 → ô trống).
   Dòng **ID tài khoản**: hàng tiêu đề `1. NGÂN SÁCH - TẠM ỨNG` của mẫu được đổi nhãn thành `ID tài khoản` và điền
   ID từng tài khoản tra ở tab **`Danh Sách`** (cột `Tên tài khoản quảng cáo` → `ID tài khoản`, tiêu đề có thể ở hàng 2)
   theo tên TK ở hàng 1; sheet không có tab này hoặc không thấy tên → lấy ID trong ngoặc ở tên tab.
   Chạy lại chỉ cập nhật hàng 1 + các dòng công thức trên.

Danh sách sheet đã dùng (`sheets`: id, tên gợi nhớ, tiêu đề, lần dùng cuối), email chia sẻ và sheet mẫu
(`template_sheet_id`) được nhớ ở `%USERPROFILE%\.fb_ads_noApi.json`.

## File

| File | Vai trò |
|---|---|
| `fb_billing_import_web.py` | App chính — server HTTP nội bộ + mở tab Chrome |
| `ui/index.html` | Giao diện HTML/CSS/JS thuần, offline, chọn file bằng nút upload hoặc kéo thả |
| `billing_core.py` | Đọc file, lọc, so cột, upsert, kết nối Google |
| `tong_hop.py` | Tạo tab `Tổng Hợp T{m}` nhân bản từ mẫu `Tổng Hợp T6`, điền dòng 1.1 (lọc theo tháng), 1.3 (tab Camp), dòng ID tài khoản (tra tab `Danh Sách`) và dòng phụ Lệch / CP Tổng / Đơn / Doanh Số / Tỷ lệ CP. `python tong_hop.py --sheet <ID> --month 8` |
| `fb_billing_import_tk.py` | Bản dự phòng Tkinter (cửa sổ desktop) |
| `service_account.json` | Khóa service account (đã ignore trong git) |
