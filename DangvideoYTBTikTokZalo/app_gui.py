# -*- coding: utf-8 -*-
"""Cửa sổ trạng thái desktop (pywebview) cho server "Đăng video tự động".

Chạy:  pythonw app_gui.py   (hoặc bấm đúp mo_gui.bat)  -> KHÔNG còn cửa sổ console.
  - Server của app.py chạy ngay trong tiến trình này (thread nền), giao diện web vẫn mở ở trình
    duyệt như trước (bỏ --khong-mo nếu không muốn tự mở).
  - Cửa sổ nhỏ 440x600 hiện: đèn "SERVER ĐANG CHẠY" + giờ, URL/cổng + nút Sao chép, hàng đợi
    (chờ/đang đăng/xong/lỗi), worker đang chạy hay dừng, Chrome đã nối extension chưa, 40 dòng
    nhật ký cuối. Nút: Mở giao diện (trình duyệt), Dừng server & thoát.
  - Đóng cửa sổ (X) cũng dừng server.

Bẫy pywebview: lớp Api chỉ được có phương thức public cho JS gọi; KHÔNG gán Window hay object
lạ vào thuộc tính public của nó (pywebview sẽ cố "phơi" thuộc tính đó ra JS và lỗi).

Kiểm thử không cần nhìn màn hình:  python app_gui.py --khong-mo --chup anh.png
  -> mở cửa sổ, chờ 3s, chụp vùng cửa sổ ra anh.png rồi tự thoát.
"""
import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import webview

import app                      # server + State dùng chung
import post_queue as pq

APP_DIR = Path(__file__).resolve().parent
W, H = 440, 600
TIEU_DE = "Đăng video tự động — server"

_WINDOW = None                  # giữ ở module, không để trong Api (xem bẫy ở docstring)


class Api:
    """Các hàm JS gọi qua pywebview.api.<tên>(). Chỉ phương thức public, không thuộc tính public."""

    def __init__(self):
        self._httpd = None
        self._thread = None
        self._url = ""
        self._t0 = time.time()
        self._dung_roi = False

    # ---- vòng đời server
    def khoi_dong(self, mo_trinh_duyet: bool):
        self._httpd, self._url = app.make_server()
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="http")
        self._thread.start()
        app.S.log(f"✓ Server sẵn sàng tại {self._url} — cửa sổ trạng thái desktop đang theo dõi.")
        if mo_trinh_duyet:
            threading.Timer(0.6, lambda: webbrowser.open(self._url)).start()
        return self._url

    def dung_server(self):
        if self._dung_roi:
            return
        self._dung_roi = True
        app.S.stop_flag.set()                       # worker đang đăng thì dừng sau video hiện tại
        if self._httpd:
            threading.Thread(target=self._httpd.shutdown, daemon=True).start()
        # tắt server = lúc duy nhất ngắt kết nối trình duyệt (đóng 3 tab điều khiển)
        threading.Thread(target=app.chrome_cdp.disconnect_all, daemon=True).start()

    # ---- JS gọi
    def trang_thai(self):
        S = app.S
        with S.lock:
            items = list(S.items)
            dem = {st: sum(1 for it in items if it.get("status") == st)
                   for st in (pq.STATUS_WAIT, pq.STATUS_RUNNING, pq.STATUS_DONE, pq.STATUS_ERROR)}
            logs = [t for _, t in S.logs[-40:]]
            worker = S.running
            # ext_ok giờ là dict theo nền tảng {youtube, tiktok, zalo}; đèn "Chrome" lấy YouTube
            chrome = bool(S.ext_ok.get("youtube")) if isinstance(S.ext_ok, dict) else bool(S.ext_ok)
        song = bool(self._thread and self._thread.is_alive()) and not self._dung_roi
        giay = int(time.time() - self._t0)
        return {
            "server": song,
            "url": self._url,
            "port": self._url.rsplit(":", 1)[-1].strip("/") if self._url else "",
            "uptime": f"{giay // 3600:02d}:{giay % 3600 // 60:02d}:{giay % 60:02d}",
            "gio": time.strftime("%H:%M:%S"),
            "tong": len(items),
            "cho": dem[pq.STATUS_WAIT], "dang": dem[pq.STATUS_RUNNING],
            "xong": dem[pq.STATUS_DONE], "loi": dem[pq.STATUS_ERROR],
            "worker": worker,
            "chrome": chrome,
            "logs": logs,
        }

    def mo_giao_dien(self):
        if self._url:
            webbrowser.open(self._url)
        return True

    def sao_chep(self):
        try:
            import tkinter as tk
            r = tk.Tk(); r.withdraw()
            r.clipboard_clear(); r.clipboard_append(self._url); r.update(); r.destroy()
            return True
        except Exception:
            return False

    def dung(self):
        """Nút 'Dừng server & thoát'."""
        self.dung_server()
        if _WINDOW is not None:
            threading.Timer(0.2, _WINDOW.destroy).start()
        return True


HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Đăng video tự động — server</title>
<style>
  :root{--bg:#111827;--card:#1f2937;--line:#263142;--fg:#e5e7eb;--dim:#9ca3af;
        --green:#16a34a;--red:#dc2626;--blue:#2563eb;--amber:#d97706}
  *{box-sizing:border-box} html,body{height:100%;margin:0}
  body{background:var(--bg);color:var(--fg);font:13px/1.45 "Segoe UI",system-ui,sans-serif;
       display:flex;flex-direction:column;padding:14px;gap:10px;user-select:none}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .row{display:flex;align-items:center;gap:10px}
  .grow{flex:1;min-width:0}
  .dot{width:14px;height:14px;border-radius:50%;background:var(--red);flex:none;
       box-shadow:0 0 0 0 rgba(22,163,74,.6)}
  .dot.on{background:var(--green);animation:pulse 1.6s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(22,163,74,.55)}70%{box-shadow:0 0 0 9px rgba(22,163,74,0)}100%{box-shadow:0 0 0 0 rgba(22,163,74,0)}}
  .title{font-weight:700;letter-spacing:.08em;font-size:14px}
  .title.off{color:#fca5a5}
  .mono{font-family:Consolas,"Cascadia Mono",monospace}
  .dim{color:var(--dim)} .small{font-size:11.5px}
  .url{font-size:13.5px;color:#93c5fd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;user-select:text}
  .btn{border:1px solid #374151;background:#111827;color:var(--fg);border-radius:8px;padding:6px 12px;
       cursor:pointer;font:inherit;white-space:nowrap}
  .btn:hover{background:#0b1220} .btn.sm{padding:4px 9px;font-size:12px}
  .btn.blue{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
  .btn.blue:hover{background:#1d4ed8}
  .btn.red{background:#7f1d1d;border-color:#991b1b;color:#fee2e2;font-weight:600}
  .btn.red:hover{background:#991b1b}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px}
  .k{color:var(--dim)} .v{font-weight:600}
  .chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
  .chip.ok{background:#14532d;color:#bbf7d0} .chip.bad{background:#7f1d1d;color:#fecaca}
  .chip.wait{background:#374151;color:#e5e7eb}
  .log{flex:1;display:flex;flex-direction:column;min-height:0}
  .log h3{margin:0 0 6px;font-size:11.5px;letter-spacing:.1em;color:var(--dim);font-weight:600}
  pre{flex:1;margin:0;overflow:auto;background:#0b1220;border:1px solid var(--line);border-radius:8px;
      padding:8px 10px;font:12px/1.5 Consolas,"Cascadia Mono",monospace;color:#d1d5db;white-space:pre-wrap;
      word-break:break-word;user-select:text}
  .foot{display:flex;gap:8px;justify-content:space-between}
  .q b{font-weight:700} .q .ok{color:#86efac} .q .err{color:#fca5a5} .q .run{color:#fcd34d}
</style></head><body>
  <div class="card">
    <div class="row">
      <div id="dot" class="dot"></div>
      <div id="tt" class="title grow">ĐANG KHỞI ĐỘNG...</div>
      <div id="gio" class="mono dim">--:--:--</div>
    </div>
    <div class="row" style="margin-top:8px">
      <div id="url" class="url grow mono">…</div>
      <button id="copy" class="btn sm">Sao chép</button>
    </div>
    <div class="small dim" style="margin-top:4px">Đã chạy <span id="up" class="mono">00:00:00</span> · cổng <span id="port" class="mono">—</span></div>
  </div>

  <div class="card grid">
    <div><span class="k">Hàng đợi:</span> <span id="q" class="v q">0 video</span></div>
    <div><span class="k">Worker:</span> <span id="worker" class="chip wait">dừng</span></div>
    <div><span class="k">Đang đăng:</span> <span id="dang" class="v">0</span> · <span class="k">chờ:</span> <span id="cho" class="v">0</span></div>
    <div><span class="k">Chrome:</span> <span id="chrome" class="chip bad">chưa nối</span></div>
  </div>

  <div class="card log">
    <h3>NHẬT KÝ</h3>
    <pre id="log">(chưa có)</pre>
  </div>

  <div class="foot">
    <button id="open" class="btn blue">Mở giao diện</button>
    <button id="stop" class="btn red">Dừng server &amp; thoát</button>
  </div>

<script>
  const $ = id => document.getElementById(id);
  let armed = 0, lastLog = "";
  function render(s){
    $('dot').className = 'dot' + (s.server ? ' on' : '');
    $('tt').textContent = s.server ? 'SERVER ĐANG CHẠY' : 'SERVER ĐÃ DỪNG';
    $('tt').className = 'title grow' + (s.server ? '' : ' off');
    $('gio').textContent = s.gio; $('url').textContent = s.url || '—';
    $('up').textContent = s.uptime; $('port').textContent = s.port || '—';
    const q = `${s.tong} video` + (s.tong ? ` (<b class="ok">${s.xong} xong</b>, <b class="err">${s.loi} lỗi</b>)` : '');
    $('q').innerHTML = q; $('dang').textContent = s.dang; $('cho').textContent = s.cho;
    $('worker').textContent = s.worker ? 'đang chạy ▶' : 'dừng';
    $('worker').className = 'chip ' + (s.worker ? 'ok' : 'wait');
    $('chrome').textContent = s.chrome ? 'đã nối ✔' : 'chưa nối';
    $('chrome').className = 'chip ' + (s.chrome ? 'ok' : 'bad');
    const txt = (s.logs && s.logs.length) ? s.logs.join('\n') : '(chưa có)';
    if (txt !== lastLog){
      const pre = $('log'), atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
      pre.textContent = txt; lastLog = txt;
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
  }
  async function tick(){ try { render(await pywebview.api.trang_thai()); } catch(e){} }
  window.addEventListener('pywebviewready', () => { tick(); setInterval(tick, 1000); });
  $('open').onclick = () => pywebview.api.mo_giao_dien();
  $('copy').onclick = async () => { const ok = await pywebview.api.sao_chep();
    $('copy').textContent = ok ? 'Đã sao chép ✔' : 'Lỗi'; setTimeout(() => $('copy').textContent = 'Sao chép', 1500); };
  $('stop').onclick = () => {
    if (!armed){ armed = 1; $('stop').textContent = 'Bấm lần nữa để dừng'; setTimeout(() => { armed = 0; $('stop').textContent = 'Dừng server & thoát'; }, 3000); return; }
    $('stop').textContent = 'Đang dừng...'; pywebview.api.dung();
  };
</script></body></html>"""


def _chup_man_hinh(win, duong_dan: str, cho: float = 3.0):
    """Chụp vùng cửa sổ ra file (để kiểm thử tự động), rồi đóng cửa sổ."""
    time.sleep(cho)
    try:
        import ctypes
        from ctypes import wintypes
        from PIL import ImageGrab
        # tọa độ thật của cửa sổ (pixel vật lý, đúng cả khi màn hình scale DPI) qua Win32
        hwnd = ctypes.windll.user32.FindWindowW(None, TIEU_DE)
        if hwnd:
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            bbox = (r.left, r.top, r.right, r.bottom)
        else:
            x, y = win.x, win.y
            bbox = (x, y, x + win.width + 16, y + win.height + 40)
        ImageGrab.grab(bbox=bbox, all_screens=True).save(duong_dan)
    except Exception as e:                       # noqa: BLE001
        print("Chụp lỗi:", e)
    win.destroy()


def main():
    global _WINDOW
    ap = argparse.ArgumentParser(description="Cửa sổ trạng thái cho server đăng video")
    ap.add_argument("--khong-mo", action="store_true", help="không tự mở giao diện web ở trình duyệt")
    ap.add_argument("--chup", help="(kiểm thử) chụp cửa sổ ra file PNG sau 3s rồi thoát")
    args = ap.parse_args()

    api = Api()
    sw, sh = (webview.screens[0].width, webview.screens[0].height) if webview.screens else (1920, 1080)
    _WINDOW = webview.create_window(
        TIEU_DE, html=HTML, js_api=api, width=W, height=H,
        x=max(0, (sw - W) // 2), y=max(0, (sh - H) // 2),       # canh giữa màn hình
        resizable=True, min_size=(380, 480), background_color="#111827")
    _WINDOW.events.closed += api.dung_server                     # bấm X cũng dừng server

    def sau_khi_mo():
        api.khoi_dong(mo_trinh_duyet=not args.khong_mo)
        if args.chup:
            threading.Thread(target=_chup_man_hinh, args=(_WINDOW, args.chup), daemon=True).start()

    webview.start(sau_khi_mo, private_mode=False)
    api.dung_server()
    sys.stdout.flush()
    os._exit(0)                 # thread server/worker daemon -> thoát thẳng cho gọn


if __name__ == "__main__":
    main()
