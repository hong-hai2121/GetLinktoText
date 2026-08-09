# Phần mềm thống kê hóa đơn MISA

Phần mềm này đọc bảng kê chi tiết hóa đơn của MISA, lấy cột `Tên hàng` và cột `Số lượng`, sau đó cộng tổng số lượng theo từng tên hàng và xuất kết quả ra giao diện webview dạng HTML.

## File trong thư mục

- `hoa_don_stats_web.py`: file Python chính, xử lý đọc Excel, tính toán và tạo báo cáo.
- `Chay thong ke hoa don.bat`: file chạy nhanh bằng double-click trên Windows.
- `Tên Sản Phẩm.xlsx`: danh mục thuốc, cột A là tên hàng, cột B..F là các tên khác của cùng thuốc.
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
- Trong khối `File ZIP hóa đơn HTML/XML`, bấm `Chọn ZIP hóa đơn` để chọn một hoặc nhiều file `.zip` hóa đơn.
- Các file ZIP được hiển thị trong một danh sách nguồn hóa đơn ngắn gọn.
- Bấm `Chạy thống kê` để đọc dữ liệu đã chọn.
- Sau khi chạy xong chương trình tự mở báo cáo HTML.
- Có thể bấm `Mở báo cáo HTML` hoặc `Mở CSV bằng Excel` để mở lại kết quả.
- Đóng cửa sổ desktop là chương trình dừng hẳn.

Hoặc chạy bằng PowerShell/CMD:

```powershell
cd /d D:\Python\GetLinktoText\HoaDonMISA\HoaDonDienTuVaMiSa
python hoa_don_stats_web.py
```

Khi bấm `Chạy thống kê`, chương trình sẽ tạo báo cáo HTML và CSV. Báo cáo luôn được lưu vào thư mục `exports` của phần mềm:

```text
D:\Python\GetLinktoText\HoaDonMISA\HoaDonDienTuVaMiSa\exports
```

Cửa sổ desktop vẫn mở để bạn chạy lại file/ZIP khác hoặc mở kết quả.

Trong file `exports/thong_ke_ten_hang.html`, kết quả được tách thành 2 bảng riêng nếu có đủ dữ liệu đầu vào:

- `Bảng kê chi tiết hóa đơn`: thống kê từ file `Bang_ke_chi_tiet_HD` dạng `.csv`, `.xls`, `.xlsx`, `.xlsm`.
- `Hóa đơn HTML/XML/ZIP`: thống kê từ các thư mục hóa đơn và các file ZIP hóa đơn.

File `exports/thong_ke_ten_hang.csv` cũng có cột `Nguồn` để khi mở bằng Excel vẫn biết từng dòng tổng hợp thuộc nhóm dữ liệu nào.

## Logic hoạt động

### 1. Chọn file dữ liệu đầu vào

Nếu chạy bằng file `.bat` hoặc chạy `python hoa_don_stats_web.py` mà không truyền tên file/ZIP, chương trình sẽ mở cửa sổ desktop trước. Báo cáo chưa tạo ngay từ đầu để tránh đọc nhầm file hoặc tạo báo cáo khi chưa chọn dữ liệu.

Trong cửa sổ desktop, bấm `Chọn file Bang_ke_chi_tiet_HD` để chọn một file:

- `.csv`
- `.xls`
- `.xlsx`
- `.xlsm`

Trong khối `File ZIP hóa đơn HTML/XML`, bấm `Chọn ZIP hóa đơn` để chọn một hoặc nhiều file ZIP. Chương trình sẽ tự giải nén mỗi ZIP vào một thư mục con riêng để tránh trùng tên `invoice.xml` và `invoice.html`.

```text
exports\extracted_invoices\20260724_162953
├─ 001_invoice
├─ 002_invoice (1)
├─ 003_invoice (2)
```

Mỗi ZIP sau khi giải nén có thể chứa:

```text
invoice.xml
invoice.html
details.js
sign-check.jpg
```

Chương trình ưu tiên đọc `invoice.xml`. Nếu không có `invoice.xml`, chương trình đọc fallback từ `invoice.html`. Sau khi giải nén, chương trình tự tìm đệ quy các thư mục có `invoice.xml` hoặc `invoice.html`.

Nếu chạy bằng dòng lệnh và truyền sẵn file/folder/ZIP, chương trình sẽ dùng đúng đường dẫn được truyền vào và không mở cửa sổ desktop.

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

Với thư mục hóa đơn HTML/XML, script đọc:

- `invoice.xml` nếu có.
- `invoice.html` nếu không có XML.

Các trường chính lấy từ `invoice.xml`:

