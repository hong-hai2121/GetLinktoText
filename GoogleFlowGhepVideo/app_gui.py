# -*- coding: utf-8 -*-
"""Cửa sổ desktop "Ghép video Flow": một cửa sổ pywebview nạp thẳng giao diện web của app.py
(menu tab dọc bên trái: Ghép video · Chỉnh sửa · Kết nối AI · Nhật ký · Cài đặt).

Chạy:  pythonw app_gui.py   (hoặc bấm đúp mo_gui.bat / shortcut "Ghép video Flow" trên Desktop)
  macOS: shortcut là một .app tự tạo (Contents/Info.plist + Resources/ghep_video.icns + MacOS/<script> gồm một dòng
  `exec /bin/zsh "<repo>/GoogleFlowGhepVideo/mo_gui_mac.sh"`); mo_gui_mac.sh exec python của venv ngay trong tiến trình
  của .app nên Dock chỉ có một biểu tượng "Ghép video Flow", không cửa sổ Terminal/python thừa. Mở lần hai khi đang chạy
  thì macOS chỉ đưa cửa sổ lên trước.
  - Server của app.py chạy trong tiến trình này (thread nền) ở http://127.0.0.1:8766; cửa sổ nạp URL đó.
    Vẫn mở được cùng giao diện bằng trình duyệt (nút "Mở trong trình duyệt" ở tab Cài đặt).
  - Mở lần hai khi server đang chạy: chỉ mở thêm cửa sổ nạp server có sẵn, không chạy server thứ hai.
  - Đóng cửa sổ (X) = dừng server + tiến trình ghép đang chạy (chỉ khi cửa sổ này là nơi chạy server).
  - Icon cửa sổ/thanh tác vụ: ghep_video.ico cạnh file (đặt qua WM_SETICON vì pywebview trên Windows
    không có tham số icon).

Kiểm thử không cần nhìn:  python app_gui.py --chup anh.png   (mở, chờ 6s, chụp cửa sổ, thoát).
"""
import argparse
import ctypes
import os
import sys
import threading
import time
from pathlib import Path

import webview

import app                      # server + State dùng chung

APP_DIR = Path(__file__).resolve().parent
ICO = APP_DIR / "ghep_video.ico"
W, H = 1180, 760
TIEU_DE = "Ghép video Flow"

_WINDOW = None
_HTTPD = None


def _dat_icon(tieu_de: str, ico: Path, cho: float = 20.0):
    """Gắn icon cho cửa sổ (tìm theo tiêu đề) — chạy ở thread nền sau khi cửa sổ hiện."""
    if not ico.exists() or os.name != "nt":       # macOS: icon lấy từ app launcher, không cần WM_SETICON
        return
    u32 = ctypes.windll.user32
    het = time.time() + cho
    hwnd = 0
    while time.time() < het and not hwnd:
        hwnd = u32.FindWindowW(None, tieu_de)
        if not hwnd:
            time.sleep(0.3)
    if not hwnd:
        return
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x80
    for kich, loai in ((16, 0), (32, 1)):            # ICON_SMALL = 0 (thanh tiêu đề), ICON_BIG = 1 (Alt-Tab)
        h = u32.LoadImageW(None, str(ico), IMAGE_ICON, kich, kich, LR_LOADFROMFILE)
        if h:
            u32.SendMessageW(hwnd, WM_SETICON, loai, h)


def _icon_dock_mac(ico: Path):
    """macOS: Dock hiện tên + icon của app thay cho "Python" + tên lửa (chạy bằng python của venv, không phải .app)."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSBundle, NSImage
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = TIEU_DE
        if ico.exists():
            img = NSImage.alloc().initWithContentsOfFile_(str(ico))
            if img is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:   # noqa: BLE001
        pass


def _chup_man_hinh(win, duong_dan: str, cho: float = 6.0):
    time.sleep(cho)
    try:
        from PIL import ImageGrab
        hwnd = ctypes.windll.user32.FindWindowW(None, TIEU_DE) if os.name == "nt" else 0
        if hwnd:
            from ctypes import wintypes
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            bbox = (r.left, r.top, r.right, r.bottom)
        else:
            bbox = (win.x, win.y, win.x + win.width + 16, win.y + win.height + 40)
        ImageGrab.grab(bbox=bbox, all_screens=True).save(duong_dan)
    except Exception as e:                       # noqa: BLE001
        print("Chụp lỗi:", e)
    win.destroy()


def _dung():
    global _HTTPD
    if _HTTPD is not None:
        app.dung_tat_ca()
        h, _HTTPD = _HTTPD, None
        threading.Thread(target=h.shutdown, daemon=True).start()


def main():
    global _WINDOW, _HTTPD
    ap = argparse.ArgumentParser(description="Cửa sổ Ghép video Flow")
    ap.add_argument("--chup", help="(kiểm thử) chụp cửa sổ ra file PNG sau 6s rồi thoát")
    ap.add_argument("--tab", help="mở sẵn tab: ghep | chinh-sua | ai | nhat-ky | cai-dat")
    args = ap.parse_args()
    _icon_dock_mac(ICO)                           # trước khi AppKit khởi tạo (webview.screens) để Dock nhận tên

    url = app.dang_chay_san()
    if not url:                                   # chưa có server -> chạy trong tiến trình này
        _HTTPD, url = app.make_server()
        threading.Thread(target=_HTTPD.serve_forever, daemon=True, name="http").start()
        app.S.log(f"✓ Server sẵn sàng tại {url} — cửa sổ desktop đang mở giao diện.")
    if args.tab:
        url += f"#{args.tab}"

    sw, sh = (webview.screens[0].width, webview.screens[0].height) if webview.screens else (1920, 1080)
    w, h = min(W, sw - 40), min(H, sh - 60)
    _WINDOW = webview.create_window(
        TIEU_DE, url=url, width=w, height=h,
        x=max(0, (sw - w) // 2), y=max(0, (sh - h) // 2),       # canh giữa màn hình
        resizable=True, min_size=(900, 600), background_color="#f3f4f6")
    _WINDOW.events.closed += _dung

    def sau_khi_mo():
        threading.Thread(target=_dat_icon, args=(TIEU_DE, ICO), daemon=True).start()
        if args.chup:
            threading.Thread(target=_chup_man_hinh, args=(_WINDOW, args.chup), daemon=True).start()

    webview.start(sau_khi_mo, private_mode=False)
    _dung()
    sys.stdout.flush()
    os._exit(0)                 # thread server/worker daemon -> thoát thẳng cho gọn


if __name__ == "__main__":
    main()
