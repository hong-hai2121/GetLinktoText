import os
import sys
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox

# =======================
# CONFIG
# =======================
CHANNEL_NAME = "CatSubz"

OUTPUT_DIR = r"D:\Python\GetLinktoText\SourceTruyen\XuLyVideo\videodoc"

# Output format (Shorts-like)
OUT_W = 1080
OUT_H = 1920
OUT_FPS = 30

# Header area
HEADER_H = 220
HEADER_ALPHA = 0.55  # 0..1

# Text style: bold + border
TEXT_SIZE = 74
TEXT_COLOR = "white"              # or "#FFD400"
TEXT_BORDER_W = 5
TEXT_BORDER_COLOR = "black@0.65"
TEXT_SHADOW_X = 2
TEXT_SHADOW_Y = 2
TEXT_SHADOW_COLOR = "black@0.65"

# Background blur tuning (speed-friendly)
# boxblur is much faster than gblur
USE_BOXBLUR = True
BOXBLUR_LUMA = 10     # 8..14 recommended. smaller = faster
BOXBLUR_CHROMA = 1
BG_DIM = 0.12         # darken background a bit (0..0.3)

# Encoding
GPU_MODE = "auto"     # auto / nvenc / qsv / amf / cpu
GPU_CODEC = "hevc"    # "hevc" to match CapCut screenshot; can switch to "h264"
GPU_CQ = 23           # lower=better quality, slower/bigger

CPU_FALLBACK = "libx264"  # libx264 (faster) or libx265 (smaller)
CPU_CRF = 20              # for libx264; if libx265, typical 22-28

AAC_BITRATE = "192k"
# =======================


