# Pipeline FB Ads — Chi tiết bất biến & builders

> Đọc file này khi cần chi tiết đầy đủ về builders, ý nghĩa cột, hằng action_type.
> Mọi file:dòng cần xác minh lại trên code hiện tại (memory có thể cũ).

## Mục lục
1. Schema Main Sheet
2. Builders
3. Hằng action_type
4. Schema Creative Sheet
5. Cơ chế Phase 2
6. Xuất JSON debug
7. Dead code

## 1. Schema Main Sheet (spec-driven)
`COLUMNS` trong `get_campaigns.py` = list `(header, is_metric, getter(ctx))`.
`HEADERS = [h for h,_,_ in COLUMNS]`. Đổi thứ tự cột = sửa list này; mọi file (get_details,
tong_hop) tự theo. Không còn tách cứng "entity A–H + metric I..".

Nhóm cột (xác minh tên/thứ tự thực tế trong code):
- Entity/chọn: Chọn Lấy Chi Tiết, Cấp, ID Chiến Dịch, Tên Chiến Dịch, Trạng Thái, Tình Trạng Phân Phối.
- Metric hội thoại/đơn: Lượt Bắt Đầu Cuộc Trò Chuyện Qua Tin Nhắn, Chi Phí/Lượt Bắt Đầu,
  Đơn Hàng Đã Tạo, Chi Phí/Đơn Hàng, Kết Quả, Chi Phí/Kết Quả.
- Ngân sách/chi tiêu: Ngân Sách Hằng Ngày, Số Tiền Đã Chi Tiêu, Lượt Hiển Thị, Người Tiếp Cận,
  Tần Suất, Số Lần Nhấp, CTR(%), CPC, CPM, Hành Động, Chi Phí/Hành Động.
- Cuối: Mục Tiêu, Ngày Bắt Đầu, Ngày Kết Thúc.

`build_headers()` gắn `(Kỳ)` vào cột "Số Tiền Đã Chi Tiêu" (`COL_SPEND`) — tìm THEO TÊN, không index.

`ID Chiến Dịch` = `camp_id` tham chiếu ở mọi cấp. `Tên Chiến Dịch` = tên entity của dòng hiện tại.

## 2. Builders
- `_campaign_row(meta, insight, is_selected, auto_by_spend)` — dòng Campaign (Phase 1).
- `build_detail_row(level, camp_id, entity, insight)` — dòng Adset/Ad (get_details).
- `merge_metric_row(existing_row, insight)` — refresh Campaign trong Phase 2: giữ cột Chọn +
  entity, chỉ thay cột metric, ghi cả dòng A→cột cuối.
- `aggregate_insights()` — Adset gộp các Ad con.

## 3. Hằng action_type (đầu file)
- `ACTION_RESULT` = `ACTION_MESSAGING` = `onsite_conversion.messaging_conversation_started_7d`.
- `ACTION_ORDER_CREATED` = `omni_purchase` (data có thể chưa có → rỗng).
- `_action_value()` lấy 1 action_type cụ thể từ insight. `Chi Phí/X` = spend / X.

## 4. Schema Creative Sheet — 12 cột (A–L)
A=Creative ID, B=Ad ID, C=Ad Name, D=Trạng Thái, E=Campaign ID, F=Adset Name, G=Page ID,
H=Post ID, I=Thumbnail URL, J=Nội Dung Quảng Cáo, K=Tiêu Đề, L=Ghi Chú (người dùng tự điền).

## 5. Cơ chế Phase 2 — insert_rows (KHÔNG clear)
1. `delete_rows()` dưới → trên cho Adset/Ad cũ.
2. `insert_rows()` dưới → trên, chèn Adset/Ad mới sau mỗi Campaign được chọn.
Lý do: insert_rows dịch mọi cột kể cả cột user thêm (ngoài phạm vi script). Clear+rewrite mất dữ liệu đó.

## 6. Xuất JSON debug
`get_campaigns.py` dump `get_campaigns.json`; `get_details.py` dump `get_details.json`.
get_campaigns lưu trong `finally` của `run()` (rate-limit vẫn ghi phần đã lấy).
Mỗi tab: `acc_id, acc_name, campaigns[], campaign_insights[]`.

## 7. Dead code (đừng nhầm là code sống)
`parse_insight_metrics`, `aggregate_metrics`, `_insights_cols` — còn định nghĩa nhưng KHÔNG dùng.

## fetch_campaigns fields
`/act_{id}/campaigns` lấy `id,name,status,effective_status,objective,daily_budget`.
Insights cấp campaign dùng `_INSIGHTS_FIELDS`.
