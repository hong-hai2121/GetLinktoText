"""
Phase 2 – Lấy chi tiết Adset / Ad / Creative + Insights cấp Ad
         cho các Campaign đã được đánh TRUE ở cột "Chọn Lấy Chi Tiết".

Chạy SAU khi đã chạy get_campaigns.py và đánh dấu campaign muốn xem chi tiết.
Script sẽ mở rộng các campaign được chọn thành cây Campaign → Adset → Ad
rồi ghi đè lại toàn bộ tab tài khoản trong Google Sheets.
"""

import requests
from datetime import datetime

from get_campaigns import (
    # Constants & config
    BASE_DIR, FB_API_VERSION, ACCESS_TOKEN, STATUS_MAP, _INSIGHTS_FIELDS,
    _date_params,
    # Google Sheets
    connect_spreadsheet, get_selected_accounts, read_detail_selections,
    get_or_create_worksheet, sanitize_sheet_name, write_to_sheet,
    # Facebook API
    paginate, fetch_campaigns, fetch_insights_campaign_level,
    # Metrics
    parse_insight_metrics, aggregate_metrics,
    # Formatting
    _insights_cols, _campaign_row,
    # Utilities
    save_json,
)


# ── Facebook Graph API — Adset / Ad ───────────────────────────────────────────

