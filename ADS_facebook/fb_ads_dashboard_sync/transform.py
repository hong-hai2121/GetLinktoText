"""
Biến đổi dữ liệu thô từ Meta API → dòng đã chuẩn hóa cho từng sheet.

Gồm:
    parse_actions()             actions[] → dict {action_type: value}
    calculate_message_metrics() Bóc số tin nhắn + cost_per_message từ actions
    build_campaign_row() / build_adset_row() / build_ad_row()
                                Ghép insight + metadata thực thể → dict theo cột sheet
"""

import json
from datetime import datetime, timezone

# ── Loại action liên quan tới TIN NHẮN, theo thứ tự ưu tiên ─────────────────────
# Lấy giá trị của action_type ĐẦU TIÊN có mặt → tránh cộng trùng (các loại này
# thường chồng lấn nhau, vd started_7d ⊂ total_messaging_connection).
MESSAGE_ACTION_TYPES = [
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.messaging_first_reply",
    "messaging_conversation_started",
    "messenger_conversations_started",
    "onsite_conversion.total_messaging_connection",
]

# Loại action cho post engagement (bóc từ actions).
POST_REACTION_TYPES = ["post_reaction"]
POST_COMMENT_TYPES = ["comment", "post_comment"]
POST_SHARE_TYPES = ["post"]  # "post" trong actions = lượt chia sẻ bài viết


