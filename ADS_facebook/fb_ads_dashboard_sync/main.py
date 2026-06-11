"""
Điểm chạy chính: lấy dữ liệu Facebook Ads từ Meta Marketing API và upsert vào
Google Sheet (database tạm cho web dashboard).

Luồng:
    1. Lấy metadata thực thể (campaign/adset/ad) 1 lần — để có status / effective_status
       / objective / budget (insights không trả các trường này).
    2. Với mỗi khoảng thời gian DAILY (hôm nay, hôm qua, 7 ngày, tháng này) và mỗi
       level (campaign/adset/ad): lấy insights time_increment=1 → upsert raw_*.
    3. Gom dòng campaign daily → build + upsert dashboard_daily.
    4. Lifetime (date_preset=maximum, level=campaign) → build + upsert dashboard_lifetime.
    5. Ghi sync_log cho mỗi (level × khoảng thời gian).

Chạy:  python main.py
"""

import logging
import sys
from datetime import date, datetime, timedelta, timezone

import config
import meta_api
import schema
import transform
import dashboard
from sheets import (
    connect_spreadsheet, get_or_create_worksheet,
    upsert_to_google_sheet, append_sync_log,
)

# Console Windows có thể là cp1252 → ép UTF-8 để log tiếng Việt không crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


# ── Khoảng thời gian DAILY (time_increment=1) ──────────────────────────────────

