# -*- coding: utf-8 -*-
"""Ghép video Flow — server cục bộ + giao diện WEB (menu tab dọc) để chạy ghep_tieude.py hàng loạt.

Chạy:  python app.py  ->  tự mở trình duyệt tại http://127.0.0.1:8766
       (hoặc bấm đúp mo_gui.bat / shortcut "Ghép video Flow": cửa sổ desktop app_gui.py nạp thẳng giao diện này)
Giao diện nằm ở web/index.html, 5 tab: Ghép video · Chỉnh sửa · Kết nối AI · Nhật ký · Cài đặt;
app.py chỉ là server: giữ hàng đợi, tùy chọn chỉnh sửa, nhật ký, chạy worker, dò trạng thái 3 AI.

Tab Chỉnh sửa = các tùy chọn dòng lệnh của ghep_tieude.py (bố cục, màu, âm thanh, phụ đề, seed, chế độ
máy, độ phân giải) lưu CHUNG cho mọi tập (`tuy_chon` trong file trạng thái) + "Xem trước": chạy
ghep_tieude.py --preview-only cho một tập (tải Drive nếu chưa có) -> ảnh bố cục + ảnh màu trước/sau
ghi vào %TEMP%/ghep_video_flow_xem_truoc và hiện ngay trong tab.
Tab Kết nối AI dùng hoi_claude / hoi_gpt / hoi_gemini ở gốc repo (đăng nhập qua CLI, không API key).

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
import tempfile
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
sys.path.insert(0, str(APP_DIR.parent))          # hoi_claude / hoi_gpt / hoi_gemini nằm ở gốc repo
import hoi_claude, hoi_gemini, hoi_gpt           # noqa: E402  (tab Kết nối AI)

INDEX_PATH = APP_DIR / "web" / "index.html"
TOOL = APP_DIR / "ghep_tieude.py"
HOST, PORT = "127.0.0.1", 8766                  # 8765 là của tool Đăng video
PHIEN_BAN = "2026-10-17"
# kiểm thử: GHEP_VIDEO_SETTINGS = file trạng thái khác, GHEP_VIDEO_OUT = thư mục ra khác Downloads
SETTINGS_PATH = Path(os.environ.get("GHEP_VIDEO_SETTINGS") or Path.home() / ".ghep_video_flow.json")
THU_MUC_XEM_TRUOC = Path(tempfile.gettempdir()) / "ghep_video_flow_xem_truoc"   # ảnh xem trước (tạm, không vào Downloads)
MAX_LOG_LINES = 3000
VAI_BAT_BUOC = ("video", "tieude", "anh", "audio")   # thiếu thì cảnh báo ngay khi thêm link
NHA_AI = {"claude": hoi_claude, "gpt": hoi_gpt, "gemini": hoi_gemini}   # thứ tự hiện ở tab Kết nối AI
AI_CHU_KY, AI_CHU_KY_NHANH, AI_NHANH_TRONG = 8.0, 2.5, 180   # giây: dò trạng thái AI thường / sau khi bấm Kết nối

# tùy chọn tab Chỉnh sửa = tham số dòng lệnh của ghep_tieude.py, áp CHUNG cho mọi tập
TUY_CHON_MAC_DINH = {
    "ti_le_tieude": 0.90,    # bề rộng tiêu đề / bề rộng video
    "khoang_cach": 0.20,     # cằm -> mép trên tiêu đề, theo chiều cao mặt
    "chinh_mau": True,       # chỉnh màu tự động kiểu CapCut Auto
    "chuan_am": True, "lufs": -14.0, "cua_so_khop": None, "lech_giong": 0.0,   # None = theo thời lượng hook
    "sub": True, "sub_font": "Arial", "sub_co": 11, "sub_le_duoi": 45, "model_sub": "",
    "seed": None,            # None = xáo clip ngẫu nhiên mỗi lần; số = cố định
    "che_do": "auto",        # auto (tự dò NVENC) | nhe | manh | cpu
    "do_phan_giai": 0,       # 0 = giữ kích thước hook (1080x1920) | 720
    # cảnh minh họa theo từ khóa (minh_hoa.py): kho = Google Sheet "Kho video minh họa" (tab Kho minh họa) hoặc CSV
    "minh_hoa": True,
    "minh_hoa_sheet": "https://docs.google.com/spreadsheets/d/1n_rCUBFRCLi5NlDZovoDvHZd3ETCLtjKeLNPxHOAqUY/edit?gid=0#gid=0",
    "minh_hoa_ai": "gpt",    # gpt | claude | gemini
    "minh_hoa_model": "",    # "" = model mặc định của CLI đó
    "minh_hoa_giay": 6.0,    # mỗi cảnh tối đa (giây)
    "minh_hoa_ti_le": 0.45,  # tổng minh họa tối đa / thời lượng phần sau
}
CHE_DO_HOP_LE = ("auto", "nhe", "manh", "cpu")
DO_PHAN_GIAI_HOP_LE = (0, 540, 720, 900)
AI_HOP_LE = ("gpt", "claude", "gemini")

CHO, DANG, XONG, LOI = "cho", "dang", "xong", "loi"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _an_cua_so_lenh_con():
    """Chạy bằng pythonw (không có console) thì MỌI lệnh con dạng console (ffprobe khi đọc kho clip,
    ffmpeg, taskkill, CLI AI...) tự mở một cửa sổ đen -> gắn CREATE_NO_WINDOW mặc định cho mọi
    subprocess.Popen trong tiến trình này. Giữ nguyên khi đã chọn CREATE_NEW_CONSOLE / DETACHED
    (cửa sổ đăng nhập AI, cài đặt CLI cố ý hiện ra)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.GetConsoleWindow():
            return                                 # có console (python.exe) -> lệnh con dùng chung, không bật cửa sổ
    except Exception:
        return
    da_chon = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    goc = subprocess.Popen.__init__

    def __init__(self, *a, creationflags=0, **kw):
        if not creationflags & da_chon:
            creationflags |= subprocess.CREATE_NO_WINDOW
        goc(self, *a, creationflags=creationflags, **kw)

    subprocess.Popen.__init__ = __init__