```text
Số hóa đơn     -> TTChung/SHDon
Tên hàng       -> DSHHDVu/HHDVu/THHDVu
ĐVT            -> DSHHDVu/HHDVu/DVTinh
Số lượng       -> DSHHDVu/HHDVu/SLuong
Đơn giá        -> DSHHDVu/HHDVu/DGia
Thành tiền     -> DSHHDVu/HHDVu/ThTien
Thuế suất      -> DSHHDVu/HHDVu/TSuat
```

Sau khi đọc các dòng hàng trong các thư mục hóa đơn, chương trình gom nhóm và cộng số lượng theo `Tên hàng` giống file bảng kê chi tiết.

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

Mỗi tên hàng được tách thành **lõi tên** và **quy cách đóng gói**, rồi gom nhóm theo cặp đó.

Khi tính lõi tên, chương trình bỏ đi:

- Khoảng trắng thừa, chữ hoa/thường, dấu tiếng Việt (`sức khoẻ` = `sức khỏe`).
- Tiền tố nhóm hàng: `Thực phẩm bảo vệ sức khỏe`, `Thực phẩm bổ sung`, `TPBVSK`, kèm dấu `:` hoặc `-` đứng sau.
- Số lô và hạn dùng: `(SL: 200326, HD: 210429)`, `(T/242 - H/30)`.
- Dấu câu và ký tự phân cách, nên `T-Gast` = `T GAST` = `T_Gast`.

Khi tính quy cách, chương trình bỏ `x` và dạng bào chế (`viên nén` = `viên`), đồng thời bỏ dung tích
mỗi đơn vị nên `Hộp 20 gói*10ml` = `Hộp 20 gói`. Nhưng nếu dung tích chính là quy cách
(`250ml`) thì vẫn giữ.

Ví dụ các dòng sau được tính là cùng một sản phẩm:

```text
Thực phẩm bảo vệ sức khỏe T-Gast ( Hộp 20 gói*10ml)
Thực phẩm bảo vệ sức khỏe T GAST (Hộp 20 gói*10ml)
Thực phẩm bảo vệ sức khoẻ T-Gast ( Hộp 20 gói * 10 ml )
```

Còn **quy cách khác nhau thì vẫn là hai sản phẩm khác nhau**:

```text
OMEGA 3.6.9 (Hộp 1 lọ x 50 viên)     -> sản phẩm A
OMEGA 3.6.9 (Hộp 1 lọ x 60 viên)     -> sản phẩm B
```

### Tên không ghi quy cách

Tên không ghi quy cách (`Thực phẩm bảo vệ sức khỏe OMEGA 3.6.9`) được xử lý như sau:

- Nếu trong dữ liệu lõi tên đó **chỉ có một quy cách** thì gộp luôn vào quy cách đó.
- Nếu có **từ hai quy cách trở lên** thì để riêng thành một dòng, kèm cảnh báo ⚠ trên báo cáo,
  vì chương trình không thể đoán số lượng đó thuộc quy cách nào.

## Danh mục thuốc (`Tên Sản Phẩm.xlsx`)

Đây là bảng mốc quyết định thuốc nào là thuốc nào. **Mỗi hàng là một thuốc**: cột A là tên hàng
chính, cột B đến F là các tên khác mà hóa đơn hay ghi cho đúng thuốc đó.

| Tên hàng | Tên khác 1 | Tên khác 2 |
|---|---|---|
| `Thực phẩm bảo vệ sức khỏe Dung dịch dạ dày P-Gast (hộp 15 gói)` | `Dạ Dày P_GAST 20 gói` | |
| `MYBUTIN 200` | | |
| `Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói)` | | |

Cách chương trình dò, theo hai tầng:

1. **Khớp cả quy cách** - tên mốc nằm trong tên hóa đơn sau khi chuẩn hóa. Nhờ vậy hai hàng danh
   mục cùng tên nhưng khác quy cách (`OMEGA 3.6.9 (Hộp 1 lọ x 50 viên)` và `(60 viên)`) vẫn tách
   được. Nhiều mốc cùng khớp thì lấy mốc dài nhất.
2. **Khớp lõi tên** - dành cho tên hóa đơn không ghi quy cách. Nếu lõi tên đó thuộc nhiều thuốc
   khác quy cách thì chương trình không đoán bừa, để tên đó thành dòng riêng.

Tên khớp danh mục thì **lấy đúng tên ở cột A làm tên hiển thị**, nên bạn kiểm soát được tên trên
báo cáo. Tên không khớp hàng nào vẫn được gộp bằng thuật toán lõi tên + quy cách như trên, lấy tên
gốc phổ biến nhất làm tên hiển thị, và được đánh dấu là chưa có trong danh mục.

