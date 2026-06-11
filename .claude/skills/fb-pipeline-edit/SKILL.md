---
name: fb-pipeline-edit
description: Hướng dẫn sửa đổi an toàn code pipeline FB Ads (get_campaigns.py, get_details.py, tong_hop.py, hub.py) trong ADS_facebook. Dùng khi thêm/đổi/xóa cột schema, thêm metric/action_type, sửa fetcher Graph API, đổi cách ghi Google Sheets. Bắt buộc đọc trước khi sửa bất kỳ file pipeline nào để không vi phạm bất biến gây mất dữ liệu.
---

# Sửa đổi Pipeline FB Ads an toàn

Skill này định nghĩa "cách sửa đúng" cho code pipeline. Vi phạm các bất biến dưới đây có thể
làm **mất dữ liệu thật trên Google Sheets của người dùng** — nên hiểu lý do, không chỉ làm theo.

## Bản đồ file
| File | Vai trò | Được phép clear? |
|------|---------|------------------|
| `get_campaigns.py` | Phase 1: fetch campaigns + insights, ghi Campaign rows. **Định nghĩa `COLUMNS`** (nguồn chân lý). | Có — viết lại toàn bộ Campaign rows từ API |
| `get_details.py` | Phase 2: fetch adsets/ads, chèn Adset/Ad rows, ghi Creative sheet | **KHÔNG** — chỉ delete_rows + insert_rows |
| `tong_hop.py` / `TongHop.py` | Gộp các tab campaign thành sheet tổng hợp theo kỳ | Theo logic riêng |
| `hub.py` | GUI hợp nhất, ghi config rồi Popen tool con | — |

Hai biến thể song song **khác kiểu schema** (đã xác minh 2026-06-11):
- `fb_ads_tsAnhDuc/` — **schema-driven**: `COLUMNS` là nguồn chân lý, `HEADERS` dẫn xuất. Đổi cột = sửa `COLUMNS`.
- `fb_ads_accounts/` — **kiểu cũ**: `HEADERS` là list tĩnh, KHÔNG có `COLUMNS`. Đổi cột phải đồng bộ
  THỦ CÔNG sang `get_details.py`/`TongHop.py` (kiểm kỹ bất biến #5 — không có cơ chế tự theo).

Khi sửa logic chung, xác định đúng biến thể trước. Đừng áp pattern schema-driven của tsAnhDuc
vào fb_ads_accounts mà không refactor có chủ đích.

## Bất biến cốt lõi (4 quy tắc)

### 1. Schema-driven — `COLUMNS` là nguồn chân lý duy nhất
`COLUMNS` trong `get_campaigns.py` là list `(header, is_metric, getter(ctx))`.
`HEADERS = [h for h,_,_ in COLUMNS]`. Mọi file khác dẫn xuất từ đây.

- **Thêm/đổi/bỏ cột** = chỉ sửa list `COLUMNS`. Không hardcode index cột (`row[8]`) ở file khác —
  tìm theo tên (vd `build_headers()` gắn `(Kỳ)` vào cột tìm theo tên `COL_SPEND`).
- `is_metric=True` → giá trị suy từ insight (`_metrics()` dict), refresh khi cập nhật dòng Campaign.
- `is_metric=False` → entity/Chọn; getter trả rỗng nếu level != Campaign (Adset/Ad không có
  Mục Tiêu/Ngân Sách/Chọn).

### 2. Phase 2 KHÔNG BAO GIỜ `clear()`
`get_details.py` chèn Adset/Ad mà không xóa Campaign rows:
1. `delete_rows()` từ dưới lên cho Adset/Ad cũ.
2. `insert_rows()` từ dưới lên, chèn Adset/Ad mới sau mỗi Campaign được chọn.

**Lý do:** `insert_rows()` khiến Sheets dịch chuyển TẤT CẢ cột — kể cả cột người dùng tự thêm
ngoài phạm vi script. `clear()` + rewrite sẽ xóa mất dữ liệu thủ công đó. Đây là yêu cầu cứng
của người dùng.

### 3. Số tiền ghi `int` thật, không string
`int(round(m["spend"]))`. String có dấu `'` prefix trong Sheets → không tính toán được.
Áp dụng cho mọi giá trị số người dùng cần tính (tiền, lượt, chi phí).

### 4. Config đọc lúc import → chạy bằng subprocess
`DATE_PRESET`/`TIME_RANGE` đọc ở module-level của pipeline. Nếu import vào tiến trình dài
(vd hub), ngày bị "đóng băng". Bất cứ thứ gì chạy pipeline với kỳ mới phải **ghi `config.py`
trước** rồi `Popen` tool con (import mới mỗi lần). `write_config()` giữ nguyên dòng `ACCESS_TOKEN`.

## Quy trình sửa
1. Đọc file mục tiêu + `COLUMNS` để hiểu schema hiện tại.
2. Nếu cần biết field Graph API hay hành vi gspread → hỏi `graph-api-researcher`, đừng đoán.
3. Sửa tối thiểu, bám idiom xung quanh (mật độ comment, đặt tên, cách dùng builder).
4. `python -m py_compile <file đã sửa>` — phải sạch.
5. Bàn giao `pipeline-qa`.

## Khi nào đọc reference
- Cần danh sách builder đầy đủ + ý nghĩa từng cột + hằng action_type → đọc
  `references/invariants.md`.
- Dead code đã biết (`parse_insight_metrics`, `aggregate_metrics`, `_insights_cols`) — định nghĩa
  còn nhưng KHÔNG dùng; đừng tưởng là code sống.

## Cảnh báo
Memory dự án có thể cũ (file:dòng có thể đã đổi). **Luôn xác minh trên code hiện tại** trước khi
khẳng định cấu trúc.
