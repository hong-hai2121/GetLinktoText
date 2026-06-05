# FB Ads Pages → Chi Tiết Chiến Dịch Theo Page

Lấy danh sách **Page đang quản lý**, chọn page → quét các Tài Khoản Quảng Cáo,
lọc ra các **Campaign** đang quảng cáo cho page đó và ghi vào Google Sheets.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình

1. **Facebook token** — điền vào `ACCESS_TOKEN` trong [config.py](config.py).
   Token cần quyền: `ads_read`, `pages_show_list` (và `pages_read_engagement` nếu cần).
2. **Google Sheet** — kết quả ghi vào sheet:
   `https://docs.google.com/spreadsheets/d/1aBWyX1f3yjMVbbJ7HxDbvS3ZvjBL9JsXc3Ycm_gTwAc`
   Phải **chia sẻ sheet** này cho service account
   `ads-392@hai-ads-check.iam.gserviceaccount.com` với quyền **Editor**.
   Tab cho từng page sẽ tự tạo nếu chưa có.

## Chạy

```bash
python get_pages.py
```

1. Cửa sổ hiện danh sách page (`/me/accounts`). Click dòng để tích chọn.
2. Bấm **"Lấy chi tiết chiến dịch"** → mở cửa sổ mới (`get_page_campaigns.py`)
   xử lý các page đã chọn và ghi vào Google Sheets, mỗi page 1 tab.

## File

| File | Vai trò |
|------|---------|
| `get_pages.py` | GUI liệt kê page quản lý + mở script chi tiết |
| `get_page_campaigns.py` | Quét TKQC → lọc campaign theo page → ghi Sheets |
| `config.py` | `ACCESS_TOKEN`, `DATE_PRESET` (mặc định `this_month`) |
| `fb_api.py` | Bộ đếm / log / retry rate-limit cho Graph API (dùng chung) |
| `service_account.json` | Khóa Google Service Account |

## Lưu ý về số liệu

Facebook không có endpoint "campaign của 1 page" — campaign thuộc về Tài Khoản
Quảng Cáo, chỉ nối với page qua creative của quảng cáo
(`object_story_spec.page_id` hoặc `effective_object_story_id`). Vì vậy metric
hiển thị là của **toàn campaign**; nếu một campaign quảng cáo nhiều page thì số
liệu là gộp chung. Cột **"Số Ad Của Page"** cho biết bao nhiêu ad trong campaign
đó quảng cáo cho page đang xét.
