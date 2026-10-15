# -*- coding: utf-8 -*-
"""Ghép video Flow — server cục bộ + giao diện WEB để chạy ghep_tieude.py hàng loạt.

Chạy:  python app.py  ->  tự mở trình duyệt tại http://127.0.0.1:8766
       (hoặc bấm đúp mo_gui.bat: cửa sổ trạng thái desktop app_gui.py, server chạy bên trong)
Giao diện nằm ở web/index.html; app.py chỉ là server: giữ hàng đợi, nhật ký và chạy worker.

Cách dùng:
  1. THƯ MỤC CLIP GỐC: kho clip ngắn quay bác sĩ, mặc định là thư mục "video gốc" cạnh tool (đã có 13 clip);
     "Chọn…" để dùng thư mục khác. Mỗi tập, ghep_tieude.py xáo ngẫu nhiên các clip rồi nối tới khi đủ
     giọng đọc (clip cuối dài hơn thì cắt) — xem mục 6 trong ghep_tieude.py.
  2. Dán danh sách link THƯ MỤC Drive (mỗi dòng một link; mỗi thư mục = một tập có đủ
     Hook / Tiêu đề / Minh họa / Giọng đọc / Kịch bản theo quy ước tên của ghep_tieude.py).
  3. Bấm Chạy: worker làm TỪNG tập một (GPU dùng chung): tải thư mục Drive về Downloads\\drive_<giờ>
     (drive_thu_muc.py, không dùng gdown) -> chạy ghep_tieude.py --thu-muc <đó> --phan-sau <thư mục clip>
     --seed <số ngẫu nhiên> trong tiến trình con -> video _full_ ra Downloads như chạy tay. Số seed và
     thứ tự clip đã dùng được ghi lại ở từng mục (chạy tay cùng --seed sẽ ra đúng thứ tự đó).

Hàng đợi + thư mục clip lưu ở ~/.ghep_video_flow.json (không để file dữ liệu trong thư mục dự án).
Server chỉ nghe trên 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import random
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import drive_thu_muc as dtm
from ghep_tieude import THU_MUC_GOC, TEN_VAI_TRO, downloads_dir, liet_ke_clip, unique_path, vai_tro_theo_ten

APP_DIR = Path(__file__).resolve().parent
INDEX_PATH = APP_DIR / "web" / "index.html"
TOOL = APP_DIR / "ghep_tieude.py"
HOST, PORT = "127.0.0.1", 8766                  # 8765 là của tool Đăng video
# kiểm thử: GHEP_VIDEO_SETTINGS = file trạng thái khác, GHEP_VIDEO_OUT = thư mục ra khác Downloads
SETTINGS_PATH = Path(os.environ.get("GHEP_VIDEO_SETTINGS") or Path.home() / ".ghep_video_flow.json")
MAX_LOG_LINES = 3000
VAI_BAT_BUOC = ("video", "tieude", "anh", "audio")   # thiếu thì cảnh báo ngay khi thêm link

CHO, DANG, XONG, LOI = "cho", "dang", "xong", "loi"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------------ tiện ích
def thu_muc_ra() -> Path:
    """Nơi tải thư mục Drive + ghi video ra: Downloads (hoặc GHEP_VIDEO_OUT khi kiểm thử)."""
    return Path(os.environ["GHEP_VIDEO_OUT"]) if os.environ.get("GHEP_VIDEO_OUT") else downloads_dir()


_KHO_CACHE: dict[str, tuple[tuple, list]] = {}   # thư mục -> (chữ ký file, [(tên, giây)]); web poll mỗi giây


def kho_clip(thu_muc: str) -> list[tuple[str, float]]:
    """[(tên clip, giây)] trong thư mục clip gốc; ffprobe từng file chỉ khi danh sách file/kích thước/mtime đổi."""
    d = Path(thu_muc) if thu_muc else None
    if not d or not d.is_dir():
        return []
    try:
        ky = tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in d.iterdir() if p.is_file()))
    except OSError:
        return []
    cu = _KHO_CACHE.get(thu_muc)
    if cu and cu[0] == ky:
        return cu[1]
    try:
        kq = [(p.name, round(giay, 2)) for p, giay in liet_ke_clip(d)]
    except Exception:
        kq = []
    _KHO_CACHE[thu_muc] = (ky, kq)
    return kq


def python_exe() -> str:
    """Tiến trình con dùng python.exe (kể cả khi server chạy bằng pythonw.exe qua mo_gui.bat)."""
    p = Path(sys.executable)
    if p.name.lower() == "pythonw.exe" and p.with_name("python.exe").exists():
        return str(p.with_name("python.exe"))
    return str(p)


def _giet_cay(p: subprocess.Popen):
    """Dừng tiến trình con + ffmpeg nó đang chạy."""
    try:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    except Exception:
        p.kill()


# ------------------------------------------------------------------ trạng thái
class State:
    """Trạng thái dùng chung giữa các request và worker (khoá bằng lock)."""

    def __init__(self):
        self.lock = threading.RLock()
        d = self._doc()
        # thư mục clip gốc: đã lưu -> dùng; chưa có -> "video gốc" cạnh tool (nếu tồn tại)
        self.goc_dir = d.get("goc_dir") or (str(THU_MUC_GOC) if THU_MUC_GOC.is_dir() else "")
        self.items = d.get("items", []) if isinstance(d.get("items"), list) else []
        for it in self.items:                      # lần trước tắt giữa chừng -> làm lại
            if it.get("status") == DANG:
                it.update(status=CHO, buoc="", loi="lần trước bị ngắt giữa chừng")
        self.next_id = max((it.get("id", 0) for it in self.items), default=0) + 1
        self.logs = []                             # [(seq, dòng)] — web poll phần sau seq đã có
        self.log_seq = 0
        self.running = False
        self.current = None                        # id mục đang chạy
        self.stop_flag = threading.Event()
        self.proc: subprocess.Popen | None = None

    @staticmethod
    def _doc() -> dict:
        try:
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def save(self):
        with self.lock:
            data = {"goc_dir": self.goc_dir, "items": self.items}
            tmp = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(SETTINGS_PATH)

    def log(self, msg):
        with self.lock:
            for dong in str(msg).splitlines() or [""]:
                self.log_seq += 1
                self.logs.append((self.log_seq, f"{time.strftime('%H:%M:%S')}  {dong}"))
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[:len(self.logs) - MAX_LOG_LINES]

    def find(self, item_id):
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            return None
        return next((it for it in self.items if it.get("id") == item_id), None)


S = State()


# ------------------------------------------------------------------ API
def state_payload(after: int) -> dict:
    with S.lock:
        kho = kho_clip(S.goc_dir)
        items = list(S.items)
        logs = [t for n, t in S.logs if n > after]
        if after == 0:
            logs = logs[-400:]
        return {
            "ok": True,
            "items": items,
            "logs": logs,
            "log_seq": S.log_seq,
            "running": S.running,
            "current": S.current,
            "stopping": S.running and S.stop_flag.is_set(),
            "goc": {"dir": S.goc_dir, "ton_tai": bool(S.goc_dir) and Path(S.goc_dir).is_dir(),
                    "mac_dinh": bool(S.goc_dir) and Path(S.goc_dir) == THU_MUC_GOC,
                    "clips": [{"ten": t, "giay": g} for t, g in kho],
                    "tong_giay": round(sum(g for _, g in kho), 1)},
            "downloads": str(thu_muc_ra()),
            "now": time.time(),
        }


def api_set_goc_dir(data):
    p = str(data.get("dir") or "").strip().strip('"')
    if not p or not Path(p).is_dir():
        return {"ok": False, "msg": f"Không thấy thư mục: {p or '(trống)'}"}
    p = str(Path(p))
    kho = kho_clip(p)
    if not kho:
        return {"ok": False, "msg": f"Thư mục {p} không có clip video nào (.mov/.mp4/.mkv)."}
    with S.lock:
        S.goc_dir = p
        S.save()
    msg = f"Thư mục clip gốc: {p} — {len(kho)} clip, tổng {sum(g for _, g in kho):.0f}s; mỗi tập xáo ngẫu nhiên tới đủ giọng đọc."
    S.log(msg)
    return {"ok": True, "msg": msg}


_DIALOG = threading.Lock()


def api_chon_thu_muc(_data):
    """Mở hộp thoại chọn thư mục (chạy trên máy này, nổi lên trên cùng)."""
    if not _DIALOG.acquire(blocking=False):
        return {"ok": False, "msg": "Hộp thoại chọn thư mục đang mở."}
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askdirectory(parent=root, title="Chọn thư mục chứa các clip gốc (quay bác sĩ)",
                                    initialdir=S.goc_dir or str(Path.home()))
        root.destroy()
    finally:
        _DIALOG.release()
    if not p:
        return {"ok": False, "msg": "Đã hủy chọn thư mục."}
    return api_set_goc_dir({"dir": p})


def _kiem_tra_bo(item_ids):
    """Chạy nền sau khi thêm link: lấy tên thư mục Drive + cảnh báo nếu thiếu file bắt buộc."""
    for item_id in item_ids:
        with S.lock:
            it = S.find(item_id)
            link = it and it.get("link")
        if not link:
            continue
        try:
            ten, files = dtm.liet_ke(dtm.folder_id(link))
            vai = {vai_tro_theo_ten(Path(n))[0] for _, n in files}
            thieu = [TEN_VAI_TRO[v] for v in VAI_BAT_BUOC if v not in vai]
            canh_bao = f"chưa thấy file: {', '.join(thieu)}" if thieu else ""
        except Exception as e:
            ten, files, canh_bao = "", [], f"không đọc được thư mục: {e}"
        with S.lock:
            it = S.find(item_id)
            if it is not None:
                if ten:
                    it["ten"] = ten
                it["so_file"] = len(files)
                it["canh_bao"] = canh_bao
                S.save()
        if canh_bao:
            S.log(f"⚠ [{item_id}] {ten or link}: {canh_bao}")
        time.sleep(0.3)


def api_add_links(data):
    text = str(data.get("text") or "")
    tokens = [t for t in re.split(r"[\s,;]+", text) if t]
    them, sai, trung = [], [], 0
    with S.lock:
        dang_co = {it.get("fid") for it in S.items if it.get("status") in (CHO, DANG)}
        for t in tokens:
            fid = dtm.folder_id(t)
            if not fid:
                sai.append(t)
                continue
            if fid in dang_co:
                trung += 1
                continue
            dang_co.add(fid)
            it = {"id": S.next_id, "link": t, "fid": fid, "ten": "", "status": CHO, "buoc": "",
                  "loi": "", "canh_bao": "", "them_luc": datetime.now().strftime("%d/%m %H:%M")}
            S.next_id += 1
            S.items.append(it)
            them.append(it["id"])
        S.save()
    if them:
        threading.Thread(target=_kiem_tra_bo, args=(them,), daemon=True).start()
    phan = [f"Đã thêm {len(them)} link"]
    if trung:
        phan.append(f"bỏ {trung} link đã có trong hàng đợi")
    if sai:
        la_sheet = any("docs.google.com" in s for s in sai)
        phan.append(f"{len(sai)} dòng không phải link THƯ MỤC Drive" + (" (link Sheet/Docs không dùng được, mở Sheet lấy link thư mục ở cột F)" if la_sheet else ""))
    if them and not kho_clip(S.goc_dir):
        phan.append("chưa có thư mục clip gốc — chọn rồi mới chạy được")
    msg = "; ".join(phan) + "."
    S.log(msg)
    return {"ok": bool(them), "msg": msg, "sai": sai[:10]}


def api_delete(data):
    with S.lock:
        it = S.find(data.get("id"))
        if it is None:
            return {"ok": False, "msg": "Không thấy mục."}
        if it.get("status") == DANG:
            return {"ok": False, "msg": "Mục đang chạy, bấm Dừng trước."}
        S.items.remove(it)
        S.save()
    return {"ok": True}


def api_retry(data):
    """{id} -> chạy lại 1 mục; không có id -> chạy lại mọi mục lỗi."""
    with S.lock:
        ds = [S.find(data["id"])] if data.get("id") is not None else [it for it in S.items if it.get("status") == LOI]
        n = 0
        for it in ds:
            if it and it.get("status") in (LOI, XONG):
                it.update(status=CHO, buoc="", loi="")      # chạy lại = xáo clip lần nữa (seed mới)
                n += 1
        S.save()
    return {"ok": True, "msg": f"Đưa {n} mục về chờ."}


def api_clear_done(_data):
    with S.lock:
        n = len(S.items)
        S.items = [it for it in S.items if it.get("status") != XONG]
        S.save()
        return {"ok": True, "msg": f"Đã bỏ {n - len(S.items)} mục xong khỏi danh sách (video vẫn ở Downloads)."}


def api_start(_data):
    with S.lock:
        if S.running:
            return {"ok": False, "msg": "Đang chạy rồi."}
        cho = [it for it in S.items if it.get("status") == CHO]
        if not cho:
            return {"ok": False, "msg": "Không có mục nào đang chờ."}
        if not kho_clip(S.goc_dir):
            return {"ok": False, "msg": "Chưa có thư mục clip gốc (hoặc thư mục không có video)."}
        S.running = True
        S.stop_flag.clear()
    threading.Thread(target=_worker, daemon=True, name="worker").start()
    return {"ok": True, "msg": f"Bắt đầu {len(cho)} tập."}


def api_stop(_data):
    with S.lock:
        if not S.running:
            return {"ok": False, "msg": "Không có gì đang chạy."}
        S.stop_flag.set()
        p = S.proc
    if p and p.poll() is None:
        _giet_cay(p)
    S.log("⏹ Đang dừng — mục đang làm sẽ về trạng thái chờ.")
    return {"ok": True}


def api_mo(data):
    """Mở file kết quả / thư mục của một mục bằng ứng dụng mặc định của Windows."""
    loai = data.get("loai")
    if loai == "downloads":
        os.startfile(thu_muc_ra())
        return {"ok": True}
    with S.lock:
        it = S.find(data.get("id"))
        khoa = {"video": "out", "thu_muc_video": "out", "srt": "srt", "preview": "preview", "tai": "thu_muc"}.get(loai)
        path = it and khoa and it.get(khoa)
    if not path or not Path(path).exists():
        return {"ok": False, "msg": "File không còn (đã xoá/di chuyển?)."}
    if loai == "thu_muc_video":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        os.startfile(path)
    return {"ok": True}


# ------------------------------------------------------------------ worker
_BUOC = [  # (đầu dòng log của ghep_tieude.py, tên bước hiện trên giao diện)
    ("Nhận diện khuôn mặt", "Nhận diện mặt"),
    ("Phân tích màu", "Chỉnh màu"),
    ("Phụ đề   : nhận diện", "Phụ đề"),
    ("Đang render", "Render"),
]
_BO_QUA_LOG = re.compile(r"^\s*(\d+%\||t=\s*[\d.]+s: mặt tại)")


def _doc_dong(it, s: str):
    """Cập nhật bước / đường dẫn kết quả từ một dòng log của ghep_tieude.py (gọi trong lock)."""
    for dau, buoc in _BUOC:
        if s.startswith(dau):
            it["buoc"] = buoc
    m = re.match(r"^(XONG|Xem trước|Phụ đề|Thời lượng|Phần sau)\s*:\s*(.+)$", s)
    if not m:
        return
    k, v = m.group(1), m.group(2).strip()
    if k == "XONG":
        it["out"] = v
    elif k == "Xem trước":
        it["preview"] = v
    elif k == "Phần sau" and "clip:" in v:         # "6 clip: 9.mov 4.2s → 14.mov 6.7s → ..."
        it["phan_sau"] = v
    elif k == "Phụ đề" and v.endswith("(đã đốt vào video)"):
        it["srt"] = v.split("  (")[0].strip()
    elif k == "Thời lượng":
        m2 = re.search(r"=\s*([\d.]+)s\s*$", v)
        if m2:
            it["thoi_luong"] = float(m2.group(1))


def _ket_thuc(it, status, loi="", t0=None):
    with S.lock:
        it.update(status=status, buoc="", loi=loi)
        if t0:
            it["giay_chay"] = round(time.time() - t0)
        S.save()


def _chay_muc(it):
    t0 = time.time()
    with S.lock:
        ten, link, goc = it.get("ten") or it["link"], it["link"], S.goc_dir
        seed = random.randrange(1, 10 ** 9)        # mỗi lần chạy một thứ tự clip khác; ghi lại để làm lại được
        it.update(status=DANG, buoc="Tải Drive", loi="", bat_dau=t0, out="", srt="", preview="", phan_sau="", seed=seed)
        S.current = it["id"]
        S.save()
    kho = kho_clip(goc)
    S.log(f"▶ [{it['id']}] {ten}  —  clip gốc: {Path(goc).name if goc else '(chưa có)'} ({len(kho)} clip), seed {seed}")
    if not kho:
        S.log(f"✗ [{it['id']}] thư mục clip gốc trống hoặc không tồn tại")
        return _ket_thuc(it, LOI, "Không có clip gốc (chọn lại thư mục clip).", t0)

    # 1) tải thư mục Drive
    try:
        dest = unique_path(thu_muc_ra(), "drive_" + time.strftime("%Y%m%d_%H%M%S"))
        ten_drive, _files = dtm.tai_thu_muc(link, dest, log=S.log, dung=S.stop_flag.is_set)
        with S.lock:
            it["ten"] = ten_drive or it.get("ten", "")
            it["thu_muc"] = str(dest)
            it["buoc"] = "Chuẩn bị"
    except Exception as e:
        if S.stop_flag.is_set():
            return _ket_thuc(it, CHO, "đã dừng khi đang tải")
        S.log(f"✗ [{it['id']}] tải Drive lỗi: {e}")
        return _ket_thuc(it, LOI, f"Tải Drive lỗi: {e}", t0)

    # 2) ghép bằng ghep_tieude.py (tiến trình riêng: ffmpeg/whisper nặng, lỗi không kéo sập server)
    cmd = [python_exe(), "-u", str(TOOL), "--thu-muc", str(dest), "--phan-sau", goc, "--seed", str(seed)]
    if os.environ.get("GHEP_VIDEO_OUT"):
        cmd += ["--out", str(thu_muc_ra())]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    cuoi: list[str] = []
    try:
        p = subprocess.Popen(cmd, cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)
    except Exception as e:
        return _ket_thuc(it, LOI, f"Không chạy được ghep_tieude.py: {e}", t0)
    with S.lock:
        S.proc = p
    for line in p.stdout:
        for part in line.rstrip("\n").split("\r"):      # thanh tiến độ ghi đè bằng \r
            s = part.rstrip()
            if not s.strip() or _BO_QUA_LOG.match(s):
                continue
            cuoi = (cuoi + [s])[-20:]
            S.log("   " + s)
            with S.lock:
                _doc_dong(it, s)
    rc = p.wait()
    with S.lock:
        S.proc = None
        out = it.get("out")
    if S.stop_flag.is_set():
        S.log(f"⏹ [{it['id']}] dừng giữa chừng, để lại trạng thái chờ.")
        return _ket_thuc(it, CHO, "đã dừng giữa chừng")
    if rc == 0 and out and Path(out).exists():
        S.log(f"✓ [{it['id']}] XONG sau {round(time.time() - t0)}s: {out}")
        return _ket_thuc(it, XONG, "", t0)
    ly_do = next((s.strip() for s in reversed(cuoi) if s.strip() and not s.startswith(" ")), "") or f"mã thoát {rc}"
    S.log(f"✗ [{it['id']}] lỗi: {ly_do}")
    return _ket_thuc(it, LOI, ly_do, t0)


def _worker():
    xong = loi = 0
    try:
        while not S.stop_flag.is_set():
            with S.lock:
                it = next((x for x in S.items if x.get("status") == CHO), None)
            if it is None:
                break
            _chay_muc(it)
            with S.lock:
                st = it.get("status")
            xong += st == XONG
            loi += st == LOI
        if S.stop_flag.is_set():
            S.log(f"⏹ Đã dừng theo yêu cầu. {xong} xong, {loi} lỗi.")
        else:
            S.log(f"🎉 Hết hàng đợi: {xong} xong, {loi} lỗi." + (" Bấm 'Chạy lại mục lỗi' để thử lại." if loi else ""))
    except Exception as e:
        S.log(f"❌ LỖI worker: {e}")
    finally:
        with S.lock:
            S.running = False
            S.current = None
            S.proc = None
            S.save()


# ------------------------------------------------------------------ HTTP server
ROUTES = {
    "/api/set_goc_dir": api_set_goc_dir,
    "/api/chon_thu_muc": api_chon_thu_muc,
    "/api/add_links": api_add_links,
    "/api/delete": api_delete,
    "/api/retry": api_retry,
    "/api/clear_done": api_clear_done,
    "/api/start": api_start,
    "/api/stop": api_stop,
    "/api/mo": api_mo,
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


class _Server(ThreadingHTTPServer):
    # Mặc định HTTPServer bật SO_REUSEADDR -> trên Windows server thứ hai VẪN bind được cổng đang dùng
    # (hai server + hai worker cùng ghi một hàng đợi). Tắt đi và giữ cổng độc quyền.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def dang_chay_san() -> str | None:
    """Đã có server Ghép video chạy ở PORT (mở app lần hai)? -> url của nó, không thì None."""
    url = f"http://{HOST}:{PORT}/"
    try:
        with urlopen(url + "api/state?after=999999999", timeout=1.5) as r:
            j = json.loads(r.read().decode("utf-8"))
        return url if "items" in j and "goc" in j else None
    except Exception:
        return None


def make_server():
    """Mở server trên PORT; cổng bị chương trình khác chiếm thì lấy cổng trống bất kỳ.
    Trả về (httpd, url). Dùng chung cho main() và cửa sổ trạng thái app_gui.py
    (hai nơi đó gọi dang_chay_san() trước để không chạy hai bản cùng lúc)."""
    try:
        httpd = _Server((HOST, PORT), Handler)
    except OSError:
        httpd = _Server((HOST, 0), Handler)
    return httpd, f"http://{HOST}:{httpd.server_address[1]}/"


def dung_tat_ca():
    """Dừng worker + tiến trình con (khi tắt server)."""
    S.stop_flag.set()
    p = S.proc
    if p and p.poll() is None:
        _giet_cay(p)


def main():
    cu = dang_chay_san()
    if cu:
        print(f"Ghép video Flow đang chạy sẵn tại {cu} — mở lại giao diện đó.")
        webbrowser.open(cu)
        return
    httpd, url = make_server()
    print(f"Ghép video Flow — giao diện web: {url}   (Ctrl+C để thoát)")
    S.log(f"✓ Server sẵn sàng tại {url}")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        dung_tat_ca()


if __name__ == "__main__":
    main()
