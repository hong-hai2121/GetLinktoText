"""
Bộ đếm & log số lần gọi Facebook Graph API — dùng chung cho
main.py, get_campaigns.py, get_details.py.

- Mỗi lần gọi API in ra terminal: số thứ tự + endpoint.
- Gặp LỖI BẤT KỲ (rate limit, lỗi mạng, lỗi Meta...) → dừng ngay,
  báo lỗi lập tức, KHÔNG tự thử lại.
- Rate limit (code 4 / 17 / 32 / 613 hoặc HTTP 429) → RateLimitError
  để script ngoài lưu checkpoint rồi dừng.
- Khi lỗi, in các header usage để biết loại quota nào bị chạm.
- Cuối mỗi script gọi api_summary() để in bảng tổng kết theo endpoint.
"""

import re
import time
from collections import OrderedDict

import requests

RATE_LIMIT_CODES = (4, 17, 32, 613)
CALL_DELAY = 3.0  # giây nghỉ sau mỗi lần gọi API — tăng lên nếu vẫn bị limit
REQUEST_TIMEOUT = 60


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
    """GET tới Graph API: đếm + log mỗi lần gọi.
    Gặp lỗi bất kỳ → raise ngay lập tức, KHÔNG tự thử lại.
    Rate limit (code 4/17/32/613 hoặc HTTP 429) → RateLimitError."""
    global _total_calls
    endpoint = label or _endpoint_label(url)

    _total_calls += 1
    _api_calls[endpoint] = _api_calls.get(endpoint, 0) + 1
    print(f"  [API #{_total_calls}] GET {endpoint}"
          f"  (lần {_api_calls[endpoint]} cho endpoint này)")

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"    Lỗi mạng: {e} → DỪNG NGAY.")
        raise RuntimeError(f"Lỗi mạng khi gọi {endpoint}: {e}") from e

    try:
        data = resp.json()
    except ValueError:
        data = {}

    if "error" in data:
        err = data["error"]
        print(f"    Facebook error: HTTP {resp.status_code}: {err.get('message')}")
        print(
            "      "
            f"type={err.get('type')}, code={err.get('code')}, "
            f"subcode={err.get('error_subcode')}, fbtrace_id={err.get('fbtrace_id')}"
        )
        print("    --- Facebook usage headers ---")
        for h in ("X-App-Usage", "X-Business-Use-Case-Usage", "X-Ad-Account-Usage"):
            if h in resp.headers:
                print(f"      {h}: {resp.headers[h]}")
        if err.get("code") in RATE_LIMIT_CODES or resp.status_code == 429:
            raise RateLimitError(
                f"Rate limit (HTTP {resp.status_code}, code={err.get('code')}): "
                f"{err.get('message')}"
            )
        raise RuntimeError(
            f"Facebook API lỗi (HTTP {resp.status_code}): {err.get('message')} "
            f"[type={err.get('type')}, code={err.get('code')}, "
            f"subcode={err.get('error_subcode')}]"
        )

    if resp.status_code == 429:
        print(f"    HTTP 429 (Too Many Requests) → DỪNG NGAY.")
        raise RateLimitError(f"Rate limit (HTTP 429) khi gọi {endpoint}")

    if not resp.ok:
        print(f"    HTTP {resp.status_code} → DỪNG NGAY.")
        raise RuntimeError(
            f"Facebook API lỗi HTTP {resp.status_code} khi gọi {endpoint}"
        )

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
