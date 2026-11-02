import os
import platform
import subprocess
import time


def play_sound(sound_type="success"):
    """
    Phát âm thanh thông báo
    sound_type: "success" (hoàn thành), "error" (lỗi), "warning" (cảnh báo)
    """
    try:
        if platform.system() == "Windows":
            import winsound

            if sound_type == "success":
                # 3 tiếng beep ngắn cho thành công
                for _ in range(3):
                    winsound.Beep(1000, 200)  # Tần số 1000Hz, thời lượng 200ms
                    time.sleep(0.1)
            elif sound_type == "error":
                # 2 tiếng beep dài cho lỗi
                for _ in range(2):
                    winsound.Beep(400, 300)  # Tần số 400Hz, thời lượng 300ms
                    time.sleep(0.1)
            elif sound_type == "warning":
                # 1 tiếng beep cho cảnh báo
                winsound.Beep(800, 200)
        elif platform.system() == "Darwin":  # macOS
            os.system(
                "afplay /System/Library/Sounds/Glass.aiff"
                if sound_type != "error"
                else "afplay /System/Library/Sounds/Sosumi.aiff"
            )
        elif platform.system() == "Linux":
            # Dùng paplay hoặc beep trên Linux
            try:
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                    timeout=2,
                )
            except Exception:
                os.system("beep")
    except Exception as e:
        print(f"⚠️ Lỗi khi phát âm thanh: {e}")
