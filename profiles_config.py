# -*- coding: utf-8 -*-
from pathlib import Path
import os

# ====== Danh sách Hồ Sơ Firefox ====== #
PROFILES = {
    "Profile01": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\jf2te79d.default-release",
    "Profile02": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\qo4o211a.5", #
    "Profile03": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\nmfygyzt.2", #
    "Profile04": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\uqiowz8o.3",
    "Profile05": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\42alfg11.4",
    "Profile06": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\mef4v4wh.6"
}

# ====== Chọn hồ sơ mặc định ====== #
selected_name = "Profile02"

# Cho phép override bằng biến môi trường FIREFOX_PROFILE_NAME nếu muốn tạm đổi
selected_name = os.environ.get("FIREFOX_PROFILE_NAME", selected_name)

# ====== Hàm lấy đường dẫn ====== #
def get_profile(name: str) -> str:
    """Trả về đường dẫn hồ sơ Firefox hợp lệ, có kiểm tra tồn tại."""
    if name not in PROFILES:
        raise KeyError(f"Profile '{name}' không tồn tại.")
    path = Path(PROFILES[name])
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy profile tại: {path}")
    return str(path)

# ====== Xuất sẵn đường dẫn đã chọn ====== #
FIREFOX_PROFILE_PATH = get_profile(selected_name)

# ====== Cho phép các file khác import dùng ngay ====== #
if __name__ == "__main__":
    print(f"Selected profile: {selected_name}")
    print(f"Path: {FIREFOX_PROFILE_PATH}")
