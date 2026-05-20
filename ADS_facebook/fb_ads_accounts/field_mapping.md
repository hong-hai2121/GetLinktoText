# Field Mapping — FB Ads Pipeline

Tài liệu này ghi rõ **mỗi cột trong Google Sheet lấy dữ liệu từ thuộc tính JSON nào**,
API endpoint nào, và cách tính nếu là giá trị dẫn xuất.

---

## 1. Tab tài khoản — cây Campaign / Adset / Ad (28 cột A–AB)

| Cột | Tên | Cấp hiển thị | JSON property | API endpoint | Ghi chú |
|-----|-----|--------------|---------------|--------------|---------|
| A | Chọn Lấy Chi Tiết | Campaign | _(không có)_ | — | Người dùng tự đánh TRUE/FALSE |
| B | Cấp | Tất cả | _(không có)_ | — | Script tự gán: "Campaign" / "Adset" / "Ad" |
| C | Campaign ID | Tất cả | `campaigns[].id` | `/{account_id}/campaigns` | |
| D | Campaign Name | Tất cả | `campaigns[].name` | `/{account_id}/campaigns` | |
| E | Adset ID | Adset, Ad | `adsets[].id` | `/{campaign_id}/adsets` | Trống ở dòng Campaign |
| F | Adset Name | Adset, Ad | `adsets[].name` | `/{campaign_id}/adsets` | Trống ở dòng Campaign |
| G | Ad ID | Ad | `ads[].id` | `/{adset_id}/ads` | Trống ở Campaign / Adset |
| H | Ad Name | Ad | `ads[].name` | `/{adset_id}/ads` | Trống ở Campaign / Adset |
| I | Trạng Thái | Tất cả | `[].status` | tương ứng mỗi cấp | Map sang tiếng Việt qua `STATUS_MAP` |
| J | Spend Tháng Này | Tất cả | `insights[].spend` | `/{account_id}/insights` | Đơn vị gốc (VND không chia 100) |
| K | Lượt Hiển Thị | Tất cả | `insights[].impressions` | `/{account_id}/insights` | |
| L | Lượt Click | Tất cả | `insights[].clicks` | `/{account_id}/insights` | |
| M | CTR (%) | Tất cả | `insights[].ctr` | `/{account_id}/insights` | Fallback: `clicks / impressions × 100` |
| N | CPC | Tất cả | `insights[].cpc` | `/{account_id}/insights` | Fallback: `spend / clicks` |
| O | CPM | Tất cả | `insights[].cpm` | `/{account_id}/insights` | Fallback: `spend / impressions × 1000` |
| P | Tiếp Cận | Tất cả | `insights[].reach` | `/{account_id}/insights` | |
| Q | Tần Suất | Tất cả | `insights[].frequency` | `/{account_id}/insights` | Fallback: `impressions / reach` |
| R | Số Inbox | Tất cả | `insights[].actions[].value` | `/{account_id}/insights` | Tổng `value` của các `action_type` trong `INBOX_TYPES` |
| S | CPI | Tất cả | _(tính toán)_ | — | `spend / inbox` |
| T | Số Lead | Tất cả | `insights[].actions[].value` | `/{account_id}/insights` | Tổng `value` của các `action_type` trong `LEAD_TYPES` |
| U | CPL | Tất cả | _(tính toán)_ | — | `spend / leads` |
| V | Số Đơn Hàng | Tất cả | `insights[].actions[].value` | `/{account_id}/insights` | Tổng `value` của các `action_type` trong `PURCHASE_TYPES` |
| W | CPS | Tất cả | _(tính toán)_ | — | `spend / purchases` |
| X | Doanh Thu | Tất cả | `insights[].action_values[].value` | `/{account_id}/insights` | Tổng `value` của `PURCHASE_TYPES` từ `action_values` |
| Y | ROAS | Tất cả | `insights[].purchase_roas[].value` | `/{account_id}/insights` | Fallback: `revenue / spend` |
| Z | Kết Quả | Tất cả | `insights[].cost_per_action_type[].value` | `/{account_id}/insights` | Count của action_type đầu tiên có cost > 0 theo thứ tự `PURCHASE → LEAD → INBOX → engagement` |
| AA | Chi Phí / Kết Quả | Tất cả | `insights[].cost_per_action_type[].value` | `/{account_id}/insights` | Lấy `value` của cùng action_type xác định Kết Quả — API đã tính sẵn |
| AB | Cập Nhật Lúc | Tất cả | _(không có)_ | — | Timestamp lúc script chạy |

### Metrics cấp Adset — cách tổng hợp

Không có API call riêng cho Adset insights.
Adset metrics được **tổng hợp từ Ad-level insights** trong Python:

- Cộng trực tiếp: `spend`, `impressions`, `clicks`, `reach`, `inbox`, `leads`, `purchases`, `revenue`, `ket_qua`
- Tính lại từ tổng: `ctr`, `cpc`, `cpm`, `frequency`, `cpi`, `cpl`, `cps`, `roas`, `cpkq`

---

## 2. Tab Creative — `{Tên TK} - Creative` (6 cột A–F)

| Cột | Tên | JSON property | API endpoint | Ghi chú |
|-----|-----|---------------|--------------|---------|
| A | Creative ID | `ads[].creative.id` | `/{adset_id}/ads` | |
| B | Ad ID | `ads[].id` | `/{adset_id}/ads` | |
| C | Ad Name | `ads[].name` | `/{adset_id}/ads` | |
| D | Nội Dung Quảng Cáo | `ads[].creative.body` | `/{adset_id}/ads` | Nội dung text của quảng cáo |
| E | Tiêu Đề | `ads[].creative.title` | `/{adset_id}/ads` | |
| F | Ghi Chú | _(không có)_ | — | Người dùng tự điền, giữ nguyên khi refresh |

---

## 3. Trường được request nhưng KHÔNG có trong JSON response

Các field sau được khai báo trong `fields` của API call nhưng thực tế **không trả về**
(tùy loại creative / cài đặt tài khoản):

| Field request | Thuộc tính | Lý do không có |
|--------------|------------|----------------|
| `creative{object_story_spec}` | page_id, link_data, video_data | Không trả về cho creative dạng post thông thường |
| `creative{link_url}` | Link đích | Chỉ có trong link ad — không có với post ad |
| `object_story_spec.link_data.description` | Mô Tả | Phụ thuộc `object_story_spec` |
| `object_story_spec.link_data.call_to_action.type` | CTA | Phụ thuộc `object_story_spec` |

> **Page ID** và **Post ID** vẫn có thể trích xuất từ `effective_object_story_id`
> (format: `{page_id}_{post_id}`) — hiện tại không đưa vào sheet Creative.

---

## 4. INBOX_TYPES / LEAD_TYPES / PURCHASE_TYPES

```
INBOX_TYPES:
  onsite_conversion.messaging_conversation_started_7d
  onsite_conversion.messaging_first_reply
  messaging_new_connections
  onsite_conversion.messaging_user_depth_2_message_send

LEAD_TYPES:
  lead
  onsite_conversion.lead_grouped
  offsite_conversion.fb_pixel_lead

PURCHASE_TYPES:
  purchase
  offsite_conversion.fb_pixel_purchase
  omni_purchase
  onsite_conversion.purchase
```

Thứ tự ưu tiên xác định "Kết Quả": `PURCHASE → LEAD → INBOX → post_engagement → page_engagement → link_click → video_view → app_install`
