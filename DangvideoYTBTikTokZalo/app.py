# -*- coding: utf-8 -*-
"""Đăng video tự động — server cục bộ + giao diện WEB (thay cửa sổ Tkinter cũ).

Chạy:  python app.py  ->  tự mở trình duyệt tại http://127.0.0.1:8765
Giao diện nằm ở web/index.html; app.py chỉ là server: giữ hàng đợi, nhật ký và chạy worker.

MỘT hàng đợi cho cả ba nền tảng: mỗi mục tick [YouTube][TikTok][Zalo] (post_queue: platforms + pf).
Worker gom theo nền tảng: nối trình duyệt của YouTube -> đăng hết mục chờ -> ngắt, rồi TikTok, rồi
Zalo (mỗi nền tảng một profile/trình duyệt riêng, xem config.json mục "platforms"; relay của
chrome_cdp chỉ nối được một profile một lúc). Lỗi ở một nền tảng: đánh dấu lỗi mục đó, dừng nền
tảng đó (tab giữ nguyên để xem) và chuyển sang nền tảng kế; "Đăng lại lỗi" chỉ làm lại phần lỗi.

Nội dung: YouTube = tiêu đề + mô tả đầy đủ + thẻ + playlist; TikTok và Zalo = MỘT dòng tiêu đề
+ hashtag (ô "Hashtag" hoặc dòng cuối của mô tả). Giờ công bố dùng chung cho cả ba.

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
import tiktok_upload
import youtube_upload
import zalo_upload
from dang_common import hashtags_from_text
from drive_download import download_drive

APP_DIR = Path(__file__).resolve().parent
INDEX_PATH = APP_DIR / "web" / "index.html"
HOST, PORT = "127.0.0.1", 8765
MAX_LOG_LINES = 2000
LABEL = pq.PLATFORM_LABEL


QUA_DAI_PATH = APP_DIR / "video_qua_dai.json"   # danh sách video > 3 phút bị bỏ qua khi bóc băng


def _doc_qua_dai():
    try:
        d = json.loads(QUA_DAI_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _ghi_qua_dai(nguon, path, giay, gioi_han):
    """Ghi lại video dài hơn giới hạn: link/đường dẫn gốc, file đã tải (nếu từ Drive), thời lượng."""
    muc = {"nguon": nguon, "file": str(path), "giay": round(giay), "thoi_luong": f"{int(giay // 60)}:{int(giay % 60):02d}",
           "gioi_han_phut": gioi_han // 60, "luc": datetime.now().strftime("%d/%m/%Y %H:%M")}
    with S.lock:
        S.qua_dai = [m for m in S.qua_dai if m.get("nguon") != nguon]
        S.qua_dai.insert(0, muc)
        S.qua_dai = S.qua_dai[:200]
        QUA_DAI_PATH.write_text(json.dumps(S.qua_dai, ensure_ascii=False, indent=1), encoding="utf-8")
    return muc


class State:
    """Trạng thái dùng chung giữa các request và worker (khoá bằng lock)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.cfg = chrome_cdp.load_config()
        if not isinstance(self.cfg.get("platforms"), dict):
            self.cfg["platforms"] = {}
        self.items = pq.load_queue()
        self.logs = []            # [(seq, "dòng nhật ký")] — web poll lấy phần sau seq đã có
        self.log_seq = 0
        self.running = False
        self.current = ""         # nền tảng/việc đang chạy, hiện trên thanh trên cùng
        self.stop_flag = threading.Event()
        self.ext_ok = {name: self._ext_installed(name) for name in pq.PLATFORMS}
        # việc "tạo nội dung bằng AI" (bóc băng + Gemini): chạy nền, 1 việc một lúc
        self.seo = {"status": "idle", "job": 0, "buoc": "", "nguon": "", "ket_qua": None, "loi": ""}
        self.seo_running = False
        self.qua_dai = _doc_qua_dai()      # video dài hơn 3 phút đã bỏ qua (lưu link lại)

    def _ext_installed(self, name):
        try:
            return chrome_cdp.extension_installed(chrome_cdp.platform_config(self.cfg, name))
        except Exception:
            return False

    def refresh_ext(self, name):
        with self.lock:
            self.ext_ok[name] = self._ext_installed(name)

    def log(self, msg):
        with self.lock:
            self.log_seq += 1
            self.logs.append((self.log_seq, str(msg)))
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[:len(self.logs) - MAX_LOG_LINES]


