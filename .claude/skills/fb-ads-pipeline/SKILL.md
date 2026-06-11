---
name: fb-ads-pipeline
description: Orchestrator điều phối team sửa đổi pipeline FB Ads (ADS_facebook — get_campaigns, get_details, tong_hop, hub). Dùng cho MỌI yêu cầu thay đổi pipeline: thêm/đổi/bỏ cột schema, thêm metric hay action_type, sửa fetcher Graph API, đổi cách ghi Google Sheets, sửa bug pipeline. Cũng kích hoạt khi yêu cầu "sửa tiếp", "làm lại", "cập nhật", "bổ sung" cho pipeline, hoặc "chỉ sửa phần X của pipeline". Câu hỏi đơn thuần (giải thích code) có thể trả lời trực tiếp không cần team.
---

# Orchestrator — Pipeline FB Ads

Điều phối 3 agent (generate-validate) để sửa đổi pipeline an toàn. Mục tiêu tối thượng:
**không vi phạm bất biến gây mất dữ liệu trên Google Sheets của người dùng.**

Người dùng là chuyên gia quảng cáo/y tế, không phải kỹ sư phần mềm — giao tiếp tiếng Việt
rõ ràng, giải thích khi dùng thuật ngữ.

## Đội hình & chế độ
**Chế độ: Agent Team** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` đã bật trong settings).
| Agent | Vai trò | Base type | Skill chính |
|-------|---------|-----------|-------------|
| `pipeline-developer` | Sửa code | general-purpose | `fb-pipeline-edit` |
| `pipeline-qa` | Kiểm tra bất biến | general-purpose | `fb-pipeline-verify` |
| `graph-api-researcher` | Tra cứu API/gspread | Explore | `fb-graph-gspread-ref` |

Mọi `Agent`/team call dùng `model: "opus"`.

## Phase 0: Xác định bối cảnh (BẮT BUỘC trước)
1. Xác định **biến thể** nào: `fb_ads_accounts` hay `fb_ads_tsAnhDuc`? Nếu yêu cầu mơ hồ, hỏi.
2. Phân loại yêu cầu:
   - **Mới:** thay đổi lần đầu → chạy full workflow.
   - **Sửa tiếp/bổ sung:** đọc thay đổi trước, chỉ gọi developer sửa phần liên quan.
   - **Câu hỏi giải thích:** trả lời trực tiếp, không lập team.

## Phase 1: Lập team & giao việc
1. `TeamCreate` với 3 thành viên (hoặc 2 nếu không cần researcher).
2. `TaskCreate` các việc với phụ thuộc:
   - Research (nếu cần field API/gspread) → Develop → QA.
3. Giao yêu cầu cụ thể cho `pipeline-developer`.

## Phase 2: Vòng generate-validate
1. `pipeline-developer` sửa code (đọc `fb-pipeline-edit` trước).
2. Cần kiến thức API/gspread → developer hỏi `graph-api-researcher` qua SendMessage.
3. `pipeline-qa` chạy `fb-pipeline-verify` (script + so sánh chéo) sau mỗi module.
4. QA FAIL → gửi developer sửa → QA lại. Lặp đến PASS.

## Phase 3: Tổng hợp & báo cáo
1. Thu kết quả, xác nhận py_compile + verify_pipeline.py PASS.
2. Báo người dùng: đã đổi gì, file nào, bất biến đã kiểm.
3. Dọn team.

## Dữ liệu giữa agent
- **Tin nhắn:** SendMessage cho hỏi/đáp nhanh, báo lỗi QA.
- **Task:** TaskCreate/Update theo dõi tiến độ + phụ thuộc.
- **File:** chính code dự án (sửa trực tiếp). Không cần `_workspace/` vì thay đổi nằm trong repo.

## Xử lý lỗi
- Agent fail → thử lại 1 lần; vẫn fail → báo người dùng phần đó chưa xong, không giả vờ hoàn thành.
- QA phát hiện vi phạm bất biến → KHÔNG bỏ qua; phải sửa trước khi báo done. Đây là rào cản cứng.
- Dữ liệu mâu thuẫn (memory vs code thật) → tin code thật, ghi chú cho người dùng.

## Test scenario
**Luồng bình thường:** "Thêm cột CPM vào pipeline fb_ads_tsAnhDuc" → Phase 0 xác định biến thể →
developer thêm vào `COLUMNS` (get_campaigns) → QA chạy verify_pipeline.py + so sánh chéo
build_detail_row/tong_hop → PASS → báo cáo.
**Luồng lỗi:** developer lỡ thêm `.clear()` vào get_details → QA FAIL bất biến #2 → gửi developer →
đổi sang insert_rows → QA PASS.

## Sau khi xong
Hỏi người dùng có muốn cải thiện gì về kết quả hay cách team làm việc. Nếu cùng loại phản hồi
lặp ≥2 lần → đề xuất cập nhật agent/skill (xem skill `harness` để tiến hóa).
