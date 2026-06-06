# FB Ads — TKQC → Chi Tiết Chiến Dịch

Cập nhật danh sách **Tài Khoản Quảng Cáo (TKQC)**, đánh dấu TKQC cần lấy bằng cột
**"Chọn Lấy Camp"** = TRUE, rồi lấy toàn bộ **Campaign** + insights của các TKQC
đó và ghi vào Google Sheets.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình

1. **Facebook token** — điền vào `ACCESS_TOKEN` trong [config.py](config.py).
   Token cần quyền: `ads_read` (và `business_management` nếu cần).
2. **Google Sheet** — kết quả ghi vào sheet:
   `https://docs.google.com/spreadsheets/d/1aBWyX1f3yjMVbbJ7HxDbvS3ZvjBL9JsXc3Ycm_gTwAc`
   Phải **chia sẻ sheet** này cho service account
   `ads-392@hai-ads-check.iam.gserviceaccount.com` với quyền **Editor**.
   Tab "TKQC API" và tab cho từng TKQC sẽ tự tạo nếu chưa có.

## Chạy

```bash
python get_accounts.py     # bước 1 – danh sách TKQC
python get_campaigns.py    # bước 2 – campaign mỗi TKQC
python get_details.py      # bước 3 – adset/ad cho campaign được chọn
```

1. `get_accounts.py` — cập nhật danh sách TKQC vào tab **"TKQC API"**. Trong tab
   này, đặt cột **"Chọn Lấy Camp"** = `TRUE` cho những TKQC muốn lấy chiến dịch.
2. `get_campaigns.py` — đọc tab "TKQC API", lọc các TKQC có **"Chọn Lấy Camp" =
   TRUE**, lấy toàn bộ campaign + insights của từng TKQC và ghi vào Google Sheets,
   **mỗi TKQC 1 tab** (mỗi campaign 1 dòng, sắp xếp theo spend giảm dần). Mỗi tab
   có cột **"Cấp"** (Campaign/Adset/Ad) và cột **"Chọn Lấy Chi Tiết"**.
3. Trong tab TKQC, đặt **"Chọn Lấy Chi Tiết"** = `TRUE` cho các campaign muốn xem
   sâu, rồi chạy `get_details.py` — script **chèn dòng Adset/Ad** (kèm insights cấp
   ad) ngay dưới mỗi campaign được chọn, không xoá dòng Campaign. Có checkpoint nên
   gặp rate limit chạy lại sẽ tiếp tục từ chỗ dở.

## File

| File | Vai trò |
|------|---------|
| `get_accounts.py` | GUI cập nhật danh sách TKQC vào tab "TKQC API" |
| `get_campaigns.py` | Đọc TKQC có TRUE → lấy campaign + insights → ghi Sheets |
| `get_details.py` | Đọc campaign có "Chọn Lấy Chi Tiết" = TRUE → chèn Adset/Ad |
| `config.py` | `ACCESS_TOKEN`, `DATE_PRESET` (mặc định `this_month`) |
| `fb_api.py` | Bộ đếm / log / retry rate-limit cho Graph API (dùng chung) |
| `service_account.json` | Khóa Google Service Account |

## Lưu ý về số liệu

Metric của mỗi dòng là insights cấp **campaign** (dòng Cấp = Campaign) hoặc cấp
**ad** (dòng Cấp = Ad; dòng Adset là tổng hợp các ad con) trong khoảng `DATE_PRESET`
(mặc định `this_month`). Cột **"Chi Phí Campaign"** là spend làm tròn; dòng campaign
có **"Chọn Lấy Chi Tiết"** = TRUE được tô nền xanh nhạt.
