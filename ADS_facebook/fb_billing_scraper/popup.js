(() => {
  'use strict';

  // ── Minimal XLSX generator (ZIP STORE + Open XML, no external library) ─────

  const _enc = new TextEncoder();

  function _crc32(bytes) {
    const t = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let j = 0; j < 8; j++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[i] = c;
    }
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) crc = t[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function _u16(n) { return [n & 0xFF, (n >> 8) & 0xFF]; }
  function _u32(n) { return [n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF, (n >>> 24) & 0xFF]; }

  function _zipStore(files) {
    const parts = [], cdEntries = [];
    let offset = 0;
    for (const { name, data } of files) {
      const nb = _enc.encode(name);
      const crc = _crc32(data), sz = data.length;
      const lfh = new Uint8Array([
        0x50, 0x4B, 0x03, 0x04, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        ..._u32(crc), ..._u32(sz), ..._u32(sz), ..._u16(nb.length), 0, 0,
      ]);
      parts.push(lfh, nb, data);
      const cde = new Uint8Array([
        0x50, 0x4B, 0x01, 0x02, 20, 0, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        ..._u32(crc), ..._u32(sz), ..._u32(sz), ..._u16(nb.length),
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ..._u32(offset),
      ]);
      cdEntries.push({ cde, nb });
      offset += lfh.length + nb.length + sz;
    }
    const cdStart = offset;
    let cdLen = 0;
    for (const { cde, nb } of cdEntries) { parts.push(cde, nb); cdLen += cde.length + nb.length; }
    parts.push(new Uint8Array([
      0x50, 0x4B, 0x05, 0x06, 0, 0, 0, 0,
      ..._u16(files.length), ..._u16(files.length),
      ..._u32(cdLen), ..._u32(cdStart), 0, 0,
    ]));
    const total = parts.reduce((s, p) => s + p.length, 0);
    const out = new Uint8Array(total);
    let pos = 0;
    for (const p of parts) { out.set(p, pos); pos += p.length; }
    return out;
  }

  function _xe(v) {
    return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _col(n) {
    let s = ''; n++;
    while (n > 0) { s = String.fromCharCode(64 + (n - 1) % 26 + 1) + s; n = Math.floor((n - 1) / 26); }
    return s;
  }

  function buildXlsx(sheets) {
    const NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
    const CT = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>${sheets.map((_,i)=>`<Override PartName="/xl/worksheets/sheet${i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')}<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`;
    const ROOT_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`;
    const WB = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="${NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${sheets.map((s,i)=>`<sheet name="${_xe(s.name)}" sheetId="${i+1}" r:id="rId${i+1}"/>`).join('')}</sheets></workbook>`;
    const WB_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_,i)=>`<Relationship Id="rId${i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i+1}.xml"/>`).join('')}<Relationship Id="rId${sheets.length+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`;
    const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="${NS}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>`;
    const wsFiles = sheets.map(({ headers, rows }, si) => {
      const allRows = [headers, ...rows];
      const xml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="${NS}"><sheetData>${allRows.map((row, ri) => `<row r="${ri+1}">${row.map((v, ci) => `<c r="${_col(ci)}${ri+1}" t="inlineStr"><is><t>${_xe(v)}</t></is></c>`).join('')}</row>`).join('')}</sheetData></worksheet>`;
      return { name: `xl/worksheets/sheet${si+1}.xml`, data: _enc.encode(xml) };
    });
    return _zipStore([
      { name: '[Content_Types].xml',        data: _enc.encode(CT) },
      { name: '_rels/.rels',                data: _enc.encode(ROOT_RELS) },
      { name: 'xl/workbook.xml',            data: _enc.encode(WB) },
      { name: 'xl/_rels/workbook.xml.rels', data: _enc.encode(WB_RELS) },
      { name: 'xl/styles.xml',              data: _enc.encode(STYLES) },
      ...wsFiles,
    ]);
  }

  function _downloadXlsx(bytes, filename) {
    const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), { href: url, download: filename });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function _buildListSheet(listData) {
    const headers = ['ID giao dịch', 'Ngày thanh toán', 'Số tiền', 'Phương thức TT', 'Số tham chiếu thẻ', 'Trạng thái', 'ID hóa đơn VAT'];
    const rows = listData.map(t => [t.txId, t.date, t.amount, t.paymentMethod, t.reference, t.status, t.vatId]);
    return { name: 'Danh sách', headers, rows };
  }

  function _buildDetailSheet(detailData) {
    const headers = [
      'ID giao dịch', 'Ngày thanh toán', 'Giờ thanh toán', 'Số tham chiếu',
      'Tổng tiền giao dịch', 'Số tiền phân bổ', 'Tài khoản quảng cáo', '4 số cuối thẻ',
      'Tên chiến dịch', 'Tên nhóm quảng cáo', 'ID nhóm quảng cáo', 'Kết quả',
      'Thời gian tính phí', 'Phương thức thanh toán', 'Trạng thái', 'Thuế',
      'Lý do lập hóa đơn', 'Loại kết quả', 'Ghi chú',
    ];
    const rows = [];
    for (const d of detailData) {
      if (d.error) {
        const r = new Array(19).fill(''); r[0] = d.listTxId; r[18] = 'LỖI: ' + d.error;
        rows.push(r); continue;
      }
      const base = [d.txId||d.listTxId, d.paymentDate||'', d.paymentTime||'', d.reference||'', d.totalAmount||d.amount||''];
      const tail = [d.paymentMethod||'', d.status||'', d.tax||'', d.reason||''];
      const mk = (amt, camp, grp, gid, period, res, rt, note) =>
        [...base, amt, d.accountId||'', d.cardLast4||'', camp, grp, gid, res, period, ...tail, rt, note];
      if (!d.campaigns?.length) { rows.push(mk('','','','','','','',d.note||'')); continue; }
      for (const c of d.campaigns) {
        if (!c.adGroups.length) { rows.push(mk('',c.campaignName,'','',c.timePeriod,'','',d.note||'')); continue; }
        for (const ag of c.adGroups) rows.push(mk(ag.amount,c.campaignName,ag.name,ag.id,c.timePeriod,ag.result,ag.resultType,ag.note||d.note||''));
      }
    }
    return { name: 'Chi tiết', headers, rows };
  }

  function exportExcel(listData, detailData) {
    const date = new Date().toISOString().slice(0, 10);
    if (listData?.length)   _downloadXlsx(buildXlsx([_buildListSheet(listData)]),     `fb_billing_list_${date}.xlsx`);
    if (detailData?.length) setTimeout(() => _downloadXlsx(buildXlsx([_buildDetailSheet(detailData)]), `fb_billing_detail_${date}.xlsx`), 600);
  }

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
      const res = await sendToContent(tab.id, { type: 'EXPORT_CSV' });
      if (!res?.ok) showError(res?.reason ?? 'Không có dữ liệu để xuất.');
      else exportExcel(res.list, res.detail);
    } catch (err) {
      showError('Lỗi khi xuất Excel.');
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
