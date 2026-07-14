# Trình xem chỉ số quảng cáo Facebook (offline)

Xem file `.xlsx` chỉ số chiến dịch tải từ **Trình quản lý quảng cáo Facebook** bằng
một web giao diện giống Ads Manager cho dễ đọc. Chạy hoàn toàn trong máy, **không tải gì lên mạng**.

## Cách dùng (khuyên dùng): mở web trước → thêm file sau
1. Nhấp đúp **`Xem bao cao.bat`** (hoặc chạy `python xem_ads.py`) → **giao diện web mở ngay** (chưa cần chọn file).
2. Trong web bấm **“Thêm file .xlsx”** hoặc **kéo–thả** file vào trang.
3. **Chọn được nhiều file cùng lúc** — mỗi file là một **tài khoản**; các file được **gộp chung** một bảng, thêm cột **“Tài khoản / Nguồn”** để biết dòng thuộc tài khoản nào. Thêm/bớt file bất cứ lúc nào qua thanh chip ở đầu trang (nút ✕ để bỏ một file, “Xóa hết” để làm lại).

Cách khác (nạp sẵn 1 file rồi vẫn thêm được file khác trong web):
- Kéo & thả file `.xlsx` **thả lên `xem_ads.py`**.
- Dòng lệnh: `python xem_ads.py "duong_dan_file.xlsx"`.

> Có thể **bôi đen & copy** trực tiếp mọi text trong bảng/bảng phân tích (bấm nhanh 1 dòng mới mở phân tích; đang bôi đen thì không mở).

## Cột cần lấy để phân tích & kiểm soát ads đầy đủ

Bộ cột hiện tại chỉ đủ **xem tổng quan cấp chiến dịch**. Để tối ưu được (bật/tắt đúng chỗ,
phát hiện ad cháy tệp, biết tiền rơi ở khâu nào), lần sau xuất từ Ads Manager nên tick thêm:

### 🔴 Thiếu — thêm NGAY (ưu tiên cao)
| Cột | Vì sao cần |
|-----|-----------|
| **Tên nhóm quảng cáo**, **Tên quảng cáo** (+ ID chiến dịch/nhóm QC/QC) | Soi & tắt/bật đúng adset/ad kém — hiện chỉ có cấp chiến dịch |
| **Mục tiêu** (Objective) | Biết KPI đúng của từng camp (nhắn tin vs mua vs tương tác) |
| **Số lần nhấp vào liên kết** | Đo lượng click thật vào link |
| **CPC (chi phí mỗi lần nhấp vào liên kết)** | Giá mỗi click — đắt/rẻ |
| **CTR (tỷ lệ nhấp vào liên kết)** | CTR "Tất cả" tính cả nhấp linh tinh; CTR liên kết mới phản ánh ad có hút không |
| **Tần suất (Frequency)** | Phát hiện "cháy tệp"/nhàm ad (nguyên nhân phổ biến làm CPM tăng, kết quả tụt) |
| **Số lượt mua** | Số đơn thực (hiện chỉ có ROAS & giá trị) |
| **Chi phí mỗi lượt mua** | Giá mỗi đơn |

### 🟠 Nên có — chẩn đoán chất lượng & phễu
| Cột | Vì sao cần |
|-----|-----------|
| **Xếp hạng chất lượng** | Ad yếu vì nội dung? |
| **Xếp hạng tỷ lệ tương tác** | Ad yếu vì kém hấp dẫn? |
| **Xếp hạng tỷ lệ chuyển đổi** | Ad yếu vì tệp/landing? |
| **Lượt xem trang đích** (Landing page views) | Bước đầu phễu |
| **Lượt thêm vào giỏ hàng** | Giữa phễu |
| **Lượt bắt đầu thanh toán** | Cuối phễu — biết rơi ở khâu nào |

### 💬 Nếu chạy camp NHẮN TIN
| Cột | Vì sao cần |
|-----|-----------|
| **Số cuộc trò chuyện qua tin nhắn bắt đầu** | Số lượng (hiện chỉ có chi phí mỗi liên hệ) |
| **Tin nhắn mới** / **Số liên hệ nhắn tin** | Đo lượng khách nhắn thực |

### 🎬 Nếu chạy VIDEO / REEL
| Cột | Vì sao cần |
|-----|-----------|
| **ThruPlay** | Số lượt xem có ý nghĩa |
| **Lượt phát video 3 giây** | Sức hút 3s đầu |
| **Thời gian xem video trung bình** | Giữ chân người xem |
| **% xem 25/50/75/100%** | Đoạn nào bị bỏ |

### 🟡 Tối ưu nâng cao (tùy nhu cầu)
- **Xuất theo Ngày/Tuần** (Phân tích theo thời gian) thay vì gộp cả kỳ → xem xu hướng.
- **Breakdown**: Tuổi–giới tính, Vị trí hiển thị (placement), Khu vực, Thiết bị → cắt tệp/vị trí đốt tiền.
- **Ngân sách chiến dịch** (nếu dùng CBO) + **Chiến lược giá thầu**.

