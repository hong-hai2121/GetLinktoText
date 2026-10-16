# -*- coding: utf-8 -*-
"""Dò DOM trang đăng video của từng nền tảng (chỉ ĐỌC, không tải video) — công cụ phát triển.

Chạy:  python do_dom.py tiktok|zalo|youtube [--url URL] [--out THU_MUC]
  1. Nối Playwright vào trình duyệt đang mở của nền tảng đó (profile + token trong config.json,
     xem chrome_cdp.platform_config) — thêm một tab "connect", không đóng gì.
  2. In các tab bạn đang mở trong profile đó (relay biết qua chrome.tabs.onCreated).
  3. Điều hướng tab điều khiển tới trang upload (mặc định theo nền tảng, --url để đổi),
     rồi với TỪNG frame: liệt kê input[type=file] (accept/multiple/hiển thị), nút bấm,
     ô nhập (textarea/contenteditable/input text) kèm placeholder/aria-label, iframe.
  4. Lưu screenshot + HTML từng frame vào --out để xem lại; in bảng tóm tắt ra màn hình.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import chrome_cdp

URL_MAC_DINH = {   # trang user đưa (15/10) + trang upload tương ứng; --url (lặp được) để đổi
    "tiktok": ["https://www.tiktok.com/tiktokstudio/content",
               "https://www.tiktok.com/tiktokstudio/upload"],
    "youtube": ["https://studio.youtube.com/channel/UCIBnAlhXefIlNzh6fJKGtEw/videos/upload"],
    "zalo": ["https://video.zalo.me/creator/video"],
}
# trang để CHỌN FILE (--file): tới thẳng chỗ có input[type=file]
URL_CHON_FILE = {
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    "youtube": "https://www.youtube.com/upload",          # mở sẵn hộp thoại tải lên của Studio
    "zalo": "https://video.zalo.me/creator/video",         # cần --click "Đăng video" để hiện modal
}

# tìm input[type=file] kể cả trong shadow DOM (YouTube Studio) -> trả về phần tử
JS_TIM_INPUT_FILE = r"""
() => {
  const deep = (root, sel) => {
    const el = root.querySelector(sel); if (el) return el;
    for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) { const r = deep(e.shadowRoot, sel); if (r) return r; }
    }
    return null;
  };
  return deep(document, 'input[type=file]');
}
"""

JS_TOM_TAT = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  const sel = el => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (el.className && typeof el.className === 'string') ? el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    if (cls) s += '.' + cls;
    for (const a of ['data-e2e', 'data-testid', 'aria-label', 'name', 'placeholder']) {
      const v = el.getAttribute(a); if (v) { s += `[${a}="${v.slice(0, 40)}"]`; break; }
    }
    return s;
  };
  const files = [...document.querySelectorAll('input[type=file]')].map(el => ({
    sel: sel(el), accept: el.accept, multiple: el.multiple, visible: vis(el) }));
  const buttons = [...document.querySelectorAll('button, [role=button]')].filter(vis).slice(0, 80).map(el => ({
    sel: sel(el), text: txt(el), disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true' }));
  const inputs = [...document.querySelectorAll('textarea, [contenteditable=true], [contenteditable=""], input:not([type=file]):not([type=hidden]), [role=textbox]')]
    .filter(vis).slice(0, 40).map(el => ({ sel: sel(el), type: el.type || el.tagName.toLowerCase(),
      placeholder: el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('data-placeholder') || '',
      text: txt(el) }));
  const iframes = [...document.querySelectorAll('iframe')].map(el => ({ sel: sel(el), src: (el.src || '').slice(0, 120), visible: vis(el) }));
  const heads = [...document.querySelectorAll('h1,h2,h3')].filter(vis).slice(0, 15).map(txt);
  return { title: document.title, url: location.href, files, buttons, inputs, iframes, heads,
           body_chars: (document.body && document.body.innerText || '').length };
}
"""


