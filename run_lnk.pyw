# -*- coding: utf-8 -*-
"""Launcher cho shortcut .lnk — mở GUI GetTextFromLink mà KHÔNG hiện cửa sổ đen.

- Chạy bằng pythonw (không có console) -> ẩn hoàn toàn "màn hình đen".
- pythonw không có console nên sys.stdout/err có thể là None; app print() rất nhiều,
  nên chuyển hướng ra file log để print() không làm crash ứng dụng.
- Xuất Word ra final_result_lnk.docx (giống GetTextFromLink.bat cũ) — đặt biến môi
  trường TRƯỚC khi import config.
- Cửa sổ GUI tự căn giữa màn hình (đã có sẵn trong app: GetTextApp.center_window).
- Không có console để "pause" báo lỗi -> hiện hộp thoại lỗi thay thế.
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