S = State()


# ------------------------------------------------------------------ nền tảng
def platform_cfg(name):
    return chrome_cdp.platform_config(S.cfg, name)


def browser_name(pcfg):
    p = (pcfg.get("chrome_path") or "").lower()
    if "coccoc" in p:
        return "Cốc Cốc"
    if "msedge" in p:
        return "Edge"
    if "brave" in p:
        return "Brave"
    return "Chrome"


def effective_hashtags():
    """Hashtag cho TikTok/Zalo: ô 'Hashtag' nếu có, không thì dòng cuối mô tả (nếu toàn hashtag)."""
    raw = (S.cfg.get("default_hashtags") or "").strip()
    if raw:
        return [t if t.startswith("#") else "#" + t for t in raw.split() if t.strip("#")]
    return hashtags_from_text(S.cfg.get("default_desc") or "")


def _valid_platform(name):
    name = (name or "youtube").strip().lower()
    if name not in pq.PLATFORMS:
        raise ValueError(f"Nền tảng không hợp lệ: {name}")
    return name


def _set_token(name, token):
    """Lưu token extension cho nền tảng (YouTube: cả khoá cấp cao nhất lẫn platforms.youtube)."""
    tok = chrome_cdp.normalize_token(token or "")
    pfs = S.cfg["platforms"]
    if name == "youtube":
        S.cfg["extension_token"] = tok
        if isinstance(pfs.get("youtube"), dict):
            pfs["youtube"]["extension_token"] = tok
    else:
        if not isinstance(pfs.get(name), dict):
            pfs[name] = {}
        pfs[name]["extension_token"] = tok


def _platform_info():
    out = {}
    for name in pq.PLATFORMS:
        pcfg = platform_cfg(name)
        pdata = S.cfg["platforms"].get(name) or {}
        if name == "youtube":
            acc, acc_url = S.cfg.get("channel_name") or "", S.cfg.get("channel_url") or ""
        else:
            acc, acc_url = pdata.get("account") or "", pdata.get("account_url") or ""
        out[name] = {
            "label": LABEL[name],
            "browser": browser_name(pcfg),
            "profile": pcfg.get("profile_dir") or "",
            "ext_ok": bool(S.ext_ok.get(name)),
            "token": pcfg.get("extension_token") or "",
            "account": acc,
            "account_url": acc_url,
            "checked_at": pdata.get("checked_at") or "",
        }
    return out


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
            "platforms": it["platforms"],
            "pf": {p: dict(it["pf"][p]) for p in it["platforms"]},
        } for it in S.items]
        return {
            "running": S.running,
            "current": S.current,
            "ext_ok": bool(S.ext_ok.get("youtube")),
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
            "hashtags_raw": S.cfg.get("default_hashtags") or "",
            "hashtags": " ".join(effective_hashtags()),
            "default_platforms": pq.normalize_platforms(S.cfg.get("default_platforms") or pq.PLATFORMS),
            "platforms": _platform_info(),
            "seo": dict(S.seo),
            "qua_dai": list(S.qua_dai[:20]),
            "items": items,
            "logs": [t for seq, t in S.logs if seq > after],
            "log_seq": S.log_seq,
        }


# ------------------------------------------------------------------ tạo nội dung bằng AI
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".m4v")


def api_list_downloads(_data):
    """Danh sách video trong thư mục Downloads (mới nhất trước) để chọn nhanh."""
    from drive_download import DOWNLOADS
    folder = Path(DOWNLOADS)
    files = []
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in VIDEO_EXT:
                st = p.stat()
                files.append({"name": p.name, "path": str(p), "size_mb": round(st.st_size / 1048576, 1),
                              "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m %H:%M"),
                              "_t": st.st_mtime})
    except Exception as e:
        return {"ok": False, "msg": f"Không đọc được Downloads: {e}"}
    files.sort(key=lambda f: f["_t"], reverse=True)
    for f in files:
        f.pop("_t", None)
    return {"ok": True, "files": files[:60], "folder": str(folder)}


