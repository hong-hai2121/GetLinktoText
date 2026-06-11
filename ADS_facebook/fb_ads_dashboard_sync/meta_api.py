"""
Lớp gọi Meta Marketing API (Graph API) — có phân trang + retry khi lỗi tạm thời.

Hàm chính:
    get_meta_insights()   Lấy insights theo level (campaign/adset/ad) cho 1 khoảng
                          thời gian, tự đi hết phân trang.
    fetch_account_name()  Tên tài khoản quảng cáo.
    fetch_campaign_meta() / fetch_adset_meta() / fetch_ad_meta()
                          Metadata thực thể (status / effective_status / objective /
                          budget...) — vì những trường này KHÔNG có trong insights.
"""

import logging
import time

import requests

import config

log = logging.getLogger("meta_api")

GRAPH_BASE = f"https://graph.facebook.com/{config.FB_API_VERSION}"

# Mã lỗi rate limit của Facebook → nên chờ rồi thử lại.
RATE_LIMIT_CODES = {4, 17, 32, 341, 613}
# HTTP status coi là lỗi tạm thời → retry.
TRANSIENT_HTTP = {429, 500, 502, 503, 504}

MAX_RETRIES = 5
BASE_BACKOFF = 5.0   # giây — nhân đôi sau mỗi lần thất bại
CALL_DELAY = 1.0     # giây nghỉ sau mỗi request thành công (giảm áp lực rate limit)

# Trường insights (KHÔNG gồm status/effective_status/budget — lấy từ metadata thực thể).
INSIGHTS_METRIC_FIELDS = [
    "spend", "impressions", "reach", "frequency", "clicks", "inline_link_clicks",
    "ctr", "cpc", "cpm", "objective",
    "actions", "cost_per_action_type",
    "video_play_actions", "video_thruplay_watched_actions",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p95_watched_actions",
    "video_avg_time_watched_actions",
    "date_start", "date_stop",
]

# Trường định danh theo từng level (cộng thêm vào INSIGHTS_METRIC_FIELDS).
LEVEL_ID_FIELDS = {
    "campaign": ["campaign_id", "campaign_name"],
    "adset": ["campaign_id", "campaign_name", "adset_id", "adset_name"],
    "ad": [
        "campaign_id", "campaign_name", "adset_id", "adset_name",
        "ad_id", "ad_name",
    ],
}


def _request_with_retry(url: str, params: dict) -> dict:
    """GET tới Graph API; tự retry khi rate limit / lỗi 5xx / lỗi mạng (backoff lũy thừa)."""
    backoff = BASE_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=120)
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            log.warning("Lỗi mạng (%s), thử lại sau %.0fs [%d/%d]",
                        e, backoff, attempt, MAX_RETRIES)
            time.sleep(backoff)
            backoff *= 2
            continue

        try:
            data = resp.json()
        except ValueError:
            data = {}

        if "error" in data:
            err = data["error"]
            code = err.get("code")
            if code in RATE_LIMIT_CODES and attempt < MAX_RETRIES:
                log.warning("Rate limit (code=%s): %s — chờ %.0fs [%d/%d]",
                            code, err.get("message"), backoff, attempt, MAX_RETRIES)
                time.sleep(backoff)
                backoff *= 2
                continue
            raise RuntimeError(
                f"Meta API lỗi (HTTP {resp.status_code}): {err.get('message')} "
                f"[type={err.get('type')}, code={code}, "
                f"subcode={err.get('error_subcode')}]"
            )

        if resp.status_code in TRANSIENT_HTTP and attempt < MAX_RETRIES:
            log.warning("HTTP %s tạm thời — chờ %.0fs [%d/%d]",
                        resp.status_code, backoff, attempt, MAX_RETRIES)
            time.sleep(backoff)
            backoff *= 2
            continue

        resp.raise_for_status()
        if CALL_DELAY > 0:
            time.sleep(CALL_DELAY)
        return data

    raise RuntimeError(f"Hết {MAX_RETRIES} lần thử mà vẫn lỗi: {url}")


def _paginate(url: str, params: dict) -> list[dict]:
    """Đi hết phân trang, gộp toàn bộ data[]."""
    results: list[dict] = []
    page = 1
    while url:
        data = _request_with_retry(url, params)
        rows = data.get("data", [])
        results.extend(rows)
        next_url = data.get("paging", {}).get("next")
        if next_url:
            log.debug("  → phân trang: tải tiếp trang %d (đã có %d dòng)",
                      page + 1, len(results))
        url, params = next_url, {}  # next URL đã chứa sẵn query string
        page += 1
    return results


# ── Insights ───────────────────────────────────────────────────────────────────

def get_meta_insights(
    level: str,
    *,
    time_range: dict | None = None,
    date_preset: str | None = None,
    time_increment: int | str | None = None,
) -> list[dict]:
    """Lấy insights cho 1 level + 1 khoảng thời gian.

    Truyền MỘT trong hai: time_range={"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}
    HOẶC date_preset (vd "maximum"). time_increment=1 để tách theo từng ngày.
    """
    if level not in LEVEL_ID_FIELDS:
        raise ValueError(f"level không hợp lệ: {level}")

    fields = LEVEL_ID_FIELDS[level] + INSIGHTS_METRIC_FIELDS
    params = {
        "level": level,
        "fields": ",".join(fields),
        "access_token": config.META_ACCESS_TOKEN,
        "limit": 200,
    }
    if time_range:
        # time_range phải là JSON; requests sẽ url-encode chuỗi này.
        import json
        params["time_range"] = json.dumps(time_range)
    elif date_preset:
        params["date_preset"] = date_preset
    else:
        raise ValueError("Cần time_range hoặc date_preset")

    if time_increment is not None:
        params["time_increment"] = time_increment

    url = f"{GRAPH_BASE}/{config.account_id_normalized()}/insights"
    rows = _paginate(url, params)
    log.info("insights level=%s → %d dòng", level, len(rows))
    return rows


# ── Metadata thực thể (status / effective_status / objective / budget) ──────────

def _fetch_edge(edge: str, fields: str) -> list[dict]:
    url = f"{GRAPH_BASE}/{config.account_id_normalized()}/{edge}"
    params = {
        "fields": fields,
        "access_token": config.META_ACCESS_TOKEN,
        "limit": 200,
    }
    return _paginate(url, params)


def fetch_account_name() -> str:
    url = f"{GRAPH_BASE}/{config.account_id_normalized()}"
    data = _request_with_retry(url, {
        "fields": "name",
        "access_token": config.META_ACCESS_TOKEN,
    })
    return data.get("name", "")


def fetch_campaign_meta() -> dict[str, dict]:
    rows = _fetch_edge(
        "campaigns",
        "id,name,status,effective_status,objective,daily_budget,lifetime_budget",
    )
    return {r["id"]: r for r in rows if r.get("id")}


def fetch_adset_meta() -> dict[str, dict]:
    rows = _fetch_edge(
        "adsets",
        "id,name,status,effective_status,campaign_id,daily_budget,lifetime_budget",
    )
    return {r["id"]: r for r in rows if r.get("id")}


def fetch_ad_meta() -> dict[str, dict]:
    rows = _fetch_edge(
        "ads",
        "id,name,status,effective_status,adset_id,campaign_id",
    )
    return {r["id"]: r for r in rows if r.get("id")}
