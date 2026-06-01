# FB Ads Accounts — Tổng quan các file Python

Thư mục này chứa pipeline thu thập dữ liệu **Facebook Ads → Google Sheets**, gồm 6 file Python và 1 file cấu hình, hoạt động theo 3 giai đoạn.

---

## Luồng hoạt động tổng quát

```
hub.py  (TRUNG TÂM ĐIỀU KHIỂN — 1 giao diện gộp mọi chức năng)
    │
    ├─► main.py          → lấy danh sách tài khoản quảng cáo (TKQC API sheet)
    │
    ├─► get_campaigns.py → Phase 1: lấy Campaign + metrics (tab từng tài khoản)
    │
    ├─► get_details.py   → Phase 2: lấy Adset / Ad / Creative (chèn vào cùng tab)
    │                                    └─► tab "{TK} - Creative"
    │
    ├─► fb_billing_import.py → nhập lịch sử thanh toán CSV/XLS
    ├─► TongHop.py           → tạo sheet "Tổng Hợp T{tháng}"
    ├─► check_spend.py       → kiểm tra Spend Campaign = Σ Adset = Σ Ad
    └─► check_billing_vs_campaigns.py → đối chiếu billing với chiến dịch

config.py               (biến cấu hình: access token, khoảng thời gian)
launcher.py             (GUI cũ — chỉ điều phối Phase 1 & 2; hub.py thay thế)
```

> **`hub.py` là entry point chính.** Chạy `python hub.py` để mở 1 cửa sổ duy nhất
> có sidebar điều hướng tất cả công cụ, thanh chọn khoảng thời gian dùng chung
> (Phase 1 & 2), và 1 console hiển thị kết quả. Các công cụ cần thao tác chọn
> (tài khoản / tab / file) sẽ mở cửa sổ chuyên dụng sẵn có của chúng; công cụ
> còn lại (cập nhật TKQC, check spend, check billing) chạy thẳng và in vào console.

---

## Chi tiết từng file

### `config.py` — Cấu hình chung

Lưu hai biến mà tất cả các script đọc:

| Biến | Mô tả |
|------|-------|
| `ACCESS_TOKEN` | Facebook Graph API access token |
| `DATE_PRESET` | Preset thời gian mặc định (`"this_month"`) |
| `TIME_RANGE` | Dict `{since, until}` khi dùng ngày tuỳ chỉnh |

`launcher.py` ghi đè `DATE_PRESET` / `TIME_RANGE` vào file này trước mỗi lần chạy để truyền khoảng thời gian mà người dùng chọn trên GUI xuống các script con.

---

### `main.py` — Đồng bộ danh sách tài khoản quảng cáo

**Chức năng:** Gọi Facebook Graph API lấy toàn bộ ad account mà token hiện tại có quyền truy cập, sau đó ghi vào sheet **TKQC API**.

**Các bước chính:**
1. Kết nối Google Sheets bằng `service_account.json`.
2. Đọc và giữ nguyên cột **"Chọn Lấy Camp"** (các lựa chọn cũ không bị mất).
3. Gọi `GET /me/adaccounts` với các trường: `id, name, account_status, currency, timezone_name, amount_spent, balance, business`.
4. Sắp xếp theo Business → Tên tài khoản.
5. Ghi lại sheet (11 cột) và lưu bản sao `ad_accounts.json`.

**Output — sheet "TKQC API" (11 cột):**

| Cột | Nội dung |
|-----|----------|
| ID Tài Khoản | act_XXXXXXX |
| Tên Tài Khoản | Tên hiển thị |
| ID / Tên Business | Business quản lý tài khoản |
| Trạng Thái | Đang hoạt động / Đã tắt / … |
| Tiền Tệ | VND / USD / … |
| Múi Giờ | Asia/Ho_Chi_Minh / … |
| Đã Chi | Tổng chi từ trước đến nay |
| Số Dư | Số dư còn lại |
| **Chọn Lấy Camp** | ✍ Người dùng đánh TRUE để Phase 1 xử lý |
| Cập Nhật Lúc | Timestamp lần ghi gần nhất |

---

### `get_campaigns.py` — Phase 1: Campaign + Metrics

**Chức năng:** Với mỗi tài khoản được đánh `TRUE` ở cột "Chọn Lấy Camp", script lấy danh sách campaign và số liệu hiệu quả (insights) theo khoảng thời gian đã chọn, ghi mỗi campaign thành một dòng vào tab riêng của tài khoản đó.

**Các bước chính:**
1. Đọc sheet "TKQC API", lọc tài khoản có `Chọn Lấy Camp = TRUE`.
2. Đọc và giữ nguyên cột **"Chọn Lấy Chi Tiết"** (lựa chọn Phase 2 không bị mất).
3. Gọi `GET /{account_id}/campaigns` → danh sách campaign.
4. Gọi `GET /{account_id}/insights?level=campaign` → metrics tháng.
5. Ghép campaign với insights, sắp xếp theo trạng thái → tên.
6. Ghi vào tab `{Tên tài khoản}` (tạo mới nếu chưa có).
7. Lưu `campaigns.json` và `insights_campaign.json`.

**Metrics được tính (18 cột F–W):**
Spend, Impressions, Clicks, CTR, CPC, CPM, Reach, Frequency, Inbox, CPI, Lead, CPL, Đơn Hàng, CPS, Doanh Thu, ROAS, Kết Quả chính, Chi Phí/Kết Quả.

**Hàm dùng lại quan trọng** (cũng được import bởi `get_details.py`):
- `parse_insight_metrics()` — chuẩn hóa raw insight thành dict float
- `aggregate_metrics()` — tổng hợp metrics từ nhiều Ad thành metrics Adset
- `_insights_cols()` — format 18 giá trị metrics thành list string cho sheet
- `paginate()` — xử lý phân trang Facebook API

