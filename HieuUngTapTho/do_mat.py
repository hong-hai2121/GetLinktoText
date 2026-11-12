"""Dò tâm khuôn mặt theo thời gian (YuNet) để hiệu ứng bám đúng chuyển động đầu thật.

Dùng: python do_mat.py <video> <t0> <t1> <fps> <ra.json>
Ra: [[t, x, y, độ_tin], ...] theo toạ độ khung gốc; khung không thấy mặt thì bỏ qua.
"""
import json, sys, subprocess
import numpy as np, cv2

MODEL = r"D:\Python\GetLinktoText\GoogleFlowGhepVideo\face_detection_yunet_2023mar.onnx"

def main(video, t0, t1, fps, out):
    t0, t1, fps = float(t0), float(t1), float(fps)
    W, H = 540, 960  # thu nhỏ một nửa cho nhanh
    cmd = ["ffmpeg", "-v", "error", "-ss", str(t0), "-t", str(t1 - t0), "-i", video,
           "-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    det = cv2.FaceDetectorYN.create(MODEL, "", (W, H), 0.5, 0.3, 5000)
    res, i = [], 0
    while True:
        buf = p.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        _, faces = det.detect(img)
        if faces is not None and len(faces):
            f = max(faces, key=lambda r: r[14])
            x, y, w, h = f[:4]
            res.append([round(t0 + i / fps, 3), round((x + w / 2) * 2, 1), round((y + h / 2) * 2, 1), round(float(f[14]), 3)])
        i += 1
    json.dump(res, open(out, "w"))
    print(f"{len(res)}/{i} khung thấy mặt")

if __name__ == "__main__":
    main(*sys.argv[1:6])