def _seo_set(**kw):
    with S.lock:
        S.seo.update(kw)


def _seo_job(nguon):
    """Nền: (tải Drive) -> bóc băng large-v3-turbo -> Gemini (profile 'gemini' hoặc Zalo) -> kết quả."""
    import gemini_seo
    import nhan_dien_giong
    pw = page = None
    try:
        path = nguon
        if pq.is_drive(nguon):
            _seo_set(buoc="Đang tải video từ Google Drive...")
            path = download_drive(nguon, log=S.log)
        if not Path(path).exists():
            raise FileNotFoundError(f"Không thấy file video: {path}")
        _seo_set(buoc="Đang bóc băng giọng nói (large-v3-turbo)...")
        S.log(f"[AI] Bóc băng: {Path(path).name}")
        try:
            _, doan = nhan_dien_giong.nhan_dien(path, log=S.log)
        except nhan_dien_giong.VideoQuaDai as e:
            muc = _ghi_qua_dai(nguon, e.path, e.giay, e.gioi_han)
            _seo_set(status="error", buoc="Bỏ qua: video dài hơn 3 phút",
                     loi=f"Video dài hơn 3 phút ({muc['thoi_luong']}) — đã dừng và lưu link vào danh sách 'Video quá 3 phút'.")
            S.log(f"[AI] ⏹ {e} — đã lưu link: {nguon}")
            return
        van_ban = nhan_dien_giong.van_ban_co_moc(doan)
        if len(van_ban) < 50:
            raise RuntimeError("Bản bóc băng quá ngắn — video không có tiếng?")
        _seo_set(buoc="Đang nối Gemini (trình duyệt profile Zalo)...")
        pcfg = chrome_cdp.platform_config(S.cfg, "gemini")
        chrome_cdp.launch_chrome(pcfg, S.log)
        pw, _b, page = chrome_cdp.connect_playwright(pcfg, S.log)
        _seo_set(buoc="Gemini đang viết nội dung (3-6 phút)...")
        kq = gemini_seo.tao_noi_dung(page, van_ban, log=S.log)
        kq = {k: v for k, v in kq.items() if k != "tho"}
        kq["file"] = str(path)
        kq["boc_bang"] = van_ban
        _seo_set(status="done", buoc="Xong", ket_qua=kq, loi="")
        S.log(f"[AI] ✓ Xong: {kq.get('tieu_de') or '(không có tiêu đề)'}")
    except Exception as e:                  # noqa: BLE001
        _seo_set(status="error", buoc="Lỗi", loi=str(e)[:400])
        S.log(f"[AI] ✗ {e}")
    finally:
        if pw is not None:
            try:
                chrome_cdp.disconnect(pw, page=page)     # đóng tab Gemini, không để mở chồng chất
            except Exception:
                pass
        with S.lock:
            S.seo_running = False


def api_tao_noi_dung(data):
    nguon = (data.get("source") or "").strip().strip('"')
    if not nguon:
        return {"ok": False, "msg": "Chọn video trong Downloads hoặc dán link Drive."}
    with S.lock:
        if S.running:
            return {"ok": False, "msg": "Đang đăng video — chờ xong rồi tạo nội dung (dùng chung trình duyệt)."}
        if S.seo_running:
            return {"ok": False, "msg": "Đang tạo nội dung cho một video khác, chờ xong đã."}
        S.seo_running = True
        S.seo = {"status": "running", "job": S.seo["job"] + 1, "buoc": "Bắt đầu...", "nguon": nguon,
                 "ket_qua": None, "loi": ""}
    threading.Thread(target=_seo_job, args=(nguon,), daemon=True).start()
    return {"ok": True, "msg": "Bắt đầu: bóc băng rồi gửi Gemini — theo dõi ở Nhật ký."}


