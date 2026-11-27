# HƯỚNG DẪN CÀI ĐẶT VÀ SỬ DỤNG
## Mindcare — chuyển đơn hàng Pancake sang hóa đơn meInvoice

---

## YÊU CẦU HỆ THỐNG

- Windows 10 / 11
- Python 3.10 trở lên → Tải tại: https://www.python.org/downloads/
  - Khi cài Python: **tích vào ô "Add Python to PATH"**

---

## CẤU TRÚC THƯ MỤC

```
Mindcare\
├── mindcare_convert.py   ← Script chính
├── requirements.txt                   ← Danh sách thư viện cần cài
├── run.bat                            ← File chạy 1 click
├── HUONG_DAN_CAI_DAT.md              ← File này
├── pancake.xlsx                       ← File dữ liệu Pancake (bạn đặt vào)
├── mẫu xuất hoá đơn.xlsx             ← File mẫu meInvoice (bạn đặt vào)
└── external_amounts.xlsx              ← (Tùy chọn) File bổ sung số tiền
```

---

## BƯỚC 1 — CHUẨN BỊ FILE DỮ LIỆU

Đặt 2 file sau vào cùng thư mục với `run.bat`:

| File | Mô tả |
|---|---|
| `pancake.xlsx` | Export từ Pancake — chứa danh sách đơn hàng |
| `mẫu xuất hoá đơn.xlsx` | Tải từ meInvoice.vn — file template nhập hóa đơn |

> **Lưu ý:** Tên file phải khớp chính xác (kể cả dấu tiếng Việt).  
> Nếu tên file khác, mở `mindcare_convert.py` và sửa phần `CONFIG` ở đầu file.

---

## BƯỚC 2 — CÀI ĐẶT (chỉ làm 1 lần)

### Cách 1: Dùng file cài đặt tự động (dễ nhất)

1. Mở **Command Prompt** hoặc **PowerShell** trong thư mục này
   - Cách mở: Giữ **Shift + chuột phải** vào thư mục → chọn **"Open PowerShell window here"**
2. Chạy lần lượt 2 lệnh sau:

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

3. Chờ cài xong (khoảng 1-2 phút, cần có Internet)

### Cách 2: Nếu đã có file `venv\` sẵn (được gửi kèm)

Bỏ qua Bước 2, chạy thẳng Bước 3.

---

## BƯỚC 3 — CHẠY CHƯƠNG TRÌNH

### Cách 1: Double-click (đơn giản nhất)

Double-click vào file **`run.bat`**

### Cách 2: Chạy bằng dòng lệnh

```
venv\Scripts\python.exe mindcare_convert.py
```

---

## BƯỚC 4 — KIỂM TRA KẾT QUẢ

Sau khi chạy xong, mở file **`meinvoice_output.xlsx`**:

- **Sheet `meInvoice`** → Dữ liệu hóa đơn đã điền vào mẫu
- **Sheet `CHECK_LOG`** → Báo cáo kiểm tra:
  - Tổng số đơn đọc được / hợp lệ / bị bỏ qua
  - Danh sách đơn thiếu SĐT, địa chỉ, tên sản phẩm, số tiền
  - Danh sách đơn bị bỏ qua và lý do

Kiểm tra kỹ `CHECK_LOG` trước khi import lên meInvoice.vn.

---

## CẤU HÌNH NÂNG CAO

Mở file `mindcare_convert.py` bằng Notepad hoặc VS Code, tìm phần `CONFIG` ở đầu file:

```python
CONFIG = {
    "PANCAKE_FILE":    "pancake.xlsx",          # Tên file Pancake
    "TEMPLATE_FILE":  "mẫu xuất hoá đơn.xlsx", # Tên file mẫu
    "OUTPUT_FILE":    "meinvoice_output.xlsx",   # Tên file kết quả
    "PANCAKE_SHEET":   "",       # Để trống = tự tìm sheet, hoặc điền tên sheet
    "START_ROW":       3,        # Dòng bắt đầu ghi dữ liệu trong mẫu
    "DEFAULT_TAX_RATE": 8,       # Thuế suất GTGT: 8 hoặc 10
    "DEFAULT_PAYMENT_METHOD": "TM/CK",   # Hình thức thanh toán
    "INCLUDE_SHIPPING_FEE": False,        # True = thêm dòng phí ship
    ...
}
```

---

## XỬ LÝ LỖI THƯỜNG GẶP

### Lỗi: `No module named 'openpyxl'` hoặc `No module named 'pandas'`
→ Chưa cài thư viện. Chạy lại Bước 2.

### Lỗi: `Không tìm thấy file: pancake.xlsx`
→ File chưa được đặt vào đúng thư mục. Đặt file cùng chỗ với `run.bat`.

### Lỗi: Cột bị ánh xạ sai / thiếu dữ liệu
→ Chạy script lần đầu, đọc log in ra:
```
Danh sách cột: ['Mã ĐH', 'Tên KH', 'SĐT', ...]
✗ ten_khach_hang → KHÔNG TÌM THẤY
```
→ Mở file script, tìm `PANCAKE_COLUMN_MAP`, thêm tên cột thực tế vào danh sách tương ứng.

### Lỗi: Tất cả đơn bị bỏ qua
→ Cột trạng thái không khớp từ khóa. Mở script, tìm `VALID_STATUS_KEYWORDS` và thêm giá trị trạng thái thực tế trong file Pancake của bạn. Hoặc đặt:
```python
"EXPORT_ALL_IF_NO_STATUS": True,
```

### Không in được tiếng Việt trong cửa sổ lệnh
→ Bình thường, không ảnh hưởng đến kết quả. File output vẫn đúng tiếng Việt.

---

## GỬI SANG MÁY KHÁC

1. Copy toàn bộ thư mục `Mindcare\` (không cần copy thư mục `venv\`)
2. Máy nhận cài Python 3.10+ (tích "Add to PATH")
3. Mở PowerShell trong thư mục, chạy:
```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```
4. Double-click `run.bat` là dùng được.

---

*Nếu gặp vấn đề, xem file `convert_log.txt` được tạo ra sau mỗi lần chạy để biết chi tiết lỗi.*
