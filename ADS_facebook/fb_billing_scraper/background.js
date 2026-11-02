// background.js — service worker: mở giao diện FB Billing Scraper thành CỬA SỔ RIÊNG
// (type "popup" của Chrome: có thanh tiêu đề, kéo đi đâu cũng được, không tự đóng khi
// bấm sang trang Facebook — khác popup bám icon extension trước đây).
//
// Luồng: bấm icon extension trên tab Facebook → mở cửa sổ popup.html?tabId=<id tab đó>.
// Bấm icon lần nữa → chỉ đưa cửa sổ đang mở lên trước và báo cho nó đổi tab đích.
'use strict';

const WIN_KEY    = 'panelWindowId';   // storage.session: id cửa sổ đang mở (mất khi tắt Chrome)
const BOUNDS_KEY = 'panelBounds';     // storage.local: vị trí + kích cỡ lần cuối người dùng kéo
const DEFAULT_W  = 360;
const DEFAULT_H  = 640;

async function getPanelWindowId() {
  const o = await chrome.storage.session.get(WIN_KEY);
  return typeof o[WIN_KEY] === 'number' ? o[WIN_KEY] : null;
}

// Cửa sổ đã mở → đưa lên trước, báo tab đích mới. Trả false nếu cửa sổ đã bị đóng.
async function focusExisting(winId, tabId) {
  try {
    await chrome.windows.update(winId, { focused: true, drawAttention: true });
  } catch (_) {
    return false;
  }
  chrome.runtime.sendMessage({ type: 'SET_TARGET_TAB', tabId }).catch(() => {});
  return true;
}

// Lần đầu: đặt ở góc trên-phải của cửa sổ Chrome chứa tab Facebook.
async function defaultPosition(tab) {
  try {
    const w = await chrome.windows.get(tab.windowId);
    return { left: Math.max(0, w.left + w.width - DEFAULT_W - 24), top: Math.max(0, w.top + 90) };
  } catch (_) {
    return {};
  }
}

async function openPanel(tab) {
  const url   = chrome.runtime.getURL('popup.html') + '?tabId=' + encodeURIComponent(tab.id);
  const saved = (await chrome.storage.local.get(BOUNDS_KEY))[BOUNDS_KEY] || {};
  const base  = { url, type: 'popup', focused: true };

  let win;
  try {
    // Ưu tiên vị trí/kích cỡ người dùng đã kéo lần trước
    const pos = saved.left !== undefined ? saved : await defaultPosition(tab);
    win = await chrome.windows.create({
      ...base,
      width:  saved.width  || DEFAULT_W,
      height: saved.height || DEFAULT_H,
      ...(pos.left !== undefined ? { left: pos.left, top: pos.top } : {}),
    });
  } catch (_) {
    // Vị trí cũ nằm ngoài màn hình (đổi monitor…) → mở mặc định
    win = await chrome.windows.create({ ...base, width: DEFAULT_W, height: DEFAULT_H });
  }
  await chrome.storage.session.set({ [WIN_KEY]: win.id });
}

chrome.action.onClicked.addListener(async (tab) => {
  const existing = await getPanelWindowId();
  if (existing !== null && await focusExisting(existing, tab.id)) return;
  await openPanel(tab);
});

// Nhớ vị trí/kích cỡ khi người dùng kéo cửa sổ
chrome.windows.onBoundsChanged.addListener(async (win) => {
  if (win.id !== await getPanelWindowId()) return;
  await chrome.storage.local.set({
    [BOUNDS_KEY]: { left: win.left, top: win.top, width: win.width, height: win.height },
  });
});

chrome.windows.onRemoved.addListener(async (winId) => {
  if (winId === await getPanelWindowId()) await chrome.storage.session.remove(WIN_KEY);
});
