---
name: fb-pipeline-verify
description: Checklist và script xác minh bất biến pipeline FB Ads sau khi sửa code — COLUMNS đồng bộ giữa get_campaigns/get_details/tong_hop, không có clear() ở Phase 2 (get_details), số tiền ghi int không string, py_compile sạch. Dùng sau mỗi thay đổi pipeline trước khi báo hoàn thành.
---

# Xác minh Pipeline FB Ads

Skill này định nghĩa "cách kiểm tra" thay đổi pipeline. Mục tiêu: bắt vi phạm bất biến TRƯỚC
khi code chạy lên Google Sheets thật của người dùng. Hiểu rõ ở `fb-pipeline-edit`.

## Cách dùng nhanh
Chạy script tự động trên thư mục biến thể đã sửa:
```
python .claude/skills/fb-pipeline-verify/scripts/verify_pipeline.py ADS_facebook/fb_ads_tsAnhDuc
```
Script báo PASS/FAIL từng bất biến tĩnh. Sau đó làm kiểm tra thủ công cho phần script không bắt được.

## Checklist 5 bất biến

### 1. COLUMNS là nguồn duy nhất
- `get_campaigns.py` có `COLUMNS` + `HEADERS = [h for h,_,_ in COLUMNS]`.
- Không file nào hardcode index cột (`row[8]`, `cells[12]`) cho cột metric — phải tìm theo tên
  hoặc dẫn xuất từ HEADERS. (Index cố định cho cột entity đầu như Chọn/Cấp có thể chấp nhận
  nếu nhất quán, nhưng cảnh báo nếu thấy magic number cho cột metric.)

### 2. Phase 2 không clear()
- `get_details.py` KHÔNG chứa `.clear()` hay rewrite toàn sheet.
- Phải dùng `delete_rows()` + `insert_rows()`.
- `get_campaigns.py` ĐƯỢC phép clear (Phase 1 viết lại toàn bộ) — không cảnh báo file này.

### 3. Số tiền là int
- Getter cột tiền tệ dùng `int(round(...))`, không `str(...)`/f-string khi ghi giá trị số.

### 4. Biên dịch sạch
- `python -m py_compile <mỗi file đã sửa>` không lỗi.

### 5. Đồng bộ đa file
- Nếu COLUMNS đổi số cột/thứ tự: `build_detail_row`, `merge_metric_row` (get_details) và header
  trong `tong_hop` vẫn khớp số cột + vị trí cột metric.
- So sánh chéo: đọc đồng thời định nghĩa COLUMNS và nơi tiêu thụ, đối chiếu shape.

## Quy trình báo cáo
1. Chạy script tự động → ghi nhận PASS/FAIL.
2. py_compile các file đã đổi.
3. So sánh chéo thủ công bất biến #5 (script không bắt được hết).
4. Báo cáo: `PASS` toàn bộ, hoặc danh sách `[bất biến #] file:dòng — mô tả vi phạm`.
5. Nếu FAIL → gửi `pipeline-developer` sửa, không tự sửa.

## Lưu ý
Script chỉ phân tích tĩnh (text/AST), không gọi API hay Sheets thật. Một số bất biến (như đồng bộ
shape COLUMNS↔builder) cần đọc-hiểu, không tự động hoàn toàn được — đừng tin 100% vào PASS của script.
