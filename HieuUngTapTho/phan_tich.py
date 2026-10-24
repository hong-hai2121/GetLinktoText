"""Phân tích video bài tập mèo-bò (cat-cow): tư thế + mặt nạ người từng khung → đường lưng, đường bụng, độ cao đầu.

Chạy bằng python của venv_lamdep (có mediapipe):
    ..\venv_lamdep\Scripts\python.exe phan_tich.py <video> <ra.npz> [--model <pose_landmarker.task>] [--kiem-tra <thư mục>]

Kết quả .npz (mỗi mảng dài = số khung):
    nose, mouth, ear, eye, shoulder, hip, knee, elbow, wrist, index, ankle, heel, foot : (N,2) toạ độ pixel (x,y); NaN nếu không thấy
    back_coef, belly_coef   : (N,3) hệ số parabol y = a x² + b x + c theo pixel; NaN nếu không đủ điểm
    back_x0, back_x1, belly_x0, belly_x1 : khoảng x hợp lệ của mỗi đường
    ok : (N,) 1 nếu khung có tư thế
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
MODEL_PATH = HERE / "pose_landmarker_heavy.task"

# chỉ số điểm mốc MediaPipe Pose
NOSE, L_EAR, R_EAR, MOUTH_L, MOUTH_R = 0, 7, 8, 9, 10
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 11, 12, 13, 14, 15, 16
L_HIP, R_HIP, L_KNEE, R_KNEE = 23, 24, 25, 26
L_EYE, R_EYE, L_IDX, R_IDX = 2, 5, 19, 20
L_ANK, R_ANK, L_HEEL, R_HEEL, L_FOOT, R_FOOT = 27, 28, 29, 30, 31, 32


def ensure_model(path: Path) -> Path:
    if not path.exists():
        print(f"Tải model pose → {path}", flush=True)
        urllib.request.urlretrieve(MODEL_URL, path)
    return path


def diem(lms, i, w, h):
    p = lms[i]
    return (p.x * w, p.y * h, p.visibility)


def diem_tot(lms, a, b, w, h):
    """Chọn điểm bên trái/phải nhìn rõ hơn (góc nhìn ngang nên hai bên chồng nhau)."""
    pa, pb = diem(lms, a, w, h), diem(lms, b, w, h)
    if pa[2] < 0.3 and pb[2] < 0.3:
        return (np.nan, np.nan)
    if abs(pa[2] - pb[2]) < 0.15:
        return ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    return (pa[0], pa[1]) if pa[2] > pb[2] else (pb[0], pb[1])


def fit_parabol(xs, ys):
    if len(xs) < 8:
        return np.array([np.nan, np.nan, np.nan])
    return np.polyfit(xs, ys, 2)


def duong_lung_bung(mask, sh, hip, w, h):
    """Từ mặt nạ người lấy đường lưng (mép trên thân) và đường bụng (mép dưới thân, chỗ không bị tay/đùi che)."""
    nan3 = np.array([np.nan] * 3)
    if np.isnan(sh[0]) or np.isnan(hip[0]):
        return nan3, nan3, (np.nan, np.nan), (np.nan, np.nan)
    x_a, x_b = sorted([sh[0], hip[0]])
    L = x_b - x_a
    if L < 50:
        return nan3, nan3, (np.nan, np.nan), (np.nan, np.nan)
    m = mask > 0.5
    y_mid = (sh[1] + hip[1]) / 2
    # ---- lưng: mép trên của mặt nạ trong khoảng x giữa vai và hông (bỏ gần vai vì cổ nhô lên)
    bx0 = int(x_a + 0.08 * L)
    bx1 = int(x_b + 0.05 * L)
    y_top_lim = max(0, int(y_mid - 0.9 * L))
    xs, ys = [], []
    for x in range(max(0, bx0), min(w - 1, bx1), 4):
        col = m[y_top_lim:int(y_mid), x]
        idx = np.flatnonzero(col)
        if idx.size:
            xs.append(x)
            ys.append(y_top_lim + idx[0])
    back = fit_parabol(np.array(xs, float), np.array(ys, float))
    bxr = (float(bx0), float(bx1)) if xs else (np.nan, np.nan)
    # ---- bụng: từ giữa thân quét xuống tới khi hết mặt nạ; cột nào tay/đùi che (chạm tới sàn) thì loại
    ux0 = int(x_a + 0.18 * L)
    ux1 = int(x_b - 0.22 * L)
    y_bot_lim = min(h - 1, int(y_mid + 1.2 * L))
    xs2, ys2 = [], []
    for x in range(max(0, ux0), min(w - 1, ux1), 4):
        col = m[int(y_mid):y_bot_lim, x]
        idx = np.flatnonzero(~col)
        if idx.size:
            xs2.append(x)
            ys2.append(int(y_mid) + idx[0])
    xs2, ys2 = np.array(xs2, float), np.array(ys2, float)
    if xs2.size >= 8:
        med = np.median(ys2)
        keep = np.abs(ys2 - med) < 0.25 * L          # loại cột bị tay/đùi che
        xs2, ys2 = xs2[keep], ys2[keep]
    belly = fit_parabol(xs2, ys2)
    uxr = (float(xs2.min()), float(xs2.max())) if xs2.size >= 8 else (np.nan, np.nan)
    return back, belly, bxr, uxr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("ra")
    ap.add_argument("--model", default=str(MODEL_PATH))
    ap.add_argument("--kiem-tra", default=None, help="thư mục ghi ảnh kiểm tra mặt nạ")
    ap.add_argument("--moi", type=int, default=60, help="ghi ảnh kiểm tra mỗi N khung")
    a = ap.parse_args()

    import mediapipe as mp
    from mediapipe.tasks import python as mp_py
    from mediapipe.tasks.python import vision

    model = ensure_model(Path(a.model))
    opts = vision.PoseLandmarkerOptions(
        base_options=mp_py.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        output_segmentation_masks=True,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    lm = vision.PoseLandmarker.create_from_options(opts)

    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"{w}x{h} {fps:.2f}fps {n} khung", flush=True)

    keys = ["nose", "mouth", "ear", "eye", "shoulder", "hip", "knee", "elbow", "wrist", "index", "ankle", "heel", "foot"]
    out = {k: np.full((n, 2), np.nan) for k in keys}
    out["back_coef"] = np.full((n, 3), np.nan)
    out["belly_coef"] = np.full((n, 3), np.nan)
    out["back_x0"] = np.full(n, np.nan); out["back_x1"] = np.full(n, np.nan)
    out["belly_x0"] = np.full(n, np.nan); out["belly_x1"] = np.full(n, np.nan)
    out["ok"] = np.zeros(n)
    kt = Path(a.kiem_tra) if a.kiem_tra else None
    if kt:
        kt.mkdir(parents=True, exist_ok=True)

    i = 0
    while True:
        ret, bgr = cap.read()
        if not ret or i >= n:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = lm.detect_for_video(img, int(i * 1000 / fps))
        if res.pose_landmarks:
            lms = res.pose_landmarks[0]
            out["ok"][i] = 1
            out["nose"][i] = diem(lms, NOSE, w, h)[:2]
            out["mouth"][i] = diem_tot(lms, MOUTH_L, MOUTH_R, w, h)
            out["ear"][i] = diem_tot(lms, L_EAR, R_EAR, w, h)
            out["shoulder"][i] = diem_tot(lms, L_SH, R_SH, w, h)
            out["hip"][i] = diem_tot(lms, L_HIP, R_HIP, w, h)
            out["knee"][i] = diem_tot(lms, L_KNEE, R_KNEE, w, h)
            out["elbow"][i] = diem_tot(lms, L_EL, R_EL, w, h)
            out["wrist"][i] = diem_tot(lms, L_WR, R_WR, w, h)
            out["eye"][i] = diem_tot(lms, L_EYE, R_EYE, w, h)
            out["index"][i] = diem_tot(lms, L_IDX, R_IDX, w, h)
            out["ankle"][i] = diem_tot(lms, L_ANK, R_ANK, w, h)
            out["heel"][i] = diem_tot(lms, L_HEEL, R_HEEL, w, h)
            out["foot"][i] = diem_tot(lms, L_FOOT, R_FOOT, w, h)
            mask = res.segmentation_masks[0].numpy_view() if res.segmentation_masks else None
            if mask is not None:
                back, belly, bxr, uxr = duong_lung_bung(mask, out["shoulder"][i], out["hip"][i], w, h)
                out["back_coef"][i] = back
                out["belly_coef"][i] = belly
                out["back_x0"][i], out["back_x1"][i] = bxr
                out["belly_x0"][i], out["belly_x1"][i] = uxr
                if kt and i % a.moi == 0:
                    vis = bgr.copy()
                    edge = (mask > 0.5).astype(np.uint8)
                    cnts, _ = cv2.findContours(edge, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(vis, cnts, -1, (0, 255, 0), 3)
                    for k, col in [("nose", (0, 0, 255)), ("shoulder", (255, 0, 0)), ("hip", (255, 0, 255)),
                                   ("knee", (0, 255, 255)), ("elbow", (255, 255, 0)), ("mouth", (0, 128, 255)),
                                   ("wrist", (0, 255, 0)), ("index", (128, 255, 128)), ("heel", (255, 128, 0)),
                                   ("eye", (255, 255, 255))]:
                        p = out[k][i]
                        if not np.isnan(p[0]):
                            cv2.circle(vis, (int(p[0]), int(p[1])), 12, col, -1)
                    for coef, xr, col in [(back, bxr, (255, 0, 0)), (belly, uxr, (0, 165, 255))]:
                        if not np.isnan(coef[0]) and not np.isnan(xr[0]):
                            xs = np.linspace(xr[0], xr[1], 60)
                            ys = np.polyval(coef, xs)
                            pts = np.stack([xs, ys], 1).astype(np.int32).reshape(-1, 1, 2)
                            cv2.polylines(vis, [pts], False, col, 6)
                    cv2.imwrite(str(kt / f"kt_{i:04d}.jpg"), cv2.resize(vis, (w // 2, h // 2)))
        if i % 100 == 0:
            print(f"  khung {i}/{n}", flush=True)
        i += 1
    cap.release()
    out["fps"] = np.array(fps)
    out["size"] = np.array([w, h])
    np.savez(a.ra, **out)
    print(f"Xong: {int(out['ok'].sum())}/{n} khung có tư thế → {a.ra}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