_an_cua_so_lenh_con()


# ------------------------------------------------------------------ tiện ích
def thu_muc_ra() -> Path:
    """Nơi tải thư mục Drive + ghi video ra: Cài đặt (thu_muc_ra) > GHEP_VIDEO_OUT (kiểm thử) > Downloads."""
    cfg = getattr(globals().get("S"), "thu_muc_ra_cfg", "")
    if cfg and Path(cfg).is_dir():
        return Path(cfg)
    return Path(os.environ["GHEP_VIDEO_OUT"]) if os.environ.get("GHEP_VIDEO_OUT") else downloads_dir()


def _so(v, kieu, mac_dinh, lo=None, hi=None):
    try:
        x = kieu(v)
    except (TypeError, ValueError):
        return mac_dinh
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def chuan_hoa_tuy_chon(d: dict) -> dict:
    """Ghép với mặc định + ép kiểu/kẹp khoảng (giao diện gửi lên chuỗi, file cũ có thể thiếu khóa)."""
    m = TUY_CHON_MAC_DINH
    d = d if isinstance(d, dict) else {}
    tc = {
        "ti_le_tieude": round(_so(d.get("ti_le_tieude"), float, m["ti_le_tieude"], 0.3, 1.0), 3),
        "khoang_cach": round(_so(d.get("khoang_cach"), float, m["khoang_cach"], -0.5, 1.5), 3),
        "chinh_mau": bool(d.get("chinh_mau", m["chinh_mau"])),
        "chuan_am": bool(d.get("chuan_am", m["chuan_am"])),
        "lufs": round(_so(d.get("lufs"), float, m["lufs"], -30.0, -6.0), 1),
        "cua_so_khop": None if d.get("cua_so_khop") in (None, "", "null") else _so(d.get("cua_so_khop"), float, None, 0.0, 600.0),
        "lech_giong": round(_so(d.get("lech_giong"), float, m["lech_giong"], -12.0, 12.0), 1),
        "sub": bool(d.get("sub", m["sub"])),
        "sub_font": (str(d.get("sub_font") or m["sub_font"]).strip() or m["sub_font"])[:60],
        "sub_co": round(_so(d.get("sub_co"), float, m["sub_co"], 4, 40), 1),
        "sub_le_duoi": _so(d.get("sub_le_duoi"), int, m["sub_le_duoi"], 0, 200),
        "model_sub": str(d.get("model_sub") or "").strip()[:80],
        "seed": None if d.get("seed") in (None, "", "null") else _so(d.get("seed"), int, None, 0, 2 ** 31 - 1),
        "che_do": d.get("che_do") if d.get("che_do") in CHE_DO_HOP_LE else m["che_do"],
        "do_phan_giai": _so(d.get("do_phan_giai"), int, m["do_phan_giai"]),
        "minh_hoa": bool(d.get("minh_hoa", m["minh_hoa"])),
        "minh_hoa_sheet": str(d.get("minh_hoa_sheet") if d.get("minh_hoa_sheet") is not None else m["minh_hoa_sheet"]).strip()[:500],
        "minh_hoa_ai": d.get("minh_hoa_ai") if d.get("minh_hoa_ai") in AI_HOP_LE else m["minh_hoa_ai"],
        "minh_hoa_model": str(d.get("minh_hoa_model") or "").strip()[:80],
        "minh_hoa_giay": round(_so(d.get("minh_hoa_giay"), float, m["minh_hoa_giay"], 2.5, 20.0), 1),
        "minh_hoa_ti_le": round(_so(d.get("minh_hoa_ti_le"), float, m["minh_hoa_ti_le"], 0.05, 0.9), 2),
    }
    if tc["do_phan_giai"] not in DO_PHAN_GIAI_HOP_LE:
        tc["do_phan_giai"] = m["do_phan_giai"]
    return tc


