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

## Export

```powershell
python export_mega645_excel.py --format csv
python export_mega645_excel.py --format xlsx
python export_mega645_excel.py --format both
```

Mega 6/45 không có số đặc biệt sau dấu `|`, nên `special_num` được lưu rỗng.