def tom_tat_frame(frame):
    try:
        return frame.evaluate(JS_TOM_TAT)
    except Exception as e:                  # noqa: BLE001
        return {"loi": str(e)[:200], "url": frame.url}


def do_trang(page, out, nhan, args):
    """Dò mọi frame của trang hiện tại, lưu screenshot/HTML/json với tiền tố `nhan`."""
    page.screenshot(path=str(out / f"{nhan}.png"), full_page=False)
    ket_qua = {}
    for k, fr in enumerate(page.frames):
        tag = "main" if fr == page.main_frame else f"frame{k}"
        s = tom_tat_frame(fr)
        ket_qua[tag] = s
        in_tom_tat(f"{nhan} {tag}", s)
        try:
            (out / f"{nhan}_{tag}.html").write_text(fr.content(), encoding="utf-8")
        except Exception as e:              # noqa: BLE001
            print(f"   (không lưu được HTML {tag}: {str(e)[:80]})")
    (out / f"{nhan}_tom_tat.json").write_text(json.dumps(ket_qua, ensure_ascii=False, indent=1), encoding="utf-8")


def chon_file(page, duong_dan: str):
    """Gán file vào input[type=file] (kể cả trong shadow DOM) — KHÔNG mở hộp thoại Windows,
    KHÔNG bấm nút đăng. Trả về mô tả input đã dùng.

    Đường chính: DOM.setFileInputFiles gửi thẳng qua relay (giống youtube_upload._set_file_via_cdp):
    chỉ chuyển ĐƯỜNG DẪN, trình duyệt tự đọc file nên không vướng giới hạn 50 MB mà Playwright
    áp cho trình duyệt nối qua connect_over_cdp. Dự phòng: set_input_files của Playwright."""
    h = page.evaluate_handle(JS_TIM_INPUT_FILE)
    el = h.as_element()
    if el is None:
        raise RuntimeError("Không tìm thấy input[type=file] trên trang (kể cả shadow DOM).")
    mo_ta = el.evaluate("e => (e.name ? 'name=' + e.name + ' ' : '') + 'accept=' + e.accept + ' multiple=' + e.multiple")
    try:
        bieu_thuc = "(" + JS_TIM_INPUT_FILE.strip() + ")()"
        res = chrome_cdp.cdp_send("Runtime.evaluate", {"expression": bieu_thuc, "returnByValue": False})
        obj = (res.get("result") or {}).get("objectId")
        if not obj:
            raise RuntimeError("Runtime.evaluate không trả objectId của input")
        chrome_cdp.cdp_send("DOM.setFileInputFiles", {"files": [str(Path(duong_dan))], "objectId": obj})
        return mo_ta + "  (qua CDP DOM.setFileInputFiles)"
    except Exception as e:                  # noqa: BLE001
        print(f"    (CDP không được: {str(e)[:120]} -> thử set_input_files của Playwright, giới hạn 50 MB)")
        el.set_input_files(duong_dan, timeout=15000)
        return mo_ta + "  (qua Playwright set_input_files)"