def args_tuy_chon(tc: dict) -> list[str]:
    """Tùy chọn -> tham số dòng lệnh ghep_tieude.py (không gồm --seed, worker tự quyết)."""
    a = ["--ti-le-tieude", str(tc["ti_le_tieude"]), "--khoang-cach", str(tc["khoang_cach"])]
    if not tc["chinh_mau"]:
        a.append("--khong-chinh-mau")
    if not tc["chuan_am"]:
        a.append("--khong-chuan-am")
    else:
        a += ["--lufs", str(tc["lufs"]), "--lech-giong", str(tc["lech_giong"])]
        if tc["cua_so_khop"] is not None:
            a += ["--cua-so-khop", str(tc["cua_so_khop"])]
    if not tc["sub"]:
        a.append("--khong-sub")
    else:
        a += ["--sub-font", tc["sub_font"], "--sub-co", str(tc["sub_co"]), "--sub-le-duoi", str(tc["sub_le_duoi"])]
        if tc["model_sub"]:
            a += ["--model-sub", tc["model_sub"]]
    a += {"nhe": ["--nhe"], "manh": ["--manh"], "cpu": ["--cpu"]}.get(tc["che_do"], [])
    if tc["do_phan_giai"]:
        a += ["--do-phan-giai", str(tc["do_phan_giai"])]
    if tc["minh_hoa"] and tc["minh_hoa_sheet"]:
        a += ["--minh-hoa", tc["minh_hoa_sheet"], "--minh-hoa-ai", tc["minh_hoa_ai"],
              "--minh-hoa-giay", str(tc["minh_hoa_giay"]), "--minh-hoa-ti-le", str(tc["minh_hoa_ti_le"])]
        if tc["minh_hoa_model"]:
            a += ["--minh-hoa-model", tc["minh_hoa_model"]]
    return a


