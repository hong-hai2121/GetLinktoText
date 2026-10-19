# -*- coding: utf-8 -*-
"""Hàng đợi video cần đăng (queue.json) + xếp khung giờ công bố mặc định.

Mỗi mục: {"id", "link" (link Drive hoặc đường dẫn file local), "title", "scheduled_at" (ISO),
"status", "result", "error", "added_at",
"platforms": ["youtube", "tiktok", "zalo"]  (đăng lên đâu),
"pf": {"youtube": {"status", "result", "error"}, ...}  (trạng thái RIÊNG từng nền tảng),
"file": đường dẫn file đã tải về (link Drive tải 1 lần, dùng lại cho các nền tảng sau)}.

"status" là trạng thái TỔNG gộp từ pf (xem overall_status) — app_gui.py và giao diện cũ vẫn đọc được.
Mục đời cũ (chưa có "platforms") = chỉ YouTube, trạng thái cũ chuyển vào pf["youtube"] khi nạp.

Giờ công bố dùng CHUNG cho mọi nền tảng của một mục (YouTube "Lên lịch", TikTok "Lên lịch",
Zalo "Hẹn giờ"): app tải video lên ngay, nền tảng tự công khai đúng giờ (máy không cần mở).
"""
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
QUEUE_PATH = APP_DIR / "queue.json"

STATUS_WAIT, STATUS_RUNNING, STATUS_DONE, STATUS_ERROR = "chờ", "đang đăng", "xong", "lỗi"
PLATFORMS = ("youtube", "tiktok", "zalo")          # thứ tự worker chạy
PLATFORM_LABEL = {"youtube": "YouTube", "tiktok": "TikTok", "zalo": "Zalo"}
DRIVE_RE = re.compile(r"https?://(?:drive|docs)\.google\.com/\S+")
MIN_LEAD = timedelta(minutes=20)   # YouTube chỉ nhận giờ hẹn đủ xa trong tương lai (TikTok: 15 phút)
MAX_DAYS = 365


def _pf_entry(status=STATUS_WAIT, result="", error=""):
    return {"status": status, "result": result or "", "error": error or ""}


def normalize_platforms(names):
    """Lọc + sắp xếp theo thứ tự chuẩn; rỗng/sai -> chỉ YouTube."""
    sel = {str(n).strip().lower() for n in (names or [])}
    out = [p for p in PLATFORMS if p in sel]
    return out or ["youtube"]


def normalize_item(it):
    """Bổ sung trường mới cho mục đời cũ (chỉ YouTube) và bảo đảm pf đủ nền tảng."""
    if "platforms" not in it:
        it["platforms"] = ["youtube"]
    it["platforms"] = normalize_platforms(it["platforms"])
    pf = it.get("pf")
    if not isinstance(pf, dict):
        pf = {}
        # trạng thái cũ (1 cột) -> cột youtube
        pf["youtube"] = _pf_entry(it.get("status") or STATUS_WAIT, it.get("result"), it.get("error"))
    for name in it["platforms"]:
        if name not in pf or not isinstance(pf[name], dict):
            pf[name] = _pf_entry()
        pf[name].setdefault("status", STATUS_WAIT)
        pf[name].setdefault("result", "")
        pf[name].setdefault("error", "")
        # app tắt giữa chừng -> mục còn "đang đăng" thì cho về chờ
        if pf[name]["status"] == STATUS_RUNNING:
            pf[name]["status"] = STATUS_WAIT
    it["pf"] = pf
    it.setdefault("title", "")
    it.setdefault("file", "")
    it.setdefault("giay", None)
    update_status(it)
    return it


NGUONG_SHORT_GIAY = 180      # YouTube: video <= 3 phút vào tab Shorts, dài hơn vào tab Video (app đăng như nhau)


def loai_video(it):
    """'short' (<= 3 phút) / 'video' (> 3 phút) / '' (chưa đo thời lượng)."""
    g = it.get("giay")
    if not g:
        return ""
    return "video" if g > NGUONG_SHORT_GIAY else "short"


def fmt_giay(g):
    return f"{int(g // 60)}:{int(g % 60):02d}" if g else ""


def load_queue():
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
    except Exception:
        return []
    return [normalize_item(it) for it in items if isinstance(it, dict) and it.get("link")]


def save_queue(items):
    QUEUE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def is_drive(s):
    return bool(DRIVE_RE.match((s or "").strip()))


def parse_entries(text):
    """Mỗi dòng một video: `link Drive hoặc đường dẫn file` [| tiêu đề]. Bỏ trùng link, giữ thứ tự.
    Trả về [(link, title)], title có thể rỗng (= tạm lấy tên file). Dấu | hoặc tab ngăn tiêu đề
    (tên file Windows không chứa |)."""
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        title = ""
        m = re.search(r"\s*[|\t]\s*", line)
        if m:
            line, title = line[:m.start()].strip(), line[m.end():].strip()
        line = line.strip('"').strip()
        m = DRIVE_RE.search(line)
        if m:
            val = m.group(0).rstrip(".,;)")
        elif os.path.isfile(line):
            val = os.path.abspath(line)
        else:
            continue
        if val not in seen:
            seen.add(val)
            out.append((val, title))
    return out


def new_item(link, title="", platforms=None):
    platforms = normalize_platforms(platforms or PLATFORMS)
    it = {"id": uuid.uuid4().hex[:8], "link": link, "title": title or "", "scheduled_at": None,
          "status": STATUS_WAIT, "result": "", "error": "", "file": "", "giay": None,
          "added_at": datetime.now().isoformat(timespec="seconds"),
          "platforms": platforms, "pf": {p: _pf_entry() for p in platforms}}
    return it