def fetch_adsets(campaign_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{campaign_id}/adsets"
    params = {
        "fields":       "id,name,status",
        "access_token": ACCESS_TOKEN,
        "limit":        100,
    }
    return paginate(url, params)


def fetch_ads(adset_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{adset_id}/ads"
    params = {
        "fields": (
            "id,name,status,"
            "creative{id,name,object_story_spec,body,title,"
            "link_url,thumbnail_url,effective_object_story_id}"
        ),
        "access_token": ACCESS_TOKEN,
        "limit":        100,
    }
    return paginate(url, params)


def fetch_insights_ad_level(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{account_id}/insights"
    params = {
        "level":        "ad",
        **_date_params(),
        "fields":       f"ad_id,adset_id,campaign_id,{_INSIGHTS_FIELDS}",
        "access_token": ACCESS_TOKEN,
        "limit":        500,
    }
    return paginate(url, params)


# ── Creative extraction ────────────────────────────────────────────────────────

def extract_creative_info(creative: dict) -> dict:
    if not creative:
        return {}

    oss        = creative.get("object_story_spec") or {}
    link_data  = oss.get("link_data")  or {}
    video_data = oss.get("video_data") or {}

    page_id = oss.get("page_id", "")
    post_id = ""
    effective_id = creative.get("effective_object_story_id", "")
    if effective_id and "_" in effective_id:
        parts = effective_id.split("_", 1)
        if not page_id:
            page_id = parts[0]
        post_id = parts[1]

    body = (
        creative.get("body")
        or link_data.get("message")
        or video_data.get("message")
        or ""
    )
    title = (
        creative.get("title")
        or link_data.get("name")
        or video_data.get("title")
        or creative.get("name", "")
    )
    description = link_data.get("description") or video_data.get("description") or ""
    link        = creative.get("link_url") or link_data.get("link") or ""
    cta_obj     = link_data.get("call_to_action") or video_data.get("call_to_action") or {}
    cta         = cta_obj.get("type", "") if cta_obj else ""

    return {
        "creative_id":   creative.get("id", ""),
        "page_id":       page_id,
        "post_id":       post_id,
        "body":          body,
        "title":         title,
        "description":   description,
        "link":          link,
        "cta":           cta,
        "thumbnail_url": creative.get("thumbnail_url", ""),
    }


# ── Row builders ───────────────────────────────────────────────────────────────

def _adset_row(camp_id, camp_name, adset, m: dict, currency: str, now_str: str) -> list:
    """Dòng Adset — tổng hợp từ Ad — 37 cột."""
    return [
        "",                                                                          # A
        "Adset",                                                                     # B
        camp_id,                                                                     # C
        camp_name,                                                                   # D
        adset.get("id",   ""),                                                       # E
        adset.get("name", ""),                                                       # F
        "", "",                                                                      # G H  Ad
        "", "", "", "", "", "", "", "", "",                                          # I..Q Creative
        STATUS_MAP.get(adset.get("status", ""), adset.get("status", "")),            # R
    ] + _insights_cols(m, currency) + [now_str]


def _ad_row(camp_id, camp_name, adset_id, adset_name,
            ad, m: dict, currency: str, now_str: str) -> list:
    """Dòng Ad — đầy đủ creative + insights — 37 cột."""
    c = extract_creative_info(ad.get("creative") or {})
    return [
        "",                                                                          # A
        "Ad",                                                                        # B
        camp_id,                                                                     # C
        camp_name,                                                                   # D
        adset_id,                                                                    # E
        adset_name,                                                                  # F
        ad.get("id",   ""),                                                          # G
        ad.get("name", ""),                                                          # H
        c.get("creative_id",   ""),                                                  # I
        c.get("page_id",       ""),                                                  # J
        c.get("post_id",       ""),                                                  # K
        c.get("body",          ""),                                                  # L
        c.get("title",         ""),                                                  # M
        c.get("description",   ""),                                                  # N
        c.get("link",          ""),                                                  # O
        c.get("cta",           ""),                                                  # P
        c.get("thumbnail_url", ""),                                                  # Q
        STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),                  # R
    ] + _insights_cols(m, currency) + [now_str]


# ── Tree builder ───────────────────────────────────────────────────────────────

def build_rows(
    campaigns:        list[dict],
    camp_insights_map: dict,
    adset_data_map:   dict,
    ad_insights_map:  dict,
    detail_selections: dict,
    currency:         str,
    now_str:          str,
) -> list[list]:
    """Xây toàn bộ danh sách dòng theo cây Campaign → Adset → Ad."""
    status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}
    sorted_camps = sorted(
        campaigns,
        key=lambda c: (status_order.get(c.get("status", ""), 9), c.get("name", "")),
    )

    rows = []
    for camp in sorted_camps:
        camp_id   = camp.get("id",   "")
        camp_name = camp.get("name", "")
        is_selected = detail_selections.get(camp_id, False)

        camp_m = parse_insight_metrics(camp_insights_map.get(camp_id, {}))
        rows.append(_campaign_row(
            camp_id, camp_name, is_selected,
            camp_m, camp.get("status", ""), currency, now_str,
        ))

        if not is_selected:
            continue

        adsets = adset_data_map.get(camp_id, [])
        sorted_adsets = sorted(
            adsets,
            key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
        )

        for adset in sorted_adsets:
            adset_id   = adset.get("id",   "")
            adset_name = adset.get("name", "")
            ads        = adset.get("_ads", [])
            sorted_ads = sorted(
                ads,
                key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
            )

            # Tổng hợp metrics Adset từ các Ad bên dưới
            ad_metrics_list = [
                parse_insight_metrics(ad_insights_map.get(ad.get("id", ""), {}))
                for ad in sorted_ads
            ]
            adset_m = aggregate_metrics(ad_metrics_list) if ad_metrics_list else parse_insight_metrics({})

            rows.append(_adset_row(camp_id, camp_name, adset, adset_m, currency, now_str))

            for ad, ad_m in zip(sorted_ads, ad_metrics_list):
                rows.append(_ad_row(
                    camp_id, camp_name, adset_id, adset_name,
                    ad, ad_m, currency, now_str,
                ))

    return rows


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    month_label = datetime.now().strftime("%m/%Y")
    print("Kết nối Google Sheets...")
    spreadsheet = connect_spreadsheet()

    print("Đọc danh sách tài khoản được chọn...")
    selected_accounts = get_selected_accounts(spreadsheet)
    if not selected_accounts:
        print("Không có tài khoản nào được chọn. Hãy đánh TRUE vào cột 'Chọn Lấy Camp'.")
        return
    print(f"Tìm thấy {len(selected_accounts)} tài khoản được chọn.")

    dump_adsets:       dict[str, list] = {}
    dump_ads:          dict[str, list] = {}
    dump_insights_ad:  dict[str, list] = {}

    for acc in selected_accounts:
        acc_id   = acc["id"]
        acc_name = acc["name"]
        currency = acc["currency"]
        print(f"\n[{acc_name}] Lấy chi tiết tháng {month_label}...")

        ws = get_or_create_worksheet(spreadsheet, acc_name)

        detail_selections = read_detail_selections(ws)
        selected_camp_ids = {cid for cid, v in detail_selections.items() if v}
        print(f"  → {len(selected_camp_ids)} campaign được chọn lấy chi tiết: "
              f"{selected_camp_ids or '(chưa có)'}")

        if not selected_camp_ids:
            print("  → Bỏ qua (không có campaign nào được chọn lấy chi tiết).")
            continue

        # Cần lại campaign list + campaign insights để vẽ toàn bộ cây
        campaigns     = fetch_campaigns(acc_id)
        camp_insights = fetch_insights_campaign_level(acc_id)
        camp_insights_map = {r["campaign_id"]: r for r in camp_insights if "campaign_id" in r}

        # ── API 3: Insights cấp Ad (toàn bộ tài khoản, lọc sau) ──────────────
        ad_insights = fetch_insights_ad_level(acc_id)
        ad_insights_map = {r["ad_id"]: r for r in ad_insights if "ad_id" in r}
        dump_insights_ad[acc_name] = ad_insights
        print(f"  → {len(ad_insights)} dòng insights ad.")

        # ── API 4+5: Adsets + Ads chỉ cho campaign được chọn ─────────────────
        adset_data_map: dict[str, list] = {}
        raw_adsets: list[dict] = []
        raw_ads:    list[dict] = []
        total_adsets = total_ads = 0

        for camp in campaigns:
            camp_id = camp.get("id", "")
            if camp_id not in selected_camp_ids:
                continue

            adsets = fetch_adsets(camp_id)
            for adset in adsets:
                raw_adsets.append({k: v for k, v in adset.items() if k != "_ads"})
                ads = fetch_ads(adset["id"])
                raw_ads.extend(ads)
                adset["_ads"] = ads
                total_ads += len(ads)
            adset_data_map[camp_id] = adsets
            total_adsets += len(adsets)

        dump_adsets[acc_name] = raw_adsets
        dump_ads[acc_name]    = raw_ads
        print(f"  → {total_adsets} adsets, {total_ads} ads.")

        # Build cây và ghi vào sheet
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        rows = build_rows(
            campaigns, camp_insights_map, adset_data_map,
            ad_insights_map, detail_selections, currency, now_str,
        )
        write_to_sheet(ws, rows)
        print(f"  → Đã ghi {len(rows)} dòng vào tab '{sanitize_sheet_name(acc_name)}'.")

    base_url = f"https://graph.facebook.com/{FB_API_VERSION}"
    print("\nLưu JSON...")
    save_json(dump_adsets, "adsets.json", {
        "endpoint": f"GET {base_url}/{{campaign_id}}/adsets",
        "fields":   "id,name,status",
        "note":     "Adsets của các campaign được chọn lấy chi tiết",
    })
    save_json(dump_ads, "ads.json", {
        "endpoint": f"GET {base_url}/{{adset_id}}/ads",
        "fields": (
            "id,name,status,"
            "creative{id,name,object_story_spec,body,title,"
            "link_url,thumbnail_url,effective_object_story_id}"
        ),
        "note": "Ads kèm creative của các adset được chọn",
    })
    save_json(dump_insights_ad, "insights_ad.json", {
        "endpoint":    f"GET {base_url}/act_{{account_id}}/insights",
        "level":       "ad",
        "date_preset": "this_month",
        "fields":      f"ad_id,adset_id,campaign_id,{_INSIGHTS_FIELDS}",
        "note":        "Insights cấp ad tháng này — dùng cho dòng Ad, tổng hợp Adset",
    })
    print("\nHoàn thành!")


if __name__ == "__main__":
    main()
