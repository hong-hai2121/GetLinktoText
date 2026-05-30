(() => {
  'use strict';

  if (window.__fbBillingLoaded) return;
  window.__fbBillingLoaded = true;

  // ── State ──────────────────────────────────────────────────────────────────
  const state = {
    running:      false,
    phase:        'idle',   // 'list' | 'detail' | 'idle'
    scrapedList:   [],      // {txId, txLink, date, amount, paymentMethod, reference, status, vatId}
    scrapedDetail: [],      // {listTxId, txId, amount, reason, dateTime, ..., campaigns[]}
    processed:    0,
    total:        0,
    selectedDateRange: '',
    accountName:  '',
  };

  // ── Utilities ──────────────────────────────────────────────────────────────

  function waitForElement(selector, timeout = 8000) {
    return new Promise((resolve, reject) => {
      const el = document.querySelector(selector);
      if (el) return resolve(el);
      const timer = setTimeout(() => { obs.disconnect(); reject(new Error('Timeout: ' + selector)); }, timeout);
      const obs = new MutationObserver(() => {
        const found = document.querySelector(selector);
        if (found) { clearTimeout(timer); obs.disconnect(); resolve(found); }
      });
      obs.observe(document.body, { childList: true, subtree: true });
    });
  }

  // URL polling (MutationObserver can't detect pushState alone)
  function waitForUrlContains(substr, timeout = 12000) {
    if (location.href.includes(substr)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + timeout;
      let obs;
      function check() {
        if (location.href.includes(substr))  { obs?.disconnect(); resolve();                          return true; }
        if (Date.now() >= deadline)           { obs?.disconnect(); reject(new Error('URL timeout: ' + substr)); return true; }
        return false;
      }
      function poll() { if (!check()) setTimeout(poll, 200); }
      setTimeout(poll, 200);
      obs = new MutationObserver(check);
      obs.observe(document.body, { childList: true, subtree: true });
    });
  }

  function waitForUrlNotContains(substr, timeout = 12000) {
    if (!location.href.includes(substr)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + timeout;
      function poll() {
        if (!location.href.includes(substr)) { resolve(); return; }
        if (Date.now() >= deadline)           { reject(new Error('URL not-gone timeout: ' + substr)); return; }
        setTimeout(poll, 200);
      }
      setTimeout(poll, 200);
    });
  }

  function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

  function sendProgress(message, current, total) {
    chrome.runtime.sendMessage({ type: 'PROGRESS', message, current, total, phase: state.phase }).catch(() => {});
  }

  // ── Page detection ─────────────────────────────────────────────────────────

  // DOM-based detection — URL patterns on Facebook are unreliable
  function isListPage() {
    // List page always has the transaction grid table visible
    return !!getTransactionTable();
  }

  function isDetailPage() {
    const url = location.href;
    // Try URL hints first (best case)
    if (url.includes('billing_transaction') || /[?&](billing_)?transaction_id=/i.test(url)) return true;
    // DOM fallback: on a billing URL but the transaction table is gone → detail page
    if (url.includes('billing') && !getTransactionTable()) return true;
    return false;
  }

  // ── DOM helpers ────────────────────────────────────────────────────────────

  function normalizeText(str) {
    return String(str ?? '')
      .replace(/\u00a0/g, ' ')
      .replace(/[\u200b-\u200f\u2060\ufeff]/g, '')
      .replace(/[ \t\r\n]+/g, ' ')
      .trim();
  }

  function findButtonByText(text, { skipHidden = true } = {}) {
    const targetText = normalizeText(text);
    for (const sel of ['[role="button"]', 'button', 'a']) {
      for (const el of document.querySelectorAll(sel)) {
        // Skip aria-hidden elements (e.g. tab overflow "Xem thêm" nav button)
        if (skipHidden && el.getAttribute('aria-hidden') === 'true') continue;
        if (normalizeText(el.innerText || el.textContent) === targetText) return el;
      }
    }
    return null;
  }

  function findButtonByTextAny(texts, options = {}) {
    for (const text of texts) {
      const el = findButtonByText(text, options);
      if (el) return el;
    }
    return null;
  }

  function looksLikeDateRangeText(text) {
    const t = normalizeText(text);
    if (!t || t.length > 90) return false;
    return /\d{1,2}\s+Tháng\s+\d{1,2},\s+\d{4}/i.test(t)
      || /\d{1,2}\s+Thg\s+\d{1,2},\s+\d{4}/i.test(t)
      || /\d{1,2}\/\d{1,2}\/\d{2,4}/.test(t)
      || /Hôm nay|Hôm qua|Tháng này|Tháng trước|7 ngày qua|30 ngày qua/i.test(t);
  }

  function findDateRangeButton() {
    return Array.from(document.querySelectorAll('[role="button"], button'))
      .find(el => looksLikeDateRangeText(el.innerText || el.textContent));
  }

  function getCurrentDateRangeText() {
    const btn = findDateRangeButton();
    return normalizeText(btn?.innerText || btn?.textContent);
  }

  function parseDateRangeText(text) {
    const parts = normalizeText(text).split(/\s+[–-]\s+/);
    if (parts.length < 2) return null;

    const parsePart = (part) => {
      let m = part.match(/(\d{1,2})\s+Th(?:áng|g)\s+(\d{1,2}),\s+(\d{4})/i);
      if (m) {
        const [, day, month, year] = m;
        return `${day.padStart(2, '0')}/${month.padStart(2, '0')}/${year}`;
      }

      m = part.match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
      if (!m) return '';
      const [, day, month, year] = m;
      return `${day.padStart(2, '0')}/${month.padStart(2, '0')}/${year.length === 2 ? '20' + year : year}`;
    };

    const start = parsePart(parts[0]);
    const end = parsePart(parts[1]);
    return start && end ? { start, end } : null;
  }

  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function findDatePickerConfirmButton() {
    return Array.from(document.querySelectorAll('[role="button"], button'))
      .find(el => {
        const text = normalizeText(el.innerText || el.textContent);
        return ['Cập nhật', 'Áp dụng', 'Apply', 'Update'].includes(text)
          && isVisible(el)
          && el.getAttribute('aria-disabled') !== 'true'
          && !el.disabled;
      });
  }

  async function clickDatePickerConfirmButton(waitMs = 1000) {
    const applyBtn = findDatePickerConfirmButton();
    if (!applyBtn) return false;
    clickElement(applyBtn);
    await delay(waitMs);
    return true;
  }

  function parseDMYDate(value) {
    const m = normalizeText(value).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (!m) return null;
    const [, day, month, year] = m;
    return new Date(Number(year), Number(month) - 1, Number(day));
  }

  function calendarAriaLabels(date) {
    const weekdays = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    return [
      `${weekdays[date.getDay()]}, ${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`,
      `${weekdays[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`,
    ];
  }

  function findCalendarDayButton(date) {
    const labels = calendarAriaLabels(date);
    return Array.from(document.querySelectorAll('[role="button"][aria-label]'))
      .find(el => labels.includes(normalizeText(el.getAttribute('aria-label'))) && isVisible(el));
  }

  function getVisibleCalendarMonthKeys() {
    return Array.from(document.querySelectorAll('h2'))
      .map(h => normalizeText(h.innerText || h.textContent).match(/Tháng\s+(\d{1,2})\s+(\d{4})/i))
      .filter(Boolean)
      .map(([, month, year]) => Number(year) * 12 + Number(month) - 1)
      .sort((a, b) => a - b);
  }

  async function ensureCalendarDateVisible(date) {
    const targetKey = date.getFullYear() * 12 + date.getMonth();

    for (let i = 0; i < 12; i++) {
      if (findCalendarDayButton(date)) return true;

      const visibleKeys = getVisibleCalendarMonthKeys();
      if (!visibleKeys.length) return false;

      const directionBtn = targetKey < visibleKeys[0]
        ? findButtonByText('Tháng trước', { skipHidden: false })
        : findButtonByText('Tháng tới', { skipHidden: false });
      if (!directionBtn) return false;

      clickElement(directionBtn);
      await delay(350);
    }

    return !!findCalendarDayButton(date);
  }

  async function applyDateRangeFromCalendar() {
    const range = parseDateRangeText(state.selectedDateRange);
    if (!range) return false;

    const startDate = parseDMYDate(range.start);
    const endDate = parseDMYDate(range.end);
    if (!startDate || !endDate) return false;

    if (!await ensureCalendarDateVisible(startDate)) return false;
    const startBtn = findCalendarDayButton(startDate);
    if (!startBtn) return false;
    clickElement(startBtn);
    await delay(250);

    if (!await ensureCalendarDateVisible(endDate)) return false;
    const endBtn = findCalendarDayButton(endDate);
    if (!endBtn) return false;
    clickElement(endBtn);
    await delay(250);

    if (!await clickDatePickerConfirmButton(1000)) return false;
    return getCurrentDateRangeText() === state.selectedDateRange;
  }

  function findDatePickerInputs() {
    return Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
      .filter(input => {
        if (!isVisible(input) || input.disabled || input.getAttribute('aria-disabled') === 'true') return false;
        const placeholder = normalizeText(input.getAttribute('placeholder'));
        const label = normalizeText(input.getAttribute('aria-label'));
        return !placeholder.includes('ID giao dịch') && !label.includes('ID giao dịch');
      });
  }

  async function applyDateRangeFromInputs() {
    const range = parseDateRangeText(state.selectedDateRange);
    if (!range) return false;

    const customBtn = findButtonByTextAny(['Tùy chỉnh', 'Custom'], { skipHidden: false });
    if (customBtn) {
      clickElement(customBtn);
      await delay(400);
    }

    const inputs = findDatePickerInputs();
    if (inputs.length < 2) return applyDateRangeFromCalendar();

    setNativeInputValue(inputs[0], range.start);
    setNativeInputValue(inputs[1], range.end);
    await delay(300);

    if (!await clickDatePickerConfirmButton(1000)) return false;
    return getCurrentDateRangeText() === state.selectedDateRange;
  }

  function rememberCurrentDateRange() {
    const dateRange = getCurrentDateRangeText();
    if (dateRange) state.selectedDateRange = dateRange;
    return state.selectedDateRange;
  }

  async function restoreRememberedDateRange(timeout = 6000) {
    if (!state.selectedDateRange) return true;

    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const current = getCurrentDateRangeText();
      if (current === state.selectedDateRange) return true;
      if (current) break;
      await delay(200);
    }

    const dateBtn = findDateRangeButton();
    if (!dateBtn) return false;
    clickElement(dateBtn);
    await delay(500);

    const savedOption = findButtonByText(state.selectedDateRange, { skipHidden: false })
      || Array.from(document.querySelectorAll('[role="button"], button'))
        .find(el => normalizeText(el.innerText || el.textContent) === state.selectedDateRange);
    if (!savedOption) return applyDateRangeFromInputs();

    clickElement(savedOption);
    await delay(500);

    await clickDatePickerConfirmButton(800);

    return getCurrentDateRangeText() === state.selectedDateRange;
  }

  function isTooltipReallyVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const s = window.getComputedStyle(el);
    return s.opacity !== '0' && s.visibility !== 'hidden' && s.display !== 'none';
  }

  async function getFullTextHover(el, timeout = 1500) {
    if (!el) return '';
    const span = el.querySelector('span') || el;
    const raw = normalizeText(span.innerText || span.textContent);
    if (!raw.endsWith('...')) return raw;

    // Try title / aria-label first (instant, no side effects)
    for (const attr of ['title', 'aria-label']) {
      const v = span.getAttribute(attr) || el.getAttribute(attr);
      if (v && !v.endsWith('...')) return normalizeText(v);
    }

    // Record previous tooltip content — only accept tooltip when content CHANGES
    const prevText = normalizeText(
      document.querySelector('[role="tooltip"]')?.innerText ||
      document.querySelector('[role="tooltip"]')?.textContent || ''
    );

    // Wait for previous tooltip to truly hide (check opacity/visibility, not just dimensions)
    const clearDeadline = Date.now() + 700;
    while (Date.now() < clearDeadline) {
      if (!isTooltipReallyVisible(document.querySelector('[role="tooltip"]'))) break;
      await delay(50);
    }

    // Trigger hover to show Facebook tooltip
    for (const type of ['pointerenter', 'mouseenter', 'mouseover']) {
      span.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
    }

    const deadline = Date.now() + timeout;
    let fullText = '';
    while (Date.now() < deadline) {
      const tip = document.querySelector('[role="tooltip"]');
      if (isTooltipReallyVisible(tip)) {
        const t = normalizeText(tip.innerText || tip.textContent);
        // Only accept if content is new (not leftover from previous hover)
        if (t && !t.endsWith('...') && t !== prevText) { fullText = t; break; }
      }
      await delay(80);
    }

    for (const type of ['pointerleave', 'mouseleave', 'mouseout']) {
      span.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
    }
    await delay(200);

    return fullText || raw;
  }

  function clickElement(el) {
    if (!el) return false;
    el.scrollIntoView?.({ block: 'center', inline: 'center' });
    el.focus?.();
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
    return true;
  }

  function setNativeInputValue(input, value) {
    const proto = input instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(input, value);
    else input.value = value;
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function findBackButton() {
    return findButtonByText('Trước')
      || Array.from(document.querySelectorAll('div[role="button"], [role="button"], button, a'))
        .find(el => normalizeText(el.innerText || el.textContent) === 'Trước');
  }

  async function waitForBackButton(timeout = 5000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const backBtn = findBackButton();
      if (backBtn) return backBtn;
      await delay(150);
    }
    return null;
  }

  async function goBackToTransactionList() {
    const backBtn = await waitForBackButton();
    if (clickElement(backBtn)) return true;
    history.back();
    return false;
  }

  // Account name heading: "Tên tài khoản (ID)" — any heading containing a long numeric account ID
  function detectAccountName() {
    for (const el of document.querySelectorAll('[role="heading"]')) {
      const text = normalizeText(el.innerText || el.textContent || '');
      if (/\(\d{10,}\)/.test(text)) return text;
    }
    return '';
  }

  // Find the transaction table specifically (aria-label="Giao dịch")
  function getTransactionTable() {
    return document.querySelector('table[aria-label="Giao dịch"][role="grid"]')
        || document.querySelector('table[role="grid"]');
  }

  function findTransactionSearchInput() {
    return Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
      .find(input => {
        const placeholder = normalizeText(input.getAttribute('placeholder'));
        return placeholder.includes('ID giao dịch') || placeholder.toLowerCase().includes('transaction id');
      });
  }

  async function waitForTransactionSearchInput(timeout = 10000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const input = findTransactionSearchInput();
      if (input) return input;
      await delay(200);
    }
    return null;
  }

  function findRowByTxId(txId) {
    const table = getTransactionTable();
    if (!table) return null;

    const rows = Array.from(table.querySelectorAll('tr[role="row"]'))
      .filter(r => !r.querySelector('[role="columnheader"]'));

    for (const row of rows) {
      const c1 = row.querySelector('[aria-colindex="1"]');
      const id = normalizeText(c1?.querySelector('a')?.textContent || c1?.textContent);
      if (id === txId) return row;
    }

    return null;
  }

  function canonicalText(str) {
    return normalizeText(str).replace(/[:：]\s*$/, '').toLowerCase();
  }

  function stripInlineLabelValue(text, labels) {
    const source = normalizeText(text);
    if (!source || source.length > 220) return '';

    for (const label of labels) {
      const normalizedLabel = normalizeText(label);
      if (!normalizedLabel || source === normalizedLabel) continue;
      if (!source.toLowerCase().startsWith(normalizedLabel.toLowerCase())) continue;

      const value = normalizeText(source.slice(normalizedLabel.length).replace(/^[:：\-\s]+/, ''));
      if (value) return value;
    }
    return '';
  }

  // Find value paired with a label text node.
  // Walks up ancestor chain looking for a sibling containing the value.
  function findValueByLabels(labelTexts, root = document) {
    const labels = [].concat(labelTexts).filter(Boolean);
    const labelSet = new Set(labels.map(canonicalText));

    for (const el of root.querySelectorAll('span, div, label')) {
      const text = normalizeText(el.innerText || el.textContent);
      if (!labelSet.has(canonicalText(text))) continue;
      if (el.children.length > 1) continue; // skip containers that just happen to match

      for (let cur = el, lvl = 0; cur && lvl < 5; cur = cur.parentElement, lvl++) {
        const sib = cur.nextElementSibling;
        if (sib) {
          const heading = sib.querySelector('[role="heading"]');
          const value = normalizeText(heading?.innerText || heading?.textContent || sib.innerText || sib.textContent);
          if (value && !labelSet.has(canonicalText(value))) return value;
        }

        const inlineValue = stripInlineLabelValue(cur.parentElement?.innerText || cur.parentElement?.textContent, labels);
        if (inlineValue) return inlineValue;
      }
    }
    return '';
  }

  function findValueByLabel(labelText, root = document) {
    return findValueByLabels([labelText], root);
  }

  function cleanNumber(str) {
    // Remove ₫, spaces, +; dots are VN thousands separators → strip them
    return String(str ?? '').replace(/[₫+\s]/g, '').replace(/\./g, '').replace(',', '.').trim();
  }

  function splitDateTime(text) {
    const t = normalizeText(text);
    if (!t) return { date: '', time: '' };

    const trailingTime = t.match(/^(.*?)(?:,?\s+(?:lúc|at)\s+|\s*,\s*)(\d{1,2}:\d{2}(?:\s*[AP]M)?)(?:\s+.*)?$/i);
    if (trailingTime) {
      return {
        date: normalizeText(trailingTime[1]),
        time: normalizeText(trailingTime[2]),
      };
    }

    const leadingTime = t.match(/^(\d{1,2}:\d{2}(?:\s*[AP]M)?)\s+(.+)$/i);
    if (leadingTime) {
      return {
        date: normalizeText(leadingTime[2]),
        time: normalizeText(leadingTime[1]),
      };
    }

    return { date: t, time: '' };
  }

  function extractCardLast4(...parts) {
    const text = normalizeText(parts.filter(Boolean).join(' '));
    // Cover all common masked-card characters including various Unicode dots/bullets
    const masked = text.match(/(?:\*|x|X|[•·∙‧⋅·]|\.){2,}\s*(\d{4})(?!\d)/u);
    if (masked) return masked[1];
    // Fallback: 4 digits at end of string (handles "Visa ···· 2175" → "2175")
    const trailing = text.match(/(\d{4})\s*$/);
    if (trailing) return trailing[1];
    const allGroups = Array.from(text.matchAll(/\b(\d{4})(?!\d)\b/g));
    return allGroups.length ? allGroups[allGroups.length - 1][1] : '';
  }

  function normalizeCellText(str) {
    return normalizeText(str);
  }

  function isLikelyCardReference(text) {
    const s = normalizeCellText(text);
    return /^[A-Z0-9][A-Z0-9_-]{5,}$/i.test(s) && !/\s/.test(s) && !/[\u00b7\u2022*.]/.test(s);
  }

  function splitInlinePaymentAndReference(text) {
    const s = normalizeCellText(text);
    const match = s.match(/^(.+?)\s+([A-Z0-9][A-Z0-9_-]{5,})$/i);
    if (!match) return null;

    const method = normalizeCellText(match[1]);
    const reference = normalizeCellText(match[2]);
    const looksLikePaymentMethod =
      /visa|mastercard|american express|amex|discover|jcb|paypal|momo|zalopay|bank|card|thẻ|ngân hàng/i.test(method)
      || /[\u00b7\u2022*]{2,}|x{2,}/i.test(method);

    return looksLikePaymentMethod && isLikelyCardReference(reference)
      ? { paymentMethod: method, reference }
      : null;
  }

  function getCellTextLines(el) {
    if (!el) return [];

    const rawLines = (el.innerText || el.textContent || '')
      .split(/\r?\n/)
      .map(normalizeCellText)
      .filter(Boolean);

    if (rawLines.length > 1) return rawLines;

    const childLines = Array.from(el.children)
      .map(child => normalizeCellText(child.innerText || child.textContent))
      .filter(Boolean);

    return childLines.length > 1 ? childLines : rawLines;
  }

  function parsePaymentCell(cellEl) {
    const lines = getCellTextLines(cellEl);
    const fullText = normalizeCellText(cellEl?.innerText || cellEl?.textContent || '');

    if (lines.length > 1) {
      const referenceIndex = lines.findIndex(isLikelyCardReference);
      if (referenceIndex >= 0) {
        return {
          paymentMethod: lines.slice(0, referenceIndex).join(' ') || lines.find(line => !isLikelyCardReference(line)) || '',
          reference: lines[referenceIndex],
        };
      }

      return {
        paymentMethod: lines[0] || '',
        reference: lines[1] || '',
      };
    }

    const inline = splitInlinePaymentAndReference(fullText);
    if (inline) return inline;

    return {
      paymentMethod: fullText,
      reference: '',
    };
  }

  // ── List page: scrape one row ──────────────────────────────────────────────

  function scrapeListRow(row) {
    const cell = (i) => row.querySelector(`[aria-colindex="${i}"]`);

    // Col 1: ID giao dịch — <a> text
    const c1 = cell(1);
    const txId   = c1?.querySelector('a')?.textContent.trim() || c1?.textContent.trim() || '';
    const txLink = c1?.querySelector('a')?.href || '';

    // Col 2: Ngày — first <span> text
    const c2 = cell(2);
    const date = c2?.querySelector('span')?.textContent.trim() || c2?.textContent.trim() || '';

    // Col 3: Số tiền — first <span> text
    const c3 = cell(3);
    const amount = cleanNumber(c3?.querySelector('span')?.textContent.trim() || c3?.textContent.trim() || '');

    // Col 4: payment method + card reference. Facebook may render these as two
    // visual lines inside one wrapper, e.g. "Visa .... 2175" over "UMEE7QM8P2".
    const c4 = cell(4);
    const { paymentMethod, reference } = parsePaymentCell(c4);

    // Col 5: Trạng thái thanh toán
    const status = cell(5)?.textContent.trim() || '';

    // Col 6: ID hóa đơn VAT
    const vatId  = cell(6)?.textContent.trim() || '';

    return { txId, txLink, date, amount, paymentMethod, reference, status, vatId };
  }

  // ── List page: main loop ───────────────────────────────────────────────────

  async function runListScrape() {
    state.running = true;
    state.phase   = 'list';
    state.scrapedList  = [];
    state.processed    = 0;
    state.total        = 0;
    state.accountName  = detectAccountName();

    sendProgress('Đang tìm bảng giao dịch...', 0, 0);

    try {
      await waitForElement('table[role="grid"]', 8000);
    } catch {
      sendProgress('Không tìm thấy bảng giao dịch. Hãy đảm bảo bạn đang ở trang danh sách.', 0, 0);
      state.running = false;
      state.phase   = 'idle';
      return;
    }

    const seenIds = new Set();

    while (state.running) {
      const table = getTransactionTable();
      if (!table) break;

      const rows = Array.from(table.querySelectorAll('tr[role="row"]'))
        .filter(r => !r.querySelector('[role="columnheader"]'));

      for (const row of rows) {
        const data = scrapeListRow(row);
        if (!data.txId || seenIds.has(data.txId)) continue;
        seenIds.add(data.txId);
        state.scrapedList.push(data);
      }

      state.processed = state.scrapedList.length;
      sendProgress(`Đã cào ${state.scrapedList.length} giao dịch...`, state.scrapedList.length, 0);

      // Click "Xem thêm" if available
      const loadMoreBtn = findButtonByText('Xem thêm');
      if (!loadMoreBtn || !state.running) break;

      const countBefore = rows.length;
      loadMoreBtn.click();

      // Wait for new rows to appear in the table
      await new Promise(resolve => {
        const t = setTimeout(resolve, 8000);
        const obs = new MutationObserver(() => {
          const tbl = getTransactionTable();
          const newCount = tbl ? tbl.querySelectorAll('tr[role="row"]').length : 0;
          if (newCount > countBefore) { clearTimeout(t); obs.disconnect(); resolve(); }
        });
        obs.observe(document.body, { childList: true, subtree: true });
      });

      await delay(400);
    }

    state.running = false;
    state.phase   = 'idle';
    const n = state.scrapedList.length;
    sendProgress(`Hoàn thành! Đã cào ${n} giao dịch trong danh sách.`, n, n);
  }

  // ── Detail page: find row by txId using the transaction search box ─────────

  async function findRowBySearch(txId, timeout = 20000) {
    const deadline = Date.now() + timeout;
    const input = await waitForTransactionSearchInput(Math.min(10000, timeout));

    if (input) {
      input.focus();
      setNativeInputValue(input, txId);
    }

    while (Date.now() < deadline) {
      const row = findRowByTxId(txId);
      if (row) return row;
      await delay(300);
    }

    return null;
  }

  // ── Detail page: campaign / ad group extraction ────────────────────────────

  // Facebook billing detail page uses a div-based grid (no <table>).
  // Structure per campaign block:
  //   sectionEl (direct children: innerWrapper | headerRow | dataRow | totalRow)
  //     innerWrapper → nameSection → headingGroup (xeuugli)
  //       [aria-level="2" role="heading"]  ← campaign name
  //       div (sibling)                    ← time period "Từ ... đến ..."
  //     headerRow: [aria-level="4"] headings = column labels
  //     dataRow:   <span> elements = actual truncated values
  //     totalRow:  [aria-level="4"] "Tổng số" + <span> "Số lần hiển thị" = loại kết quả

  const COL_HEADER_LABELS = new Set([
    'tên nhóm quảng cáo', 'kết quả', 'số tiền', 'id nhóm quảng cáo',
  ]);

  function scrapeCampaigns() {
    const campaigns = [];

    // aria-level="1" = page title, aria-level="4" = column headers/values.
    // Campaign names are exclusively aria-level="2". Filter hidden/transitioning duplicates.
    const seen = new Set();
    const campaignHeadings = Array.from(
      document.querySelectorAll('[aria-level="2"][role="heading"]')
    ).filter(el => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      const text = normalizeText(el.innerText || el.textContent);
      if (seen.has(text)) return false;
      seen.add(text);
      return true;
    });

    for (const heading of campaignHeadings) {
      const campaignName = normalizeText(heading.innerText || heading.textContent);
      if (!campaignName) continue;

      // Time period is a sibling of the heading inside the same parent (headingGroup div).
      const headingGroup = heading.parentElement;
      let timePeriod = '';
      for (const child of Array.from(headingGroup?.children || [])) {
        if (child === heading) continue;
        const t = normalizeText(child.innerText || child.textContent);
        if (t.startsWith('Từ') && t.includes('đến')) { timePeriod = t; break; }
      }

      // Walk up to find the "section container": the first ancestor whose DIRECT
      // children include one that contains a "Tổng số" level-4 heading.
      let sectionEl = headingGroup?.parentElement;
      for (let i = 0; i < 8 && sectionEl && sectionEl !== document.body; i++) {
        const hasTotalChild = Array.from(sectionEl.children).some(child =>
          Array.from(child.querySelectorAll('[aria-level="4"][role="heading"]'))
            .some(h => normalizeText(h.innerText || h.textContent) === 'Tổng số')
        );
        if (hasTotalChild) break;
        sectionEl = sectionEl.parentElement;
      }
      if (!sectionEl || sectionEl === document.body) continue;

      // Categorise direct children of sectionEl.
      let totalRowEl = null;
      let dataRowEl  = null;

      for (const child of Array.from(sectionEl.children)) {
        if (child.contains(heading)) continue; // skip the name/time section

        const h4Texts = Array.from(
          child.querySelectorAll('[aria-level="4"][role="heading"]')
        ).map(h => normalizeText(h.innerText || h.textContent).toLowerCase());

        if (h4Texts.includes('tổng số')) {
          totalRowEl = child;
        } else if (h4Texts.length > 0 && h4Texts.every(t => COL_HEADER_LABELS.has(t))) {
          // All level-4 headings are column label names → header row, skip
        } else if (child.querySelector('span')) {
          dataRowEl = child; // has span values but no level-4 column-name headings
        }
      }

      // loại kết quả: a <span> in the total row that is NOT inside a heading
      // e.g. "Số lần hiển thị"
      let resultType = '';
      if (totalRowEl) {
        for (const span of totalRowEl.querySelectorAll('span')) {
          if (span.closest('[role="heading"]')) continue;
          const t = normalizeText(span.innerText || span.textContent);
          if (t && !/^\d[\d.,\s]*$/.test(t)) { resultType = t; break; }
        }
      }

      // Ad group data: 4 direct children of dataRowEl = [name, result, amount, id]
      let adGroup = null;
      if (dataRowEl) {
        const cols = Array.from(dataRowEl.children);
        if (cols.length >= 3) {
          const getText = col => normalizeText(col?.innerText || col?.textContent || '').replace(/\.{3}$/, '').trimEnd();
          adGroup = {
            name:       getText(cols[0]),
            result:     getText(cols[1]),
            resultType: resultType,
            amount:     cleanNumber(getText(cols[2])),
            id:         cols[3] ? getText(cols[3]) : '',
            note:       '',
          };
        }
      }

      campaigns.push({ campaignName, timePeriod, adGroups: adGroup ? [adGroup] : [] });
    }

    return campaigns;
  }

  function scrapeDetailPage(listItem = {}) {
    const rawDate = findValueByLabels(['Ngày thanh toán', 'Ngày']) || listItem.date || '';
    const rawTime = findValueByLabels(['Giờ thanh toán']);
    const split = splitDateTime(rawDate);
    const paymentMethod = findValueByLabels(['Phương thức thanh toán', 'Payment method']) || listItem.paymentMethod || '';
    const reference = findValueByLabels(['Số tham chiếu', 'Mã tham chiếu', 'Reference number']) || listItem.reference || '';
    const cardLast4 = listItem.paymentMethod || '';
    const totalAmount = cleanNumber(findValueByLabels(['Tổng tiền giao dịch', 'Tổng tiền', 'Số tiền', 'Total amount'])) || listItem.amount || '';
    const subtotal = cleanNumber(findValueByLabels(['Tổng phụ', 'Subtotal']));
    const tax = cleanNumber(findValueByLabels(['Thuế', 'Thuế VAT', 'VAT', 'Tax']));
    const status = findValueByLabels(['Trạng thái', 'Trạng thái thanh toán', 'Status']) || listItem.status || '';
    const note = findValueByLabels(['Ghi chú', 'Ghi chú giao dịch', 'Note', 'Notes']);

    return {
      txId:          findValueByLabels(['ID giao dịch', 'Transaction ID']) || listItem.txId || '',
      paymentDate:   split.date || rawDate,
      paymentTime:   rawTime || split.time,
      dateTime:      rawDate,
      reference,
      accountId:     findValueByLabels(['Tài khoản quảng cáo', 'Ad account']),
      paymentMethod,
      cardLast4,
      status,
      totalAmount,
      amount:        totalAmount,
      subtotal,
      tax,
      reason:        findValueByLabels(['Lý do lập hóa đơn', 'Lý do tính phí', 'Billing reason']),
      product:       findValueByLabels(['Sản phẩm', 'Product']),
      note,
      campaigns:     scrapeCampaigns(),
    };
  }

  // Wait for the detail page to fully appear — DOM-based, not URL-based.
  // Facebook may use various URL patterns (billing_transaction, transaction_id= etc.)
  // so we detect by DOM: list table gone + detail-specific content present.
  async function waitForDetailPageReady(timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (!getTransactionTable()) {
        // List table is gone; verify detail content has loaded
        const hasCampaignHeading = !!document.querySelector('[aria-level="2"][role="heading"]');
        const hasIdLabel = Array.from(document.querySelectorAll('span')).some(
          s => normalizeText(s.innerText || s.textContent) === 'ID giao dịch'
        );
        if (hasCampaignHeading || hasIdLabel) return true;
      }
      await delay(200);
    }
    return false;
  }

  // Wait for the list table to reappear after going back from detail page.
  async function waitForListPageReady(timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (getTransactionTable()) return true;
      await delay(200);
    }
    return false;
  }

  // ── Detail: main loop ──────────────────────────────────────────────────────

  async function runDetailScrape() {
    state.running      = true;
    state.phase        = 'detail';
    state.scrapedDetail = [];
    state.processed    = 0;
    state.total        = state.scrapedList.length;
    rememberCurrentDateRange();

    for (let i = 0; i < state.total; i++) {
      if (!state.running) break;

      const item = state.scrapedList[i];
      sendProgress(`Cào chi tiết ${i + 1}/${state.total}: ${item.txId}`, i + 1, state.total);

      // Search the list by transaction ID, then open the exact matching row.
      await restoreRememberedDateRange();
      const row = await findRowBySearch(item.txId, 20000);
      if (!row) {
        console.warn('[FB Scraper] Row not found:', item.txId);
        state.scrapedDetail.push({ listTxId: item.txId, error: 'Row not found by search' });
        continue;
      }

      const link = row.querySelector('[aria-colindex="1"] a');
      if (!link) {
        console.warn('[FB Scraper] No link in row:', item.txId);
        continue;
      }

      clickElement(link);

      try {
        // Use DOM-based detection — URL pattern varies across Facebook page versions
        const onDetail = await waitForDetailPageReady(15000);
        if (!onDetail) throw new Error('Trang chi tiết không tải được sau 15 giây');
        await delay(3000); // wait for full React render including campaign sections

        const detail = scrapeDetailPage(item);
        detail.listTxId = item.txId;
        state.scrapedDetail.push(detail);

        // Navigate back via the visible "Trước" button when Facebook renders one.
        await goBackToTransactionList();

        const onList = await waitForListPageReady(15000);
        if (!onList) { history.back(); await delay(1500); }
        await delay(600);
        await restoreRememberedDateRange();
      } catch (err) {
        console.warn('[FB Scraper] Detail error for', item.txId, ':', err.message);
        state.scrapedDetail.push({ listTxId: item.txId, error: err.message });
        try {
          history.back();
          await waitForListPageReady(8000);
        } catch (_) {}
      }

      await delay(600);
    }

    state.running = false;
    state.phase   = 'idle';
    const n = state.scrapedDetail.length;
    sendProgress(`Hoàn thành! Đã cào ${n} chi tiết.`, n, n);
  }


  // ── Message listener ───────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    switch (msg.type) {

      case 'START_LIST_SCRAPE':
        if (state.running) {
          sendResponse({ ok: false, reason: 'Already running' });
        } else {
          runListScrape();
          sendResponse({ ok: true });
        }
        break;

      case 'START_DETAIL_SCRAPE':
        if (state.running) {
          sendResponse({ ok: false, reason: 'Already running' });
        } else if (!state.scrapedList.length) {
          sendResponse({ ok: false, reason: 'Chưa có dữ liệu danh sách. Cào danh sách trước.' });
        } else {
          runDetailScrape();
          sendResponse({ ok: true });
        }
        break;

      case 'STOP_SCRAPE':
        state.running = false;
        sendResponse({ ok: true });
        break;

      case 'GET_STATUS':
        sendResponse({
          running:     state.running,
          phase:       state.phase,
          listCount:   state.scrapedList.length,
          detailCount: state.scrapedDetail.length,
          processed:   state.processed,
          total:       state.total,
          isListPage:  isListPage(),
          isDetailPage: isDetailPage(),
        });
        break;

      case 'EXPORT_CSV':
        sendResponse({ ok: true, list: state.scrapedList, detail: state.scrapedDetail, accountName: state.accountName || detectAccountName() });
        break;

      case 'CLEAR_DATA':
        Object.assign(state, { scrapedList: [], scrapedDetail: [], processed: 0, total: 0, phase: 'idle', selectedDateRange: '', accountName: '' });
        sendResponse({ ok: true });
        break;
    }
    return true;
  });

  console.log('[FB Billing Scraper] Loaded.');
})();
