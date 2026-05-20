"""
Phase 2 – Lấy chi tiết Adset / Ad / Creative + Insights cấp Ad
         cho các Campaign đã được đánh TRUE ở cột "Chọn Lấy Chi Tiết".

Chạy SAU khi đã chạy get_campaigns.py và đánh dấu campaign muốn xem chi tiết.
Script CHÈN dòng Adset/Ad vào đúng vị trí trong sheet, KHÔNG xóa dữ liệu
dòng Campaign hiện có (kể cả các cột ngoài cấu trúc script quản lý).
"""

import requests
from datetime import datetime

from get_campaigns import (
    # Constants & config
    BASE_DIR, FB_API_VERSION, ACCESS_TOKEN, STATUS_MAP, _INSIGHTS_FIELDS,
    _date_params,
    # Google Sheets
    col_to_letter, connect_spreadsheet, get_selected_accounts,
    read_detail_selections, get_or_create_worksheet, sanitize_sheet_name,
    # Facebook API
    paginate,
    # Metrics
    parse_insight_metrics, aggregate_metrics,
    # Formatting
    _insights_cols,
    # Utilities
    save_json,
)

# ── Creative sheet ─────────────────────────────────────────────────────────────

CREATIVE_HEADERS = [
    "Creative ID",          # A  – ads[].creative.id
    "Ad ID",                # B  – ads[].id
    "Ad Name",              # C  – ads[].name
    "Trạng Thái",           # D  – ads[].status
    "Campaign ID",          # E  – từ vòng lặp fetch
    "Adset Name",           # F  – từ vòng lặp fetch
    "Page ID",              # G  – effective_object_story_id.split("_")[0]
    "Post ID",              # H  – effective_object_story_id.split("_")[1]
    "Thumbnail URL",        # I  – ads[].creative.thumbnail_url
    "Nội Dung Quảng Cáo",  # J  – ads[].creative.body
    "Tiêu Đề",              # K  – ads[].creative.title
    "Ghi Chú",              # L  – người dùng tự điền, giữ nguyên khi refresh
]


def read_creative_notes(worksheet) -> dict[str, str]:
    """Đọc cột 'Ghi Chú' hiện tại theo Creative ID để giữ lại khi ghi đè."""
    try:
        all_values = worksheet.get_all_values()
    except Exception:
        return {}
    if len(all_values) < 2:
        return {}
    header = all_values[0]
    try:
        id_col   = header.index("Creative ID")
        note_col = header.index("Ghi Chú")
    except ValueError:
        return {}
    notes = {}
    for row in all_values[1:]:
        cid  = row[id_col].strip()   if id_col   < len(row) else ""
        note = row[note_col].strip() if note_col < len(row) else ""
        if cid:
            notes[cid] = note
    return notes


def write_creative_sheet(spreadsheet, acc_name: str, creative_rows: list[list]):
    """Ghi danh sách creative vào tab '{acc_name} - Creative'."""
    title = sanitize_sheet_name(f"{acc_name} - Creative")
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    if title in existing:
        ws = existing[title]
    else:
        ws = spreadsheet.add_worksheet(
            title=title, rows=2000, cols=len(CREATIVE_HEADERS))

    notes = read_creative_notes(ws)

    rows_with_notes = [
        row + [notes.get(row[0], "")]   # row[0] = Creative ID
        for row in creative_rows
    ]

    last_col = col_to_letter(len(CREATIVE_HEADERS))
    ws.update("A1", [CREATIVE_HEADERS])
    last_row = ws.row_count
    if last_row >= 2:
        ws.batch_clear([f"A2:{last_col}{last_row}"])
    if rows_with_notes:
        ws.update("A2", rows_with_notes)
    return title, len(rows_with_notes)


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

def _adset_row(camp_id, adset, m: dict, currency: str, now_str: str) -> list:
    """Dòng Adset — 25 cột. C = Campaign ID (reference), D = Adset Name."""
    return [
        "",                                                                        # A
        "Adset",                                                                   # B
        camp_id,                                                                   # C  Campaign ID
        adset.get("name", ""),                                                     # D  Adset Name
        STATUS_MAP.get(adset.get("status", ""), adset.get("status", "")),          # E
    ] + _insights_cols(m, currency) + ["", now_str]  # X trống + Y


def _ad_row(camp_id, ad, m: dict, currency: str, now_str: str) -> list:
    """Dòng Ad — 25 cột. C = Campaign ID (reference), D = Ad Name."""
    return [
        "",                                                                        # A
        "Ad",                                                                      # B
        camp_id,                                                                   # C  Campaign ID
        ad.get("name", ""),                                                        # D  Ad Name
        STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),                # E
    ] + _insights_cols(m, currency) + ["", now_str]  # X trống + Y