### Tên chưa có trong danh mục

Trên báo cáo, dòng chưa có trong danh mục được **tô nền cam, tên hàng đổi màu**, kèm nhãn
`⚠ chưa có trong danh mục`. Đầu bảng có thông báo đếm số tên và nút **Đi đến** để nhảy thẳng
xuống đúng dòng đó (bấm tiếp sẽ sang dòng chưa có tiếp theo).

Nếu không tìm thấy file danh mục, chương trình vẫn chạy bình thường và không đánh dấu gì cả.

### Màn hình sửa danh mục

Bấm nút **Danh mục thuốc** trong cửa sổ chương trình:

- Bảng bên trái liệt kê từng thuốc kèm các tên khác. Bấm đúp để sửa.
- **Thêm thuốc / Sửa / Xóa** - form sửa có 6 ô: tên hàng và 5 tên khác.
- Danh sách bên phải là các tên trên hóa đơn chưa có trong danh mục, lấy từ lần chạy thống kê gần
  nhất. Chọn một tên rồi bấm **Thành thuốc mới**, hoặc chọn thêm một thuốc ở bảng trái rồi bấm
  **Thành tên khác của thuốc đang chọn**.
- **Lưu vào file** ghi thẳng vào `Tên Sản Phẩm.xlsx`, Excel vẫn mở và sửa tay được. Chạy lại thống
  kê là áp dụng.

## Hàng trả lại và điều chỉnh giảm

MISA ghi dòng trả hàng bằng một câu dài chứ không phải tên hàng gốc:

| Tên hàng | Số lượng |
|---|---:|
| `Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói)` | 4.172 |
| `điều chỉnh giảm Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói) do khách hàng trả lại 1 phần hàng hóa` | -4 |

Chương trình tách phần tên hàng nằm giữa `điều chỉnh giảm` và `do khách ... trả lại`, tìm đúng
sản phẩm rồi cộng số lượng đó vào **cột Hoàn** thay vì tạo một dòng riêng. Các lỗi chính tả có
thật trong dữ liệu (`điêu chỉnh giảm`, `dieu chỉnh giảm`, `diều chỉnh giảm`, `điều chỉnh giả`,
`do khách trả lại hàng`, `do khách hầng trả hàng hóa`) đều nhận diện được.

Dòng trả hàng **luôn được tính là số âm**, kể cả khi MISA ghi số dương. Trong file thử có 10 dòng
như vậy ở hóa đơn `00007133` và `00007134`. Ngoài ra **mọi dòng có số lượng âm cũng là hoàn**, kể
cả khi dòng đó ghi đúng tên hàng.

Bảng kết quả có 3 cột số lượng:

| Cột | Ý nghĩa |
|---|---|
| **Hoàn** | Số lượng khách trả lại, luôn là số âm hoặc 0 |
| **Tổng số lượng** | Tổng bán ra, chưa trừ hoàn (giữ nguyên như báo cáo cũ) |
| **Thực bán** | `Tổng số lượng + Hoàn` |

Ví dụ thật từ file `Bang_ke_chi_tiet_HD_da_su_dung (2).xls`:

```text
Tên hàng                                              Hoàn     Tổng   Thực bán
Thực phẩm bảo vệ sức khỏe PROENTERMAX (Hộp 30 gói)     -23    4.172      4.149
Thực phẩm bảo vệ sức khỏe NEXTHP GREEN                 -11    2.500      2.489
MYBUTIN 200                                             -6    1.512      1.506
CNN AQUACALCI EXTRACT                                   -5      617        612
```

### Dòng điều chỉnh khác

Các dòng điều chỉnh **không phải trả hàng** (`Điều chỉnh bổ sung đơn vị tính " Hộp " cho toàn bộ
hàng hoá tại HĐ số ...`, `Điều chỉnh tên hàng hóa từ X thành Y`) không gắn được vào sản phẩm nào,
nên được dồn hết vào một dòng cuối bảng tên **"Dòng điều chỉnh khác (không phải trả hàng)"**.
Bấm *Chi tiết* để xem từng dòng gốc. Trong file thử có 89 dòng loại này, tất cả đều có số lượng 0.

Chỉ dòng có **số lượng bằng 0** mới được dồn vào đây. Dòng bắt đầu bằng `điều chỉnh` mà có số
lượng thật thì vẫn đứng riêng, để không giấu mất số liệu.

Nhờ hai bước gom này, bảng thống kê giảm từ 107 dòng xuống 22 dòng mà không mất dòng dữ liệu nào:
tổng số dòng và tổng số lượng trước/sau khi gom vẫn khớp tuyệt đối.

