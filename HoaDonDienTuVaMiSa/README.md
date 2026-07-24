# Phần mềm thống kê hóa đơn MISA

Phần mềm này đọc bảng kê chi tiết hóa đơn của MISA, lấy cột `Tên hàng` và cột `Số lượng`, sau đó cộng tổng số lượng theo từng tên hàng và xuất kết quả ra giao diện webview dạng HTML.

## File trong thư mục

- `hoa_don_stats_web.py`: file Python chính, xử lý đọc Excel, tính toán và tạo báo cáo.
- `Chay thong ke hoa don.bat`: file chạy nhanh bằng double-click trên Windows.
- `exports/thong_ke_ten_hang.html`: báo cáo webview được tạo sau khi chạy.
- `exports/thong_ke_ten_hang.csv`: file CSV kết quả, có thể mở bằng Excel.

## Cách chạy

Double-click file:

```bat
Chay thong ke hoa don.bat
```

Sau khi double-click, chương trình sẽ mở một cửa sổ desktop. Trong cửa sổ này:

- Bấm `Chọn file Bang_ke_chi_tiet_HD` để chọn file dữ liệu hóa đơn MISA.
- Hỗ trợ chọn file `.csv`, `.xls`, `.xlsx`, `.xlsm`.
- Bấm `Chạy thống kê` để đọc file đã chọn.
- Sau khi chạy xong chương trình tự mở báo cáo HTML.
- Có thể bấm `Mở báo cáo HTML` hoặc `Mở CSV bằng Excel` để mở lại kết quả.
- Đóng cửa sổ desktop là chương trình dừng hẳn.

Hoặc chạy bằng PowerShell/CMD:

```powershell
cd /d D:\Python\GetLinktoText\HoaDonDienTuVaMiSa
python hoa_don_stats_web.py
```

Khi bấm `Chạy thống kê`, chương trình sẽ tạo báo cáo HTML và CSV. Báo cáo được lưu vào thư mục `exports` cạnh file đầu tiên đã chọn. Cửa sổ desktop vẫn mở để bạn chạy lại file khác hoặc mở kết quả.

## Logic hoạt động

### 1. Chọn file dữ liệu đầu vào

Nếu chạy bằng file `.bat` hoặc chạy `python hoa_don_stats_web.py` mà không truyền tên file/folder, chương trình sẽ mở cửa sổ desktop trước. Báo cáo chưa tạo ngay từ đầu để tránh đọc nhầm file hoặc tạo báo cáo khi chưa chọn dữ liệu.

Trong cửa sổ desktop, bấm `Chọn file Bang_ke_chi_tiet_HD` để chọn một file:

- `.csv`
- `.xls`
- `.xlsx`
- `.xlsm`

Nếu chạy bằng dòng lệnh và truyền sẵn file/folder, chương trình sẽ dùng đúng đường dẫn được truyền vào và không mở cửa sổ desktop.

File mẫu hiện tại là:

```text
Bang_ke_chi_tiet_HD_da_su_dung (2).xls
```

Lưu ý: file này mang đuôi `.xls`, nhưng bên trong thực tế là định dạng `.xlsx` dạng ZIP/XML. Vì vậy script đọc trực tiếp cấu trúc XML của Excel, không cần cài thêm `openpyxl` hoặc `xlrd`.

### 2. Đọc danh sách sheet trong Excel

Với file Excel, script mở file và đọc:

- `xl/workbook.xml` để biết danh sách sheet.
- `xl/_rels/workbook.xml.rels` để biết file XML tương ứng của từng sheet.
- `xl/sharedStrings.xml` để đọc các chuỗi tiếng Việt trong Excel.

Sau đó script duyệt từng sheet để tìm sheet có dòng tiêu đề phù hợp.

Với file CSV, script đọc trực tiếp nội dung CSV, tự nhận diện dấu phân cách thường gặp như dấu phẩy, chấm phẩy hoặc tab, rồi tìm dòng tiêu đề giống cách đọc Excel.

### 3. Tự tìm dòng tiêu đề

Script không cố định dòng tiêu đề là dòng nào. Nó quét từng dòng để tìm đủ 2 cột:

- `Tên hàng`
- `Số lượng`

Trước khi so sánh, tiêu đề được chuẩn hóa:

