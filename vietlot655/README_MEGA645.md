# Vietlott Mega 6/45 crawler

Tool này tách riêng hoàn toàn khỏi crawler Power 6/55.

## Files

- `crawl_mega645.py`
- `vietlott_mega645_data.db`
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

- Trước khi cào: chốt 1000 bộ/chế độ (5 giải thuật) dựa trên lịch sử hiện có.
- Sau khi cào: tính lại `number_frequency` / `number_streaks` /
  `position_distribution` / `position_summary` cho `mega645`.
- Chấm điểm các batch đang chờ vào `prediction_stats`.

Tắt phần dự đoán: `--no-predict`. Đổi số bộ: `--predict-sets 5000`.

Nhờ vậy `stats_web.py` sinh trang Mega **đầy đủ** như Power (có "Phân bố theo vị
trí", bảng xếp hạng giải thuật...), không còn bản rút gọn. Muốn rút gọn thì
truyền `--minimal`.

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

## Export

```powershell
python export_mega645_excel.py --format csv
python export_mega645_excel.py --format xlsx
python export_mega645_excel.py --format both
```

Mega 6/45 không có số đặc biệt sau dấu `|`, nên `special_num` được lưu rỗng.
