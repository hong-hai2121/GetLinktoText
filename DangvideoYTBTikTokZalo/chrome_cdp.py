# -*- coding: utf-8 -*-
"""Nối Playwright vào CHROME ĐANG MỞ BÌNH THƯỜNG của bạn — qua "Playwright Extension" (Microsoft).

Vì sao không dùng --remote-debugging-port nữa:
- Chrome >= 136 chặn cổng DevTools trên thư mục User Data mặc định.
- Mọi cách lách bằng đổi đường dẫn (copy profile, junction) đều khiến Chrome KHÔNG giải mã được
  cookie (App-Bound Encryption gắn khoá với đúng đường dẫn User Data) -> nhìn như mất đăng nhập.

Cách này: extension chạy BÊN TRONG Chrome thật (đúng profile, đúng cookie), nối ra ngoài bằng
WebSocket tới relay Python (pw_extension_relay.py); Playwright connect_over_cdp vào relay như
Chrome thật. Chạy song song với mọi cửa sổ Chrome khác — không mở Chrome riêng, không đóng gì.

Chuẩn bị 1 LẦN cho profile (ví dụ "Profile 9"):
  1. Cài "Playwright Extension" từ Chrome Web Store (app tự mở trang cài nếu chưa thấy).
  2. chrome://extensions -> Chi tiết (Details) của extension -> bật "Cho phép truy cập URL tệp"
     (Allow access to file URLs). BẮT BUỘC: không bật thì Playwright không nạp được file video
     vào <input type=file> (Chrome trả "Not allowed").
  3. Bấm icon extension -> trang trạng thái -> sao chép dòng PLAYWRIGHT_MCP_EXTENSION_TOKEN=...
     -> dán vào ô "Token extension" của app (hoặc config.json). Có token thì tự kết nối, không
     phải bấm "Cho phép" trong Chrome mỗi lần.
"""
import json
import os
import subprocess
from pathlib import Path

from pw_extension_relay import EXTENSION_ID, EXTENSION_STORE_URL, ExtensionRelay

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
DEFAULT_USER_DATA = str(Path(LOCALAPPDATA) / "Google" / "Chrome" / "User Data")

DEFAULT_CONFIG = {
    "chrome_path": "",                 # để trống sẽ tự dò
    "user_data_dir": DEFAULT_USER_DATA,
    "profile_dir": "Profile 9",
    "extension_token": "",             # PLAYWRIGHT_MCP_EXTENSION_TOKEN=... (dán cả dòng cũng được)
    "client_name": "Đăng video YouTube",  # tên hiện trên nhóm tab "Playwright · ..."
    "connect_timeout_sec": 60,
    # --- tab YouTube trong app ---
    "channel_name": "",                    # điền sau khi "Kiểm tra kết nối"
    "channel_url": "",                     # link Studio của kênh
    "schedule_times": ["08:00", "19:00"],  # khung giờ YouTube tự công bố mỗi ngày
    "schedule_start": "",                  # YYYY-MM-DD, trống = hôm nay
    "default_desc": "",                    # mô tả dùng chung (tiêu đề = tên file, sửa sau trong Studio)
    "default_playlist": "Dạ dày tiêu hóa",
    "default_tags": "",
    "default_kids": False,
    # --- TikTok / Zalo: nội dung = 1 dòng tiêu đề + hashtag ---
    "default_hashtags": "",                # "#a #b"; trống = lấy dòng cuối của mô tả (nếu toàn hashtag)
    "default_platforms": ["youtube", "tiktok", "zalo"],   # ô tick mặc định khi thêm video
    # --- trình duyệt + token Playwright Extension riêng từng nền tảng (xem platform_config) ---
    # {"tiktok": {"browser_path", "user_data_dir", "profile_dir", "extension_token", "client_name",
    #             "account" (kết quả Kiểm tra kết nối)}, "zalo": {...}}
    "platforms": {},
}

