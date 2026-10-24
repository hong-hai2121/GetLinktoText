"""Đo nhịp phồng/xẹp của bụng (người nằm ngửa, quay ngang) bằng dòng quang học dọc trong một vùng bụng,
rồi tách các pha HÍT / THỞ RA để hiệu ứng thở khớp đúng nhịp thật của người tập.

    python do_bung.py <video> <ra.npz> --vung x0,y0,x1,y1 [--nen x0,y0,x1,y1] [--ve <ảnh.png>]

    --vung : khung chứa mép trên bụng (có một dải tường phía trên để có biên ảnh)
    --nen  : vùng nền đứng yên (rèm/tường) để trừ rung máy quay

Kết quả .npz: bung (px, DƯƠNG = bụng phồng, đã làm mượt), v (px/s), fps, vung
In ra danh sách pha gợi ý để chép vào kịch bản (hiệu ứng "tho_bung").
"""
from __future__ import annotations

import argparse

import cv2
import numpy as np


def dong_doc(cap, rois):
    prev = {}
    dy = {k: [] for k in rois}
    while True:
        ok, f = cap.read()
        if not ok:
            break
        for k, (x0, y0, x1, y1) in rois.items():
            g = cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)
            if k not in prev:
                dy[k].append(0.0)
            else:
                fl = cv2.calcOpticalFlowFarneback(prev[k], g, None, 0.5, 3, 21, 3, 5, 1.1, 0)
                w = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
                w = w * (w > np.percentile(w, 80))                 # chỉ lấy chỗ có biên ngang (mép áo)
                dy[k].append(float((fl[..., 1] * w).sum() / (w.sum() + 1e-6)) * 2)
            prev[k] = g
    return {k: np.array(v) for k, v in dy.items()}


def gauss(a, sigma):
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(a, r, mode="edge"), k, mode="valid")


def tach_pha(t, v, len_in=0.6, len_out=-0.45, min_in=0.25, min_out=0.8):
    """Đoạn v > len_in = HÍT, v < len_out = THỞ RA; đếm HÍT 1/2 trong một chu kỳ (reset sau mỗi lần thở ra)."""
    st = np.zeros(len(v), int)
    st[v > len_in] = 1
    st[v < len_out] = -1
    segs = []
    i = 0
    while i < len(st):
        j = i
        while j + 1 < len(st) and st[j + 1] == st[i]:
            j += 1
        if st[i] != 0:
            segs.append([float(t[i]), float(t[j]), int(st[i])])
        i = j + 1
    # gộp đoạn cùng loại cách nhau rất ngắn, bỏ đoạn quá ngắn
    merged = []
    for s in segs:
        if merged and merged[-1][2] == s[2] and s[0] - merged[-1][1] < (0.12 if s[2] > 0 else 0.4):
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    merged = [s for s in merged if (s[1] - s[0]) >= (min_in if s[2] > 0 else min_out)]
    out, n_in = [], 0
    for s in merged:
        if s[2] > 0:
            n_in += 1
            out.append([round(s[0], 2), round(s[1], 2), f"hit{n_in}"])
        else:
            out.append([round(s[0], 2), round(s[1], 2), "tho"])
            n_in = 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("ra")
    ap.add_argument("--vung", required=True)
    ap.add_argument("--nen", default=None)
    ap.add_argument("--ve", default=None)
    a = ap.parse_args()
    rois = {"bung": tuple(int(x) for x in a.vung.split(","))}
    if a.nen:
        rois["nen"] = tuple(int(x) for x in a.nen.split(","))
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dy = dong_doc(cap, rois)
    cap.release()
    d = dy["bung"] - (dy["nen"] if "nen" in dy else 0)
    raw = -np.cumsum(d)                                            # mép đi lên (y giảm) = phồng → dương
    bung = gauss(raw, 3)
    v = np.gradient(gauss(raw, 5)) * fps
    t = np.arange(len(bung)) / fps
    pha = tach_pha(t, v)
    np.savez(a.ra, bung=bung, v=v, fps=np.array(fps), vung=np.array(rois["bung"]))
    print(f"{len(bung)} khung; bụng {bung.min():.2f}..{bung.max():.2f} px")
    print("pha gợi ý:", pha)
    if a.ve:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(16, 6), sharex=True)
        ax[0].plot(t, bung)
        ax[0].set_ylabel("bụng (px, + phồng)")
        ax[1].plot(t, v)
        ax[1].axhline(0.6, color="g", ls="--")
        ax[1].axhline(-0.45, color="r", ls="--")
        ax[1].set_ylabel("tốc độ (px/s)")
        for s0, s1, k in pha:
            col = "tab:blue" if k.startswith("hit") else "tab:orange"
            for q in ax:
                q.axvspan(s0, s1, color=col, alpha=0.2)
            ax[0].text((s0 + s1) / 2, bung.max(), k, ha="center", va="top")
        for q in ax:
            q.grid(True)
            q.set_xticks(np.arange(0, t[-1] + 1, 1))
        plt.tight_layout()
        plt.savefig(a.ve, dpi=70)


if __name__ == "__main__":
    main()
