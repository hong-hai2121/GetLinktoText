# -*- coding: utf-8 -*-
"""Launcher cho shortcut .lnk — mở GUI GetTextFromLink mà KHÔNG hiện cửa sổ đen.

- Chạy bằng pythonw (không có console) -> ẩn hoàn toàn "màn hình đen".
- pythonw không có console nên sys.stdout/err có thể là None; app print() rất nhiều,
  nên chuyển hướng ra file log để print() không làm crash ứng dụng.
- Xuất Word ra final_result_lnk.docx (giống GetTextFromLink.bat cũ) — đặt biến môi
  trường TRƯỚC khi import config.
- Cửa sổ GUI tự căn giữa màn hình (đã có sẵn trong app: GetTextApp.center_window).
- Không có console để "pause" báo lỗi -> hiện hộp thoại lỗi thay thế.
- Không có console -> mỗi tiến trình con được Windows cấp cửa sổ đen riêng; xem
  _an_cua_so_tien_trinh_con() bên dưới.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

# Đặt TRƯỚC khi import config: chạy qua shortcut -> ghi ra file Word riêng.
os.environ.setdefault("OUTPUT_WORD_FILE", os.path.join(HERE, "final_result_lnk.docx"))

# pythonw: stdout/err có thể là None -> hứng vào file log để print() không gây lỗi.
try:
    _log = open(os.path.join(HERE, "lnk_run.log"), "w", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log
    if sys.stderr is None:
        sys.stderr = _log
except Exception:
    pass


def _an_cua_so_tien_trinh_con():
    """Ẩn cửa sổ đen của MỌI tiến trình con (ffmpeg, taskkill, geckodriver...).

    Chạy bằng python.exe thì tiến trình con kế thừa console sẵn có -> không có gì
    chớp lên. Chạy bằng pythonw.exe thì không có console nào để kế thừa, nên Windows
    cấp cho mỗi tiến trình con một cửa sổ mới -> chớp đen sau mỗi link.

    Patch Popen thay vì sửa từng lời gọi trong src/ vì ffmpeg do yt-dlp gọi ngầm
    không truyền creationflags vào được. Chỉ ảnh hưởng tiến trình launcher này;
    chạy `python GetTextFromLink.py` từ terminal vẫn như cũ.
    """
    if sys.platform != "win32":
        return
    import subprocess

    CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    # Caller đã tự quyết định chuyện cửa sổ -> tôn trọng, không đè lên.
    DA_CHON = CREATE_NO_WINDOW | subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS

    goc = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        # creationflags là tham số vị trí thứ 14 — không ai truyền kiểu đó, nhưng
        # nếu có thì để nguyên cho an toàn.
        if len(args) < 14 and not (kwargs.get("creationflags", 0) & DA_CHON):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        goc(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__


_an_cua_so_tien_trinh_con()


def _bao_loi(msg):
    """Không có console -> báo lỗi bằng hộp thoại thay cho 'pause' của .bat."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("GetTextFromLink — Lỗi", msg)
        r.destroy()
    except Exception:
        pass


def main():
    try:
        from src.main import main as run
        run()
    except SystemExit as e:
        if e.code not in (0, None):
            _bao_loi("Ứng dụng dừng sớm (mã %s).\nXem chi tiết trong lnk_run.log." % e.code)
    except Exception:
        import traceback
        traceback.print_exc()
        _bao_loi("Có lỗi khi chạy:\n\n%s\nChi tiết trong lnk_run.log."
                 % traceback.format_exc(limit=3))


if __name__ == "__main__":
    main()