_relay = None  # ExtensionRelay đang dùng (giữ giữa launch_chrome và connect_playwright)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            # config đời cũ (junction) dùng khoá source_user_data
            if data.get("source_user_data") and not data.get("user_data_dir"):
                data["user_data_dir"] = data["source_user_data"]
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        except Exception:
            pass
    else:
        save_config(cfg)
    if not cfg.get("user_data_dir"):
        cfg["user_data_dir"] = DEFAULT_USER_DATA
    return cfg


def save_config(cfg):
    out = {k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG}
    CONFIG_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_token(token):
    """Nhận 'PLAYWRIGHT_MCP_EXTENSION_TOKEN=abc', 'abc' hay có ngoặc kép -> 'abc'."""
    t = (token or "").strip().strip('"').strip("'")
    if "=" in t and t.upper().startswith("PLAYWRIGHT_MCP_EXTENSION_TOKEN"):
        t = t.split("=", 1)[1].strip().strip('"').strip("'")
    return t


def find_chrome(cfg):
    if cfg.get("chrome_path") and Path(cfg["chrome_path"]).exists():
        return cfg["chrome_path"]
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path(LOCALAPPDATA) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FileNotFoundError("Không tìm thấy chrome.exe — hãy điền chrome_path vào config.json")


def profile_path(cfg):
    return Path(cfg["user_data_dir"]) / cfg["profile_dir"]


def extension_installed(cfg):
    """Extension đã cài trong profile chưa (cùng cách Playwright kiểm tra):
    Web Store giải nén vào <profile>/Extensions/<id>; ngoài ra còn bản ghi extensions.settings
    trong Preferences / Secure Preferences (bản ghi rỗng = đã gỡ, không tính)."""
    p = profile_path(cfg)
    if (p / "Extensions" / EXTENSION_ID).exists():
        return True
    for name in ("Preferences", "Secure Preferences"):
        try:
            prefs = json.loads((p / name).read_text(encoding="utf-8"))
        except Exception:
            continue
        rec = ((prefs.get("extensions") or {}).get("settings") or {}).get(EXTENSION_ID)
        if isinstance(rec, dict) and rec:
            return True
    return False


def _spawn_chrome(cfg, url):
    args = [find_chrome(cfg), f"--profile-directory={cfg['profile_dir']}", url]
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def open_store_page(cfg, log=print):
    """Mở trang Chrome Web Store của extension trong đúng profile để người dùng bấm 'Thêm vào Chrome'."""
    log(f"Mở trang cài Playwright Extension trong profile '{cfg['profile_dir']}'...")
    _spawn_chrome(cfg, EXTENSION_STORE_URL)


def open_extension_settings(cfg, log=print):
    """Mở trang chi tiết extension (chỗ bật 'Cho phép truy cập URL tệp')."""
    _spawn_chrome(cfg, f"chrome://extensions/?id={EXTENSION_ID}")


def launch_chrome(cfg, log=print):
    """Giữ tên cũ cho app.py / run_cli.py. Thực chất: bật relay, mở trang connect của extension
    trong đúng profile và chờ extension nối vào. Chrome đang mở thì chỉ thêm 1 tab."""
    global _relay
    if _relay is not None and _relay.connected:
        log("✓ Extension đang nối sẵn — dùng lại.")
        return _relay
    if _relay is not None:
        _relay.stop()
        _relay = None

    chrome = find_chrome(cfg)
    if not extension_installed(cfg):
        open_store_page(cfg, log)
        raise RuntimeError(
            f"Chưa cài Playwright Extension trong profile '{cfg['profile_dir']}'. "
            "Đã mở trang Chrome Web Store trong profile đó — bấm 'Thêm vào Chrome', rồi: "
            "(1) chrome://extensions -> Chi tiết -> bật 'Cho phép truy cập URL tệp'; "
            "(2) bấm icon extension -> sao chép token -> dán vào app. Sau đó chạy lại.")

    token = normalize_token(cfg.get("extension_token"))
    relay = ExtensionRelay(log=log)
    relay.start()
    log(f"Relay sẵn sàng (cổng {relay.port}). Mở trang kết nối trong profile '{cfg['profile_dir']}'...")
    relay.open_connect_page(chrome, cfg["profile_dir"],
                            cfg.get("client_name") or DEFAULT_CONFIG["client_name"], token)
    if token:
        timeout = float(cfg.get("connect_timeout_sec") or 60)
        log("Có token — extension sẽ tự kết nối, không cần bấm gì.")
    else:
        timeout = None
        log("⚠ Chưa có token — hãy bấm 'Cho phép' (Allow) trong tab Chrome vừa mở. "
            "(Dán token vào app để lần sau tự động.)")
    try:
        relay.wait_for_extension(timeout)
    except Exception:
        relay.stop()
        raise
    log("✓ Extension đã nối — đang điều khiển Chrome thật của bạn (cookie/đăng nhập giữ nguyên).")
    _relay = relay
    return relay


