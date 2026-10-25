# -*- coding: utf-8 -*-
"""Ghép video Flow — server cục bộ + giao diện WEB (menu tab dọc) để chạy ghep_tieude.py hàng loạt.

Chạy:  python app.py  ->  tự mở trình duyệt tại http://127.0.0.1:8766
       (hoặc bấm đúp mo_gui.bat / shortcut "Ghép video Flow": cửa sổ desktop app_gui.py nạp thẳng giao diện này)
Giao diện nằm ở web/index.html, 6 tab: Ghép video · Chỉnh sửa · Làm đẹp · Kết nối AI · Nhật ký · Cài đặt;
Tab Làm đẹp (lam_dep.py): làm trắng da / son môi / sức sống / sáng / tương phản / nhiệt độ màu, kéo thanh trượt xem
thử trên ảnh mẫu, Lưu -> --lam-dep khi render, CHỈ clip hook (mặt nạ từng khung bằng MediaPipe trong venv_lamdep riêng);
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
  3. Bấm Chạy: worker làm TỪNG tập một (GPU dùng chung): tải thư mục Drive về Downloads\\<tên kịch bản>
     (drive_thu_muc.py, không dùng gdown) -> chạy ghep_tieude.py --thu-muc <đó> --phan-sau <thư mục clip>
     --seed <số ngẫu nhiên> trong tiến trình con -> video _full_ + ảnh bố cục + .srt + file link minh họa
     (<tên>_minh_hoa_<stamp>.txt: cảnh nào ở mốc nào, dùng Link Drive nào) gom vào Downloads\\done\\<tên tập>\\
     như chạy tay. Số seed và thứ tự clip đã dùng được ghi lại ở từng mục (chạy tay cùng --seed sẽ ra đúng
     thứ tự đó).

Hàng đợi + thư mục clip lưu ở ~/.ghep_video_flow.json (không để file dữ liệu trong thư mục dự án).
Server chỉ nghe trên 127.0.0.1.
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import shutil
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
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

import base64

import cv2
import numpy as np

import drive_len                                  # tải video lên Drive + ghi cột G Sheet lịch đăng (tài khoản Google của user)
import drive_thu_muc as dtm
import lam_dep                                    # tab Làm đẹp: làm trắng da / son môi / màu toàn khung (xem thử tại chỗ)
import minh_hoa                                   # kho video minh họa (Sheet) + thư mục video mẫu
from ghep_tieude import (THU_MUC_GOC, TEN_VAI_TRO, doi_toc_do_giong, downloads_dir, liet_ke_clip, need_ffmpeg,
                         pick_from_folder, unique_path, vai_tro_theo_ten)

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
THU_MUC_MINH_HOA = minh_hoa.CACHE_DIR            # thư mục video mẫu mặc định: "video minh họa" cạnh tool
# thư mục Drive nhận video đã ghép (user đưa 21/10/2026, cùng một Gmail dr.bachhoihmu); sửa/thêm ở tab Cài đặt
DRIVE_DICH_MAC_DINH = [
    {"id": "1P1Gqnk9PFX1DTp9Okx5i2HStEUxocwIQ", "ten": "QUANG ANH", "link": "https://drive.google.com/drive/folders/1P1Gqnk9PFX1DTp9Okx5i2HStEUxocwIQ"},
    {"id": "1_MBNAWFc6lW-OCN-PF9yuVVxPaQ-2SHB", "ten": "EM NGỌC", "link": "https://drive.google.com/drive/folders/1_MBNAWFc6lW-OCN-PF9yuVVxPaQ-2SHB"},
    {"id": "1ZIp0IHFZcYPFhwrzEkXMGG6-t9QPLGnt", "ten": "ĐỨC ANH", "link": "https://drive.google.com/drive/folders/1ZIp0IHFZcYPFhwrzEkXMGG6-t9QPLGnt"},
    {"id": "1Qini2sM2SU5Jeft6wlwWG-5yBMelHxpb", "ten": "LÂM ANH", "link": "https://drive.google.com/drive/folders/1Qini2sM2SU5Jeft6wlwWG-5yBMelHxpb"},
    {"id": "1MYKqbh2XLcORyxFuYTdi5Y_9EeJGPQNF", "ten": "EM HIỀN", "link": "https://drive.google.com/drive/folders/1MYKqbh2XLcORyxFuYTdi5Y_9EeJGPQNF"},
]
# ảnh mẫu mặc định cho tab Làm đẹp (ảnh xem trước user chọn lúc đầu, 19/10/2026); không còn thì để trống, chọn ảnh khác
ANH_MAU_LAM_DEP = downloads_dir() / "Người bị đau dạ dày cần tránh 4 thói quen làm việc xuyên giờ ăn_ghep_20261019_180943_preview.jpg"
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
    "toc_do_giong": 1.0,     # tốc độ giọng đọc 0.5 (chậm nửa) … 2.0 (gấp đôi), giữ cao độ; nghe thử trên tập đã tải trong hàng đợi
    "sub": True, "sub_font": "Arial", "sub_co": 11, "sub_le_duoi": 45, "model_sub": "",
    "sub_kieu": "karaoke",   # karaoke = IN HOA, trắng viền đen đậm, từ đang đọc tô vàng (user chốt 20/10/2026) | thuong = như cũ
    "seed": None,            # None = xáo clip ngẫu nhiên mỗi lần; số = cố định
    "che_do": "auto",        # auto (tự dò NVENC) | nhe | manh | cpu
    "do_phan_giai": 0,       # 0 = giữ kích thước hook (1080x1920) | 720
    "nghi_giua_tap_phut": 3.0,   # xong một tập nghỉ bấy nhiêu phút rồi mới tải/dựng tập kế (user 22/10); 0 = chạy liên tục
    # cảnh minh họa theo từ khóa (minh_hoa.py): kho = Google Sheet "Kho video minh họa" (tab Kho minh họa) hoặc CSV
    "minh_hoa": True,
    "minh_hoa_sheet": "https://docs.google.com/spreadsheets/d/1n_rCUBFRCLi5NlDZovoDvHZd3ETCLtjKeLNPxHOAqUY/edit?gid=0#gid=0",
    "minh_hoa_ai": "gpt",    # gpt | claude | gemini
    "minh_hoa_model": "",    # "" = model mặc định của CLI đó
    "minh_hoa_giay": 5.0,    # phủ kín: mỗi cảnh video ≈ bấy nhiêu giây thì đổi cảnh (user 23/10: 5s), ảnh giữ tối đa; điểm xuyết: mỗi cảnh tối đa
    "minh_hoa_toc_do": 1.2,  # phủ kín: tốc độ chiếu clip minh họa (1.2 = nhanh 20%); cần phủ dài hơn thì planner hạ dần tới 0.8 thay vì đứng hình
    "minh_hoa_soat": True,   # AI soát lại cảnh đã chọn: clip chưa hợp câu -> ghi tab Thiếu để bổ sung kho (user 23/10)
    "minh_hoa_xen_bs": True, # có clip gốc: rút ngẫu nhiên theo seed một phần câu giữ hình bác sĩ thay cảnh kho (user 25/10)
    "minh_hoa_xen_bs_pct": 50,   # tỉ lệ câu bác sĩ (%); không clip gốc thì ô này không có tác dụng
    "minh_hoa_ti_le": 0.45,  # tổng minh họa tối đa / thời lượng phần sau (chỉ điểm xuyết)
    "minh_hoa_che_do": "phu_kin",   # phu_kin = cảnh kho là nền chính, bác sĩ bù | diem_xuyet = vài cảnh ngắn (cũ)
    "minh_hoa_chuyen": 0.5,         # giây mờ chồng khi vào/ra mỗi cảnh minh họa, CHỈ dùng với kiểu mo_chong; 0 = cắt cụp
    "minh_hoa_chuyen_kieu": "ngau_nhien",   # ngau_nhien = rút ngẫu nhiên kiểu xfade ffmpeg (bỏ fadeblack/fadewhite), thời gian
                                            # chuyển = gốc của ffmpeg 1s (user 19/10) | mo_chong = mờ chồng theo ô giây
    "minh_hoa_anh_dong": True,      # ảnh tĩnh -> động (phóng to / thu nhỏ / lắc / trượt) thay vì đứng hình
    "minh_hoa_sfx": True,           # mỗi lần chuyển cảnh xfade trộn một tiếng hợp kiểu đó (tab Âm thanh hiệu ứng, cột K)
    "minh_hoa_sfx_db": -4.0,        # tiếng chuyển cảnh nhỏ hơn giọng đọc bấy nhiêu dB (user chốt -4 sau khi nghe thử -8)
    "minh_hoa_vec_nguong": 0.70,    # tìm clip theo nghĩa (vector câu): sàn điểm để nhận (user chốt 22/10: 90% + vượt sàn)
    "minh_hoa_vec_nhom": 0.97,      # nhóm random: clip đạt ≥ tỉ lệ này × điểm cao nhất
    # checkbox "Hỏi GPT mới khi chạy" ở tab Ghép video: False = tập đã hỏi AI rồi (gpt_minh_hoa.json trong thư mục
    # tập) thì dùng lại trả lời cũ, chỉ ghép lại; True = hỏi AI mới mỗi lần chạy (--minh-hoa-hoi-lai)
    "minh_hoa_hoi_lai": False,
    # nút lớn ở thẻ "1. Thư mục clip gốc" (tab Ghép video): BẬT = phần sau KHÔNG dùng clip bác sĩ, 100% cảnh kho minh họa;
    # câu không khớp từ khóa lấy clip có từ khóa gần nhất (--khong-clip-goc). User yêu cầu 21/10/2026.
    "khong_clip_goc": False,
    # tab Làm đẹp (lam_dep.py): làm trắng da / son môi theo mặt nạ từng khung (MediaPipe) + màu toàn khung;
    # CHỈ áp lên clip hook (10 giây đầu); phần sau và cảnh kho minh họa giữ nguyên. Chỉnh theo ảnh mẫu rồi Lưu.
    "lam_dep": True,           # mặc định BẬT khi render (--lam-dep ...); user chốt 19/10/2026
    "ld_trang": 30,            # làm trắng da 0..100 (user chốt 30, 19/10/2026)
    "ld_son": 15,              # son môi 0..100 (user chốt 15)
    "ld_son_mau": "cam",       # hong | do | cam (user chốt cam)
    "ld_suc_song": 20,         # sức sống (vibrance) -100..100
    "ld_sang": 0,              # độ sáng -100..100
    "ld_tuong_phan": 0,        # tương phản -100..100
    "ld_nhiet": 0,             # nhiệt độ màu -100 (lạnh) .. 100 (ấm)
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


def thu_muc_done() -> Path:
    """<thư mục kết quả>\\done\\ — ghep_tieude.py gom video, ảnh bố cục, .srt, file link minh họa của mỗi tập vào
    một thư mục con ở đây (done\\<tên tập>\\); ngoài Downloads chỉ còn thư mục Drive tải về."""
    return thu_muc_ra() / "done"


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
        "toc_do_giong": round(_so(d.get("toc_do_giong"), float, m["toc_do_giong"], 0.5, 2.0), 2),
        "nghi_giua_tap_phut": round(_so(d.get("nghi_giua_tap_phut"), float, m["nghi_giua_tap_phut"], 0.0, 180.0), 1),
        "sub": bool(d.get("sub", m["sub"])),
        "sub_kieu": d.get("sub_kieu") if d.get("sub_kieu") in ("karaoke", "thuong") else m["sub_kieu"],
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
        "minh_hoa_toc_do": round(_so(d.get("minh_hoa_toc_do"), float, m["minh_hoa_toc_do"], 0.8, 1.5), 2),
        "minh_hoa_soat": bool(d.get("minh_hoa_soat", m["minh_hoa_soat"])),
        "minh_hoa_xen_bs": bool(d.get("minh_hoa_xen_bs", m["minh_hoa_xen_bs"])),
        "minh_hoa_xen_bs_pct": _so(d.get("minh_hoa_xen_bs_pct"), int, m["minh_hoa_xen_bs_pct"], 10, 90),
        "minh_hoa_ti_le": round(_so(d.get("minh_hoa_ti_le"), float, m["minh_hoa_ti_le"], 0.05, 0.9), 2),
        "minh_hoa_che_do": d.get("minh_hoa_che_do") if d.get("minh_hoa_che_do") in minh_hoa.CHE_DO_MINH_HOA else m["minh_hoa_che_do"],
        "minh_hoa_chuyen": round(_so(d.get("minh_hoa_chuyen"), float, m["minh_hoa_chuyen"], 0.0, 2.0), 2),
        "minh_hoa_chuyen_kieu": d.get("minh_hoa_chuyen_kieu") if d.get("minh_hoa_chuyen_kieu") in ("ngau_nhien", "mo_chong") else m["minh_hoa_chuyen_kieu"],
        "minh_hoa_anh_dong": bool(d.get("minh_hoa_anh_dong", m["minh_hoa_anh_dong"])),
        "minh_hoa_sfx": bool(d.get("minh_hoa_sfx", m["minh_hoa_sfx"])),
        "minh_hoa_vec_nguong": round(_so(d.get("minh_hoa_vec_nguong"), float, m["minh_hoa_vec_nguong"], 0.3, 0.95), 2),
        "minh_hoa_vec_nhom": round(_so(d.get("minh_hoa_vec_nhom"), float, m["minh_hoa_vec_nhom"], 0.5, 1.0), 2),
        "minh_hoa_sfx_db": round(_so(d.get("minh_hoa_sfx_db"), float, m["minh_hoa_sfx_db"], -30.0, 6.0), 1),
        "minh_hoa_hoi_lai": bool(d.get("minh_hoa_hoi_lai", m["minh_hoa_hoi_lai"])),
        "khong_clip_goc": bool(d.get("khong_clip_goc", m["khong_clip_goc"])),
        "lam_dep": bool(d.get("lam_dep", m["lam_dep"])),
        "ld_trang": _so(d.get("ld_trang"), int, m["ld_trang"], 0, 100),
        "ld_son": _so(d.get("ld_son"), int, m["ld_son"], 0, 100),
        "ld_son_mau": d.get("ld_son_mau") if d.get("ld_son_mau") in lam_dep.SON_MAU else m["ld_son_mau"],
        "ld_suc_song": _so(d.get("ld_suc_song"), int, m["ld_suc_song"], -100, 100),
        "ld_sang": _so(d.get("ld_sang"), int, m["ld_sang"], -100, 100),
        "ld_tuong_phan": _so(d.get("ld_tuong_phan"), int, m["ld_tuong_phan"], -100, 100),
        "ld_nhiet": _so(d.get("ld_nhiet"), int, m["ld_nhiet"], -100, 100),
    }
    if tc["do_phan_giai"] not in DO_PHAN_GIAI_HOP_LE:
        tc["do_phan_giai"] = m["do_phan_giai"]
    return tc


def tc_lam_dep(tc: dict) -> dict:
    """Khóa ld_* của tùy chọn -> tham số lam_dep.py (trang, son, son_mau, suc_song, sang, tuong_phan, nhiet)."""
    return lam_dep.doc_tc({k: tc.get("ld_" + k, lam_dep.MAC_DINH[k]) for k in lam_dep.KHOA})


def args_tuy_chon(tc: dict, thu_muc_minh_hoa: str = "") -> list[str]:
    """Tùy chọn -> tham số dòng lệnh ghep_tieude.py (không gồm --seed, worker tự quyết).
    thu_muc_minh_hoa: thư mục video mẫu đang chọn trên GUI (trống = mặc định của tool)."""
    a = ["--ti-le-tieude", str(tc["ti_le_tieude"]), "--khoang-cach", str(tc["khoang_cach"])]
    if tc.get("khong_clip_goc"):
        a.append("--khong-clip-goc")
    if abs(float(tc.get("toc_do_giong", 1.0)) - 1.0) > 0.005:
        a += ["--toc-do-giong", str(tc["toc_do_giong"])]
    if tc.get("lam_dep") and lam_dep.co_hieu_ung(tc_lam_dep(tc)):
        a += ["--lam-dep", lam_dep.chuoi_tc(tc_lam_dep(tc))]
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
        a += ["--sub-kieu", tc.get("sub_kieu", "karaoke"), "--sub-font", tc["sub_font"], "--sub-co", str(tc["sub_co"]),
              "--sub-le-duoi", str(tc["sub_le_duoi"])]
        if tc["model_sub"]:
            a += ["--model-sub", tc["model_sub"]]
    a += {"nhe": ["--nhe"], "manh": ["--manh"], "cpu": ["--cpu"]}.get(tc["che_do"], [])
    if tc["do_phan_giai"]:
        a += ["--do-phan-giai", str(tc["do_phan_giai"])]
    if tc["minh_hoa"] and tc["minh_hoa_sheet"]:
        a += ["--minh-hoa", tc["minh_hoa_sheet"], "--minh-hoa-ai", tc["minh_hoa_ai"],
              "--minh-hoa-giay", str(tc["minh_hoa_giay"]), "--minh-hoa-ti-le", str(tc["minh_hoa_ti_le"]),
              "--minh-hoa-che-do", tc["minh_hoa_che_do"], "--minh-hoa-chuyen", str(tc["minh_hoa_chuyen"]),
              "--minh-hoa-chuyen-kieu", tc.get("minh_hoa_chuyen_kieu", "ngau_nhien")]
        if not tc.get("minh_hoa_anh_dong", True):
            a.append("--minh-hoa-anh-tinh")
        if tc.get("minh_hoa_sfx", True):
            a += ["--minh-hoa-sfx-db", str(tc.get("minh_hoa_sfx_db", -4.0))]
        else:
            a.append("--khong-minh-hoa-sfx")
        if not tc.get("minh_hoa_soat", True):
            a.append("--khong-minh-hoa-soat")
        if tc.get("minh_hoa_xen_bs", True) and not tc.get("khong_clip_goc"):
            a += ["--minh-hoa-xen-bac-si", str(tc.get("minh_hoa_xen_bs_pct", 50))]
        a += ["--minh-hoa-vec-nguong", str(tc.get("minh_hoa_vec_nguong", 0.7)), "--minh-hoa-vec-nhom", str(tc.get("minh_hoa_vec_nhom", 0.9)),
              "--minh-hoa-toc-do", str(tc.get("minh_hoa_toc_do", 1.2))]
        if tc["minh_hoa_model"]:
            a += ["--minh-hoa-model", tc["minh_hoa_model"]]
        if thu_muc_minh_hoa:
            a += ["--minh-hoa-thu-muc", thu_muc_minh_hoa]
        if tc.get("minh_hoa_hoi_lai"):
            a.append("--minh-hoa-hoi-lai")
    return a


def _osascript_chon(lenh: str, tieu_de: str, bat_dau: str) -> str:
    """macOS: hộp thoại chọn của Finder qua AppleScript (tkinter không chạy được ngoài main thread trên Mac,
    mà main thread đã thuộc cửa sổ pywebview). `lenh` = 'choose folder' / 'choose file ...'; '' nếu hủy."""
    def _q(x: str) -> str:
        return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'
    vi_tri = f" default location (POSIX file {_q(bat_dau)})" if bat_dau and Path(bat_dau).is_dir() else ""
    r = subprocess.run(["osascript", "-e", f"POSIX path of ({lenh} with prompt {_q(tieu_de)}{vi_tri})"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def _chon_thu_muc_dialog(tieu_de: str, bat_dau: str) -> str:
    """Hộp thoại chọn thư mục của Windows (tkinter), nổi lên trên cùng; '' nếu hủy."""
    if sys.platform == "darwin":
        return _osascript_chon("choose folder", tieu_de, bat_dau).rstrip("/")
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    p = filedialog.askdirectory(parent=root, title=tieu_de, initialdir=bat_dau or str(Path.home()))
    root.destroy()
    return p or ""


def _chon_anh_dialog(tieu_de: str, bat_dau: str) -> str:
    """Hộp thoại chọn một file ảnh (jpg/png); '' nếu hủy."""
    if sys.platform == "darwin":
        return _osascript_chon('choose file of type {"public.image"}', tieu_de, bat_dau)
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    p = filedialog.askopenfilename(parent=root, title=tieu_de, initialdir=bat_dau or str(Path.home()),
                                   filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.webp"), ("Mọi file", "*.*")])
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


# macOS/Linux: tiến trình con chạy trong nhóm riêng -> _giet_cay dừng được cả ffmpeg/CLI AI nó gọi
NHOM_RIENG = {} if os.name == "nt" else {"start_new_session": True}


def _giet_cay(p: subprocess.Popen):
    """Dừng tiến trình con + ffmpeg nó đang chạy."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        p.kill()


