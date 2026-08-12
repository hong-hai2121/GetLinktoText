/* ============================================================================
 * ReelStats — popup
 * Gửi lệnh cho scraper.js trong tab Facebook, hiển thị tiến độ, xuất file.
 * ========================================================================== */

const $ = id => document.getElementById(id);
const CFG_KEYS = ['pauseMs', 'onlyReels', 'getFollowers'];
const COLS = ['kind', 'id', 'type', 'url', 'video_url', 'title', 'page', 'page_url',
              'followers', 'duration', 'duration_sec', 'date', 'views', 'views_text',
              'reactions', 'comments', 'shares', 'description', 'thumb'];

// Mirror của detectMode() trong scraper.js, dùng khi content script chưa nạp.
function modeFromUrl(url) {
  let p;
  try { p = new URL(url).pathname; } catch { return 'post'; }
  if (/^\/search\/(videos|reels)/.test(p)) return 'video';
  if (/^\/search\//.test(p)) return 'post';
  if (/\/(reels|videos|watch)\/?$/.test(p)) return 'video';
  return 'post';
}

function showMode(mode) {
  const video = mode === 'video';
  $('mode').innerHTML = video
    ? 'Trang <b>thước phim / video</b> — gom thẻ video kèm lượt xem. '
      + 'Trang này <b>không hover lấy người theo dõi</b>, chỉ lấy link trang.'
    : 'Trang <b>bài viết</b> (Tất cả, Bài viết, trang cá nhân…) — gom bài viết, kèm link video nếu bài có video.';
  // Hover chỉ có tác dụng ở feed bài viết -> khoá luôn cho khỏi bật nhầm.
  $('getFollowers').disabled = video;
  $('testfl').disabled = video;
}

let tabId = null;
let rows = [];

// ── Tiện ích ────────────────────────────────────────────────────────────────
function setStatus(text, isErr = false) {
  $('status').textContent = text;
  $('status').classList.toggle('err', isErr);
}

function stamp() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function fmtViews(n) {
  if (n == null) return '—';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.', ',') + 'tr';
  if (n >= 1e3) return Math.round(n / 1e3) + 'K';
  return String(n);
}

async function download(text, filename, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  try {
    await chrome.downloads.download({ url, filename, saveAs: true });
  } catch (e) {
    // Người dùng bấm Huỷ ở hộp thoại lưu -> không tải nữa.
    if (/cancel/i.test(e?.message || '')) return;
    // Dự phòng nếu chrome.downloads bị chặn: tải bằng thẻ <a>.
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}

// ── Hiển thị ────────────────────────────────────────────────────────────────
function render(meta) {
  const has = rows.length > 0;
  for (const id of ['csv', 'txt', 'copy', 'clear']) $(id).disabled = !has;

  if (!has) {
    $('result').textContent = 'Chưa có dữ liệu.';
    $('preview').innerHTML = '';
    return;
  }

  const reels = rows.filter(r => r.type === 'reel').length;
  const posts = rows.filter(r => r.kind === 'post').length;
  const when = meta?.savedAt ? new Date(meta.savedAt).toLocaleString('vi-VN') : '';
  const parts = [`${rows.length} mục`];
  if (posts) parts.push(`${posts} bài viết`);
  if (reels) parts.push(`${reels} reel`);
  // Cho biết dữ liệu đang giữ là của từ khoá nào, tránh nhầm với lần chạy trước.
  let kw = '';
  try { kw = new URL(meta?.sourceUrl).searchParams.get('q') || ''; } catch {}
  if (kw) parts.push(`từ khoá “${kw}”`);
  $('result').textContent = parts.join(' — ') + (when ? ` — ${when}` : '');

  fillPreview(rows);
}

function fillPreview(list) {
  $('preview').innerHTML = '';
  for (const r of list.slice(0, 30)) {
    const li = document.createElement('li');
    const b = document.createElement('b');
    // Bài viết thường không có lượt xem -> hiện cảm xúc/bình luận thay.
    b.textContent = fmtViews(r.views ?? r.reactions ?? r.comments);
    const s = document.createElement('span');
    s.textContent = r.title || r.page || r.url;
    s.title = `${r.page ? r.page + ' — ' : ''}${r.url}`;
    li.append(b, s);
    $('preview').appendChild(li);
  }
}

// Hiện ngay sau mỗi lần cuộn, không đợi chạy xong.
function renderLive(count, preview) {
  $('result').textContent = count ? `${count} mục — đang gom…` : 'Chưa thấy mục nào.';
  if (preview) fillPreview(preview);
}

async function loadLast() {
  const { lastResult } = await chrome.storage.local.get('lastResult');
  rows = lastResult?.rows || [];
  render(lastResult);
}

// ── Kết nối content script ──────────────────────────────────────────────────
async function ping() {
  try {
    return await chrome.tabs.sendMessage(tabId, { cmd: 'ping' });
  } catch {
    return null;
  }
}

async function ensureScraper() {
  if (await ping()) return true;
  // Tab đã mở từ trước khi cài extension -> chưa có content script, tiêm thủ công.
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['scraper.js'] });
  } catch (e) {
    setStatus('Không tiêm được script: ' + e.message, true);
    return false;
  }
  return !!(await ping());
}

