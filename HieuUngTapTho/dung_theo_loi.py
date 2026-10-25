"""Dựng hiệu ứng THEO LỜI NÓI cho video bài tập: đọc kịch bản (kich_ban/<tên>.json) gồm các bước và hiệu ứng có mốc giờ,
bám theo điểm mốc cơ thể (phan_tich.py) và phụ đề karaoke từ lời (chep_loi.py).

Quy trình cho một video mới:
    ..\venv_lamdep\Scripts\python.exe phan_tich.py <video> <pt.npz>
    ..\venv\Scripts\python.exe -X utf8 chep_loi.py <audio.wav> <loi.json>      (audio: ffmpeg -i video -vn -ac 1 -ar 16000 audio.wav)
    viết kich_ban/<tên>.json theo lời
    ..\venv_lamdep\Scripts\python.exe -X utf8 dung_theo_loi.py <video> <pt.npz> kich_ban/<tên>.json --loi <loi.json>
        [--mau 30,200,400 --ra <thư mục>]   → chỉ xuất khung mẫu PNG

Kết quả: 2 bản trong Downloads — <tên>_hieu_ung_<giờ>.mp4 và <tên>_hieu_ung_phu_de_<giờ>.mp4 (thêm phụ đề karaoke).

Loại hiệu ứng trong kịch bản (mọi điểm là tên điểm mốc, {"diem": tên, "lech": [dx, dy]} hoặc [x, y]):
    vong       : vòng sáng + sóng lan ở một điểm; nhan / nhan_phu / nhan_lech / nhan_xy; cham = chấm chạm (lệch từ tâm)
    mui_ten    : mũi tên cong tu_diem → toi_diem (hoặc vec); cong = độ phình (+/−); co_dinh = khoá vị trí lúc bắt đầu
    duoi       : đường sáng dọc chuỗi điểm (vd vai→khuỷu→cổ tay→ngón) + vạch chạy theo hướng duỗi
    tho        : bong bóng thở (HÍT VÀO / THỞ RA đếm giây), chu_ky giây; lung = cho đường lưng sáng theo nhịp
    goi        : gối mỏng trượt vào tại điểm; rong, cao, goc (độ)
    so_do_rong : thẻ sơ đồ nhìn từ trên xuống "gối rộng bằng hông"
    dong_ho    : đồng hồ giữ tư thế (tren / chinh / duoi, vd GIỮ / 3–5 / PHÚT), chu_ky vòng chạy
    chen_lai   : khung nhỏ phát lại đoạn nguon_tu→nguon_den, vong = vòng đánh dấu một điểm trong khung
    the_canh_bao: các dòng cảnh báo có biểu tượng (mat / tim / lua / dung), hiện lần lượt
    danh_sach  : thẻ danh sách, từng dòng được tích vào lúc 'tu' của dòng (co = phóng to, dùng cho video dọc)
    tho_bung   : thở bụng theo tín hiệu đo thật (do_bung.py → tin_hieu), pha = [[t0, t1, hit1|hit2|tho]],
                 bong bóng to/nhỏ theo bụng, vùng bụng phồng, thanh nhịp [HÍT][HÍT][THỞ RA DÀI]
    zzz        : chữ Z bay lên từ một điểm (ngủ quên)
    so_do_goc  : thẻ sơ đồ chân duỗi gối cong nhẹ + 2 tay đan dưới khoeo + góc (goc, chu, tieu_de)
    goc_vuong  : dấu góc vuông tại tam, một cạnh hướng về 'huong', nhãn chu (mặc định 90°)
    do_cao     : thước khoảng hở từ mặt giường (day) lên tới một điểm khi điểm được nhấc (vd "khỏi mặt giường")
    lac        : mũi tên hai đầu dao động quanh một điểm, đổi trục theo 'truc' mỗi 'doi' giây (vd đẩy bánh chè)
    nhan       : nhãn đứng riêng (chu, phu, mau, xy, co) bật lên — cho đoạn nói chuyện không có động tác
    tien_do    : thanh tiến độ chạy tới 'phan' (0..1), nhãn phía trên + phần trăm
    dem        : bộ đếm vòng N ô, moc = [t1, t2, ...] lúc nhảy số; xong = nhãn khi đếm hết
    bien_do    : biên độ khớp — cung tại 'tam', kim theo hướng goc→dau đo thật (vd tam=ankle, goc=heel, dau=foot;
                 goc có thể là điểm cố định [x, y], vd gối tựa trên gối kê), tang / giam = {nhan, mau, het_muc}
                 ('' = không bật 'hết mức' ở đầu đó), nguong_cuc = tỉ lệ biên độ coi như chạm cực (0.86);
                 cung=false: ẩn dải cung/kim, chỉ còn đường chi (chuoi = các điểm trước 'dau'), mũi tên theo đường đi
                 và nhãn hai đầu
Thẻ trên cùng chung: kb["the_tren"] = {x, y, co} (co = tỉ lệ thu nhỏ, dùng cho video ngang).
Thẻ trên cùng (buoc): kieu = buoc | canh_bao | meo | nguy_hiem | tieu_de; phu = chuỗi hoặc danh sách dòng.
Không có --loi thì chỉ xuất bản không phụ đề.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dung import (BLUE, DARK, ORANGE, WHITE, bgr, chon_encoder, downloads_dir, draw_glow_poly, font,  # noqa: E402
                  paste_rgba, smooth, smooth2, blend_roi)

YELLOW = (255, 214, 60)
RED = (255, 86, 86)
AMBER = (255, 186, 40)
GREEN = (80, 225, 150)
MAU = {"xanh": BLUE, "cam": ORANGE, "vang": YELLOW, "do": RED, "luc": GREEN, "trang": WHITE, "hoac_vang": AMBER}
FADE = 0.3


# ------------------------------------------------------------------ tiện ích
def ease(x):
    x = float(np.clip(x, 0, 1))
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = float(np.clip(x, 0, 1))
    return 1 - (1 - x) ** 3


def ease_out_back(x):
    x = float(np.clip(x, 0, 1))
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def env(t, tu, den, fade=FADE):
    return ease((t - tu) / fade) * ease((den - t) / fade)


def fit_font(text, max_w, size, weight="black", min_size=28):
    while size > min_size:
        f = font(size, weight)
        b = f.getbbox(text)
        if b[2] - b[0] <= max_w:
            return f
        size -= 2
    return font(min_size, weight)


def circle_pts(c, r, n=72):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([c[0] + r * np.cos(a), c[1] + r * np.sin(a)], 1)


def bezier(A, B, cong, n=64):
    d = B - A
    L = np.linalg.norm(d) + 1e-6
    perp = np.array([d[1], -d[0]]) / L
    C = (A + B) / 2 + perp * cong * L
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * A + 2 * (1 - t) * t * C + t ** 2 * B


def path_len(pts):
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    return np.concatenate([[0], np.cumsum(seg)])


def point_at(pts, cum, s):
    """Điểm + hướng tại độ dài s dọc đường."""
    s = float(np.clip(s, 0, cum[-1]))
    k = int(np.clip(np.searchsorted(cum, s) - 1, 0, len(pts) - 2))
    seg = cum[k + 1] - cum[k]
    u = (s - cum[k]) / seg if seg > 1e-6 else 0
    p = pts[k] + (pts[k + 1] - pts[k]) * u
    d = pts[k + 1] - pts[k]
    n = np.linalg.norm(d)
    return p, (d / n if n > 1e-6 else np.array([1.0, 0.0]))


def fill_poly_alpha(frame, pts, color, alpha, blur=1.5):
    if alpha <= 0.01:
        return
    x0, y0 = (pts.min(0) - 10).astype(int)
    x1, y1 = (pts.max(0) + 10).astype(int)
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(m, [((pts - [x0, y0]) * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_AA, shift=4)
    a = m.astype(np.float32) / 255
    if blur:
        a = cv2.GaussianBlur(a, (0, 0), blur)
    blend_roi(frame, x0, y0, a * alpha, color)


def paste_center(frame, rgba, c, alpha):
    paste_rgba(frame, rgba, int(round(c[0] - rgba.shape[1] / 2)), int(round(c[1] - rgba.shape[0] / 2)), alpha)


def leader(frame, c, r, lc, lsize, color, alpha):
    """Đường dẫn mảnh từ mép vòng tới mép nhãn."""
    d = lc - c
    n = np.linalg.norm(d)
    if n < r + 30:
        return
    d = d / n
    hw, hh = lsize[0] / 2 + 6, lsize[1] / 2 + 6
    t_hit = min(hw / abs(d[0]) if abs(d[0]) > 1e-3 else 1e9, hh / abs(d[1]) if abs(d[1]) > 1e-3 else 1e9)
    p0 = c + d * (r + 8)
    p1 = lc - d * t_hit
    if np.linalg.norm(p1 - p0) > 15:
        draw_glow_poly(frame, np.array([p0, p1]), color, alpha * 0.9, 3, glow=0.3)


# ------------------------------------------------------------------ tấm hình tĩnh (PIL)
def header_img(c, n_steps):
    """Thẻ trên cùng. kieu: buoc (số bước + chấm tiến độ) | canh_bao (vàng !) | meo (vàng i) | nguy_hiem (đỏ !) | tieu_de.
    phu: chuỗi hoặc danh sách dòng; mau / huy_hieu: ghi đè màu và chữ trong huy hiệu."""
    kieu = c.get("kieu", "canh_bao" if c.get("canh_bao") else "buoc")
    if kieu == "tieu_de":
        return title_img(c)
    accent = MAU.get(c.get("mau"), None) or {"buoc": BLUE, "canh_bao": AMBER, "meo": AMBER, "nguy_hiem": RED,
                                             "thuong": BLUE}[kieu]
    phu = c.get("phu", "")
    phu = [x for x in ([phu] if isinstance(phu, str) else list(phu)) if x]
    dots = kieu == "buoc" and n_steps > 0
    W = 960
    H = 186 + 64 * max(len(phu), 1) + (32 if dots else 0)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 52, fill=DARK + (218,), outline=accent + (255,), width=6)
    cx, cy, rr = 98, 112, 62
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=accent + (255,))
    badge = c.get("huy_hieu") or {"buoc": str(c.get("so", "")), "canh_bao": "!", "meo": "i", "nguy_hiem": "!",
                                  "thuong": "•"}[kieu]
    fb = fit_font(badge, 96, 80, "black")
    bb = fb.getbbox(badge)
    d.text((cx - (bb[0] + bb[2]) / 2, cy - (bb[1] + bb[3]) / 2), badge, font=fb, fill=DARK + (255,))
    x0 = 190
    fm = fit_font(c["chinh"], W - x0 - 36, 92)
    bm = fm.getbbox(c["chinh"])
    d.text((x0 - bm[0], 34 - bm[1]), c["chinh"], font=fm, fill=accent + (255,))
    for k, line in enumerate(phu):
        fs = fit_font(line, W - x0 - 36, 54, "bold")
        bs = fs.getbbox(line)
        d.text((x0 - bs[0], 150 + 64 * k - bs[1]), line, font=fs, fill=WHITE + (255,))
    if dots:
        k = int(c.get("so", 0))
        gap = 40
        sx = W / 2 - gap * (n_steps - 1) / 2
        y = H - 34
        for j in range(1, n_steps + 1):
            x = sx + gap * (j - 1)
            r = 11 if j == k else 8
            col = accent + (255,) if j == k else ((235, 235, 235, 230) if j < k else (110, 110, 110, 230))
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    return np.array(img)


def clock_icon(d, cx, cy, r, color, width=5):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
    d.line([(cx, cy), (cx, cy - r * 0.62)], fill=color, width=width)
    d.line([(cx, cy), (cx + r * 0.48, cy + r * 0.12)], fill=color, width=width)


def title_img(c):
    """Thẻ tiêu đề mở đầu: dòng nhỏ 'tren', dòng lớn 'chinh', viên thuốc 'phu' có đồng hồ."""
    accent = MAU.get(c.get("mau", "xanh"), BLUE)
    top = 0 if c.get("tren") else -82
    W, H = int(c.get("rong", 820)), 372 + top
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 52, fill=DARK + (225,), outline=accent + (255,), width=6)
    if c.get("tren"):
        f1 = font(56, "black")
        b1 = f1.getbbox(c["tren"])
        d.text(((W - (b1[2] - b1[0])) / 2 - b1[0], 30 - b1[1]), c["tren"], font=f1, fill=AMBER + (255,))
    f2 = fit_font(c["chinh"], W - 70, 104)
    b2 = f2.getbbox(c["chinh"])
    d.text(((W - (b2[2] - b2[0])) / 2 - b2[0], 112 + top - b2[1]), c["chinh"], font=f2, fill=WHITE + (255,))
    if c.get("phu"):
        f3 = font(48, "black")
        b3 = f3.getbbox(c["phu"])
        tw = b3[2] - b3[0]
        cw, ch = tw + 2 * 34 + 62, 82
        x0, y0 = (W - cw) / 2, 252 + top
        d.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], ch // 2, fill=accent + (255,))
        clock_icon(d, x0 + 34 + 22, y0 + ch / 2, 22, DARK + (255,), 5)
        d.text((x0 + 34 + 62 - b3[0], y0 + (ch - (b3[3] - b3[1])) / 2 - b3[1]), c["phu"], font=f3, fill=DARK + (255,))
    return np.array(img)


def timer_img(c):
    accent = MAU.get(c.get("mau", "hoac_vang"), AMBER)
    W = H = 200
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for txt, size, wgt, col, y, mw in ((c.get("tren", "GIỮ"), 30, "bold", WHITE, 46, 112),
                                       (c.get("chinh", "3–5"), 66, "black", accent, 100, 150),
                                       (c.get("duoi", "PHÚT"), 30, "bold", WHITE, 154, 112)):
        f = fit_font(txt, mw, size, wgt, min_size=18)
        b = f.getbbox(txt)
        d.text(((W - (b[2] - b[0])) / 2 - b[0], y - (b[1] + b[3]) / 2), txt, font=f, fill=col + (255,))
    return np.array(img)


def icon_glyph(d, kind, cx, cy, s):
    w = (255, 255, 255, 255)
    if kind == "mat":
        u = np.linspace(0, 1, 40)
        xs = cx - s + 2 * s * u
        top = [(x, cy - s * 0.62 * np.sin(np.pi * v)) for x, v in zip(xs, u)]
        bot = [(x, cy + s * 0.62 * np.sin(np.pi * v)) for x, v in zip(xs[::-1], u[::-1])]
        d.line(top + bot + [top[0]], fill=w, width=6, joint="curve")
        d.ellipse([cx - s * 0.4, cy - s * 0.4, cx + s * 0.4, cy + s * 0.4], fill=w)
        d.ellipse([cx - s * 0.17, cy - s * 0.17, cx + s * 0.17, cy + s * 0.17], fill=RED + (255,))
    elif kind == "tim":
        t = np.linspace(0, 2 * np.pi, 80)
        x = 16 * np.sin(t) ** 3
        y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        k = s / 17
        d.polygon([(cx + xi * k, cy + yi * k) for xi, yi in zip(x, y)], fill=w)
        zz = [(cx - s * 0.75, cy), (cx - s * 0.3, cy), (cx - s * 0.12, cy - s * 0.45), (cx + s * 0.1, cy + s * 0.4),
              (cx + s * 0.28, cy - s * 0.1), (cx + s * 0.75, cy - s * 0.1)]
        d.line(zz, fill=RED + (255,), width=6, joint="curve")
    elif kind == "lua":
        t = np.linspace(0, 2 * np.pi, 90)
        r = 1 - 0.55 * (np.sin(t / 2) ** 6)                  # giọt lửa nhọn phía trên
        x = cx + s * 0.62 * np.sin(t) * r
        y = cy + s * 0.25 - s * 0.95 * np.cos(t) * (0.55 + 0.45 * (np.cos(t) > 0))
        d.polygon(list(zip(x, y)), fill=w)
        d.ellipse([cx - s * 0.28, cy + s * 0.05, cx + s * 0.28, cy + s * 0.62], fill=RED + (255,))
    elif kind == "dung":
        d.ellipse([cx - s * 0.2, cy - s * 0.95, cx + s * 0.2, cy - s * 0.55], fill=w)
        d.line([(cx, cy - s * 0.5), (cx, cy + s * 0.25)], fill=w, width=8)
        d.line([(cx - s * 0.5, cy - s * 0.25), (cx + s * 0.5, cy - s * 0.25)], fill=w, width=7)
        d.line([(cx, cy + s * 0.2), (cx - s * 0.35, cy + s * 0.9)], fill=w, width=8)
        d.line([(cx, cy + s * 0.2), (cx + s * 0.35, cy + s * 0.9)], fill=w, width=8)
        d.line([(cx + s * 0.25, cy + s * 0.35), (cx + s * 0.75, cy + s * 0.85)], fill=RED + (255,), width=7)
        d.line([(cx + s * 0.75, cy + s * 0.35), (cx + s * 0.25, cy + s * 0.85)], fill=RED + (255,), width=7)


def checklist_imgs(c):
    """Thẻ danh sách: ảnh nền (các dòng mờ) + ảnh từng dòng đã tích."""
    color = MAU.get(c.get("mau", "luc"), GREEN)
    W = int(c.get("rong", 480))
    rows = c["dong"]
    rh, top, pad = 78, (70 if c.get("tieu_de") else 0), 22
    H = pad + top + rh * len(rows) + pad - 6
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 36, fill=DARK + (215,), outline=color + (255,), width=5)
    if c.get("tieu_de"):
        ft = fit_font(c["tieu_de"], W - 48, 44, "black")
        bt = ft.getbbox(c["tieu_de"])
        d.text((26 - bt[0], pad + 30 - (bt[1] + bt[3]) / 2), c["tieu_de"], font=ft, fill=color + (255,))
    fr_ = [fit_font(r["chu"], W - 120, 44, "bold") for r in rows]
    overs = []
    for k, r in enumerate(rows):
        cy = pad + top + rh * k + rh / 2
        b = fr_[k].getbbox(r["chu"])
        d.ellipse([26, cy - 22, 70, cy + 22], outline=(150, 150, 150, 255), width=4)
        d.text((92 - b[0], cy - (b[1] + b[3]) / 2), r["chu"], font=fr_[k], fill=(165, 165, 165, 255))
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        o = ImageDraw.Draw(ov)
        o.ellipse([24, cy - 24, 72, cy + 24], fill=color + (255,))
        o.line([(36, cy + 1), (46, cy + 11), (61, cy - 10)], fill=DARK + (255,), width=7, joint="curve")
        o.rounded_rectangle([84, cy - 30, W - 14, cy + 30], 18, fill=DARK + (255,))
        o.text((92 - b[0], cy - (b[1] + b[3]) / 2), r["chu"], font=fr_[k], fill=WHITE + (255,))
        overs.append(np.array(ov))
    return np.array(base), overs


def belly_text_img(state):
    txt, sub, color = {"hit1": ("HÍT 1", "bụng phồng", BLUE), "hit2": ("HÍT 2", "phồng thêm", BLUE),
                       "tho": ("THỞ RA", "thật dài…", ORANGE), "nghi": ("THẢ", "LỎNG", GREEN)}[state]
    W, H = 210, 150
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f1 = fit_font(txt, W - 16, 58, "black")
    b1 = f1.getbbox(txt)
    d.text(((W - (b1[2] - b1[0])) / 2 - b1[0], 56 - (b1[1] + b1[3]) / 2), txt, font=f1, fill=color + (255,))
    f2 = fit_font(sub, W - 30, 32, "bold")
    b2 = f2.getbbox(sub)
    d.text(((W - (b2[2] - b2[0])) / 2 - b2[0], 110 - (b2[1] + b2[3]) / 2), sub, font=f2, fill=WHITE + (255,))
    return np.array(img)


def pattern_bar_img(active, done, width=500):
    """Thanh nhịp [HÍT][HÍT][THỞ RA DÀI]; active = chỉ số ô đang làm, done = tập các ô đã xong."""
    segs = [("HÍT", 1, BLUE), ("HÍT", 1, BLUE), ("THỞ RA DÀI", 2, ORANGE)]
    H, gap = 64, 10
    unit = (width - gap * 2) / 4
    img = Image.new("RGBA", (width, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 0
    f = font(34, "black")
    for k, (txt, u, col) in enumerate(segs):
        w = unit * u
        if k == active:
            d.rounded_rectangle([x, 0, x + w, H - 1], 26, fill=col + (255,))
            tc = DARK
        elif k in done:
            d.rounded_rectangle([x, 0, x + w, H - 1], 26, fill=DARK + (225,), outline=col + (255,), width=4)
            tc = col
        else:
            d.rounded_rectangle([x, 0, x + w, H - 1], 26, fill=DARK + (200,), outline=(120, 120, 120, 255), width=3)
            tc = (170, 170, 170)
        b = f.getbbox(txt)
        d.text((x + (w - (b[2] - b[0])) / 2 - b[0], H / 2 - (b[1] + b[3]) / 2), txt, font=f, fill=tc + (255,))
        x += w + gap
    return np.array(img)


def z_img(size, color):
    f = font(size, "black")
    b = f.getbbox("Z")
    W, H = b[2] - b[0] + 20, b[3] - b[1] + 20
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((10 - b[0], 10 - b[1]), "Z", font=f, fill=color + (255,), stroke_width=4, stroke_fill=DARK + (255,))
    return np.array(img)


def count_img(num, color, top="ĐẾM"):
    W, H = 200, 190
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f1 = font(30, "bold")
    b1 = f1.getbbox(top)
    d.text(((W - (b1[2] - b1[0])) / 2 - b1[0], 34 - (b1[1] + b1[3]) / 2), top, font=f1, fill=WHITE + (255,))
    f2 = fit_font(str(num), 150, 104, "black")
    b2 = f2.getbbox(str(num))
    d.text(((W - (b2[2] - b2[0])) / 2 - b2[0], 112 - (b2[1] + b2[3]) / 2), str(num), font=f2, fill=color + (255,))
    return np.array(img)


def so_do_goc_img(c):
    """Sơ đồ nhìn ngang: chân duỗi gối cong nhẹ, 2 tay đan dưới khoeo, cung góc."""
    color = MAU.get(c.get("mau", "vang"), YELLOW)
    W, H = 330, 350
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 30, fill=DARK + (222,), outline=color + (255,), width=5)
    ft = fit_font(c.get("tieu_de", "KHÔNG CÓ GỐI KÊ"), W - 36, 30, "black")
    tt = c.get("tieu_de", "KHÔNG CÓ GỐI KÊ")
    bt = ft.getbbox(tt)
    d.text(((W - (bt[2] - bt[0])) / 2 - bt[0], 26 - bt[1]), tt, font=ft, fill=WHITE + (255,))
    oy = 40
    hip, knee, ank = (290, 175 + oy), (165, 140 + oy), (40, 150 + oy)
    d.line([(20, 205 + oy), (W - 20, 205 + oy)], fill=(140, 140, 140, 255), width=4)          # mặt giường
    ex = (knee[0] - 0.85 * (hip[0] - knee[0]), knee[1] - 0.85 * (hip[1] - knee[1]))      # đùi kéo dài (đường thẳng)
    for k in range(0, 10, 2):
        u0, u1 = k / 10, (k + 1) / 10
        d.line([(knee[0] + (ex[0] - knee[0]) * u0, knee[1] + (ex[1] - knee[1]) * u0),
                (knee[0] + (ex[0] - knee[0]) * u1, knee[1] + (ex[1] - knee[1]) * u1)], fill=(200, 200, 200, 255), width=3)
    d.line([hip, knee], fill=(235, 220, 200, 255), width=18)
    d.line([knee, ank], fill=(235, 220, 200, 255), width=16)
    d.line([ank, (ank[0] - 4, ank[1] - 38)], fill=(255, 255, 255, 255), width=12)          # bàn chân
    d.ellipse([knee[0] - 12, knee[1] - 12, knee[0] + 12, knee[1] + 12], fill=(235, 220, 200, 255))
    for dx in (-14, 8):                                                                      # 2 bàn tay đan dưới khoeo
        d.ellipse([knee[0] + dx - 14, knee[1] + 10, knee[0] + dx + 16, knee[1] + 40], fill=(240, 196, 160, 255),
                  outline=DARK + (255,), width=3)
    a1 = np.degrees(np.arctan2(ex[1] - knee[1], ex[0] - knee[0]))
    a2 = np.degrees(np.arctan2(ank[1] - knee[1], ank[0] - knee[0]))
    r = 95
    delta = (a2 - a1 + 540) % 360 - 180                     # cung NGẮN giữa đường đùi kéo dài và cẳng chân
    start = a1 if delta > 0 else a2
    d.arc([knee[0] - r, knee[1] - r, knee[0] + r, knee[1] + r], start, start + abs(delta), fill=color + (255,), width=8)
    fa = font(36, "black")
    lab = c.get("goc", "15–20°")
    ba = fa.getbbox(lab)
    d.text((knee[0] - 72 - (ba[2] - ba[0]) / 2 - ba[0], knee[1] - 78 - ba[1]), lab, font=fa, fill=color + (255,))
    fc = fit_font(c.get("chu", "ĐAN TAY GIỮ KHOEO"), W - 30, 34, "black")
    cc = c.get("chu", "ĐAN TAY GIỮ KHOEO")
    bc = fc.getbbox(cc)
    d.text(((W - (bc[2] - bc[0])) / 2 - bc[0], H - 54 - bc[1]), cc, font=fc, fill=color + (255,))
    return np.array(img)


def warn_row_img(row, width, color):
    lines = row["chu"] if isinstance(row["chu"], list) else [row["chu"]]
    H = max(140, 64 * len(lines) + 44)
    img = Image.new("RGBA", (width, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, H - 1], 36, fill=DARK + (222,), outline=color + (255,), width=5)
    cx, cy, r = 78, H / 2, 52
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (255,))
    icon_glyph(d, row.get("bieu_tuong", ""), cx, cy, 30)
    x0 = 154
    y = (H - 64 * len(lines)) / 2 + 6
    for k, line in enumerate(lines):
        f = fit_font(line, width - x0 - 24, 54 if k == 0 else 46, "black" if k == 0 else "bold")
        b = f.getbbox(line)
        d.text((x0 - b[0], y + 64 * k - b[1]), line, font=f, fill=(WHITE if k == 0 else (225, 225, 225)) + (255,))
    return np.array(img)


def label_img(text, sub, color):
    f1 = font(52, "black")
    b1 = f1.getbbox(text)
    w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
    f2 = font(38, "bold")
    if sub:
        b2 = f2.getbbox(sub)
        w2, h2 = b2[2] - b2[0], b2[3] - b2[1]
    else:
        b2, w2, h2 = None, 0, 0
    padx, pady, gap = 30, 16, 14 if sub else 0
    W = max(w1, w2) + 2 * padx
    H = h1 + h2 + gap + 2 * pady
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], min(H // 2, 40), fill=DARK + (212,), outline=color + (255,), width=4)
    d.text(((W - w1) / 2 - b1[0], pady - b1[1]), text, font=f1, fill=color + (255,))
    if sub:
        d.text(((W - w2) / 2 - b2[0], pady + h1 + gap - b2[1]), sub, font=f2, fill=WHITE + (255,))
    return np.array(img)


def so_do_rong_img(color):
    W, H = 330, 372
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 30, fill=DARK + (218,), outline=color + (255,), width=5)
    ft = fit_font("NHÌN TỪ TRÊN XUỐNG", W - 36, 28, "bold")
    bt = ft.getbbox("NHÌN TỪ TRÊN XUỐNG")
    d.text(((W - (bt[2] - bt[0])) / 2 - bt[0], 20 - bt[1]), "NHÌN TỪ TRÊN XUỐNG", font=ft, fill=(220, 220, 220, 255))
    hx, hy, ky = (135, 245), 128, 246
    d.rounded_rectangle([105, hy - 24, 275, hy + 24], 22, fill=(255, 255, 255, 50), outline=(255, 255, 255, 170), width=3)
    for x in hx:
        d.line([(x, hy), (x, ky)], fill=(255, 255, 255, 210), width=12)
    for x in hx:
        d.ellipse([x - 15, hy - 15, x + 15, hy + 15], fill=color + (255,))
        d.ellipse([x - 18, ky - 18, x + 18, ky + 18], fill=color + (255,))
    fl = font(26, "bold")
    for txt, y in (("Hông", hy), ("Gối", ky)):
        bl = fl.getbbox(txt)
        d.text((22 - bl[0], y - (bl[1] + bl[3]) / 2), txt, font=fl, fill=WHITE + (255,))

    def harrow(y):
        x0, x1 = hx[0], hx[1]
        d.line([(x0 + 4, y), (x1 - 4, y)], fill=color + (255,), width=5)
        d.polygon([(x0, y), (x0 + 16, y - 10), (x0 + 16, y + 10)], fill=color + (255,))
        d.polygon([(x1, y), (x1 - 16, y - 10), (x1 - 16, y + 10)], fill=color + (255,))
    harrow(hy - 46)
    harrow(ky + 42)
    fb = fit_font("GỐI RỘNG = HÔNG", W - 30, 38)
    bb = fb.getbbox("GỐI RỘNG = HÔNG")
    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], 322 - bb[1]), "GỐI RỘNG = HÔNG", font=fb, fill=color + (255,))
    return np.array(img)


def breath_text_img(state, num):
    color = BLUE if state == "in" else ORANGE
    txt = "HÍT VÀO" if state == "in" else "THỞ RA"
    W, H = 230, 160
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f1 = font(40, "black")
    b1 = f1.getbbox(txt)
    d.text(((W - (b1[2] - b1[0])) / 2 - b1[0], 14 - b1[1]), txt, font=f1, fill=color + (255,))
    f2 = font(80, "black")
    s = str(num)
    b2 = f2.getbbox(s)
    d.text(((W - (b2[2] - b2[0])) / 2 - b2[0], 68 - b2[1]), s, font=f2, fill=WHITE + (255,))
    return np.array(img)


# ------------------------------------------------------------------ phụ đề karaoke
def build_phrases(segs, sua):
    phrases = []
    for s in segs:
        words = []
        for w in s["words"]:
            txt = w["w"].strip()
            if txt in sua:
                txt = sua[txt]
            else:
                core = txt.rstrip(",.!?")
                if core in sua:
                    txt = sua[core] + txt[len(core):]
            if txt:
                words.append({"w": txt, "s": float(w["s"]), "e": float(w["e"])})
        parts, cur = [], []
        for w in words:
            cur.append(w)
            if w["w"].endswith((",", ".", "!", "?")):
                parts.append(cur)
                cur = []
        if cur:
            parts.append(cur)
        merged = []
        for p in parts:
            if merged and len(merged[-1]) < 5 and len(p) < 5 and len(merged[-1]) + len(p) <= 9:
                merged[-1] = merged[-1] + p
            else:
                merged.append(p)
        out = []
        stack = list(merged)
        while stack:
            p = stack.pop(0)
            if len(p) <= 12:
                out.append(p)
                continue
            k = next((j for j, w in enumerate(p) if w["w"].lower().startswith("hoặc") and 2 < j < len(p) - 2), len(p) // 2)
            stack[0:0] = [p[:k], p[k:]]
        phrases.extend(out)
    res = []
    for j, p in enumerate(phrases):
        start = p[0]["s"] - 0.1
        end = p[-1]["e"] + 0.5
        if j + 1 < len(phrases):
            end = min(end, phrases[j + 1][0]["s"] - 0.1)
        res.append({"words": p, "start": start, "end": max(end, p[-1]["e"])})
    return res


class PhuDe:
    def __init__(self, phrases, W, y_top=1530, size=68, max_w=960):
        self.ph = phrases
        self.W, self.y_top = W, y_top
        self.f = font(size, "black")
        self.max_w = max_w
        self.space = self.f.getbbox("a a")[2] - self.f.getbbox("aa")[2]
        self.cache = {}
        self.layouts = [self._layout(p) for p in phrases]

    def _layout(self, p):
        lines, cur, cw = [], [], 0
        for k, w in enumerate(p["words"]):
            b = self.f.getbbox(w["w"])
            ww = b[2] - b[0]
            add = ww + (self.space if cur else 0)
            if cur and cw + add > self.max_w:
                lines.append((cur, cw))
                cur, cw = [], 0
                add = ww
            cur.append((k, w["w"], ww, b))
            cw += add
        if cur:
            lines.append((cur, cw))
        return lines

    def img(self, pi, active):
        key = (pi, active)
        if key in self.cache:
            return self.cache[key]
        lines = self.layouts[pi]
        lh = 88
        pad = 14
        H = lh * len(lines) + 2 * pad
        im = Image.new("RGBA", (self.W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for li, (ws, cw) in enumerate(lines):
            x = (self.W - cw) / 2
            y = pad + li * lh
            for k, txt, ww, b in ws:
                col = YELLOW if k == active else WHITE
                d.text((x - b[0], y + 8), txt, font=self.f, fill=col + (255,), stroke_width=7, stroke_fill=(10, 10, 10, 255))
                x += ww + self.space
        arr = np.array(im)
        self.cache[key] = arr
        return arr

    def draw(self, frame, t):
        for pi, p in enumerate(self.ph):
            if p["start"] <= t < p["end"]:
                a = ease((t - p["start"]) / 0.12) * ease((p["end"] - t) / 0.12)
                active = None
                ws = p["words"]
                for k, w in enumerate(ws):
                    if w["s"] <= t:
                        active = k
                if active is not None and active == len(ws) - 1 and t > ws[-1]["e"] + 0.35:
                    active = None
                paste_rgba(frame, self.img(pi, active), 0, self.y_top, a)
                return


# ------------------------------------------------------------------ bộ dựng
class Dung:
    def __init__(self, pt, kb, fps, W, H, video=None):
        self.fps, self.W, self.H = fps, W, H
        self.video = video
        self.pip = {}
        self.N = len(pt["ok"])
        self.P = {}
        for k in pt.files:
            v = pt[k]
            if v.ndim == 2 and v.shape[1] == 2 and v.shape[0] == self.N:
                self.P[k] = smooth2(v, 3)
        self.back_coef = smooth2(pt["back_coef"], 3)
        self.back_x0 = smooth(pt["back_x0"], 5)
        self.back_x1 = smooth(pt["back_x1"], 5)
        self.kb = kb
        steps = kb.get("buoc", [])
        n_steps = max([int(s.get("so", 0)) for s in steps] + [0])
        self.the_tren = kb.get("the_tren", {})
        self.headers = []
        for st in steps:
            img = header_img(st, n_steps)
            co = float(st.get("co", self.the_tren.get("co", 1.0)))
            if abs(co - 1) > 1e-3:
                img = cv2.resize(img, (int(img.shape[1] * co), int(img.shape[0] * co)), interpolation=cv2.INTER_AREA)
            self.headers.append(img)
        self.labels = {}
        for c in kb.get("hieu_ung", []):
            if c.get("nhan"):
                self.labels[id(c)] = label_img(c["nhan"], c.get("nhan_phu"), MAU.get(c.get("mau", "vang"), YELLOW))
            if c["loai"] == "so_do_rong":
                self.labels[("so_do", id(c))] = so_do_rong_img(MAU.get(c.get("mau", "vang"), YELLOW))
            if c["loai"] == "dong_ho":
                self.labels[("dh", id(c))] = timer_img(c)
            if c["loai"] == "danh_sach":
                base, overs = checklist_imgs(c)
                co = float(c.get("co", 1.0))
                if abs(co - 1) > 1e-3:
                    rz = lambda im: cv2.resize(im, (int(im.shape[1] * co), int(im.shape[0] * co)), interpolation=cv2.INTER_AREA)
                    base, overs = rz(base), [rz(o) for o in overs]
                self.labels[("ds", id(c))] = (base, overs)
            if c["loai"] == "tho_bung":
                sig = np.load(c["tin_hieu"])
                self.labels[("tb", id(c))] = {"bung": np.asarray(sig["bung"], float), "v": np.asarray(sig["v"], float)}
                self.labels[("tbtxt", id(c))] = {k: belly_text_img(k) for k in ("hit1", "hit2", "tho", "nghi")}
            if c["loai"] == "zzz":
                col = MAU.get(c.get("mau", "trang"), WHITE)
                self.labels[("z", id(c))] = [z_img(sz, col) for sz in (50, 66, 82, 98)]
            if c["loai"] == "so_do_goc":
                self.labels[("sdg", id(c))] = so_do_goc_img(c)
            if c["loai"] == "goc_vuong":
                self.labels[("gv", id(c))] = label_img(c.get("chu", "90°"), None, MAU.get(c.get("mau", "vang"), YELLOW))
            if c["loai"] == "the_canh_bao":
                col = MAU.get(c.get("mau", "do"), RED)
                rows = [warn_row_img(r, int(c.get("rong", 590)), col) for r in c["dong"]]
                co = float(c.get("co", 1.0))
                if abs(co - 1) > 1e-3:
                    rows = [cv2.resize(im, (int(im.shape[1] * co), int(im.shape[0] * co)), interpolation=cv2.INTER_AREA)
                            for im in rows]
                self.labels[("cb", id(c))] = rows
        self.breath_cache = {}
        self.frozen = {}

    # --- điểm
    def pt_at(self, spec, i):
        if isinstance(spec, (list, tuple)):
            return np.array(spec, float)
        if isinstance(spec, str):
            spec = {"diem": spec}
        p = self.P[spec["diem"]][int(np.clip(i, 0, self.N - 1))].copy()
        if "lech" in spec:
            p = p + np.array(spec["lech"], float)
        return p

    def _series(self, spec):
        if isinstance(spec, (list, tuple)):
            return np.tile(np.array(spec, float), (self.N, 1))
        if isinstance(spec, str):
            return self.P[spec]
        return self.P[spec["diem"]] + np.array(spec.get("lech", [0, 0]), float)

    def pt(self, c, key, i):
        if c.get("co_dinh"):
            k = (id(c), key)
            if k not in self.frozen:
                i0 = int(round(c["tu"] * self.fps))
                self.frozen[k] = np.mean([self.pt_at(c[key], j) for j in range(i0, i0 + 6)], axis=0)
            return self.frozen[k]
        return self.pt_at(c[key], i)

    # --- hiệu ứng
    def fx_vong(self, fr, c, i, t, a):
        color = MAU.get(c.get("mau", "vang"), YELLOW)
        C = self.pt(c, "diem", i)
        r0 = c.get("ban_kinh", 60)
        pop = ease_out_back((t - c["tu"]) / 0.4)
        r = r0 * (0.55 + 0.45 * pop) * (1 + 0.035 * np.sin(2 * np.pi * t / 1.1))
        ph = ((t - c["tu"]) / 1.4) % 1
        draw_glow_poly(fr, circle_pts(C, r * (1 + 0.55 * ph)), color, a * (1 - ph) * 0.75, 4, glow=0.4, closed=True)
        fill_poly_alpha(fr, circle_pts(C, r), color, a * 0.12, blur=0)
        draw_glow_poly(fr, circle_pts(C, r), color, a, 8, glow=1.1, closed=True)
        if "cham" in c:
            P0 = C + np.array(c["cham"], float)
            pr = 12 + 4 * np.sin(2 * np.pi * t / 0.8)
            ph2 = ((t - c["tu"]) / 0.9) % 1
            draw_glow_poly(fr, circle_pts(P0, 16 + 40 * ph2, 40), color, a * (1 - ph2), 4, glow=0.3, closed=True)
            fill_poly_alpha(fr, circle_pts(P0, pr, 32), color, a, blur=1.2)
            fill_poly_alpha(fr, circle_pts(P0, pr * 0.45, 24), WHITE, a, blur=1)
        if id(c) in self.labels:
            lab = self.labels[id(c)]
            la = a * ease((t - c["tu"] - c.get("nhan_tre", 0.15)) / 0.3)
            Lc = np.array(c["nhan_xy"], float) if "nhan_xy" in c else C + np.array(c.get("nhan_lech", [0, -r0 - 70]), float)
            leader(fr, C, r, Lc, (lab.shape[1], lab.shape[0]), color, la)
            paste_center(fr, lab, Lc, la)

    def fx_mui_ten(self, fr, c, i, t, a):
        color = MAU.get(c.get("mau", "cam"), ORANGE)
        A = self.pt(c, "tu_diem", i)
        B = self.pt(c, "toi_diem", i) if "toi_diem" in c else A + np.array(c["vec"], float)
        pts = bezier(A, B, c.get("cong", 0.3))
        cum = path_len(pts)
        g = ease_out((t - c["tu"]) / 0.7)
        if g <= 0.01:
            return
        Ld = cum[-1] * g
        k = int(np.searchsorted(cum, Ld))
        sub = np.vstack([pts[:max(k, 1)], point_at(pts, cum, Ld)[0][None]])
        draw_glow_poly(fr, sub, color, a, 12, glow=1.0)
        tip, dvec = point_at(pts, cum, Ld)
        perp = np.array([-dvec[1], dvec[0]])
        head = np.array([tip - dvec * 34 + perp * 24, tip + dvec * 4, tip - dvec * 34 - perp * 24])
        draw_glow_poly(fr, head, color, a, 12, glow=0.8)
        if g >= 0.99:
            f = ((t - c["tu"] - 0.7) / 1.3) % 1
            p, _ = point_at(pts, cum, cum[-1] * f)
            al = a * np.sin(np.pi * f)
            fill_poly_alpha(fr, circle_pts(p, 13, 28), color, al, blur=3)
            fill_poly_alpha(fr, circle_pts(p, 7, 20), WHITE, al, blur=1)
        if id(c) in self.labels:
            lab = self.labels[id(c)]
            if "nhan_xy" in c:
                Lc = np.array(c["nhan_xy"], float)
            elif "nhan_lech_dau" in c:
                Lc = A + np.array(c["nhan_lech_dau"], float)
            else:
                Lc = pts[len(pts) // 2] + np.array(c.get("nhan_lech", [0, -90]), float)
            paste_center(fr, lab, Lc, a * ease((t - c["tu"] - 0.25) / 0.3))

    def fx_duoi(self, fr, c, i, t, a):
        color = MAU.get(c.get("mau", "xanh"), BLUE)
        pts = np.array([self.pt_at(k, i) for k in c["diem"]])
        dense = []
        for j in range(len(pts) - 1):
            for u in np.linspace(0, 1, 12, endpoint=False):
                dense.append(pts[j] + (pts[j + 1] - pts[j]) * u)
        dense.append(pts[-1])
        dense = np.array(dense)
        cum = path_len(dense)
        g = ease_out((t - c["tu"]) / 0.6)
        al = a * (0.7 + 0.3 * np.sin(2 * np.pi * t / 2.4)) if c.get("nhip") else a   # chỉ đường sáng nhấp nháy, nhãn giữ rõ
        day = float(c.get("day", 10))
        seg = dense[:max(2, int(len(dense) * g))]
        if day >= 16:                                   # vệt dày (vd cơ đang gồng): nền mờ rộng + lõi
            draw_glow_poly(fr, seg, color, al * 0.35, day * 2.2, glow=0.6)
        draw_glow_poly(fr, seg, color, al, day, glow=1.1)
        sv = float(c.get("co_vach", 1.0))
        for k in range(3 if c.get("vach", True) else 0):
            f = ((t - c["tu"]) / 1.2 + k / 3) % 1
            p, dvec = point_at(dense, cum, cum[-1] * f)
            perp = np.array([-dvec[1], dvec[0]])
            ch = np.array([p - dvec * 16 * sv + perp * 20 * sv, p + dvec * 6 * sv, p - dvec * 16 * sv - perp * 20 * sv])
            draw_glow_poly(fr, ch, WHITE, a * np.sin(np.pi * f) * g, 7 * sv, glow=0.5)
        if id(c) in self.labels:
            lab = self.labels[id(c)]
            Lc = np.array(c["nhan_xy"], float) if "nhan_xy" in c else dense[len(dense) // 2] + [0, -120]
            paste_center(fr, lab, Lc, a * ease((t - c["tu"] - c.get("nhan_tre", 0.2)) / 0.3))

    def fx_tho(self, fr, c, i, t, a):
        T = float(c.get("chu_ky", 8))
        lt = t - c["tu"]
        ph = (lt % T) / T
        if ph < 0.5:
            state, s = "in", ease(ph / 0.5)
            num = int((ph * T)) + 1
        else:
            state, s = "out", 1 - ease((ph - 0.5) / 0.5)
            num = int((ph - 0.5) * T) + 1
        color = BLUE if state == "in" else ORANGE
        C = np.array(c.get("xy", [800, 720]), float)
        rmin, rmax = c.get("ban_kinh", [122, 162])
        r = rmin + (rmax - rmin) * s
        fill_poly_alpha(fr, circle_pts(C, r + 4), DARK, a * 0.72, blur=0)
        draw_glow_poly(fr, circle_pts(C, r), color, a, 9, glow=1.2, closed=True)
        draw_glow_poly(fr, circle_pts(C, r * 1.18), color, a * 0.35 * s, 4, glow=0.4, closed=True)
        key = (state, num)
        if key not in self.breath_cache:
            self.breath_cache[key] = breath_text_img(state, num)
        paste_center(fr, self.breath_cache[key], C + [0, 4], a)
        if c.get("lung"):
            coef = self.back_coef[i]
            if not np.isnan(coef).any():
                xs = np.linspace(self.back_x0[i] - 15, self.back_x1[i] + 10, 90)
                ys = np.polyval(coef, xs) - 8 - 10 * s
                draw_glow_poly(fr, np.stack([xs, ys], 1), color, a * (0.45 + 0.55 * s), 6 + 6 * s, glow=0.6 + 0.8 * s)

    def fx_goi(self, fr, c, i, t, a):
        color = MAU.get(c.get("mau", "do"), RED)
        C = self.pt(c, "diem", i)
        sl = ease_out((t - c["tu"]) / 0.55)
        C = C + [180 * (1 - sl), 0]
        w, h = c.get("rong", 320), c.get("cao", 46)
        ang = np.deg2rad(c.get("goc", 0))
        rr = h / 2
        arc1 = np.linspace(np.pi / 2, 3 * np.pi / 2, 20)
        arc2 = np.linspace(-np.pi / 2, np.pi / 2, 20)
        left = np.stack([-w / 2 + rr + rr * np.cos(arc1), rr * np.sin(arc1)], 1)
        right = np.stack([w / 2 - rr + rr * np.cos(arc2), rr * np.sin(arc2)], 1)
        shape = np.vstack([left, right])
        R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
        pts = shape @ R.T + C
        aa = a * sl
        fill_poly_alpha(fr, pts, (250, 240, 218), aa * 0.9, blur=1.5)
        hi = np.stack([np.linspace(-w / 2 + rr, w / 2 - rr, 20), np.full(20, -h * 0.18)], 1) @ R.T + C
        draw_glow_poly(fr, hi, WHITE, aa * 0.7, 5, glow=0)
        draw_glow_poly(fr, pts, color, aa, 6, glow=0.8, closed=True)
        if id(c) in self.labels:
            lab = self.labels[id(c)]
            paste_center(fr, lab, C + np.array(c.get("nhan_lech", [0, 100]), float), aa)

    def fx_dong_ho(self, fr, c, i, t, a):
        """Đồng hồ giữ tư thế: vòng tiến độ chạy lặp + chữ GIỮ / 3–5 / PHÚT."""
        color = MAU.get(c.get("mau", "hoac_vang"), AMBER)
        C = np.array(c.get("xy", [975, 800]), float)
        r = float(c.get("ban_kinh", 92))
        pop = ease_out_back((t - c["tu"]) / 0.45)
        rr = r * (0.6 + 0.4 * pop)
        fill_poly_alpha(fr, circle_pts(C, rr + 6), DARK, a * 0.78, blur=0)
        draw_glow_poly(fr, circle_pts(C, rr), (120, 120, 120), a * 0.7, 6, glow=0, closed=True)
        frac = ((t - c["tu"]) / float(c.get("chu_ky", 6))) % 1
        ang = -np.pi / 2 + np.linspace(0, 2 * np.pi * max(frac, 0.02), 90)
        arc = np.stack([C[0] + rr * np.cos(ang), C[1] + rr * np.sin(ang)], 1)
        draw_glow_poly(fr, arc, color, a, 9, glow=1.0)
        fill_poly_alpha(fr, circle_pts(arc[-1], 9, 20), WHITE, a, blur=1)
        img = self.labels[("dh", id(c))]
        sc = rr / r
        if abs(sc - 1) > 0.01:
            img = cv2.resize(img, (max(1, int(img.shape[1] * sc)), max(1, int(img.shape[0] * sc))), interpolation=cv2.INTER_AREA)
        paste_center(fr, img, C, a)

    def _pip_frames(self, c):
        k = id(c)
        if k in self.pip:
            return self.pip[k]
        i0 = int(round(c["nguon_tu"] * self.fps))
        i1 = int(round(c["nguon_den"] * self.fps))
        w = int(c.get("rong", 300))
        h = int(round(w * self.H / self.W))
        col = bgr(MAU.get(c.get("mau", "hoac_vang"), AMBER))
        vr = c.get("vong")
        cap = cv2.VideoCapture(self.video)
        cap.set(cv2.CAP_PROP_POS_FRAMES, i0)
        frames = []
        for j in range(i0, i1):
            ok, f = cap.read()
            if not ok:
                break
            tj = j / self.fps
            if vr and vr["tu"] <= tj <= vr["den"]:
                P0 = self.pt_at(vr["diem"], j)
                cv2.circle(f, (int(P0[0]), int(P0[1])), int(vr.get("ban_kinh", 90)), col, 16, cv2.LINE_AA)
            frames.append(cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA))
        cap.release()
        m = np.zeros((h, w), np.uint8)
        rad = 26
        cv2.rectangle(m, (rad, 0), (w - rad, h), 255, -1)
        cv2.rectangle(m, (0, rad), (w, h - rad), 255, -1)
        for cx, cy in ((rad, rad), (w - rad, rad), (rad, h - rad), (w - rad, h - rad)):
            cv2.circle(m, (cx, cy), rad, 255, -1, cv2.LINE_AA)
        self.pip[k] = (frames, m.astype(np.float32)[..., None] / 255)
        return self.pip[k]

    def fx_chen_lai(self, fr, c, i, t, a):
        """Khung nhỏ phát lại đoạn nguon_tu → nguon_den (tự tăng tốc cho vừa thời lượng hiệu ứng)."""
        frames, m = self._pip_frames(c)
        if not frames:
            return
        color = MAU.get(c.get("mau", "hoac_vang"), AMBER)
        u = np.clip((t - c["tu"]) / max(c["den"] - c["tu"] - 0.3, 0.1), 0, 1)
        f = frames[min(int(u * (len(frames) - 1)), len(frames) - 1)].astype(np.float32)
        x, y = [int(v) for v in c.get("xy", [40, 480])]
        dy = int(40 * (1 - ease_out((t - c["tu"]) / 0.45)))
        y += dy
        h, w = f.shape[:2]
        roi = fr[y:y + h, x:x + w]
        al = m[:roi.shape[0], :roi.shape[1]] * a
        roi *= (1 - al)
        roi += f[:roi.shape[0], :roi.shape[1]] * al
        rect = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], float)
        draw_glow_poly(fr, rect, color, a, 6, glow=0.8, closed=True)
        if id(c) in self.labels:
            lab = self.labels[id(c)]
            paste_center(fr, lab, (x + w / 2, y), a)

    def fx_the_canh_bao(self, fr, c, i, t, a):
        """Các dòng cảnh báo có biểu tượng, hiện lần lượt."""
        rows = self.labels[("cb", id(c))]
        x, y = [int(v) for v in c.get("xy", [40, 500])]
        gap = int(c.get("khoang", 24))
        for k, img in enumerate(rows):
            t0 = c["tu"] + k * float(c.get("tre", 0.7))
            ra = a * ease((t - t0) / 0.35)
            if ra > 0.01:
                dx = int(-70 * (1 - ease_out((t - t0) / 0.45)))
                paste_rgba(fr, img, x + dx, y, ra)
            y += img.shape[0] + gap

    def fx_danh_sach(self, fr, c, i, t, a):
        base, overs = self.labels[("ds", id(c))]
        x, y = [int(v) for v in c.get("xy", [40, 500])]
        dx = int(-50 * (1 - ease_out((t - c["tu"]) / 0.45)))
        paste_rgba(fr, base, x + dx, y, a)
        for r, ov in zip(c["dong"], overs):
            ra = a * ease((t - r["tu"]) / 0.3)
            if ra > 0.01:
                paste_rgba(fr, ov, x + dx, y, ra)

    def _tho_state(self, c, t):
        """Pha hiện tại theo danh sách pha [t0, t1, hit1|hit2|tho]; giữa hai pha thì suy ra."""
        pha = c["pha"]
        for t0, t1, k in pha:
            if t0 <= t <= t1:
                return k
        prev = [p for p in pha if p[1] < t]
        nxt = [p for p in pha if p[0] > t]
        if prev and prev[-1][2] in ("hit1", "hit2") and nxt and nxt[0][2] != "hit1":
            return prev[-1][2]                     # nghỉ ngắn giữa hai nhịp hít / giữ hơi trước khi thở ra
        if prev and prev[-1][2] == "tho" and t - prev[-1][1] < 0.6:
            return "tho"
        return "nghi"

    def fx_tho_bung(self, fr, c, i, t, a):
        """Bụng phồng/xẹp theo tín hiệu đo thật (do_bung.py) + bong bóng HÍT 1/HÍT 2/THỞ RA + thanh nhịp 2-1."""
        sig = self.labels[("tb", id(c))]
        bung, vv = sig["bung"], sig["v"]
        j = int(np.clip(i, 0, len(bung) - 1))
        if "_lohi" not in c:
            j0, j1 = int(c["tu"] * self.fps), int(c["den"] * self.fps)
            seg = bung[j0:j1] if j1 > j0 + 5 else bung
            c["_lohi"] = (float(np.percentile(seg, 5)), float(np.percentile(seg, 97)))
            c["_coef"] = np.nanmedian(self.back_coef[j0:j1], axis=0)
            c["_xr"] = (float(np.nanmedian(self.back_x0[j0:j1])), float(np.nanmedian(self.back_x1[j0:j1])))
        lo, hi = c["_lohi"]
        n = float(np.clip((bung[j] - lo) / (hi - lo + 1e-6), 0, 1))
        st = self._tho_state(c, t)
        color = {"hit1": BLUE, "hit2": BLUE, "tho": ORANGE, "nghi": GREEN}[st]
        # --- bụng: vùng phồng giữa mép thân thật và đường phồng phóng đại
        xc, wb = float(c.get("bung_x", 680)), float(c.get("bung_rong", 130))
        k = float(c.get("phong", 46))
        x0, x1 = c["_xr"]
        xs = np.linspace(max(x0, xc - 2.3 * wb), min(x1, xc + 2.3 * wb), 70)
        base = np.polyval(c["_coef"], xs)
        bell = np.exp(-((xs - xc) / wb) ** 2)
        infl = base - 6 - k * n * bell
        poly = np.vstack([np.stack([xs, infl], 1), np.stack([xs[::-1], base[::-1] + 2], 1)])
        fill_poly_alpha(fr, poly, color, a * (0.18 + 0.2 * n), blur=3)
        draw_glow_poly(fr, np.stack([xs, infl], 1), color, a, 6 + 4 * n, glow=0.6 + 0.8 * n)
        # --- mũi tên theo tốc độ thật
        v = vv[j]
        if v > 0.45 or v < -0.35:
            up = v > 0
            av = a * float(np.clip(abs(v) / (2.0 if up else 1.2), 0, 1))
            topy = float(np.polyval(c["_coef"], xc)) - 6 - k * n - 26
            for q in range(2):
                ph = (t / 0.8 + q / 2) % 1
                cy = topy - (ph * 46 if up else (1 - ph) * 46)
                al = av * np.sin(np.pi * ph)
                if up:
                    ch = np.array([[xc - 34, cy + 13], [xc, cy - 13], [xc + 34, cy + 13]])
                else:
                    ch = np.array([[xc - 34, cy - 13], [xc, cy + 13], [xc + 34, cy - 13]])
                draw_glow_poly(fr, ch, BLUE if up else ORANGE, al, 8, glow=0.6)
        # --- bong bóng theo độ phồng thật
        C = np.array(c.get("xy", [830, 730]), float)
        rmin, rmax = c.get("ban_kinh", [100, 140])
        r = rmin + (rmax - rmin) * n
        fill_poly_alpha(fr, circle_pts(C, r + 4), DARK, a * 0.75, blur=0)
        draw_glow_poly(fr, circle_pts(C, r), color, a, 9, glow=1.2, closed=True)
        draw_glow_poly(fr, circle_pts(C, r * 1.16), color, a * 0.3 * n, 4, glow=0.4, closed=True)
        paste_center(fr, self.labels[("tbtxt", id(c))][st], C, a)
        # --- thanh nhịp
        if "thanh" in c:
            active = {"hit1": 0, "hit2": 1, "tho": 2}.get(st)
            done = {"hit1": (), "hit2": (0,), "tho": (0, 1), "nghi": ()}[st]
            key = ("bar", id(c), active, done)
            if key not in self.labels:
                self.labels[key] = pattern_bar_img(active, set(done), int(c["thanh"].get("rong", 500)))
            paste_center(fr, self.labels[key], c["thanh"]["xy"], a)

    def fx_zzz(self, fr, c, i, t, a):
        """Chữ Z bay lên từ đầu (ngủ quên cũng không sao)."""
        imgs = self.labels[("z", id(c))]
        P0 = self.pt(c, "diem", i)
        T, life = float(c.get("chu_ky", 0.9)), float(c.get("song", 2.6))
        lt = t - c["tu"]
        kmax = int(lt / T)
        for kk in range(max(0, kmax - int(life / T) - 1), kmax + 1):
            u = (lt - kk * T) / life
            if not 0 <= u <= 1:
                continue
            img = imgs[min(int(u * len(imgs)), len(imgs) - 1)]
            pos = P0 + np.array([-70 * u + 18 * np.sin(u * 6 + kk), -190 * u])
            paste_center(fr, img, pos, a * np.sin(np.pi * u) ** 0.7)

    def _bien_do_data(self, c):
        key = ("bd", id(c))
        if key in self.labels:
            return self.labels[key]
        A, B = self._series(c["goc"]), self._series(c["dau"])
        th = smooth(np.unwrap(np.arctan2(B[:, 1] - A[:, 1], B[:, 0] - A[:, 0])), 3)
        v = np.gradient(smooth(th, 5)) * self.fps
        j0 = int(c["tu"] * self.fps)
        j1 = int(min(c["den"] * self.fps, self.N))
        lo, hi = np.percentile(th[j0:j1], [3, 97])
        vt = float(c.get("nguong", 0.25))
        nc = float(c.get("nguong_cuc", 0.86))
        n = (th - lo) / (hi - lo + 1e-9)
        dirs = np.zeros(self.N, int)
        reach = np.full(self.N, -1e9)
        reach_end = np.zeros(self.N, int)
        cur, last_r, last_end = 0, -1e9, 0
        for j in range(self.N):
            if v[j] > vt:
                cur = 1
            elif v[j] < -vt:
                cur = -1
            dirs[j] = cur
            if cur == 1 and n[j] > nc and last_end != 1:
                last_r, last_end = j / self.fps, 1
            elif cur == -1 and n[j] < 1 - nc and last_end != -1:
                last_r, last_end = j / self.fps, -1
            reach[j], reach_end[j] = last_r, last_end
        tg, gm = c["tang"], c["giam"]
        ct, cg = MAU.get(tg.get("mau", "xanh"), BLUE), MAU.get(gm.get("mau", "cam"), ORANGE)
        hm_t = tg.get("het_muc", c.get("het_muc", "hết mức!"))
        hm_g = gm.get("het_muc", c.get("het_muc", "hết mức!"))
        lt, lg = label_img(tg["nhan"], None, ct), label_img(gm["nhan"], None, cg)
        D = dict(th=th, v=v, lo=lo, hi=hi, n=n, dirs=dirs, reach=reach, reach_end=reach_end, ct=ct, cg=cg,
                 lt=lt, lt2=label_img(tg["nhan"], hm_t, ct) if hm_t else lt,
                 lg=lg, lg2=label_img(gm["nhan"], hm_g, cg) if hm_g else lg)
        self.labels[key] = D
        return D

    def fx_bien_do(self, fr, c, i, t, a):
        """Biên độ khớp: cung đo tại 'tam', kim theo hướng goc→dau (vd gót→mũi bàn chân) đo thật từng khung;
        hai đầu cung = hai cực (tang / giam) sáng lên + 'hết mức!' khi chạm; mũi tên cong theo chiều đang chạy."""
        D = self._bien_do_data(c)
        j = int(np.clip(i, 0, self.N - 1))
        lo, hi = D["lo"], D["hi"]
        C = self.pt_at(c["tam"], i)
        R = float(c.get("ban_kinh", 280))
        dirn = int(D["dirs"][j])
        col = D["ct"] if dirn > 0 else (D["cg"] if dirn < 0 else WHITE)
        g = ease_out((t - c["tu"]) / 0.6)

        def P(ang, r=R):
            return C + r * np.array([np.cos(ang), np.sin(ang)])
        cung = c.get("cung", True)
        # dải cung tối + phần đã đi được tô màu theo chiều đang chạy (biên độ) + vạch hai đầu
        bw = float(c.get("day_cung", 26))
        angs = np.linspace(lo, lo + (hi - lo) * g, 60)
        band = np.vstack([np.array([P(x, R + bw) for x in angs]), np.array([P(x, R - bw) for x in angs[::-1]])])
        if cung:
            fill_poly_alpha(fr, band, DARK, a * 0.62, blur=1)
            draw_glow_poly(fr, band, WHITE, a * 0.55, 3, glow=0, closed=True)
        thp = float(np.clip(D["th"][j], lo, hi))
        if cung and dirn != 0 and g > 0.99:
            a0, a1 = (lo, thp) if dirn > 0 else (thp, hi)
            if a1 - a0 > 0.02:
                pa = np.linspace(a0, a1, 40)
                prog = np.vstack([np.array([P(x, R + bw - 5) for x in pa]), np.array([P(x, R - bw + 5) for x in pa[::-1]])])
                fill_poly_alpha(fr, prog, col, a * 0.85, blur=1.5)
        for ang, cc in (((hi, D["ct"]), (lo, D["cg"])) if cung else ()):
            draw_glow_poly(fr, np.array([P(ang, R - 26), P(ang, R + 26)]), cc, a * g, 8, glow=0.6)
        # đoạn đang đo: goc → dau (vd gót → mũi chân, gối → cổ chân), kéo dài thêm
        if c.get("duong", True):
            H0, F0 = self.pt_at(c["goc"], i), self.pt_at(c["dau"], i)
            toe = F0 + (F0 - H0) * float(c.get("keo_dai", 0.45))
            chain = [self.pt_at(k, i) for k in c["chuoi"]] if c.get("chuoi") else [H0]
            draw_glow_poly(fr, np.array(chain + [F0, toe] if c.get("chuoi") else [H0, toe]), col, a * 0.9, 10, glow=1.0)
        # kim
        thc = float(np.clip(D["th"][j], lo - 0.12, hi + 0.12))
        tip = P(thc)
        if cung:
            draw_glow_poly(fr, np.array([P(thc, 70), tip]), col, a, 6, glow=0.8)
            fill_poly_alpha(fr, circle_pts(tip, 15, 28), col, a, blur=2)
            fill_poly_alpha(fr, circle_pts(tip, 7, 20), WHITE, a, blur=1)
        # mũi tên cong theo chiều chuyển động thật
        v = D["v"][j]
        if abs(v) > float(c.get("nguong", 0.25)):
            end = hi + 0.05 if v > 0 else lo - 0.05
            span = float(np.clip(end - thc, -0.45, 0.45))
            if abs(span) > 0.06:
                pts = np.array([P(x, R + 46) for x in np.linspace(thc, thc + span, 24)])
                av = a * float(np.clip(abs(v) / 0.8, 0.3, 1))
                draw_glow_poly(fr, pts, col, av, 9, glow=0.8)
                d = pts[-1] - pts[-2]
                d = d / (np.linalg.norm(d) + 1e-6)
                pp = np.array([-d[1], d[0]])
                head = np.array([pts[-1] - d * 26 + pp * 18, pts[-1] + d * 4, pts[-1] - d * 26 - pp * 18])
                draw_glow_poly(fr, head, col, av, 9, glow=0.6)
        # nhãn hai đầu
        rl = R + float(c.get("nhan_r", 95))
        for ang, end_id, lab, lab2 in ((hi, 1, D["lt"], D["lt2"]), (lo, -1, D["lg"], D["lg2"])):
            reached = D["reach_end"][j] == end_id and t - D["reach"][j] < float(c.get("giu_het_muc", 1.8))
            active = dirn == end_id
            img = lab2 if reached else lab
            if reached:
                pop = ease_out_back((t - D["reach"][j]) / 0.35)
                sc = 0.8 + 0.2 * pop
                img = cv2.resize(img, (max(1, int(img.shape[1] * sc)), max(1, int(img.shape[0] * sc))),
                                 interpolation=cv2.INTER_AREA)
            Lc = P(ang, rl)
            hw, hh = img.shape[1] / 2 + 10, img.shape[0] / 2 + 10
            Lc = np.array([np.clip(Lc[0], hw, self.W - hw), np.clip(Lc[1], hh, self.H - hh)])
            if "nhan_lech" in c:
                Lc = Lc + np.array(c["nhan_lech"].get("tang" if end_id == 1 else "giam", [0, 0]), float)
            paste_center(fr, img, Lc, a * g * (1.0 if (active or reached) else 0.5))

    def fx_dem(self, fr, c, i, t, a):
        """Bộ đếm: vòng N ô sáng dần + số lớn nhảy đúng các mốc 'moc' (vd lúc ngón tay giơ lên)."""
        color = MAU.get(c.get("mau", "hoac_vang"), AMBER)
        moc = c["moc"]
        N = len(moc)
        k = sum(1 for m in moc if t >= m)
        C = np.array(c.get("xy", [650, 400]), float)
        R = float(c.get("ban_kinh", 110))
        pop_in = ease_out_back((t - c["tu"]) / 0.45)
        rr = R * (0.6 + 0.4 * pop_in)
        fill_poly_alpha(fr, circle_pts(C, rr + 8), DARK, a * 0.8, blur=0)
        gap = 0.12
        for q in range(N):
            a0 = -np.pi / 2 + 2 * np.pi * q / N + gap / 2
            a1 = -np.pi / 2 + 2 * np.pi * (q + 1) / N - gap / 2
            arc = np.stack([C[0] + rr * np.cos(np.linspace(a0, a1, 12)), C[1] + rr * np.sin(np.linspace(a0, a1, 12))], 1)
            if q < k:
                draw_glow_poly(fr, arc, color, a, 11, glow=0.9 if q == k - 1 else 0.4)
            else:
                draw_glow_poly(fr, arc, (110, 110, 110), a * 0.8, 7, glow=0)
        if k == 0:
            return
        key = ("dem", id(c), k)
        if key not in self.labels:
            self.labels[key] = count_img(k, color, c.get("tren", "ĐẾM"))
        img = self.labels[key]
        tk = moc[k - 1]
        sc = (0.7 + 0.3 * ease_out_back((t - tk) / 0.3)) * rr / R
        if abs(sc - 1) > 0.01:
            img = cv2.resize(img, (max(1, int(img.shape[1] * sc)), max(1, int(img.shape[0] * sc))), interpolation=cv2.INTER_AREA)
        paste_center(fr, img, C, a)
        ph = (t - tk) / 0.6
        if 0 <= ph <= 1:
            draw_glow_poly(fr, circle_pts(C, rr * (1 + 0.35 * ph)), color, a * (1 - ph) * 0.8, 5, glow=0.4, closed=True)
        if k == N and t - tk > 0.25 and c.get("xong"):
            key2 = ("dem_xong", id(c))
            if key2 not in self.labels:
                self.labels[key2] = label_img(c["xong"], None, color)
            paste_center(fr, self.labels[key2], C + np.array([0, rr + 55]), a * ease((t - tk - 0.25) / 0.3))

    def fx_so_do_goc(self, fr, c, i, t, a):
        img = self.labels[("sdg", id(c))]
        x, y = [int(v) for v in c.get("xy", [40, 290])]
        dy = int(30 * (1 - ease_out((t - c["tu"]) / 0.4)))
        paste_rgba(fr, img, x, y + dy, a)

    def fx_goc_vuong(self, fr, c, i, t, a):
        """Dấu góc vuông tại 'tam' (vd cổ chân): một cạnh dọc theo hướng tới 'huong' (vd gối), cạnh kia vuông góc
        về phía 'phia' (len = hướng lên trên ảnh), kèm nhãn 90°."""
        color = MAU.get(c.get("mau", "vang"), YELLOW)
        C = self.pt_at(c["tam"], i)
        Hh = self.pt_at(c["huong"], i)
        u = Hh - C
        u = u / (np.linalg.norm(u) + 1e-6)
        v = np.array([-u[1], u[0]])
        if (v[1] > 0) == (c.get("phia", "len") == "len"):
            v = -v
        L = float(c.get("canh", 48)) * (0.6 + 0.4 * ease_out_back((t - c["tu"]) / 0.4))
        corner = np.array([C + u * L, C + u * L + v * L, C + v * L])
        draw_glow_poly(fr, np.array([C + u * L * 2.2, C, C + v * L * 2.2]), WHITE, a * 0.8, 5, glow=0.4)
        draw_glow_poly(fr, corner, color, a, 7, glow=0.9)
        lab = self.labels[("gv", id(c))]
        Lc = C + (u + v) * L * 1.2 + np.array(c.get("nhan_lech", [0, -60]), float)
        paste_center(fr, lab, Lc, a * ease((t - c["tu"] - 0.2) / 0.3))

    def fx_tien_do(self, fr, c, i, t, a):
        """Thanh tiến độ (vd 'đã đi hết một nửa chặng đường'): chạy từ 0 tới 'phan'."""
        color = MAU.get(c.get("mau", "luc"), GREEN)
        key = ("td", id(c))
        if key not in self.labels:
            self.labels[key] = label_img(c.get("nhan", ""), None, color) if c.get("nhan") else None
        x0, y0 = [float(v) for v in c.get("xy", [60, 300])]
        w, h = float(c.get("rong", 640)), float(c.get("cao", 44))
        f = float(c.get("phan", 0.5)) * ease_out((t - c["tu"] - 0.3) / 1.2)
        track = np.array([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]])
        fill_poly_alpha(fr, track, DARK, a * 0.8, blur=0)
        draw_glow_poly(fr, track, WHITE, a * 0.7, 3, glow=0, closed=True)
        if f > 0.005:
            bar = np.array([[x0 + 6, y0 + 6], [x0 + 6 + (w - 12) * f, y0 + 6], [x0 + 6 + (w - 12) * f, y0 + h - 6], [x0 + 6, y0 + h - 6]])
            fill_poly_alpha(fr, bar, color, a, blur=1)
            tip = np.array([x0 + 6 + (w - 12) * f, y0 + h / 2])
            fill_poly_alpha(fr, circle_pts(tip, h * 0.55, 30), WHITE, a, blur=2)
        pk = ("tdp", id(c), int(round(f * 100)))
        if pk not in self.labels:
            self.labels[pk] = label_img(f"{int(round(f * 100))}%", None, color)
        paste_center(fr, self.labels[pk], (x0 + w + 70, y0 + h / 2), a)
        if self.labels[key] is not None:
            lab = self.labels[key]
            paste_center(fr, lab, (x0 + lab.shape[1] / 2, y0 - lab.shape[0] / 2 - 12), a)

    def fx_do_cao(self, fr, c, i, t, a):
        """Thước khoảng hở: vạch đứt từ mặt giường (y = 'day') lên tới điểm (vd cổ chân) khi điểm nhấc cao hơn ngưỡng."""
        color = MAU.get(c.get("mau", "vang"), YELLOW)
        Pt = self.pt_at(c["diem"], i)
        yb = float(c.get("day", 990))
        hgap = yb - Pt[1] - float(c.get("lech_day", 25))
        av = a * float(np.clip((hgap - float(c.get("nguong", 50))) / 70, 0, 1))
        if av <= 0.01:
            return
        x = Pt[0] + float(c.get("lech_x", 0))
        y0, y1 = yb, Pt[1] + float(c.get("lech_day", 25))
        n = max(2, int((y0 - y1) / 22))
        for k in range(n):
            u0, u1 = k / n, (k + 0.55) / n
            draw_glow_poly(fr, np.array([[x, y0 + (y1 - y0) * u0], [x, y0 + (y1 - y0) * u1]]), color, av, 5, glow=0.3)
        for yy in (y0, y1):
            draw_glow_poly(fr, np.array([[x - 22, yy], [x + 22, yy]]), color, av, 6, glow=0.4)
        if c.get("nhan") and t <= float(c.get("nhan_den", 1e9)):
            key = ("dc", id(c))
            if key not in self.labels:
                self.labels[key] = label_img(c["nhan"], None, color)
            lab = self.labels[key]
            if "nhan_xy" in c:
                Lc = np.array(c["nhan_xy"], float)
            else:
                Lc = np.array([x, (y0 + y1) / 2]) + np.array(c.get("nhan_lech", [0, 0]), float)
            hw = lab.shape[1] / 2 + 10
            Lc[0] = np.clip(Lc[0], hw, self.W - hw)
            paste_center(fr, lab, Lc, av * ease((float(c.get("nhan_den", 1e9)) - t) / 0.3))

    def fx_nhan(self, fr, c, i, t, a):
        """Nhãn đứng riêng: chữ + dòng phụ, bật lên tại xy (dùng cho đoạn nói chuyện, không có động tác)."""
        key = ("nh", id(c))
        if key not in self.labels:
            img = label_img(c["chu"], c.get("phu"), MAU.get(c.get("mau", "vang"), YELLOW))
            co = float(c.get("co", 1.0))
            if abs(co - 1) > 1e-3:
                img = cv2.resize(img, (int(img.shape[1] * co), int(img.shape[0] * co)), interpolation=cv2.INTER_AREA)
            self.labels[key] = img
        img = self.labels[key]
        pop = ease_out_back((t - c["tu"]) / 0.4)
        sc = 0.75 + 0.25 * pop
        if abs(sc - 1) > 0.01:
            img = cv2.resize(img, (max(1, int(img.shape[1] * sc)), max(1, int(img.shape[0] * sc))), interpolation=cv2.INTER_AREA)
        C = np.array(c.get("xy", [self.W / 2, self.H * 0.72]), float)
        C = C + np.array([0, 6 * np.sin(2 * np.pi * (t - c["tu"]) / 3.0)])
        paste_center(fr, img, C, a)

    def fx_lac(self, fr, c, i, t, a):
        """Mũi tên hai đầu dao động quanh một điểm (vd đẩy bánh chè lên xuống / qua lại).
        truc = danh sách vector hướng, đổi trục mỗi 'doi' giây; bien = biên độ dao động (px)."""
        color = MAU.get(c.get("mau", "vang"), YELLOW)
        C = self.pt_at(c["diem"], i)
        truc = c.get("truc", [[1, 0]])
        k = int((t - c["tu"]) / float(c.get("doi", 2.5))) % len(truc)
        u = np.array(truc[k], float)
        u = u / (np.linalg.norm(u) + 1e-6)
        L = float(c.get("dai", 46))
        off = u * float(c.get("bien", 16)) * np.sin(2 * np.pi * (t - c["tu"]) / float(c.get("chu_ky", 0.9)))
        P0, P1 = C + off - u * L, C + off + u * L
        draw_glow_poly(fr, np.array([P0, P1]), color, a, 8, glow=0.8)
        pp = np.array([-u[1], u[0]])
        for tip, d in ((P1, u), (P0, -u)):
            head = np.array([tip - d * 22 + pp * 16, tip + d * 3, tip - d * 22 - pp * 16])
            draw_glow_poly(fr, head, color, a, 8, glow=0.6)
        fill_poly_alpha(fr, circle_pts(C + off, 9, 20), WHITE, a, blur=1)
        if c.get("nhan"):
            key = ("lac", id(c))
            if key not in self.labels:
                self.labels[key] = label_img(c["nhan"], c.get("nhan_phu"), color)
            lab = self.labels[key]
            Lc = np.array(c["nhan_xy"], float) if "nhan_xy" in c else C + np.array(c.get("nhan_lech", [0, -110]), float)
            leader(fr, C, L + 10, Lc, (lab.shape[1], lab.shape[0]), color, a)
            paste_center(fr, lab, Lc, a * ease((t - c["tu"] - 0.2) / 0.3))

    def fx_so_do_rong(self, fr, c, i, t, a):
        img = self.labels[("so_do", id(c))]
        x, y = c.get("xy", [715, 470])
        dy = int(30 * (1 - ease_out((t - c["tu"]) / 0.4)))
        paste_rgba(fr, img, int(x), int(y) + dy, a)

    # --- khung
    def render(self, bgr_u8, i):
        fr = bgr_u8.astype(np.float32)
        t = i / self.fps
        for c in self.kb.get("hieu_ung", []):
            if c["tu"] - 0.01 <= t <= c["den"] + 0.01:
                a = env(t, c["tu"], c["den"])
                if a > 0.005:
                    getattr(self, "fx_" + c["loai"])(fr, c, i, t, a)
        for c, img in zip(self.kb.get("buoc", []), self.headers):
            if c["tu"] - FADE / 2 <= t <= c["den"] + FADE / 2:
                a = ease((t - c["tu"] + FADE / 2) / FADE) * ease((c["den"] - t + FADE / 2) / FADE)
                if c["tu"] <= 0.01:
                    a = ease((c["den"] - t + FADE / 2) / FADE)
                dy = int(18 * (1 - ease((t - c["tu"] + FADE / 2) / (FADE * 1.5))))
                x = int(c.get("x", self.the_tren.get("x", (self.W - img.shape[1]) // 2)))
                paste_rgba(fr, img, x, int(c.get("y", self.the_tren.get("y", 170))) + dy, a)
        return fr


def ten_ra(thu_muc: Path, stem: str, hau_to: str, stamp: str) -> Path:
    base = f"{stem}_{hau_to}_{stamp}"
    p = thu_muc / f"{base}.mp4"
    k = 1
    while p.exists():
        k += 1
        p = thu_muc / f"{base}_{k}.mp4"
    return p


def ffmpeg_proc(out, W, H, fps, video, enc, extra):
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "pipe:0",
           "-i", video, "-map", "0:v:0", "-map", "1:a:0?",
           "-c:v", enc, *extra, "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("npz")
    ap.add_argument("kich_ban")
    ap.add_argument("--loi", default=None, help="loi.json từ chep_loi.py (để làm bản có phụ đề)")
    ap.add_argument("--ra", default=None, help="thư mục xuất (mặc định Downloads)")
    ap.add_argument("--mau", default=None, help="chỉ xuất các khung này ra PNG (bản có phụ đề nếu có --loi)")
    ap.add_argument("--bung", default=None, help="tín hiệu bụng từ do_bung.py cho hiệu ứng tho_bung")
    a = ap.parse_args()

    pt = np.load(a.npz)
    kb = json.loads(Path(a.kich_ban).read_text(encoding="utf-8"))
    for c in kb.get("hieu_ung", []):
        if c["loai"] == "tho_bung" and a.bung:
            c["tin_hieu"] = a.bung
    fps = float(pt["fps"])
    W, H = [int(v) for v in pt["size"]]
    N = len(pt["ok"])
    d = Dung(pt, kb, fps, W, H, video=a.video)
    sub = None
    if a.loi:
        segs = json.loads(Path(a.loi).read_text(encoding="utf-8"))
        phrases = build_phrases(segs, kb.get("sua_loi", {}))
        sub = PhuDe(phrases, W)
        for p in phrases:
            print(f"  [{p['start']:5.2f}-{p['end']:5.2f}] {' '.join(w['w'] for w in p['words'])}")

    outdir = Path(a.ra) if a.ra else downloads_dir()
    outdir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(a.video)
    if a.mau:
        for i in [int(x) for x in a.mau.split(",")]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = cap.read()
            if not ok:
                continue
            f = d.render(fr, i)
            if sub:
                sub.draw(f, i / fps)
            p = outdir / f"mau_{i:04d}.png"
            cv2.imwrite(str(p), np.clip(f, 0, 255).astype(np.uint8))
            print("→", p)
        return

    stem = Path(a.video).stem
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    enc, extra = chon_encoder()
    out1 = ten_ra(outdir, stem, "hieu_ung", stamp)
    procs = [(ffmpeg_proc(out1, W, H, fps, a.video, enc, extra), out1, False)]
    if sub:
        out2 = ten_ra(outdir, stem, "hieu_ung_phu_de", stamp)
        procs.append((ffmpeg_proc(out2, W, H, fps, a.video, enc, extra), out2, True))
    print(f"encoder: {enc} → " + " | ".join(str(p[1]) for p in procs), flush=True)
    i = 0
    try:
        while i < N:
            ok, fr = cap.read()
            if not ok:
                break
            base = d.render(fr, i)
            procs[0][0].stdin.write(np.clip(base, 0, 255).astype(np.uint8).tobytes())
            if sub:
                f2 = base.copy()
                sub.draw(f2, i / fps)
                procs[1][0].stdin.write(np.clip(f2, 0, 255).astype(np.uint8).tobytes())
            if i % 150 == 0:
                print(f"  khung {i}/{N}", flush=True)
            i += 1
    finally:
        for p, _, _ in procs:
            p.stdin.close()
            p.wait()
        cap.release()
    bad = [str(o) for p, o, _ in procs if p.returncode != 0]
    if bad:
        print("ffmpeg lỗi:", bad)
        sys.exit(1)
    for _, o, _ in procs:
        print(f"Xong {i} khung → {o}")


if __name__ == "__main__":
    main()