# ------------------------------------------------------------------ trạng thái từng nền tảng
def overall_status(it):
    """Gộp trạng thái các nền tảng: đang đăng > lỗi > xong (tất cả) > chờ."""
    sts = [it["pf"][p]["status"] for p in it["platforms"] if p in it.get("pf", {})]
    if not sts:
        return STATUS_WAIT
    if STATUS_RUNNING in sts:
        return STATUS_RUNNING
    if STATUS_ERROR in sts:
        return STATUS_ERROR
    if all(s == STATUS_DONE for s in sts):
        return STATUS_DONE
    return STATUS_WAIT


def update_status(it):
    """Cập nhật status/result/error tổng (để app_gui.py và code cũ đọc được)."""
    it["status"] = overall_status(it)
    parts, errs = [], []
    for p in it["platforms"]:
        e = it["pf"].get(p) or {}
        if e.get("result"):
            parts.append(f"{PLATFORM_LABEL[p]}: {e['result']}")
        if e.get("error"):
            errs.append(f"{PLATFORM_LABEL[p]}: {e['error']}")
    it["result"] = " · ".join(parts)
    it["error"] = " · ".join(errs)
    return it


def pending_platforms(it, only=None):
    """Nền tảng còn 'chờ' của mục (only: giới hạn trong danh sách nền tảng)."""
    return [p for p in it["platforms"]
            if it["pf"][p]["status"] == STATUS_WAIT and (only is None or p in only)]


def any_done(it):
    return any(it["pf"][p]["status"] == STATUS_DONE for p in it["platforms"])


def is_running(it):
    return any(it["pf"][p]["status"] == STATUS_RUNNING for p in it["platforms"])


def set_pf(it, name, status, result=None, error=None):
    e = it["pf"].setdefault(name, _pf_entry())
    e["status"] = status
    if result is not None:
        e["result"] = result
    if error is not None:
        e["error"] = error
    update_status(it)
    return it


def reset_errors(items, only=None):
    """'Đăng lại lỗi': nền tảng đang lỗi -> chờ (only: chỉ nền tảng đó). Trả về số ô được reset."""
    n = 0
    for it in items:
        for p in it["platforms"]:
            if it["pf"][p]["status"] == STATUS_ERROR and (only is None or p in only):
                it["pf"][p] = _pf_entry()
                n += 1
        update_status(it)
    return n


# ------------------------------------------------------------------ xếp giờ
def parse_times(text):
    """'08:00, 19:00' -> ['08:00', '19:00'] (đã sắp xếp, hợp lệ)."""
    times = set()
    for tok in re.split(r"[,\s;]+", text or ""):
        m = re.fullmatch(r"(\d{1,2})[:h.](\d{2})", tok.strip())
        if not m:
            continue
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            times.add(f"{h:02d}:{mi:02d}")
    return sorted(times)


def parse_start(text):
    """'YYYY-MM-DD' hoặc 'DD/MM/YYYY'; trống/sai -> hôm nay."""
    t = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return date.today()


def iter_slots(times, start_date, now=None):
    now = now or datetime.now()
    day = max(start_date, now.date())
    for _ in range(MAX_DAYS):
        for hhmm in times:
            h, mi = map(int, hhmm.split(":"))
            dt = datetime.combine(day, datetime.min.time()).replace(hour=h, minute=mi)
            if dt >= now + MIN_LEAD:
                yield dt
        day += timedelta(days=1)


def reschedulable(it):
    """Mục còn xếp lại giờ được: chưa nền tảng nào đã đăng/đang đăng (giờ đã lên lịch ở một
    nền tảng thì giữ nguyên để các nền tảng còn lại dùng cùng giờ)."""
    return not any_done(it) and not is_running(it) and it["status"] != STATUS_DONE


def assign_schedule(items, times, start_date=None, now=None, reassign=False, extra_taken=None):
    """Gán giờ công bố cho các mục đang chờ chưa có giờ (reassign=True: xếp lại tất cả mục chờ).
    Giờ của mục đã xếp/đang đăng/đã xong được giữ, không cấp trùng. extra_taken: thêm các giờ
    (ISO 'YYYY-MM-DDTHH:MM') đã dùng bởi mục không còn trong hàng đợi (app: config gio_da_dung)."""
    if not times:
        raise ValueError("Chưa có khung giờ nào (ví dụ: 08:00, 19:00)")
    now = now or datetime.now()
    start_date = start_date or now.date()
    targets = [it for it in items if reschedulable(it) and (reassign or not it.get("scheduled_at"))]
    taken = {it["scheduled_at"] for it in items if it.get("scheduled_at") and it not in targets}
    taken |= {g for g in (extra_taken or []) if isinstance(g, str)}
    slots = iter_slots(times, start_date, now)
    for it in targets:
        for dt in slots:
            iso = dt.isoformat(timespec="minutes")
            if iso not in taken:
                it["scheduled_at"] = iso
                taken.add(iso)
                break
    return items


def parse_dt(iso):
    return datetime.fromisoformat(iso) if iso else None


def fmt_dt(iso):
    dt = parse_dt(iso)
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def short_link(link, n=48):
    s = link.strip()
    if is_drive(s):
        m = re.search(r"/d/([\w-]+)|[?&]id=([\w-]+)", s)
        if m:
            return "drive:" + (m.group(1) or m.group(2))
    base = os.path.basename(s) if not s.startswith("http") else s
    return base if len(base) <= n else base[:n - 1] + "…"