def vong_cho_lenh(page, out, args):
    """--giu: giữ Playwright nối, mỗi giây đọc file lenh.txt trong thư mục out rồi xóa.
    Lệnh mỗi dòng:  dom | shot | click <chữ trên nút> | fill <css> <chữ> | js <mã JS> | goto <url> | thoat"""
    f = out / "lenh.txt"
    print(f"\n*** Đang giữ kết nối. Ghi lệnh vào {f} (dom / shot / click <chữ> / fill <css> <chữ> / js <mã> / goto <url> / thoat)")
    sys.stdout.flush()
    n = 0
    while True:
        time.sleep(1.0)
        if not f.exists():
            continue
        try:
            dong = [d.strip() for d in f.read_text(encoding="utf-8").splitlines() if d.strip()]
            f.unlink()
        except Exception:
            continue
        for lenh in dong:
            n += 1
            print(f"\n>>> lệnh {n}: {lenh}")
            try:
                tu = lenh.split(" ", 1)
                if tu[0] == "thoat":
                    return
                if tu[0] == "dom":
                    do_trang(page, out, f"lenh{n}", args)
                elif tu[0] == "shot":
                    page.screenshot(path=str(out / f"lenh{n}.png")); print(f"   -> {out / f'lenh{n}.png'}")
                elif tu[0] == "click":
                    page.get_by_role("button", name=tu[1]).first.click(timeout=10000); time.sleep(2)
                    page.screenshot(path=str(out / f"lenh{n}.png")); print("   đã bấm")
                elif tu[0] == "fill":
                    css, chu = tu[1].split(" ", 1)
                    page.locator(css).first.fill(chu, timeout=10000); print("   đã điền")
                elif tu[0] == "js":
                    print("   ->", json.dumps(page.evaluate(tu[1]), ensure_ascii=False)[:2000])
                elif tu[0] == "goto":
                    page.goto(tu[1], wait_until="domcontentloaded", timeout=60000); print("   đã tới", page.url)
                elif tu[0] == "py":
                    # chạy một file Python với biến sẵn: page, out, chrome_cdp (điền form nhiều dòng,
                    # dùng lại helper của youtube_upload...). File do mình viết, không phải dữ liệu web.
                    ma = Path(tu[1]).read_text(encoding="utf-8")
                    exec(compile(ma, tu[1], "exec"), {"page": page, "out": out, "chrome_cdp": chrome_cdp,
                                                      "print": print, "__name__": "__lenh__"})
                    print("   py xong")
                else:
                    print("   lệnh lạ, bỏ qua")
            except Exception as e:          # noqa: BLE001
                print("   LỖI:", str(e)[:300])
            sys.stdout.flush()


