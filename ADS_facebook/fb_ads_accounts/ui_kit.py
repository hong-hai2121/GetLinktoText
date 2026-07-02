"""
Tiện ích giao diện dùng chung cho các cửa sổ Tkinter của bộ công cụ FB Ads.

- Palette (bảng màu) thống nhất, dịu mắt — dùng lại giữa hub và các tool con.
- size_window(): canh cửa sổ theo tỉ lệ 21:9 (màn hình siêu rộng), co giãn vừa
  màn hình rồi canh giữa. Dùng chung cho mọi cửa sổ để nhìn đồng bộ.
"""

# ── Palette (Soft Light / dịu mắt) ────────────────────────────────────────────
BG        = "#eef2f6"   # nền chính (xám xanh nhạt)
SIDEBAR   = "#f8fafc"   # nền sidebar / thẻ (slate-50)
SURFACE   = "#f8fafc"
CARD      = "#f8fafc"
BORDER    = "#cbd5e1"   # viền mềm (slate-300)
ACCENT    = "#3b82f6"   # blue-500
ACCENT_HV = "#2563eb"   # blue-600
ACCENT_SOFT = "#e0f2fe" # nền xanh nhạt (mục đang chọn)
GREEN     = "#10b981"
YELLOW    = "#f59e0b"
RED       = "#ef4444"
TEXT      = "#334155"   # slate-700
MUTED     = "#64748b"   # slate-500
CODE_BG   = "#f1f5f9"   # nền console (slate-100)

ASPECT_21_9 = 21 / 9


def size_window(win, min_w=960, min_h=560,
                height_frac=0.84, max_width_frac=0.94, ratio=ASPECT_21_9):
    """Đặt kích thước cửa sổ theo tỉ lệ `ratio` (mặc định 21:9), vừa màn hình, canh giữa.

    Ưu tiên lấp chiều cao (height_frac × chiều cao màn hình) rồi suy ra bề ngang
    theo tỉ lệ; nếu quá rộng thì co lại theo max_width_frac × bề ngang màn hình.
    """
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()

    h = int(sh * height_frac)
    w = int(h * ratio)
    if w > sw * max_width_frac:                 # màn hình không đủ rộng → co bề ngang
        w = int(sw * max_width_frac)
        h = int(w / ratio)

    w, h = max(w, min_w), max(h, min_h)
    w, h = min(w, sw), min(h, sh)               # không vượt màn hình
    x = max((sw - w) // 2, 0)
    y = max((sh - h) // 2 - 24, 0)
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.minsize(min_w, min_h)
    return w, h
