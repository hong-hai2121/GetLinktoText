# -*- coding: utf-8 -*-
"""Đăng video tự động — server cục bộ + giao diện WEB (thay cửa sổ Tkinter cũ).

Chạy:  python app.py  ->  tự mở trình duyệt tại http://127.0.0.1:8765
Giao diện nằm ở web/index.html; app.py chỉ là server: giữ hàng đợi, nhật ký và chạy worker.

Tab YouTube: dán danh sách link Google Drive (hoặc đường dẫn file trên máy) -> app tải từng video
lên YouTube Studio NGAY và đặt chế độ "Lên lịch" theo khung giờ mặc định (YouTube tự công khai
đúng giờ, máy không cần mở lúc đó). Tiêu đề tạm = tên file; mô tả/thẻ/playlist dùng mặc định
của tab — bạn sửa lại sau trong Studio.

Điều khiển CHROME ĐANG MỞ BÌNH THƯỜNG qua "Playwright Extension" (xem chrome_cdp.py): không mở
Chrome riêng, không đóng Chrome, cookie/đăng nhập là của profile thật.

Server chỉ nghe trên 127.0.0.1 (máy này) — không mở ra mạng LAN vì nó điều khiển Chrome của bạn.
"""
import json
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import chrome_cdp
import post_queue as pq
import youtube_upload
from drive_download import download_drive

APP_DIR = Path(__file__).resolve().parent
INDEX_PATH = APP_DIR / "web" / "index.html"
HOST, PORT = "127.0.0.1", 8765
MAX_LOG_LINES = 2000