def in_tom_tat(tag, s):
    print(f"\n--- [{tag}] {s.get('title', '')!r}  {s.get('url', '')}")
    if "loi" in s:
        print("   lỗi:", s["loi"]); return
    print(f"   chữ trong body: {s['body_chars']} ký tự; tiêu đề: {s['heads']}")
    print(f"   input[type=file]: {len(s['files'])}")
    for f in s["files"]:
        print(f"     - {f['sel']}  accept={f['accept']!r} multiple={f['multiple']} hiển_thị={f['visible']}")
    print(f"   ô nhập: {len(s['inputs'])}")
    for i in s["inputs"]:
        print(f"     - {i['sel']}  ({i['type']}) placeholder={i['placeholder']!r} text={i['text']!r}")
    print(f"   nút (hiển thị): {len(s['buttons'])}")
    for b in s["buttons"]:
        print(f"     - {b['sel']}  {b['text']!r}{'  [disabled]' if b['disabled'] else ''}")
    print(f"   iframe: {len(s['iframes'])}")
    for i in s["iframes"]:
        print(f"     - {i['sel']}  src={i['src']!r} hiển_thị={i['visible']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nen_tang", choices=["tiktok", "zalo", "youtube"])
    ap.add_argument("--url", action="append", help="trang cần dò, lặp lại được (mặc định theo nền tảng)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "dom_dump"))
    ap.add_argument("--cho", type=float, default=6.0, help="giây chờ trang tải xong trước khi dò")
    ap.add_argument("--click", help="sau khi dò trang, bấm nút có chữ này (vd 'Đăng video') rồi dò lại — "
                                    "chỉ mở hộp thoại, không chọn file")
    ap.add_argument("--file", help="gán file video này vào input[type=file] của trang (tới URL_CHON_FILE "
                                   "của nền tảng), chờ --cho-upload giây rồi dò form hiện ra; KHÔNG bấm đăng")
    ap.add_argument("--cho-upload", type=float, default=25.0, help="giây chờ sau khi chọn file (mặc định 25)")
    ap.add_argument("--giu", action="store_true", help="xong thì giữ kết nối, đọc lệnh từ <out>/lenh.txt")
    ap.add_argument("--giu-tab", action="store_true", help="khi thoát KHÔNG đóng tab điều khiển (mặc định đóng)")
    args = ap.parse_args()

    out = Path(args.out) / args.nen_tang
    out.mkdir(parents=True, exist_ok=True)
    cfg = chrome_cdp.platform_config(chrome_cdp.load_config(), args.nen_tang)
    print(f"Nền tảng {args.nen_tang}: profile '{cfg['profile_dir']}' @ {cfg['user_data_dir']}")

    relay = chrome_cdp.launch_chrome(cfg, log=lambda m: print("  ", m))
    tabs = list(getattr(getattr(relay, "_model", None), "_known_tabs", {}).values())
    print(f"\nTab đang mở trong profile ({len(tabs)}):")
    for t in tabs:
        print(f"   - {str(t.get('title', ''))[:60]!r}  {str(t.get('url', ''))[:110]}")

    urls = args.url or ([URL_CHON_FILE[args.nen_tang]] if args.file else URL_MAC_DINH[args.nen_tang])

    pw, browser, page = chrome_cdp.connect_playwright(cfg, log=lambda m: print("  ", m))
    try:
        for n, url in enumerate(urls, 1):
            print(f"\n{'=' * 70}\nTRANG {n}/{len(urls)}: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(args.cho)
            page.screenshot(path=str(out / f"trang{n}.png"), full_page=False)
            ket_qua = {}
            for k, fr in enumerate(page.frames):
                tag = "main" if fr == page.main_frame else f"frame{k}"
                s = tom_tat_frame(fr)
                ket_qua[tag] = s
                in_tom_tat(tag, s)
                try:
                    (out / f"trang{n}_{tag}.html").write_text(fr.content(), encoding="utf-8")
                except Exception as e:          # noqa: BLE001
                    print(f"   (không lưu được HTML {tag}: {str(e)[:80]})")
            (out / f"trang{n}_tom_tat.json").write_text(json.dumps(ket_qua, ensure_ascii=False, indent=1), encoding="utf-8")
            if args.click:
                print(f"\n>>> Bấm nút {args.click!r} rồi dò lại (không chọn file)...")
                page.get_by_role("button", name=args.click).first.click(timeout=10000)
                time.sleep(args.cho)
                page.screenshot(path=str(out / f"trang{n}_sau_click.png"), full_page=False)
                ket_qua = {}
                for k, fr in enumerate(page.frames):
                    tag = "main" if fr == page.main_frame else f"frame{k}"
                    s = tom_tat_frame(fr)
                    ket_qua[tag] = s
                    in_tom_tat(tag + " sau click", s)
                    try:
                        (out / f"trang{n}_sau_click_{tag}.html").write_text(fr.content(), encoding="utf-8")
                    except Exception as e:      # noqa: BLE001
                        print(f"   (không lưu được HTML {tag}: {str(e)[:80]})")
                (out / f"trang{n}_sau_click_tom_tat.json").write_text(
                    json.dumps(ket_qua, ensure_ascii=False, indent=1), encoding="utf-8")
            if args.file:
                print(f"\n>>> Chọn file vào input (không bấm đăng): {args.file}")
                print("    input:", chon_file(page, args.file))
                print(f"    chờ {args.cho_upload:g}s cho form hiện ra...")
                sys.stdout.flush()
                time.sleep(args.cho_upload)
                do_trang(page, out, f"trang{n}_sau_file", args)
        print(f"\nĐã lưu screenshot + HTML + tom_tat.json vào {out}")
        sys.stdout.flush()
        if args.giu:
            vong_cho_lenh(page, out, args)
    finally:
        if args.giu_tab:
            chrome_cdp.disconnect(pw)
            print("Đã ngắt Playwright (tab để mở theo --giu-tab).")
        else:
            dong = chrome_cdp.close_tab(page)
            chrome_cdp.disconnect(pw)
            print("Đã ngắt Playwright; đóng tab điều khiển:", "OK" if dong else "KHÔNG đóng được")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