def _chon_thu_muc_dialog(tieu_de: str, bat_dau: str) -> str:
    """Hộp thoại chọn thư mục của Windows (tkinter), nổi lên trên cùng; '' nếu hủy."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    p = filedialog.askdirectory(parent=root, title=tieu_de, initialdir=bat_dau or str(Path.home()))
    root.destroy()
    return p or ""


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
        self.tuy_chon = chuan_hoa_tuy_chon(d.get("tuy_chon") or {})
        self.thu_muc_ra_cfg = str(d.get("thu_muc_ra") or "")
        self.logs = []                             # [(seq, dòng)] — web poll phần sau seq đã có
        self.log_seq = 0
        self.running = False
        self.current = None                        # id mục đang chạy
        self.stop_flag = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.url = f"http://{HOST}:{PORT}/"       # make_server() ghi lại url thật
        # xem trước (tab Chỉnh sửa): một việc một lúc
        self.xem_truoc = {"status": "idle", "ten": "", "buoc": "", "preview": "", "mau": "", "loi": "", "luc": "", "phan_sau": ""}
        self.xem_truoc_proc: subprocess.Popen | None = None
        # Kết nối AI: trạng thái dò ở thread nền, web chỉ đọc bản mới nhất
        self.ai = {k: dict(ten=m.TEN, cli=m.CLI, cai=None, phien_ban="", ket_noi=False, email="", ghi_chu="đang dò...")
                   for k, m in NHA_AI.items()}
        self.ai_luc_do = 0.0
        self.ai_nhanh_den = 0.0
        self.ai_do_ngay = threading.Event()
        self.ai_phien = {k: None for k in NHA_AI}
        self.ai_dang_hoi: set[str] = set()
        self.ai_loi_xac_thuc: dict[str, str] = {}
        threading.Thread(target=self._vong_do_ai, daemon=True, name="do-ai").start()

    def _vong_do_ai(self):
        while True:
            for k, m in NHA_AI.items():
                try:
                    tt = m.trang_thai()
                except Exception as e:             # noqa: BLE001
                    tt = dict(ten=m.TEN, cli=m.CLI, cai=False, phien_ban="", ket_noi=False, email="", ghi_chu=f"lỗi dò: {e}")
                try:
                    tt["models"] = m.danh_sach_model() if tt.get("cai") else []
                except Exception:                  # noqa: BLE001
                    tt["models"] = []
                with self.lock:
                    self.ai[k] = tt
            with self.lock:
                self.ai_luc_do = time.time()
            self.ai_do_ngay.wait(AI_CHU_KY_NHANH if time.time() < self.ai_nhanh_den else AI_CHU_KY)
            self.ai_do_ngay.clear()

    @staticmethod
    def _doc() -> dict:
        try:
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def save(self):
        with self.lock:
            data = {"goc_dir": self.goc_dir, "items": self.items, "tuy_chon": self.tuy_chon,
                    "thu_muc_ra": self.thu_muc_ra_cfg}
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
            "tuy_chon": dict(S.tuy_chon),
            "tuy_chon_mac_dinh": dict(TUY_CHON_MAC_DINH),
            "xem_truoc": dict(S.xem_truoc),
            "ai": {"nha": [dict(S.ai[k], ma=k, dang_hoi=(k in S.ai_dang_hoi), loi_xac_thuc=S.ai_loi_xac_thuc.get(k, ""))
                           for k in NHA_AI],
                   "luc_do": time.strftime("%H:%M:%S", time.localtime(S.ai_luc_do)) if S.ai_luc_do else ""},
            "cai_dat": {"thu_muc_ra": S.thu_muc_ra_cfg, "thu_muc_ra_thuc": str(thu_muc_ra()),
                        "url": S.url, "phien_ban": PHIEN_BAN, "goc_mac_dinh": str(THU_MUC_GOC),
                        "file_trang_thai": str(SETTINGS_PATH), "thu_muc_xem_truoc": str(THU_MUC_XEM_TRUOC)},
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
        p = _chon_thu_muc_dialog("Chọn thư mục chứa các clip gốc (quay bác sĩ)", S.goc_dir)
    finally:
        _DIALOG.release()
    if not p:
        return {"ok": False, "msg": "Đã hủy chọn thư mục."}
    return api_set_goc_dir({"dir": p})


# ---- tab Chỉnh sửa
def api_save_tuy_chon(data):
    tc = chuan_hoa_tuy_chon(data.get("tuy_chon") or data)
    with S.lock:
        S.tuy_chon = tc
        S.save()
    S.log("Đã lưu tùy chọn chỉnh sửa: " + " ".join(args_tuy_chon(tc)) + (f" --seed {tc['seed']}" if tc["seed"] is not None else ""))
    return {"ok": True, "msg": "Đã lưu — áp dụng cho các tập chạy từ giờ.", "tuy_chon": tc}


def api_mac_dinh_tuy_chon(_data):
    with S.lock:
        S.tuy_chon = dict(TUY_CHON_MAC_DINH)
        S.save()
    S.log("Tùy chọn chỉnh sửa về mặc định.")
    return {"ok": True, "msg": "Đã về mặc định.", "tuy_chon": dict(TUY_CHON_MAC_DINH)}


def _xem_truoc_job(item_id):
    with S.lock:
        it = S.find(item_id)
        if it is None:
            S.xem_truoc.update(status="loi", loi="Không thấy tập.")
            return
        link, ten, thu_muc, goc, tc = it["link"], it.get("ten") or it["link"], it.get("thu_muc"), S.goc_dir, dict(S.tuy_chon)
        S.xem_truoc.update(status="dang", ten=ten, buoc="Tải Drive", preview="", mau="", loi="", phan_sau="")
    try:
        folder = Path(thu_muc) if thu_muc and Path(thu_muc).is_dir() else None
        if folder is None:
            dest = unique_path(thu_muc_ra(), "drive_" + time.strftime("%Y%m%d_%H%M%S"))
            ten_drive, _ = dtm.tai_thu_muc(link, dest, log=S.log)
            with S.lock:
                it["thu_muc"], it["ten"] = str(dest), ten_drive or it.get("ten", "")
                S.save()
            folder = dest
        THU_MUC_XEM_TRUOC.mkdir(parents=True, exist_ok=True)
        seed = tc["seed"] if tc["seed"] is not None else random.randrange(1, 10 ** 9)
        cmd = [python_exe(), "-u", str(TOOL), "--thu-muc", str(folder), "--phan-sau", goc, "--preview-only",
               "--out", str(THU_MUC_XEM_TRUOC), "--seed", str(seed), *args_tuy_chon(tc)]
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        with S.lock:
            S.xem_truoc["buoc"] = "Nhận diện mặt"
        p = subprocess.Popen(cmd, cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)
        with S.lock:
            S.xem_truoc_proc = p
        cuoi = []
        for line in p.stdout:
            for part in line.rstrip("\n").split("\r"):
                s = part.rstrip()
                if not s.strip() or _BO_QUA_LOG.match(s):
                    continue
                cuoi = (cuoi + [s])[-15:]
                S.log("   [xem trước] " + s)
                m = re.match(r"^(Xem trước|So sánh màu trước/sau|Phần sau|Phân tích màu)\s*:?\s*(.*)$", s)
                if m:
                    with S.lock:
                        k, v = m.group(1), m.group(2).strip()
                        if k == "Xem trước":
                            S.xem_truoc["preview"] = v
                            S.xem_truoc["buoc"] = "Phân tích màu"
                        elif k == "So sánh màu trước/sau":
                            S.xem_truoc["mau"] = v
                        elif k == "Phần sau":
                            S.xem_truoc["phan_sau"] = v
        rc = p.wait()
        with S.lock:
            S.xem_truoc_proc = None
            ok = rc == 0 and S.xem_truoc["preview"] and Path(S.xem_truoc["preview"]).exists()
            if ok:
                S.xem_truoc.update(status="xong", buoc="", luc=time.strftime("%H:%M:%S"))
            else:
                ly_do = next((s.strip() for s in reversed(cuoi) if s.strip()), "") or f"mã thoát {rc}"
                S.xem_truoc.update(status="loi", buoc="", loi=ly_do)
    except Exception as e:                         # noqa: BLE001
        with S.lock:
            S.xem_truoc.update(status="loi", buoc="", loi=str(e))
            S.xem_truoc_proc = None


def api_xem_truoc(data):
    """Xem trước bố cục + màu cho một tập (id; bỏ trống = tập đầu tiên trong hàng đợi), không render."""
    with S.lock:
        if S.xem_truoc["status"] == "dang":
            return {"ok": False, "msg": "Đang xem trước tập khác, chờ xong đã."}
        it = S.find(data.get("id")) if data.get("id") is not None else next((x for x in S.items), None)
        if it is None:
            return {"ok": False, "msg": "Hàng đợi trống — thêm link thư mục Drive trước."}
        if not kho_clip(S.goc_dir):
            return {"ok": False, "msg": "Chưa có thư mục clip gốc."}
        S.xem_truoc.update(status="dang", ten=it.get("ten") or it["link"], buoc="Chuẩn bị", preview="", mau="", loi="")
    threading.Thread(target=_xem_truoc_job, args=(it["id"],), daemon=True, name="xem-truoc").start()
    return {"ok": True, "msg": "Đang tạo ảnh xem trước (10–30 giây, không render video)."}


# ---- tab Cài đặt
def api_save_cai_dat(data):
    p = str(data.get("thu_muc_ra") or "").strip().strip('"')
    if p and not Path(p).is_dir():
        return {"ok": False, "msg": f"Không thấy thư mục: {p}"}
    with S.lock:
        S.thu_muc_ra_cfg = str(Path(p)) if p else ""
        S.save()
    msg = f"Thư mục kết quả: {thu_muc_ra()}" + ("" if p else " (mặc định Downloads)")
    S.log(msg)
    return {"ok": True, "msg": msg}


def api_chon_thu_muc_ra(_data):
    if not _DIALOG.acquire(blocking=False):
        return {"ok": False, "msg": "Hộp thoại chọn thư mục đang mở."}
    try:
        p = _chon_thu_muc_dialog("Chọn thư mục ghi video kết quả", str(thu_muc_ra()))
    finally:
        _DIALOG.release()
    if not p:
        return {"ok": False, "msg": "Đã hủy chọn thư mục."}
    return api_save_cai_dat({"thu_muc_ra": p})


# ---- tab Kết nối AI
def api_ai_lam_moi(_data):
    S.ai_do_ngay.set()
    return {"ok": True, "msg": "Đang dò lại trạng thái AI…"}


def api_ai_ket_noi(data):
    m = NHA_AI.get(data.get("ma"))
    if m is None:
        return {"ok": False, "msg": "Không rõ hãng AI."}
    m.dang_nhap()
    with S.lock:
        S.ai_nhanh_den = time.time() + AI_NHANH_TRONG
        S.ai_loi_xac_thuc.pop(data["ma"], None)
    S.ai_do_ngay.set()
    return {"ok": True, "msg": f"Đã mở cửa sổ đăng nhập {m.TEN}. Trong trình duyệt chọn tài khoản (Google) rồi quay lại đây."}


def api_ai_ngat(data):
    m = NHA_AI.get(data.get("ma"))
    if m is None:
        return {"ok": False, "msg": "Không rõ hãng AI."}
    msg = m.dang_xuat()
    with S.lock:
        S.ai_phien[data["ma"]] = None
    S.ai_do_ngay.set()
    return {"ok": True, "msg": f"Đã ngắt {m.TEN}. {msg}".strip()}


def api_ai_cai_dat(data):
    m = NHA_AI.get(data.get("ma"))
    if m is None:
        return {"ok": False, "msg": "Không rõ hãng AI."}
    m.cai_dat()
    with S.lock:
        S.ai_nhanh_den = time.time() + AI_NHANH_TRONG
    return {"ok": True, "msg": f"Đang cài {m.TEN} CLI trong cửa sổ lệnh: {m.LENH_CAI}"}


def api_ai_hoi(data):
    ma, cau_hoi = data.get("ma"), str(data.get("cau_hoi") or "").strip()
    model = str(data.get("model") or "").strip() or None      # None = mặc định của CLI
    m = NHA_AI.get(ma)
    if m is None:
        return {"ok": False, "msg": "Không rõ hãng AI."}
    if not cau_hoi:
        return {"ok": False, "msg": "Chưa gõ câu hỏi."}
    with S.lock:
        if ma in S.ai_dang_hoi:
            return {"ok": False, "msg": f"{m.TEN} đang trả lời câu trước."}
        S.ai_dang_hoi.add(ma)
        # đổi model giữa chừng = hội thoại mới (phiên CLI gắn với model lúc tạo)
        if S.ai_phien[ma] is None or getattr(S.ai_phien[ma], "model", None) != model:
            S.ai_phien[ma] = m.Phien(model=model)
        phien = S.ai_phien[ma]
    t0 = time.time()
    try:
        text = phien.hoi(cau_hoi)
        r = phien.lich_su[-1]
        with S.lock:
            S.ai_loi_xac_thuc.pop(ma, None)
        return {"ok": True, "text": text, "model": r.model, "giay": round(time.time() - t0, 1)}
    except Exception as e:                         # noqa: BLE001
        msg = str(e)
        # token hết hạn / chưa đăng nhập: `auth status` vẫn báo đã đăng nhập, chỉ lúc hỏi mới lộ ra
        if any(t in msg.lower() for t in ("expired", "authenticate", "unauthorized", "401", "chưa đăng nhập", "login")):
            with S.lock:
                S.ai_loi_xac_thuc[ma] = msg.splitlines()[0][:160]
        return {"ok": False, "msg": msg}
    finally:
        with S.lock:
            S.ai_dang_hoi.discard(ma)


def api_ai_hoi_thoai_moi(data):
    with S.lock:
        S.ai_phien[data.get("ma")] = None
    return {"ok": True, "msg": "Đã bắt đầu hội thoại mới."}


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
    if loai in ("downloads", "thu_muc_ra"):
        os.startfile(thu_muc_ra())
        return {"ok": True}
    if loai == "goc":
        if not S.goc_dir or not Path(S.goc_dir).is_dir():
            return {"ok": False, "msg": "Chưa có thư mục clip gốc."}
        os.startfile(S.goc_dir)
        return {"ok": True}
    if loai == "url":                              # mở link ở trình duyệt mặc định (cửa sổ desktop không có tab)
        url = str(data.get("url") or "")
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "msg": "Link không hợp lệ."}
        webbrowser.open(url)
        return {"ok": True}
    if loai == "duong_dan":                        # ảnh xem trước / file trong thư mục kết quả
        p = Path(str(data.get("path") or ""))
        if not _duoc_phep(p):
            return {"ok": False, "msg": "Không mở được đường dẫn này."}
        os.startfile(p)
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


def _duoc_phep(p: Path) -> bool:
    """Chỉ cho mở/xem file nằm trong thư mục xem trước hoặc thư mục kết quả."""
    try:
        p = p.resolve()
    except OSError:
        return False
    if not p.is_file():
        return False
    for goc in (THU_MUC_XEM_TRUOC, thu_muc_ra()):
        try:
            p.relative_to(goc.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


# ------------------------------------------------------------------ worker
_BUOC = [  # (đầu dòng log của ghep_tieude.py, tên bước hiện trên giao diện)
    ("Nhận diện khuôn mặt", "Nhận diện mặt"),
    ("Phân tích màu", "Chỉnh màu"),
    ("Phụ đề   : nhận diện", "Phụ đề"),
    ("Khớp lời :", "Khớp lời"),
    ("Minh họa : gpt", "Chọn minh họa"), ("Minh họa : claude", "Chọn minh họa"), ("Minh họa : gemini", "Chọn minh họa"),
    ("Đang render", "Render"),
]
_BO_QUA_LOG = re.compile(r"^\s*(\d+%\||t=\s*[\d.]+s: mặt tại)")


def _doc_dong(it, s: str):
    """Cập nhật bước / đường dẫn kết quả từ một dòng log của ghep_tieude.py (gọi trong lock)."""
    for dau, buoc in _BUOC:
        if s.startswith(dau):
            it["buoc"] = buoc
    m = re.match(r"^(XONG|Xem trước|Phụ đề|Thời lượng|Phần sau|Minh họa)\s*:\s*(.+)$", s)
    if not m:
        return
    k, v = m.group(1), m.group(2).strip()
    if k == "XONG":
        it["out"] = v
    elif k == "Xem trước":
        it["preview"] = v
    elif k == "Phần sau" and "clip:" in v:         # "6 clip: 9.mov 4.2s → 14.mov 6.7s → ..."
        it["phan_sau"] = v
    elif k == "Minh họa" and ("cảnh" in v and not v.endswith("...")):   # "3 cảnh: 12.3s ợ nóng (...)" / "không chèn cảnh nào (...)"
        it["minh_hoa"] = v
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
        ten, link, goc, tc = it.get("ten") or it["link"], it["link"], S.goc_dir, dict(S.tuy_chon)
        # seed cố định (tab Chỉnh sửa) hoặc mỗi lần chạy một thứ tự clip khác; ghi lại để làm lại được
        seed = tc["seed"] if tc["seed"] is not None else random.randrange(1, 10 ** 9)
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
    cmd = [python_exe(), "-u", str(TOOL), "--thu-muc", str(dest), "--phan-sau", goc, "--seed", str(seed),
           "--out", str(thu_muc_ra()), *args_tuy_chon(tc)]
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
    "/api/save_tuy_chon": api_save_tuy_chon,
    "/api/mac_dinh_tuy_chon": api_mac_dinh_tuy_chon,
    "/api/xem_truoc": api_xem_truoc,
    "/api/save_cai_dat": api_save_cai_dat,
    "/api/chon_thu_muc_ra": api_chon_thu_muc_ra,
    "/api/ai_lam_moi": api_ai_lam_moi,
    "/api/ai_ket_noi": api_ai_ket_noi,
    "/api/ai_ngat": api_ai_ngat,
    "/api/ai_cai_dat": api_ai_cai_dat,
    "/api/ai_hoi": api_ai_hoi,
    "/api/ai_hoi_thoai_moi": api_ai_hoi_thoai_moi,
}
ANH_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


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
        elif u.path == "/anh":                     # ảnh xem trước: /anh?p=<đường dẫn tuyệt đối>
            p = Path((parse_qs(u.query).get("p") or [""])[0])
            mime = ANH_MIME.get(p.suffix.lower())
            if mime and _duoc_phep(p):
                self._send(p.read_bytes(), mime)
            else:
                self._json({"ok": False, "msg": "Không có ảnh này."}, 404)
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
    S.url = f"http://{HOST}:{httpd.server_address[1]}/"
    return httpd, S.url


def dung_tat_ca():
    """Dừng worker + tiến trình con (khi tắt server)."""
    S.stop_flag.set()
    for p in (S.proc, S.xem_truoc_proc):
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