function running(on) {
  $('start').disabled = on;
  $('stop').disabled = !on;
}

// ── Khởi động ───────────────────────────────────────────────────────────────
(async () => {
  const cfg = await chrome.storage.local.get(CFG_KEYS);
  for (const k of CFG_KEYS) {
    if (cfg[k] === undefined) continue;
    const el = $(k);
    if (el.type === 'checkbox') el.checked = !!cfg[k];
    else el.value = cfg[k];
  }

  await loadLast();

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https:\/\/([\w-]+\.)*facebook\.com\//.test(tab.url || '')) {
    setStatus('Tab hiện tại không phải Facebook.', true);
    $('start').disabled = true;
    return;
  }
  tabId = tab.id;
  showMode(modeFromUrl(tab.url));

  const state = await ping();
  if (state?.mode) showMode(state.mode);
  if (state?.running) {
    running(true);
    setStatus(`Đang chạy… ${state.count} mục.`);
  } else {
    setStatus('Sẵn sàng.');
  }
})();

// ── Nút bấm ─────────────────────────────────────────────────────────────────
$('start').addEventListener('click', async () => {
  const cfg = {
    pauseMs: Math.max(300, +$('pauseMs').value || 1800),
    onlyReels: $('onlyReels').checked,
    getFollowers: $('getFollowers').checked,
  };
  await chrome.storage.local.set(cfg);

  setStatus('Đang kết nối trang…');
  if (!await ensureScraper()) {
    setStatus('Không kết nối được. Hãy tải lại (F5) trang Facebook rồi thử lại.', true);
    return;
  }

  const res = await chrome.tabs.sendMessage(tabId, { cmd: 'start', cfg });
  if (!res?.ok) { setStatus(res?.error || 'Không bắt đầu được.', true); return; }
  running(true);
  // Ẩn kết quả lần trước ngay, tránh bấm nhầm "Tải CSV" ra dữ liệu từ khoá cũ.
  rows = [];
  render(null);
  setStatus('Đang cuộn… 0 mục.');
});

$('stop').addEventListener('click', async () => {
  try { await chrome.tabs.sendMessage(tabId, { cmd: 'stop' }); } catch {}
  setStatus('Đang dừng…');
});

