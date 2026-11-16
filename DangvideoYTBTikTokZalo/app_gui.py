# -*- coding: utf-8 -*-
"""Cửa sổ trạng thái desktop (pywebview) cho server "Đăng video tự động".

Chạy:  pythonw app_gui.py   (hoặc bấm đúp mo_gui.bat)  -> KHÔNG còn cửa sổ console.
  - Server của app.py chạy ngay trong tiến trình này (thread nền), giao diện web vẫn mở ở trình
    duyệt như trước (bỏ --khong-mo nếu không muốn tự mở).
  - Cửa sổ NGANG 1100x620 (26/10/2026, nới 16/11/2026) hiện: đèn "SERVER ĐANG CHẠY" + giờ, URL/cổng + nút Sao chép,
    hàng đợi (chờ/đang đăng/xong/lỗi), worker đang chạy hay dừng, từng trình duyệt đã nối chưa, 60 dòng
    nhật ký cuối. Nút: Mở giao diện (trình duyệt), Dừng server & thoát.
  - Thẻ TRÌNH DUYỆT (user 16/11/2026: "Invalid token provided", muốn sửa token + nối lại ngay ở cửa sổ này, không
    phải qua giao diện web): mỗi nền tảng có ô Token + Lưu, nút "🔌 Nối lại" (api_ket_noi_lai), "Nối & Cho phép"
    (mở trang connect KHÔNG token -> bấm 'Allow & select' trong Chrome, app tự lưu token mới), "Trang token" (mở
    status.html của extension để sao chép token); nút "Nối lại cả 3".
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
W, H = 1100, 720                # cửa sổ NGANG (user 26/10/2026): cột trái trạng thái (có ô token + nút nối lại), cột phải nhật ký
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
        # tắt server = lúc duy nhất ngắt kết nối trình duyệt (đóng 3 tab điều khiển); main() chờ thread này
        self._ngat = threading.Thread(target=app.chrome_cdp.disconnect_all, daemon=True)
        self._ngat.start()

    # ---- JS gọi
    def trang_thai(self):
        S = app.S
        with S.lock:
            items = list(S.items)
            dem = {st: sum(1 for it in items if it.get("status") == st)
                   for st in (pq.STATUS_WAIT, pq.STATUS_RUNNING, pq.STATUS_DONE, pq.STATUS_ERROR)}
            logs = [t for _, t in S.logs[-60:]]
            worker = S.running
            # ext_ok giờ là dict theo nền tảng {youtube, tiktok, zalo}; đèn "Chrome" lấy YouTube
            chrome = bool(S.ext_ok.get("youtube")) if isinstance(S.ext_ok, dict) else bool(S.ext_ok)
            # kết nối trình duyệt giữ suốt phiên: session_ready = extension + Playwright đều nối, tab còn
            trinh_duyet = []
            for n in pq.PLATFORMS:
                pc = app.platform_cfg(n)
                trinh_duyet.append({"id": n,
                                    "ten": pq.PLATFORM_LABEL[n] + (" · Gemini" if n == "zalo" else ""),
                                    "profile": f"{app.browser_name(pc)} {pc.get('profile_dir', '')}",
                                    "ok": app.chrome_cdp.session_ready(pc),
                                    "token": app.chrome_cdp.normalize_token(pc.get("extension_token") or "")})
            ban = bool(S.running or S.seo_running)      # đang đăng / AI / nối lại -> khoá nút nối
            gpt = S.gpt_status or {}
            ai = {"backend": S.cfg.get("ai_backend") or "gemini", "gpt_da_kiem_tra": bool(gpt),
                  "gpt_ok": bool(gpt.get("ket_noi")), "gpt_ghi_chu": gpt.get("ghi_chu") or "", "gpt_email": gpt.get("email") or ""}
            seo = {"running": S.seo_running,
                   "cho": sum(1 for j in S.seo_jobs if j["status"] == "chờ"),
                   "dang": sum(1 for j in S.seo_jobs if j["status"] == "đang chạy"),
                   "xong": sum(1 for j in S.seo_jobs if j["status"] == "xong"),
                   "loi": sum(1 for j in S.seo_jobs if j["status"] == "lỗi"),
                   "buoc": next((j["buoc"] for j in S.seo_jobs if j["status"] == "đang chạy"), "")}
            current = S.current
        song = bool(self._thread and self._thread.is_alive()) and not self._dung_roi
        giay = int(time.time() - self._t0)
        return {
            "trinh_duyet": trinh_duyet, "ai": ai, "seo": seo, "current": current, "ban": ban,
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

    # ---- thẻ TRÌNH DUYỆT: token + nối lại ngay ở cửa sổ này (dùng chung API với giao diện web)
    def luu_token(self, nen_tang, token):
        try:
            return app.api_save_token({"platform": nen_tang, "token": token or ""})
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def ket_noi_lai(self, nen_tang, cho_phep=False, token=None):
        """nen_tang: youtube/tiktok/zalo/all. cho_phep=True: mở trang connect KHÔNG token, người dùng bấm
        'Allow & select' trong Chrome (token đã đổi). token: lưu token đang gõ trước khi nối (chỉ khi không cho_phep)."""
        d = {"platform": nen_tang, "cho_phep": bool(cho_phep)}
        if token is not None and nen_tang != "all" and not cho_phep:
            d["token"] = token
        try:
            return app.api_ket_noi_lai(d)
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def mo_trang_token(self, nen_tang):
        """Mở trang trạng thái của extension (có dòng PLAYWRIGHT_MCP_EXTENSION_TOKEN=... + nút sao chép) trong đúng profile."""
        try:
            app.chrome_cdp.open_status_page(app.platform_cfg(nen_tang), log=app.S.log)
            return {"ok": True, "msg": "Đã mở trang token trong trình duyệt — sao chép dòng PLAYWRIGHT_MCP_EXTENSION_TOKEN=… dán vào ô Token rồi Lưu."}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "msg": f"Không mở được trang token: {e}"}

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
       display:flex;flex-direction:column;padding:12px;gap:10px;user-select:none}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px}
  .row{display:flex;align-items:center;gap:10px}
  .grow{flex:1;min-width:0}
  .dot{width:14px;height:14px;border-radius:50%;background:var(--red);flex:none;
       box-shadow:0 0 0 0 rgba(22,163,74,.6)}
  .dot.on{background:var(--green);animation:pulse 1.6s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(22,163,74,.55)}70%{box-shadow:0 0 0 9px rgba(22,163,74,0)}100%{box-shadow:0 0 0 0 rgba(22,163,74,0)}}
  .title{font-weight:700;letter-spacing:.08em;font-size:14px;white-space:nowrap}
  .title.off{color:#fca5a5}
  .mono{font-family:Consolas,"Cascadia Mono",monospace}
  .dim{color:var(--dim)} .small{font-size:11.5px}
  .url{font-size:13px;color:#93c5fd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;user-select:text}
  .btn{border:1px solid #374151;background:#111827;color:var(--fg);border-radius:8px;padding:6px 12px;
       cursor:pointer;font:inherit;white-space:nowrap}
  .btn:hover{background:#0b1220} .btn.sm{padding:4px 9px;font-size:12px}
  .btn:disabled{opacity:.45;cursor:not-allowed}
  .btn.blue{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
  .btn.blue:hover{background:#1d4ed8}
  .btn.amber{background:var(--amber);border-color:var(--amber);color:#fff;font-weight:600}
  .btn.amber:hover{background:#b45309}
  /* thẻ TRÌNH DUYỆT: mỗi nền tảng một khối (chip + ô token + nút) — dựng 1 lần, chỉ cập nhật chip/ô (không đè chữ đang gõ) */
  .pf{padding:7px 0;border-top:1px solid var(--line)} .pf:first-child{border-top:0;padding-top:2px}
  .pf .line{border-top:0;padding:2px 0}
  .pf .row{gap:5px;margin-top:5px}
  .pf input{flex:1;min-width:0;background:#0b1220;border:1px solid #374151;color:var(--fg);border-radius:7px;
       padding:4px 8px;font:12px Consolas,"Cascadia Mono",monospace;user-select:text;outline:none}
  .pf input:focus{border-color:var(--blue)}
  .toast{position:fixed;left:50%;bottom:54px;transform:translateX(-50%);background:#111827;border:1px solid #374151;
       color:#f9fafb;padding:8px 14px;border-radius:9px;font-size:12.5px;max-width:82%;box-shadow:0 6px 20px rgba(0,0,0,.45);
       transition:opacity .3s;z-index:9;opacity:0;pointer-events:none}
  .toast.show{opacity:1} .toast.err{background:#7f1d1d;border-color:#991b1b}
  .btn.red{background:#7f1d1d;border-color:#991b1b;color:#fee2e2;font-weight:600}
  .btn.red:hover{background:#991b1b}
  .sep{width:1px;height:22px;background:var(--line);margin:0 4px}
  .main{flex:1;min-height:0;display:grid;grid-template-columns:420px 1fr;gap:10px}
  .col{display:flex;flex-direction:column;gap:10px;min-height:0;overflow:auto}
  h3{margin:0 0 7px;font-size:11px;letter-spacing:.12em;color:var(--dim);font-weight:600}
  .k{color:var(--dim)} .v{font-weight:600}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;text-align:center}
  .stat{background:#0b1220;border:1px solid var(--line);border-radius:9px;padding:6px 4px}
  .stat b{display:block;font-size:19px;line-height:1.1} .stat span{font-size:11px;color:var(--dim)}
  .stat.ok b{color:#86efac} .stat.err b{color:#fca5a5} .stat.run b{color:#fcd34d}
  .chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:600;white-space:nowrap}
  .chip.ok{background:#14532d;color:#bbf7d0} .chip.bad{background:#7f1d1d;color:#fecaca}
  .chip.wait{background:#374151;color:#e5e7eb}
  .line{display:flex;align-items:center;gap:8px;padding:4px 0;border-top:1px solid var(--line)}
  .line:first-of-type{border-top:0}
  .line .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .line .nm small{color:var(--dim);margin-left:6px}
  .log{display:flex;flex-direction:column;min-height:0}
  pre{flex:1;margin:0;overflow:auto;background:#0b1220;border:1px solid var(--line);border-radius:8px;
      padding:8px 10px;font:12px/1.5 Consolas,"Cascadia Mono",monospace;color:#d1d5db;white-space:pre-wrap;
      word-break:break-word;user-select:text}
  .foot{display:flex;gap:8px;justify-content:space-between;align-items:center}
  .foot .cur{color:#fcd34d;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;text-align:center}
</style></head><body>
  <div class="card row">
    <div id="dot" class="dot"></div>
    <div id="tt" class="title">ĐANG KHỞI ĐỘNG...</div>
    <div class="sep"></div>
    <div id="url" class="url grow mono">…</div>
    <button id="copy" class="btn sm">Sao chép</button>
    <div class="sep"></div>
    <div class="small dim" style="white-space:nowrap">cổng <span id="port" class="mono">—</span> · chạy <span id="up" class="mono">00:00:00</span></div>
    <div id="gio" class="mono dim" style="white-space:nowrap">--:--:--</div>
  </div>

  <div class="main">
    <div class="col">
      <div class="card">
        <h3>HÀNG ĐỢI ĐĂNG <span id="worker" class="chip wait" style="float:right">dừng</span></h3>
        <div class="stats">
          <div class="stat"><b id="cho">0</b><span>chờ</span></div>
          <div class="stat run"><b id="dang">0</b><span>đang đăng</span></div>
          <div class="stat ok"><b id="xong">0</b><span>xong</span></div>
          <div class="stat err"><b id="loi">0</b><span>lỗi</span></div>
        </div>
      </div>
      <div class="card">
        <h3>TRÌNH DUYỆT <span class="dim" style="letter-spacing:0;font-weight:400">— nối 1 lần, giữ tới khi tắt server</span>
          <button id="noiTatCa" class="btn sm" style="float:right;margin-top:-4px" title="Nối lại cả YouTube, TikTok, Zalo — phiên đang tốt giữ nguyên, chỉ nối cái hỏng">🔌 Nối lại cả 3</button></h3>
        <div id="tds"></div>
        <div class="small dim" style="margin-top:7px;line-height:1.4">Tab Chrome báo <b>"Invalid token provided"</b> = token extension đã đổi →
          bấm <b>Nối &amp; Cho phép</b>, trong tab vừa mở chọn <b>Allow &amp; select</b> ở dòng của chính tab đó; app tự lưu token mới.
          Hoặc <b>Trang token</b> → sao chép token, dán vào ô rồi <b>Lưu</b> → <b>Nối lại</b>.</div>
      </div>
      <div class="card">
        <h3>TẠO NỘI DUNG AI <span id="seoRun" class="chip wait" style="float:right">nghỉ</span></h3>
        <div class="line"><span class="nm">Đang chọn: <b id="aiBackend">—</b></span></div>
        <div class="line"><span class="nm">ChatGPT CLI<small id="gptNote"></small></span><span id="gptChip" class="chip wait">chưa kiểm tra</span></div>
        <div class="line"><span class="nm">Việc AI: <span id="seoCnt" class="v">—</span></span></div>
      </div>
    </div>
    <div class="card log">
      <h3>NHẬT KÝ</h3>
      <pre id="log">(chưa có)</pre>
    </div>
  </div>

  <div class="foot">
    <button id="open" class="btn blue">Mở giao diện</button>
    <div id="cur" class="cur"></div>
    <button id="stop" class="btn red">Dừng server &amp; thoát</button>
  </div>
  <div id="toast" class="toast"></div>

<script>
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  let lastLog = "", tokenLoaded = false;
  // ----- thẻ TRÌNH DUYỆT: dựng 3 khối một lần (ô token giữ chữ đang gõ), render() chỉ cập nhật chip/profile/khoá nút
  const PF = [["youtube", "YouTube"], ["tiktok", "TikTok"], ["zalo", "Zalo · Gemini"]];
  $('tds').innerHTML = PF.map(([n, L]) => `
    <div class="pf">
      <div class="line"><span class="nm"><b>${L}</b><small id="${n}-profile"></small></span><span id="${n}-chip" class="chip wait">…</span></div>
      <div class="row">
        <input id="${n}-token" type="password" spellcheck="false" autocomplete="off" placeholder="PLAYWRIGHT_MCP_EXTENSION_TOKEN=…">
        <button class="btn sm" data-act="eye" data-pf="${n}" title="Hiện / ẩn token">👁</button>
        <button class="btn sm" data-act="luu" data-pf="${n}" title="Lưu token vào config.json">Lưu</button>
      </div>
      <div class="row">
        <button class="btn sm blue" data-act="noi" data-pf="${n}" title="Lưu token đang gõ rồi nối lại trình duyệt này (phiên đang tốt thì giữ nguyên)">🔌 Nối lại</button>
        <button class="btn sm" data-act="chophep" data-pf="${n}" title="Token đã đổi (Chrome báo 'Invalid token provided'): mở trang kết nối KHÔNG token, bạn bấm 'Allow &amp; select' trong Chrome; app tự lưu token mới">Nối &amp; Cho phép</button>
        <button class="btn sm" data-act="token" data-pf="${n}" title="Mở trang token của extension trong profile này để sao chép">Trang token</button>
      </div>
    </div>`).join('');
  function bao(r){
    const t = $('toast'); if (!r || !r.msg) return;
    t.textContent = r.msg; t.className = 'toast show' + (r.ok ? '' : ' err');
    clearTimeout(bao._t); bao._t = setTimeout(() => t.className = 'toast', 6000);
  }
  $('tds').onclick = async e => {
    const b = e.target.closest('button[data-act]'); if (!b || b.disabled) return;
    const n = b.dataset.pf, act = b.dataset.act, inp = $(n + '-token');
    if (act === 'eye') { inp.type = inp.type === 'password' ? 'text' : 'password'; return; }
    let r;
    try {
      if (act === 'luu') r = await pywebview.api.luu_token(n, inp.value);
      else if (act === 'noi') r = await pywebview.api.ket_noi_lai(n, false, inp.value);
      else if (act === 'chophep') r = await pywebview.api.ket_noi_lai(n, true, null);
      else if (act === 'token') r = await pywebview.api.mo_trang_token(n);
    } catch (err) { r = {ok: false, msg: String(err)}; }
    bao(r); tick();
  };
  $('noiTatCa').onclick = async () => { try { bao(await pywebview.api.ket_noi_lai('all', false, null)); } catch (err) { bao({ok: false, msg: String(err)}); } tick(); };
  function render(s){
    $('dot').className = 'dot' + (s.server ? ' on' : '');
    $('tt').textContent = s.server ? 'SERVER ĐANG CHẠY' : 'SERVER ĐÃ DỪNG';
    $('tt').className = 'title' + (s.server ? '' : ' off');
    $('gio').textContent = s.gio; $('url').textContent = s.url || '—';
    $('up').textContent = s.uptime; $('port').textContent = s.port || '—';
    $('cho').textContent = s.cho; $('dang').textContent = s.dang; $('xong').textContent = s.xong; $('loi').textContent = s.loi;
    $('worker').textContent = s.worker ? 'đang chạy ▶' : 'dừng';
    $('worker').className = 'chip ' + (s.worker ? 'ok' : 'wait');
    (s.trinh_duyet || []).forEach(t => {
      const prof = $(t.id + '-profile'), chip = $(t.id + '-chip'), inp = $(t.id + '-token');
      if (!prof) return;
      prof.textContent = t.profile;
      const dang = !!s.ban && (s.current || '').includes(t.ten.split(' ')[0]);   // "nối lại YouTube" / "kiểm tra Zalo"
      chip.textContent = t.ok ? 'đã nối ✔' : (dang ? 'đang nối…' : 'chưa nối');
      chip.className = 'chip ' + (t.ok ? 'ok' : (dang ? 'wait' : 'bad'));
      if (!tokenLoaded) inp.value = t.token || '';           // nạp token 1 lần, không đè lên chữ đang gõ
      const noi = document.querySelector(`#tds button[data-act="noi"][data-pf="${t.id}"]`);
      if (noi) noi.className = 'btn sm ' + (t.ok ? 'blue' : 'amber');   // vàng = chưa nối, bấm vào đây
    });
    if (s.trinh_duyet && s.trinh_duyet.length) tokenLoaded = true;
    document.querySelectorAll('#tds button[data-act="noi"], #tds button[data-act="chophep"], #noiTatCa')
      .forEach(b => b.disabled = !!s.ban);
    const ai = s.ai || {};
    $('aiBackend').textContent = ai.backend === 'chatgpt' ? '🤖 ChatGPT (Codex CLI)' : '♊ Gemini (trình duyệt)';
    const gc = $('gptChip');
    if (!ai.gpt_da_kiem_tra){ gc.textContent = 'chưa kiểm tra'; gc.className = 'chip wait'; }
    else { gc.textContent = ai.gpt_ok ? 'đã đăng nhập ✔' : 'chưa sẵn sàng'; gc.className = 'chip ' + (ai.gpt_ok ? 'ok' : 'bad'); }
    $('gptNote').textContent = ai.gpt_ok ? (ai.gpt_email || '') : (ai.gpt_ghi_chu || '');
    const seo = s.seo || {};
    $('seoRun').textContent = seo.running ? 'đang chạy ▶' : 'nghỉ';
    $('seoRun').className = 'chip ' + (seo.running ? 'ok' : 'wait');
    $('seoCnt').textContent = (seo.cho + seo.dang + seo.xong + seo.loi) ? `${seo.cho} chờ · ${seo.dang} đang làm · ${seo.xong} xong · ${seo.loi} lỗi` : '—';
    $('cur').textContent = seo.buoc ? '⏳ ' + seo.buoc : (s.current ? '⏳ ' + s.current : '');
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
  $('stop').onclick = () => {   // bấm 1 lần là dừng, không hỏi lại (user 02/11/2026)
    $('stop').disabled = true; $('stop').textContent = 'Đang dừng...'; pywebview.api.dung();
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
        resizable=True, min_size=(860, 480), background_color="#111827")
    _WINDOW.events.closed += api.dung_server                     # bấm X cũng dừng server

    def sau_khi_mo():
        api.khoi_dong(mo_trinh_duyet=not args.khong_mo)
        if args.chup:
            threading.Thread(target=_chup_man_hinh, args=(_WINDOW, args.chup), daemon=True).start()

    webview.start(sau_khi_mo, private_mode=False)
    api.dung_server()
    t = getattr(api, "_ngat", None)
    if t is not None:
        t.join(6)               # chờ đóng tab điều khiển xong rồi mới thoát
    sys.stdout.flush()
    os._exit(0)                 # thread server/worker daemon -> thoát thẳng cho gọn


if __name__ == "__main__":
    main()
