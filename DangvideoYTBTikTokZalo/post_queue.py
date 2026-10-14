# -*- coding: utf-8 -*-
"""Hàng đợi video cần đăng (queue.json) + xếp khung giờ công bố mặc định.

Mỗi mục: {"id", "link" (link Drive hoặc đường dẫn file local), "title", "scheduled_at" (ISO),
"status", "result", "error", "added_at"}. Giờ công bố là giờ YouTube "Lên lịch" — app tải video
lên ngay, YouTube tự công khai đúng giờ (máy không cần mở lúc đó).
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
DRIVE_RE = re.compile(r"https?://(?:drive|docs)\.google\.com/\S+")
MIN_LEAD = timedelta(minutes=20)   # YouTube chỉ nhận giờ hẹn đủ xa trong tương lai
MAX_DAYS = 365


def load_queue():
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_queue(items):
    QUEUE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def is_drive(s):
    return bool(DRIVE_RE.match((s or "").strip()))


def parse_entries(text):
    """Mỗi dòng một video: link Google Drive hoặc đường dẫn file trên máy. Bỏ trùng, giữ thứ tự."""
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.strip().strip('"').strip()
        if not line:
            continue
        m = DRIVE_RE.search(line)
        if m:
            val = m.group(0).rstrip(".,;)")
        elif os.path.isfile(line):
            val = os.path.abspath(line)
        else:
            continue
        if val not in seen:
            seen.add(val)
            out.append(val)
    return out


def new_item(link):
    return {"id": uuid.uuid4().hex[:8], "link": link, "title": "", "scheduled_at": None,
            "status": STATUS_WAIT, "result": "", "error": "",
            "added_at": datetime.now().isoformat(timespec="seconds")}


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


def assign_schedule(items, times, start_date=None, now=None, reassign=False):
    """Gán giờ công bố cho các mục đang chờ chưa có giờ (reassign=True: xếp lại tất cả mục chờ).
    Giờ của mục đã xếp/đang đăng/đã xong được giữ, không cấp trùng."""
    if not times:
        raise ValueError("Chưa có khung giờ nào (ví dụ: 08:00, 19:00)")
    now = now or datetime.now()
    start_date = start_date or now.date()
    targets = [it for it in items if it["status"] == STATUS_WAIT and (reassign or not it.get("scheduled_at"))]
    taken = {it["scheduled_at"] for it in items if it.get("scheduled_at") and it not in targets}
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
