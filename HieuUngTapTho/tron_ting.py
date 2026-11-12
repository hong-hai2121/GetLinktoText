"""Tạo tiếng "ting" ngắn tại các mốc hiệu ứng chữ rồi trộn vào tiếng gốc.

Dùng: python tron_ting.py <moc.json> <video_tieng_goc> <video_hinh> <file_ra.mp4>
moc.json theo mẫu remotion/src/lung01.json (intro, ex, cues).
"""
import json, subprocess, sys, wave, tempfile, os
import numpy as np

SR = 48000

def chuong(f0, dai=0.9, to=1.0):
    t = np.arange(int(SR * dai)) / SR
    s = (np.sin(2 * np.pi * f0 * t) * np.exp(-6 * t)
         + 0.45 * np.sin(2 * np.pi * f0 * 2.0 * t) * np.exp(-9 * t)
         + 0.2 * np.sin(2 * np.pi * f0 * 3.01 * t) * np.exp(-13 * t))
    s *= np.minimum(1, t / 0.003)  # chống tiếng tách đầu
    return to * s / np.abs(s).max()

def main(moc, goc, hinh, ra):
    d = json.load(open(moc, encoding="utf-8"))
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", goc]).decode().strip())
    tr = np.zeros(int(SR * (dur + 1)))

    def dat(t, s):
        i = int(t * SR)
        n = min(len(s), len(tr) - i)
        tr[i:i + n] += s[:n]

    if d.get("title_ting", True):
        dat(0.2, chuong(1047, 1.4, 0.8) + chuong(1568, 1.4, 0.6))  # tiêu đề
    for it in d["intro"]:
        dat(it["t"], chuong(2093, 0.8, 0.55))
    for ex in d["ex"]:  # ting-ting khi sang động tác mới
        dat(ex["start"], chuong(1568, 0.8, 0.65))
        dat(ex["start"] + 0.13, chuong(2093, 0.9, 0.65))
    for c in d["cues"]:
        f0 = {"ok": 2637, "no": 880}.get(c.get("kind"), 2093)
        dat(c["t"], chuong(f0, 0.7, 0.5))

    tr = np.clip(tr, -1, 1)
    wav = os.path.join(tempfile.gettempdir(), "ting_track.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((tr * 32767).astype("<i2").tobytes())
    subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-i", hinh, "-i", goc, "-i", wav,
        "-filter_complex", "[1:a]aresample=48000[g];[2:a]aformat=channel_layouts=stereo[s];"
                           "[g][s]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", ra])
    print("xong:", ra)

if __name__ == "__main__":
    main(*sys.argv[1:5])
