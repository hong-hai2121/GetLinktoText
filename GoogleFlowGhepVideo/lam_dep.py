# -*- coding: utf-8 -*-
"""Làm đẹp clip HOOK: làm trắng da + son môi (mặt nạ TỪNG KHUNG HÌNH bằng MediaPipe Face Landmarker, 478 điểm)
và chỉnh màu toàn khung (sức sống, độ sáng, tương phản, nhiệt độ màu). Chỉ áp cho clip hook (10 giây đầu);
phần sau và cảnh kho minh họa giữ nguyên (user yêu cầu 19/10/2026).

Cách chạy: đọc từng khung bằng cv2 -> dò 478 điểm mặt -> mặt nạ da/môi -> áp bằng numpy (chỉ trong vùng mặt)
-> bơm rawvideo sang ffmpeg mã hóa libx264; chỉnh màu toàn khung (vibrance/eq/colortemperature) giao cho chính
ffmpeg đó (đa luồng, gần như miễn phí; numpy làm việc này mất 23 ms/khung). Xem thử trong tab Làm đẹp đi đúng
hai bước đó trên ảnh mẫu nên thấy sao ra vậy.

MediaPipe kéo numpy 2 + opencv-contrib, cài vào venv chung sẽ vỡ pandas/numba của tool khác -> nằm ở venv RIÊNG
`..\\venv_lamdep` (tạo: python -m venv venv_lamdep && venv_lamdep\\Scripts\\pip install mediapipe).
Phần áp hiệu ứng chỉ cần numpy + cv2 nên app.py (venv chính) import thẳng để xem thử nhanh; điểm mốc của ảnh mẫu
lấy qua subprocess `--diem-moc` một lần. Xử lý video chạy trọn trong venv_lamdep (ghep_tieude gọi subprocess).

Dòng lệnh (chạy bằng python của venv_lamdep):
  lam_dep.py --diem-moc <ảnh>                          -> in JSON [[x,y],...] (478 điểm, pixel) hoặc null
  lam_dep.py --anh <ảnh> --ra <jpg> [--ghep] --tc "trang=60,son=40,son_mau=hong,suc_song=30,sang=0,tuong_phan=0,nhiet=0"
  lam_dep.py --video <in> --ra <out.mp4> --tc "..." [--giay N] [--crf 16]
Model: face_landmarker.task (Google, ~3,7 MB) cạnh file này; thiếu thì tự tải.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = HERE / "face_landmarker.task"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
VENV_PY = (HERE.parent / "venv_lamdep" / "Scripts" / "python.exe" if os.name == "nt"   # python có mediapipe
           else HERE.parent / "venv_lamdep" / "bin" / "python")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ENV_IM = {"PYTHONUTF8": "1", "GLOG_minloglevel": "2", "TF_CPP_MIN_LOG_LEVEL": "2"}   # bớt log rác của mediapipe

# ----- tham số: trang/son 0..100; suc_song/sang/tuong_phan/nhiet -100..100 -----
MAC_DINH = dict(trang=30, son=15, son_mau="cam", suc_song=20, sang=0, tuong_phan=0, nhiet=0)   # user chốt 19/10/2026
KHOA = ("trang", "son", "son_mau", "suc_song", "sang", "tuong_phan", "nhiet")
SON_MAU = {          # màu son -> (ΔCr, ΔCb, hệ số sáng) ở mức 100%
    "hong": (22.0, 2.0, 0.97),     # hồng tự nhiên
    "do": (32.0, -6.0, 0.93),      # đỏ
    "cam": (26.0, -16.0, 0.95),    # cam đất
}
GIU_MOC_TOI_DA = 15      # mất mặt -> giữ mốc cũ tối đa bấy nhiêu khung rồi bỏ hiệu ứng
EMA = 0.6                # làm mượt mốc giữa các khung (giảm rung viền)
TRAN_THEM = 0.30         # viền mặt MediaPipe dừng dưới chân tóc ~50px -> đẩy các điểm phía trên mắt lên thêm bấy nhiêu
                         # lần chiều cao mặt (đỉnh trán lên hết, hai bên ít dần); tóc bị cổng màu da loại ra

# ----- chỉ số điểm MediaPipe Face Mesh -----
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
             148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
JAW = [93, 132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361, 323]  # hàm, trái->phải
LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
LEFT_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
RIGHT_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]


# ================================================================ tham số
def _so(v, mac_dinh):
    try:
        return float(v)
    except (TypeError, ValueError):
        return mac_dinh


def doc_tc(s: str | dict | None) -> dict:
    """'trang=60,son=40,son_mau=hong,...' hoặc dict -> dict đủ khóa, kẹp khoảng."""
    d = dict(MAC_DINH)
    if isinstance(s, dict):
        d.update({k: v for k, v in s.items() if k in d})
    elif s:
        for cap in str(s).split(","):
            if "=" in cap:
                k, v = cap.split("=", 1)
                if k.strip() in d:
                    d[k.strip()] = v.strip()
    kq = {}
    for k in ("trang", "son"):
        kq[k] = int(round(max(0, min(100, _so(d[k], MAC_DINH[k])))))
    for k in ("suc_song", "sang", "tuong_phan", "nhiet"):
        kq[k] = int(round(max(-100, min(100, _so(d[k], MAC_DINH[k])))))
    kq["son_mau"] = d["son_mau"] if d["son_mau"] in SON_MAU else "hong"
    return kq


def chuoi_tc(tc) -> str:
    tc = doc_tc(tc)
    return ",".join(f"{k}={tc[k]}" for k in KHOA)


def co_hieu_ung(tc) -> bool:
    tc = doc_tc(tc)
    return any(tc[k] for k in ("trang", "son", "suc_song", "sang", "tuong_phan", "nhiet"))


def loc_toan_khung(tc) -> str:
    """Chuỗi filter ffmpeg cho phần toàn khung (sức sống, sáng, tương phản, nhiệt độ màu); '' nếu đều 0.
    colortemperature: số Kelvin THẤP hơn = ảnh ấm hơn (đo thử: 4500K -> Cr tăng, Cb giảm), nên dương = ấm -> trừ."""
    tc = doc_tc(tc)
    f = []
    if tc["suc_song"]:
        f.append(f"vibrance=intensity={tc['suc_song'] / 100 * 1.0:.3f}")
    if tc["sang"] or tc["tuong_phan"]:
        f.append(f"eq=brightness={tc['sang'] / 100 * 0.25:.3f}:contrast={1 + tc['tuong_phan'] / 100 * 0.6:.3f}")
    if tc["nhiet"]:
        f.append(f"colortemperature=temperature={6500 - tc['nhiet'] * 20:.0f}")
    return ",".join(f)


def ma_cache(src: Path, giay: float | None, tc) -> str:
    """Tên cache: nguồn (tên+kích thước+mtime) + số giây + tham số -> 10 ký tự hex."""
    st = src.stat()
    s = f"{src.name}|{st.st_size}|{st.st_mtime_ns}|{giay or 0:.2f}|{chuoi_tc(tc)}"
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


# ================================================================ điểm mốc (mediapipe)
def ensure_model() -> Path:
    if not MODEL.exists():
        print(f"Tải model Face Landmarker về {MODEL} ...", flush=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL)
    return MODEL


class TimMoc:
    """Bọc MediaPipe FaceLandmarker. che_do 'anh' (từng ảnh rời) | 'video' (theo dõi liên tục, nhanh + mượt)."""

    def __init__(self, che_do: str = "anh"):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_py
        from mediapipe.tasks.python import vision
        self.mp, self.vision = mp, vision
        rm = vision.RunningMode.VIDEO if che_do == "video" else vision.RunningMode.IMAGE
        opts = vision.FaceLandmarkerOptions(
            base_options=mp_py.BaseOptions(model_asset_path=str(ensure_model())), running_mode=rm, num_faces=1,
            min_face_detection_confidence=0.5, min_face_presence_confidence=0.5, min_tracking_confidence=0.5)
        self.lm = vision.FaceLandmarker.create_from_options(opts)
        self.che_do = che_do
        self.ts = 0

    def tim(self, bgr, ts_ms: int | None = None):
        """-> mảng (478, 2) pixel float32 hoặc None. Dò ở ảnh thu nhỏ (cạnh dài ~960) cho nhanh rồi nhân lại."""
        H, W = bgr.shape[:2]
        ti_le = min(1.0, 960 / max(W, H))
        nho = cv2.resize(bgr, None, fx=ti_le, fy=ti_le, interpolation=cv2.INTER_AREA) if ti_le < 1 else bgr
        rgb = np.ascontiguousarray(cv2.cvtColor(nho, cv2.COLOR_BGR2RGB))
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        if self.che_do == "video":
            if ts_ms is None:
                ts_ms = self.ts
            ts_ms = max(int(ts_ms), self.ts)           # mediapipe đòi mốc thời gian tăng dần
            self.ts = ts_ms + 1
            kq = self.lm.detect_for_video(img, ts_ms)
        else:
            kq = self.lm.detect(img)
        if not kq.face_landmarks:
            return None
        return np.array([(p.x * W, p.y * H) for p in kq.face_landmarks[0]], np.float32)

    def dong(self):
        try:
            self.lm.close()
        except Exception:   # noqa: BLE001
            pass


# ================================================================ mặt nạ + áp hiệu ứng (numpy/cv2)
def _poly(pts, idx, dx=0.0, dy=0.0):
    return np.round(pts[idx] - (dx, dy)).astype(np.int32).reshape(-1, 1, 2)


def vien_mat(pts):
    """Đa giác mặt = viền MediaPipe, phần trên đường mắt kéo lên thêm TRAN_THEM×chiều cao mặt (đỉnh trán lên
    nhiều nhất, hai bên thái dương ít dần) vì viền gốc dừng dưới chân tóc; cũng trả về (fw, fh) của viền gốc."""
    ov = pts[FACE_OVAL].copy()
    fw, fh = float(np.ptp(ov[:, 0])), float(np.ptp(ov[:, 1]))
    mat_y = float((pts[LEFT_EYE][:, 1].mean() + pts[RIGHT_EYE][:, 1].mean()) / 2)
    dinh_y = float(ov[:, 1].min())
    tren = ov[:, 1] < mat_y
    t = (mat_y - ov[tren, 1]) / max(mat_y - dinh_y, 1.0)      # 0 ở ngang mắt .. 1 ở đỉnh trán
    ov[tren, 1] -= t * fh * TRAN_THEM
    return ov, (fw, fh)


def vung_mat(pts, W, H):
    """ROI (x0, y0, x1, y1) bao mặt (đã kéo trán) + cổ, nới 15% ngang / 12% dọc; kích thước mặt (fw, fh)."""
    ov, (fw, fh) = vien_mat(pts)
    x0, y0 = ov.min(axis=0)
    x1, y1 = ov.max(axis=0)
    y1 += fh * 0.5                       # thêm cổ
    px, py = fw * 0.15, fh * 0.12
    x0, y0 = int(max(0, x0 - px)), int(max(0, y0 - py))
    x1, y1 = int(min(W, x1 + px)), int(min(H, y1 + py))
    return (x0, y0, x1, y1), (fw, fh)


def mat_na(pts, roi, kt_mat, ycc_roi):
    """-> (mặt nạ da, mặt nạ môi) float32 0..1 trong ROI. Da = bầu dục mặt + cổ, trừ mắt/lông mày/khoang miệng,
    nhân cổng màu da (YCrCb) để loại gọng kính, tóc, áo. Môi = viền ngoài trừ viền trong (răng)."""
    x0, y0, x1, y1 = roi
    h, w = y1 - y0, x1 - x0
    fw, fh = kt_mat
    da = np.zeros((h, w), np.uint8)
    ov, _ = vien_mat(pts)
    cv2.fillPoly(da, [np.round(ov - (x0, y0)).astype(np.int32).reshape(-1, 1, 2)], 255)
    jaw = pts[JAW] - (x0, y0)
    co = np.concatenate([jaw, (jaw + (0, fh * 0.45))[::-1]])          # hàm kéo xuống thành cổ
    cv2.fillPoly(da, [np.round(co).astype(np.int32).reshape(-1, 1, 2)], 255)
    tru = np.zeros((h, w), np.uint8)
    for idx in (LEFT_EYE, RIGHT_EYE, LEFT_BROW, RIGHT_BROW, LIPS_INNER):
        cv2.fillPoly(tru, [_poly(pts, idx, x0, y0)], 255)
    k = max(3, int(fw * 0.03) | 1)
    tru = cv2.dilate(tru, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    da[tru > 0] = 0
    da = cv2.GaussianBlur(da, (0, 0), max(1.0, fw * 0.02)).astype(np.float32) / 255.0
    # cổng màu da: Cr 134..176, Cb 72..130, Y 50..80 mờ dần (mép tóc Y~65 Cr~142 chỉ được nửa; tóc Y<45 loại hẳn)
    Y, Cr, Cb = ycc_roi[..., 0], ycc_roi[..., 1], ycc_roi[..., 2]
    cong = (np.clip((Cr - 134) / 8, 0, 1) * np.clip((176 - Cr) / 8, 0, 1)
            * np.clip((Cb - 72) / 8, 0, 1) * np.clip((130 - Cb) / 8, 0, 1) * np.clip((Y - 50) / 30, 0, 1))
    da *= cv2.GaussianBlur(cong.astype(np.float32), (0, 0), 2.0)
    moi = np.zeros((h, w), np.uint8)
    cv2.fillPoly(moi, [_poly(pts, LIPS_OUTER, x0, y0)], 255)
    cv2.fillPoly(moi, [_poly(pts, LIPS_INNER, x0, y0)], 0)
    moi = cv2.GaussianBlur(moi, (0, 0), max(1.0, fw * 0.012)).astype(np.float32) / 255.0
    sac = np.hypot(Cr - 128, Cb - 128)
    moi *= np.clip((sac - 5) / 6, 0, 1) * np.clip((205 - Y) / 25, 0, 1)      # bỏ răng (sáng, không màu)
    return da, moi


class ApDung:
    """Áp làm trắng da + son môi theo tham số (chỉ vùng mặt). Phần toàn khung xem loc_toan_khung()."""

    def __init__(self, tc):
        self.tc = tc = doc_tc(tc)
        self.st, self.ss = tc["trang"] / 100.0, tc["son"] / 100.0
        self.son = SON_MAU[tc["son_mau"]]
        gamma = 1 - 0.45 * self.st            # nâng tông giữa: 50% -> 0.5 thành 0.58, 100% -> 0.68
        self.lut_trang = (255 * (np.arange(256, dtype=np.float32) / 255) ** gamma).astype(np.float32)

    def ap(self, bgr, pts):
        """bgr uint8 + mốc (478,2) hoặc None -> ảnh mới đã làm trắng/son (không đổi mảng vào)."""
        if pts is None or (self.st <= 0 and self.ss <= 0):
            return bgr
        H, W = bgr.shape[:2]
        roi, kt = vung_mat(pts, W, H)
        x0, y0, x1, y1 = roi
        if x1 - x0 <= 8 or y1 - y0 <= 8:
            return bgr
        out = bgr.copy()
        v = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2YCrCb).astype(np.float32)
        da, moi = mat_na(pts, roi, kt, v)
        Y, Cr, Cb = v[..., 0], v[..., 1], v[..., 2]
        if self.st > 0:
            Yw = self.lut_trang[np.clip(Y, 0, 255).astype(np.uint8)]
            Y += (Yw - Y) * da
            k = 0.3 * self.st                 # bớt bão hòa da (bớt đỏ/vàng)
            Cr -= (Cr - 128) * k * da
            Cb -= (Cb - 128) * k * da
        if self.ss > 0:
            w = moi * self.ss
            dcr, dcb, ymul = self.son
            Cr += (Cr - 128) * 0.3 * w + dcr * w
            Cb += dcb * w
            Y *= 1 - (1 - ymul) * w
        out[y0:y1, x0:x1] = cv2.cvtColor(np.clip(v, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR)
        return out


# ================================================================ ảnh / video
def doc_anh(p: Path):
    img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"Không đọc được ảnh: {p}")
    return img


def ghi_anh(p: Path, img, chat_luong: int = 92):
    ok, buf = cv2.imencode(p.suffix or ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, chat_luong])
    if not ok:
        sys.exit(f"Không ghi được ảnh: {p}")
    buf.tofile(str(p))


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("Không thấy ffmpeg trên PATH.")
    return exe


def ap_toan_khung_anh(img, tc):
    """Áp phần toàn khung (vibrance/eq/colortemperature) lên MỘT ảnh bằng ffmpeg — đúng filter sẽ dùng khi mã hóa."""
    vf = loc_toan_khung(tc)
    if not vf:
        return img
    with tempfile.TemporaryDirectory() as td:
        vao, ra = Path(td) / "vao.png", Path(td) / "ra.png"
        cv2.imwrite(str(vao), img)
        r = subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", str(vao), "-vf", vf, "-frames:v", "1", str(ra)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if r.returncode != 0 or not ra.exists():
            raise RuntimeError("ffmpeg lỗi: " + (r.stderr or "")[-400:])
        return cv2.imread(str(ra))


def lam_dep_anh(goc, pts, tc):
    """Ảnh đã làm đẹp đầy đủ (da/môi numpy -> toàn khung ffmpeg), đúng thứ tự khi xử lý video."""
    return ap_toan_khung_anh(ApDung(tc).ap(goc, pts), tc)


def xem_thu(goc, pts, tc, rong: int = 760):
    """Ảnh ghép cho tab Làm đẹp: hàng trên = cận mặt (gốc | chỉnh), hàng dưới = cả khung (gốc | chỉnh)."""
    ra = lam_dep_anh(goc, pts, tc)
    H, W = goc.shape[:2]
    nua = rong // 2
    if pts is not None:
        (x0, y0, x1, y1), (fw, fh) = vung_mat(pts, W, H)
        y1 = min(H, int(y1 - fh * 0.25))
        cat = [goc[y0:y1, x0:x1], ra[y0:y1, x0:x1]]
    else:
        cat = [goc[: H // 2], ra[: H // 2]]

    def _vua(img, w):
        h = max(1, int(round(img.shape[0] * w / img.shape[1])))
        return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    tren = np.concatenate([_vua(c, nua) for c in cat], axis=1)
    duoi = np.concatenate([_vua(goc, nua), _vua(ra, nua)], axis=1)
    vach = np.full((6, nua * 2, 3), 255, np.uint8)
    return np.concatenate([tren, vach, duoi], axis=0)


def xu_ly_video(src: Path, ra: Path, tc, giay: float | None = None, crf: int = 16, log=print) -> dict:
    """Đọc từng khung, dò mốc, áp da/môi, bơm rawvideo sang ffmpeg (libx264 crf 16 + filter toàn khung, giữ tiếng gốc)."""
    tc = doc_tc(tc)
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        sys.exit(f"Không mở được video: {src}")
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    n_max = int(giay * fps) + 1 if giay else n
    if n and n_max > n:
        n_max = n
    ra.parent.mkdir(parents=True, exist_ok=True)
    tam = ra.with_name(ra.stem + ".tmp.mp4")
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", f"{fps:.6f}", "-i", "-", "-i", str(src), "-map", "0:v:0", "-map", "1:a?"]
    vf = loc_toan_khung(tc)
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart"]
    if giay:
        cmd += ["-t", f"{giay:.3f}"]
    cmd.append(str(tam))
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    moc = TimMoc("video")
    ap = ApDung(tc)
    pts_cu, giu, k, mat, t0, bao = None, 0, 0, 0, time.time(), time.time()
    try:
        while not n_max or k < n_max:
            ok, frame = cap.read()
            if not ok:
                break
            pts = moc.tim(frame, int(k * 1000 / fps))
            if pts is not None:
                if pts_cu is not None and np.abs(pts - pts_cu).max() < 40:   # cùng vị trí -> làm mượt
                    pts = EMA * pts + (1 - EMA) * pts_cu
                pts_cu, giu, mat = pts, 0, mat + 1
            elif pts_cu is not None and giu < GIU_MOC_TOI_DA:
                pts, giu = pts_cu, giu + 1
            else:
                pts_cu = None
            enc.stdin.write(ap.ap(frame, pts).tobytes())
            k += 1
            if time.time() - bao > 3:
                bao = time.time()
                pct = f"{100 * k / n_max:.0f}%" if n_max else f"{k} khung"
                log(f"  làm đẹp {src.name}: {pct} ({k / (time.time() - t0):.1f} khung/s)")
    finally:
        cap.release()
        moc.dong()
        try:
            enc.stdin.close()
        except Exception:   # noqa: BLE001
            pass
    rc = enc.wait()
    err = enc.stderr.read().decode("utf-8", "replace").strip()
    if rc != 0 or not tam.exists():
        sys.exit(f"ffmpeg mã hóa lỗi ({rc}): {err[-800:]}")
    tam.replace(ra)
    return dict(khung=k, co_mat=mat, giay=round(time.time() - t0, 1), fps=round(k / max(time.time() - t0, 1e-6), 1))


# ================================================================ gọi từ venv khác
def python_lam_dep() -> str | None:
    """python có mediapipe: venv_lamdep cạnh thư mục dự án; không có -> None."""
    if VENV_PY.exists():
        return str(VENV_PY)
    try:
        import mediapipe  # noqa: F401
        return sys.executable
    except Exception:   # noqa: BLE001
        return None


def san_sang() -> tuple[bool, str]:
    """(có chạy được không, python hoặc lý do)."""
    py = python_lam_dep()
    if not py:
        pip = "venv_lamdep\\Scripts\\pip" if os.name == "nt" else "venv_lamdep/bin/pip"
        return False, ("Chưa có venv_lamdep (mediapipe). Tạo bằng: python -m venv venv_lamdep && "
                       f"{pip} install mediapipe (cạnh thư mục GoogleFlowGhepVideo)")
    if not shutil.which("ffmpeg"):
        return False, "Không thấy ffmpeg trên PATH."
    return True, py


def diem_moc_qua_subprocess(anh: Path, timeout: int = 120):
    """Gọi lam_dep.py --diem-moc bằng python của venv_lamdep -> (478,2) float32 hoặc None. Lỗi -> RuntimeError."""
    ok, py = san_sang()
    if not ok:
        raise RuntimeError(py)
    r = subprocess.run([py, str(Path(__file__).resolve()), "--diem-moc", str(anh)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env={**os.environ, **ENV_IM},
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-600:] or f"mã thoát {r.returncode}")
    dong = [x for x in r.stdout.splitlines() if x.strip().startswith(("[", "null"))]
    kq = json.loads(dong[-1]) if dong else None
    return np.array(kq, np.float32) if kq else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diem-moc", help="ảnh -> in JSON điểm mốc")
    ap.add_argument("--anh", help="ảnh vào (xem thử)")
    ap.add_argument("--video", help="video vào")
    ap.add_argument("--ra", help="file ra")
    ap.add_argument("--tc", default="", help="trang=..,son=..,son_mau=hong|do|cam,suc_song=..,sang=..,tuong_phan=..,nhiet=..")
    ap.add_argument("--giay", type=float, default=None, help="chỉ xử lý N giây đầu của video")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--ghep", action="store_true", help="với --anh: xuất ảnh ghép gốc|chỉnh thay vì ảnh đã chỉnh")
    a = ap.parse_args()
    tc = doc_tc(a.tc)
    if a.diem_moc:
        pts = TimMoc("anh").tim(doc_anh(Path(a.diem_moc)))
        print(json.dumps(None if pts is None else np.round(pts, 2).tolist()))
        return
    if a.anh:
        if not a.ra:
            sys.exit("--anh cần --ra")
        goc = doc_anh(Path(a.anh))
        pts = TimMoc("anh").tim(goc)
        print("mốc:", "không thấy mặt" if pts is None else f"{len(pts)} điểm")
        ghi_anh(Path(a.ra), xem_thu(goc, pts, tc) if a.ghep else lam_dep_anh(goc, pts, tc))
        print("ra:", a.ra)
        return
    if a.video:
        if not a.ra:
            sys.exit("--video cần --ra")
        kq = xu_ly_video(Path(a.video), Path(a.ra), tc, a.giay, a.crf)
        print(f"xong: {kq['khung']} khung ({kq['co_mat']} khung có mặt), {kq['giay']}s, {kq['fps']} khung/s -> {a.ra}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