def api_add_seo_item(data):
    """Thêm 1 video vào hàng đợi kèm tiêu đề/mô tả/thẻ/hashtag RIÊNG (ưu tiên hơn mặc định của tab)."""
    link = (data.get("link") or "").strip()
    title = " ".join((data.get("title") or "").split())
    if not link or not title:
        return {"ok": False, "msg": "Thiếu video hoặc tiêu đề."}
    sel = data.get("platforms")
    if sel is not None and not sel:
        return {"ok": False, "msg": "Chọn ít nhất một nền tảng."}
    platforms = pq.normalize_platforms(sel or S.cfg.get("default_platforms") or pq.PLATFORMS)
    if data.get("times") is not None:        # web gửi kèm khung giờ của tab; gọi API tay thì dùng lịch đã lưu
        err = _apply_schedule(data.get("times"), data.get("start"))
        if err:
            return {"ok": False, "msg": err}
    if not S.cfg.get("schedule_times"):
        return {"ok": False, "msg": "Chưa có khung giờ công bố — nhập ở mục Lịch (ví dụ 08:00, 19:00)."}
    with S.lock:
        if any(it["link"] == link for it in S.items):
            return {"ok": False, "msg": "Video này đã có trong hàng đợi."}
        it = pq.new_item(link, title, platforms)
        it["desc"] = (data.get("desc") or "").strip()
        it["tags"] = (data.get("tags") or "").strip()
        it["hashtags"] = " ".join((data.get("hashtags") or "").split())
        S.items.append(it)
        pq.assign_schedule(S.items, S.cfg["schedule_times"], pq.parse_start(S.cfg["schedule_start"]))
        pq.save_queue(S.items)
    S.log(f"✓ Thêm vào hàng đợi (nội dung AI): {title}")
    return {"ok": True, "msg": f"Đã thêm: {title}"}


# ------------------------------------------------------------------ lưu config
def api_save_token(data):
    name = _valid_platform(data.get("platform"))
    with S.lock:
        _set_token(name, data.get("token"))
        chrome_cdp.save_config(S.cfg)
    return {"ok": True, "msg": f"Đã lưu token extension ({LABEL[name]}) vào config.json."}


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


def _apply_defaults(data):
    S.cfg["default_desc"] = (data.get("desc") or "").strip()
    S.cfg["default_playlist"] = (data.get("playlist") or "").strip()
    S.cfg["default_tags"] = (data.get("tags") or "").strip()
    S.cfg["default_kids"] = bool(data.get("kids"))
    if "hashtags" in data:
        S.cfg["default_hashtags"] = " ".join((data.get("hashtags") or "").split())


def api_save_defaults(data):
    with S.lock:
        _apply_defaults(data)
        chrome_cdp.save_config(S.cfg)
    return {"ok": True, "msg": "Đã lưu thông tin mặc định."}


def api_save_hashtags(data):
    with S.lock:
        S.cfg["default_hashtags"] = " ".join((data.get("hashtags") or "").split())
        chrome_cdp.save_config(S.cfg)
        tags = effective_hashtags()
    return {"ok": True, "hashtags": " ".join(tags),
            "msg": ("Hashtag TikTok/Zalo: " + " ".join(tags)) if tags else
                   "Đã lưu — hiện KHÔNG có hashtag (ô trống và dòng cuối mô tả không phải hashtag)."}


# ------------------------------------------------------------------ hàng đợi
def api_add_links(data):
    entries = pq.parse_entries(data.get("text") or "")
    if not entries:
        return {"ok": False, "msg": "Không thấy link Drive hay file hợp lệ nào."}
    sel = data.get("platforms")
    if sel is not None and not sel:
        return {"ok": False, "msg": "Chọn ít nhất một nền tảng (YouTube / TikTok / Zalo)."}
    platforms = pq.normalize_platforms(sel or S.cfg.get("default_platforms") or pq.PLATFORMS)
    err = _apply_schedule(data.get("times"), data.get("start"))
    if err:
        return {"ok": False, "msg": err}
    with S.lock:
        S.cfg["default_platforms"] = platforms
        chrome_cdp.save_config(S.cfg)
        existing = {it["link"] for it in S.items}
        added = 0
        for link, title in entries:
            if link in existing:
                continue
            S.items.append(pq.new_item(link, title, platforms))
            existing.add(link)
            added += 1
        pq.assign_schedule(S.items, S.cfg["schedule_times"], pq.parse_start(S.cfg["schedule_start"]))
        pq.save_queue(S.items)
    names = ", ".join(LABEL[p] for p in platforms)
    S.log(f"✓ Thêm {added} video vào hàng đợi → {names} (bỏ {len(entries) - added} trùng).")
    return {"ok": True, "msg": f"Đã thêm {added} video → {names} (bỏ {len(entries) - added} trùng)."}


