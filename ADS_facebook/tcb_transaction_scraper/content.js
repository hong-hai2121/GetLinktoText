(() => {
  'use strict';

  if (window.__tcbScraperLoaded) return;
  window.__tcbScraperLoaded = true;

  // ─── State ────────────────────────────────────────────────────────────────
  let state = {
    running: false,
    transactions: [],
    currentPage: 1,
    processed: 0,
    total: 0,
    maxPages: 0, // 0 = unlimited
  };

  // ─── Utilities ────────────────────────────────────────────────────────────

  function waitForElement(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
      const el = document.querySelector(selector);
      if (el) return resolve(el);

      const timer = setTimeout(() => {
        observer.disconnect();
        reject(new Error(`Timeout waiting for: ${selector}`));
      }, timeout);

      const observer = new MutationObserver(() => {
        const found = document.querySelector(selector);
        if (found) {
          clearTimeout(timer);
          observer.disconnect();
          resolve(found);
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });
    });
  }

  function waitForElementGone(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
      if (!document.querySelector(selector)) return resolve();

      const timer = setTimeout(() => {
        observer.disconnect();
        reject(new Error(`Timeout waiting for removal of: ${selector}`));
      }, timeout);

      const observer = new MutationObserver(() => {
        if (!document.querySelector(selector)) {
          clearTimeout(timer);
          observer.disconnect();
          resolve();
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });
    });
  }

  function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function sendProgress(message, current, total) {
    chrome.runtime.sendMessage({
      type: 'PROGRESS',
      message,
      current,
      total,
      page: state.currentPage,
    }).catch(() => {});
  }

  // Try multiple selectors, return first non-empty text found
  function getTextFrom(root, ...selectors) {
    for (const sel of selectors) {
      const text = root.querySelector(sel)?.textContent.trim();
      if (text) return text;
    }
    return '';
  }

  // ─── Scrape row (before opening modal) ───────────────────────────────────

  function scrapeRow(row) {
    // <span data-role="text.value-date"> 14/05/2026 19:09:25 </span>
    const customerDate = getTextFrom(row,
      '[data-role="text.value-date"]',
      '[data-role="value-date"]',
      '[data-role="transaction-date"]',
    );

    const closingBalance = getTextFrom(row,
      '[data-role="running-balance"]',
      '[data-role="closing-balance"]',
      '[data-role="balance"]',
      'td:last-child .amount',
      'td:last-child',
    );

    return { customerDate, closingBalance };
  }

  // ─── Scrape modal data ────────────────────────────────────────────────────

  function scrapeModal() {
    const getText = (sel) => document.querySelector(sel)?.textContent.trim() ?? '';

    const amountEl = document.querySelector('[data-role="table-details-amount"]');
    let amount = '';
    if (amountEl) {
      const sign    = amountEl.querySelector('.sign')?.textContent.trim()    ?? '';
      const integer = amountEl.querySelector('.integer')?.textContent.trim() ?? '';
      amount = (sign === '+' ? '' : sign) + integer;
    }

    const description = getText('[data-role="table-details-description-section"] [data-role="section-content"]');

    // Parse ref after '#' or '*' e.g. #GZZVVPV8P2 or *3LVXDQZGX2 → code part
    const refMatch = description.match(/[#*]([A-Z0-9]+)/);
    const refFromDesc = refMatch ? refMatch[1] : '';

    // Parse card number after 'SO THE ' e.g. SO THE 402156...2175 → 402156...2175
    const cardMatch = description.match(/SO\s+THE\s+([0-9.*]+(?:\.\.\.[0-9]+)?)/i);
    const cardNumber = cardMatch ? cardMatch[1] : '';

    return {
      date:          getText('[data-role="table-details-booking-date"] .value-date'),
      name:          getText('[data-role="table-details-merchant"] strong'),
      accountNumber: getText('[data-role="table-details-account-number-section"] [data-role="section-content"]'),
      bankName:      getText('[data-role="table-details-bank-name-section"] [data-role="section-content"]'),
      reference:     getText('[data-role="table-details-reference-section"] [data-role="section-content"]'),
      amount,
      description,
      refFromDesc,
      cardNumber,
    };
  }

  // ─── Excel export (SheetJS .xlsx) ────────────────────────────────────────

  const HEADERS = [
    'Ngày GD',
    'Tên',
    'Số TK',
    'Ngân hàng',
    'Số tham chiếu',
    'Số tiền',
    'Số dư cuối',
    'Mã FACEBK',
    'App Code',
    'Nội dung đầy đủ',
  ];

  function downloadExcel(transactions) {
    const rows = transactions.map(t => [
      t.customerDate,
      t.name,
      t.accountNumber,
      t.bankName,
      t.reference,
      t.amount,
      t.closingBalance,
      t.refFromDesc,
      t.cardNumber,
      t.description,
    ]);

    const ws = XLSX.utils.aoa_to_sheet([HEADERS, ...rows]);

    // Bold header row
    const range = XLSX.utils.decode_range(ws['!ref']);
    for (let c = range.s.c; c <= range.e.c; c++) {
      const addr = XLSX.utils.encode_cell({ r: 0, c });
      if (ws[addr]) ws[addr].s = { font: { bold: true } };
    }

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Giao dịch');
    XLSX.writeFile(wb, `tcb_transactions_${new Date().toISOString().slice(0, 10)}.xlsx`);
  }

  // ─── Core scraping logic ──────────────────────────────────────────────────

  async function scrapePage() {
    const rowCount = document.querySelectorAll(
      'tr[aria-label="click transaction for more details"]'
    ).length;

    if (rowCount === 0) return false;

    for (let i = 0; i < rowCount; i++) {
      if (!state.running) return false;

      // Re-query each iteration — Angular re-renders the list after each modal close
      const row = document.querySelectorAll(
        'tr[aria-label="click transaction for more details"]'
      )[i];
      if (!row) continue;

      state.processed++;

      sendProgress(
        `Trang ${state.currentPage} — giao dịch ${i + 1}/${rowCount}`,
        state.processed,
        state.total,
      );

      // Grab row-level data BEFORE clicking (Angular may re-render rows after modal closes)
      const rowData = scrapeRow(row);

      // Click row to open modal
      row.click();

      try {
        await waitForElement('bb-transactions-table-details', 5000);
        await delay(300); // let Angular finish rendering

        const modalData = scrapeModal();
        state.transactions.push({ ...rowData, ...modalData });

        const closeBtn = document.querySelector('button[aria-label="Close dialog"]');
        if (closeBtn) closeBtn.click();

        await waitForElementGone('bb-transactions-table-details', 5000);
      } catch (err) {
        console.warn('[TCB Scraper] Modal error:', err.message);
        // Merge what we have; leave modal fields empty
        state.transactions.push({
          ...rowData,
          date: '', name: '', accountNumber: '', bankName: '',
          reference: '', refFromDesc: '', cardNumber: '',
          amount: '', description: '',
        });
        const closeBtn = document.querySelector('button[aria-label="Close dialog"]');
        if (closeBtn) closeBtn.click();
        await delay(500);
      }

      await delay(800);
    }

    return true;
  }

  async function goToNextPage() {
    const nextBtn = document.querySelector('[data-role="pagination-icon-next"]');
    if (!nextBtn || nextBtn.disabled || nextBtn.hasAttribute('disabled')) return false;
    if (nextBtn.getAttribute('aria-disabled') === 'true') return false;

    const currentFirstRow = document.querySelector(
      'tr[aria-label="click transaction for more details"]'
    )?.textContent;

    let pageChanged = false;

    // Set up observer BEFORE clicking so we don't miss fast page transitions
    const changePromise = new Promise((resolve) => {
      const timeout = setTimeout(() => { observer.disconnect(); resolve(); }, 8000);
      const observer = new MutationObserver(() => {
        const newFirst = document.querySelector(
          'tr[aria-label="click transaction for more details"]'
        )?.textContent;
        if (newFirst && newFirst !== currentFirstRow) {
          pageChanged = true;
          clearTimeout(timeout);
          observer.disconnect();
          resolve();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    });

    nextBtn.click();

    try {
      await changePromise;
    } catch (err) {
      console.warn('[TCB Scraper] Pagination error:', err.message);
    }

    if (!pageChanged) return false;

    state.currentPage++;
    return true;
  }

  async function runScraper(maxPages) {
    state.running      = true;
    state.transactions = [];
    state.currentPage  = 1;
    state.processed    = 0;
    state.total        = 0;
    state.maxPages     = maxPages || 0;

    sendProgress('Bắt đầu cào dữ liệu...', 0, 0);

    try {
      while (state.running) {
        // Estimate total for progress bar
        const rowCount = document.querySelectorAll(
          'tr[aria-label="click transaction for more details"]'
        ).length;
        const pagesLeft = state.maxPages > 0
          ? state.maxPages - state.currentPage + 1
          : 99;
        state.total = state.processed + rowCount * Math.min(pagesLeft, 10);

        const pageOk = await scrapePage();
        if (!pageOk) break;

        // Stop if we've reached the requested number of pages
        if (state.maxPages > 0 && state.currentPage >= state.maxPages) break;

        const hasNext = await goToNextPage();
        if (!hasNext) break;
      }
    } catch (err) {
      console.error('[TCB Scraper] Fatal error:', err);
    }

    state.running = false;
    const total = state.transactions.length;
    sendProgress(`Hoàn thành! Đã cào ${total} giao dịch.`, total, total);

    if (total > 0) downloadExcel(state.transactions);
  }

  // ─── Message listener ─────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    switch (msg.type) {
      case 'START_SCRAPE':
        if (!state.running) {
          runScraper(msg.maxPages || 0);
          sendResponse({ ok: true });
        } else {
          sendResponse({ ok: false, reason: 'Already running' });
        }
        break;

      case 'STOP_SCRAPE':
        state.running = false;
        sendResponse({ ok: true });
        break;

      case 'GET_STATUS':
        sendResponse({
          running:   state.running,
          count:     state.transactions.length,
          page:      state.currentPage,
          processed: state.processed,
          maxPages:  state.maxPages,
        });
        break;

      case 'DOWNLOAD_CSV':
        if (state.transactions.length > 0) {
          downloadExcel(state.transactions);
          sendResponse({ ok: true });
        } else {
          sendResponse({ ok: false, reason: 'No data' });
        }
        break;

      case 'GET_DATA':
        sendResponse({ ok: true, transactions: state.transactions });
        break;

      case 'CLEAR_DATA':
        state.transactions = [];
        state.processed    = 0;
        state.currentPage  = 1;
        state.maxPages     = 0;
        sendResponse({ ok: true });
        break;
    }

    return true;
  });

  console.log('[TCB Scraper] Content script loaded.');
})();
