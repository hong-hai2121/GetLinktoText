# -*- coding: utf-8 -*-
"""Cửa sổ "Kết nối AI": xem Claude / GPT / Gemini đã đăng nhập chưa, bấm Kết nối để đăng nhập
(trình duyệt mở trang đăng nhập của hãng -> chọn "Tiếp tục bằng Google" hoặc cách khác), và ô hỏi thử.

Chạy:  pythonw ket_noi_ai.py   (hoặc bấm đúp mo_ket_noi_ai.bat)
  - Mỗi dòng: đèn xanh "Đã kết nối — email · gói" / đỏ "Chưa kết nối" / xám "Chưa cài".
  - Nút Kết nối: mở cửa sổ lệnh chạy lệnh đăng nhập của CLI đó (claude auth login / codex login /
    gemini); đăng nhập xong trong trình duyệt thì đèn tự chuyển xanh (tự dò lại mỗi vài giây).
  - Nút Ngắt: đăng xuất CLI đó. Nút Cài đặt: chạy npm install trong cửa sổ lệnh.
  - Ô hỏi thử: chọn hãng, gõ câu hỏi, Gửi -> trả lời hiện bên dưới (nhớ ngữ cảnh tới khi bấm Hội thoại mới).
Các tool khác dùng chung 3 module: hoi_claude.py / hoi_gpt.py / hoi_gemini.py (cùng khuôn hoi(), Phien).

Bẫy pywebview: lớp Api chỉ được có phương thức public; KHÔNG gán Window vào thuộc tính public.
Kiểm thử không cần nhìn: python ket_noi_ai.py --chup anh.png  (mở, chờ 4s, chụp cửa sổ, thoát).
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

import webview

import hoi_claude
import hoi_gemini
import hoi_gpt

NHA = {"claude": hoi_claude, "gpt": hoi_gpt, "gemini": hoi_gemini}   # thứ tự hiện trên cửa sổ
W, H = 560, 660
TIEU_DE = "Kết nối AI — Claude / GPT / Gemini"
CHU_KY_DO = 8.0                 # giây giữa hai lần dò trạng thái (mỗi lần gọi 2 lệnh CLI ~1-3s)
CHU_KY_NHANH = 2.5              # sau khi bấm Kết nối thì dò dày hơn trong NHANH_TRONG giây
NHANH_TRONG = 180

_WINDOW = None


class Api:
    """JS gọi qua pywebview.api.<tên>(). Trạng thái được dò ở thread nền, JS chỉ đọc bản mới nhất."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tt: dict[str, dict] = {k: dict(ten=m.TEN, cli=m.CLI, cai=None, ket_noi=False, email="", ghi_chu="đang dò...")
                                     for k, m in NHA.items()}
        self._luc_do = 0.0
        self._nhanh_den = 0.0
        self._do_ngay = threading.Event()
        self._phien = {k: None for k in NHA}       # Phien hỏi thử theo hãng
        self._dang_hoi: set[str] = set()
        self._loi_xac_thuc: dict[str, str] = {}    # hãng -> lỗi token/đăng nhập gặp khi hỏi (đèn vàng, nhắc đăng nhập lại)
        threading.Thread(target=self._vong_do, daemon=True, name="do-trang-thai").start()

    # ---- dò trạng thái ở nền
    def _do_mot_lan(self):
        for k, m in NHA.items():
            try:
                tt = m.trang_thai()
            except Exception as e:                 # noqa: BLE001
                tt = dict(ten=m.TEN, cli=m.CLI, cai=False, ket_noi=False, email="", ghi_chu=f"lỗi dò: {e}")
            with self._lock:
                self._tt[k] = tt
        with self._lock:
            self._luc_do = time.time()

    def _vong_do(self):
        while True:
            self._do_mot_lan()
            chu_ky = CHU_KY_NHANH if time.time() < self._nhanh_den else CHU_KY_DO
            self._do_ngay.wait(chu_ky)
            self._do_ngay.clear()

    # ---- JS gọi
    def trang_thai(self):
        with self._lock:
            return {"nha": [dict(self._tt[k], ma=k, dang_hoi=(k in self._dang_hoi), loi_xac_thuc=self._loi_xac_thuc.get(k, ""))
                            for k in NHA],
                    "luc_do": time.strftime("%H:%M:%S", time.localtime(self._luc_do)) if self._luc_do else "",
                    "gio": time.strftime("%H:%M:%S")}

    def lam_moi(self):
        self._do_ngay.set()
        return True

    def ket_noi(self, ma):
        m = NHA[ma]
        try:
            m.dang_nhap()
        except Exception as e:                     # noqa: BLE001
            return {"ok": False, "msg": str(e)}
        self._nhanh_den = time.time() + NHANH_TRONG
        self._loi_xac_thuc.pop(ma, None)
        self._do_ngay.set()
        return {"ok": True, "msg": f"Đã mở cửa sổ đăng nhập {m.TEN}. Trong trình duyệt chọn tài khoản (Google) rồi quay lại đây."}

    def ngat(self, ma):
        m = NHA[ma]
        try:
            msg = m.dang_xuat()
        except Exception as e:                     # noqa: BLE001
            return {"ok": False, "msg": str(e)}
        self._phien[ma] = None
        self._do_ngay.set()
        return {"ok": True, "msg": f"Đã ngắt {m.TEN}. {msg}".strip()}

    def cai_dat(self, ma):
        m = NHA[ma]
        m.cai_dat()
        self._nhanh_den = time.time() + NHANH_TRONG
        return {"ok": True, "msg": f"Đang cài {m.TEN} CLI trong cửa sổ lệnh: {m.LENH_CAI}"}

    def hoi(self, ma, cau_hoi):
        m = NHA[ma]
        cau_hoi = (cau_hoi or "").strip()
        if not cau_hoi:
            return {"ok": False, "msg": "Chưa gõ câu hỏi."}
        with self._lock:
            if ma in self._dang_hoi:
                return {"ok": False, "msg": f"{m.TEN} đang trả lời câu trước."}
            self._dang_hoi.add(ma)
        try:
            if self._phien[ma] is None:
                self._phien[ma] = m.Phien()
            t0 = time.time()
            text = self._phien[ma].hoi(cau_hoi)
            r = self._phien[ma].lich_su[-1]
            self._loi_xac_thuc.pop(ma, None)
            return {"ok": True, "text": text, "model": r.model, "giay": round(time.time() - t0, 1)}
        except Exception as e:                     # noqa: BLE001
            msg = str(e)
            # token hết hạn / chưa đăng nhập: `auth status` vẫn báo đã đăng nhập, chỉ lúc hỏi mới lộ ra
            if any(t in msg.lower() for t in ("expired", "authenticate", "unauthorized", "401", "chưa đăng nhập", "login")):
                self._loi_xac_thuc[ma] = msg.splitlines()[0][:160]
            return {"ok": False, "msg": msg}
        finally:
            with self._lock:
                self._dang_hoi.discard(ma)

    def hoi_thoai_moi(self, ma):
        self._phien[ma] = None
        return True

    def dong(self):
        if _WINDOW is not None:
            threading.Timer(0.2, _WINDOW.destroy).start()
        return True


HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Kết nối AI</title>
<style>
  :root{--bg:#111827;--card:#1f2937;--line:#263142;--fg:#e5e7eb;--dim:#9ca3af;
        --green:#16a34a;--red:#dc2626;--blue:#2563eb;--amber:#d97706;--gray:#4b5563}
  *{box-sizing:border-box} html,body{height:100%;margin:0}
  body{background:var(--bg);color:var(--fg);font:13px/1.45 "Segoe UI",system-ui,sans-serif;
       display:flex;flex-direction:column;padding:14px;gap:10px;user-select:none}
  h1{margin:0;font-size:14px;letter-spacing:.1em} .sub{color:var(--dim);font-size:12px;margin-top:2px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .row{display:flex;align-items:center;gap:10px}
  .grow{flex:1;min-width:0}
  .nha{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}
  .nha:last-child{border-bottom:0;padding-bottom:0} .nha:first-child{padding-top:0}
  .dot{width:13px;height:13px;border-radius:50%;background:var(--gray);flex:none}
  .dot.on{background:var(--green);box-shadow:0 0 0 3px rgba(22,163,74,.25)}
  .dot.off{background:var(--red)} .dot.no{background:var(--gray)} .dot.wait{background:var(--amber)}
  .ten{font-weight:700;font-size:14px;width:70px;flex:none}
  .tt{font-size:12.5px} .tt .k{color:var(--dim)} .tt b{font-weight:600}
  .tt .ok{color:#86efac} .tt .bad{color:#fca5a5} .tt .no{color:#d1d5db}
  .mono{font-family:Consolas,"Cascadia Mono",monospace} .dim{color:var(--dim)} .small{font-size:11.5px}
  .btn{border:1px solid #374151;background:#111827;color:var(--fg);border-radius:8px;padding:6px 12px;
       cursor:pointer;font:inherit;white-space:nowrap}
  .btn:hover{background:#0b1220} .btn.sm{padding:4px 9px;font-size:12px} .btn:disabled{opacity:.45;cursor:default}
  .btn.blue{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600} .btn.blue:hover{background:#1d4ed8}
  .btn.red{background:#7f1d1d;border-color:#991b1b;color:#fee2e2} .btn.red:hover{background:#991b1b}
  .btn.amber{background:#78350f;border-color:#92400e;color:#fde68a}
  .chips{display:flex;gap:6px} .chip{padding:4px 11px;border-radius:999px;border:1px solid #374151;cursor:pointer;font-size:12px}
  .chip.on{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
  textarea{width:100%;min-height:64px;resize:vertical;background:#0b1220;color:var(--fg);border:1px solid var(--line);
           border-radius:8px;padding:8px 10px;font:inherit;user-select:text}
  textarea:focus{outline:2px solid #1e3a8a}
  pre{flex:1;margin:0;overflow:auto;background:#0b1220;border:1px solid var(--line);border-radius:8px;min-height:110px;
      padding:8px 10px;font:12.5px/1.5 "Segoe UI",system-ui,sans-serif;color:#d1d5db;white-space:pre-wrap;word-break:break-word;user-select:text}
  .qa{flex:1;display:flex;flex-direction:column;gap:8px;min-height:0}
  #toast{position:fixed;left:14px;right:14px;bottom:14px;background:#0b1220;border:1px solid #374151;color:#fff;padding:9px 12px;
         border-radius:10px;font-size:12.5px;opacity:0;transform:translateY(8px);transition:all .2s;pointer-events:none}
  #toast.show{opacity:1;transform:none} #toast.err{border-color:#991b1b;background:#450a0a}
  .foot{display:flex;justify-content:space-between;align-items:center;color:var(--dim);font-size:11.5px}
</style></head><body>
  <div>
    <h1>KẾT NỐI AI</h1>
    <div class="sub">Đăng nhập bằng tài khoản đang có (chọn <b>Tiếp tục bằng Google</b> trên trang đăng nhập) — không cần API key.</div>
  </div>

  <div class="card" id="ds">(đang dò trạng thái…)</div>

  <div class="card qa">
    <div class="row">
      <div class="chips" id="chips"></div>
      <span class="grow"></span>
      <button class="btn sm" id="moi">Hội thoại mới</button>
    </div>
    <textarea id="cau" placeholder="Gõ câu hỏi thử rồi bấm Gửi (Ctrl+Enter)…"></textarea>
    <div class="row">
      <span id="tl" class="dim small grow"></span>
      <button class="btn blue" id="gui">Gửi</button>
    </div>
    <pre id="dap">(câu trả lời hiện ở đây)</pre>
  </div>

  <div class="foot">
    <span>Dò lại lúc <span id="luc" class="mono">—</span> · <button class="btn sm" id="refresh">Làm mới</button></span>
    <span id="gio" class="mono">--:--:--</span>
  </div>
  <div id="toast"></div>

<script>
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let chon = 'claude', lastKey = '', toastT = 0, busy = false;
  function toast(msg, err){ const t = $('toast'); t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
    clearTimeout(toastT); toastT = setTimeout(() => t.className = '', 4500); }
  function hang(n){
    let dot = 'no', tt = '', nut = '';
    if (n.cai === null){ dot = 'wait'; tt = `<span class="no">Đang dò…</span>`; }
    else if (!n.cai){ dot = 'no'; tt = `<span class="no">Chưa cài ${esc(n.cli)}</span> <span class="k">· ${esc(n.ghi_chu)}</span>`;
      nut = `<button class="btn sm amber" onclick="act('cai_dat','${n.ma}')">Cài đặt</button>`; }
    else if (n.ket_noi && n.loi_xac_thuc){ dot = 'wait';
      tt = `<span style="color:#fcd34d">▲ Đã đăng nhập nhưng hỏi bị từ chối</span> — <b>${esc(n.email)}</b><div class="k small">${esc(n.loi_xac_thuc)}</div>`;
      nut = `<button class="btn sm blue" onclick="act('ket_noi','${n.ma}')">Đăng nhập lại</button> <button class="btn sm red" onclick="ngat('${n.ma}')">Ngắt</button>`; }
    else if (n.ket_noi){ dot = 'on'; tt = `<span class="ok">● Đã kết nối</span> — <b>${esc(n.email || '(không rõ tài khoản)')}</b>` +
        (n.ghi_chu ? ` <span class="k">· ${esc(n.ghi_chu)}</span>` : '');
      nut = `<button class="btn sm" onclick="act('ket_noi','${n.ma}')">Đăng nhập lại</button> <button class="btn sm red" onclick="ngat('${n.ma}')">Ngắt</button>`; }
    else { dot = 'off'; tt = `<span class="bad">○ Chưa kết nối</span>` + (n.ghi_chu ? ` <span class="k">· ${esc(n.ghi_chu)}</span>` : '');
      nut = `<button class="btn sm blue" onclick="act('ket_noi','${n.ma}')">Kết nối</button>`; }
    const ver = n.phien_ban ? `<div class="k small mono">${esc(n.cli)} ${esc(n.phien_ban)}</div>` : '';
    return `<div class="nha"><div class="dot ${dot}"></div><div class="ten">${esc(n.ten)}</div>
      <div class="grow tt">${tt}${ver}</div><div>${nut}</div></div>`;
  }
  function render(s){
    const key = JSON.stringify(s.nha);
    if (key !== lastKey){ lastKey = key; $('ds').innerHTML = s.nha.map(hang).join(''); }
    $('luc').textContent = s.luc_do || '—'; $('gio').textContent = s.gio;
    $('chips').innerHTML = s.nha.map(n => `<span class="chip${n.ma === chon ? ' on' : ''}" onclick="chon='${n.ma}';tick()">${esc(n.ten)}${n.ket_noi ? '' : ' ○'}</span>`).join('');
  }
  async function tick(){ try { render(await pywebview.api.trang_thai()); } catch(e){} }
  async function act(fn, ma){ const r = await pywebview.api[fn](ma); toast(r.msg, !r.ok); tick(); }
  async function ngat(ma){ if (!confirm('Ngắt kết nối ' + ma + '? (đăng xuất CLI đó)')) return; await act('ngat', ma); }
  async function gui(){
    if (busy) return; const cau = $('cau').value.trim(); if (!cau) return toast('Chưa gõ câu hỏi.', true);
    busy = true; $('gui').disabled = true; $('tl').textContent = 'Đang hỏi ' + chon + '…'; $('dap').textContent = '…';
    try{ const r = await pywebview.api.hoi(chon, cau);
      if (r.ok){ $('dap').textContent = r.text; $('tl').textContent = `${chon} trả lời sau ${r.giay}s` + (r.model ? ` · ${r.model}` : ''); }
      else { $('dap').textContent = 'LỖI: ' + r.msg; $('tl').textContent = ''; }
    } catch(e){ $('dap').textContent = 'Lỗi gọi: ' + e; }
    busy = false; $('gui').disabled = false;
  }
  $('gui').onclick = gui;
  $('cau').addEventListener('keydown', e => { if (e.ctrlKey && e.key === 'Enter') gui(); });
  $('moi').onclick = async () => { await pywebview.api.hoi_thoai_moi(chon); $('dap').textContent = '(hội thoại mới)'; toast('Đã bắt đầu hội thoại mới với ' + chon); };
  $('refresh').onclick = () => { pywebview.api.lam_moi(); toast('Đang dò lại…'); };
  function batDau(){ tick(); setInterval(tick, 1000); }
  if (window.pywebview && window.pywebview.api) batDau(); else window.addEventListener('pywebviewready', batDau);
</script></body></html>"""


def _chup_man_hinh(win, duong_dan: str, cho: float = 4.0):
    """Chụp vùng cửa sổ ra file (kiểm thử tự động) rồi đóng cửa sổ."""
    time.sleep(cho)
    try:
        import ctypes
        from ctypes import wintypes
        from PIL import ImageGrab
        hwnd = ctypes.windll.user32.FindWindowW(None, TIEU_DE)
        if hwnd:
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            bbox = (r.left, r.top, r.right, r.bottom)
        else:
            bbox = (win.x, win.y, win.x + win.width + 16, win.y + win.height + 40)
        ImageGrab.grab(bbox=bbox, all_screens=True).save(duong_dan)
    except Exception as e:                       # noqa: BLE001
        print("Chụp lỗi:", e)
    win.destroy()


def main():
    global _WINDOW
    ap = argparse.ArgumentParser(description="Cửa sổ kết nối Claude / GPT / Gemini")
    ap.add_argument("--chup", help="(kiểm thử) chụp cửa sổ ra file PNG sau 4s rồi thoát")
    args = ap.parse_args()

    api = Api()
    sw, sh = (webview.screens[0].width, webview.screens[0].height) if webview.screens else (1920, 1080)
    _WINDOW = webview.create_window(
        TIEU_DE, html=HTML, js_api=api, width=W, height=H,
        x=max(0, (sw - W) // 2), y=max(0, (sh - H) // 2),       # canh giữa màn hình
        resizable=True, min_size=(460, 520), background_color="#111827")

    def sau_khi_mo():
        if args.chup:
            threading.Thread(target=_chup_man_hinh, args=(_WINDOW, args.chup), daemon=True).start()

    webview.start(sau_khi_mo, private_mode=False)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
