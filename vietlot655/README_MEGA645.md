# Vietlott Mega 6/45 crawler

Từ 2026-08-22, `crawl_mega645.py` chỉ còn là **wrapper mỏng (~40 dòng)** gọi
đúng engine của `crawl.py` với `--game mega645 --db vietlott_mega645_data.db`
(crawl.py vốn có sẵn `GAME_CONFIGS["mega645"]`). Trước đó nó là bản copy ~700
dòng và hai bản đã bắt đầu lệch nhau. Mọi bugfix cho crawler (retry, validate
số, busy_timeout...) giờ chỉ cần sửa MỘT chỗ trong `crawl.py`.

Dữ liệu và log vẫn tách riêng như cũ:

- `vietlott_mega645_data.db` (schema đã được crawl.py tự migrate sang
  `UNIQUE(game_type, draw_period)` — dữ liệu giữ nguyên)
- `export_mega645_excel.py`
- `logs\crawler_mega645.log`
- `exports\vietlott_mega645.xlsx`
- `exports\vietlott_mega645.csv`

## Crawl

```powershell
cd D:\Python\GetLinktoText\vietlot655
python crawl_mega645.py
```

Mặc định đây là chế độ cập nhật hằng ngày: crawler lấy trang mới nhất,
import kỳ chưa có, và dừng ngay khi gặp một trang mà toàn bộ kỳ đã có trong DB.
Crawler gọi AjaxPro với `PageIndex=1,2,3...` khi cần đi sang trang tiếp theo.

Test giới hạn số trang:

```powershell
python crawl_mega645.py --max-pages 3
```

Cào full lịch sử khi cần:

```powershell
python crawl_mega645.py --full-crawl
```

## Thống kê & backtest — giống hệt Power 6/55

Từ 2026-07-21, `crawl_mega645.py` làm đủ mọi thứ mà `crawl.py` làm cho Power:

- Trước khi cào: chốt 1000 bộ/chế độ (6 giải thuật) dựa trên lịch sử hiện có.
- Sau khi cào: tính lại `number_frequency` / `number_streaks` /
  `position_distribution` / `position_summary` cho `mega645`.
- Chấm điểm các batch đang chờ vào `prediction_stats`.

Tắt phần dự đoán: `--no-predict`. Đổi số bộ: `--predict-sets 5000`.

Nhờ vậy `stats_web.py` sinh trang Mega **giống hệt** trang Power — cùng 5 mục,
không còn bản rút gọn.

Các bảng `number_frequency` / `position_*` vẫn cần dù trang không còn vẽ biểu đồ:
`sugEngine` đọc chúng để sinh bộ số. Xem mục "Các mục đã bỏ" trong `README.md`.

Bảng xếp hạng giải thuật cho Mega:

```powershell
python predict_track.py --db vietlott_mega645_data.db board --game mega645
```

Lưu ý thứ tự tham số: `--db` đứng TRƯỚC subcommand, `--game` đứng sau.

DB Mega cũ chưa có bảng thống kê thì tính một lần bằng:

```powershell
python number_stats.py --db vietlott_mega645_data.db --game mega645
python predict_track.py --db vietlott_mega645_data.db backfill --game mega645 --periods 300 -n 1000
```

Thêm `--redo` nếu muốn xoá các kỳ đã chấm rồi dựng lại từ đầu (cần khi thêm chế độ
mới). Backfill 304 kỳ × 6 chế độ mất khoảng 5–6 phút (từ 2026-08-22, sau khi
tiền tính trọng số trong `predict_track.py` — kết quả giữ nguyên từng bit với
cùng seed, không cần `--redo` vì tối ưu này).

### Cạm bẫy riêng của Mega 6/45: trần độ phủ

Mega chỉ có C(45,3) = **14.190** bộ-3, ít hơn mức 20 × 1000 = 20.000 của một bội số
1000 vé. Vì vậy trần độ phủ phải là `min(20 × số vé, C(n,3))` chứ không phải
`20 × số vé` — nếu lấy 20.000 làm mẫu số thì mọi chế độ ở Mega đều bị báo thấp một
cách giả tạo (chế độ "Phủ rộng" bị báo 64% thay vì 90,8% thật).

Xem `coverage_cap()` trong `predict_track.py` và `coverageCap()` trong JS của
`stats_web.py` — hai chỗ phải giống nhau. Ràng buộc này giờ được KHÓA bằng bộ
golden vectors: `python predict_track.py selftest` kiểm bản Python, còn trang
HTML tự đối chiếu bản JS lúc mở (lệch là hiện banner cảnh báo). Chi tiết ở mục
"bảng xếp theo ĐỘ PHỦ" trong `README.md`.

Kết quả backtest Mega (304 kỳ, 1,82 triệu vé): không giải thuật nào vượt ngẫu nhiên,
TB trùng cả 6 chế độ đều quanh 0,800 = 36/45. Độ phủ: Phủ rộng 90,8% · Cân đối 73,1%
· Số nóng 72,8% · Tránh số đông 56,7% · Số gan 43,8% · Theo cặp 24,1%.

## Export

```powershell
python export_mega645_excel.py --format csv
python export_mega645_excel.py --format xlsx
python export_mega645_excel.py --format both
```

Mega 6/45 không có số đặc biệt sau dấu `|`, nên `special_num` được lưu rỗng.
