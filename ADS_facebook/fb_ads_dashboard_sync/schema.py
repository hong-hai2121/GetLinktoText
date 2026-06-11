"""
Định nghĩa tập trung TÊN SHEET + THỨ TỰ CỘT của từng sheet, và khóa upsert.

Đây là "nguồn chân lý duy nhất": đổi thứ tự / thêm cột chỉ sửa ở đây, mọi nơi
khác (row builder, upsert, dashboard) tự bám theo tên cột nên không lệch.
"""

# ── Tên các sheet (tab) trong Google Sheet ────────────────────────────────────
SHEET_RAW_CAMPAIGN = "raw_campaign_daily"
SHEET_RAW_ADSET = "raw_adset_daily"
SHEET_RAW_AD = "raw_ad_daily"
SHEET_DASHBOARD_DAILY = "dashboard_daily"
SHEET_DASHBOARD_LIFETIME = "dashboard_lifetime"
SHEET_SYNC_LOG = "sync_log"

# ── Khóa upsert chung cho các sheet raw_* và dashboard_daily ───────────────────
# Dòng đã tồn tại (trùng khóa) → cập nhật; chưa có → thêm mới.
KEY_RAW = ["date_start", "account_id", "campaign_id", "adset_id", "ad_id"]
KEY_DASHBOARD_DAILY = ["date", "account_id", "campaign_id"]
KEY_DASHBOARD_LIFETIME = ["account_id", "campaign_id"]

# ── Cột của từng sheet (đúng thứ tự yêu cầu) ───────────────────────────────────
COLS_RAW_CAMPAIGN = [
    "date_start", "date_stop", "account_id", "account_name",
    "campaign_id", "campaign_name", "campaign_status", "campaign_effective_status",
    "objective", "daily_budget", "lifetime_budget",
    "spend", "impressions", "reach", "frequency", "clicks", "inline_link_clicks",
    "ctr", "cpc", "cpm", "messages", "cost_per_message",
    "actions_json", "cost_per_action_type_json", "updated_at",
]

COLS_RAW_ADSET = [
    "date_start", "date_stop", "account_id", "account_name",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name", "adset_status", "adset_effective_status",
    "daily_budget", "lifetime_budget",
    "spend", "impressions", "reach", "frequency", "clicks", "inline_link_clicks",
    "ctr", "cpc", "cpm", "messages", "cost_per_message",
    "actions_json", "cost_per_action_type_json", "updated_at",
]

COLS_RAW_AD = [
    "date_start", "date_stop", "account_id", "account_name",
    "campaign_id", "campaign_name", "adset_id", "adset_name",
    "ad_id", "ad_name", "ad_status", "ad_effective_status",
    "spend", "impressions", "reach", "frequency", "clicks", "inline_link_clicks",
    "ctr", "cpc", "cpm", "messages", "cost_per_message",
    "video_play_actions", "video_thruplay_watched_actions",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p95_watched_actions",
    "video_avg_time_watched_actions",
    "post_reactions", "post_comments", "post_shares",
    "actions_json", "cost_per_action_type_json", "updated_at",
]

COLS_DASHBOARD_DAILY = [
    "date", "account_id", "account_name", "campaign_id", "campaign_name",
    "spend", "impressions", "reach", "clicks", "ctr", "cpc", "cpm",
    "messages", "cost_per_message",
    "orders", "cost_per_order", "revenue", "roas", "note", "updated_at",
]

COLS_DASHBOARD_LIFETIME = [
    "account_id", "account_name", "campaign_id", "campaign_name",
    "campaign_status", "campaign_effective_status",
    "total_spend", "total_impressions", "total_reach", "total_clicks",
    "avg_ctr", "avg_cpc", "avg_cpm", "total_messages", "avg_cost_per_message",
    "total_orders", "avg_cost_per_order", "total_revenue", "roas", "updated_at",
]

COLS_SYNC_LOG = [
    "sync_time", "account_id", "level", "date_preset_or_range",
    "status", "rows_fetched", "rows_inserted", "rows_updated", "error_message",
]

# Các cột do người dùng / CRM nhập tay — upsert KHÔNG ghi đè nếu đã có giá trị.
PRESERVE_DASHBOARD_DAILY = ["orders", "cost_per_order", "revenue", "roas", "note"]
PRESERVE_DASHBOARD_LIFETIME = [
    "total_orders", "avg_cost_per_order", "total_revenue", "roas"
]