def tool_exists(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def ffmpeg_has_encoder(enc: str) -> bool:
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        return enc.lower() in p.stdout.lower()
    except Exception:
        return False


def escape_drawtext(text: str) -> str:
    # Escape for FFmpeg drawtext
    t = text.replace("\\", "\\\\")
    t = t.replace(":", r"\:")
    t = t.replace("'", r"\'")
    t = t.replace("%", r"\%")
    t = t.replace("\n", r"\n")
    return t


def pick_input_video() -> Optional[Path]:
    root = tk.Tk()
    root.withdraw()
    root.update()
    fp = filedialog.askopenfilename(
        title="Chọn video MP4 cần chuyển sang dọc (9:16)",
        filetypes=[("MP4 Video", "*.mp4"), ("All files", "*.*")]
    )
    root.destroy()
    if not fp:
        return None
    return Path(fp)


def unique_outpath(out_dir: Path, base_name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate = out_dir / base_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    i = 1
    while True:
        c = out_dir / f"{stem}_{i}{suffix}"
        if not c.exists():
            return c
        i += 1


def find_windows_vietnamese_fontfile() -> str:
    """
    Pick a Vietnamese-capable bold font that exists by default on Windows.
    We try common built-in fonts in priority order.
    """
    win_fonts = Path(r"C:\Windows\Fonts")
    candidates = [
        "segoeuib.ttf",   # Segoe UI Bold
        "seguisb.ttf",    # Segoe UI Semibold
        "segoeui.ttf",    # Segoe UI Regular
        "arialbd.ttf",    # Arial Bold
        "arial.ttf",      # Arial
        "tahomabd.ttf",   # Tahoma Bold
        "tahoma.ttf",     # Tahoma
        "timesbd.ttf",    # Times New Roman Bold
        "times.ttf",      # Times New Roman
    ]
    for name in candidates:
        p = win_fonts / name
        if p.exists():
            return str(p)
    # If not found, return empty -> ffmpeg default font
    return ""


def pick_gpu_encoder() -> Optional[str]:
    """
    Return encoder name for GPU if available, else None.
    """
    mode = (GPU_MODE or "auto").lower().strip()
    codec = (GPU_CODEC or "hevc").lower().strip()

    if codec not in ("hevc", "h264"):
        codec = "hevc"

    # map
    if codec == "hevc":
        pref = [("nvenc", "hevc_nvenc"), ("qsv", "hevc_qsv"), ("amf", "hevc_amf")]
    else:
        pref = [("nvenc", "h264_nvenc"), ("qsv", "h264_qsv"), ("amf", "h264_amf")]

    if mode == "cpu":
        return None

    if mode in ("nvenc", "qsv", "amf"):
        for key, enc in pref:
            if key == mode:
                return enc if ffmpeg_has_encoder(enc) else None
        return None

    # auto
    for _, enc in pref:
        if ffmpeg_has_encoder(enc):
            return enc
    return None


def build_filter_complex(fontfile: str) -> str:
    W, H = OUT_W, OUT_H
    header_h = HEADER_H

    channel_text = escape_drawtext(CHANNEL_NAME)
    fontfile_esc = escape_drawtext(fontfile) if fontfile else ""

    overlay_y = f"{header_h}+(H-{header_h}-h)/2"

    # Background: fill 9:16 then blur + dim
    if USE_BOXBLUR:
        blur_part = (
            f"boxblur=luma_radius={BOXBLUR_LUMA}:luma_power=1:"
            f"chroma_radius={BOXBLUR_CHROMA}:chroma_power=1"
        )
    else:
        # Not recommended for speed, but kept as fallback
        blur_part = "gblur=sigma=18:steps=2"

    bg_chain = (
        f"[0:v]"
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},"
        f"{blur_part},"
        f"eq=brightness=-{BG_DIM}"
        f"[bg]"
    )

    # Foreground: scale to fit width, keep AR
    fg_chain = f"[0:v]scale={W}:-2:force_original_aspect_ratio=decrease[fg]"

    # Header bar
    header_src = f"color=c=black@{HEADER_ALPHA}:s={W}x{header_h}[hdr]"

    # Compose bg + fg, then header
    comp_base = f"[bg][fg]overlay=x=(W-w)/2:y={overlay_y}:format=auto[base]"
    comp_hdr = f"[base][hdr]overlay=x=0:y=0:format=auto[with_hdr]"

    # Draw text (bold font via fontfile), border, shadow, force FPS
    font_part = f":fontfile='{fontfile_esc}'" if fontfile_esc else ""

    text_draw = (
        f"[with_hdr]drawtext=text='{channel_text}'"
        f"{font_part}"
        f":fontsize={TEXT_SIZE}"
        f":fontcolor={TEXT_COLOR}"
        f":borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}"
        f":shadowx={TEXT_SHADOW_X}:shadowy={TEXT_SHADOW_Y}:shadowcolor={TEXT_SHADOW_COLOR}"
        f":x=(w-text_w)/2"
        f":y=({header_h}-text_h)/2"
        f",fps={OUT_FPS}"
        f"[vout]"
    )

    return ";".join([bg_chain, fg_chain, header_src, comp_base, comp_hdr, text_draw])


def build_cmd(in_path: Path, out_path: Path, audio_mode: str, gpu_encoder: Optional[str], fontfile: str) -> list:
    filter_complex = build_filter_complex(fontfile)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-stats",
        "-y",
        "-i", str(in_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        "-movflags", "+faststart",
        "-shortest",
        # Rec.709 SDR metadata (CapCut-like)
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
    ]

    # Video encoding
    if gpu_encoder:
        cmd += ["-c:v", gpu_encoder]

        # Reasonable presets per encoder family
        if gpu_encoder.endswith("_nvenc"):
            # p1 fastest ... p7 best, p4 balanced
            cmd += ["-preset", "p4", "-rc", "vbr", "-cq", str(GPU_CQ)]
            # if HEVC on some players, use hvc1 tag
            if "hevc" in gpu_encoder:
                cmd += ["-tag:v", "hvc1"]
        elif gpu_encoder.endswith("_qsv"):
            cmd += ["-global_quality", str(GPU_CQ)]
            if "hevc" in gpu_encoder:
                cmd += ["-tag:v", "hvc1"]
        elif gpu_encoder.endswith("_amf"):
            cmd += ["-quality", "quality", "-qp_i", str(GPU_CQ), "-qp_p", str(GPU_CQ), "-qp_b", str(GPU_CQ)]
            if "hevc" in gpu_encoder:
                cmd += ["-tag:v", "hvc1"]

        # Compatibility
        cmd += ["-pix_fmt", "yuv420p"]
    else:
        # CPU fallback
        if CPU_FALLBACK == "libx265":
            cmd += ["-c:v", "libx265", "-preset", "veryfast", "-crf", str(max(22, min(28, CPU_CRF)))]
            cmd += ["-tag:v", "hvc1", "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(CPU_CRF), "-pix_fmt", "yuv420p"]

    # Audio (no normalization; keep original feel)
    if audio_mode == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", AAC_BITRATE]

    cmd += [str(out_path)]
    return cmd


def run_ffmpeg_inherit(cmd: list) -> int:
    # Let ffmpeg print progress directly to console; avoids "hung pipe" issues.
    print("Running command:\n", " ".join(shlex.quote(str(x)) for x in cmd), "\n")
    p = subprocess.run(cmd)
    return p.returncode


def main():
    if not tool_exists("ffmpeg"):
        messagebox.showerror("Thiếu ffmpeg", "Không tìm thấy ffmpeg trong PATH.\nHãy chạy được: ffmpeg -version")
        sys.exit(1)

    in_path = pick_input_video()
    if in_path is None:
        print("No input selected. Exit.")
        sys.exit(0)

    out_dir = Path(OUTPUT_DIR)
    out_path = unique_outpath(out_dir, f"{in_path.stem}_vertical.mp4")

    # Choose font (built-in Windows fonts; Vietnamese capable)
    fontfile = find_windows_vietnamese_fontfile()

    gpu_encoder = pick_gpu_encoder()
    if gpu_encoder:
        print(f"\nUsing GPU encoder: {gpu_encoder}\n")
    else:
        print("\nNo GPU encoder found (or GPU_MODE=cpu). Using CPU fallback.\n")

    # 1) Try audio copy
    cmd = build_cmd(in_path, out_path, audio_mode="copy", gpu_encoder=gpu_encoder, fontfile=fontfile)
    rc = run_ffmpeg_inherit(cmd)
    if rc == 0:
        messagebox.showinfo("Xong", f"Đã xuất video dọc:\n{out_path}")
        return

    # 2) Fallback: re-encode audio to AAC if copy fails
    cmd2 = build_cmd(in_path, out_path, audio_mode="aac", gpu_encoder=gpu_encoder, fontfile=fontfile)
    rc2 = run_ffmpeg_inherit(cmd2)
    if rc2 == 0:
        messagebox.showinfo("Xong", f"Đã xuất video dọc (audio AAC fallback):\n{out_path}")
        return

    messagebox.showerror(
        "Lỗi ffmpeg",
        "Render thất bại.\n\n"
        "Gợi ý nhanh:\n"
        "1) Kiểm tra ffmpeg có encoder GPU không: ffmpeg -encoders\n"
        "2) Nếu video input lỗi, thử mở và re-save hoặc đổi file.\n"
        "3) Nếu vẫn lỗi, copy/paste log ffmpeg trong terminal gửi mình."
    )
    sys.exit(rc2)


if __name__ == "__main__":
    main()
