# GetLinktoText

## Harness: Pipeline FB Ads

**Mục tiêu:** Sửa đổi pipeline FB Ads (fetch Graph API → ghi Google Sheets) an toàn, không vi phạm bất biến gây mất dữ liệu.

**Trigger:** Mọi yêu cầu thay đổi pipeline trong `ADS_facebook/*` (đổi cột schema, thêm metric/action_type, sửa fetcher, đổi cách ghi Sheets, sửa bug) → dùng skill `fb-ads-pipeline`. Câu hỏi giải thích code có thể trả lời trực tiếp.

**Bất biến cốt lõi (chi tiết trong skill `fb-pipeline-edit`):** COLUMNS là nguồn schema duy nhất · Phase 2 (`get_details.py`) không `clear()` · số tiền ghi `int` · config đọc lúc import → chạy subprocess.

**Variants:** `ADS_facebook/fb_ads_accounts/` và `ADS_facebook/fb_ads_tsAnhDuc/` (cấu trúc chung). Variant chính của user thường là `fb_ads_tsAnhDuc` — xác nhận lại nếu yêu cầu mơ hồ.

**Đội hình (chi tiết ở `.claude/agents/`):** `pipeline-developer` (sửa code) · `pipeline-qa` (kiểm bất biến) · `graph-api-researcher` (tra cứu API/gspread).

**Biến môi trường:** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (đã bật trong `.claude/settings.json`) để dùng Agent Team.

**Lịch sử thay đổi:**

| Ngày | Thay đổi | Đối tượng | Lý do |
|------|----------|-----------|-------|
| 2026-06-11 | Khởi tạo harness | Toàn bộ (3 agent + 4 skill) | - |
