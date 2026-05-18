(() => {
  'use strict';

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const pageCtx        = document.getElementById('pageCtx');
  const listCountEl    = document.getElementById('listCount');
  const detailCountEl  = document.getElementById('detailCount');
  const phaseBadge     = document.getElementById('phaseBadge');
  const phaseText      = document.getElementById('phaseText');
  const progressBar    = document.getElementById('progressBar');
  const progressText   = document.getElementById('progressText');
  const errorMsg       = document.getElementById('errorMsg');
  const btnScrapeList  = document.getElementById('btnScrapeList');
  const btnScrapeDetail= document.getElementById('btnScrapeDetail');
  const btnStop        = document.getElementById('btnStop');
  const btnExport      = document.getElementById('btnExport');
  const btnClear       = document.getElementById('btnClear');

  // ── Helpers ────────────────────────────────────────────────────────────────

  function showError(msg) { errorMsg.style.display = 'block'; errorMsg.textContent = msg; }
  function clearError()   { errorMsg.style.display = 'none';  errorMsg.textContent = ''; }

  function getActiveTab() {
    return new Promise((resolve, reject) => {
      chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
        if (chrome.runtime.lastError) return reject(chrome.runtime.lastError);
        if (!tabs.length) return reject(new Error('No active tab'));
        resolve(tabs[0]);
      });
    });
  }

  function sendToContent(tabId, message) {
    return new Promise((resolve, reject) => {
      chrome.tabs.sendMessage(tabId, message, response => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
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

  // ── UI state machine ───────────────────────────────────────────────────────
  // States: idle_empty | idle_list_done | idle_both_done | running_list | running_detail | wrong_page

  function renderUI(status) {
    const { running, phase, listCount, detailCount, processed, total, isListPage, isDetailPage } = status;
    const hasData = listCount > 0 || detailCount > 0;

    // Page context banner
    if (running && phase === 'detail' && isDetailPage) {
      // Extension navigated here automatically — don't tell user to go back
      pageCtx.className   = 'page-ctx running';
      pageCtx.textContent = `Đang cào chi tiết giao dịch ${processed}/${total}...`;
    } else if (isListPage) {
      pageCtx.className   = 'page-ctx list';
      pageCtx.textContent = 'Trang danh sách hoạt động thanh toán';
    } else if (isDetailPage) {
      pageCtx.className   = 'page-ctx detail';
      pageCtx.textContent = 'Trang chi tiết giao dịch — quay lại danh sách để bắt đầu cào';
    } else {
      pageCtx.className   = 'page-ctx wrong';
      pageCtx.textContent = 'Chưa thấy bảng giao dịch — hãy vào trang Hoạt động thanh toán';
    }

    // Counters
    listCountEl.textContent   = listCount;
    detailCountEl.textContent = detailCount;

    // Phase badge
    if (running) {
      phaseBadge.className = 'badge running';
      phaseBadge.querySelector('.dot').className = 'dot pulse';
      phaseText.textContent = phase === 'list' ? 'Đang cào danh sách' : 'Đang cào chi tiết';
    } else if (phase === 'idle' && listCount > 0) {
      phaseBadge.className = 'badge done';
      phaseBadge.querySelector('.dot').className = 'dot';
      phaseText.textContent = detailCount > 0 ? 'Hoàn thành' : 'Danh sách xong';
    } else {
      phaseBadge.className = 'badge';
      phaseBadge.querySelector('.dot').className = 'dot';
      phaseText.textContent = 'Chờ';
    }

    // Progress bar
    if (running && total > 0) {
      progressBar.style.width = Math.min(100, Math.round((processed / total) * 100)) + '%';
    } else if (!running && hasData) {
      progressBar.style.width = '100%';
    } else {
      progressBar.style.width = '0%';
    }

    // Action buttons
    // Running state: show Stop only
    btnStop.style.display         = running ? '' : 'none';
    btnScrapeList.style.display   = running ? 'none' : '';
    btnScrapeDetail.style.display = running ? 'none' : (listCount > 0 ? '' : 'none');

    // "Cào danh sách" — only works on list page
    btnScrapeList.disabled = running || !isListPage;
    btnScrapeList.textContent = listCount > 0
      ? `Re-cào danh sách (${listCount} hiện tại)`
      : 'Bắt đầu cào danh sách';

    // "Cào chi tiết" — only works on list page (extension navigates from there)
    if (listCount > 0 && !running) {
      btnScrapeDetail.disabled = !isListPage;
      btnScrapeDetail.textContent = detailCount > 0
        ? `Re-cào chi tiết (${detailCount}/${listCount})`
        : `Cào chi tiết ${listCount} giao dịch`;
    }

    // Export / Clear — always available when there's data, regardless of page
    btnExport.disabled = !hasData || running;
    btnClear.disabled  = !hasData || running;
  }

  function setProgress(message, current, total) {
    progressText.textContent = message || '';
    if (total > 0) {
      progressBar.style.width = Math.min(100, Math.round((current / total) * 100)) + '%';
    }
  }

  // ── Button handlers ────────────────────────────────────────────────────────

  btnScrapeList.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      if (!tab.url?.includes('business.facebook.com')) {
        showError('Hãy mở trang Facebook Business trước.');
        return;
      }
      await ensureContentScript(tab.id);
      const res = await sendToContent(tab.id, { type: 'START_LIST_SCRAPE' });
      if (!res?.ok) showError(res?.reason ?? 'Không thể bắt đầu cào.');
      else { progressText.textContent = 'Đang khởi động...'; progressBar.style.width = '0%'; }
    } catch (err) {
      showError('Lỗi kết nối content script.');
      console.error(err);
    }
  });

  btnScrapeDetail.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      await ensureContentScript(tab.id);
      const res = await sendToContent(tab.id, { type: 'START_DETAIL_SCRAPE' });
      if (!res?.ok) showError(res?.reason ?? 'Không thể bắt đầu cào chi tiết.');
      else { progressText.textContent = 'Đang khởi động...'; progressBar.style.width = '0%'; }
    } catch (err) {
      showError('Lỗi kết nối content script.');
    }
  });

  btnStop.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      await sendToContent(tab.id, { type: 'STOP_SCRAPE' });
      progressText.textContent = 'Đã dừng.';
    } catch (err) {
      showError('Lỗi khi dừng.');
    }
  });

  btnExport.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      await ensureContentScript(tab.id);
      await sendToContent(tab.id, { type: 'EXPORT_CSV' });
    } catch (err) {
      showError('Lỗi khi xuất CSV.');
    }
  });

  btnClear.addEventListener('click', async () => {
    clearError();
    try {
      const tab = await getActiveTab();
      await ensureContentScript(tab.id);
      await sendToContent(tab.id, { type: 'CLEAR_DATA' });
      listCountEl.textContent   = '0';
      detailCountEl.textContent = '0';
      progressBar.style.width   = '0%';
      progressText.textContent  = '';
      btnExport.disabled        = true;
      btnClear.disabled         = true;
      phaseText.textContent     = 'Chờ';
      phaseBadge.className      = 'badge';
    } catch (err) {
      showError('Lỗi khi xóa dữ liệu.');
    }
  });

  // ── Listen for progress messages from content script ──────────────────────

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type !== 'PROGRESS') return;
    setProgress(msg.message, msg.current, msg.total);

    // Update counters from progress
    // (full re-render happens on next GET_STATUS poll, but update counters immediately)
    const isDone = msg.message?.includes('Hoàn thành') || msg.message?.includes('Đã dừng');
    if (isDone) progressBar.style.width = '100%';
  });

  // ── Poll status every second while popup is open ──────────────────────────

  let pollTimer;

  async function pollStatus() {
    try {
      const tab = await getActiveTab();
      if (!tab.url?.includes('business.facebook.com')) {
        renderUI({
          running: false, phase: 'idle',
          listCount: 0, detailCount: 0, processed: 0, total: 0,
          isListPage: false, isDetailPage: false,
        });
        return;
      }
      await ensureContentScript(tab.id);
      const status = await sendToContent(tab.id, { type: 'GET_STATUS' });
      if (status) renderUI(status);
    } catch (_) {
      // content script not ready yet
    }
    pollTimer = setTimeout(pollStatus, 1200);
  }

  pollStatus();

  // Clean up poll when popup closes
  window.addEventListener('unload', () => clearTimeout(pollTimer));
})();