def safe_float(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def parse_actions(actions: list | None) -> dict[str, float]:
    """actions[] = [{action_type, value}, ...] → {action_type: tổng value}.

    Cộng dồn nếu một action_type xuất hiện nhiều lần. Trả dict rỗng nếu không có.
    """
    result: dict[str, float] = {}
    for item in actions or []:
        atype = item.get("action_type")
        if not atype:
            continue
        result[atype] = result.get(atype, 0.0) + safe_float(item.get("value"))
    return result


def _first_present(action_map: dict[str, float], types: list[str]) -> float:
    """Giá trị của action_type ĐẦU TIÊN trong `types` có mặt trong action_map."""
    for t in types:
        if t in action_map:
            return action_map[t]
    return 0.0


def _sum_types(action_map: dict[str, float], types: list[str]) -> float:
    return sum(action_map.get(t, 0.0) for t in types)


def calculate_message_metrics(actions: list | None, spend: float) -> tuple[float, float]:
    """Trả (messages, cost_per_message).

    messages       = số tin nhắn lấy từ actions theo MESSAGE_ACTION_TYPES (ưu tiên).
    cost_per_message = spend / messages nếu messages > 0, ngược lại 0.
    """
    action_map = parse_actions(actions)
    messages = _first_present(action_map, MESSAGE_ACTION_TYPES)
    cost_per_message = spend / messages if messages > 0 else 0.0
    return messages, cost_per_message


def action_total(arr: list | None) -> float:
    """Tổng value của một mảng action (vd video_play_actions, video_p25_...)."""
    return sum(safe_float(it.get("value")) for it in (arr or []))


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _budget(v) -> str:
    """daily/lifetime_budget của FB là chuỗi đơn vị nhỏ nhất; giữ nguyên, "" nếu trống."""
    if v in (None, "", "0", 0):
        return ""
    return str(v)


def _derived_rates(insight: dict, spend: float, impr: float, clicks: float,
                   reach: float) -> dict:
    """ctr/cpc/cpm/frequency: ưu tiên giá trị FB trả, thiếu thì tự tính lại."""
    ctr = safe_float(insight.get("ctr")) or (clicks / impr * 100 if impr > 0 else 0.0)
    cpc = safe_float(insight.get("cpc")) or (spend / clicks if clicks > 0 else 0.0)
    cpm = safe_float(insight.get("cpm")) or (spend / impr * 1000 if impr > 0 else 0.0)
    freq = safe_float(insight.get("frequency")) or (impr / reach if reach > 0 else 0.0)
    return {"ctr": ctr, "cpc": cpc, "cpm": cpm, "frequency": freq}


def _base_metrics(insight: dict) -> dict:
    """Phần metric dùng chung cho cả 3 level."""
    spend = safe_float(insight.get("spend"))
    impr = safe_float(insight.get("impressions"))
    clicks = safe_float(insight.get("clicks"))
    reach = safe_float(insight.get("reach"))
    actions = insight.get("actions") or []
    messages, cost_per_message = calculate_message_metrics(actions, spend)
    rates = _derived_rates(insight, spend, impr, clicks, reach)
    return {
        "spend": spend,
        "impressions": impr,
        "reach": reach,
        "frequency": round(rates["frequency"], 4),
        "clicks": clicks,
        "inline_link_clicks": safe_float(insight.get("inline_link_clicks")),
        "ctr": round(rates["ctr"], 4),
        "cpc": round(rates["cpc"], 2),
        "cpm": round(rates["cpm"], 2),
        "messages": int(messages),
        "cost_per_message": round(cost_per_message, 2) if cost_per_message else "",
        "actions_json": json.dumps(actions, ensure_ascii=False) if actions else "",
        "cost_per_action_type_json": json.dumps(
            insight.get("cost_per_action_type") or [], ensure_ascii=False
        ) if insight.get("cost_per_action_type") else "",
    }


# ── Row builders ───────────────────────────────────────────────────────────────

def build_campaign_row(insight: dict, account_id: str, account_name: str,
                       camp_meta: dict) -> dict:
    m = _base_metrics(insight)
    return {
        "date_start": insight.get("date_start", ""),
        "date_stop": insight.get("date_stop", ""),
        "account_id": account_id,
        "account_name": account_name,
        "campaign_id": insight.get("campaign_id", ""),
        "campaign_name": insight.get("campaign_name", ""),
        "campaign_status": camp_meta.get("status", ""),
        "campaign_effective_status": camp_meta.get("effective_status", ""),
        "objective": insight.get("objective", "") or camp_meta.get("objective", ""),
        "daily_budget": _budget(camp_meta.get("daily_budget")),
        "lifetime_budget": _budget(camp_meta.get("lifetime_budget")),
        # khóa upsert raw cần adset_id/ad_id rỗng ở cấp campaign
        "adset_id": "",
        "ad_id": "",
        "updated_at": _now_iso(),
        **m,
    }


def build_adset_row(insight: dict, account_id: str, account_name: str,
                    adset_meta: dict) -> dict:
    m = _base_metrics(insight)
    return {
        "date_start": insight.get("date_start", ""),
        "date_stop": insight.get("date_stop", ""),
        "account_id": account_id,
        "account_name": account_name,
        "campaign_id": insight.get("campaign_id", ""),
        "campaign_name": insight.get("campaign_name", ""),
        "adset_id": insight.get("adset_id", ""),
        "adset_name": insight.get("adset_name", ""),
        "adset_status": adset_meta.get("status", ""),
        "adset_effective_status": adset_meta.get("effective_status", ""),
        "daily_budget": _budget(adset_meta.get("daily_budget")),
        "lifetime_budget": _budget(adset_meta.get("lifetime_budget")),
        "ad_id": "",
        "updated_at": _now_iso(),
        **m,
    }


def build_ad_row(insight: dict, account_id: str, account_name: str,
                 ad_meta: dict) -> dict:
    m = _base_metrics(insight)
    action_map = parse_actions(insight.get("actions"))
    return {
        "date_start": insight.get("date_start", ""),
        "date_stop": insight.get("date_stop", ""),
        "account_id": account_id,
        "account_name": account_name,
        "campaign_id": insight.get("campaign_id", ""),
        "campaign_name": insight.get("campaign_name", ""),
        "adset_id": insight.get("adset_id", ""),
        "adset_name": insight.get("adset_name", ""),
        "ad_id": insight.get("ad_id", ""),
        "ad_name": insight.get("ad_name", ""),
        "ad_status": ad_meta.get("status", ""),
        "ad_effective_status": ad_meta.get("effective_status", ""),
        "video_play_actions": action_total(insight.get("video_play_actions")),
        "video_thruplay_watched_actions": action_total(
            insight.get("video_thruplay_watched_actions")),
        "video_p25_watched_actions": action_total(insight.get("video_p25_watched_actions")),
        "video_p50_watched_actions": action_total(insight.get("video_p50_watched_actions")),
        "video_p75_watched_actions": action_total(insight.get("video_p75_watched_actions")),
        "video_p95_watched_actions": action_total(insight.get("video_p95_watched_actions")),
        "video_avg_time_watched_actions": action_total(
            insight.get("video_avg_time_watched_actions")),
        "post_reactions": _sum_types(action_map, POST_REACTION_TYPES),
        "post_comments": _sum_types(action_map, POST_COMMENT_TYPES),
        "post_shares": _sum_types(action_map, POST_SHARE_TYPES),
        "updated_at": _now_iso(),
        **m,
    }
