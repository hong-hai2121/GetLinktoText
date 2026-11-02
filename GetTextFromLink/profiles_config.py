# -*- coding: utf-8 -*-
import os
from config import BASE_DIR, IS_FROZEN

PROFILES = {
    "Profile01": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\jf2te79d.default-release",
    "Profile02": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\qo4o211a.5", #
    "Profile03": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\nmfygyzt.2", #
    "Profile04": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\uqiowz8o.3",
    "Profile05": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\42alfg11.4",
    "Profile06": r"C:\Users\PC\AppData\Roaming\Mozilla\Firefox\Profiles\mef4v4wh.6"
}

selected_name = "Profile05"

# Cho phép override bằng biến môi trường FIREFOX_PROFILE_NAME nếu muốn tạm đổi
selected_name = os.environ.get("FIREFOX_PROFILE_NAME", selected_name)

if selected_name not in PROFILES:
    raise KeyError(f"Profile '{selected_name}' không tồn tại.")

FIREFOX_PROFILE_PATH = os.environ.get("FIREFOX_PROFILE_PATH") or (
    os.path.join(BASE_DIR, "firefox_profile") if IS_FROZEN else PROFILES[selected_name]
)
