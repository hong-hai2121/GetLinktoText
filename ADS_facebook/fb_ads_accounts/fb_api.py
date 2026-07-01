"""
Bộ đếm & log số lần gọi Facebook Graph API — dùng chung cho
main.py, get_campaigns.py, get_details.py.

- Mỗi lần gọi API in ra terminal: số thứ tự + endpoint.
- Tự retry khi gặp rate limit (code 4 / 17 / 32 / 613) với backoff.
- Khi lỗi, in các header usage để biết loại quota nào bị chạm.
- Cuối mỗi script gọi api_summary() để in bảng tổng kết theo endpoint.
"""

import os
import re
import time
from collections import OrderedDict

import requests

RATE_LIMIT_CODES = (4, 17, 32, 613)

# Khoảng nghỉ (giây) sau MỖI lần gọi Graph API — giãn cách để tránh rate limit.
# Chỉnh runtime bằng set_call_delay(), hoặc đặt biến môi trường FB_API_CALL_DELAY.
CALL_DELAY = float(os.environ.get("FB_API_CALL_DELAY", "1.0"))


def set_call_delay(seconds: float) -> None:
    """Đặt lại khoảng nghỉ (giây) sau mỗi lần gọi API để giãn cách, tránh rate limit."""
    global CALL_DELAY
    try:
        CALL_DELAY = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return
    print(f"  ⏱ Giãn cách gọi API: {CALL_DELAY:g}s sau mỗi request.")


class RateLimitError(RuntimeError):
    """Facebook trả về rate limit — dừng ngay, không retry."""
    pass

# ── Bộ đếm toàn cục theo endpoint ────────────────────────────────────────────
_api_calls: "OrderedDict[str, int]" = OrderedDict()
_total_calls = 0


def _endpoint_label(url: str) -> str:
    """Rút gọn URL thành nhãn endpoint dễ đọc.
    Ví dụ: .../v20.0/act_123/insights → 'act_{id}/insights'."""
    path = url.split("graph.facebook.com/", 1)[-1]
    path = path.split("?", 1)[0]  # bỏ query string
    parts = path.split("/", 1)
    if parts and re.fullmatch(r"v\d+\.\d+", parts[0]):  # bỏ version
        path = parts[1] if len(parts) > 1 else ""
    path = re.sub(r"act_\d+", "act_{id}", path)
    path = re.sub(r"\b\d{6,}\b", "{id}", path)
    return path or "(root)"


def graph_get(url: str, params: dict, label: str | None = None) -> dict:
    """GET tới Graph API: đếm + log mỗi lần gọi, tự retry khi rate limit.
    Trả về data JSON đã parse (đã raise nếu lỗi không thể retry)."""
    global _total_calls
    endpoint = label or _endpoint_label(url)

    _total_calls += 1
    _api_calls[endpoint] = _api_calls.get(endpoint, 0) + 1
    print(f"  [API #{_total_calls}] GET {endpoint}"
          f"  (lần {_api_calls[endpoint]} cho endpoint này)")

    resp = requests.get(url, params=params)
    try:
        data = resp.json()
    except ValueError:
        data = {}

    if "error" in data:
        err = data["error"]
        print("    --- Facebook usage headers ---")
        for h in ("X-App-Usage", "X-Business-Use-Case-Usage", "X-Ad-Account-Usage"):
            if h in resp.headers:
                print(f"      {h}: {resp.headers[h]}")
        if err.get("code") in RATE_LIMIT_CODES:
            raise RateLimitError(
                f"Rate limit (code={err.get('code')}): {err.get('message')}"
            )
        raise RuntimeError(
            f"Facebook API lỗi (HTTP {resp.status_code}): {err.get('message')} "
            f"[type={err.get('type')}, code={err.get('code')}, "
            f"subcode={err.get('error_subcode')}]"
        )

    resp.raise_for_status()
    if CALL_DELAY > 0:
        time.sleep(CALL_DELAY)
    return data


def graph_paginate(url: str, params: dict, label: str | None = None) -> list:
    """Như graph_get nhưng tự đi hết phân trang, gộp toàn bộ data[]."""
    endpoint = label or _endpoint_label(url)
    results = []
    while url:
        data = graph_get(url, params, label=endpoint)
        results.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return results


def call_count() -> int:
    """Tổng số lần gọi API tính tới hiện tại."""
    return _total_calls


def calls_by_endpoint() -> dict:
    """Bản sao dict {endpoint: số lần} để ghi vào JSON nếu cần."""
    return dict(_api_calls)


def api_summary():
    """In bảng tổng kết số lần gọi Facebook Graph API theo endpoint."""
    print("\n" + "─" * 52)
    print(f"TỔNG KẾT API — {_total_calls} lần gọi Facebook Graph API")
    for endpoint, count in _api_calls.items():
        print(f"  • {endpoint:<28} {count} lần")
    print("─" * 52)


def reset_counter():
    """Đặt lại bộ đếm (hữu ích khi chạy nhiều lần trong cùng tiến trình)."""
    global _total_calls
    _api_calls.clear()
    _total_calls = 0