def _mo(path, chon: bool = False):
    """Mở file/thư mục bằng ứng dụng mặc định (Explorer / Finder); chon=True: mở thư mục chứa và chọn sẵn file."""
    path = str(path)
    if os.name == "nt":
        if chon:
            subprocess.Popen(["explorer", "/select,", path])
        else:
            os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if chon else ["open", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent) if chon else path])


# ------------------------------------------------------------------ trạng thái
class State:
    """Trạng thái dùng chung giữa các request và worker (khoá bằng lock)."""

    def __init__(self):
        self.lock = threading.RLock()
        d = self._doc()
        # thư mục clip gốc: đã lưu -> dùng; chưa có -> "video gốc" cạnh tool (nếu tồn tại)
        self.goc_dir = d.get("goc_dir") or (str(THU_MUC_GOC) if THU_MUC_GOC.is_dir() else "")
        # thư mục video mẫu (kho minh họa): clip tải từ Drive + file tự chép cho dòng Sheet chưa có link
        self.minh_hoa_dir = str(d.get("minh_hoa_dir") or THU_MUC_MINH_HOA)
        # ảnh mẫu tab Làm đẹp (khung hình bác sĩ): đã lưu -> dùng; chưa có -> ảnh xem trước user đưa lúc đầu nếu còn
        self.lam_dep_anh = str(d.get("lam_dep_anh") or (ANH_MAU_LAM_DEP if ANH_MAU_LAM_DEP.is_file() else ""))
        # tải lên Drive + ghi Sheet: danh sách thư mục đích (tab Cài đặt), thư mục chọn sẵn, tự tải sau khi ghép xong
        dd = d.get("drive_dich")
        self.drive_dich = [x for x in (dd if isinstance(dd, list) else DRIVE_DICH_MAC_DINH) if isinstance(x, dict) and x.get("id")]
        self.drive_dich_chon = str(d.get("drive_dich_chon") or (self.drive_dich[0]["id"] if self.drive_dich else ""))
        self.tu_tai_len = bool(d.get("tu_tai_len", True))
        self.tu_don_rac = bool(d.get("tu_don_rac", True))   # tải Drive + ghi Sheet xong thì đưa file tập vào Thùng rác (user 26/10)
        self.google = {"dang": False, "loi": ""}      # đang chờ user đăng nhập trên trình duyệt
        self.kho_mh_dong: list[dict] | None = None   # các dòng Sheet kho đã đọc (None = chưa đọc được)
        self.kho_mh = {"dong": [], "co": 0, "chua_tai": 0, "thieu": 0, "thu_muc": "", "luc": "", "loi": "", "dang": ""}
        self._kho_mh_ky = None                        # chữ ký file trong thư mục lúc tính trạng thái lần cuối
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
        self.stop_flag = threading.Event()         # Dừng ngay: cắt tiến trình đang dựng, mục về chờ
        self.dung_sau_tap = False                  # Dừng sau tập này: tập đang dựng chạy nốt rồi worker thoát
        self.chon_thu = False                      # lượt đang chạy là CHỌN THỬ (chỉ chọn cảnh + AI soát + ghi Thiếu, không dựng)
        self.nghi_den = 0.0                        # đang nghỉ giữa hai tập: mốc time.time() hết nghỉ (0 = không nghỉ)
        self.bo_nghi = threading.Event()           # "Chạy tiếp ngay" trong lúc nghỉ
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
        threading.Thread(target=self.lam_moi_kho_mh, daemon=True, name="kho-mh").start()

    # ---- kho video minh họa (thẻ 3 tab Ghép video)
    def lam_moi_kho_mh(self, moi: bool = False):
        """Đọc (lại) Sheet kho minh họa ở thread nền rồi tính trạng thái từng dòng. moi=True: bỏ bản đệm 5 phút."""
        with self.lock:
            if self.kho_mh["dang"]:
                return
            self.kho_mh["dang"], sheet = "doc", self.tuy_chon["minh_hoa_sheet"]
        dong, loi = None, ""
        try:
            dong = minh_hoa._doc_dong(sheet, log=self.log, moi=moi) if sheet else []
        except Exception as e:                       # noqa: BLE001
            loi = str(e)
        with self.lock:
            if dong is not None:
                self.kho_mh_dong = dong
            self.kho_mh.update(loi=loi, luc=time.strftime("%H:%M:%S"), dang="")
            self._kho_mh_ky = None
        self.cap_nhat_kho_mh()
        if dong is not None and sheet:
            _tinh_vector_kho(sheet)                    # vector nghĩa cho dòng mới (tiến trình con, model không ở lại server)

    def cap_nhat_kho_mh(self):
        """Tính lại trạng thái theo thư mục video mẫu (không gọi mạng) khi danh sách file trong thư mục đổi."""
        with self.lock:
            if self.kho_mh_dong is None:
                return
            d = Path(self.minh_hoa_dir)
            try:
                ky = (str(d), tuple(sorted((p.name, p.stat().st_size) for p in d.iterdir() if p.is_file()))) if d.is_dir() else (str(d), ())
            except OSError:
                ky = (str(d), ())
            if ky == self._kho_mh_ky:
                return
            self.kho_mh.update(minh_hoa.trang_thai_tu_dong(self.kho_mh_dong, d))
            self._kho_mh_ky = ky

    def tai_kho_mh(self) -> bool:
        """Nút 'Tải video mẫu từ Sheet': tải mọi clip có Link Drive mà thư mục chưa có (thread nền)."""
        with self.lock:
            if self.kho_mh["dang"]:
                return False
            self.kho_mh["dang"], sheet, d = "tai", self.tuy_chon["minh_hoa_sheet"], self.minh_hoa_dir
        self.log(f"Kho minh họa: tải các clip có Link Drive về {d} ...")
        try:
            kq = minh_hoa.tai_tat_ca(sheet, d, log=self.log)
            self.log(f"Kho minh họa: tải mới {kq['tai']} file, {kq['da_co']} file đã có sẵn"
                     + (f", {len(kq['loi'])} lỗi" if kq["loi"] else ""))
        except Exception as e:                       # noqa: BLE001
            self.log(f"Kho minh họa: tải lỗi: {e}")
        with self.lock:
            self.kho_mh["dang"] = ""
        self.lam_moi_kho_mh()                        # Sheet vừa tải lại trong tai_tat_ca -> dùng bản đệm, không gọi mạng thêm
        return True

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
                    "thu_muc_ra": self.thu_muc_ra_cfg, "minh_hoa_dir": self.minh_hoa_dir, "lam_dep_anh": self.lam_dep_anh,
                    "drive_dich": self.drive_dich, "drive_dich_chon": self.drive_dich_chon, "tu_tai_len": self.tu_tai_len,
                    "tu_don_rac": self.tu_don_rac}
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
    S.cap_nhat_kho_mh()                             # rẻ: chỉ tính lại khi file trong thư mục video mẫu đổi
    google = {**drive_len.trang_thai(), **S.google}   # ngoài lock: có thể gọi mạng một lần (lấy email)
    with S.lock:
        kho = kho_clip(S.goc_dir)
        mh_dir = Path(S.minh_hoa_dir)
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
            "dung_sau_tap": S.running and S.dung_sau_tap,
            "chon_thu": S.running and S.chon_thu,
            "nghi_con": round(max(0.0, S.nghi_den - time.time()), 1) if S.running and S.nghi_den else 0,
            "goc": {"dir": S.goc_dir, "ton_tai": bool(S.goc_dir) and Path(S.goc_dir).is_dir(),
                    "mac_dinh": bool(S.goc_dir) and Path(S.goc_dir) == THU_MUC_GOC,
                    "clips": [{"ten": t, "giay": g} for t, g in kho],
                    "tong_giay": round(sum(g for _, g in kho), 1)},
            "downloads": str(thu_muc_ra()),
            "minh_hoa": {"dir": S.minh_hoa_dir, "ton_tai": mh_dir.is_dir(), "mac_dinh": mh_dir == THU_MUC_MINH_HOA,
                         "sheet": S.tuy_chon["minh_hoa_sheet"], "bat": S.tuy_chon["minh_hoa"], "kho": dict(S.kho_mh)},
            "tuy_chon": dict(S.tuy_chon),
            "tuy_chon_mac_dinh": dict(TUY_CHON_MAC_DINH),
            "mau_giong": mau_giong(),
            "google": google,
            "drive_dich": list(S.drive_dich), "drive_dich_chon": S.drive_dich_chon, "tu_tai_len": S.tu_tai_len,
            "tu_don_rac": S.tu_don_rac,
            "lam_dep": {"anh": S.lam_dep_anh, "ton_tai": bool(S.lam_dep_anh) and Path(S.lam_dep_anh).is_file(),
                        "san_sang": _LD_SAN_SANG[0], "ly_do": "" if _LD_SAN_SANG[0] else _LD_SAN_SANG[1]},
            "xem_truoc": dict(S.xem_truoc),
            "ai": {"nha": [dict(S.ai[k], ma=k, dang_hoi=(k in S.ai_dang_hoi), loi_xac_thuc=S.ai_loi_xac_thuc.get(k, ""))
                           for k in NHA_AI],
                   "luc_do": time.strftime("%H:%M:%S", time.localtime(S.ai_luc_do)) if S.ai_luc_do else ""},
            "cai_dat": {"thu_muc_ra": S.thu_muc_ra_cfg, "thu_muc_ra_thuc": str(thu_muc_ra()), "thu_muc_done": str(thu_muc_done()),
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


# ---- thẻ 3: kho video minh họa
def api_set_minh_hoa_dir(data):
    """Đổi thư mục video mẫu. Thư mục mặc định chưa có thì tạo; thư mục khác phải tồn tại (được phép trống)."""
    p = str(data.get("dir") or "").strip().strip('"')
    if not p:
        return {"ok": False, "msg": "Chưa nhập thư mục video mẫu."}
    pp = Path(p)
    if pp == THU_MUC_MINH_HOA:
        pp.mkdir(parents=True, exist_ok=True)
    if not pp.is_dir():
        return {"ok": False, "msg": f"Không thấy thư mục: {p}"}
    with S.lock:
        S.minh_hoa_dir = str(pp)
        S._kho_mh_ky = None
        S.save()
    n = sum(1 for q in pp.iterdir() if q.is_file() and q.suffix.lower() in minh_hoa.DUOI_VIDEO + minh_hoa.DUOI_ANH)
    msg = f"Thư mục video mẫu: {pp} — {n} file video/ảnh"
    S.log(msg)
    return {"ok": True, "msg": msg}


def api_chon_thu_muc_minh_hoa(_data):
    if not _DIALOG.acquire(blocking=False):
        return {"ok": False, "msg": "Hộp thoại chọn thư mục đang mở."}
    try:
        p = _chon_thu_muc_dialog("Chọn thư mục video mẫu (clip minh họa tải về / tự chép)", S.minh_hoa_dir)
    finally:
        _DIALOG.release()
    if not p:
        return {"ok": False, "msg": "Đã hủy chọn thư mục."}
    return api_set_minh_hoa_dir({"dir": p})


def _doc_lai_kho_nen(moi: bool = True):
    with S.lock:
        S.kho_mh_dong = None
        S.kho_mh.update(dong=[], co=0, chua_tai=0, thieu=0, loi="")
    threading.Thread(target=S.lam_moi_kho_mh, args=(moi,), daemon=True, name="kho-mh").start()


def api_set_minh_hoa_sheet(data):
    """Lưu link Sheet kho (cùng khóa minh_hoa_sheet với tab Chỉnh sửa) rồi đọc lại kho."""
    s = str(data.get("sheet") or "").strip()
    if s and not (minh_hoa.sheet_csv_url(s) or Path(s).is_file()):
        return {"ok": False, "msg": "Phải là link Google Sheet hoặc đường dẫn file CSV trên máy."}
    with S.lock:
        S.tuy_chon = chuan_hoa_tuy_chon({**S.tuy_chon, "minh_hoa_sheet": s})
        S.save()
    S.log(f"Kho minh họa: {s or '(bỏ trống)'}")
    _doc_lai_kho_nen()
    return {"ok": True, "msg": "Đã lưu link kho, đang đọc lại Sheet…" if s else "Đã bỏ link kho."}


def api_kho_minh_hoa_lam_moi(_data):
    if S.kho_mh["dang"]:
        return {"ok": False, "msg": "Đang đọc Sheet / tải clip, chờ xong đã."}
    _doc_lai_kho_nen(moi=True)
    return {"ok": True, "msg": "Đang đọc lại Sheet kho…"}


def api_tai_minh_hoa(_data):
    if not S.tuy_chon["minh_hoa_sheet"]:
        return {"ok": False, "msg": "Chưa có link Sheet kho."}
    if S.kho_mh["dang"]:
        return {"ok": False, "msg": "Đang đọc Sheet / tải clip, chờ xong đã."}
    threading.Thread(target=S.tai_kho_mh, daemon=True, name="tai-mh").start()
    return {"ok": True, "msg": "Đang tải các clip có Link Drive về thư mục video mẫu…"}


# ---- tab Chỉnh sửa
def api_set_khong_clip_goc(data):
    """Nút lớn ở thẻ Thư mục clip gốc: BẬT = phần sau không dùng clip bác sĩ, 100% cảnh kho (--khong-clip-goc)."""
    bat = bool(data.get("bat"))
    with S.lock:
        S.tuy_chon = chuan_hoa_tuy_chon({**S.tuy_chon, "khong_clip_goc": bat})
        S.save()
    S.log("Clip gốc: " + ("KHÔNG DÙNG — phần sau 100% cảnh kho minh họa, câu không khớp từ khóa lấy clip có từ khóa gần nhất"
                          if bat else "dùng lại clip gốc (quay bác sĩ) làm nền phần sau như bình thường"))
    return {"ok": True, "bat": bat, "msg": "Đã BẬT: không dùng clip gốc." if bat else "Đã TẮT: dùng clip gốc như bình thường."}


def api_set_minh_hoa_hoi_lai(data):
    """Checkbox 'Hỏi GPT mới khi chạy' ở tab Ghép video — khóa minh_hoa_hoi_lai, lưu cùng tùy chọn chỉnh sửa."""
    bat = bool(data.get("bat"))
    with S.lock:
        S.tuy_chon = chuan_hoa_tuy_chon({**S.tuy_chon, "minh_hoa_hoi_lai": bat})
        S.save()
    S.log("Minh họa: " + ("HỎI AI MỚI mỗi lần chạy (bỏ trả lời đã nhớ trong thư mục tập)" if bat
                         else "chạy lại cùng kịch bản thì dùng lại trả lời AI đã nhớ, chỉ ghép lại"))
    return {"ok": True, "bat": bat}


def api_save_tuy_chon(data):
    d = data.get("tuy_chon") or data
    # form tab Chỉnh sửa không có ô minh_hoa_hoi_lai / khong_clip_goc (nằm ở tab Ghép video) -> giữ giá trị đang có
    tc = chuan_hoa_tuy_chon({"minh_hoa_hoi_lai": S.tuy_chon["minh_hoa_hoi_lai"],
                             "khong_clip_goc": S.tuy_chon.get("khong_clip_goc", False), **d})
    with S.lock:
        sheet_doi = tc["minh_hoa_sheet"] != S.tuy_chon["minh_hoa_sheet"]
        S.tuy_chon = tc
        S.save()
    if sheet_doi:
        _doc_lai_kho_nen()
    S.log("Đã lưu tùy chọn chỉnh sửa: " + " ".join(args_tuy_chon(tc)) + (f" --seed {tc['seed']}" if tc["seed"] is not None else ""))
    return {"ok": True, "msg": "Đã lưu — áp dụng cho các tập chạy từ giờ.", "tuy_chon": tc}


def api_mac_dinh_tuy_chon(_data):
    with S.lock:
        sheet_doi = S.tuy_chon["minh_hoa_sheet"] != TUY_CHON_MAC_DINH["minh_hoa_sheet"]
        S.tuy_chon = dict(TUY_CHON_MAC_DINH)
        S.save()
    if sheet_doi:
        _doc_lai_kho_nen()
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
            ten_drive, dest, _ = dtm.tai_thu_muc_theo_ten(link, thu_muc_ra(), log=S.log)   # Downloads\<tên kịch bản>
            with S.lock:
                it["thu_muc"], it["ten"] = str(dest), ten_drive or it.get("ten", "")
                S.save()
            folder = dest
        THU_MUC_XEM_TRUOC.mkdir(parents=True, exist_ok=True)
        seed = tc["seed"] if tc["seed"] is not None else random.randrange(1, 10 ** 9)
        cmd = [python_exe(), "-u", str(TOOL), "--thu-muc", str(folder), *(["--phan-sau", goc] if goc else []), "--preview-only",
               "--out", str(THU_MUC_XEM_TRUOC), "--seed", str(seed), *args_tuy_chon(tc, S.minh_hoa_dir)]
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        with S.lock:
            S.xem_truoc["buoc"] = "Nhận diện mặt"
        p = subprocess.Popen(cmd, cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW, **NHOM_RIENG,
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
        if not kho_clip(S.goc_dir) and not S.tuy_chon.get("khong_clip_goc"):
            return {"ok": False, "msg": "Chưa có thư mục clip gốc."}
        S.xem_truoc.update(status="dang", ten=it.get("ten") or it["link"], buoc="Chuẩn bị", preview="", mau="", loi="")
    threading.Thread(target=_xem_truoc_job, args=(it["id"],), daemon=True, name="xem-truoc").start()
    return {"ok": True, "msg": "Đang tạo ảnh xem trước (10–30 giây, không render video)."}


# ---- Google Drive + Sheet lịch đăng (drive_len.py): đăng nhập, thư mục đích, đọc Sheet thêm vào hàng đợi, tải lên
def api_google_dang_nhap(_data):
    """Mở trình duyệt đăng nhập Google (chạy nền, chờ tối đa 5 phút); trạng thái qua state.google."""
    with S.lock:
        if S.google["dang"]:
            return {"ok": False, "msg": "Đang chờ bạn đăng nhập trên trình duyệt."}
        S.google.update(dang=True, loi="")

    def _job():
        try:
            drive_len.creds(True, log=lambda s: S.log("   [Google] " + s))
            tt = drive_len.trang_thai()
            S.log(f"✓ Google: đã đăng nhập {tt.get('email') or ''} — token lưu ở {tt.get('token')}")
            with S.lock:
                S.google.update(dang=False, loi="")
        except Exception as e:                     # noqa: BLE001
            S.log(f"✗ Google: đăng nhập lỗi: {e}")
            with S.lock:
                S.google.update(dang=False, loi=str(e))
    threading.Thread(target=_job, daemon=True, name="google-login").start()
    return {"ok": True, "msg": "Đã mở trình duyệt — chọn tài khoản Google rồi bấm Cho phép (màn hình “chưa xác minh” thì chọn Nâng cao → Tiếp tục)."}


def api_google_chon_client(_data):
    """Chọn file client_secret.json (OAuth client loại Desktop tải từ Google Cloud Console của Gmail mình) -> chép cạnh app."""
    if not _DIALOG.acquire(blocking=False):
        return {"ok": False, "msg": "Hộp thoại chọn file đang mở."}
    try:
        if sys.platform == "darwin":
            p = _osascript_chon('choose file of type {"public.json"}',
                                "Chọn file client_secret*.json (OAuth client loại Desktop app)", str(downloads_dir()))
        else:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            p = filedialog.askopenfilename(parent=root, title="Chọn file client_secret*.json (OAuth client loại Desktop app)",
                                           initialdir=str(downloads_dir()), filetypes=[("JSON", "*.json"), ("Mọi file", "*.*")])
            root.destroy()
    finally:
        _DIALOG.release()
    if not p:
        return {"ok": False, "msg": "Đã hủy chọn file."}
    try:
        cl = drive_len.dat_client(Path(p))
    except Exception as e:                         # noqa: BLE001
        return {"ok": False, "msg": f"Không dùng được file này: {e}"}
    S.log(f"Google: đã thay OAuth client (dự án {cl.get('project') or '?'}), token cũ đã xóa — bấm Đăng nhập Google.")
    return {"ok": True, "msg": f"Đã dùng client của dự án {cl.get('project') or '?'} — giờ bấm Đăng nhập Google."}


def api_google_dang_xuat(_data):
    drive_len.dang_xuat()
    S.log("Google: đã đăng xuất, xóa token.")
    return {"ok": True, "msg": "Đã đăng xuất Google."}


def api_set_tu_tai_len(data):
    bat = bool(data.get("bat"))
    with S.lock:
        S.tu_tai_len = bat
        S.save()
    S.log("Tải lên Drive sau khi ghép: " + ("BẬT (tập lấy từ Sheet, có thư mục đích)" if bat else "TẮT — bấm Tải lên ở từng tập khi cần"))
    return {"ok": True, "bat": bat}


def api_set_tu_don_rac(data):
    bat = bool(data.get("bat"))
    with S.lock:
        S.tu_don_rac = bat
        S.save()
    S.log("Dọn file sau khi tải lên: " + ("BẬT (tải Drive + ghi Sheet xong thì đưa file của tập vào Thùng rác)" if bat else "TẮT"))
    return {"ok": True, "bat": bat}


def _vao_thung_rac(p: Path) -> None:
    """Đưa file/thư mục vào Thùng rác (lấy lại được), không xoá vĩnh viễn."""
    if sys.platform == "darwin":
        rac = Path.home() / ".Trash"
        dich = rac / p.name
        i = 1
        while dich.exists():
            dich = rac / f"{p.stem} {datetime.now():%H.%M.%S}{'' if i == 1 else f' {i}'}{p.suffix}"
            i += 1
        try:
            shutil.move(str(p), str(dich))
        except OSError:                            # không có quyền ghi ~/.Trash -> nhờ Finder (hỏi quyền một lần)
            q = str(p).replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{q}")'],
                           check=True, capture_output=True, timeout=60)
    elif os.name == "nt":
        ham = "DeleteDirectory" if p.is_dir() else "DeleteFile"
        lenh = ("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::"
                f"{ham}($env:DUONG_DAN, 'OnlyErrorDialogs', 'SendToRecycleBin')")
        subprocess.run(["powershell", "-NoProfile", "-Command", lenh], check=True, capture_output=True, timeout=120,
                       env={**os.environ, "DUONG_DAN": str(p)}, creationflags=NO_WINDOW)
    else:
        raise OSError("chưa hỗ trợ Thùng rác trên hệ điều hành này")


def _don_rac_muc(it) -> None:
    """Sau khi video (+ file txt minh họa) đã lên Drive và link đã ghi vào Sheet: đưa vào Thùng rác thư mục Drive tải về
    (<thư mục kết quả>/<tên tập>), thư mục kết quả done/<tên tập> và bản hook đã làm đẹp trong cache "Làm đẹp".
    Chỉ đụng tới đường dẫn nằm trong thư mục kết quả; không bao giờ đụng video gốc, kho minh họa, cài đặt."""
    goc = thu_muc_ra().resolve()
    tm = Path(it.get("thu_muc") or "")
    out = Path(it.get("out") or "")
    ds: list[Path] = []
    if it.get("thu_muc") and tm.is_dir():
        ld = goc / "Làm đẹp"
        for hook in tm.glob("Hook*"):
            ds += sorted(ld.glob(f"{glob.escape(hook.stem)} - lam dep *.mp4"))
        ds.append(tm)
    if it.get("out") and out.parent.is_dir() and out.parent != thu_muc_done():
        ds.append(out.parent)
    cam = {Path(S.goc_dir or "/").resolve(), Path(S.minh_hoa_dir or "/").resolve(), APP_DIR.resolve(), goc}
    for p in ds:
        try:
            r = p.resolve()
            if r in cam or goc not in r.parents:
                S.log(f"   bỏ qua (ngoài thư mục kết quả): {p}")
                continue
            _vao_thung_rac(p)
            S.log(f"🗑 [{it['id']}] đã đưa vào Thùng rác: {p}")
        except Exception as e:                     # noqa: BLE001
            S.log(f"✗ [{it['id']}] dọn {p} lỗi: {e}")
    with S.lock:
        it["da_don"] = True
        S.save()


def api_set_drive_dich(data):
    i = str(data.get("id") or "")
    with S.lock:
        if not any(x["id"] == i for x in S.drive_dich):
            return {"ok": False, "msg": "Không có thư mục này trong danh sách."}
        S.drive_dich_chon = i
        S.save()
        ten = next(x["ten"] for x in S.drive_dich if x["id"] == i)
    S.log(f"Thư mục Drive nhận video: {ten} (áp cho tập thêm từ giờ; tập đã có trong hàng đợi đổi ở cột Trạng thái)")
    return {"ok": True, "msg": f"Thư mục Drive nhận video: {ten}"}


def api_drive_dich_them(data):
    link = str(data.get("link") or "").strip()
    fid = drive_len.folder_id(link)
    if not fid:
        return {"ok": False, "msg": "Không phải link thư mục Drive."}
    with S.lock:
        if any(x["id"] == fid for x in S.drive_dich):
            return {"ok": False, "msg": "Thư mục đã có trong danh sách."}
    try:
        tt = drive_len.thong_tin_thu_muc(fid)
    except Exception as e:                         # noqa: BLE001
        return {"ok": False, "msg": f"Không đọc được thư mục (đã đăng nhập Google chưa?): {e}"}
    with S.lock:
        S.drive_dich.append({"id": tt["id"], "ten": tt["ten"], "link": tt["link"]})
        if not S.drive_dich_chon:
            S.drive_dich_chon = tt["id"]
        S.save()
    S.log(f"Thêm thư mục Drive đích: {tt['ten']} ({tt['chu']})")
    return {"ok": True, "msg": f"Đã thêm thư mục “{tt['ten']}”."}


def api_drive_dich_xoa(data):
    i = str(data.get("id") or "")
    with S.lock:
        S.drive_dich = [x for x in S.drive_dich if x["id"] != i]
        if S.drive_dich_chon == i:
            S.drive_dich_chon = S.drive_dich[0]["id"] if S.drive_dich else ""
        S.save()
    return {"ok": True, "msg": "Đã bỏ thư mục khỏi danh sách."}


def api_doc_sheet(data):
    """Đọc Sheet lịch đăng -> các dòng (D tiêu đề, F link nguyên liệu, G link video) để tick thêm vào hàng đợi."""
    link = str(data.get("link") or "").strip()
    try:
        kq = drive_len.doc_lich(link, log=S.log)
    except Exception as e:                         # noqa: BLE001
        return {"ok": False, "msg": f"Không đọc được Sheet: {e}"}
    with S.lock:
        dang_co = {it.get("fid") for it in S.items if it.get("status") in (CHO, DANG)}
    for d in kq["dong"]:
        d["dang_co"] = bool(d.get("fid")) and d["fid"] in dang_co
    kq.update(ok=True, link=link)
    n_ok = sum(1 for d in kq["dong"] if d.get("fid") and not d.get("link_g") and not d["dang_co"])
    kq["msg"] = f"Sheet “{kq['tieu_de_sheet']}”: {len(kq['dong'])} dòng, {n_ok} dòng chạy được (F có link, G trống)."
    return kq


def api_them_tu_sheet(data):
    """Thêm các dòng đã tick vào hàng đợi: mỗi dòng = một tập (link F), nhớ Sheet/tab/dòng để ghi cột G + thư mục Drive đích."""
    sh = data.get("sheet") or {}
    dong = data.get("dong") or []
    dich = str(data.get("dich") or "")
    with S.lock:
        if dich and not any(x["id"] == dich for x in S.drive_dich):
            dich = ""
        dich = dich or S.drive_dich_chon
        dang_co = {it.get("fid") for it in S.items if it.get("status") in (CHO, DANG)}
        them, bo = [], 0
        for d in dong:
            fid = drive_len.folder_id(str(d.get("link_f") or ""))
            if not fid or fid in dang_co:
                bo += 1
                continue
            dang_co.add(fid)
            it = {"id": S.next_id, "link": str(d.get("link_f")), "fid": fid, "ten": str(d.get("tieu_de") or ""),
                  "tieu_de": str(d.get("tieu_de") or ""), "status": CHO, "buoc": "", "loi": "", "canh_bao": "",
                  "them_luc": datetime.now().strftime("%d/%m %H:%M"), "dich": dich, "tai_len": {},
                  "sheet": {"id": sh.get("id"), "tab": sh.get("tab"), "dong": int(d.get("dong") or 0),
                            "cot_g": sh.get("cot_g") or drive_len.COT_LINK_VIDEO, "link": sh.get("link") or ""}}
            S.next_id += 1
            S.items.append(it)
            them.append(it["id"])
        S.save()
        ten_dich = next((x["ten"] for x in S.drive_dich if x["id"] == dich), "(chưa chọn)")
    if them:
        threading.Thread(target=_kiem_tra_bo, args=(them,), daemon=True).start()
    msg = f"Đã thêm {len(them)} tập từ Sheet (xong sẽ tải lên “{ten_dich}” và điền cột G)" + (f"; bỏ {bo} dòng trùng/không có link" if bo else "") + "."
    S.log(msg)
    return {"ok": bool(them), "msg": msg}


def _tai_len_muc(it, ep: bool = False) -> None:
    """Sau khi ghép xong: tải video lên thư mục Drive đích của tập (tên = tiêu đề cột D), rồi ghi link vào cột G nếu tập
    lấy từ Sheet. ep=True: bấm tay, bỏ qua công tắc tự tải. Trạng thái ở it['tai_len'] = {tt, pct, link, fid, g, loi}."""
    with S.lock:
        out, dich, sheet, tu = it.get("out"), it.get("dich") or "", it.get("sheet"), S.tu_tai_len
        ten = (it.get("tieu_de") or it.get("ten") or "video").strip()
        txt = it.get("minh_hoa_file") or ""
    if not dich or not out or not Path(out).is_file() or (not tu and not ep):
        return

    def tt(**k):
        with S.lock:
            it["tai_len"] = {**(it.get("tai_len") or {}), **k}
            S.save()
    tt(tt="dang", pct=0, loi="", link="", fid="", g="", thu_muc_link="", txt_link="")
    log = lambda s: S.log("   " + s)              # noqa: E731
    # Drive: <thư mục đích>\<tên video>\ gồm video + file txt minh họa (user 21/10: "tạo 1 thư mục tên giống tên video")
    S.log(f"⬆ [{it['id']}] tải lên Drive: thư mục con “{ten}” trong {dich} ← {Path(out).name}" + (f" + {Path(txt).name}" if txt else ""))
    try:
        tm = drive_len.tao_thu_muc(dich, ten, log=log)
        tt(thu_muc_link=tm["link"], thu_muc_id=tm["id"])
        kq = drive_len.tai_len(Path(out), tm["id"], ten + ".mp4", log=log, tien_do=lambda p: tt(pct=p))
    except Exception as e:                         # noqa: BLE001
        S.log(f"✗ [{it['id']}] tải lên Drive lỗi: {e}")
        tt(tt="loi", loi=str(e))
        return
    tt(tt="xong", pct=100, link=kq["link"], fid=kq["id"], ten_file=kq["ten"])
    S.log(f"✓ [{it['id']}] đã tải video lên Drive: {kq['link']}")
    if txt and Path(txt).is_file():
        try:
            kt = drive_len.tai_len(Path(txt), tm["id"], Path(txt).name, log=log, chia_se=False)   # thư mục đã chia sẻ, file kế thừa
            drive_len.xoa_file_cu(tm["id"], "_minh_hoa_", ".txt", giu=kt["ten"], log=log)       # chỉ giữ bản txt mới nhất
            tt(txt_link=kt["link"])
            S.log(f"✓ [{it['id']}] đã tải file minh họa: {kt['ten']}")
        except Exception as e:                     # noqa: BLE001
            S.log(f"✗ [{it['id']}] tải file txt minh họa lỗi (video vẫn xong): {e}")
            tt(loi=f"txt: {e}")
    if sheet and sheet.get("id") and sheet.get("dong"):
        try:
            drive_len.ghi_o(sheet["id"], sheet["tab"], int(sheet["dong"]), sheet.get("cot_g") or "G", kq["link"])
            tt(g="xong")
            S.log(f"✓ [{it['id']}] đã ghi link vào cột {sheet.get('cot_g') or 'G'} dòng {sheet['dong']} của Sheet")
        except Exception as e:                     # noqa: BLE001
            S.log(f"✗ [{it['id']}] ghi Sheet lỗi: {e}")
            tt(g="loi", loi=f"ghi Sheet: {e}")
            return
    if S.tu_don_rac:
        if txt and not (it.get("tai_len") or {}).get("txt_link"):
            S.log(f"   [{it['id']}] không dọn file: file txt minh họa chưa lên Drive")
        else:
            _don_rac_muc(it)


def api_set_dich_muc(data):
    """Đổi thư mục Drive đích của MỘT tập trong hàng đợi (ô chọn ở cột Trạng thái); '' = không tải lên."""
    dich = str(data.get("dich") or "")
    with S.lock:
        it = S.find(data.get("id"))
        if it is None:
            return {"ok": False, "msg": "Không thấy mục."}
        if dich and not any(x["id"] == dich for x in S.drive_dich):
            return {"ok": False, "msg": "Không có thư mục này trong danh sách."}
        it["dich"] = dich
        S.save()
        ten = next((x["ten"] for x in S.drive_dich if x["id"] == dich), "")
    return {"ok": True, "msg": f"Tập “{(it.get('ten') or '')[:40]}”: " + (f"tải lên “{ten}”" if dich else "không tải lên Drive")}


def api_tai_len_lai(data):
    """Nút Tải lên / Tải lên lại ở từng tập (chạy nền)."""
    with S.lock:
        it = S.find(data.get("id"))
        if it is None:
            return {"ok": False, "msg": "Không thấy mục."}
        if (it.get("tai_len") or {}).get("tt") == "dang":
            return {"ok": False, "msg": "Đang tải lên rồi."}
        if not it.get("dich"):
            it["dich"] = S.drive_dich_chon
        if not it.get("out") or not Path(it["out"]).is_file():
            return {"ok": False, "msg": "Tập này chưa có video đã ghép."}
    threading.Thread(target=_tai_len_muc, args=(it, True), daemon=True, name="tai-len").start()
    return {"ok": True, "msg": "Đang tải lên Drive…"}


# ---- nghe thử tốc độ giọng đọc (tab Chỉnh sửa): mẫu = file "Giọng đọc - …" của tập đầu tiên trong hàng đợi đã tải về máy
_MAU_GIONG_CACHE: dict[str, tuple[int, Path | None]] = {}   # thư mục -> (mtime_ns thư mục, file giọng đọc | None)


def _giong_trong_thu_muc(thu_muc: str) -> Path | None:
    """File giọng đọc (theo tiền tố tên, như pick_from_folder) trong thư mục tập; cache theo mtime thư mục (poll mỗi giây)."""
    d = Path(thu_muc) if thu_muc else None
    if not d or not d.is_dir():
        return None
    try:
        mt = d.stat().st_mtime_ns
    except OSError:
        return None
    cu = _MAU_GIONG_CACHE.get(thu_muc)
    if cu and cu[0] == mt:
        return cu[1]
    kq = next((p for p in sorted(d.iterdir()) if p.is_file() and vai_tro_theo_ten(p)[0] == "audio"), None)
    _MAU_GIONG_CACHE[thu_muc] = (mt, kq)
    return kq


def mau_giong() -> dict:
    """{co, ten (tập), file} — tập đầu tiên trong hàng đợi có thư mục đã tải và có file giọng đọc; không có -> co=False."""
    with S.lock:
        items = list(S.items)
    for it in items:
        p = _giong_trong_thu_muc(it.get("thu_muc") or "")
        if p:
            return {"co": True, "ten": it.get("ten") or it["link"], "file": p.name, "duong_dan": str(p)}
    return {"co": False, "ten": "", "file": "", "duong_dan": ""}


_NGHE_LOCK = threading.Lock()


def api_nghe_thu_giong(data):
    """Tạo 25 giây đầu giọng đọc mẫu ở tốc độ `toc_do` (atempo, cache trong thư mục xem trước) -> url phát trên trang."""
    m = mau_giong()
    if not m["co"]:
        return {"ok": False, "msg": "Chưa có mẫu: hàng đợi chưa có tập nào đã tải về máy kèm file giọng đọc."}
    toc = round(_so(data.get("toc_do"), float, 1.0, 0.5, 2.0), 2)
    if not _NGHE_LOCK.acquire(timeout=20):
        return {"ok": False, "msg": "Đang tạo bản nghe thử trước đó, thử lại."}
    try:
        THU_MUC_XEM_TRUOC.mkdir(parents=True, exist_ok=True)
        ra = doi_toc_do_giong(Path(m["duong_dan"]), toc, THU_MUC_XEM_TRUOC, need_ffmpeg(), giay=25.0)
    except SystemExit as e:
        return {"ok": False, "msg": str(e)}
    except Exception as e:                         # noqa: BLE001
        return {"ok": False, "msg": f"Nghe thử lỗi: {e}"}
    finally:
        _NGHE_LOCK.release()
    return {"ok": True, "url": "/am?p=" + quote(str(ra)), "ten": m["ten"], "file": m["file"], "toc_do": toc,
            "msg": f"Nghe thử ×{toc:.2f}: 25 giây đầu giọng đọc tập “{m['ten']}”."}


# ---- tab Làm đẹp
_LD_SAN_SANG = lam_dep.san_sang()                 # (ok, python | lý do): venv_lamdep + ffmpeg, dò một lần lúc khởi động
_LD_LOCK = threading.Lock()                       # xem thử tuần tự (mediapipe subprocess + ffmpeg)
_LD_MOC: dict = {}                                # điểm mốc ảnh mẫu: {"ky": (đường dẫn, mtime), "pts": mảng | None}


def _doc_anh_bgr(p: Path):
    img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Không đọc được ảnh: {p}")
    return img


def _lam_dep_moc(anh: Path):
    """478 điểm mặt của ảnh mẫu: tính qua venv_lamdep một lần (2–3 s) rồi nhớ theo (đường dẫn, mtime)."""
    ky = (str(anh), anh.stat().st_mtime_ns)
    if _LD_MOC.get("ky") != ky:
        _LD_MOC.update(ky=ky, pts=lam_dep.diem_moc_qua_subprocess(anh))
    return _LD_MOC["pts"]


def api_lam_dep_xem_thu(data):
    """Thanh trượt -> ảnh ghép gốc|chỉnh (jpg base64) tính trên ảnh mẫu bằng đúng hai bước sẽ dùng khi render:
    da/môi theo điểm mặt (numpy) rồi màu toàn khung (filter ffmpeg)."""
    tc = lam_dep.doc_tc(data.get("tc") or {})
    with S.lock:
        anh = S.lam_dep_anh
    p = Path(anh) if anh else None
    if not p or not p.is_file():
        return {"ok": False, "msg": "Chưa có ảnh mẫu — bấm Chọn ảnh… hoặc Lấy khung hình tập đầu."}
    if not _LD_SAN_SANG[0]:
        return {"ok": False, "msg": _LD_SAN_SANG[1]}
    if not _LD_LOCK.acquire(timeout=30):
        return {"ok": False, "msg": "Đang tính ảnh xem thử trước đó, thử lại."}
    try:
        t0 = time.time()
        goc = _doc_anh_bgr(p)
        pts = _lam_dep_moc(p)
        img = lam_dep.xem_thu(goc, pts, tc, rong=int(_so(data.get("rong"), int, 820, 400, 1600)))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise RuntimeError("không mã hóa được jpg")
        return {"ok": True, "anh": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii"),
                "co_mat": pts is not None, "giay": round(time.time() - t0, 2), "loc": lam_dep.loc_toan_khung(tc),
                "tc": lam_dep.chuoi_tc(tc)}
    except Exception as e:                         # noqa: BLE001
        return {"ok": False, "msg": f"Xem thử lỗi: {e}"}
    finally:
        _LD_LOCK.release()


def _dat_anh_mau(p: Path, nguon: str):
    with S.lock:
        S.lam_dep_anh = str(p)
        S.save()
    _LD_MOC.clear()
    msg = f"Ảnh mẫu Làm đẹp: {p.name} ({nguon})"
    S.log(msg)
    return {"ok": True, "msg": msg, "anh": str(p)}


def api_lam_dep_set_anh(data):
    p = Path(str(data.get("anh") or "").strip().strip('"'))
    if not p.is_file():
        return {"ok": False, "msg": f"Không thấy ảnh: {p}"}
    return _dat_anh_mau(p, "nhập đường dẫn")


def api_lam_dep_chon_anh(_data):
    if not _DIALOG.acquire(blocking=False):
        return {"ok": False, "msg": "Hộp thoại chọn file đang mở."}
    try:
        with S.lock:
            bat_dau = str(Path(S.lam_dep_anh).parent) if S.lam_dep_anh else str(thu_muc_ra())
        p = _chon_anh_dialog("Chọn ảnh mẫu (khung hình bác sĩ) cho tab Làm đẹp", bat_dau)
    finally:
        _DIALOG.release()
    if not p:
        return {"ok": False, "msg": "Đã hủy chọn ảnh."}
    return _dat_anh_mau(Path(p), "chọn file")


def api_lam_dep_khung_hinh(data):
    """Lấy một khung hình (mặc định giây 2) của clip Hook ở tập đầu hàng đợi (hoặc tập có id) làm ảnh mẫu."""
    with S.lock:
        it = S.find(data.get("id")) if data.get("id") is not None else next((x for x in S.items), None)
    if it is None:
        return {"ok": False, "msg": "Hàng đợi trống — thêm link thư mục Drive trước."}
    folder = it.get("thu_muc")
    if not folder or not Path(folder).is_dir():
        return {"ok": False, "msg": "Tập này chưa tải về máy — bấm Xem trước (tab Chỉnh sửa) hoặc chạy tập rồi thử lại."}
    giay = _so(data.get("giay"), float, 2.0, 0.0, 600.0)
    try:
        hook = pick_from_folder(Path(folder)).get("video")
        if not hook:
            return {"ok": False, "msg": f"Không thấy clip Hook trong {folder}"}
        THU_MUC_XEM_TRUOC.mkdir(parents=True, exist_ok=True)
        ra = THU_MUC_XEM_TRUOC / f"lam_dep_{it['id']}.jpg"
        r = subprocess.run([need_ffmpeg(), "-v", "error", "-y", "-ss", f"{giay:.2f}", "-i", str(hook), "-frames:v", "1",
                            "-q:v", "2", str(ra)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
        if r.returncode != 0 or not ra.is_file():
            return {"ok": False, "msg": "ffmpeg không lấy được khung hình: " + (r.stderr or "")[-300:]}
    except SystemExit as e:                        # pick_from_folder / need_ffmpeg thoát bằng sys.exit
        return {"ok": False, "msg": f"Lỗi: {e}"}
    except Exception as e:                         # noqa: BLE001
        return {"ok": False, "msg": f"Lỗi lấy khung hình: {e}"}
    return _dat_anh_mau(ra, f"giây {giay:g} clip Hook tập “{it.get('ten') or it['link']}”")


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
                  "loi": "", "canh_bao": "", "them_luc": datetime.now().strftime("%d/%m %H:%M"),
                  "dich": S.drive_dich_chon, "tai_len": {}}      # thư mục Drive nhận video = ô chọn dưới thẻ 2 lúc thêm
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
    if them and not kho_clip(S.goc_dir) and not S.tuy_chon.get("khong_clip_goc"):
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
        if not kho_clip(S.goc_dir) and not S.tuy_chon.get("khong_clip_goc"):
            return {"ok": False, "msg": "Chưa có thư mục clip gốc (hoặc thư mục không có video)."}
        S.running = True
        S.stop_flag.clear()
        S.bo_nghi.clear()
        S.dung_sau_tap, S.nghi_den = False, 0.0
        S.chon_thu = bool(_data.get("chon_thu")) if isinstance(_data, dict) else False
    threading.Thread(target=_worker, daemon=True, name="worker").start()
    return {"ok": True, "msg": (f"Chọn thử {len(cho)} tập (không dựng video)." if S.chon_thu else f"Bắt đầu {len(cho)} tập.")}


def api_chon_thu(_data):
    """Nút 'Chọn thử' (user 23/10): chạy mọi mục chờ ở chế độ --chon-thu — tải Drive, lấy mốc, AI chọn cảnh + soát, ghi tab
    Thiếu + file ghi chú, KHÔNG dựng video; mục về lại trạng thái chờ. Bổ sung kho xong thì bấm ▶ Chạy như thường."""
    return api_start({"chon_thu": True})


def api_stop(_data):
    with S.lock:
        if not S.running:
            return {"ok": False, "msg": "Không có gì đang chạy."}
        S.stop_flag.set()
        S.bo_nghi.set()                            # đang nghỉ giữa hai tập thì thoát nghỉ luôn
        p = S.proc
    if p and p.poll() is None:
        _giet_cay(p)
    S.log("⏹ Dừng ngay — mục đang làm về trạng thái chờ.")
    return {"ok": True}


def api_stop_sau(_data):
    """Bật/tắt 'Dừng sau tập này': tập đang dựng chạy nốt (kể cả tải lên Drive), không tải tập kế; đang nghỉ thì dừng luôn."""
    with S.lock:
        if not S.running:
            return {"ok": False, "msg": "Không có gì đang chạy."}
        S.dung_sau_tap = not S.dung_sau_tap
        bat = S.dung_sau_tap
    S.log("⏸ Sẽ dừng sau khi xong tập đang chạy (bấm lại để hủy)." if bat else "↩ Đã hủy 'Dừng sau tập này', chạy tiếp hàng đợi.")
    return {"ok": True, "dung_sau_tap": bat}


def api_tiep_ngay(_data):
    """Đang nghỉ giữa hai tập -> bỏ nghỉ, tải và dựng tập kế ngay."""
    with S.lock:
        if not (S.running and S.nghi_den):
            return {"ok": False, "msg": "Không đang nghỉ giữa các tập."}
        S.bo_nghi.set()
    return {"ok": True}


def api_clipboard(data):
    """Đọc / ghi clipboard của máy cho nút Dán, Cmd+V/C/X trong cửa sổ desktop (WebView trên Mac không có menu Edit nên
    phím tắt dán/chép không chạy; trình duyệt cũng hay chặn navigator.clipboard)."""
    ghi = data.get("ghi")
    try:
        if sys.platform == "darwin":
            if ghi is not None:
                subprocess.run(["pbcopy"], input=str(ghi), text=True, encoding="utf-8", timeout=10, check=True)
                return {"ok": True}
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            return {"ok": True, "text": r.stdout}
        if os.name == "nt":
            if ghi is not None:
                subprocess.run(["clip"], input=str(ghi), text=True, encoding="utf-16le", timeout=10, check=True,
                               creationflags=NO_WINDOW)
                return {"ok": True}
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                               creationflags=NO_WINDOW)
            return {"ok": True, "text": r.stdout.rstrip("\r\n")}
        return {"ok": False, "msg": "Chưa hỗ trợ clipboard trên hệ điều hành này."}
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "msg": f"Không đọc/ghi được clipboard: {e}"}


