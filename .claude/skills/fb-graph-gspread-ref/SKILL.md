---
name: fb-graph-gspread-ref
description: Bảng tra cứu Facebook Graph API (fields cho campaigns/adsets/ads/insights, action_type) và hành vi gspread (insert_rows dịch cột, ghi int vs string, định dạng số) cho pipeline FB Ads. Dùng khi cần biết field API hợp lệ, cấu trúc insight, hoặc cách gspread thao tác hàng/cột mà không muốn đoán sai.
---

# Tra cứu Graph API & gspread

Tham chiếu nhanh cho researcher. Luôn xác minh chéo với code hiện tại (`fb_api.py`, `config.py`)
và tài liệu Graph API chính thức khi không chắc — đừng bịa field.

## Facebook Graph API

### Edges thường dùng
| Edge | Fields điển hình trong dự án |
|------|------------------------------|
| `/act_{id}/campaigns` | `id,name,status,effective_status,objective,daily_budget` |
| `/{campaign_id}/adsets` | `id,name,status,effective_status` |
| `/{adset_id}/ads` | `id,name,status,creative` |
| `.../insights` | định nghĩa ở `_INSIGHTS_FIELDS` trong code |

### action_type quan trọng
- `onsite_conversion.messaging_conversation_started_7d` — Lượt bắt đầu hội thoại (= Kết Quả mặc định).
- `omni_purchase` — Đơn hàng đã tạo (data có thể chưa có → rỗng).
- Insight trả `actions` là list `{action_type, value}`; lấy 1 type cụ thể qua hàm như `_action_value()`.

### Lưu ý API
- Rate limit: response vẫn nên dump JSON thô trong `finally` để giữ phần đã lấy.
- `daily_budget` trả về đơn vị nhỏ nhất (xu/cent) tùy currency — kiểm tra cách code chia.
- `effective_status` (tình trạng phân phối) khác `status` (trạng thái bật/tắt).

## gspread

### insert_rows / delete_rows — DỊCH CỘT
`insert_rows(values, row)` chèn hàng và **dịch chuyển TẤT CẢ cột hiện có xuống**, kể cả cột
người dùng tự thêm ngoài phạm vi script. Đây là lý do Phase 2 dùng insert thay vì clear+rewrite:
giữ nguyên dữ liệu thủ công. `delete_rows(start, end)` tương tự, dịch lên.
→ Luôn thao tác từ **dưới lên** để index không lệch khi chèn/xóa nhiều khối.

### Ghi int vs string
- Ghi `int`/`float` Python → ô số, tính toán được.
- Ghi `str` (đặc biệt số dạng chuỗi) → gspread/Sheets có thể thêm `'` prefix → text, không tính được.
- Tiền: `int(round(spend))`.

### Hiệu năng
- Gom ghi bằng batch (`update`, `batch_update`) thay vì ghi từng ô để giảm gọi API.
- Định dạng số (số thập phân, %) qua format request riêng, không nhúng vào giá trị.

## Vị trí code cần biết
- Hằng action_type, `_INSIGHTS_FIELDS`, `COLUMNS`: đầu `get_campaigns.py`.
- Wrapper gọi API: `fb_api.py`. Token + kỳ: `config.py`.
- Builders: xem `references` của skill `fb-pipeline-edit`.
