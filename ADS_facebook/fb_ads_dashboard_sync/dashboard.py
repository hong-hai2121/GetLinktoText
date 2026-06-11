"""
Dựng dữ liệu tổng hợp cho 2 sheet dashboard.

    build_dashboard_daily()     Tổng hợp theo (ngày × campaign) từ raw campaign daily.
    build_dashboard_lifetime()  Tổng hợp toàn thời gian theo campaign (level=campaign,
                                date_preset=maximum → mỗi campaign đã là 1 dòng).

orders / revenue để TRỐNG (nhập tay hoặc nối CRM sau). cost_per_order, roas chỉ
tính khi có orders/revenue — ở bước sync để trống, người dùng nhập orders/revenue
thì có thể đặt công thức hoặc tính lại sau.
"""

from datetime import datetime, timezone

from transform import safe_float, _base_metrics


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def build_dashboard_daily(campaign_rows: list[dict]) -> list[dict]:
    """Từ các dòng raw_campaign_daily (đã chuẩn hóa) → dòng dashboard_daily.

    Mỗi raw campaign daily đã là 1 (ngày × campaign) nên ánh xạ trực tiếp; nếu có
    trùng khóa (do nhiều khoảng thời gian) thì cộng dồn KHÔNG cần — upsert + dedup
    đã giữ bản mới nhất. Ở đây ta chỉ map cột.
    """
    out = []
    for r in campaign_rows:
        spend = safe_float(r.get("spend"))
        messages = safe_float(r.get("messages"))
        out.append({
            "date": r.get("date_start", ""),
            "account_id": r.get("account_id", ""),
            "account_name": r.get("account_name", ""),
            "campaign_id": r.get("campaign_id", ""),
            "campaign_name": r.get("campaign_name", ""),
            "spend": spend,
            "impressions": r.get("impressions", ""),
            "reach": r.get("reach", ""),
            "clicks": r.get("clicks", ""),
            "ctr": r.get("ctr", ""),
            "cpc": r.get("cpc", ""),
            "cpm": r.get("cpm", ""),
            "messages": int(messages) if messages else "",
            "cost_per_message": r.get("cost_per_message", ""),
            "orders": "",          # nhập tay / nối CRM
            "cost_per_order": "",  # = spend / orders nếu orders > 0
            "revenue": "",         # nhập tay / nối CRM
            "roas": "",            # = revenue / spend nếu spend > 0
            "note": "",
            "updated_at": _now_iso(),
        })
    return out


def build_dashboard_lifetime(lifetime_insights: list[dict],
                             account_id: str, account_name: str,
                             camp_meta: dict[str, dict]) -> list[dict]:
    """Từ insights level=campaign date_preset=maximum → dòng dashboard_lifetime.

    Mỗi insight là tổng toàn thời gian của 1 campaign.
    """
    out = []
    for ins in lifetime_insights:
        cid = ins.get("campaign_id", "")
        meta = camp_meta.get(cid, {})
        m = _base_metrics(ins)  # đã tính ctr/cpc/cpm/messages/cost_per_message
        spend = m["spend"]
        messages = m["messages"]
        out.append({
            "account_id": account_id,
            "account_name": account_name,
            "campaign_id": cid,
            "campaign_name": ins.get("campaign_name", ""),
            "campaign_status": meta.get("status", ""),
            "campaign_effective_status": meta.get("effective_status", ""),
            "total_spend": round(spend, 2),
            "total_impressions": m["impressions"],
            "total_reach": m["reach"],
            "total_clicks": m["clicks"],
            "avg_ctr": m["ctr"],
            "avg_cpc": m["cpc"],
            "avg_cpm": m["cpm"],
            "total_messages": messages,
            "avg_cost_per_message": m["cost_per_message"],
            "total_orders": "",          # nhập tay / nối CRM
            "avg_cost_per_order": "",     # = total_spend / total_orders
            "total_revenue": "",          # nhập tay / nối CRM
            "roas": "",                   # = total_revenue / total_spend
            "updated_at": _now_iso(),
        })
    return out