def api_set_title(data):
    title = " ".join((data.get("title") or "").split())
    with S.lock:
        for it in S.items:
            if it["id"] == data.get("id"):
                if pq.is_running(it):
                    return {"ok": False, "msg": "Mục này đang đăng — đợi xong rồi sửa."}
                it["title"] = title
                pq.save_queue(S.items)
                return {"ok": True, "msg": "Đã đổi tiêu đề." if title else "Đã xoá tiêu đề (sẽ tạm dùng tên file)."}
    return {"ok": False, "msg": "Không thấy mục này."}


def api_reassign(data):
    err = _apply_schedule(data.get("times"), data.get("start"))
    if err:
        return {"ok": False, "msg": err}
    with S.lock:
        pq.assign_schedule(S.items, S.cfg["schedule_times"],
                           pq.parse_start(S.cfg["schedule_start"]), reassign=True)
        pq.save_queue(S.items)
    S.log("✓ Đã xếp lại giờ công bố cho các mục đang chờ (mục đã lên lịch ở một nền tảng giữ giờ cũ).")
    return {"ok": True, "msg": "Đã xếp lại giờ công bố."}


def api_delete(data):
    sel = set(data.get("ids") or [])
    if not sel:
        return {"ok": False, "msg": "Chưa chọn dòng nào."}
    with S.lock:
        S.items = [it for it in S.items if it["id"] not in sel or pq.is_running(it)]
        pq.save_queue(S.items)
    return {"ok": True, "msg": "Đã xoá các dòng chọn."}


def api_clear_finished(_data):
    with S.lock:
        S.items = [it for it in S.items if it["status"] not in (pq.STATUS_DONE, pq.STATUS_ERROR)]
        pq.save_queue(S.items)
    return {"ok": True, "msg": "Đã dọn các mục xong/lỗi."}


def api_retry_errors(data):
    only = [_valid_platform(data["platform"])] if data.get("platform") else None
    with S.lock:
        n = pq.reset_errors(S.items, only)
        pq.save_queue(S.items)
    if not n:
        return {"ok": False, "msg": "Không có mục nào đang lỗi" + (f" ở {LABEL[only[0]]}." if only else ".")}
    S.log(f"↻ Đưa {n} ô lỗi về 'chờ'" + (f" ({LABEL[only[0]]})" if only else "") + " — bấm Bắt đầu đăng để làm lại.")
    return {"ok": True, "msg": f"Đã đưa {n} ô lỗi về chờ — bấm Bắt đầu đăng để làm lại."}


