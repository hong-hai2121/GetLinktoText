# -*- coding: utf-8 -*-
"""Giao diện cho cat_dau.py (user 11/11/2026: "làm giao diện đi, Sheet nhiều video mà").

Một cửa sổ: dán link tab Sheet -> bảng các dòng có Link Đăng -> tick dòng cần chạy.
  · "Làm thử dòng N": chạy riêng dòng đang bôi xanh (kể cả khi đã có v2), xong tự phát bản v2 ở khung bên phải.
  · "Cắt N dòng đã tick": chạy cả loạt; dòng xong tự bỏ tick, dòng lỗi / cần xem lại vẫn tick để chạy lại.
  · "Tải N dòng tick lên Drive" (len_drive.py): bản v2 của các dòng đã tick lên thư mục ở cột Link video (E), link ghi
    vào cột H; cột "Drive" của bảng báo dòng nào đã lên. Ô "Cắt xong tải luôn lên Drive" làm hai việc liền nhau, trừ
    dòng có cảnh báo cần nghe lại.
  · Khung xem lại bên phải bảng (user chốt 11/11 "khung phát cạnh bảng"): bấm một dòng là phát luôn 12 giây đầu bản
    v2, có tiếng; dòng CHƯA có v2 mà đã tải bản gốc thì phát bản gốc (user 11/11: "video không có bản trùng lặp thì
    phải ấn vào mở lên để chọn được thời gian cắt"). Nút "Cả video" phát hết; "Gốc quanh chỗ cắt" phát bản gốc từ 4
    giây trước mốc cắt tới 6 giây sau để nghe đoạn đã bỏ nối sang phần giữ lại.
  · "Xem bản mới ↗" / "Xem bản gốc ↗": mở file bằng trình phát của Windows để tự kéo thanh thời gian (user 11/11:
    "ấn vào mở ra ngoài tự tôi kéo cũng được, không cần tích hợp vào app" — ĐỪNG làm thanh kéo trong app nữa). Bản gốc
    chưa tải thì tải về rồi mở. Bấm đúp một dòng cũng mở bản mới.
  · "Cắt tay ở giây [..] ✂ Cắt" (user 11/11: máy dò sai thì "để tôi chọn thủ công rồi phần mềm cắt"): cắt dòng đang chọn ở
    giây (của bản gốc) gõ vào, mốc tự bám khoảng lặng gần đó (cat_dau.cat_tay), xong phát luôn bản v2 để nghe. Dòng đã
    có v2 thì hỏi lại trước khi cắt đè.

Mọi việc nặng (tải, nghe, render) chạy trong luồng phụ và gọi thẳng các hàm của cat_dau, nên model nhận diện nạp một
lần cho cả phiên. Luồng phụ chỉ đẩy sự kiện vào hàng đợi; mọi thao tác Tk nằm ở luồng chính (_bom).

Khung xem lại không cần thư viện phát video: ffmpeg xuất khung hình đã thu nhỏ qua đường ống (25 hình/giây), tiếng
được ffmpeg tách ra file WAV tạm rồi phát bằng winsound; hình bám theo đồng hồ tính từ lúc tiếng bắt đầu.

Đóng cửa sổ bằng os._exit: không để ctranslate2 hủy model GPU lúc thoát (từng abort 0xC0000409).

Chạy: bấm đúp chay.bat (hoặc  pythonw giao_dien.py).
"""
import os
import sys

if sys.stdout is None:          # pythonw không có console: thư viện in ra stdout/stderr sẽ lỗi nếu để None
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import json
import queue
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import traceback
import winsound
from pathlib import Path
from tkinter import messagebox, ttk
from types import SimpleNamespace

from PIL import Image, ImageTk

import cat_dau as cd

NEN, THE, CHU, MO, XANH, VIEN = "#eef2f7", "#ffffff", "#0f172a", "#64748b", "#2563eb", "#cbd5e1"
NEN_VIDEO = "#0f172a"
F, F_DAM, F_NHO = ("Segoe UI", 10), ("Segoe UI", 10, "bold"), ("Segoe UI", 9)
COT = (  # (mã, tên cột, rộng, canh, co giãn)
    ("chon", "☐", 44, "center", False), ("dong", "Dòng", 56, "center", False), ("stt", "STT", 50, "center", False),
    ("tieu_de", "Tiêu đề (cột B)", 340, "w", True), ("trang_thai", "Trạng thái", 190, "w", False),
    ("cat", "Cắt bỏ", 70, "center", False), ("drive", "Drive", 84, "center", False), ("ghi_chu", "Ghi chú", 130, "w", True))
XONG_HAN = ("xong", "đã có", "không có đoạn lặp")       # trạng thái không cần chạy lại

XEM_GIAY = 12.0             # nút "12 giây đầu": đủ nghe hết câu mở đầu
XEM_FPS = 25                # số hình mỗi giây ở khung xem lại
TRUOC_CAT, SAU_CAT = 4.0, 6.0   # "Gốc quanh chỗ cắt": phát từ 4 giây trước mốc cắt tới 6 giây sau
TRE_TIENG = 0.05            # winsound cần chừng này mới ra tiếng -> hình chờ theo
THU_MUC_TAM = Path(tempfile.gettempdir()) / "CatDauVideo_xem"       # file WAV tạm của khung xem lại