---

### `get_details.py` — Phase 2: Adset / Ad / Creative

**Chức năng:** Với mỗi campaign được đánh `TRUE` ở cột "Chọn Lấy Chi Tiết", script lấy toàn bộ Adset và Ad kèm creative, chèn các dòng Adset/Ad ngay bên dưới dòng Campaign tương ứng mà **không xóa dữ liệu Campaign**.

**Các bước chính:**
1. Đọc danh sách campaign có `Chọn Lấy Chi Tiết = TRUE`.
2. Gọi `GET /{account_id}/insights?level=ad` → insights cho từng Ad.
3. Với mỗi campaign được chọn:
   - `GET /{campaign_id}/adsets` → danh sách adset
   - `GET /{adset_id}/ads` → ads kèm creative chi tiết
4. **Xóa toàn bộ dòng Adset/Ad cũ** rồi **chèn lại** (`insert_rows`) đúng vị trí phía dưới dòng Campaign — dòng Campaign và các cột người dùng tự thêm không bị ảnh hưởng.
5. Metrics Adset = tổng hợp (`aggregate_metrics`) từ các Ad con.
6. Ghi tab `{TK} - Creative` riêng với 12 cột creative.
7. Lưu `adsets.json`, `ads.json`, `insights_ad.json`.

**Tab Creative (12 cột):**

| Cột | Nội dung |
|-----|----------|
| Creative ID | ID creative |
| Ad ID / Ad Name | ID và tên quảng cáo |
| Trạng Thái | Trạng thái ad |
| Campaign ID / Adset Name | Tham chiếu ngữ cảnh |
| Page ID / Post ID | Tách từ `effective_object_story_id` |
| Thumbnail URL | Ảnh thumbnail |
| Nội Dung Quảng Cáo | Body text |
| Tiêu Đề | Title |
| **Ghi Chú** | ✍ Người dùng tự điền — giữ nguyên khi refresh |

---

### `launcher.py` — GUI điều phối (entry point chính)

**Chức năng:** Giao diện dark-mode cho phép người dùng chọn khoảng thời gian và các script cần chạy, sau đó thực thi tuần tự với output realtime.

**Giao diện gồm:**
- **Card 1 — Khoảng thời gian:** Radio chọn preset (Hôm nay / Tháng này / Quý trước / …) hoặc nhập ngày tuỳ chỉnh (YYYY-MM-DD).
- **Card 2 — Script cần chạy:** Checkbox chọn Phase 1 (`get_campaigns.py`) và/hoặc Phase 2 (`get_details.py`).
- **Nút Chạy ngay:** Ghi `config.py`, chạy lần lượt từng script qua `subprocess.Popen`, stream output vào console.
- **Console:** Hiển thị stdout realtime với màu sắc (xanh = OK, đỏ = lỗi, vàng = warning).

> **Lưu ý:** `main.py` (đồng bộ danh sách TKQC) không được tích hợp vào launcher — chạy riêng khi cần cập nhật danh sách tài khoản.

---

### `fb_billing_import.py` — Nhập lịch sử thanh toán

**Chức năng:** GUI nhập lịch sử thanh toán từ file CSV hoặc XLS (xuất từ **FB Billing Scraper** extension) vào một tab bất kỳ trong Google Sheet, với logic upsert theo "ID giao dịch".

**Luồng sử dụng:**
1. Kết nối Google Sheet tự động khi khởi động.
2. **Bước 1** — Chọn tab đích trong danh sách bên trái.
3. **Bước 2** — Duyệt và chọn file CSV/XLS; app đọc file và hiển thị:
   - Tổng dòng, số cột
   - Số dòng sẽ import (chỉ giữ `Trạng thái = "Đã thanh toán"`)
   - Phân tích cột: khớp / mới từ CSV / thiếu trong CSV
4. **Bước 3** — Preview bảng dữ liệu (tối đa 200 dòng).
5. Nhấn **Import** → hộp thoại xác nhận → ghi vào sheet.

**Logic upsert:**
- Nếu "ID giao dịch" đã tồn tại trong sheet → cập nhật dòng đó.
- Nếu chưa có → thêm dòng mới.
- Cột mới từ CSV chưa có trong sheet sẽ tự động được thêm.
- Cột ID dạng text (ID giao dịch, Tài khoản QC, …) được format `TEXT` để tránh mất số 0 đầu.

**Hỗ trợ định dạng file:**
- `.csv` — đọc với fallback encoding utf-8-sig → utf-8 → cp1252
- `.xls` — đọc SpreadsheetML (XML-based) do extension FB Billing Scraper xuất

---

## Phụ thuộc (`requirements.txt`)

| Package | Phiên bản | Dùng cho |
|---------|-----------|----------|
| `gspread` | 6.1.2 | Đọc/ghi Google Sheets |
| `google-auth` | 2.29.0 | Xác thực Service Account |
| `requests` | 2.31.0 | Gọi Facebook Graph API |

---

## File dữ liệu sinh ra khi chạy

| File | Sinh bởi | Nội dung |
|------|----------|---------|
| `ad_accounts.json` | `main.py` | Raw response danh sách tài khoản |
| `campaigns.json` | `get_campaigns.py` | Raw campaigns theo từng tài khoản |
| `insights_campaign.json` | `get_campaigns.py` | Raw insights cấp campaign |
| `adsets.json` | `get_details.py` | Raw adsets của campaigns được chọn |
| `ads.json` | `get_details.py` | Raw ads kèm creative |
| `insights_ad.json` | `get_details.py` | Raw insights cấp ad |
