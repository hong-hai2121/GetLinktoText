(() => {
  'use strict';

  // ─── DOM refs ─────────────────────────────────────────────────────────────
  const btnStart    = document.getElementById('btnStart');
  const btnDownload = document.getElementById('btnDownload');
  const btnClear    = document.getElementById('btnClear');
  const dot         = document.getElementById('dot');
  const stateText   = document.getElementById('stateText');
  const countText   = document.getElementById('countText');
  const pageText    = document.getElementById('pageText');
  const progressBar = document.getElementById('progressBar');
  const progressText= document.getElementById('progressText');
  const errorMsg    = document.getElementById('errorMsg');
  const pageInput   = document.getElementById('pageInput');
  const pageChips   = document.querySelectorAll('.page-chip');

  // ─── Local state ──────────────────────────────────────────────────────────
  let isRunning  = false;
  let dataCount  = 0;
  let selectedPages = 0; // 0 = all

  // ─── Page selector logic ──────────────────────────────────────────────────

  function setActiveChip(pages) {
    selectedPages = pages;
    pageChips.forEach(c => c.classList.toggle('active', Number(c.dataset.pages) === pages));
    // Sync input field: show number or clear if "all"
    pageInput.value = pages > 0 ? pages : '';
  }

  pageChips.forEach(chip => {
    chip.addEventListener('click', () => {
      if (isRunning) return;
      setActiveChip(Number(chip.dataset.pages));
    });
  });

  pageInput.addEventListener('input', () => {
    if (isRunning) return;
    const v = parseInt(pageInput.value, 10);
    if (!isNaN(v) && v > 0) {
      selectedPages = v;
      // Deactivate all chips (custom value)
      pageChips.forEach(c => c.classList.remove('active'));
    } else if (pageInput.value === '') {
      setActiveChip(0); // back to "all"
    }
  });

  // ─── Helpers ──────────────────────────────────────────────────────────────

  function showError(msg) {
    errorMsg.style.display = 'block';
    errorMsg.textContent = msg;
  }

  function clearError() {
    errorMsg.style.display = 'none';
    errorMsg.textContent = '';
  }

  function setRunning(running) {
    isRunning = running;

    dot.className   = running ? 'dot running' : 'dot';
    stateText.textContent = running ? 'Đang chạy...' : 'Sẵn sàng';

    btnStart.textContent = running ? 'Dừng lại' : 'Bắt đầu cào';
    btnStart.className   = running ? 'btn btn-secondary' : 'btn btn-primary';

    // Lock page selector while running
    pageChips.forEach(c => c.style.pointerEvents = running ? 'none' : '');
    pageInput.disabled = running;
  }

  function updateProgress(msg) {
    const { message, current, total, page } = msg;

    if (current !== undefined) dataCount = current;

    if (current !== undefined && total > 0) {
      const pct = Math.min(100, Math.round((current / total) * 100));
      progressBar.style.width = pct + '%';
    }

    progressText.textContent = message || '';
    countText.textContent    = dataCount;
    if (page) pageText.textContent = selectedPages > 0
      ? `Trang ${page} / ${selectedPages}`
      : `Trang ${page}`;

    btnDownload.disabled = dataCount === 0;
    btnClear.disabled    = dataCount === 0;
  }

  // ─── Active tab helpers ───────────────────────────────────────────────────

  function getActiveTab() {
    return new Promise((resolve, reject) => {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (chrome.runtime.lastError) return reject(chrome.runtime.lastError);
        if (!tabs.length) return reject(new Error('No active tab'));
        resolve(tabs[0]);
      });
    });
  }

  function sendToContent(tabId, message) {
    return new Promise((resolve, reject) => {
      chrome.tabs.sendMessage(tabId, message, (response) => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        resolve(response);
      });
    });
  }

  async function ensureContentScript(tabId) {
    try {
      await sendToContent(tabId, { type: 'GET_STATUS' });
    } catch (_) {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
      await new Promise(r => setTimeout(r, 150));
    }
  }

  // ─── Button handlers ──────────────────────────────────────────────────────

  btnStart.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();

      if (!tab.url?.includes('techcombank.com')) {
        showError('Vui lòng mở trang Techcombank Business trước khi cào.');
        return;
      }

      await ensureContentScript(tab.id);

      if (isRunning) {
        await sendToContent(tab.id, { type: 'STOP_SCRAPE' });
        setRunning(false);
        progressText.textContent = 'Đã dừng.';
      } else {
        const res = await sendToContent(tab.id, {
          type:     'START_SCRAPE',
          maxPages: selectedPages, // 0 = unlimited
        });
        if (res?.ok) {
          setRunning(true);
          progressBar.style.width = '0%';
          progressText.textContent = selectedPages > 0
            ? `Sẽ cào tối đa ${selectedPages} trang...`
            : 'Đang khởi động (tất cả trang)...';
        } else {
          showError(res?.reason ?? 'Không thể bắt đầu cào.');
        }
      }
    } catch (err) {
      showError('Không thể kết nối tới trang. Kiểm tra URL có phải techcombank.com không.');
      console.error('[TCB Popup]', err);
    }
  });

  btnDownload.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      await ensureContentScript(tab.id);
      const res = await sendToContent(tab.id, { type: 'DOWNLOAD_CSV' });
      if (!res?.ok) showError(res?.reason ?? 'Không có dữ liệu để tải.');
    } catch (err) {
      showError('Không thể tải CSV.');
    }
  });

  btnClear.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      await ensureContentScript(tab.id);
      await sendToContent(tab.id, { type: 'CLEAR_DATA' });
      dataCount = 0;
      countText.textContent    = '0';
      pageText.textContent     = '—';
      progressBar.style.width  = '0%';
      progressText.textContent = '';
      btnDownload.disabled     = true;
      btnClear.disabled        = true;
    } catch (err) {
      showError('Không thể xóa dữ liệu.');
    }
  });

  // ─── Listen for progress from content script ──────────────────────────────

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type !== 'PROGRESS') return;
    updateProgress(msg);

    const isDone = isRunning &&
      (msg.message?.includes('Hoàn thành') || msg.message?.includes('Đã dừng'));

    if (isDone) {
      setRunning(false);
      progressBar.style.width = '100%';
    }
  });

  // ─── Sync status on popup open ────────────────────────────────────────────

  (async () => {
    try {
      const tab = await getActiveTab();

      if (!tab.url?.includes('techcombank.com')) {
        showError('Vui lòng mở trang Techcombank Business để sử dụng extension.');
        btnStart.disabled = true;
        return;
      }

      const status = await sendToContent(tab.id, { type: 'GET_STATUS' });
      if (status) {
        setRunning(status.running);
        dataCount = status.count ?? 0;
        countText.textContent = dataCount;
        if (status.page > 1) pageText.textContent = `Trang ${status.page}`;
        if (status.maxPages > 0) setActiveChip(status.maxPages);
        btnDownload.disabled = dataCount === 0;
        btnClear.disabled    = dataCount === 0;
      }
    } catch (_) {
      // content script chưa inject — bình thường
    }
  })();
})();