def refresh_adset_ad_rows(worksheet, adset_data_map: dict, ad_insights_map: dict,
                          detail_selections: dict, currency: str, now_str: str):
    """
    Xóa toàn bộ dòng Adset/Ad hiện tại rồi chèn lại đúng vị trí.
    Dòng Campaign giữ nguyên — dữ liệu và mọi cột ngoài script không bị mất.
    Dùng insert_rows() nên các cột phía sau tự dịch chuyển theo đúng hàng.
    """
    all_data = worksheet.get_all_values()
    if len(all_data) < 2:
        return

    header = all_data[0]
    try:
        cap_col     = header.index("Cấp")
        camp_id_col = header.index("Campaign ID")
    except ValueError:
        return

    status_order = {"ACTIVE": 0, "PAUSED": 1, "ARCHIVED": 2, "DELETED": 3}

    # ── Bước 1: Xóa dòng Adset/Ad từ dưới lên (tránh lệch index) ────────────
    to_delete = [
        i + 2  # i=0 → sheet row 2 (bỏ header)
        for i, row in enumerate(all_data[1:])
        if (row[cap_col] if cap_col < len(row) else "") in ("Adset", "Ad")
    ]
    for rn in reversed(to_delete):
        worksheet.delete_rows(rn)

    # ── Bước 2: Đọc lại sau khi xóa ─────────────────────────────────────────
    all_data = worksheet.get_all_values()

    # ── Bước 3: Tìm vị trí Campaign được chọn ────────────────────────────────
    selected_positions = [
        (i + 2, row[camp_id_col] if camp_id_col < len(row) else "")
        for i, row in enumerate(all_data[1:])
        if (row[cap_col] if cap_col < len(row) else "") == "Campaign"
        and detail_selections.get(row[camp_id_col] if camp_id_col < len(row) else "", False)
    ]

    # ── Bước 4: Chèn dòng Adset/Ad từ dưới lên ───────────────────────────────
    inserted_total = 0
    for sheet_row, camp_id in reversed(selected_positions):
        adsets = sorted(
            adset_data_map.get(camp_id, []),
            key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
        )
        new_rows = []
        for adset in adsets:
            ads = sorted(
                adset.get("_ads", []),
                key=lambda a: (status_order.get(a.get("status", ""), 9), a.get("name", "")),
            )
            ad_mets = [
                parse_insight_metrics(ad_insights_map.get(ad.get("id", ""), {}))
                for ad in ads
            ]
            adset_m = aggregate_metrics(ad_mets) if ad_mets else parse_insight_metrics({})
            new_rows.append(_adset_row(camp_id, adset, adset_m, currency, now_str))
            for ad, ad_m in zip(ads, ad_mets):
                new_rows.append(_ad_row(camp_id, ad, ad_m, currency, now_str))

        if new_rows:
            worksheet.insert_rows(new_rows, sheet_row + 1)
            inserted_total += len(new_rows)

    return inserted_total


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

    dump_adsets:      dict[str, list] = {}
    dump_ads:         dict[str, list] = {}
    dump_insights_ad: dict[str, list] = {}

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

        # ── API 1: Insights cấp Ad ───────────────────────────────────────────
        ad_insights = fetch_insights_ad_level(acc_id)
        ad_insights_map = {r["ad_id"]: r for r in ad_insights if "ad_id" in r}
        dump_insights_ad[acc_name] = ad_insights
        print(f"  → {len(ad_insights)} dòng insights ad.")

        # ── API 2+3: Adsets + Ads chỉ cho campaign được chọn ─────────────────
        adset_data_map: dict[str, list] = {}
        raw_adsets: list[dict] = []
        raw_ads:    list[dict] = []
        total_adsets = total_ads = 0

        for camp_id in selected_camp_ids:
            adsets = fetch_adsets(camp_id)
            for adset in adsets:
                raw_adsets.append({k: v for k, v in adset.items() if k != "_ads"})
                ads = fetch_ads(adset["id"])
                for ad in ads:
                    ad["_camp_id"]    = camp_id
                    ad["_adset_name"] = adset.get("name", "")
                raw_ads.extend(ads)
                adset["_ads"] = ads
                total_ads += len(ads)
            adset_data_map[camp_id] = adsets
            total_adsets += len(adsets)

        dump_adsets[acc_name] = raw_adsets
        dump_ads[acc_name]    = raw_ads
        print(f"  → {total_adsets} adsets, {total_ads} ads.")

        # Chèn dòng Adset/Ad vào sheet (Campaign rows giữ nguyên)
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        inserted = refresh_adset_ad_rows(
            ws, adset_data_map, ad_insights_map, detail_selections, currency, now_str,
        )
        print(f"  → Đã chèn {inserted} dòng Adset/Ad vào tab '{sanitize_sheet_name(acc_name)}'.")

        # Ghi sheet Creative riêng
        creative_rows = []
        for ad in raw_ads:
            c = extract_creative_info(ad.get("creative") or {})
            creative_rows.append([
                c.get("creative_id",  ""),                                          # A
                ad.get("id",          ""),                                          # B
                ad.get("name",        ""),                                          # C
                STATUS_MAP.get(ad.get("status", ""), ad.get("status", "")),         # D
                ad.get("_camp_id",    ""),                                          # E
                ad.get("_adset_name", ""),                                          # F
                c.get("page_id",      ""),                                          # G
                c.get("post_id",      ""),                                          # H
                c.get("thumbnail_url",""),                                          # I
                c.get("body",         ""),                                          # J
                c.get("title",        ""),                                          # K
                # L Ghi Chú: thêm bởi write_creative_sheet từ sheet cũ
            ])
        c_title, c_count = write_creative_sheet(spreadsheet, acc_name, creative_rows)
        print(f"  → Đã ghi {c_count} creative vào tab '{c_title}'.")

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
        "fields":      f"ad_id,adset_id,campaign_id,{_INSIGHTS_FIELDS}",
        "note":        "Insights cấp ad — dùng cho dòng Ad và tổng hợp Adset",
    })
    print("\nHoàn thành!")


if __name__ == "__main__":
    main()