- Chuyển về chữ thường.
- Bỏ dấu tiếng Việt.
- Gom nhiều khoảng trắng thành một khoảng trắng.
- Đổi `đ` thành `d`.

Ví dụ:

```text
Tên hàng   -> ten hang
Số lượng   -> so luong
```

Trong file mẫu hiện tại:

- Dòng tiêu đề là dòng `6`.
- `Tên hàng` nằm ở cột `AB`.
- `Số lượng` nằm ở cột `AE`.

Tuy nhiên script vẫn tự dò theo tên cột, nên nếu sau này MISA đổi vị trí cột nhưng vẫn giữ tên tiêu đề thì chương trình vẫn đọc được.

### 4. Đọc từng dòng dữ liệu

Sau khi tìm được dòng tiêu đề, script đọc tất cả các dòng bên dưới.

Mỗi dòng được lấy các thông tin chính:

- `Tên hàng`
- `Số lượng`
- `ĐVT`
- `Số hóa đơn`

Trong đó:

- Dòng trống sẽ bị bỏ qua.
- Dòng không có `Tên hàng` sẽ bị bỏ qua.
- Nếu `Số lượng` trống hoặc không đọc được thì tính là `0`.

### 5. Cách parse số lượng

Hàm `parse_decimal()` chuyển giá trị ở cột `Số lượng` thành số dạng `Decimal` để cộng chính xác hơn số float.

Script xử lý được các kiểu số thường gặp:

```text
1
10
1.000
1,000
1.5
1,5
```

Nếu vừa có dấu `.` vừa có dấu `,`, script tự đoán dấu nào là dấu thập phân dựa theo vị trí xuất hiện cuối cùng.

Ví dụ:

```text
1.234,5 -> 1234.5
1,234.5 -> 1234.5
```

## Cách tính toán

Mục tiêu chính là cộng tổng `Số lượng` theo từng `Tên hàng`.

Công thức logic:

```text
Tổng số lượng của một tên hàng
= tổng tất cả giá trị ở cột Số lượng của các dòng có cùng Tên hàng
```

Ví dụ dữ liệu đầu vào:

| Tên hàng | Số lượng |
|---|---:|
| Sản phẩm A | 1 |
| Sản phẩm B | 2 |
| Sản phẩm A | 3 |

Kết quả:

| Tên hàng | Tổng số lượng |
|---|---:|
| Sản phẩm A | 4 |
| Sản phẩm B | 2 |

Trong code, phần cộng nằm ở hàm `aggregate_lines()`:

```python
stat.total_quantity += line.quantity
stat.line_count += 1
```

Ngoài tổng số lượng, chương trình còn tính thêm:

- `Số dòng`: số dòng hóa đơn có chứa tên hàng đó.
- `Số hóa đơn`: số hóa đơn khác nhau có chứa tên hàng đó.
- `ĐVT`: đơn vị tính xuất hiện nhiều nhất của tên hàng đó.

## Cách gom nhóm tên hàng

Tên hàng được gom nhóm theo nội dung sau khi đã:

- Cắt khoảng trắng đầu/cuối.
- Gom nhiều khoảng trắng liên tiếp thành một khoảng trắng.
- Không phân biệt chữ hoa/chữ thường.

Ví dụ các dòng sau được tính là cùng một tên hàng:

```text
Sản phẩm A
sản phẩm a
  Sản   phẩm   A
```

Nhưng nếu tên hàng khác dấu câu, khác ký tự hoặc khác nội dung thì vẫn được tính là mặt hàng khác.

## Lưu ý về hàng trả lại và điều chỉnh giảm

Hiện tại chương trình cộng trực tiếp giá trị ở cột `Số lượng`.

Nếu một dòng có `Số lượng` âm, ví dụ:

```text
-1
-4
```

thì giá trị âm đó sẽ được trừ vào tổng của nhóm `Tên hàng` tương ứng.

Ví dụ nếu cùng một tên hàng có dữ liệu:

| Tên hàng | Số lượng |
|---|---:|
| Sản phẩm A | 10 |
| Sản phẩm A | -2 |

thì kết quả sẽ là:

```text
Sản phẩm A = 8
```

Tuy nhiên có một trường hợp cần xử lý sau: MISA có thể ghi dòng trả hàng bằng một tên hàng khác với tên hàng gốc, ví dụ:

