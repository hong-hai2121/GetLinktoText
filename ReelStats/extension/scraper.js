/* ============================================================================
 * ReelStats — content script
 * Cuộn trang Facebook và gom video/reel trong feed.
 *
 * Chạy trên: /<page>/reels/, /<page>/videos/, /search/videos?q=..., /watch/...
 * Nhận lệnh từ popup qua chrome.runtime.onMessage:
 *   {cmd:'ping'}              -> {ok, running, count}
 *   {cmd:'start', cfg}        -> bắt đầu gom
 *   {cmd:'stop'}              -> dừng giữa chừng (giữ lại phần đã gom)
 * Bắn ngược về popup: {evt:'progress'|'done', count, rows?}
 * ========================================================================== */

(() => {
  if (window.__reelStatsLoaded) return;
  window.__reelStatsLoaded = true;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // FB chèn ký tự vô hình (U+034F…) và span mồi để chống copy. innerText đã bỏ
  // span ẩn theo CSS, còn ký tự vô hình thì phải tự lọc.
  const INVISIBLE = /[\u034f\u200b-\u200f\u2060\ufeff]/g;
  const clean = s => (s || '').replace(INVISIBLE, '').replace(/\u00a0/g, ' ')
                              .replace(/[ \t]+/g, ' ').trim();
  const txt = el => clean(el?.innerText || '');

  // ── Chế độ trang ──────────────────────────────────────────────────────────
  // 'video' = lưới thước phim / video (thẻ video, có lượt xem)
  // 'post'  = feed bài viết (search/top, search/posts, trang cá nhân, nhóm…)
  function detectMode() {
    const p = location.pathname;
    if (/^\/search\/(videos|reels)/.test(p)) return 'video';
    if (/^\/search\//.test(p)) return 'post';
    if (/\/(reels|videos|watch)\/?$/.test(p)) return 'video';
    return 'post';
  }

  // Bỏ tham số theo dõi FB nhét vào link (__cft__, __tn__, mibextid…).
  function cleanUrl(href) {
    let u;
    try { u = new URL(href, location.origin); } catch { return href; }
    for (const k of [...u.searchParams.keys()]) {
      if (/^__|^_rdr$|^mibextid$|^rdid$|^share_url|^extid$|^notif|^ref$|^refid$|^external_log_id$/.test(k)) {
        u.searchParams.delete(k);
      }
    }
    const q = u.searchParams.toString();
    return u.origin + u.pathname + (q ? '?' + q : '');
  }

  // ── Nhận diện link video ──────────────────────────────────────────────────
  function videoInfo(href) {
    let u;
    try { u = new URL(href, location.origin); } catch { return null; }
    if (!/(^|\.)facebook\.com$/.test(u.hostname)) return null;

    let m = u.pathname.match(/\/reel\/(\d+)/);
    if (m) return { id: m[1], type: 'reel', url: `https://www.facebook.com/reel/${m[1]}/` };

    m = u.pathname.match(/\/videos\/(?:[^/]+\/)?(\d+)/);
    if (m) return { id: m[1], type: 'video', url: `https://www.facebook.com/watch/?v=${m[1]}` };

    if (u.pathname.startsWith('/watch')) {
      const v = u.searchParams.get('v');
      if (v) return { id: v, type: 'watch', url: `https://www.facebook.com/watch/?v=${v}` };
    }
    return null;
  }

  // ── "1,7 triệu" / "712K" / "12.345" -> số nguyên ──────────────────────────
  const UNITS = { 'triệu': 1e6, 'tr': 1e6, 'm': 1e6, 'nghìn': 1e3, 'k': 1e3, 'tỷ': 1e9, 'b': 1e9 };

  function parseCount(raw) {
    if (!raw) return null;
    const s = raw.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
    const m = s.match(/([\d.,]+)\s*(triệu|nghìn|tỷ|tr|k|m|b)?/);
    if (!m) return null;

    const unit = m[2] || '';
    let n;
    if (unit) {
      // Có đơn vị -> số thập phân kiểu VN, dấu phẩy là dấu thập phân.
      n = parseFloat(m[1].replace(/\./g, '').replace(',', '.'));
    } else {
      // Không đơn vị -> mọi dấu . và , đều là phân cách nghìn ("12.345" = 12345).
      n = parseInt(m[1].replace(/[.,]/g, ''), 10);
    }
    if (!isFinite(n)) return null;
    return Math.round(n * (UNITS[unit] || 1));
  }

  function durToSec(t) {
    if (!t) return null;
    const p = t.split(':').map(Number);
    return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  }

  // ── Bóc 1 thẻ kết quả (div[role="article"]) ───────────────────────────────
  function parseArticle(art) {
    // Thumbnail (aria-hidden) và tiêu đề dùng chung href -> ưu tiên anchor tiêu đề.
    let info = null, titleEl = null;
    for (const a of art.querySelectorAll('a[href]')) {
      const vi = videoInfo(a.getAttribute('href'));
      if (!vi) continue;
      if (!info) info = vi;
      if (!titleEl && a.getAttribute('aria-hidden') !== 'true') titleEl = a;
    }
    if (!info) return null;

    const title = txt(titleEl);
    const label = titleEl?.getAttribute('aria-label') || '';

    // Lượt xem: aria-label đầy đủ nhất, khớp cả "1,7\ntriệu lượt xem".
    const mv = label.match(/([\d.,]+)\s*(triệu|nghìn|tỷ|tr|k|m|b)?\s*lượt xem/i);
    let viewsText = mv ? mv[0] : '';

    // Dòng "22 tháng 5 · 712K lượt xem" — chỉ lấy node lá, tránh dính text cha.
    let dateText = '';
    for (const d of art.querySelectorAll('div, span')) {
      if (d.children.length) continue;
      const t = txt(d);
      if (t.includes('·') && /lượt xem|views/i.test(t)) {
        const parts = t.split('·');
        dateText = parts[0].trim();
        if (!viewsText) viewsText = parts[1].trim();
        break;
      }
    }
    if (!dateText) {
      const md = label.match(/(\d{1,2} tháng \d{1,2}(?:, \d{4})?)/);
      dateText = md ? md[1] : '';
    }

    // Thời lượng: span dạng "2:58" / "1:02:03".
    let duration = '';
    for (const s of art.querySelectorAll('span')) {
      const t = txt(s);
      if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(t)) { duration = t; break; }
    }

    // Page: anchor facebook.com không phải link video.
    let page = '', pageUrl = '';
    for (const a of art.querySelectorAll('a[href]')) {
      if (videoInfo(a.getAttribute('href'))) continue;
      let u;
      try { u = new URL(a.href); } catch { continue; }
      if (!/(^|\.)facebook\.com$/.test(u.hostname)) continue;
      if (u.pathname === '/' || !txt(a)) continue;
      const pid = u.searchParams.get('id');
      page = txt(a).split('\n')[0];
      pageUrl = u.origin + u.pathname + (pid ? `?id=${pid}` : '');
      break;
    }

    // Mô tả: khối span[dir=auto] dài nhất, bỏ tiêu đề và dòng lượt xem.
    let description = '';
    for (const s of art.querySelectorAll('span[dir="auto"]')) {
      const t = txt(s);
      if (!t || t === title || /lượt xem|views/i.test(t)) continue;
      if (t.length > description.length) description = t;
    }

    return {
      kind: 'video',
      id: info.id,
      type: info.type,
      url: info.url,
      video_url: '',
      title,
      page,
      page_url: pageUrl,
      duration,
      duration_sec: durToSec(duration),
      date: dateText,
      views: parseCount(viewsText.replace(/lượt xem|views?/i, '')),
      views_text: viewsText.replace(/\s+/g, ' ').trim(),
      reactions: null,
      comments: null,
      shares: null,
      description,
      thumb: art.querySelector('img[src*="fbcdn"]')?.src || '',
    };
  }

  // ── Bóc 1 bài viết (search/top, search/posts, trang cá nhân, nhóm…) ───────
  // Link bài viết: /posts/, /permalink/, /share/p/, story_fbid=, /photo?fbid=.
  // Bỏ /stories/ vì đó là vòng tin trên avatar, không phải bài viết.
  function postInfo(href) {
    let u;
    try { u = new URL(href, location.origin); } catch { return null; }
    if (!/(^|\.)facebook\.com$/.test(u.hostname)) return null;
    const p = u.pathname;
    if (p.startsWith('/stories/')) return null;

    let m = p.match(/\/groups\/[^/]+\/(?:posts|permalink)\/(\d+)/)
         || p.match(/\/(?:posts|permalink)\/([\w.-]+)/)
         || p.match(/\/share\/p\/([\w-]+)/);
    if (m) return { id: m[1], url: cleanUrl(u.href) };

    const fbid = u.searchParams.get('story_fbid')
              || (p.startsWith('/photo') ? u.searchParams.get('fbid') : null);
    if (fbid) return { id: fbid, url: cleanUrl(u.href) };
    return null;
  }

  const COUNT_RE = [
    ['comments', /([\d.,]+\s*(?:k|tr|triệu|nghìn)?)\s*bình luận/i],
    ['shares', /([\d.,]+\s*(?:k|tr|triệu|nghìn)?)\s*lượt chia sẻ/i],
    ['views', /([\d.,]+\s*(?:k|tr|triệu|nghìn)?)\s*lượt xem/i],
  ];

  function parsePost(item) {
    let perma = null, permaEl = null, video = null;
    for (const a of item.querySelectorAll('a[href]')) {
      const href = a.getAttribute('href') || '';
      if (!href || href.startsWith('#')) continue;
      if (!video) video = videoInfo(href);
      if (!perma) {
        const pi = postInfo(href);
        if (pi) { perma = pi; permaEl = a; }
      }
      if (perma && video) break;
    }
    // Không có link bài lẫn link video -> thẻ gợi ý / rail tin, bỏ qua.
    if (!perma && !video) return null;

    let page = '', pageUrl = '';
    const nameEl = item.querySelector('[data-ad-rendering-role="profile_name"] a[href], h3 a[href], h2 a[href]');
    if (nameEl) {
      page = txt(nameEl).split('\n')[0];
      pageUrl = cleanUrl(nameEl.href);
    }

    // Nội dung: FB đánh dấu sẵn story_message; không có thì lấy khối dài nhất.
    let description = txt(item.querySelector('[data-ad-rendering-role="story_message"], [data-ad-comet-preview="message"]'));
    if (!description) {
      for (const el of item.querySelectorAll('div[dir="auto"], span[dir="auto"]')) {
        const t = txt(el);
        if (!t || t === page) continue;
        if (t.length > description.length) description = t;
      }
    }

    // Thời gian: chữ trên chính link bài viết ("3 giờ", "12 tháng 5").
    const date = permaEl ? txt(permaEl).split('\n')[0] : '';

    const all = txt(item);
    const counts = {};
    for (const [key, re] of COUNT_RE) {
      const m = all.match(re);
      counts[key] = m ? parseCount(m[1]) : null;
    }

    // Cảm xúc: số nằm trong aria-label của cụm icon cảm xúc.
    let reactions = null;
    for (const el of item.querySelectorAll('[aria-label]')) {
      const l = el.getAttribute('aria-label') || '';
      if (!/cảm xúc|reaction/i.test(l)) continue;
      const m = l.match(/[\d.,]+\s*(?:k|m|b|tr|triệu|nghìn|tỷ)?/i);
      if (m) { reactions = parseCount(m[0]); break; }
    }

    return {
      kind: 'post',
      id: (perma || video).id,
      type: video ? video.type : 'post',
      url: (perma || video).url,
      video_url: video ? video.url : '',
      title: description.split('\n')[0].slice(0, 120),
      page,
      page_url: pageUrl,
      duration: '',
      duration_sec: null,
      date,
      views: counts.views,
      views_text: counts.views != null ? String(counts.views) : '',
      reactions,
      comments: counts.comments,
      shares: counts.shares,
      description,
      thumb: item.querySelector('img[src*="fbcdn"]')?.src || '',
    };
  }

  // ── Video nằm ngoài thẻ role="article" ────────────────────────────────────
  // Lưới thước phim /<page>/reels/ chỉ là các ô link, không có role="article".
  // Quét thêm toàn trang để không bỏ sót (giống GetReelStats.py và script cũ).
  function trangHienTai() {
    const m = location.pathname.match(/^\/([^/]+)\/(?:reels|videos)/);
    const bo = ['search', 'watch', 'reel', 'reels', 'videos', 'groups', 'marketplace'];
    if (!m || bo.includes(m[1])) return { page: '', page_url: '' };
    return {
      page: clean(document.title).replace(/^\(\d+\+?\)\s*/, '').replace(/\s*\|\s*Facebook$/i, ''),
      page_url: `https://www.facebook.com/${m[1]}`,
    };
  }

  function parseLooseVideo(a) {
    const info = videoInfo(a.getAttribute('href') || '');
    if (!info) return null;

    const label = a.getAttribute('aria-label') || '';
    const mv = label.match(/([\d.,]+)\s*(triệu|nghìn|tỷ|tr|k|m|b)?\s*lượt xem/i);
    let viewsText = mv ? mv[0] : '';
    if (!viewsText) {
      // Ô lưới chỉ in số trần dưới icon lượt xem; "2:58" có dấu hai chấm nên không dính.
      for (const s of a.querySelectorAll('span')) {
        if (s.children.length) continue;
        const t = txt(s);
        if (/^[\d.,]+\s*(?:k|m|b|tr|triệu|nghìn|tỷ)?$/i.test(t)) { viewsText = t; break; }
      }
    }

    let duration = '';
    for (const s of a.querySelectorAll('span')) {
      const t = txt(s);
      if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(t)) { duration = t; break; }
    }

    const chu = trangHienTai();
    return {
      kind: 'video',
      id: info.id,
      type: info.type,
      url: info.url,
      video_url: '',
      title: clean(label.split('\n')[0]) || txt(a).split('\n')[0],
      page: chu.page,
      page_url: chu.page_url,
      duration,
      duration_sec: durToSec(duration),
      date: '',
      views: parseCount(viewsText.replace(/lượt xem|views?/i, '')),
      views_text: viewsText,
      reactions: null,
      comments: null,
      shares: null,
      description: '',
      thumb: a.querySelector('img[src*="fbcdn"]')?.src || '',
    };
  }

  // ── Nhận biết "đã hết kết quả" ────────────────────────────────────────────
  const END_TEXTS = [
    'đã hết kết quả', 'hết kết quả', 'không còn kết quả', 'không có kết quả nào khác',
    'bạn đã xem hết', 'đã xem hết', 'không còn nội dung', 'không còn video',
    'end of results', 'no more results', 'no more posts', "you're all caught up",
  ];

  const scroller = () => document.scrollingElement || document.documentElement;

  function feedEnded() {
    // Banner "Đã hết kết quả" nằm ở cuối feed hoặc ngay sau feed -> chỉ soi vài
    // node đó cho nhẹ, không quét cả trang.
    const feed = document.querySelector('div[role="feed"]');
    const zones = [];
    if (feed) {
      zones.push(...[...feed.children].slice(-4));
      let sib = feed.nextElementSibling;
      for (let i = 0; i < 3 && sib; i++, sib = sib.nextElementSibling) zones.push(sib);
      if (feed.parentElement) zones.push(...[...feed.parentElement.children].slice(-3));
    } else {
      zones.push(...[...document.body.children].slice(-4));
    }
    for (const z of zones) {
      // Vùng còn video/bài viết -> không phải banner.
      if (!z || z.querySelector('div[role="article"], [aria-posinset]')) continue;
      const t = (z.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (!t || t.length > 200) continue;
      if (END_TEXTS.some(s => t.includes(s))) return true;
    }
    return false;
  }

  // ── Vòng gom + cuộn ───────────────────────────────────────────────────────
  let running = false;
  let stopFlag = false;
  const store = new Map();

  // Đếm ô đã có dữ liệu, để giữ bản "đầy đặn" hơn khi gặp lại cùng 1 item.
  const score = r => [r.views, r.reactions, r.comments, r.shares,
                      r.description, r.page, r.date, r.duration]
    .filter(v => v !== null && v !== undefined && v !== '').length;

  function harvest(onlyReels, wantFollowers) {
    // Feed FB ảo hoá: item cũ bị gỡ khỏi DOM khi cuộn -> phải gom sau MỖI lần cuộn.
    const mode = detectMode();   // đọc lại mỗi vòng vì FB đổi tab không tải lại trang
    const items = mode === 'video'
      ? document.querySelectorAll('div[role="article"]')
      : document.querySelectorAll('[aria-posinset], div[role="article"]');

    const nhap = row => {
      if (!row) return;
      if (onlyReels && row.type !== 'reel') return;
      const old = store.get(row.id);
      if (!old) { store.set(row.id, row); return; }
      const better = score(row) > score(old)
        || (score(row) === score(old) && (row.views ?? -1) > (old.views ?? -1));
      if (better) store.set(row.id, row);
    };

    for (const el of items) {
      const row = mode === 'video' ? parseArticle(el) : parsePost(el);
      if (!row) continue;
      // Chỉ hover ở feed bài viết. Trang thước phim/video không lấy người theo
      // dõi (làm phiên chạy chậm hẳn) — số đó lấy sau bằng công cụ riêng.
      if (wantFollowers && mode === 'post') queueAuthor(el, row.page_url);
      nhap(row);
    }

    // Quét vét video nằm ngoài thẻ (lưới /reels/, băng chuyền reel trong kết quả
    // tìm kiếm). Chỉ làm ở chế độ video: ở feed bài viết sẽ đẻ ra dòng trùng với
    // chính bài đang chứa video đó.
    if (mode !== 'video') return;
    for (const a of document.querySelectorAll('a[href*="/reel/"], a[href*="/watch/"], a[href*="/videos/"]')) {
      if (a.closest('div[role="article"], [aria-posinset]')) continue;   // đã xử lý ở trên
      nhap(parseLooseVideo(a));
    }
  }

  function emit(msg) {
    try { chrome.runtime.sendMessage(msg).catch(() => {}); } catch { /* popup đã đóng */ }
  }

  // Bản rút gọn để popup hiện ngay trong lúc chạy (không gửi cả mô tả cho nhẹ).
  const previewOf = () => [...store.values()]
    .sort((a, b) => (b.views ?? 0) - (a.views ?? 0))
    .slice(0, 20)
    .map(r => ({ title: r.title, page: r.page, url: r.url, type: r.type,
                 views: r.views, reactions: r.reactions, comments: r.comments }));

  // ── Số người theo dõi (giả lập hover lên tên tác giả) ─────────────────────
  // FB chỉ vẽ hover-card khi có sự kiện chuột trên chính thẻ <a> của họ, nên
  // phải hover đúng phần tử đang nằm trong DOM — không tự tạo link thay được.
  const followers = new Map();   // page_url -> số | null (null = đã thử, không ra)
  const pending = new Map();     // page_url -> phần tử <a> đang chờ hover

  const FOLLOW_RE = /([\d.,]+\s*(?:k|m|b|tr|triệu|nghìn|tỷ)?)\s*(?:người theo dõi|người follow|followers)/i;

  function authorAnchor(item, url) {
    // 1. Hook FB tự đánh dấu cho tên tác giả (feed bài viết).
    const p = item.querySelector('[data-ad-rendering-role="profile_name"] a[href]');
    if (p) return p;

    const anchors = [...item.querySelectorAll('a[href]')];
    // 2. Đúng link trang đã bóc được ở cột page_url.
    if (url) {
      const khop = anchors.find(a => cleanUrl(a.href) === url);
      if (khop) return khop;
    }
    // 3. Link facebook không phải link video. Ở thẻ video, h2 là TIÊU ĐỀ VIDEO
    //    nên tuyệt đối không lấy theo h2/h3 — hover vào đó FB không vẽ thẻ trang.
    return anchors.find(a => {
      if (videoInfo(a.getAttribute('href') || '')) return false;
      if (!txt(a)) return false;
      let u;
      try { u = new URL(a.href); } catch { return false; }
      return /(^|\.)facebook\.com$/.test(u.hostname) && u.pathname !== '/'
             && !u.pathname.startsWith('/stories/');
    }) || null;
  }

  function queueAuthor(item, url) {
    if (!url || followers.has(url) || pending.has(url)) return;
    const a = authorAnchor(item, url);
    if (a) pending.set(url, a);
  }

  function fireMouse(el, type, extra) {
    const r = el.getBoundingClientRect();
    const noBubble = ['mouseenter', 'mouseleave', 'pointerenter', 'pointerleave'];
    const opts = Object.assign({
      bubbles: !noBubble.includes(type),
      cancelable: true,
      view: window,
      clientX: Math.round(r.left + r.width / 2),
      clientY: Math.round(r.top + r.height / 2),
    }, extra || {});
    const isPointer = type.startsWith('pointer');
    const Ctor = isPointer && window.PointerEvent ? window.PointerEvent : window.MouseEvent;
    if (isPointer) { opts.pointerType = 'mouse'; opts.isPrimary = true; }
    el.dispatchEvent(new Ctor(type, opts));
  }

  function hoverOn(el) {
    const r = el.getBoundingClientRect();
    // Hover-card chỉ mở khi phần tử nằm trong khung nhìn.
    if (r.bottom < 0 || r.top > window.innerHeight) el.scrollIntoView({ block: 'center' });
    for (const t of ['pointerover', 'pointerenter', 'mouseover', 'mouseenter', 'mousemove']) fireMouse(el, t);
  }

  function hoverOff(el) {
    for (const t of ['mouseout', 'mouseleave', 'pointerout', 'pointerleave']) {
      fireMouse(el, t, { relatedTarget: document.body });
    }
  }

  // Hover rồi soi các node MỚI được chèn vào DOM (chính là hover-card).
  async function hoverFollowers(el, waitMs) {
    const added = [];
    const obs = new MutationObserver(muts => {
      for (const m of muts) for (const n of m.addedNodes) if (n.nodeType === 1) added.push(n);
    });
    obs.observe(document.body, { childList: true, subtree: true });
    try {
      hoverOn(el);
      const deadline = Date.now() + waitMs;
      while (Date.now() < deadline) {
        await sleep(200);
        for (const n of added) {
          if (!n.isConnected) continue;
          const m = clean(n.innerText || n.textContent || '').match(FOLLOW_RE);
          if (m) return parseCount(m[1]);
        }
      }
      return null;
    } finally {
      obs.disconnect();
      hoverOff(el);
    }
  }

  async function drainFollowers(gap) {
    const list = [...pending];
    let done = 0;
    for (const [url, el] of list) {
      if (stopFlag) return;
      pending.delete(url);
      if (!el.isConnected) continue;   // đã bị gỡ khỏi DOM -> lần gặp sau xếp hàng lại
      emit({ evt: 'followers', count: store.size, done: ++done, total: list.length });
      followers.set(url, await hoverFollowers(el, 2500));
      await sleep(gap);
    }
  }

  async function save() {
    const rows = [...store.values()]
      .map(r => Object.assign({}, r, { followers: followers.get(r.page_url) ?? null }))
      .sort((a, b) => (b.views ?? 0) - (a.views ?? 0));
    await chrome.storage.local.set({
      lastResult: { rows, sourceUrl: location.href, savedAt: new Date().toISOString() },
    });
    return rows;
  }

  async function run(cfg) {
    running = true;
    stopFlag = false;
    store.clear();

    const pause = cfg.pauseMs || 1800;
    const onlyReels = !!cfg.onlyReels;
    const wantFollowers = !!cfg.getFollowers;
    // Chốt chặn an toàn: FB không hiện banner "hết kết quả" mà cũng không nạp
    // thêm gì (trang không dài ra, không có video mới) suốt ngần này vòng.
    const IDLE_MAX = 8;

    harvest(onlyReels, wantFollowers);
    emit({ evt: 'progress', count: store.size, idle: 0, preview: previewOf() });

    let idle = 0, lastSaved = 0, reason = 'stopped';
    while (!stopFlag) {
      if (feedEnded()) { reason = 'end'; break; }

      const beforeCount = store.size;
      const beforeH = scroller().scrollHeight;
      window.scrollTo(0, beforeH);
      await sleep(pause);
      harvest(onlyReels, wantFollowers);

      // Hover ngay trong vòng lặp: feed ảo hoá nên cuộn qua là thẻ <a> biến mất.
      if (wantFollowers) await drainFollowers(400);

      const grew = store.size > beforeCount || scroller().scrollHeight > beforeH;
      idle = grew ? 0 : idle + 1;
      emit({ evt: 'progress', count: store.size, idle, preview: previewOf() });

      // Cuộn 1 lần thì gom + lưu 1 lần, không đợi tới cuối: đóng tab giữa chừng
      // vẫn còn dữ liệu, và popup bật được nút xuất ngay.
      if (store.size > lastSaved) {
        await save();
        lastSaved = store.size;
        emit({ evt: 'saved', count: store.size });
      }

      if (idle >= IDLE_MAX) { reason = feedEnded() ? 'end' : 'idle'; break; }
    }
    if (stopFlag) reason = 'stopped';
    if (wantFollowers && !stopFlag) await drainFollowers(400);   // nốt hàng còn lại

    const rows = await save();
    running = false;
    emit({ evt: 'done', count: rows.length, reason });
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.cmd === 'ping') {
      sendResponse({ ok: true, running, count: store.size, mode: detectMode() });
      return;
    }
    if (msg?.cmd === 'stop') {
      stopFlag = true;
      sendResponse({ ok: true });
      return;
    }
    if (msg?.cmd === 'clear') {
      if (running) { sendResponse({ ok: false, error: 'Đang chạy, dừng trước đã.' }); return; }
      store.clear();
      sendResponse({ ok: true });
      return;
    }
    if (msg?.cmd === 'start') {
      if (running) { sendResponse({ ok: false, error: 'Đang chạy rồi.' }); return; }
      run(msg.cfg || {});
      sendResponse({ ok: true });
      return;
    }
    if (msg?.cmd === 'testFollowers') {
      // Thử hover 1 tên tác giả đang hiện trên màn hình để xem có lấy được không.
      (async () => {
        const item = document.querySelector('[aria-posinset], div[role="article"]');
        const a = item && authorAnchor(item, '');
        if (!a) { sendResponse({ ok: false, error: 'Không thấy tên tác giả nào trên màn hình.' }); return; }
        const n = await hoverFollowers(a, 5000);
        sendResponse({ ok: true, name: txt(a).split('\n')[0], url: cleanUrl(a.href), followers: n });
      })();
      return true;   // giữ kênh mở để trả lời bất đồng bộ
    }
  });
})();