def daily_ranges(today: date | None = None) -> list[dict]:
    """Trả danh sách {label, time_range} cho 4 kỳ daily — lấy TỪNG NGÀY (increment=1)."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    last7_start = today - timedelta(days=6)        # 7 ngày gần nhất (gồm hôm nay)
    month_start = today.replace(day=1)             # đầu tháng này

    def rng(since: date, until: date) -> dict:
        return {"since": since.isoformat(), "until": until.isoformat()}

    return [
        {"label": "today", "time_range": rng(today, today)},
        {"label": "yesterday", "time_range": rng(yesterday, yesterday)},
        {"label": "last_7d", "time_range": rng(last7_start, today)},
        {"label": "this_month", "time_range": rng(month_start, today)},
    ]


LEVEL_CONFIG = {
    "campaign": {
        "sheet": schema.SHEET_RAW_CAMPAIGN,
        "cols": schema.COLS_RAW_CAMPAIGN,
    },
    "adset": {
        "sheet": schema.SHEET_RAW_ADSET,
        "cols": schema.COLS_RAW_ADSET,
    },
    "ad": {
        "sheet": schema.SHEET_RAW_AD,
        "cols": schema.COLS_RAW_AD,
    },
}


def write_sync_log(ws, *, account_id, level, date_label, status,
                   rows_fetched=0, rows_inserted=0, rows_updated=0,
                   error_message="") -> None:
    """Ghi 1 dòng vào sheet sync_log."""
    row = {
        "sync_time": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "account_id": account_id,
        "level": level,
        "date_preset_or_range": date_label,
        "status": status,
        "rows_fetched": rows_fetched,
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
        "error_message": error_message,
    }
    append_sync_log(ws, row, schema.COLS_SYNC_LOG)


def _build_rows(level: str, insights: list[dict], account_id: str, account_name: str,
                camp_meta: dict, adset_meta: dict, ad_meta: dict) -> list[dict]:
    rows = []
    for ins in insights:
        if level == "campaign":
            meta = camp_meta.get(ins.get("campaign_id", ""), {})
            rows.append(transform.build_campaign_row(ins, account_id, account_name, meta))
        elif level == "adset":
            meta = adset_meta.get(ins.get("adset_id", ""), {})
            rows.append(transform.build_adset_row(ins, account_id, account_name, meta))
        else:  # ad
            meta = ad_meta.get(ins.get("ad_id", ""), {})
            rows.append(transform.build_ad_row(ins, account_id, account_name, meta))
    return rows


def main() -> None:
    config.validate()
    account_id = config.account_id_bare()

    log.info("Kết nối Google Sheet %s ...", config.GOOGLE_SHEET_ID)
    ss = connect_spreadsheet()
    log.info("  → OK: %s", ss.title)

    # Chuẩn bị/đảm bảo tất cả tab + header trước khi ghi.
    ws = {
        schema.SHEET_RAW_CAMPAIGN: get_or_create_worksheet(
            ss, schema.SHEET_RAW_CAMPAIGN, schema.COLS_RAW_CAMPAIGN),
        schema.SHEET_RAW_ADSET: get_or_create_worksheet(
            ss, schema.SHEET_RAW_ADSET, schema.COLS_RAW_ADSET),
        schema.SHEET_RAW_AD: get_or_create_worksheet(
            ss, schema.SHEET_RAW_AD, schema.COLS_RAW_AD),
        schema.SHEET_DASHBOARD_DAILY: get_or_create_worksheet(
            ss, schema.SHEET_DASHBOARD_DAILY, schema.COLS_DASHBOARD_DAILY),
        schema.SHEET_DASHBOARD_LIFETIME: get_or_create_worksheet(
            ss, schema.SHEET_DASHBOARD_LIFETIME, schema.COLS_DASHBOARD_LIFETIME),
        schema.SHEET_SYNC_LOG: get_or_create_worksheet(
            ss, schema.SHEET_SYNC_LOG, schema.COLS_SYNC_LOG),
    }
    log_ws = ws[schema.SHEET_SYNC_LOG]

    # ── 1. Metadata thực thể (1 lần) ──────────────────────────────────────────
    log.info("Lấy metadata thực thể (campaign/adset/ad)...")
    account_name = meta_api.fetch_account_name()
    camp_meta = meta_api.fetch_campaign_meta()
    adset_meta = meta_api.fetch_adset_meta()
    ad_meta = meta_api.fetch_ad_meta()
    log.info("  → %s | %d campaign, %d adset, %d ad",
             account_name, len(camp_meta), len(adset_meta), len(ad_meta))

    # ── 2. DAILY: từng kỳ × từng level → upsert raw_* ─────────────────────────
    campaign_daily_rows: list[dict] = []  # gom để dựng dashboard_daily

    for rng in daily_ranges():
        label = rng["label"]
        for level, cfg in LEVEL_CONFIG.items():
            try:
                insights = meta_api.get_meta_insights(
                    level, time_range=rng["time_range"], time_increment=1)
                rows = _build_rows(level, insights, account_id, account_name,
                                   camp_meta, adset_meta, ad_meta)
                ins_n, upd_n = upsert_to_google_sheet(
                    ws[cfg["sheet"]], cfg["cols"], rows, schema.KEY_RAW)
                if level == "campaign":
                    campaign_daily_rows.extend(rows)
                log.info("[%s/%s] fetched=%d inserted=%d updated=%d",
                         label, level, len(rows), ins_n, upd_n)
                write_sync_log(log_ws, account_id=account_id, level=level,
                               date_label=label, status="success",
                               rows_fetched=len(rows), rows_inserted=ins_n,
                               rows_updated=upd_n)
            except Exception as e:
                log.error("[%s/%s] LỖI: %s", label, level, e)
                write_sync_log(log_ws, account_id=account_id, level=level,
                               date_label=label, status="error",
                               error_message=str(e))

    # ── 3. dashboard_daily (từ campaign daily đã gom) ─────────────────────────
    try:
        dd_rows = dashboard.build_dashboard_daily(campaign_daily_rows)
        ins_n, upd_n = upsert_to_google_sheet(
            ws[schema.SHEET_DASHBOARD_DAILY], schema.COLS_DASHBOARD_DAILY,
            dd_rows, schema.KEY_DASHBOARD_DAILY,
            preserve_cols=schema.PRESERVE_DASHBOARD_DAILY)
        log.info("[dashboard_daily] inserted=%d updated=%d", ins_n, upd_n)
        write_sync_log(log_ws, account_id=account_id, level="dashboard_daily",
                       date_label="daily", status="success",
                       rows_fetched=len(dd_rows), rows_inserted=ins_n,
                       rows_updated=upd_n)
    except Exception as e:
        log.error("[dashboard_daily] LỖI: %s", e)
        write_sync_log(log_ws, account_id=account_id, level="dashboard_daily",
                       date_label="daily", status="error", error_message=str(e))

    # ── 4. lifetime → dashboard_lifetime ──────────────────────────────────────
    try:
        lifetime_insights = meta_api.get_meta_insights(
            "campaign", date_preset="maximum")  # KHÔNG time_increment → tổng toàn thời gian
        dl_rows = dashboard.build_dashboard_lifetime(
            lifetime_insights, account_id, account_name, camp_meta)
        ins_n, upd_n = upsert_to_google_sheet(
            ws[schema.SHEET_DASHBOARD_LIFETIME], schema.COLS_DASHBOARD_LIFETIME,
            dl_rows, schema.KEY_DASHBOARD_LIFETIME,
            preserve_cols=schema.PRESERVE_DASHBOARD_LIFETIME)
        log.info("[dashboard_lifetime] fetched=%d inserted=%d updated=%d",
                 len(dl_rows), ins_n, upd_n)
        write_sync_log(log_ws, account_id=account_id, level="dashboard_lifetime",
                       date_label="maximum", status="success",
                       rows_fetched=len(dl_rows), rows_inserted=ins_n,
                       rows_updated=upd_n)
    except Exception as e:
        log.error("[dashboard_lifetime] LỖI: %s", e)
        write_sync_log(log_ws, account_id=account_id, level="dashboard_lifetime",
                       date_label="maximum", status="error", error_message=str(e))

    log.info("✓ Hoàn thành sync.")


if __name__ == "__main__":
    main()