# ------------------------------------------------------------------ hành động
def api_check_connection(data):
    name = _valid_platform(data.get("platform"))
    with S.lock:
        if S.running:
            return {"ok": False, "msg": "Đang chạy việc khác — chờ xong đã."}
        if "token" in data:
            _set_token(name, data.get("token"))
            chrome_cdp.save_config(S.cfg)
        S.running = True
        S.current = f"kiểm tra {LABEL[name]}"
    pcfg = platform_cfg(name)

    def work():
        pw = page = None
        giu_tab = {"v": False}          # True = chưa đăng nhập -> để tab mở cho người dùng đăng nhập
        try:
            S.log(f"===== Kiểm tra {LABEL[name]} — {browser_name(pcfg)} profile '{pcfg['profile_dir']}' =====")
            chrome_cdp.launch_chrome(pcfg, log=S.log)
            pw, _browser, page = chrome_cdp.connect_playwright(pcfg, log=S.log)
            if name == "youtube":
                info = youtube_upload.get_channel_info(page, log=S.log)
                if not info["logged_in"]:
                    S.log("❌ CHƯA đăng nhập YouTube — hãy đăng nhập Google trong tab Chrome vừa mở.")
                    giu_tab["v"] = True
                else:
                    with S.lock:
                        S.cfg["channel_name"] = info["name"] or S.cfg.get("channel_name") or ""
                        S.cfg["channel_url"] = info["url"]
                        chrome_cdp.save_config(S.cfg)
                    S.log(f"✓ ĐÃ đăng nhập — kênh: {info['name']}  ({info['url']})")
            else:
                mod = tiktok_upload if name == "tiktok" else zalo_upload
                url = tiktok_upload.UPLOAD_URL if name == "tiktok" else zalo_upload.CREATOR_URL
                S.log(f"Mở {url} ...")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                try:
                    mod._check_logged_in(page)
                    acc, ok = "đã đăng nhập", True
                except RuntimeError as e:
                    acc, ok = "CHƯA đăng nhập", False
                    giu_tab["v"] = True
                    S.log(f"❌ {e}")
                with S.lock:
                    S.cfg["platforms"].setdefault(name, {})
                    S.cfg["platforms"][name]["account"] = acc
                    S.cfg["platforms"][name]["account_url"] = page.url
                    S.cfg["platforms"][name]["checked_at"] = datetime.now().strftime("%d/%m %H:%M")
                    chrome_cdp.save_config(S.cfg)
                if ok:
                    S.log(f"✓ {LABEL[name]}: ĐÃ đăng nhập trong profile '{pcfg['profile_dir']}' ({page.url}).")
        except Exception as e:
            S.log(f"❌ Lỗi: {e}")
        finally:
            # chưa đăng nhập thì để tab mở cho người dùng đăng nhập; còn lại đóng tab
            chrome_cdp.disconnect(pw, page=None if giu_tab["v"] else page)
            S.refresh_ext(name)
            with S.lock:
                S.running = False
                S.current = ""

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "msg": f"Đang kiểm tra kết nối {LABEL[name]} — xem Nhật ký."}


def api_start(data):
    sel = data.get("platforms")
    only = pq.normalize_platforms(sel) if sel else list(pq.PLATFORMS)
    with S.lock:
        if S.running:
            return {"ok": False, "msg": "Đang chạy rồi."}
        if S.seo_running:
            return {"ok": False, "msg": "Đang tạo nội dung bằng AI (dùng chung trình duyệt) — chờ xong rồi bắt đầu đăng."}
        counts = {p: sum(1 for it in S.items if p in pq.pending_platforms(it, only)) for p in only}
        if not any(counts.values()):
            return {"ok": False, "msg": "Chưa có video nào đang chờ" +
                    (f" ở {', '.join(LABEL[p] for p in only)}." if sel else ".")}
        # lưu token + mặc định + lịch như GUI cũ làm trước khi chạy
        if "token" in data:
            _set_token("youtube", data.get("token"))
        _apply_defaults(data)
        times = pq.parse_times(data.get("times") or "")
        if not times:
            return {"ok": False, "msg": "Nhập ít nhất một khung giờ, ví dụ: 08:00, 19:00"}
        S.cfg["schedule_times"] = times
        S.cfg["schedule_start"] = pq.parse_start(data.get("start") or "").isoformat()
        chrome_cdp.save_config(S.cfg)
        S.stop_flag.clear()
        S.running = True
        S.current = ""
    dry = bool(data.get("dry_run"))
    threading.Thread(target=_worker, args=(dry, only), daemon=True).start()
    chi_tiet = ", ".join(f"{LABEL[p]} {n}" for p, n in counts.items() if n)
    return {"ok": True, "msg": ("Chạy thử 1 video mỗi nền tảng (không bấm nút cuối): " if dry else "Bắt đầu đăng: ") + chi_tiet}


def api_stop(_data):
    with S.lock:
        if not S.running:
            return {"ok": False, "msg": "Không có gì đang chạy."}
        S.stop_flag.set()
    S.log("⏹ Sẽ dừng sau khi xong video hiện tại.")
    return {"ok": True, "msg": "Sẽ dừng sau khi xong video hiện tại."}