class State:
    """Trạng thái dùng chung giữa các request và worker (khoá bằng lock)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.cfg = chrome_cdp.load_config()
        self.items = pq.load_queue()
        self.logs = []            # [(seq, "dòng nhật ký")] — web poll lấy phần sau seq đã có
        self.log_seq = 0
        self.running = False
        self.stop_flag = threading.Event()
        self.ext_ok = chrome_cdp.extension_installed(self.cfg)

    def log(self, msg):
        with self.lock:
            self.log_seq += 1
            self.logs.append((self.log_seq, str(msg)))
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[:len(self.logs) - MAX_LOG_LINES]


S = State()


# ------------------------------------------------------------------ trạng thái
def state_payload(after=0):
    with S.lock:
        items = [{
            "id": it["id"],
            "link": it["link"],
            "short": pq.short_link(it["link"]),
            "title": it.get("title") or "",
            "gio": pq.fmt_dt(it.get("scheduled_at")),
            "status": it["status"],
            "kq": it.get("error") or it.get("result") or "",
        } for it in S.items]
        return {
            "running": S.running,
            "ext_ok": S.ext_ok,
            "profile": S.cfg["profile_dir"],
            "channel_name": S.cfg.get("channel_name") or "",
            "channel_url": S.cfg.get("channel_url") or "",
            "token": S.cfg.get("extension_token") or "",
            "times": ", ".join(S.cfg.get("schedule_times") or []),
            "start": S.cfg.get("schedule_start") or date.today().isoformat(),
            "desc": S.cfg.get("default_desc") or "",
            "playlist": S.cfg.get("default_playlist") or "",
            "tags": S.cfg.get("default_tags") or "",
            "kids": bool(S.cfg.get("default_kids")),
            "items": items,
            "logs": [t for seq, t in S.logs if seq > after],
            "log_seq": S.log_seq,
        }


# ------------------------------------------------------------------ lưu config
def api_save_token(data):
    with S.lock:
        S.cfg["extension_token"] = chrome_cdp.normalize_token(data.get("token") or "")
        chrome_cdp.save_config(S.cfg)
    return {"ok": True, "msg": "Đã lưu token extension vào config.json."}


def _apply_schedule(times_text, start_text):
    """Lưu khung giờ + ngày bắt đầu vào config. Trả về None nếu ok, chuỗi lỗi nếu sai."""
    times = pq.parse_times(times_text or "")
    if not times:
        return "Nhập ít nhất một khung giờ, ví dụ: 08:00, 19:00"
    with S.lock:
        S.cfg["schedule_times"] = times
        S.cfg["schedule_start"] = pq.parse_start(start_text or "").isoformat()
        chrome_cdp.save_config(S.cfg)
    return None


def api_save_schedule(data):
    err = _apply_schedule(data.get("times"), data.get("start"))
    if err:
        return {"ok": False, "msg": err}
    with S.lock:
        return {"ok": True,
                "msg": f"Lịch mặc định: {', '.join(S.cfg['schedule_times'])} mỗi ngày, từ {S.cfg['schedule_start']}.",
                "times": ", ".join(S.cfg["schedule_times"]), "start": S.cfg["schedule_start"]}


def api_save_defaults(data):
    with S.lock:
        S.cfg["default_desc"] = (data.get("desc") or "").strip()
        S.cfg["default_playlist"] = (data.get("playlist") or "").strip()
        S.cfg["default_tags"] = (data.get("tags") or "").strip()
        S.cfg["default_kids"] = bool(data.get("kids"))
        chrome_cdp.save_config(S.cfg)
    return {"ok": True, "msg": "Đã lưu thông tin mặc định."}


# ------------------------------------------------------------------ hàng đợi
def api_add_links(data):
    entries = pq.parse_entries(data.get("text") or "")
    if not entries:
        return {"ok": False, "msg": "Không thấy link Drive hay file hợp lệ nào."}
    err = _apply_schedule(data.get("times"), data.get("start"))
    if err:
        return {"ok": False, "msg": err}
    with S.lock:
        existing = {it["link"] for it in S.items}
        added = 0
        for e in entries:
            if e in existing:
                continue
            S.items.append(pq.new_item(e))
            added += 1
        pq.assign_schedule(S.items, S.cfg["schedule_times"], pq.parse_start(S.cfg["schedule_start"]))
        pq.save_queue(S.items)
    S.log(f"✓ Thêm {added} video vào hàng đợi (bỏ {len(entries) - added} trùng).")
    return {"ok": True, "msg": f"Đã thêm {added} video (bỏ {len(entries) - added} trùng)."}


def api_reassign(data):
    err = _apply_schedule(data.get("times"), data.get("start"))
    if err:
        return {"ok": False, "msg": err}
    with S.lock:
        pq.assign_schedule(S.items, S.cfg["schedule_times"],
                           pq.parse_start(S.cfg["schedule_start"]), reassign=True)
        pq.save_queue(S.items)
    S.log("✓ Đã xếp lại giờ công bố cho các mục đang chờ.")
    return {"ok": True, "msg": "Đã xếp lại giờ công bố."}


def api_delete(data):
    sel = set(data.get("ids") or [])
    if not sel:
        return {"ok": False, "msg": "Chưa chọn dòng nào."}
    with S.lock:
        S.items = [it for it in S.items if it["id"] not in sel or it["status"] == pq.STATUS_RUNNING]
        pq.save_queue(S.items)
    return {"ok": True, "msg": "Đã xoá các dòng chọn."}


def api_clear_finished(_data):
    with S.lock:
        S.items = [it for it in S.items if it["status"] not in (pq.STATUS_DONE, pq.STATUS_ERROR)]
        pq.save_queue(S.items)
    return {"ok": True, "msg": "Đã dọn các mục xong/lỗi."}


# ------------------------------------------------------------------ hành động
def api_check_connection(data):
    with S.lock:
        if S.running:
            return {"ok": False, "msg": "Đang chạy việc khác — chờ xong đã."}
        S.cfg["extension_token"] = chrome_cdp.normalize_token(data.get("token") or "")
        chrome_cdp.save_config(S.cfg)
        S.running = True

    def work():
        pw = None
        try:
            chrome_cdp.launch_chrome(S.cfg, log=S.log)
            pw, _browser, page = chrome_cdp.connect_playwright(S.cfg, log=S.log)
            info = youtube_upload.get_channel_info(page, log=S.log)
            if not info["logged_in"]:
                S.log("❌ CHƯA đăng nhập YouTube — hãy đăng nhập Google trong tab Chrome vừa mở.")
            else:
                with S.lock:
                    S.cfg["channel_name"] = info["name"] or S.cfg.get("channel_name") or ""
                    S.cfg["channel_url"] = info["url"]
                    chrome_cdp.save_config(S.cfg)
                S.log(f"✓ ĐÃ đăng nhập — kênh: {info['name']}  ({info['url']})")
        except Exception as e:
            S.log(f"❌ Lỗi: {e}")
        finally:
            chrome_cdp.disconnect(pw)
            with S.lock:
                S.ext_ok = chrome_cdp.extension_installed(S.cfg)
                S.running = False

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "msg": "Đang kiểm tra kết nối — xem Nhật ký."}


def api_start(data):
    with S.lock:
        if S.running:
            return {"ok": False, "msg": "Đang chạy rồi."}
        waiting = [it for it in S.items if it["status"] == pq.STATUS_WAIT]
        if not waiting:
            return {"ok": False, "msg": "Chưa có video nào đang chờ."}
        # lưu token + mặc định + lịch như GUI cũ làm trước khi chạy
        S.cfg["extension_token"] = chrome_cdp.normalize_token(data.get("token") or "")
        S.cfg["default_desc"] = (data.get("desc") or "").strip()
        S.cfg["default_playlist"] = (data.get("playlist") or "").strip()
        S.cfg["default_tags"] = (data.get("tags") or "").strip()
        S.cfg["default_kids"] = bool(data.get("kids"))
        times = pq.parse_times(data.get("times") or "")
        if not times:
            return {"ok": False, "msg": "Nhập ít nhất một khung giờ, ví dụ: 08:00, 19:00"}
        S.cfg["schedule_times"] = times
        S.cfg["schedule_start"] = pq.parse_start(data.get("start") or "").isoformat()
        chrome_cdp.save_config(S.cfg)
        S.stop_flag.clear()
        S.running = True
    dry = bool(data.get("dry_run"))
    threading.Thread(target=_worker, args=(dry,), daemon=True).start()
    n = 1 if dry else len(waiting)
    return {"ok": True, "msg": "Chạy thử 1 video (không bấm Lưu)..." if dry else f"Bắt đầu đăng {n} video..."}


def api_stop(_data):
    with S.lock:
        if not S.running:
            return {"ok": False, "msg": "Không có gì đang chạy."}
        S.stop_flag.set()
    S.log("⏹ Sẽ dừng sau khi xong video hiện tại.")
    return {"ok": True, "msg": "Sẽ dừng sau khi xong video hiện tại."}


def _worker(dry_run):
    pw = page = None
    try:
        chrome_cdp.launch_chrome(S.cfg, log=S.log)
        pw, _browser, page = chrome_cdp.connect_playwright(S.cfg, log=S.log)
        tags = [t.strip() for t in S.cfg.get("default_tags", "").split(",") if t.strip()]
        for it in list(S.items):
            if S.stop_flag.is_set():
                break
            if it["status"] != pq.STATUS_WAIT:
                continue
            with S.lock:
                # Giờ hẹn phải còn đủ xa; không thì xếp lại trước khi đăng
                when = pq.parse_dt(it.get("scheduled_at"))
                if when is None or when < datetime.now() + pq.MIN_LEAD:
                    it["scheduled_at"] = None
                    pq.assign_schedule(S.items, S.cfg["schedule_times"], pq.parse_start(S.cfg["schedule_start"]))
                    when = pq.parse_dt(it["scheduled_at"])
                    S.log(f"  Giờ hẹn cũ đã qua -> xếp lại: {pq.fmt_dt(it['scheduled_at'])}")
                it["status"] = pq.STATUS_RUNNING
                it["error"] = ""
                pq.save_queue(S.items)
            S.log(f"=== Video: {pq.short_link(it['link'])}  (công bố {pq.fmt_dt(it['scheduled_at'])}) ===")
            try:
                path = download_drive(it["link"], log=S.log) if pq.is_drive(it["link"]) else it["link"]
                title = it.get("title") or Path(path).stem
                link = youtube_upload.upload_video(
                    page, path, title, S.cfg.get("default_desc", ""),
                    playlist=S.cfg.get("default_playlist") or None, tags=tags,
                    visibility="SCHEDULE", schedule_at=when,
                    made_for_kids=bool(S.cfg.get("default_kids")), log=S.log, dry_run=dry_run)
                with S.lock:
                    it["title"] = title
                    if dry_run:
                        it["status"] = pq.STATUS_WAIT
                        it["result"] = "(chạy thử xong, chưa đăng) " + (link or "")
                    else:
                        it["status"] = pq.STATUS_DONE
                        it["result"] = link or "đã lên lịch"
                    pq.save_queue(S.items)
            except Exception as e:
                with S.lock:
                    it["status"] = pq.STATUS_ERROR
                    it["error"] = str(e).splitlines()[0][:300]
                    pq.save_queue(S.items)
                S.log(f"❌ LỖI: {it['error']}")
                try:
                    shot = str(APP_DIR / "loi_gan_nhat.png")
                    page.screenshot(path=shot)
                    S.log(f"Ảnh chụp lúc lỗi: {shot}")
                except Exception:
                    pass
                S.log("Dừng hàng đợi để bạn kiểm tra Chrome (hộp thoại vẫn mở, chưa bấm Lưu).")
                break
            if dry_run:
                break
        else:
            S.log("🎉 Hết hàng đợi.")
    except Exception as e:
        S.log(f"❌ LỖI: {e}")
    finally:
        chrome_cdp.disconnect(pw)
        with S.lock:
            S.running = False


# ------------------------------------------------------------------ HTTP server
ROUTES = {
    "/api/save_token": api_save_token,
    "/api/save_schedule": api_save_schedule,
    "/api/save_defaults": api_save_defaults,
    "/api/add_links": api_add_links,
    "/api/reassign": api_reassign,
    "/api/delete": api_delete,
    "/api/clear_finished": api_clear_finished,
    "/api/check_connection": api_check_connection,
    "/api/start": api_start,
    "/api/stop": api_stop,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):   # tắt log request mặc định cho đỡ nhiễu console
        pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send(INDEX_PATH.read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/state":
            try:
                after = int((parse_qs(u.query).get("after") or ["0"])[0])
            except ValueError:
                after = 0
            self._json(state_payload(after))
        else:
            self._json({"ok": False, "msg": "Không có đường dẫn này."}, 404)

    def do_POST(self):
        fn = ROUTES.get(urlparse(self.path).path)
        if fn is None:
            return self._json({"ok": False, "msg": "Không có đường dẫn này."}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            data = {}
        try:
            self._json(fn(data))
        except Exception as e:
            self._json({"ok": False, "msg": str(e)})


def make_server():
    """Mở server trên PORT; cổng bận (app đang chạy sẵn?) thì lấy cổng trống bất kỳ.
    Trả về (httpd, url). Dùng chung cho main() và cửa sổ trạng thái app_gui.py."""
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        httpd = ThreadingHTTPServer((HOST, 0), Handler)
    return httpd, f"http://{HOST}:{httpd.server_address[1]}/"


def main():
    httpd, url = make_server()
    print(f"Đăng video tự động — giao diện web: {url}   (Ctrl+C để thoát)")
    S.log(f"✓ Server sẵn sàng tại {url} — giao diện web thay cửa sổ desktop, backend giữ nguyên.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