| Tên hàng | Số lượng |
|---|---:|
| Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói) | 4.172 |
| điều chỉnh giảm Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói) do khách hàng trả lại 1 phần hàng hóa | -4 |

Với logic hiện tại, 2 dòng trên bị xem là 2 tên hàng khác nhau vì nội dung `Tên hàng` không giống nhau hoàn toàn.

Kết quả hiện tại sẽ là:

```text
Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói) = 4.172
điều chỉnh giảm Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói) do khách hàng trả lại 1 phần hàng hóa = -4
```

Chương trình hiện **chưa tự tách tên hàng gốc** trong câu `điều chỉnh giảm ... do khách hàng trả lại ...`, nên chưa tự trừ `-4` vào dòng PROENTERMAX gốc.

Phương án xử lý sau:

- Nhận diện các dòng có dạng `điều chỉnh giảm ... do khách hàng trả lại ...`.
- Tách phần tên hàng gốc nằm giữa `điều chỉnh giảm` và `do khách hàng trả lại`.
- Gom số lượng âm đó vào đúng tên hàng gốc.
- Bổ sung các cột rõ hơn:

```text
Tên hàng | ĐVT | Số lượng bán | Số lượng trả/điều chỉnh giảm | Số lượng ròng
```

Ví dụ mong muốn sau khi xử lý:

```text
Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói)
Số lượng bán: 4.172
Số lượng trả/điều chỉnh giảm: 4
Số lượng ròng: 4.168
```

## Kết quả xuất ra

Sau khi chạy, chương trình tạo 2 file:

```text
exports/thong_ke_ten_hang.html
exports/thong_ke_ten_hang.csv
```

File HTML hiển thị:

- Tổng số mặt hàng.
- Tổng số lượng.
- Tổng số dòng hóa đơn.
- Tổng số hóa đơn.
- Bảng thống kê chi tiết.
- Ô tìm kiếm theo tên hàng.
- Sắp xếp khi bấm vào tiêu đề cột.
- Biểu đồ top mặt hàng có số lượng cao nhất.
- Nút `Mở CSV bằng Excel` để mở file CSV đã xuất ra.
- Nút tải CSV.

Lưu ý: nút `Mở CSV bằng Excel` là link trực tiếp tới file `.csv` trên máy. Nếu Windows hoặc trình duyệt đang gán file CSV mở bằng Excel thì file sẽ mở bằng Excel; nếu không, trình duyệt có thể mở hoặc tải file CSV theo cấu hình hiện tại.

File CSV có các cột:

```text
STT, Tên hàng, ĐVT, Tổng số lượng, Số dòng, Số hóa đơn
```

## Kết quả chạy thử với file hiện tại

Với file:

```text
Bang_ke_chi_tiet_HD_da_su_dung (2).xls
```

Chương trình đã đọc được:

```text
9.272 dòng dữ liệu
125 tên hàng
```

## Tùy chọn dòng lệnh

Chạy một file cụ thể:

```powershell
python hoa_don_stats_web.py "Bang_ke_chi_tiet_HD_da_su_dung (2).xls"
```

Chỉ xuất file, không tự mở trình duyệt:

```powershell
python hoa_don_stats_web.py --no-open
```

Không mở cửa sổ desktop, dùng các file trong thư mục chứa script như cách cũ:

```powershell
python hoa_don_stats_web.py --no-dialog
```

Chạy thống kê một file cụ thể:

```powershell
python hoa_don_stats_web.py "D:\DuLieuHoaDon\Bang_ke_chi_tiet_HD_da_su_dung.xlsx"
```

Chỉ đọc một sheet cụ thể:

```powershell
python hoa_don_stats_web.py --sheet "Bảng kê chi tiết HĐ đã sử dụng"
```

Đổi đường dẫn file HTML/CSV kết quả:

```powershell
python hoa_don_stats_web.py --out exports/bao_cao.html --csv exports/bao_cao.csv
```

## Ghi chú kỹ thuật

Script hiện đọc được file `.csv`, file Excel dạng `.xlsx/.xlsm`, hoặc file `.xls` nhưng thực chất là `.xlsx` như file MISA mẫu. Nếu gặp file `.xls` đời cũ dạng nhị phân thật, cần mở file bằng Excel rồi lưu lại thành `.xlsx` trước khi chạy.