def api_mo(data):
    """Mở file kết quả / thư mục của một mục bằng ứng dụng mặc định (Explorer / Finder)."""
    loai = data.get("loai")
    if loai in ("downloads", "thu_muc_ra"):
        _mo(thu_muc_ra())
        return {"ok": True}
    if loai == "done":                             # <thư mục kết quả>\done\ — mỗi tập một thư mục con
        d = thu_muc_done()
        d.mkdir(parents=True, exist_ok=True)
        _mo(d)
        return {"ok": True}
    if loai == "goc":
        if not S.goc_dir or not Path(S.goc_dir).is_dir():
            return {"ok": False, "msg": "Chưa có thư mục clip gốc."}
        _mo(S.goc_dir)
        return {"ok": True}
    if loai == "minh_hoa":                         # thư mục video mẫu (mặc định chưa có thì tạo)
        d = Path(S.minh_hoa_dir)
        if d == THU_MUC_MINH_HOA:
            d.mkdir(parents=True, exist_ok=True)
        if not d.is_dir():
            return {"ok": False, "msg": f"Không thấy thư mục video mẫu: {d}"}
        _mo(d)
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
        _mo(p)
        return {"ok": True}
    with S.lock:
        it = S.find(data.get("id"))
        khoa = {"video": "out", "thu_muc_video": "out", "srt": "srt", "preview": "preview", "tai": "thu_muc",
                "link_minh_hoa": "minh_hoa_file"}.get(loai)
        path = it and khoa and it.get(khoa)
    if not path or not Path(path).exists():
        return {"ok": False, "msg": "File không còn (đã xoá/di chuyển?)."}
    _mo(path, chon=loai == "thu_muc_video")
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
    ("Làm đẹp :", "Làm đẹp"),
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
    m = re.match(r"^(XONG|CHỌN THỬ|Xem trước|Phụ đề|Thời lượng|Phần sau|Minh họa|Link minh họa|Âm thanh)\s*:\s*(.+)$", s)
    if not m:
        return
    k, v = m.group(1), m.group(2).strip()
    if k == "XONG":
        it["out"] = v
    elif k == "CHỌN THỬ":                           # "6 cảnh, 2 thiếu (1 AI thấy chưa hợp) — đã ghi … | <file ghi chú>"
        it["chon_thu_xong"] = v.split(" | ")[0].strip()
    elif k == "Xem trước":
        it["preview"] = v
    elif k == "Link minh họa":                     # file .txt cạnh video: cảnh nào ở mốc nào, dùng Link Drive nào
        it["minh_hoa_file"] = v
    elif k == "Âm thanh" and "lần chuyển cảnh" in v:   # "7/9 lần chuyển cảnh có tiếng: 12.2s AT07 (wipeleft) → ..."
        it["am_thanh"] = v
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
        chon_thu = S.chon_thu
        # seed: cố định (tab Chỉnh sửa) > seed của lần chọn thử trước (chạy thật chọn cùng cách, chỉ khác kho đã bổ sung) > ngẫu nhiên
        seed = tc["seed"] if tc["seed"] is not None else (it.get("seed_chon_thu") or random.randrange(1, 10 ** 9))
        it.update(status=DANG, buoc="Tải Drive", loi="", bat_dau=t0, out="", srt="", preview="", phan_sau="",
                  minh_hoa_file="", am_thanh="", seed=seed, tai_len={})
        da_chon_thu = (not chon_thu) and bool(it.get("seed_chon_thu"))   # chạy thật sau khi đã chọn thử
        it.pop("chon_thu_xong", None)              # tóm tắt của lượt trước không được tính là kết quả lượt này
        if chon_thu:
            it["seed_chon_thu"] = seed
            it.pop("chon_thu", None)
        S.current = it["id"]
        S.save()
    kho = kho_clip(goc)
    kcg = bool(tc.get("khong_clip_goc"))
    S.log(f"{'🔍 CHỌN THỬ' if chon_thu else '▶'} [{it['id']}] {ten}  —  " + ("KHÔNG dùng clip gốc (phần sau 100% cảnh kho)" if kcg else
          f"clip gốc: {Path(goc).name if goc else '(chưa có)'} ({len(kho)} clip)") + f", seed {seed}")
    if not kho and not kcg:
        S.log(f"✗ [{it['id']}] thư mục clip gốc trống hoặc không tồn tại")
        return _ket_thuc(it, LOI, "Không có clip gốc (chọn lại thư mục clip).", t0)

    # 1) tải thư mục Drive
    try:
        # Downloads\<tên thư mục Drive = tên kịch bản>; đã có thì dùng lại, chỉ tải file thiếu
        ten_drive, dest, _files = dtm.tai_thu_muc_theo_ten(link, thu_muc_ra(), log=S.log, dung=S.stop_flag.is_set)
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
    tham_so = args_tuy_chon(tc, S.minh_hoa_dir)
    if da_chon_thu and "--minh-hoa-hoi-lai" in tham_so:
        # user 23/10: đã bấm Chọn thử trước thì lần Chạy thật KHÔNG hỏi GPT từ khóa lại (dùng lại trả lời + seed của lần chọn
        # thử, chỉ chọn lại cảnh với kho đã bổ sung rồi AI soát thêm một lần); chưa chọn thử thì vẫn hỏi lại như cài đặt
        tham_so.remove("--minh-hoa-hoi-lai")
        S.log(f"   [{it['id']}] đã chọn thử trước đó → dùng lại từ khóa GPT và seed {seed}, chỉ chọn lại cảnh với kho mới")
    cmd = [python_exe(), "-u", str(TOOL), "--thu-muc", str(dest), *(["--phan-sau", goc] if goc else []), "--seed", str(seed),
           "--out", str(thu_muc_ra()), *tham_so, *(["--chon-thu"] if chon_thu else [])]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    cuoi: list[str] = []
    try:
        p = subprocess.Popen(cmd, cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW, **NHOM_RIENG,
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
    if chon_thu:
        with S.lock:
            tom_tat = it.get("chon_thu_xong") or ""
        if rc == 0 and tom_tat:
            S.log(f"🔍 [{it['id']}] chọn thử xong sau {round(time.time() - t0)}s: {tom_tat} — bổ sung kho rồi bấm ▶ Chạy")
            with S.lock:
                it["chon_thu"] = {"luc": time.strftime("%d/%m %H:%M"), "tom_tat": tom_tat}
            return _ket_thuc(it, CHO, "", t0)   # về chờ, không dựng
        ly_do = next((s.strip() for s in reversed(cuoi) if s.strip() and not s.startswith(" ")), "") or f"mã thoát {rc}"
        S.log(f"✗ [{it['id']}] chọn thử lỗi: {ly_do}")
        return _ket_thuc(it, LOI, f"Chọn thử lỗi: {ly_do}", t0)
    if rc == 0 and out and Path(out).exists():
        S.log(f"✓ [{it['id']}] XONG sau {round(time.time() - t0)}s: {out}")
        with S.lock:
            it.pop("seed_chon_thu", None)          # đã dựng thật -> lần chạy lại sau xáo seed mới như thường
            it.pop("chon_thu", None)               # bỏ nhãn "🔍 chọn thử" (Chạy lại sau đó không còn hiện nhãn cũ)
        _ket_thuc(it, XONG, "", t0)
        _tai_len_muc(it)                           # tập từ Sheet có thư mục đích + công tắc bật: tải lên Drive, ghi cột G
        return
    ly_do = next((s.strip() for s in reversed(cuoi) if s.strip() and not s.startswith(" ")), "") or f"mã thoát {rc}"
    S.log(f"✗ [{it['id']}] lỗi: {ly_do}")
    return _ket_thuc(it, LOI, ly_do, t0)


def _tinh_vector_kho(sheet: str) -> None:
    """Tính vector nghĩa cho các dòng kho còn thiếu (vector_kho.py --cap-nhat, tiến trình con); kết quả vào S.kho_mh['vector']."""
    with S.lock:
        S.kho_mh["vector"] = {**(S.kho_mh.get("vector") or {}), "dang": True}
        thu_muc = S.minh_hoa_dir
    kq: dict = {}
    try:
        cmd = [python_exe(), "-u", str(APP_DIR / "vector_kho.py"), "--cap-nhat", sheet, "--thu-muc", thu_muc]
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(cmd, cwd=str(APP_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, creationflags=NO_WINDOW, timeout=1800)
        for line in (r.stdout or "").splitlines():
            if line.startswith("VECTOR "):
                kq = json.loads(line[7:])
            elif line.strip() and "hf_xet" not in line and "Xet Storage" not in line:
                S.log("   [vector] " + line.strip())
        if not kq:
            kq = {"loi": (r.stderr or r.stdout or "").strip()[-300:] or f"mã thoát {r.returncode}"}
    except Exception as e:                         # noqa: BLE001
        kq = {"loi": str(e)}
    kq["dang"] = False
    kq["luc"] = time.strftime("%H:%M:%S")
    with S.lock:
        S.kho_mh["vector"] = kq
    if kq.get("loi"):
        S.log(f"⚠ vector kho: {kq['loi']} — tìm clip chỉ còn so chữ")


def _cap_nhat_kho_dau_luot() -> None:
    """Đầu mỗi lượt Bắt đầu: đọc Sheet kho MỘT lần (bỏ bản đệm) + tính vector cho dòng mới; các tập trong lượt dùng chung
    bản đệm (CSV_TTL 12 giờ), không gọi Sheet lại từng tập (user 22/10). Bấm "Cập nhật" ở thẻ kho cũng chạy y vậy."""
    with S.lock:
        sheet, bat = S.tuy_chon.get("minh_hoa_sheet"), S.tuy_chon.get("minh_hoa")
    if not sheet or not bat:
        return
    S.log("Kho minh họa: đọc Sheet một lần cho lượt chạy này (xem có cảnh mới) + cập nhật vector…")
    S.lam_moi_kho_mh(moi=True)                     # đồng bộ, trong thread worker


def _worker():
    xong = loi = thu = 0
    da_thu: set = set()                            # chọn thử: mục đã làm trong lượt này (về lại chờ nên không được lấy lại)
    try:
        _cap_nhat_kho_dau_luot()
        while not S.stop_flag.is_set():
            with S.lock:
                it = next((x for x in S.items if x.get("status") == CHO and x.get("id") not in da_thu), None)
            if it is None:
                break
            if S.chon_thu:
                da_thu.add(it["id"])
            _chay_muc(it)
            with S.lock:
                st = it.get("status")
                con = any(x.get("status") == CHO and x.get("id") not in da_thu for x in S.items)
                nghi = float(S.tuy_chon.get("nghi_giua_tap_phut") or 0)
            xong += st == XONG
            loi += st == LOI
            thu += bool(S.chon_thu and st == CHO)
            if S.stop_flag.is_set() or not con or S.dung_sau_tap:
                break
            if nghi > 0 and not S.chon_thu and not _nghi_giua_tap(nghi):   # nghỉ giữa hai tập (chọn thử thì không); dừng -> thoát
                break
        with S.lock:
            con = sum(1 for x in S.items if x.get("status") == CHO and x.get("id") not in da_thu)
        if S.stop_flag.is_set():
            S.log(f"⏹ Đã dừng ngay theo yêu cầu. {xong} xong, {loi} lỗi.")
        elif S.chon_thu:
            S.log(f"🔍 Chọn thử xong {thu} tập, {loi} lỗi — xem tab Thiếu của Sheet kho và file ghi chú từng mục; "
                  "bổ sung kho rồi bấm ▶ Chạy (sẽ dùng lại từ khóa GPT và seed của lần chọn thử).")
        elif not con:
            S.log(f"🎉 Hết hàng đợi: {xong} xong, {loi} lỗi." + (" Bấm 'Chạy lại mục lỗi' để thử lại." if loi else ""))
        else:
            S.log(f"⏸ Đã dừng sau khi xong tập đang chạy: {xong} xong, {loi} lỗi, còn {con} tập chờ — bấm ▶ Chạy để tiếp.")
    except Exception as e:
        S.log(f"❌ LỖI worker: {e}")
    finally:
        with S.lock:
            S.running = False
            S.current = None
            S.proc = None
            S.dung_sau_tap, S.nghi_den = False, 0.0
            S.chon_thu = False
            S.save()


def _nghi_giua_tap(phut: float) -> bool:
    """Nghỉ giữa hai tập (tùy chọn nghi_giua_tap_phut, tab Chỉnh sửa). Giao diện hiện đếm ngược (nghi_con) + nút
    "Chạy tiếp ngay" (bo_nghi). -> False nếu trong lúc nghỉ có lệnh Dừng ngay / Dừng sau tập này (worker thoát)."""
    with S.lock:
        S.nghi_den = time.time() + phut * 60
        S.current = None
        S.bo_nghi.clear()
    S.log(f"⏳ Nghỉ {phut:g} phút rồi chạy tập kế ('Chạy tiếp ngay' để bỏ nghỉ, 'Dừng sau tập này' để dừng tại đây).")
    try:
        while time.time() < S.nghi_den:
            if S.stop_flag.is_set() or S.dung_sau_tap:
                return False
            if S.bo_nghi.wait(0.5):
                S.log("⏭ Bỏ nghỉ, chạy tập kế ngay.")
                break
        return True
    finally:
        with S.lock:
            S.nghi_den = 0.0


# ------------------------------------------------------------------ HTTP server
ROUTES = {
    "/api/set_goc_dir": api_set_goc_dir,
    "/api/chon_thu_muc": api_chon_thu_muc,
    "/api/set_minh_hoa_dir": api_set_minh_hoa_dir,
    "/api/chon_thu_muc_minh_hoa": api_chon_thu_muc_minh_hoa,
    "/api/set_minh_hoa_sheet": api_set_minh_hoa_sheet,
    "/api/kho_minh_hoa_lam_moi": api_kho_minh_hoa_lam_moi,
    "/api/tai_minh_hoa": api_tai_minh_hoa,
    "/api/set_minh_hoa_hoi_lai": api_set_minh_hoa_hoi_lai,
    "/api/set_khong_clip_goc": api_set_khong_clip_goc,
    "/api/nghe_thu_giong": api_nghe_thu_giong,
    "/api/google_dang_nhap": api_google_dang_nhap,
    "/api/google_dang_xuat": api_google_dang_xuat,
    "/api/google_chon_client": api_google_chon_client,
    "/api/set_tu_tai_len": api_set_tu_tai_len,
    "/api/set_tu_don_rac": api_set_tu_don_rac,
    "/api/set_drive_dich": api_set_drive_dich,
    "/api/drive_dich_them": api_drive_dich_them,
    "/api/drive_dich_xoa": api_drive_dich_xoa,
    "/api/doc_sheet": api_doc_sheet,
    "/api/them_tu_sheet": api_them_tu_sheet,
    "/api/tai_len_lai": api_tai_len_lai,
    "/api/set_dich_muc": api_set_dich_muc,
    "/api/add_links": api_add_links,
    "/api/delete": api_delete,
    "/api/retry": api_retry,
    "/api/clear_done": api_clear_done,
    "/api/start": api_start,
    "/api/chon_thu": api_chon_thu,
    "/api/stop": api_stop,
    "/api/stop_sau": api_stop_sau,
    "/api/tiep_ngay": api_tiep_ngay,
    "/api/mo": api_mo,
    "/api/clipboard": api_clipboard,
    "/api/save_tuy_chon": api_save_tuy_chon,
    "/api/mac_dinh_tuy_chon": api_mac_dinh_tuy_chon,
    "/api/lam_dep_xem_thu": api_lam_dep_xem_thu,
    "/api/lam_dep_set_anh": api_lam_dep_set_anh,
    "/api/lam_dep_chon_anh": api_lam_dep_chon_anh,
    "/api/lam_dep_khung_hinh": api_lam_dep_khung_hinh,
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
AM_MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


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
        elif u.path == "/am":                      # audio nghe thử: /am?p=<đường dẫn tuyệt đối> (chỉ trong thư mục xem trước / kết quả)
            p = Path((parse_qs(u.query).get("p") or [""])[0])
            mime = AM_MIME.get(p.suffix.lower())
            if mime and _duoc_phep(p):
                self._send(p.read_bytes(), mime)
            else:
                self._json({"ok": False, "msg": "Không có file audio này."}, 404)
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


# Cổng dùng lần gần nhất. 8766 bị myvoice/myvideo (cũng mặc định 8766) chiếm thì
# server phải nhảy sang cổng khác — ghi lại để lần sau (a) dang_chay_san() biết
# tìm bản đang chạy ở đâu và (b) make_server() lấy lại đúng cổng đó: địa chỉ web
# không đổi, khỏi dò lại mỗi lần. Xoá file = quay về 8766.
CONG_FILE = Path(__file__).resolve().parent / "cong.txt"


def _cong_da_nho() -> int | None:
    try:
        p = int(CONG_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return p if 1024 <= p <= 65535 else None


def _nho_cong(port: int) -> None:
    try:
        CONG_FILE.write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def _cong_trong(port: int) -> bool:
    """Cổng còn trống không — BIND THỬ (tức thì). Không dò bằng connect: connect tới
    cổng trống trên Windows chờ hết timeout (~0,4 s mỗi cổng)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def _cac_cong_thu() -> list[int]:
    """Thứ tự dò: cổng nhớ từ lần trước (nếu có) rồi PORT mặc định."""
    nho = _cong_da_nho()
    return [nho, PORT] if nho not in (None, PORT) else [PORT]


def dang_chay_san() -> str | None:
    """Đã có server Ghép video chạy sẵn (mở app lần hai)? -> url của nó, không thì None.
    Dò cổng nhớ lần trước rồi PORT; cổng còn trống thì khỏi hỏi HTTP cho nhanh."""
    for port in _cac_cong_thu():
        if _cong_trong(port):
            continue
        url = f"http://{HOST}:{port}/"
        try:
            with urlopen(url + "api/state?after=999999999", timeout=1.5) as r:
                j = json.loads(r.read().decode("utf-8"))
            if "items" in j and "goc" in j:
                return url
        except Exception:
            pass
    return None


def make_server():
    """Mở server: cổng nhớ lần trước → PORT → cổng trống bất kỳ (khi cả hai bị chương
    trình khác chiếm). Cổng lấy được ghi vào cong.txt cho lần sau. Trả về (httpd, url).
    Dùng chung cho main() và cửa sổ trạng thái app_gui.py (hai nơi đó gọi
    dang_chay_san() trước để không chạy hai bản cùng lúc)."""
    httpd = None
    for port in _cac_cong_thu():
        try:
            httpd = _Server((HOST, port), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        httpd = _Server((HOST, 0), Handler)
    _nho_cong(httpd.server_address[1])
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