$('csv').addEventListener('click', () => {
  const cell = v => {
    const s = (v ?? '').toString().replace(/\r?\n/g, ' ').trim();
    return /[",;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  // BOM để Excel mở đúng tiếng Việt.
  const csv = '﻿' + COLS.join(',') + '\n' +
              rows.map(r => COLS.map(c => cell(r[c])).join(',')).join('\n');
  download(csv, `fb_videos_${stamp()}.csv`, 'text/csv');
});

$('txt').addEventListener('click', () => {
  // Bài viết có reel thì link reel nằm ở video_url.
  const links = rows.filter(r => r.type === 'reel').map(r => r.video_url || r.url);
  const body = [...new Set(links)].join('\n');
  // GetReelStats.py bỏ qua dòng '#' -> dùng làm phần chú thích nguồn.
  const head = `# ReelStats — ${links.length} reel, xuất ${new Date().toLocaleString('vi-VN')}\n`;
  download(head + body + '\n', 'reel_links.txt', 'text/plain');
});

$('testfl').addEventListener('click', async () => {
  setStatus('Đang hover thử lên tên đầu tiên trên màn hình…');
  if (!await ensureScraper()) {
    setStatus('Không kết nối được. Tải lại (F5) trang Facebook rồi thử lại.', true);
    return;
  }
  const r = await chrome.tabs.sendMessage(tabId, { cmd: 'testFollowers' });
  if (!r?.ok) { setStatus(r?.error || 'Thử không thành công.', true); return; }
  setStatus(r.followers != null
    ? `“${r.name}” — ${r.followers.toLocaleString('vi-VN')} người theo dõi. Dùng được.`
    : `“${r.name}” — không đọc được số người theo dõi (thẻ thông tin không hiện hoặc không có mục này).`,
    r.followers == null);
});

// Xóa kết quả cũ trước khi gom từ khoá khác. Bấm 2 lần để tránh lỡ tay.
let clearArmed = null;
function disarmClear() {
  clearTimeout(clearArmed);
  clearArmed = null;
  $('clear').textContent = 'Xóa kết quả';
  $('clear').classList.remove('danger');
}

$('clear').addEventListener('click', async () => {
  if (!clearArmed) {
    $('clear').textContent = 'Bấm lần nữa để xóa';
    $('clear').classList.add('danger');
    clearArmed = setTimeout(disarmClear, 4000);
    return;
  }
  disarmClear();
  await chrome.storage.local.remove('lastResult');
  // Xóa luôn bộ nhớ tạm trong tab, không thì lần chạy sau vẫn còn hàng cũ.
  if (tabId) { try { await chrome.tabs.sendMessage(tabId, { cmd: 'clear' }); } catch {} }
  rows = [];
  render(null);
  setStatus('Đã xóa kết quả cũ — mở từ khoá mới rồi bấm Bắt đầu.');
});

$('copy').addEventListener('click', async () => {
  await navigator.clipboard.writeText(rows.map(r => r.url).join('\n'));
  setStatus(`Đã chép ${rows.length} link.`);
});

// ── Tin nhắn từ content script ──────────────────────────────────────────────
chrome.runtime.onMessage.addListener(msg => {
  if (msg?.evt === 'progress') {
    const chua = msg.idle ? ` (chưa thấy thêm ${msg.idle} lượt)` : '';
    setStatus(`Đang cuộn… ${msg.count} mục${chua}.`);
    renderLive(msg.count, msg.preview);
  } else if (msg?.evt === 'saved') {
    // Đã ghi xuống storage -> nạp lại để bật nút xuất file với dữ liệu thật.
    loadLast().then(() => renderLive(msg.count));
  } else if (msg?.evt === 'followers') {
    setStatus(`Đang lấy người theo dõi ${msg.done}/${msg.total} — ${msg.count} mục.`);
  } else if (msg?.evt === 'done') {
    running(false);
    const why = {
      end: 'đã hết kết quả',
      stopped: 'đã dừng',
      idle: 'Facebook không nạp thêm',
    }[msg.reason] || 'xong';
    setStatus(`Xong — ${msg.count} mục (${why}).`);
    loadLast();
  }
});