def connect_playwright(cfg, log=print):
    """Nối Playwright vào relay. Trả về (playwright, browser, page); page là tab connect vừa mở."""
    if _relay is None or not _relay.connected:
        raise RuntimeError("Chưa kết nối extension — gọi launch_chrome() trước.")
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(_relay.cdp_endpoint, timeout=30000)
    except Exception:
        pw.stop()
        raise
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.bring_to_front()
    except Exception:
        pass
    log("✓ Playwright đã nối vào Chrome (qua extension).")
    return pw, browser, page


def relay_connected():
    """Extension còn nối với relay không (để worker AI biết phải nối lại hay dùng tiếp)."""
    return _relay is not None and _relay.connected


def cdp_send(method, params=None, timeout=30.0):
    """Gửi lệnh CDP thẳng tới tab đang điều khiển (xem ExtensionRelay.send_cdp)."""
    if _relay is None or not _relay.connected:
        raise RuntimeError("Chưa kết nối extension — gọi launch_chrome() trước.")
    return _relay.send_cdp(method, params, timeout=timeout)


def close_tab(page, log=None):
    """Đóng tab điều khiển (relay chuyển Target.closeTarget -> chrome.tabs.remove). Lỗi thì bỏ qua."""
    if page is None:
        return False
    try:
        page.close(run_before_unload=False)
        if log:
            log("✓ Đã đóng tab điều khiển.")
        return True
    except Exception:
        return False


def disconnect(pw, page=None):
    """Ngắt Playwright và tắt relay. Truyền `page` để ĐÓNG tab điều khiển trước khi ngắt (mặc định
    không: Chrome và tab vẫn mở, extension chỉ gỡ debugger khỏi tab)."""
    global _relay
    if page is not None:
        close_tab(page)
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass
    if _relay is not None:
        _relay.stop()
        _relay = None


# ------------------------------------------------------------------ nhiều nền tảng
def platform_config(cfg, name):
    """Cấu hình trình duyệt cho một nền tảng ("youtube" / "tiktok" / "zalo").

    config.json có mục "platforms": {tên: {browser_path, user_data_dir, profile_dir,
    extension_token, client_name}}. Trả về bản sao cfg với các khóa cấp cao nhất
    (chrome_path, user_data_dir, profile_dir, extension_token, client_name) được ghi đè theo
    nền tảng, nên mọi hàm hiện có (find_chrome, profile_path, connect...) dùng được ngay.
    Zalo chạy Cốc Cốc: browser_path trỏ tới browser.exe của Cốc Cốc (cùng nhân Chromium).
    Không có mục cho nền tảng đó thì trả về cfg gốc (YouTube)."""
    pfs = cfg.get("platforms") or {}
    p = pfs.get(name)
    if not p and name == "gemini":          # Gemini chưa có mục riêng -> dùng trình duyệt/profile của Zalo
        p = pfs.get("zalo")
    if not p:
        return dict(cfg)
    out = dict(cfg)
    if p.get("browser_path"):
        out["chrome_path"] = p["browser_path"]
    for k in ("user_data_dir", "profile_dir", "extension_token", "client_name"):
        if p.get(k):
            out[k] = p[k]
    return out
