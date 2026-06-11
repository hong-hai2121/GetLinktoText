# FB Ads → Google Sheet Sync

Hệ thống lấy dữ liệu Facebook Ads từ **Meta Marketing API** và đẩy vào **Google Sheet**
làm database tạm cho web dashboard. Lấy theo 3 cấp (campaign / adset / ad) và 5 kỳ thời
gian (hôm nay, hôm qua, 7 ngày, tháng này, lifetime), bóc tách số tin nhắn từ `actions`,
upsert theo khóa nên **không làm mất dữ liệu cũ**.

## Cấu trúc file

```
fb_ads_dashboard_sync/
├── main.py            # Điểm chạy: orchestrate toàn bộ luồng + write_sync_log()
├── config.py          # Đọc .env, validate biến môi trường
├── meta_api.py        # get_meta_insights() + metadata thực thể, paging + retry
├── transform.py       # parse_actions(), calculate_message_metrics(), build_*_row()
├── dashboard.py       # build_dashboard_daily(), build_dashboard_lifetime()
├── sheets.py          # connect, get_or_create_worksheet, upsert_to_google_sheet()
├── schema.py          # Tên sheet + thứ tự cột + khóa upsert (nguồn chân lý)
├── requirements.txt
├── .env.example
└── service_account.json   # (bạn tự thêm — KHÔNG commit)
```

## 1. Cài thư viện

```bash
cd fb_ads_dashboard_sync
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## 2. Chuẩn bị Google Service Account

1. Tạo service account trên Google Cloud, bật **Google Sheets API** + **Drive API**.
2. Tải file JSON key → lưu thành `service_account.json` trong thư mục này.
3. **Chia sẻ Google Sheet** cho email service account (dạng `xxx@yyy.iam.gserviceaccount.com`)
   với quyền **Editor**.

## 3. Tạo file `.env`

Copy `.env.example` thành `.env` rồi điền:

```env
META_ACCESS_TOKEN=EAAxxxxxxxx
META_AD_ACCOUNT_ID=act_123456789012345
GOOGLE_SHEET_ID=1aBWyX1f3yjMVbbJ7HxDbvS3ZvjBL9JsXc3Ycm_gTwAc
GOOGLE_SERVICE_ACCOUNT_JSON=service_account.json
FB_API_VERSION=v20.0
```

- `META_ACCESS_TOKEN`: token có quyền `ads_read`.
- `META_AD_ACCOUNT_ID`: có hoặc không có tiền tố `act_` đều được.
- `GOOGLE_SHEET_ID`: phần giữa `/d/.../edit` trên URL Sheet.

## 4. Chạy

```bash
python main.py
```

Mỗi lần chạy sẽ:

1. Lấy metadata thực thể (status / effective_status / objective / budget).
2. Với 4 kỳ daily (`today`, `yesterday`, `last_7d`, `this_month`) × 3 level
   (campaign/adset/ad), lấy insights `time_increment=1` (tách theo từng ngày) →
   **upsert** vào `raw_campaign_daily`, `raw_adset_daily`, `raw_ad_daily`.
3. Dựng `dashboard_daily` (tổng hợp theo ngày × campaign).
4. Lấy lifetime (`date_preset=maximum`, level=campaign) → dựng `dashboard_lifetime`.
5. Ghi `sync_log` cho mỗi bước.

> Chạy nhiều lần an toàn: upsert theo khóa nên dòng trùng được **cập nhật**, dòng mới được
> **thêm**, dữ liệu cũ không bị xóa. Có thể đặt cron/Task Scheduler chạy mỗi giờ.

## Khóa upsert

| Sheet                | Khóa |
|----------------------|------|
| `raw_*_daily`        | `date_start` + `account_id` + `campaign_id` + `adset_id` + `ad_id` |
| `dashboard_daily`    | `date` + `account_id` + `campaign_id` |
| `dashboard_lifetime` | `account_id` + `campaign_id` |

## Cột nhập tay / nối CRM

`orders`, `revenue`, `note` (và `cost_per_order`, `roas`) ở 2 sheet dashboard để **trống**
khi sync. Bạn nhập tay hoặc nối CRM; lần sync sau **giữ nguyên** các ô này (không ghi đè) —
xem `PRESERVE_*` trong `schema.py`.

- `cost_per_order = spend / orders` nếu `orders > 0`
- `roas = revenue / spend` nếu `spend > 0`

## Bóc tách tin nhắn

`messages` lấy từ `actions` theo thứ tự ưu tiên (lấy loại đầu tiên có mặt, tránh cộng trùng):

```
onsite_conversion.messaging_conversation_started_7d
onsite_conversion.messaging_first_reply
messaging_conversation_started
messenger_conversations_started
onsite_conversion.total_messaging_connection
```

`cost_per_message = spend / messages` nếu `messages > 0`. Chỉnh danh sách tại
`MESSAGE_ACTION_TYPES` trong `transform.py`.

## Web view (xem nhanh) — `dashboard.html`

Trang HTML tĩnh **chỉ đọc** Google Sheet (qua endpoint gviz của Google) rồi hiển thị
bảng/biểu đồ — không header/footer, không cần token, không ghi gì.

1. Mở Google Sheet → **Chia sẻ** → "Bất kỳ ai có link đều **xem** được".
2. Mở `dashboard.html` trực tiếp bằng trình duyệt (double-click) hoặc serve tĩnh:
   `python -m http.server 8080` rồi vào `http://localhost:8080/dashboard.html`.

Tính năng: chuyển 6 tab, tìm kiếm, sắp xếp theo cột, lọc theo kỳ (hôm nay/hôm qua/
7 ngày/tháng này), thẻ tổng (chi tiêu, tin nhắn, chi phí/tin nhắn…), xem JSON `actions`
đầy đủ. `SHEET_ID` cấu hình ở đầu phần `<script>` trong file.

## Ghi chú kỹ thuật

- `actions` và `cost_per_action_type` được lưu nguyên dạng **JSON string** trong cột
  `actions_json` / `cost_per_action_type_json` để dashboard parse lại.
- ID (account/campaign/adset/ad, 15–17 số) ghi dạng **text RAW** nên không bị làm tròn.
- Retry tự động khi rate limit (code 4/17/32/341/613) hoặc HTTP 429/5xx với backoff lũy thừa.
- Đã xử lý phân trang (`paging.next`) cho mọi endpoint.