# ------------------------------------------------------------------ worker
def _local_file(it):
    """Link Drive: tải về 1 lần (lưu it['file']) rồi dùng lại cho các nền tảng sau / lần chạy sau."""
    if not pq.is_drive(it["link"]):
        return it["link"]
    f = it.get("file")
    if f and Path(f).exists():
        S.log(f"Dùng file đã tải: {f}")
        return f
    f = download_drive(it["link"], log=S.log)
    with S.lock:
        it["file"] = f
        pq.save_queue(S.items)
    return f


def _upload(name, page, path, title, when, dry_run, it=None):
    """Mục có desc/tags/hashtags riêng (thêm từ 'Tạo nội dung bằng AI') thì ưu tiên hơn mặc định của tab."""
    it = it or {}
    if name == "youtube":
        desc = it.get("desc") or S.cfg.get("default_desc", "")
        tags_raw = it.get("tags") or S.cfg.get("default_tags") or ""
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return youtube_upload.upload_video(
            page, path, title, desc,
            playlist=S.cfg.get("default_playlist") or None, tags=tags,
            visibility="SCHEDULE", schedule_at=when,
            made_for_kids=bool(S.cfg.get("default_kids")), log=S.log, dry_run=dry_run)
    if it.get("hashtags"):
        hashtags = it["hashtags"].split() if isinstance(it["hashtags"], str) else list(it["hashtags"])
    elif it.get("desc") and hashtags_from_text(it["desc"]):
        hashtags = hashtags_from_text(it["desc"])
    else:
        hashtags = effective_hashtags()
    if name == "tiktok":
        return tiktok_upload.upload_video(page, path, title, hashtags, schedule_at=when, log=S.log, dry_run=dry_run)
    if name == "zalo":
        return zalo_upload.upload_video(page, path, title, hashtags, schedule_at=when, log=S.log, dry_run=dry_run)
    raise ValueError(name)