## Kết quả xuất ra

Sau khi chạy, chương trình tạo 2 file:

```text
exports/thong_ke_ten_hang.html
exports/thong_ke_ten_hang.csv
```

File HTML hiển thị:

- Tổng số mặt hàng.
- Tổng số lượng, tổng hàng hoàn và tổng thực bán.
- Tổng số dòng hóa đơn.
- Tổng số hóa đơn.
- Khối "Đã gộp N tên trên hóa đơn thành M sản phẩm" kèm cảnh báo ⚠ nếu có tên chưa rõ quy cách.
- Bảng thống kê chi tiết.
- Ô tìm kiếm theo tên hàng.
- Sắp xếp khi bấm vào tiêu đề cột.
- Biểu đồ top mặt hàng có số lượng cao nhất.
- Nút `Mở CSV bằng Excel` để mở file CSV đã xuất ra.
- Nút tải CSV.

### Tên hàng dài

Tên hàng của MISA thường rất dài nên ô tên hàng chỉ hiển thị tối đa **2 dòng**, phần thừa được
cắt bằng dấu `...`. Đưa chuột vào ô sẽ hiện tên đầy đủ, **bấm vào ô là copy** tên đầy đủ vào
clipboard kèm thông báo `Đã copy: ...` ở đáy màn hình. Copy được ở cả bảng chính, bảng đã gộp,
popup Chi tiết và popup So sánh.

Lưu ý: nút `Mở CSV bằng Excel` là link trực tiếp tới file `.csv` trên máy. Nếu Windows hoặc trình duyệt đang gán file CSV mở bằng Excel thì file sẽ mở bằng Excel; nếu không, trình duyệt có thể mở hoặc tải file CSV theo cấu hình hiện tại.

File CSV có các cột:

```text
Nguồn, STT, Tên hàng, Hoàn, Tổng số lượng, Thực bán, Số dòng, Số hóa đơn,
Số tên gốc, Tên gốc đã gộp, Cảnh báo
```

Ba cột cuối để soát lại việc gộp tên: `Tên gốc đã gộp` liệt kê mọi cách viết đã dồn vào dòng đó,
`Cảnh báo` chỉ có nội dung khi chương trình không tự quyết được quy cách.

## Kết quả chạy thử với file hiện tại

Với file:

```text
Bang_ke_chi_tiet_HD_da_su_dung (2).xls
```

Chương trình đã đọc được:

```text
9.272 dòng dữ liệu
22 sản phẩm (gộp từ 107 cách viết tên khác nhau), 20 khớp danh mục thuốc
Tổng bán 14.522 - hoàn 71 = thực bán 14.451
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

## Đóng gói sang máy khác

Mục tiêu đóng gói:

- Tạo file chạy chính: `dist\ThongKeHoaDonMISA.exe`.
- Tạo file cài đặt: `dist\installer\Setup_ThongKeHoaDonMISA.exe`.
- Khi cài đặt, chương trình tạo biểu tượng ngoài Desktop.

Trên máy dùng để build cần có:

- Python 3.
- Inno Setup 6 nếu muốn tạo file cài đặt `.exe`.

Chạy lệnh build:

```powershell
cd /d D:\Python\GetLinktoText\HoaDonMISA\HoaDonDienTuVaMiSa
powershell -ExecutionPolicy Bypass -File .\packaging\build_installer.ps1
```

Nếu chỉ muốn tạo file `.exe` chạy trực tiếp, chưa tạo bộ cài:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_installer.ps1 -SkipInstaller
```

Sau khi build xong, lấy file này đem sang máy khác để cài:

```text
D:\Python\GetLinktoText\HoaDonMISA\HoaDonDienTuVaMiSa\dist\installer\Setup_ThongKeHoaDonMISA.exe
```

Khi chạy file cài đặt, app được cài vào thư mục người dùng:

```text
%LOCALAPPDATA%\HoaDonDienTuVaMiSa
```

Chọn tùy chọn `Tao bieu tuong ngoai Desktop` để tạo biểu tượng ngoài màn hình Desktop.

Chạy thống kê một thư mục hóa đơn:

```powershell
python hoa_don_stats_web.py --no-dialog --invoice-folder "D:\Python\GetLinktoText\HoaDonMISA\HoaDonDienTuVaMiSa\invoice"
```

Chạy thống kê một file ZIP hóa đơn:

```powershell
python hoa_don_stats_web.py --no-dialog --invoice-zip "C:\Users\PC\Downloads\invoice.zip"
```

Có thể truyền nhiều ZIP bằng cách lặp lại `--invoice-zip`.

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