### 🧾 Cột đang có sẵn (23 cột — giữ lại)
Ngày báo cáo · Tên chiến dịch · Trạng thái phân phối · Kết quả & Chỉ báo kết quả · Chi phí mỗi kết quả ·
Ngân sách & Loại ngân sách nhóm QC · Số tiền đã chi tiêu · Lượt hiển thị · Người tiếp cận ·
Cài đặt ghi nhận · CPM · ROAS lượt mua · Giá trị chuyển đổi · CTR (Tất cả) · ROAS kết quả ·
Đơn đặt hàng đã tạo · Chi phí mỗi liên hệ nhắn tin.

> ⚠️ **Lưu ý dữ liệu hiện tại:** cột *"Ngân sách nhóm QC"* đang chứa chữ còn *"Loại ngân sách"* = 0
> (có vẻ lệch cột khi xuất); cột cuối *"(VND)"* không có tên. Xuất lại nên chọn đúng cột và đặt tên rõ.

### 💡 Mẹo lấy đủ lần sau
Ads Manager → **Cột ▸ Tùy chỉnh cột** → tick thêm các mục trên → **Lưu làm mẫu (preset)** để lần sau
xuất là có sẵn. Nên xuất **3 mức**: Chiến dịch → Nhóm QC → Quảng cáo, và bật **Phân tích theo thời gian: Ngày**.
Viewer **tự nhận cột theo tên header**, nên thêm bao nhiêu cột cũng hiển thị được ngay, không cần sửa code.

## Tính năng
- **Bảng phân tích chi tiết cho từng dòng** — bấm vào một chiến dịch/nhóm quảng cáo để mở panel phân tích theo 6 tầng:
  1. **Nhận diện & cấu hình** (mục tiêu qua *Chỉ báo kết quả*, phân phối, ngân sách, giá thầu, lần chỉnh sửa gần nhất, attribution).
  2. **Tiền & kết quả cuối** (chi tiêu, kết quả & CP/kết quả, đơn, CPA, ROAS).
  3. **Tầng tiếp cận** (hiển thị, tiếp cận, tần suất, CPM).
  4. **Tầng click** (số click, CTR/CPC liên kết & tất cả).
  5. **Tầng nhắn tin** (liên hệ mới/tổng, CP/tin nhắn mới & tỷ lệ chốt tự tính) — chỉ hiện khi có dữ liệu.
  6. **Tầng video** (phát ≥3 giây, ThruPlay, hook 3 giây) — chỉ hiện khi nhóm chạy video.
  Kèm dải **6 con số quyết định** và **nhận định tự động** (cờ đỏ/vàng/xanh): thiếu *Chỉ báo kết quả* = lệch cấu hình; tần suất >3 = cháy tệp; CPM vọt cao so với median; CTR liên kết thấp = nghẽn chất liệu; ROAS <1 = lỗ; vừa chỉnh sửa = đang học máy.
- Giao diện giống Ads Manager: cột **Chiến dịch/Nhóm QC** ghim trái, công tắc bật/tắt, chấm trạng thái phân phối.
- **Tìm kiếm** theo tên chiến dịch; **lọc** Tất cả / Đang chạy / Đã tắt.
- **Sắp xếp** bằng cách bấm tiêu đề cột (mặc định theo chi tiêu giảm dần).
- **Ẩn/hiện cột** qua nút “Cột”.
- Định dạng **VND (₫)**, số nghìn, phần trăm; hàng **Tổng cộng** tự tính CPM / chi phí mỗi kết quả / ROAS / CTR (CTR bình quân theo lượt hiển thị).
- Thẻ tổng quan: số chiến dịch, đã chi tiêu, hiển thị, tiếp cận, kết quả.
- Tự dò dòng tiêu đề & kiểu cột → dùng được cho các bản xuất Ads Manager khác.

## File trong thư mục
| File | Vai trò |
|------|---------|
| `xem_ads.py` | **Chạy file này** — chọn Excel, sinh `report.html`, tự mở trình duyệt |
| `Xem bao cao.bat` | Nhấp đúp để chạy `xem_ads.py` trên Windows |
| `index.html` | Giao diện + xử lý (mở trực tiếp cũng dùng được, hỗ trợ kéo–thả) |
| `xlsx.full.min.js` | Thư viện đọc Excel (đi kèm để chạy offline) |
| `report.html` | File kết quả sinh ra sau khi chạy (mở cái này để xem lại) |

> Yêu cầu: Python 3 + thư viện `openpyxl` (đọc `.xlsx`). Cài nếu thiếu: `pip install openpyxl`.