def center_on_screen(win, w: int, h: int):
    """Mở cửa sổ giữa màn hình; màn hình thấp (864px) thì co chiều cao, chừa chỗ cho thanh tác vụ."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(w, sw - 60), min(h, sh - 110)
    # h là phần trong cửa sổ; thanh tiêu đề + viền ~40px và thanh tác vụ ~48px nằm ngoài -> canh giữa phần còn lại
    win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - 48 - h - 40) // 2)}")


def _phut(giay: float) -> str:
    return f"{int(giay // 60)}:{int(giay % 60):02d}"


def _doc_giay(s: str) -> float | None:
    """'6' · '5.3' · '5,3' · '0:06' · '1:02.5' -> số giây; không hiểu thì None."""
    s = s.strip().replace(",", ".")
    try:
        if ":" in s:
            phut, giay = s.split(":", 1)
            return int(phut) * 60 + float(giay)
        return float(s)
    except ValueError:
        return None


class _Huy(Exception):
    """Phiên xem lại bị thay bằng phiên khác trong lúc đang chuẩn bị."""


def _doc_khung(proc, q: queue.Queue, dung: threading.Event, n: int):
    """Luồng đọc khung hình thô (n byte mỗi khung) từ ffmpeg vào hàng đợi; hết video thì đẩy None."""
    i = 0
    try:
        while not dung.is_set():
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            while not dung.is_set():
                try:
                    q.put((i, buf), timeout=0.2)
                    break
                except queue.Full:
                    pass
            i += 1
    except Exception:       # noqa: BLE001 — ffmpeg bị tắt giữa chừng
        pass
    while not dung.is_set():
        try:
            q.put(None, timeout=0.2)
            break
        except queue.Full:
            pass


def _don_xem(proc=None, wav=None, dung=None):
    """Tắt ffmpeg của một phiên xem lại và xóa file tiếng tạm."""
    if dung is not None:
        dung.set()
    if proc is not None:
        try:
            proc.kill()
            proc.stdout.close()
        except Exception:       # noqa: BLE001
            pass
    if wav is not None:
        try:
            Path(wav).unlink(missing_ok=True)
        except OSError:         # winsound chưa nhả file: lần mở sau dọn
            pass


class UngDung(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cắt đoạn đọc tiêu đề lặp ở đầu video")
        self.configure(bg=NEN)
        self.hang_doi = queue.Queue()
        self.ds, self.theo_dong = [], {}
        self.tick, self.kq, self.tam = set(), {}, {}        # dòng đang tick · kết quả theo dòng · trạng thái tạm lúc chạy
        self.sheet, self.ten_bo, self.thu_muc, self.so_tay = "", "", None, {}
        self._so_tay_goc = {}
        self.dang_tai = self.dang_chay = False
        self.dong_chay, self.thu_tu = None, (0, 0)
        self.dung = threading.Event()
        self.lam_lai = tk.BooleanVar(value=False)
        self.tu_len = tk.BooleanVar(value=False)            # cắt xong tự tải bản v2 lên Drive + ghi cột H
        self.len_loi = {}                                   # dòng -> lỗi của lần tải lên Drive gần nhất
        # khung xem lại: xem = phiên đang phát, xem_cho = phiên đang chuẩn bị, xem_phien tăng mỗi lần phát / dừng
        self.xem, self.xem_cho, self.xem_phien = None, None, 0
        self.xem_w, self.xem_h = 117, 208
        self.tu_phat = tk.BooleanVar(value=True)
        self._hen, self._bo_tha = None, False
        self._dang_tai_goc = False                          # đang tải bản gốc về để mở bằng trình phát ngoài
        self._kieu()
        self._dung_giao_dien()
        center_on_screen(self, 1240, 750)
        self.minsize(1040, 700)
        self._dat_co_man_hinh()
        self.protocol("WM_DELETE_WINDOW", self._dong_cua_so)
        cd.log = lambda *a: self.hang_doi.put(("log", " ".join(str(x) for x in a)))
        cd.buoc = lambda ten: self.hang_doi.put(("buoc", ten))
        self.o_link.insert(0, cd._doc_json(cd.FILE_CAU_HINH).get("sheet") or cd.SHEET_MAC_DINH)
        for cu in THU_MUC_TAM.glob("xem_*.wav"):            # file tiếng tạm sót lại từ lần mở trước
            try:
                cu.unlink()
            except OSError:
                pass
        self._cap_nhat_nut()
        self.after(80, self._bom)
        self.after(250, self.tai_sheet)

    # ------------------------------------------------------------ dựng giao diện
    def _kieu(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", font=F)
        st.configure("TFrame", background=NEN)
        st.configure("TLabel", background=NEN, foreground=CHU)
        st.configure("Mo.TLabel", background=NEN, foreground=MO)
        st.configure("TCheckbutton", background=NEN, foreground=CHU)
        st.map("TCheckbutton", background=[("active", NEN)])
        st.configure("Nho.TCheckbutton", font=F_NHO)
        st.configure("TButton", padding=(12, 6), background="#e2e8f0", bordercolor=VIEN)
        st.map("TButton", background=[("disabled", "#eef2f7"), ("active", "#d5deea")])
        st.configure("Nho.TButton", padding=(8, 3), font=F_NHO)
        st.configure("Chinh.TButton", padding=(14, 7), font=F_DAM, background=XANH, foreground="#ffffff", bordercolor=XANH)
        st.map("Chinh.TButton", background=[("disabled", "#a9bbdb"), ("active", "#1d4ed8")],
               foreground=[("disabled", "#f1f5f9")])
        st.configure("Treeview", rowheight=27, font=F, background=THE, fieldbackground=THE, foreground=CHU, bordercolor=VIEN)
        st.configure("Treeview.Heading", font=F_DAM, background="#e2e8f0", foreground=CHU, padding=(6, 5))
        st.map("Treeview", background=[("selected", "#bfdbfe")], foreground=[("selected", CHU)])
        st.configure("Horizontal.TProgressbar", troughcolor="#dbe3ee", background=XANH, bordercolor="#dbe3ee",
                     lightcolor=XANH, darkcolor=XANH)

    def _dung_giao_dien(self):
        # cột 0: thông tin + bảng + chi tiết (hàng 1-3) · cột 1: khung xem lại, cao bằng cả ba hàng đó
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)          # chỉ bảng co giãn; các hàng nút giữ nguyên chiều cao

        tren = ttk.Frame(self, padding=(14, 12, 14, 2))
        tren.grid(row=0, column=0, columnspan=2, sticky="ew")
        tren.columnconfigure(1, weight=1)
        ttk.Label(tren, text="Link tab Sheet", font=F_DAM).grid(row=0, column=0, padx=(0, 8))
        self.o_link = ttk.Entry(tren)
        self.o_link.grid(row=0, column=1, sticky="ew", ipady=3)
        self.o_link.bind("<Return>", lambda e: self.tai_sheet())
        self.nut_tai = ttk.Button(tren, text="Tải danh sách", command=self.tai_sheet)
        self.nut_tai.grid(row=0, column=2, padx=(8, 0))

        giua = ttk.Frame(self, padding=(14, 6, 12, 6))
        giua.grid(row=1, column=0, sticky="ew")
        giua.columnconfigure(0, weight=1)
        self.nhan_bo = ttk.Label(giua, text="Chưa tải danh sách.", style="Mo.TLabel", width=1)
        self.nhan_bo.grid(row=0, column=0, sticky="ew")
        self.nut_tick = [
            ttk.Button(giua, text="Tick dòng chưa làm", style="Nho.TButton", command=lambda: self._tick_loat("chua")),
            ttk.Button(giua, text="Tick dòng chưa lên Drive", style="Nho.TButton", command=lambda: self._tick_loat("chua_len")),
            ttk.Button(giua, text="Tick tất cả", style="Nho.TButton", command=lambda: self._tick_loat("het")),
            ttk.Button(giua, text="Bỏ tick", style="Nho.TButton", command=lambda: self._tick_loat("bo")),
        ]
        for i, b in enumerate(self.nut_tick, start=1):
            b.grid(row=0, column=i, padx=(6, 0))

        khung = ttk.Frame(self, padding=(14, 0, 12, 0))
        khung.grid(row=2, column=0, sticky="nsew")
        khung.columnconfigure(0, weight=1)
        khung.rowconfigure(0, weight=1)
        self.bang = ttk.Treeview(khung, columns=[c[0] for c in COT], show="headings", selectmode="browse", height=6)
        for ma, ten, rong, canh, co in COT:
            self.bang.heading(ma, text=ten, anchor="center" if canh == "center" else "w")
            self.bang.column(ma, width=rong, minwidth=min(rong, 60), anchor=canh, stretch=co)
        self.bang.heading("chon", command=self._tick_dau_cot)
        cuon = ttk.Scrollbar(khung, orient="vertical", command=self.bang.yview)
        self.bang.configure(yscrollcommand=cuon.set)
        self.bang.grid(row=0, column=0, sticky="nsew")
        cuon.grid(row=0, column=1, sticky="ns")
        self.bang.tag_configure("ok", background="#f0fdf4")
        self.bang.tag_configure("canh_bao", background="#fff7ed")
        self.bang.tag_configure("loi", background="#fef2f2")
        self.bang.tag_configure("chay", background="#eff6ff")
        self.bang.tag_configure("xam", foreground=MO)
        self.bang.bind("<Button-1>", self._bam_bang, add="+")
        self.bang.bind("<ButtonRelease-1>", self._tha_bang, add="+")
        self.bang.bind("<Double-1>", self._bam_dup)
        self.bang.bind("<space>", lambda e: self._doi_tick(self._dong_chon()))
        for phim in ("Up", "Down", "Prior", "Next", "Home", "End"):
            self.bang.bind(f"<KeyRelease-{phim}>", lambda e: self._hen_phat(), add="+")
        self.bang.bind("<<TreeviewSelect>>", lambda e: (self._ve_chi_tiet(), self._cap_nhat_nut()))

        vien = tk.Frame(self, bg=VIEN, padx=1, pady=1)
        vien.grid(row=3, column=0, sticky="ew", padx=(14, 12), pady=(8, 0))
        self.chi_tiet = tk.Text(vien, height=4, wrap="word", font=F, bg=THE, fg=CHU, relief="flat", padx=10, pady=6,
                                spacing1=1, spacing3=1, cursor="arrow", state="disabled")
        self.chi_tiet.pack(fill="x")
        self.chi_tiet.tag_configure("dau", font=F_DAM)
        self.chi_tiet.tag_configure("nhan", foreground=MO)

        self._dung_khung_xem()

        nut = ttk.Frame(self, padding=(14, 10, 14, 4))
        nut.grid(row=4, column=0, columnspan=2, sticky="ew")
        nut.columnconfigure(4, weight=1)
        self.nut_thu = ttk.Button(nut, text="▶ Làm thử 1 dòng", command=self.lam_thu)
        self.nut_thu.grid(row=0, column=0)
        self.nut_chay = ttk.Button(nut, text="▶▶ Cắt các dòng đã tick", style="Chinh.TButton", command=self.chay_tick)
        self.nut_chay.grid(row=0, column=1, padx=(8, 0))
        self.nut_len = ttk.Button(nut, text="↑ Tải dòng tick lên Drive", command=self.tai_len_tick)
        self.nut_len.grid(row=0, column=2, padx=(8, 0))
        self.nut_dung = ttk.Button(nut, text="■ Dừng", command=self.bam_dung)
        self.nut_dung.grid(row=0, column=3, padx=(8, 0))
        # mở bằng trình phát của Windows để tự kéo thanh thời gian tìm giây cần cắt (user 11/11: không cần kéo trong app)
        self.nut_v2 = ttk.Button(nut, text="Xem bản mới ↗", command=lambda: self.mo_ngoai("v2"))
        self.nut_v2.grid(row=0, column=5, padx=(8, 0))
        self.nut_goc = ttk.Button(nut, text="Xem bản gốc ↗", command=lambda: self.mo_ngoai("goc"))
        self.nut_goc.grid(row=0, column=6, padx=(8, 0))
        self.nut_thu_muc = ttk.Button(nut, text="Mở thư mục", command=self._mo_thu_muc)
        self.nut_thu_muc.grid(row=0, column=7, padx=(8, 0))

        td = ttk.Frame(self, padding=(14, 4, 14, 4))
        td.grid(row=5, column=0, columnspan=2, sticky="ew")
        td.columnconfigure(1, weight=1)
        self.thanh = ttk.Progressbar(td, length=220, mode="determinate")
        self.thanh.grid(row=0, column=0)
        self.nhan_tt = ttk.Label(td, text="", style="Mo.TLabel", width=1)       # width=1: chữ dài tự cắt, không đẩy mất ô tick
        self.nhan_tt.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.o_lam_lai = ttk.Checkbutton(td, text="Làm lại cả dòng đã có v2", variable=self.lam_lai)
        self.o_lam_lai.grid(row=0, column=2, padx=(12, 0))
        self.o_tu_len = ttk.Checkbutton(td, text="Cắt xong tải luôn lên Drive", variable=self.tu_len)
        self.o_tu_len.grid(row=0, column=3, padx=(14, 0))
        ttk.Checkbutton(td, text="Bấm dòng là phát luôn", variable=self.tu_phat).grid(row=0, column=4, padx=(14, 0))

        vien2 = tk.Frame(self, bg=VIEN, padx=1, pady=1)
        vien2.grid(row=6, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 12))
        vien2.columnconfigure(0, weight=1)
        self.nhat_ky = tk.Text(vien2, height=5, wrap="word", font=("Consolas", 9), bg="#f8fafc", fg="#334155",
                               relief="flat", padx=8, pady=4, state="disabled")
        cuon2 = ttk.Scrollbar(vien2, orient="vertical", command=self.nhat_ky.yview)
        self.nhat_ky.configure(yscrollcommand=cuon2.set)
        self.nhat_ky.grid(row=0, column=0, sticky="ew")
        cuon2.grid(row=0, column=1, sticky="ns")

    def _dung_khung_xem(self):
        k = self.khung_xem = ttk.Frame(self, padding=(0, 4, 14, 0))
        k.grid(row=1, column=1, rowspan=3, sticky="ns")
        k.columnconfigure(0, weight=1)
        self.nhan_xem = ttk.Label(k, text="Xem lại", font=F_DAM, width=1, anchor="w")
        self.nhan_xem.grid(row=0, column=0, sticky="ew")
        self.vien_hinh = tk.Frame(k, bg=VIEN, padx=1, pady=1)
        self.vien_hinh.grid(row=1, column=0, pady=(4, 4))
        self.man_hinh = tk.Canvas(self.vien_hinh, width=self.xem_w, height=self.xem_h, bg=NEN_VIDEO, highlightthickness=0)
        self.man_hinh.pack()
        self.anh = None
        self.anh_id = self.man_hinh.create_image(0, 0, anchor="nw")
        self.chu_id = self.man_hinh.create_text(0, 0, fill="#94a3b8", font=F_NHO, justify="center",
                                                text="Bấm vào một dòng\nđể xem video\ncủa dòng đó ở đây")
        # width=10: Canvas mặc định đòi rộng 378px, sẽ kéo cả cột phải rộng theo; sticky "ew" tự giãn bằng khung video
        self.thanh_xem = tk.Canvas(k, width=10, height=6, bg="#dbe3ee", highlightthickness=0)
        self.thanh_xem.grid(row=2, column=0, sticky="ew")
        self.thanh_xem_id = self.thanh_xem.create_rectangle(0, 0, 0, 6, fill=XANH, width=0)
        self.moc_xem_id = self.thanh_xem.create_rectangle(0, 0, 0, 6, fill="#dc2626", width=0, state="hidden")
        self.nhan_gio = ttk.Label(k, text=" ", style="Mo.TLabel", font=F_NHO, width=1, anchor="w")
        self.nhan_gio.grid(row=3, column=0, sticky="ew", pady=(1, 3))
        h1 = ttk.Frame(k)
        h1.grid(row=4, column=0, sticky="ew")
        h1.columnconfigure((0, 1), weight=1, uniform="xem")
        self.nut_xem_dau = ttk.Button(h1, text="▶ 12 giây đầu", style="Nho.TButton", command=lambda: self._phat("dau"))
        self.nut_xem_dau.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.nut_xem_het = ttk.Button(h1, text="▶ Cả video", style="Nho.TButton", command=lambda: self._phat("het"))
        self.nut_xem_het.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        h2 = ttk.Frame(k)
        h2.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        h2.columnconfigure(0, weight=1)
        self.nut_xem_goc = ttk.Button(h2, text="▶ Gốc quanh chỗ cắt", style="Nho.TButton", command=lambda: self._phat("goc"))
        self.nut_xem_goc.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.nut_xem_dung = ttk.Button(h2, text="■", width=3, style="Nho.TButton", command=self._xem_dung)
        self.nut_xem_dung.grid(row=0, column=1)
        # cắt tay: máy dò sai / không dò ra thì gõ giây mà lần đọc đúng bắt đầu (gõ áng chừng, mốc tự bám khoảng lặng gần đó).
        # Tìm giây: bấm "Xem bản gốc ↗" mở video ra trình phát ngoài rồi tự kéo (user 11/11: không cần kéo ngay trong app).
        h3 = ttk.Frame(k)
        h3.grid(row=6, column=0, sticky="ew", pady=(3, 0))
        h3.columnconfigure(1, weight=1)
        ttk.Label(h3, text="Cắt tay ở giây", font=F_NHO).grid(row=0, column=0)
        self.o_giay = ttk.Entry(h3, width=5, font=F_NHO, justify="center")
        self.o_giay.grid(row=0, column=1, sticky="ew", padx=5)
        self.o_giay.bind("<Return>", lambda e: self.cat_tay())
        self.nut_cat_tay = ttk.Button(h3, text="✂ Cắt", style="Nho.TButton", command=self.cat_tay)
        self.nut_cat_tay.grid(row=0, column=2)

    def _dat_co_man_hinh(self):
        """Cho khung video cao hết chỗ còn lại của cột phải (tỉ lệ dọc 9:16), sau khi cửa sổ đã có kích thước thật."""
        self.update()
        k = self.khung_xem
        con = k.winfo_height() - (k.winfo_reqheight() - self.vien_hinh.winfo_reqheight()) - 2
        self.xem_h = max(208, min(400, con)) // 16 * 16
        self.xem_w = self.xem_h * 9 // 16
        self.man_hinh.configure(width=self.xem_w, height=self.xem_h)
        self.anh = ImageTk.PhotoImage(Image.new("RGB", (self.xem_w, self.xem_h), NEN_VIDEO))
        self.man_hinh.itemconfigure(self.anh_id, image=self.anh)
        self.man_hinh.coords(self.chu_id, self.xem_w // 2, self.xem_h // 2)
        self.man_hinh.itemconfigure(self.chu_id, width=self.xem_w - 16)
        self.man_hinh.tag_raise(self.chu_id)

    # ------------------------------------------------------------ bơm sự kiện từ luồng phụ
    def _bom(self):
        try:
            while True:
                loai, *du = self.hang_doi.get_nowait()
                try:
                    getattr(self, "_khi_" + loai)(*du)
                except Exception:       # noqa: BLE001 — một sự kiện hỏng không được làm chết vòng bơm
                    self._ghi("✗ Lỗi giao diện:\n" + traceback.format_exc())
        except queue.Empty:
            pass
        self.after(80, self._bom)

    def _ghi(self, dong: str):
        t = self.nhat_ky
        t.configure(state="normal")
        t.insert("end", dong + "\n")
        if int(t.index("end-1c").split(".")[0]) > 3000:
            t.delete("1.0", "500.0")
        t.see("end")
        t.configure(state="disabled")

    def _dat_tt(self, chu: str):
        self.nhan_tt.configure(text=chu)

    def _khi_log(self, dong: str):
        self._ghi(dong)
        m = re.search(r"\.\.\. (\d+(?:/\d+)? MB)", dong)        # tiến độ tải file lớn
        if m and self.dong_chay is not None:
            self.tam[self.dong_chay] = f"⏳ tải video {m.group(1)}…"
            self._ve_dong(self.dong_chay)

    # ------------------------------------------------------------ Sheet
    def tai_sheet(self):
        link = self.o_link.get().strip()
        if not link or self.dang_tai or self.dang_chay:
            return
        self.dang_tai = True
        self._cap_nhat_nut()
        self._dat_tt("Đang đọc Sheet…")

        def viec():
            try:
                ten_bo, ds = cd.doc_sheet(link)
                thu_muc = cd.thu_muc_bo(ten_bo)
                so_tay = cd._doc_json(thu_muc / "so_tay.json")
                cd.nho_sheet(link)
                self.hang_doi.put(("sheet", link, ten_bo, ds, thu_muc, so_tay))
            except Exception as e:      # noqa: BLE001
                self.hang_doi.put(("sheet_loi", f"{type(e).__name__}: {e}"))

        threading.Thread(target=viec, daemon=True).start()

    def _khi_sheet_loi(self, loi: str):
        self.dang_tai = False
        self._cap_nhat_nut()
        self._dat_tt("Không đọc được Sheet.")
        self._ghi("✗ " + loi)
        messagebox.showerror("Không đọc được Sheet", loi, parent=self)

    def _khi_sheet(self, link, ten_bo, ds, thu_muc, so_tay):
        self._xem_dung()
        self.dang_tai = False
        self.sheet, self.ten_bo, self.ds, self.thu_muc, self.so_tay = link, ten_bo, ds, thu_muc, so_tay
        self._so_tay_goc = json.loads(json.dumps(so_tay))        # bản lúc đọc, để _luu_so_tay biết mục nào phiên này đã sửa
        self.theo_dong = {d.dong: d for d in ds}
        self.kq, self.tam, self.len_loi = {}, {}, {}
        self.bang.delete(*self.bang.get_children())
        for d in ds:
            cu = so_tay.get(cd.id_drive(d.link) or "") or {}
            if cu.get("v2") and (thu_muc / cu["v2"]).is_file():      # đã làm ở lần mở trước
                self.kq[d.dong] = {"dong": d.dong, "trang_thai": "đã có", "v2": cu["v2"], "goc": cu.get("goc", ""),
                                   "moc_cat": cu.get("moc_cat"), "canh_bao": cu.get("ghi_chu", ""),
                                   "link_v2": cu.get("link_v2", ""), "tay": bool(cu.get("tay")),
                                   "doan_bo": cu.get("doan_bo"), "cau_dau_v2": cu.get("cau_dau", "")}
            self.bang.insert("", "end", iid=str(d.dong))
        self.tick = {d.dong for d in ds if d.dong not in self.kq}
        for d in ds:
            self._ve_dong(d.dong)
        if ds:
            self.bang.selection_set(str(ds[0].dong))
            self.bang.focus(str(ds[0].dong))
        self._ve_thong_tin()
        self._ve_chi_tiet()
        self._cap_nhat_nut()
        self._dat_tt("Bấm vào dòng đã có v2 để xem lại ở khung bên phải."
                     if ds else "Tab này không có dòng nào có link Drive ở cột Link Đăng.")
        self._ghi(f"{ten_bo}: {len(ds)} dòng có link ở cột Link Đăng. Kết quả ghi vào: {thu_muc}")

    # ------------------------------------------------------------ bảng
    def _nhan(self, kq: dict) -> tuple[str, str, str]:
        """-> (chữ cột Trạng thái, thẻ màu, ghi chú)."""
        tt, ghi = kq["trang_thai"], kq.get("ghi_chu") or ""
        tay = " (cắt tay)" if kq.get("tay") else ""
        if tt == "xong":
            return (f"⚠ xong{tay}, nên nghe lại", "canh_bao", ghi) if ghi else (f"✓ xong{tay}", "ok", "")
        if tt == "đã có":
            cb = kq.get("canh_bao") or ""
            return (f"⚠ đã có v2{tay}, nên nghe lại", "canh_bao", cb) if cb else (f"✓ đã có v2{tay}", "ok", "")
        if tt == "không có đoạn lặp":
            return "– không có đoạn lặp", "xam", ghi
        if tt == "cần xem lại":
            return "⚠ cần xem lại, chưa cắt", "canh_bao", ghi
        return "✗ lỗi", "loi", ghi

    def _ve_dong(self, dong: int):
        d, kq, tam = self.theo_dong[dong], self.kq.get(dong), self.tam.get(dong)
        chu, the, cat, ghi = "chưa làm", "", "", ""
        if kq:
            chu, the, ghi = self._nhan(kq)
            if kq.get("moc_cat") is not None:
                cat = f"{kq['moc_cat']:.2f}s"
        if tam:
            chu, the = tam, ("chay" if tam.startswith("⏳") else the)
        # cột Drive: link của ĐÚNG bản v2 đang có (sổ tay) · lỗi lần tải gần nhất · hoặc Sheet đã có link ở cột H từ trước
        len_ = "✓ đã lên" if (kq or {}).get("link_v2") else "✗ lỗi" if dong in self.len_loi else "H có link" if d.link_v2 else ""
        if dong in self.len_loi:
            ghi = (ghi + " · " if ghi else "") + "tải lên: " + self.len_loi[dong]
        self.bang.item(str(dong), tags=(the,) if the else (),
                       values=("☑" if dong in self.tick else "☐", dong, d.stt, d.tieu_de, chu, cat, len_, ghi))

    def _dong_chon(self) -> int | None:
        s = self.bang.selection()
        return int(s[0]) if s else None

    def _doi_tick(self, dong: int | None):
        if dong is None or self.dang_chay:
            return
        self.tick.symmetric_difference_update({dong})
        self._ve_dong(dong)
        self._cap_nhat_nut()

    def _tick_loat(self, kieu: str):
        if self.dang_chay:
            return
        if kieu == "het":
            self.tick = set(self.theo_dong)
        elif kieu == "bo":
            self.tick = set()
        elif kieu == "chua_len":        # đã có v2 nhưng bản đó chưa nằm trên Drive
            self.tick = {n for n, k in self.kq.items() if k.get("v2") and not k.get("link_v2")}
        else:
            self.tick = {n for n in self.theo_dong if (self.kq.get(n) or {}).get("trang_thai") not in XONG_HAN}
        for n in self.theo_dong:
            self._ve_dong(n)
        self._cap_nhat_nut()

    def _tick_dau_cot(self):
        self._tick_loat("bo" if self.ds and len(self.tick) == len(self.ds) else "het")

    def _bam_bang(self, e):
        if self.bang.identify_region(e.x, e.y) == "cell" and self.bang.identify_column(e.x) == "#1":
            iid = self.bang.identify_row(e.y)
            if iid:
                self._doi_tick(int(iid))

    def _tha_bang(self, e):
        """Nhả chuột trên một dòng (không phải ô tick): phát bản v2 của dòng đó ở khung xem lại."""
        if self._bo_tha:                # lần nhả thứ hai của cú bấm đúp: đã mở trình phát ngoài, không phát thêm
            self._bo_tha = False
            return
        if self.bang.identify_region(e.x, e.y) == "cell" and self.bang.identify_column(e.x) != "#1":
            self._hen_phat()

    def _bam_dup(self, e):
        if self.bang.identify_region(e.x, e.y) == "cell" and self.bang.identify_column(e.x) != "#1":
            if (self.kq.get(self._dong_chon()) or {}).get("v2"):
                self._bo_tha = True
                self.mo_ngoai("v2")

    def _ve_thong_tin(self):
        if not self.thu_muc:
            return
        co = sum(1 for k in self.kq.values() if k.get("v2"))
        try:        # đường dẫn đầy đủ quá dài, đẩy mất các nút tick -> ghi gọn từ Downloads
            noi = "Downloads\\" + str(self.thu_muc.relative_to(cd.downloads_dir()))
        except ValueError:
            noi = str(self.thu_muc)
        self.nhan_bo.configure(text=f"{len(self.ds)} dòng có link  ·  {co} dòng đã có v2  ·  kết quả ở {noi}")
        self.title(f"Cắt đoạn đọc tiêu đề lặp ở đầu video  ·  {self.ten_bo}")

    def _ve_chi_tiet(self):
        t, dong = self.chi_tiet, self._dong_chon()
        t.configure(state="normal")
        t.delete("1.0", "end")
        if dong is not None and dong in self.theo_dong:
            d, kq = self.theo_dong[dong], self.kq.get(dong) or {}
            dau = f"Dòng {dong} · STT {d.stt}"
            if kq.get("moc_cat") is not None and kq.get("v2"):
                dau += f" · đã cắt bỏ {kq['moc_cat']:.2f} giây đầu" + (" (cắt tay)" if kq.get("tay") else "")
                dau += " · bản v2 đã lên Drive, link ở cột H" if kq.get("link_v2") else " · bản v2 chưa lên Drive"
            elif not kq:
                dau += " · chưa làm"
            t.insert("end", dau + "\n", "dau")
            if kq.get("doan_bo") is not None:
                t.insert("end", "Đoạn bị bỏ:  ", "nhan")
                t.insert("end", (kq["doan_bo"] or "(máy không nghe ra chữ)") + "\n")
            cau = kq.get("cau_dau_v2") or kq.get("cau_dau")
            if cau:
                t.insert("end", "Câu đầu mới:  ", "nhan")
                t.insert("end", cau + "…\n")
            elif kq.get("nghe_duoc"):
                t.insert("end", "Máy nghe được:  ", "nhan")
                t.insert("end", kq["nghe_duoc"] + "…\n")
            elif kq.get("v2"):
                t.insert("end", "(Dòng làm từ bản cũ chưa lưu chi tiết. Bấm \"Làm thử\" để làm lại và xem.)\n", "nhan")
            t.insert("end", "Kịch bản cột C:  ", "nhan")
            t.insert("end", " ".join(d.kich_ban.split())[:260] + "…")
        t.configure(state="disabled")

    # ------------------------------------------------------------ nút
    def _cap_nhat_nut(self):
        ban = self.dang_chay or self.dang_tai
        co_ds = bool(self.ds) and self.thu_muc is not None
        dong = self._dong_chon()
        kq = self.kq.get(dong) or {}
        ranh = dong is not None and dong != self.dong_chay       # dòng đang render thì không mở file của nó
        bat = lambda w, dk: w.configure(state="normal" if dk else "disabled")      # noqa: E731
        bat(self.nut_tai, not ban)
        bat(self.o_link, not ban)
        for b in self.nut_tick:
            bat(b, co_ds and not ban)
        bat(self.o_lam_lai, not ban)
        bat(self.o_tu_len, not ban)
        bat(self.nut_thu, co_ds and not ban and dong is not None)
        bat(self.nut_chay, co_ds and not ban and bool(self.tick))
        n_len = sum(1 for n in self.tick if (self.kq.get(n) or {}).get("v2"))       # tick mà chưa có v2 thì không có gì để tải
        bat(self.nut_len, co_ds and not ban and n_len > 0)
        self.nut_len.configure(text=f"↑ Tải {n_len} dòng tick lên Drive" if n_len else "↑ Tải dòng tick lên Drive")
        bat(self.nut_dung, self.dang_chay and not self.dung.is_set())
        co_goc = self._ten_goc(dong) is not None                # bản gốc đã nằm trên đĩa (kể cả dòng chưa có v2)
        bat(self.nut_v2, bool(kq.get("v2")) and ranh)
        bat(self.nut_goc, co_ds and dong is not None and not self._dang_tai_goc)      # chưa tải thì bấm sẽ tải về rồi mở
        bat(self.nut_thu_muc, self.thu_muc is not None)
        co_xem = ranh and (bool(kq.get("v2")) or co_goc)
        bat(self.nut_xem_dau, co_xem)
        bat(self.nut_xem_het, co_xem)
        bat(self.nut_xem_goc, ranh and co_goc and kq.get("moc_cat") is not None)
        bat(self.nut_xem_dung, self.xem is not None or self.xem_cho is not None)
        bat(self.nut_cat_tay, co_ds and not ban and dong is not None)
        self.nut_thu.configure(text=f"▶ Làm thử dòng {dong}" if dong is not None else "▶ Làm thử 1 dòng")
        self.nut_chay.configure(text=f"▶▶ Cắt {len(self.tick)} dòng đã tick" if self.tick else "▶▶ Cắt các dòng đã tick")
        self.bang.heading("chon", text="☑" if self.ds and len(self.tick) == len(self.ds) else "☐")
        if self.xem is None and self.xem_cho is None:           # khung xem lại đang rảnh: ghi dòng đang chọn có gì để xem
            self.nhan_xem.configure(foreground=CHU, text=(
                "Xem lại" if dong is None else f"Dòng {dong} · có bản v2" if kq.get("v2")
                else f"Dòng {dong} · chỉ có bản gốc" if co_goc else f"Dòng {dong} · chưa tải video"))

    def _mo(self, p):
        try:
            os.startfile(str(p))
        except OSError as e:
            messagebox.showerror("Không mở được", f"{p}\n\n{e}", parent=self)

    def _mo_thu_muc(self):
        if self.thu_muc is not None:
            self.thu_muc.mkdir(parents=True, exist_ok=True)
            self._mo(self.thu_muc)

    # ------------------------------------------------------------ khung xem lại
    def _ten_goc(self, dong: int | None) -> str | None:
        """Tên file bản gốc đã tải của dòng (có thật trên đĩa), kể cả dòng chưa cắt / không cắt được; chưa tải -> None."""
        d = self.theo_dong.get(dong)
        if d is None or self.thu_muc is None:
            return None
        ten = (self.kq.get(dong) or {}).get("goc") or (self.so_tay.get(cd.id_drive(d.link) or "") or {}).get("goc")
        return ten if ten and (self.thu_muc / "goc" / ten).is_file() else None

    def _huy_hen(self):
        if self._hen is not None:
            self.after_cancel(self._hen)
            self._hen = None

    def _hen_phat(self):
        """Người dùng vừa đổi dòng (chuột / phím mũi tên): đợi 0,22 giây cho yên rồi mới phát, để lướt nhanh không giật."""
        self._huy_hen()
        if self.tu_phat.get():
            self._hen = self.after(220, self._tu_phat_dong)

    def _tu_phat_dong(self):
        """Bấm vào dòng: phát 12 giây đầu bản v2; dòng CHƯA có v2 mà đã tải bản gốc thì phát bản gốc (user 11/11: video không
        có bản trùng lặp cũng phải mở lên được để chọn chỗ cắt)."""
        self._hen = None
        dong = self._dong_chon()
        if dong != self.dong_chay and ((self.kq.get(dong) or {}).get("v2") or self._ten_goc(dong)):
            self._phat("dau")
        else:
            self._xem_dung()        # sang dòng chưa tải video: tắt tiếng của dòng trước

    def _phat(self, kieu: str, dong: int | None = None):
        """kieu: 'dau' = 12 giây đầu · 'het' = cả video · 'goc' = bản gốc quanh mốc cắt."""
        dong = self._dong_chon() if dong is None else dong
        kq = self.kq.get(dong) or {}
        goc = self._ten_goc(dong)
        if dong is None or self.thu_muc is None or dong == self.dong_chay:
            return
        if kieu == "goc":
            if not goc or kq.get("moc_cat") is None:
                return
            p, ten = self.thu_muc / "goc" / goc, "GỐC"
            s = max(kq["moc_cat"] - TRUOC_CAT, 0.0)
            dai, moc = kq["moc_cat"] - s + SAU_CAT, kq["moc_cat"] - s
        else:
            if kq.get("v2"):
                p, ten = self.thu_muc / kq["v2"], "v2"
            elif goc:                       # dòng chưa có v2 (không cắt được / chưa cắt): xem bản gốc để tự chọn chỗ cắt
                p, ten = self.thu_muc / "goc" / goc, "GỐC"
            else:
                return
            s, dai, moc = 0.0, (XEM_GIAY if kieu == "dau" else None), None
        self._huy_hen()
        self._xem_dung()
        if not p.is_file():
            self.nhan_xem.configure(text=f"Dòng {dong} · không thấy file", foreground="#b91c1c")
            return
        self.xem_phien += 1
        self.xem_cho = {"phien": self.xem_phien, "dong": dong}
        self.nhan_xem.configure(text=f"Dòng {dong} · {ten} · đang mở…", foreground=CHU)
        self._cap_nhat_nut()
        threading.Thread(target=self._viec_xem, daemon=True,
                         args=(self.xem_phien, dong, kieu, ten, p, s, dai, moc, self.xem_w, self.xem_h)).start()

    def _viec_xem(self, phien, dong, kieu, ten, p, s, dai, moc, w, h):
        """Luồng phụ: tách tiếng ra WAV tạm, mở ffmpeg xuất khung hình thu nhỏ, có khung đầu tiên thì báo luồng chính."""
        proc = wav = dung = None
        try:
            tt = cd.thong_tin(p)
            if tt is None:
                raise RuntimeError("ffprobe không đọc được video")
            dai = max(min(tt["giay"] if dai is None else dai, tt["giay"] - s), 0.5)
            ffmpeg = cd._exe("ffmpeg")
            vao = ["-ss", f"{s:.3f}", "-t", f"{dai:.3f}", "-i", str(p)]
            if tt["acodec"]:
                THU_MUC_TAM.mkdir(parents=True, exist_ok=True)
                wav = THU_MUC_TAM / f"xem_{os.getpid()}_{phien}.wav"
                r = subprocess.run([ffmpeg, "-v", "error", "-y", *vao, "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
                                    str(wav)], capture_output=True, timeout=180, creationflags=cd._FLAGS)
                if r.returncode != 0 or not wav.is_file():
                    wav.unlink(missing_ok=True)
                    wav = None
            if phien != self.xem_phien:
                raise _Huy()
            loc = (f"fps={XEM_FPS},scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0f172a")
            proc = subprocess.Popen([ffmpeg, "-v", "error", *vao, "-an", "-vf", loc, "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                    creationflags=cd._FLAGS)
            q, dung = queue.Queue(maxsize=8), threading.Event()
            threading.Thread(target=_doc_khung, args=(proc, q, dung, w * h * 3), daemon=True).start()
            t0 = time.time()
            while q.empty() and time.time() - t0 < 8:        # đợi khung hình đầu tiên để hình và tiếng cùng bắt đầu
                time.sleep(0.01)
            if phien != self.xem_phien:
                raise _Huy()
            self.hang_doi.put(("xem_san", {"phien": phien, "dong": dong, "kieu": kieu, "ten": ten, "s": s, "dai": dai,
                                           "moc": moc, "moc_cat": s + moc if moc is not None else None, "proc": proc, "q": q,
                                           "dung": dung, "wav": wav, "w": w, "h": h, "cho": None, "het": False,
                                           "so_khung": 0}))
        except Exception as e:      # noqa: BLE001
            _don_xem(proc, wav, dung)
            if not isinstance(e, _Huy):
                self.hang_doi.put(("xem_loi", phien, dong, f"{type(e).__name__}: {e}"))

    def _khi_xem_loi(self, phien: int, dong: int, loi: str):
        self._ghi(f"✗ Không xem lại được dòng {dong}: {loi}")
        if phien == self.xem_phien:
            self.xem_cho = None
            self._cap_nhat_nut()
            self.nhan_xem.configure(text=f"Dòng {dong} · không phát được", foreground="#b91c1c")

    def _khi_xem_san(self, x: dict):
        if x["phien"] != self.xem_phien:        # người dùng đã bấm dòng khác trong lúc chuẩn bị
            _don_xem(x["proc"], x["wav"], x["dung"])
            return
        self.xem_cho, self.xem = None, x
        if x["wav"] is not None:
            try:
                winsound.PlaySound(str(x["wav"]), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except RuntimeError as e:
                self._ghi(f"⚠ Không phát được tiếng: {e}")
        x["t0"] = time.perf_counter()
        self.man_hinh.itemconfigure(self.chu_id, state="hidden")
        self.thanh_xem.itemconfigure(self.moc_xem_id, state="normal" if x["moc"] is not None else "hidden")
        self._cap_nhat_nut()
        self._xem_nhip(x["phien"])

    def _xem_nhip(self, phien: int):
        """Mỗi 15 ms: hiện khung hình ứng với thời gian đã trôi từ lúc tiếng bắt đầu (trễ thì bỏ bớt khung)."""
        x = self.xem
        if x is None or x["phien"] != phien:
            return
        t = time.perf_counter() - x["t0"]
        can = int(max(t - TRE_TIENG, 0.0) * XEM_FPS)
        hien = None
        while True:
            if x["cho"] is None and not x["het"]:
                try:
                    m = x["q"].get_nowait()
                except queue.Empty:
                    break
                if m is None:
                    x["het"] = True
                    break
                x["cho"] = m
            if x["cho"] is None or x["cho"][0] > can:
                break
            hien, x["cho"] = x["cho"], None
        if hien is not None:
            self.anh.paste(Image.frombuffer("RGB", (x["w"], x["h"]), hien[1], "raw", "RGB", 0, 1))
            x["so_khung"] += 1
        tl = min(t, x["dai"])
        rong = max(self.thanh_xem.winfo_width(), 1)
        self.thanh_xem.coords(self.thanh_xem_id, 0, 0, int(rong * tl / x["dai"]), 6)
        if x["moc"] is not None:            # bản gốc quanh chỗ cắt: vạch đỏ = mốc cắt, nhãn đổi khi qua vạch
            vach = int(rong * x["moc"] / x["dai"])
            self.thanh_xem.coords(self.moc_xem_id, vach - 1, 0, vach + 1, 6)
            truoc = tl < x["moc"]
            self.nhan_xem.configure(text=f"Dòng {x['dong']} · GỐC · " + ("đoạn bị bỏ" if truoc else "phần giữ lại"),
                                    foreground="#b45309" if truoc else "#15803d")
            self.nhan_gio.configure(text=f"gốc {x['s'] + tl:.1f}s  ·  ✂ cắt ở {x['moc_cat']:.2f}s")
        else:
            self.nhan_xem.configure(foreground=CHU, text=f"Dòng {x['dong']} · {x['ten']} · "
                                    + ("12 giây đầu" if x["kieu"] == "dau" else "cả video"))
            # lẻ một số để đọc được giây cần gõ vào ô "Cắt tay" khi xem bản gốc
            self.nhan_gio.configure(text=f"{int(tl // 60)}:{tl % 60:04.1f} / {_phut(x['dai'])}")
        if (x["het"] and x["cho"] is None and t >= x["dai"] + 0.25) or t > x["dai"] + 2.0:
            self._xem_dung(het=True)
            return
        self.after(15, self._xem_nhip, phien)

    def _xem_dung(self, het: bool = False):
        """Dừng phiên đang phát / đang chuẩn bị. het=True: phát tới cuối tự dừng (giữ khung hình cuối và thanh đầy)."""
        self.xem_phien += 1             # phiên đang chuẩn bị ở luồng phụ thấy số này đổi sẽ tự hủy
        x, self.xem, self.xem_cho = self.xem, None, None
        if x is not None:
            try:
                winsound.PlaySound(None, 0)
            except RuntimeError:
                pass
            _don_xem(x["proc"], x["wav"], x["dung"])
            if not het:
                self.thanh_xem.coords(self.thanh_xem_id, 0, 0, 0, 6)
                self.thanh_xem.itemconfigure(self.moc_xem_id, state="hidden")
                self.nhan_gio.configure(text=" ")
        self._cap_nhat_nut()

    # ------------------------------------------------------------ mở ra trình phát ngoài
    def mo_ngoai(self, loai: str):
        """Nút "Xem bản mới ↗" / "Xem bản gốc ↗" (user 11/11: mở ra ngoài tự kéo thanh thời gian, không cần làm trong app):
        mở file bằng trình phát mặc định của Windows. Bản gốc chưa tải về thì tải rồi mở."""
        dong = self._dong_chon()
        if dong is None or self.thu_muc is None:
            return
        self._huy_hen()
        self._xem_dung()            # không để hai nơi cùng phát tiếng
        if loai == "v2":
            v2 = (self.kq.get(dong) or {}).get("v2")
            if v2:
                self._mo(self.thu_muc / v2)
            return
        goc = self._ten_goc(dong)
        if goc:
            self._mo(self.thu_muc / "goc" / goc)
        elif self.dang_chay:
            self._dat_tt("Đang chạy loạt: đợi xong rồi mới tải riêng bản gốc của dòng này về được.")
        elif not self._dang_tai_goc:
            self._dang_tai_goc = True
            d = self.theo_dong[dong]
            self._dat_tt(f"Đang tải bản gốc của dòng {dong} về để mở…")
            self._cap_nhat_nut()

            def viec():
                try:
                    fid = cd.id_drive(d.link)
                    if not fid or "/folders/" in d.link:
                        raise RuntimeError("cột Link Đăng không phải link FILE Drive.")
                    cu = self.so_tay.get(fid) or {}
                    f = cd.tai_drive(fid, self.thu_muc / "goc", cu.get("goc"))
                    self.so_tay[fid] = {**cu, "goc": f.name, "dong": d.dong}
                    self._luu_so_tay()
                    self.hang_doi.put(("goc_xong", dong, ""))
                except Exception as e:      # noqa: BLE001
                    self.hang_doi.put(("goc_xong", dong, f"{type(e).__name__}: {e}"[:200]))

            threading.Thread(target=viec, daemon=True).start()

    def _khi_goc_xong(self, dong: int, loi: str):
        self._dang_tai_goc = False
        if loi:
            self._dat_tt(f"Không tải được bản gốc dòng {dong}.")
            self._ghi(f"✗ Không tải được bản gốc dòng {dong}: {loi}")
        else:
            self._dat_tt(f"Đã tải bản gốc dòng {dong}.")
            goc = self._ten_goc(dong)
            if goc:
                self._mo(self.thu_muc / "goc" / goc)
        self._cap_nhat_nut()

    # ------------------------------------------------------------ chạy
    def lam_thu(self):
        dong = self._dong_chon()
        if dong is not None:
            self._chay([self.theo_dong[dong]], lam_lai=True, thu=True)      # làm thử thì luôn làm lại để nghe

    def cat_tay(self):
        """Cắt dòng đang chọn ở giây gõ trong ô (máy dò sai hoặc không dò ra). Xong tự phát bản v2 để nghe."""
        dong = self._dong_chon()
        if dong is None or self.dang_chay or self.dang_tai:
            return
        giay = _doc_giay(self.o_giay.get())
        if giay is None or giay <= 0:
            messagebox.showinfo("Cắt tay", "Gõ vào ô giây (của BẢN GỐC) mà lần đọc ĐÚNG bắt đầu, ví dụ 6 hoặc 5.3 (hay 0:06).\n\n"
                                "Chưa biết giây nào: bấm “Xem bản gốc ↗” để mở video ra trình phát rồi kéo tìm.\n"
                                "Gõ áng chừng là được: gần đó có chỗ nghỉ thì mốc cắt tự bám vào chỗ nghỉ ấy.", parent=self)
            self.o_giay.focus_set()
            return
        kq = self.kq.get(dong) or {}
        if kq.get("v2") and not messagebox.askyesno(
                "Cắt lại", f"Cắt lại dòng {dong} ở giây {giay:.2f} của bản gốc?\n\nBản v2 đang có sẽ được làm lại"
                + (", và bản trên Drive thành bản cũ: cắt xong cần tải lên lại." if kq.get("link_v2") else "."), parent=self):
            return
        self._chay([self.theo_dong[dong]], lam_lai=True, thu=True, tay=giay)

    def chay_tick(self):
        chon = [d for d in self.ds if d.dong in self.tick]
        if chon:
            self._chay(chon, lam_lai=self.lam_lai.get(), thu=False)

    def bam_dung(self):
        if self.dang_chay:
            self.dung.set()
            self._cap_nhat_nut()
            self._dat_tt(self.nhan_tt.cget("text") + "  ·  sẽ dừng sau khi xong dòng này")

    def _chay(self, chon: list, lam_lai: bool, thu: bool, tay: float | None = None):
        if self.dang_chay or self.dang_tai or self.thu_muc is None:
            return
        self.dang_chay = True
        self.dung.clear()
        self.tam = {d.dong: "… chờ" for d in chon}
        for d in chon:
            self._ve_dong(d.dong)
        self.thanh.configure(maximum=len(chon), value=0)
        self._cap_nhat_nut()
        tu_len = self.tu_len.get() and not thu          # làm thử thì không tự tải lên: còn phải nghe đã
        threading.Thread(target=self._viec_chay, args=(chon, lam_lai, thu, tu_len, tay), daemon=True).start()

    def _luu_so_tay(self):
        """Ghi sổ tay. Mục nào phiên này không đụng tới thì lấy bản đang nằm trên đĩa: cửa sổ khác / bản dòng lệnh có thể
        vừa ghi mục đó, ghi cả cuốn từ bộ nhớ sẽ xóa mất việc của họ."""
        p = self.thu_muc / "so_tay.json"
        for k, v in cd._doc_json(p).items():
            if self.so_tay.get(k) == self._so_tay_goc.get(k):
                self.so_tay[k] = v
        p.write_text(json.dumps(self.so_tay, ensure_ascii=False, indent=1), encoding="utf-8")
        self._so_tay_goc = json.loads(json.dumps(self.so_tay))

    def _viec_chay(self, chon: list, lam_lai: bool, thu: bool, tu_len: bool, tay: float | None = None):
        """Luồng phụ: không đụng widget, chỉ đẩy sự kiện."""
        args = SimpleNamespace(giay=cd.GIAY_NGHE, cpu=False, chi_xem=False, lam_lai=lam_lai)
        ds_kq, bc, t0, tab = [], None, time.time(), None
        try:
            self.thu_muc.mkdir(parents=True, exist_ok=True)
            for i, d in enumerate(chon, 1):
                if self.dung.is_set():
                    break
                self.hang_doi.put(("bat_dau", d.dong, i, len(chon)))
                # đợi luồng chính nhận "bat_dau": nó tắt khung xem lại nếu đang mở file của dòng này (file mở thì
                # render không ghi đè được bản v2)
                t_doi = time.time()
                while self.dong_chay != d.dong and time.time() - t_doi < 2:
                    time.sleep(0.02)
                cd.log(f"\n[{i}/{len(chon)}] Dòng {d.dong} (STT {d.stt}): {d.tieu_de[:80]}")
                kq = (cd.cat_tay(d, self.thu_muc, self.so_tay, tay, args) if tay is not None
                      else cd.xu_ly(d, self.thu_muc, self.so_tay, args))
                ds_kq.append(kq)
                if tu_len:              # dòng có cảnh báo thì để lại cho người nghe rồi tự bấm tải
                    import len_drive
                    if len_drive.nen_tu_tai(kq):
                        try:
                            tab = tab or len_drive.TabSheet(self.sheet, cd.log)
                            cd.buoc("tải lên Drive")
                            kq["link_v2"] = len_drive.tai_len(d, self.thu_muc, self.so_tay, tab, cd.log,
                                                              lambda p: cd.buoc(f"tải lên Drive {p}%"))
                        except len_drive.ChuaDangNhap:
                            tu_len = False
                            cd.log("  ⚠ Chưa đăng nhập Google nên không tự tải lên. Cắt xong hãy bấm nút Tải lên Drive để đăng nhập.")
                        except Exception as e:      # noqa: BLE001
                            kq["loi_len"] = f"{type(e).__name__}: {e}"[:300]
                            cd.log(f"  ✗ Không tải lên Drive được: {kq['loi_len']}")
                self._luu_so_tay()
                self.hang_doi.put(("xong_dong", kq, i))
            if any(k["trang_thai"] != "đã có" for k in ds_kq):
                bc = cd.ghi_bao_cao(self.thu_muc, self.sheet, self.ten_bo, ds_kq)
        except Exception as e:      # noqa: BLE001
            cd.log(f"✗ {type(e).__name__}: {e}")
        self.hang_doi.put(("het", ds_kq, bc, time.time() - t0, thu, len(chon)))

    def _khi_bat_dau(self, dong: int, i: int, n: int):
        dang_xem = (self.xem or self.xem_cho or {}).get("dong")
        if dang_xem == dong:            # đang xem lại chính dòng sắp render: nhả file ra
            self._xem_dung()
        self.dong_chay, self.thu_tu = dong, (i, n)
        self.tam[dong] = "⏳ bắt đầu…"
        self._ve_dong(dong)
        self.bang.see(str(dong))
        self._dat_tt(f"Đang chạy {i}/{n}  ·  dòng {dong}")
        self._cap_nhat_nut()

    def _khi_buoc(self, ten: str):
        if self.dong_chay is None:
            return
        self.tam[self.dong_chay] = f"⏳ {ten}…"
        self._ve_dong(self.dong_chay)
        i, n = self.thu_tu
        self._dat_tt(f"Đang chạy {i}/{n}  ·  dòng {self.dong_chay}  ·  {ten}"
                     + ("  ·  sẽ dừng sau khi xong dòng này" if self.dung.is_set() else ""))

    def _khi_xong_dong(self, kq: dict, i: int):
        dong = kq["dong"]
        self.tam.pop(dong, None)
        self.kq[dong] = kq
        self.dong_chay = None
        if kq.get("loi_len"):
            self.len_loi[dong] = kq["loi_len"]
        else:
            self.len_loi.pop(dong, None)
        if kq["trang_thai"] in XONG_HAN:
            self.tick.discard(dong)
        else:
            self.tick.add(dong)             # lỗi / cần xem lại: giữ tick để chạy lại
        self._ve_dong(dong)
        self.thanh.configure(value=i)
        if kq["trang_thai"] not in ("xong", "đã có"):
            self._ghi(f"  → {kq['trang_thai']}" + (f": {kq['ghi_chu']}" if kq.get("ghi_chu") else ""))
        elif kq["trang_thai"] == "xong" and kq.get("ghi_chu"):
            self._ghi(f"  ⚠ {kq['ghi_chu']}")
        if dong == self._dong_chon():
            self._ve_chi_tiet()
        self._ve_thong_tin()
        self._cap_nhat_nut()

    def _khi_het(self, ds_kq: list, bc, giay: float, thu: bool, tong: int):
        self.dang_chay, self.dong_chay = False, None
        bo_do = list(self.tam)              # bấm Dừng: các dòng còn "chờ" trở lại trạng thái cũ
        self.tam = {}
        for n in bo_do:
            self._ve_dong(n)
        dem = {}
        for k in ds_kq:
            dem[k["trang_thai"]] = dem.get(k["trang_thai"], 0) + 1
        tom = ", ".join(f"{v} {k}" for k, v in dem.items()) or "chưa chạy dòng nào"
        dau = f"Đã dừng ({len(ds_kq)}/{tong} dòng)" if len(ds_kq) < tong else f"Xong {tong} dòng"
        self._dat_tt(f"{dau} sau {_phut(giay)}  ·  {tom}")
        self._ghi(f"\n{dau} sau {_phut(giay)}: {tom}" + (f"\nBáo cáo: {bc.name}" if bc else ""))
        self._ve_thong_tin()
        self._cap_nhat_nut()
        if thu and ds_kq and ds_kq[0]["trang_thai"] == "xong":
            dong = ds_kq[0]["dong"]
            self.bang.selection_set(str(dong))
            self._ve_chi_tiet()
            self._phat("dau", dong)         # làm thử / cắt tay xong: phát luôn đầu bản v2 ở khung xem lại

    # ------------------------------------------------------------ tải lên Drive + ghi cột H
    def tai_len_tick(self):
        chon = [d for d in self.ds if d.dong in self.tick and (self.kq.get(d.dong) or {}).get("v2")]
        if chon:
            self._tai_len(chon)

    def _tai_len(self, chon: list, dang_nhap: bool = False):
        if self.dang_chay or self.dang_tai or self.thu_muc is None:
            return
        self.dang_chay = True
        self.dung.clear()
        self.tam = {d.dong: "… chờ tải lên" for d in chon}
        for d in chon:
            self._ve_dong(d.dong)
        self.thanh.configure(maximum=len(chon), value=0)
        self._cap_nhat_nut()
        self._dat_tt("Đang đăng nhập Google ở trình duyệt…" if dang_nhap else "Đang kết nối Google…")
        threading.Thread(target=self._viec_tai_len, args=(chon, dang_nhap), daemon=True).start()

    def _viec_tai_len(self, chon: list, dang_nhap: bool):
        """Luồng phụ: tải bản v2 của từng dòng lên thư mục ở cột Link video rồi ghi link vào cột H."""
        xong = loi = 0
        t0 = time.time()
        try:
            import len_drive
            if dang_nhap:
                cd.log("Đã đăng nhập Google: " + len_drive.dang_nhap(cd.log))
            try:
                tab = len_drive.TabSheet(self.sheet, cd.log)
            except len_drive.ChuaDangNhap:
                self.hang_doi.put(("len_can_dang_nhap", chon))
                return
            for i, d in enumerate(chon, 1):
                if self.dung.is_set():
                    break
                self.hang_doi.put(("bat_dau", d.dong, i, len(chon)))
                cd.log(f"\n[{i}/{len(chon)}] Tải lên Drive dòng {d.dong}: {d.tieu_de[:70]}")
                cd.buoc("tải lên Drive")
                try:
                    link = len_drive.tai_len(d, self.thu_muc, self.so_tay, tab, cd.log, lambda p: cd.buoc(f"tải lên Drive {p}%"))
                    self._luu_so_tay()
                    xong += 1
                    self.hang_doi.put(("len_xong", d.dong, link, "", i))
                except Exception as e:      # noqa: BLE001
                    loi += 1
                    self.hang_doi.put(("len_xong", d.dong, "", f"{type(e).__name__}: {e}"[:300], i))
        except Exception as e:      # noqa: BLE001
            cd.log(f"✗ Không tải lên được: {type(e).__name__}: {e}")
        self.hang_doi.put(("het_len", xong, loi, len(chon), time.time() - t0))

    def _khi_len_can_dang_nhap(self, chon: list):
        self.dang_chay, self.dong_chay, self.tam = False, None, {}
        for d in chon:
            self._ve_dong(d.dong)
        self._cap_nhat_nut()
        self._dat_tt("Chưa đăng nhập Google.")
        if messagebox.askyesno("Đăng nhập Google", "Máy này chưa có đăng nhập Google dùng được để tải lên Drive và ghi Sheet.\n\n"
                               "Mở trình duyệt để đăng nhập và cấp quyền Drive + Sheets?", parent=self):
            self._tai_len(chon, dang_nhap=True)

    def _khi_len_xong(self, dong: int, link: str, loi: str, i: int):
        self.tam.pop(dong, None)
        self.dong_chay = None
        if link:
            self.kq[dong]["link_v2"] = link
            self.len_loi.pop(dong, None)
            self.tick.discard(dong)
        else:
            self.len_loi[dong] = loi
            self._ghi(f"  ✗ Dòng {dong} không tải lên được: {loi}")
        self._ve_dong(dong)
        self.thanh.configure(value=i)
        if dong == self._dong_chon():
            self._ve_chi_tiet()
        self._cap_nhat_nut()

    def _khi_het_len(self, xong: int, loi: int, tong: int, giay: float):
        self.dang_chay, self.dong_chay = False, None
        bo_do = list(self.tam)
        self.tam = {}
        for n in bo_do:
            self._ve_dong(n)
        dau = f"Đã dừng ({xong + loi}/{tong} dòng)" if xong + loi < tong else f"Tải lên xong {tong} dòng"
        tom = f"{xong} đã lên Drive và ghi link vào cột {self._cot_moi()}" + (f", {loi} lỗi" if loi else "")
        self._dat_tt(f"{dau} sau {_phut(giay)}  ·  {tom}")
        self._ghi(f"\n{dau} sau {_phut(giay)}: {tom}")
        self._cap_nhat_nut()

    @staticmethod
    def _cot_moi() -> str:
        import len_drive
        return len_drive.COT_LINK_MOI

    def _dong_cua_so(self):
        if self.dang_chay and not messagebox.askyesno(
                "Đang chạy", "Đang xử lý video. Đóng bây giờ thì dòng đang chạy bị bỏ dở (các dòng đã xong vẫn giữ).\n\nĐóng luôn?",
                parent=self):
            return
        self._xem_dung()        # tắt ffmpeg + tiếng của khung xem lại
        os._exit(0)             # không để ctranslate2 hủy model GPU lúc thoát


if __name__ == "__main__":
    try:
        UngDung().mainloop()
    except Exception:           # noqa: BLE001 — pythonw không có console: phải báo lỗi bằng hộp thoại
        loi = traceback.format_exc()
        try:
            messagebox.showerror("Cắt đầu video — lỗi khởi động", loi[-1500:])
        except Exception:       # noqa: BLE001
            pass
        os._exit(1)
    os._exit(0)
