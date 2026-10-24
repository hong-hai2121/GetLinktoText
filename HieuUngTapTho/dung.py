"""Dựng hiệu ứng cho video bài tập mèo-bò (cat-cow), góc quay ngang, video dọc.

Hiệu ứng:
  - Nhãn trên cùng: HÍT VÀO (cúi đầu xuống) / THỞ RA (ngửa đầu lên) – đổi theo HƯỚNG chuyển động của đầu,
    giữ nguyên khi đang dừng ở tư thế.
  - Đường cong lưng (bám mép lưng thật từ mặt nạ người) sáng lên khi cúi (lưng cong lên ∩), kèm mũi tên ↑ chạy.
  - Đường cong bụng (bám mép bụng thật) sáng lên khi ngửa (bụng võng xuống ∪), kèm mũi tên ↓ chạy.
  - Luồng khí: hạt mũi tên bay VÀO mũi khi hít, bay RA từ miệng khi thở.
  - Chú giải 2 thẻ ở đáy, thẻ đang đúng pha sáng lên.

Chạy (venv_lamdep hoặc venv cha, cần cv2 + numpy + PIL, ffmpeg trên PATH):
    python dung.py <video> <phan_tich.npz>                 → xuất mp4 ra Downloads
    python dung.py <video> <phan_tich.npz> --mau 30,200,400 → chỉ xuất khung mẫu PNG để xem trước
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ màu & chữ
BLUE = (60, 170, 255)        # hít vào / lưng (RGB)
ORANGE = (255, 150, 50)      # thở ra / bụng
GRAY = (215, 215, 215)       # chuẩn bị
WHITE = (255, 255, 255)
DARK = (14, 18, 36)
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def bgr(c):
    return (c[2], c[1], c[0])


def font(size, weight="black"):
    cands = {"black": ["seguibl.ttf", "arialbd.ttf"], "bold": ["segoeuib.ttf", "arialbd.ttf"],
             "semibold": ["seguisb.ttf", "arialbd.ttf"]}[weight]
    for c in cands:
        p = FONT_DIR / c
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


# ------------------------------------------------------------------ xử lý tín hiệu
def fill_nan(a):
    a = np.array(a, dtype=np.float64, copy=True)
    idx = np.arange(len(a))
    m = np.isnan(a)
    if m.all():
        return np.zeros_like(a)
    a[m] = np.interp(idx[m], idx[~m], a[~m])
    return a


def smooth(a, sigma):
    a = fill_nan(a)
    if sigma <= 0:
        return a
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(a, r, mode="edge"), k, mode="valid")


def smooth2(a, sigma):
    return np.stack([smooth(a[:, j], sigma) for j in range(a.shape[1])], 1)


def smoothstep(x, lo=0.2, hi=0.8):
    t = np.clip((x - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ vẽ lên khung float32 BGR
def blend_roi(frame, x0, y0, a, color):
    """a: HxW float [0,1] (đã nhân alpha). Trộn màu vào frame tại (x0,y0)."""
    H, W = frame.shape[:2]
    h, w = a.shape
    xs, ys = max(0, x0), max(0, y0)
    xe, ye = min(W, x0 + w), min(H, y0 + h)
    if xe <= xs or ye <= ys:
        return
    sub = a[ys - y0:ye - y0, xs - x0:xe - x0][..., None]
    roi = frame[ys:ye, xs:xe]
    roi *= (1 - sub)
    roi += np.array(bgr(color), np.float32) * sub


def draw_glow_poly(frame, pts, color, alpha, width, glow=1.0, closed=False):
    """pts: Nx2 float. Đường neon: quầng mờ + lõi màu + lõi trắng mảnh."""
    if alpha <= 0.01 or len(pts) < 2:
        return
    pad = int(width * 5 + 12)
    x0, y0 = (pts.min(0) - pad).astype(int)
    x1, y1 = (pts.max(0) + pad).astype(int)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    loc = ((pts - [x0, y0]) * 16).astype(np.int32).reshape(-1, 1, 2)
    layer = np.zeros((h, w), np.uint8)
    cv2.polylines(layer, [loc], closed, 255, max(1, int(width)), cv2.LINE_AA, shift=4)
    a = layer.astype(np.float32) / 255
    if glow > 0:
        g = cv2.GaussianBlur(layer, (0, 0), width * 1.6).astype(np.float32) / 255
        a = np.clip(a + g * glow, 0, 1)
    blend_roi(frame, x0, y0, a * alpha, color)
    if width >= 6:
        core = np.zeros((h, w), np.uint8)
        cv2.polylines(core, [loc], closed, 255, max(1, int(width // 3)), cv2.LINE_AA, shift=4)
        blend_roi(frame, x0, y0, core.astype(np.float32) / 255 * alpha * 0.85, WHITE)


def draw_arrow(frame, p0, p1, color, alpha, width=7, glow=0.8):
    if alpha <= 0.01:
        return
    pts = np.array([p0, p1], float)
    pad = int(width * 5 + 30)
    x0, y0 = (pts.min(0) - pad).astype(int)
    x1, y1 = (pts.max(0) + pad).astype(int)
    w, h = x1 - x0, y1 - y0
    layer = np.zeros((h, w), np.uint8)
    a0 = tuple(((pts[0] - [x0, y0]) * 16).astype(int))
    a1 = tuple(((pts[1] - [x0, y0]) * 16).astype(int))
    cv2.arrowedLine(layer, a0, a1, 255, width, cv2.LINE_AA, shift=4, tipLength=0.45)
    a = layer.astype(np.float32) / 255
    if glow > 0:
        g = cv2.GaussianBlur(layer, (0, 0), width * 1.4).astype(np.float32) / 255
        a = np.clip(a + g * glow, 0, 1)
    blend_roi(frame, x0, y0, a * alpha, color)


def paste_rgba(frame, rgba, x, y, alpha=1.0):
    if alpha <= 0.01:
        return
    a = rgba[..., 3].astype(np.float32) / 255 * alpha
    H, W = frame.shape[:2]
    h, w = a.shape
    xs, ys = max(0, x), max(0, y)
    xe, ye = min(W, x + w), min(H, y + h)
    if xe <= xs or ye <= ys:
        return
    sa = a[ys - y:ye - y, xs - x:xe - x][..., None]
    col = rgba[ys - y:ye - y, xs - x:xe - x, :3][..., ::-1].astype(np.float32)
    roi = frame[ys:ye, xs:xe]
    roi *= (1 - sa)
    roi += col * sa


# ------------------------------------------------------------------ các tấm chữ (PIL, cache)
def pill(text, color, size=56, pad=(30, 14), radius=None, fill_alpha=200, border=0):
    f = font(size, "black")
    tb = f.getbbox(text)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    w, h = tw + 2 * pad[0], th + 2 * pad[1]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = radius if radius is not None else h // 2
    d.rounded_rectangle([0, 0, w - 1, h - 1], r, fill=DARK + (fill_alpha,),
                        outline=(color + (255,)) if border else None, width=border)
    d.text((pad[0] - tb[0], pad[1] - tb[1]), text, font=f, fill=color + (255,))
    return np.array(img)


def arrow_icon(d, cx, cy, size, color, up):
    """Mũi tên dọc đơn giản (PIL)."""
    s = size
    shaft_w = s * 0.22
    head_h = s * 0.42
    if up:
        d.polygon([(cx - s / 2, cy - s / 2 + head_h), (cx, cy - s / 2), (cx + s / 2, cy - s / 2 + head_h)], fill=color)
        d.rectangle([cx - shaft_w / 2, cy - s / 2 + head_h - 2, cx + shaft_w / 2, cy + s / 2], fill=color)
    else:
        d.polygon([(cx - s / 2, cy + s / 2 - head_h), (cx, cy + s / 2), (cx + s / 2, cy + s / 2 - head_h)], fill=color)
        d.rectangle([cx - shaft_w / 2, cy - s / 2, cx + shaft_w / 2, cy + s / 2 - head_h + 2], fill=color)


def top_banner(state):
    """Nhãn lớn trên cùng. state: 0 chuẩn bị, 1 hít vào, 2 thở ra."""
    W, H = 820, 250
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = {0: GRAY, 1: BLUE, 2: ORANGE}[state]
    main = {0: "TƯ THẾ CHUẨN BỊ", 1: "HÍT VÀO", 2: "THỞ RA"}[state]
    sub = {0: "Quỳ 4 điểm", 1: "Cúi đầu xuống", 2: "Ngửa đầu lên"}[state]
    d.rounded_rectangle([0, 0, W - 1, H - 1], 60, fill=DARK + (215,), outline=color + (255,), width=6)
    f1 = font(118 if state else 74, "black")
    f2 = font(54, "bold")
    tb = f1.getbbox(main)
    tw = tb[2] - tb[0]
    icon_w = 90 if state else 0
    x = (W - tw - icon_w) / 2 + icon_w
    y = 28 - tb[1]
    d.text((x, y), main, font=f1, fill=color + (255,))
    if state:
        arrow_icon(d, x - icon_w + 22, 28 + (tb[3] - tb[1]) / 2, 64, color + (255,), up=(state == 2))
    sb = f2.getbbox(sub)
    d.text(((W - (sb[2] - sb[0])) / 2 - sb[0], 168 - sb[1]), sub, font=f2, fill=WHITE + (255,))
    return np.array(img)


def legend_card(idx, active):
    """Thẻ chú giải ở đáy. idx 1: cúi/hít/lưng, 2: ngửa/thở/bụng."""
    W, H = 505, 250
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = BLUE if idx == 1 else ORANGE
    tcol = color if active else (190, 190, 190)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 34, fill=DARK + (205 if active else 150,),
                        outline=(color + (255,)) if active else ((120, 120, 120, 255)), width=6 if active else 3)
    f1 = font(42, "black")
    f2 = font(52, "black")
    f3 = font(36, "bold")
    t1 = "CÚI ĐẦU" if idx == 1 else "NGỬA ĐẦU"
    t2 = "HÍT VÀO" if idx == 1 else "THỞ RA"
    t3 = "Lưng cong lên" if idx == 1 else "Bụng võng xuống"
    # số thứ tự tròn
    d.ellipse([22, 22, 84, 84], fill=tcol + (255,))
    fn = font(42, "black")
    nb = fn.getbbox(str(idx))
    d.text((53 - (nb[0] + nb[2]) / 2, 53 - (nb[1] + nb[3]) / 2), str(idx), font=fn, fill=DARK + (255,))
    b1 = f1.getbbox(t1)
    d.text((102 - b1[0], 53 - (b1[1] + b1[3]) / 2), t1, font=f1, fill=WHITE + (255 if active else 200,))
    b2 = f2.getbbox(t2)
    d.text((24 - b2[0], 128 - (b2[1] + b2[3]) / 2), t2, font=f2, fill=tcol + (255,))
    b3 = f3.getbbox(t3)
    d.text((24 - b3[0], 203 - (b3[1] + b3[3]) / 2), t3, font=f3, fill=WHITE + (255 if active else 200,))
    # biểu tượng ∩ / ∪ bên phải dòng cuối
    cx, cy = W - 62, 203
    box = [cx - 34, cy - 22, cx + 34, cy + 22]
    if idx == 1:
        d.arc(box, 180, 360, fill=tcol + (255,), width=7)
    else:
        d.arc(box, 0, 180, fill=tcol + (255,), width=7)
    return np.array(img)


# ------------------------------------------------------------------ Downloads
def downloads_dir() -> Path:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            raw = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
        p = Path(os.path.expandvars(raw))
        if p.is_dir():
            return p
    except Exception:
        pass
    return Path.home() / "Downloads"


def ten_ra(thu_muc: Path, goc: Path, duoi=".mp4") -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{goc.stem}_hieu_ung_{stamp}"
    p = thu_muc / f"{base}{duoi}"
    k = 1
    while p.exists():
        k += 1
        p = thu_muc / f"{base}_{k}{duoi}"
    return p


def chon_encoder():
    for enc, extra in [("h264_nvenc", ["-preset", "p5", "-cq", "19", "-b:v", "0"]),
                       ("h264_qsv", ["-global_quality", "20"]),
                       ("h264_amf", ["-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]),
                       ("libx264", ["-preset", "medium", "-crf", "18"])]:
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=256x256:rate=30",
                            "-frames:v", "2", "-c:v", enc, "-f", "null", "-"], capture_output=True)
        if r.returncode == 0:
            return enc, extra
    return "libx264", ["-preset", "medium", "-crf", "18"]


# ------------------------------------------------------------------ chính
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("npz")
    ap.add_argument("--ra", default=None, help="thư mục xuất (mặc định Downloads)")
    ap.add_argument("--mau", default=None, help="chỉ xuất các khung này ra PNG, vd 30,200,400")
    a = ap.parse_args()

    d = np.load(a.npz)
    fps = float(d["fps"])
    W, H = [int(v) for v in d["size"]]
    N = len(d["ok"])
    nose = smooth2(d["nose"], 2.5)
    mouth = smooth2(d["mouth"], 2.5)
    ear = smooth2(d["ear"], 2.5)
    shoulder = smooth2(d["shoulder"], 3)
    back_coef = smooth2(d["back_coef"], 3)
    belly_coef = smooth2(d["belly_coef"], 4)
    back_x0 = smooth(d["back_x0"], 5); back_x1 = smooth(d["back_x1"], 5)
    belly_x0 = smooth(d["belly_x0"], 6); belly_x1 = smooth(d["belly_x1"], 6)

    # ---- pha & trạng thái thở
    head = smooth(shoulder[:, 1] - nose[:, 1], 4)           # dương = đầu cao hơn vai
    lo, hi = np.percentile(head, 3), np.percentile(head, 97)
    p_cow = np.clip((head - lo) / (hi - lo), 0, 1)
    p_cat = 1 - p_cow                                        # 1 = cúi hẳn (lưng cong lên)
    a_back = smoothstep(p_cat)                                # mức sáng đường lưng
    a_belly = smoothstep(p_cow)                               # mức sáng đường bụng
    g_back = smoothstep(p_cat, 0.45, 0.75)                    # nhãn + mũi tên: chỉ hiện khi đã rõ tư thế
    g_belly = smoothstep(p_cow, 0.45, 0.75)
    v = np.gradient(smooth(head, 6)) * fps                   # px/s, dương = đầu đi lên
    top1 = int(np.argmax(head > lo + 0.8 * (hi - lo)))
    start = int(np.argmin(head[:max(top1, 1)]))
    state = np.zeros(N, int)
    cur = 2                                                   # từ điểm thấp nhất đầu đi lên → thở ra
    for i in range(start, N):
        if v[i] > 45:
            cur = 2
        elif v[i] < -45:
            cur = 1
        state[i] = cur
    w_state = np.stack([smooth((state == s).astype(float), 2.5) for s in range(3)], 1)
    print(f"bắt đầu chu kỳ ở khung {start} ({start / fps:.1f}s); đổi trạng thái tại:",
          [f"{i / fps:.1f}s→{'hít' if state[i] == 1 else 'thở'}" for i in range(1, N) if state[i] != state[i - 1]])

    banners = [top_banner(s) for s in range(3)]
    cards = {(idx, act): legend_card(idx, act) for idx in (1, 2) for act in (False, True)}
    tag_back = pill("LƯNG CONG LÊN", BLUE, 58)
    tag_belly = pill("BỤNG VÕNG XUỐNG", ORANGE, 58)

    def render(i, bgr_u8):
        fr = bgr_u8.astype(np.float32)
        t = i / fps
        # ---- đường lưng
        xs = np.linspace(back_x0[i] - 15, back_x1[i] + 10, 90)
        ys = np.polyval(back_coef[i], xs) - 7
        pts_b = np.stack([xs, ys], 1)
        ab = a_back[i]
        draw_glow_poly(fr, pts_b, BLUE, 0.35 + 0.65 * ab, 5 + 8 * ab, glow=1.3 * ab)
        # ---- đường bụng
        xs2 = np.linspace(belly_x0[i] - 12, belly_x1[i] + 12, 60)
        ys2 = np.polyval(belly_coef[i], xs2) + 7
        pts_u = np.stack([xs2, ys2], 1)
        au = a_belly[i]
        draw_glow_poly(fr, pts_u, ORANGE, 0.35 + 0.65 * au, 5 + 8 * au, glow=1.3 * au)
        # ---- mũi tên chạy + nhãn cạnh đường cong
        T = 1.1
        gb = g_back[i] * (1 - w_state[i, 0])
        gu = g_belly[i] * (1 - w_state[i, 0])
        if gb > 0.02:
            mx = (xs[0] + xs[-1]) / 2
            my = np.polyval(back_coef[i], mx) - 40
            for k in range(3):
                ph = (t / T + k / 3) % 1
                cy = my - 20 - ph * 95
                al = np.sin(np.pi * ph) * gb
                ch = np.array([[mx - 46, cy + 17], [mx, cy - 17], [mx + 46, cy + 17]])
                draw_glow_poly(fr, ch, BLUE, al, 9, glow=0.6)
            paste_rgba(fr, tag_back, int(mx - tag_back.shape[1] / 2), int(my - 150 - tag_back.shape[0]), gb)
        if gu > 0.02:
            mx = (xs2[0] + xs2[-1]) / 2
            my = np.polyval(belly_coef[i], mx) + 40
            for k in range(3):
                ph = (t / T + k / 3) % 1
                cy = my + 20 + ph * 95
                al = np.sin(np.pi * ph) * gu
                ch = np.array([[mx - 46, cy - 17], [mx, cy + 17], [mx + 46, cy - 17]])
                draw_glow_poly(fr, ch, ORANGE, al, 9, glow=0.6)
            paste_rgba(fr, tag_belly, int(mx - tag_belly.shape[1] / 2), int(my + 150), gu)
        # ---- luồng khí ở mũi/miệng
        st = state[i]
        if st:
            fdir = nose[i] - ear[i]
            fdir[0] = min(fdir[0], 0.0)                       # người nhìn sang trái: không cho luồng khí quay sang phải
            n = np.linalg.norm(fdir)
            fdir = fdir / n if n > 1 else np.array([-1.0, 0.0])
            perp = np.array([-fdir[1], fdir[0]])
            col = BLUE if st == 1 else ORANGE
            anchor = nose[i] if st == 1 else mouth[i]
            Tp = 0.85
            for s_i, off in enumerate((-1, 0, 1)):
                for k in range(2):
                    ph = (t / Tp + k / 2 + s_i * 0.17) % 1
                    if st == 1:     # bay vào mũi: xa → gần, gom lại
                        dist = 250 - ph * 200
                        sp = (48 - ph * 34) * off
                        dv = -fdir
                    else:           # thở ra: gần → xa, toả ra
                        dist = 50 + ph * 200
                        sp = (14 + ph * 34) * off
                        dv = fdir
                    c = anchor + fdir * dist + perp * sp
                    p0 = c - dv * 26
                    p1 = c + dv * 26
                    al = np.sin(np.pi * ph) * w_state[i, st]
                    draw_arrow(fr, p0, p1, col, al * 0.95, 7)
        # ---- nhãn trên cùng (mờ dần giữa các trạng thái)
        for s in range(3):
            ws = w_state[i, s]
            if ws > 0.01:
                b = banners[s]
                paste_rgba(fr, b, (W - b.shape[1]) // 2, 190, ws)
        # ---- chú giải đáy
        act1 = w_state[i, 1]
        act2 = w_state[i, 2]
        y0 = H - 400
        c1, c2 = cards[(1, False)], cards[(2, False)]
        paste_rgba(fr, c1, 25, y0, 1.0)
        paste_rgba(fr, cards[(1, True)], 25, y0, act1)
        paste_rgba(fr, c2, W - 25 - c2.shape[1], y0, 1.0)
        paste_rgba(fr, cards[(2, True)], W - 25 - c2.shape[1], y0, act2)
        return np.clip(fr, 0, 255).astype(np.uint8)

    cap = cv2.VideoCapture(a.video)
    if a.mau:
        idxs = [int(x) for x in a.mau.split(",")]
        outdir = Path(a.ra) if a.ra else downloads_dir()
        outdir.mkdir(parents=True, exist_ok=True)
        for i in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = cap.read()
            if not ok:
                continue
            p = outdir / f"mau_{i:04d}.png"
            cv2.imwrite(str(p), render(i, fr))
            print("→", p)
        return

    outdir = Path(a.ra) if a.ra else downloads_dir()
    outdir.mkdir(parents=True, exist_ok=True)
    out = ten_ra(outdir, Path(a.video))
    enc, extra = chon_encoder()
    print(f"encoder: {enc} → {out}", flush=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "pipe:0",
           "-i", a.video, "-map", "0:v:0", "-map", "1:a:0?",
           "-c:v", enc, *extra, "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    i = 0
    try:
        while i < N:
            ok, fr = cap.read()
            if not ok:
                break
            proc.stdin.write(render(i, fr).tobytes())
            if i % 150 == 0:
                print(f"  khung {i}/{N}", flush=True)
            i += 1
    finally:
        proc.stdin.close()
        proc.wait()
    cap.release()
    if proc.returncode != 0:
        print("ffmpeg lỗi", proc.returncode)
        sys.exit(1)
    print(f"Xong {i} khung → {out}")


if __name__ == "__main__":
    main()