def _run_platform(name, dry_run):
    """Nối trình duyệt của một nền tảng, đăng mọi mục còn chờ ở nền tảng đó, ngắt.
    Trả về (số xong, số lỗi)."""
    label = LABEL[name]
    with S.lock:
        todo = [it for it in S.items if name in pq.pending_platforms(it)]
    if not todo:
        S.log(f"— {label}: không có mục nào chờ, bỏ qua.")
        return 0, 0
    pcfg = platform_cfg(name)
    with S.lock:
        S.current = label
    S.log(f"===== {label} — {browser_name(pcfg)} profile '{pcfg['profile_dir']}' — {len(todo)} video chờ =====")
    pw = page = None
    done = err = 0
    try:
        chrome_cdp.launch_chrome(pcfg, log=S.log)
        pw, _browser, page = chrome_cdp.connect_playwright(pcfg, log=S.log)
    except Exception as e:
        msg = "không nối được trình duyệt: " + str(e).splitlines()[0][:220]
        S.log(f"❌ {label}: {msg}")
        with S.lock:
            for it in todo:
                pq.set_pf(it, name, pq.STATUS_ERROR, error=msg)
            pq.save_queue(S.items)
        chrome_cdp.disconnect(pw)
        S.refresh_ext(name)
        return 0, len(todo)
    giu_tab = False                 # True = dừng vì lỗi, để tab mở cho người dùng xem
    try:
        for it in todo:
            if S.stop_flag.is_set():
                break
            with S.lock:
                if it not in S.items or it["pf"][name]["status"] != pq.STATUS_WAIT:
                    continue      # bị xoá / đổi trong lúc chạy
                # Giờ hẹn phải còn đủ xa; không thì xếp lại trước khi đăng (nếu chưa nền tảng nào dùng giờ đó)
                when = pq.parse_dt(it.get("scheduled_at"))
                if when is None or when < datetime.now() + pq.MIN_LEAD:
                    if pq.reschedulable(it):
                        it["scheduled_at"] = None
                        pq.assign_schedule(S.items, S.cfg["schedule_times"], pq.parse_start(S.cfg["schedule_start"]))
                        when = pq.parse_dt(it["scheduled_at"])
                        S.log(f"  Giờ hẹn cũ đã qua -> xếp lại: {pq.fmt_dt(it['scheduled_at'])}")
                    else:
                        S.log(f"  ⚠ Giờ hẹn {pq.fmt_dt(it.get('scheduled_at'))} đã gần/qua nhưng nền tảng khác đã lên lịch giờ này — vẫn thử.")
                pq.set_pf(it, name, pq.STATUS_RUNNING, error="")
                pq.save_queue(S.items)
            S.log(f"=== [{label}] {pq.short_link(it['link'])}  (công bố {pq.fmt_dt(it['scheduled_at'])}) ===")
            try:
                path = _local_file(it)
                title = it.get("title") or Path(path).stem
                link = _upload(name, page, path, title, when, dry_run, it)
                with S.lock:
                    it["title"] = title
                    if dry_run:
                        pq.set_pf(it, name, pq.STATUS_WAIT, result="(chạy thử xong, chưa đăng) " + (link or ""))
                    else:
                        pq.set_pf(it, name, pq.STATUS_DONE, result=link or "đã lên lịch", error="")
                    pq.save_queue(S.items)
                done += 1
            except Exception as e:
                msg = str(e).splitlines()[0][:300]
                with S.lock:
                    pq.set_pf(it, name, pq.STATUS_ERROR, error=msg)
                    pq.save_queue(S.items)
                err += 1
                S.log(f"❌ [{label}] LỖI: {msg}")
                try:
                    shot = str(APP_DIR / f"loi_gan_nhat_{name}.png")
                    page.screenshot(path=shot)
                    S.log(f"Ảnh chụp lúc lỗi: {shot}")
                except Exception:
                    pass
                S.log(f"Dừng {label} để bạn kiểm tra tab (hộp thoại vẫn mở, chưa bấm nút cuối) — chuyển sang nền tảng kế.")
                giu_tab = True
                break
            if dry_run:
                break
    finally:
        # xong việc thì đóng tab điều khiển; chạy thử hoặc dừng vì lỗi thì để tab mở cho người dùng xem
        chrome_cdp.disconnect(pw, page=None if (dry_run or giu_tab) else page)
        S.refresh_ext(name)
        with S.lock:
            S.current = ""
    return done, err


def _worker(dry_run, only):
    tong = {}
    try:
        for name in pq.PLATFORMS:
            if name not in only:
                continue
            if S.stop_flag.is_set():
                break
            tong[name] = _run_platform(name, dry_run)
        tom_tat = ", ".join(f"{LABEL[p]} {d} xong/{e} lỗi" for p, (d, e) in tong.items())
        if S.stop_flag.is_set():
            S.log(f"⏹ Đã dừng theo yêu cầu. {tom_tat}")
        elif dry_run:
            S.log(f"✓ Chạy thử xong: {tom_tat}. Các tab vẫn mở để bạn kiểm tra.")
        elif any(e for _d, e in tong.values()):
            S.log(f"⚠ Hết lượt đăng, có lỗi: {tom_tat}. Sửa xong bấm 'Đăng lại lỗi'.")
        else:
            S.log(f"🎉 Hết hàng đợi: {tom_tat}.")
    except Exception as e:
        S.log(f"❌ LỖI: {e}")
    finally:
        with S.lock:
            S.running = False
            S.current = ""


# ------------------------------------------------------------------ HTTP server
ROUTES = {
    "/api/save_token": api_save_token,
    "/api/save_schedule": api_save_schedule,
    "/api/save_defaults": api_save_defaults,
    "/api/save_hashtags": api_save_hashtags,
    "/api/add_links": api_add_links,
    "/api/list_downloads": api_list_downloads,
    "/api/tao_noi_dung": api_tao_noi_dung,
    "/api/add_seo_item": api_add_seo_item,
    "/api/set_title": api_set_title,
    "/api/reassign": api_reassign,
    "/api/delete": api_delete,
    "/api/clear_finished": api_clear_finished,
    "/api/retry_errors": api_retry_errors,
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
    S.log(f"✓ Server sẵn sàng tại {url} — một hàng đợi cho YouTube / TikTok / Zalo.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
