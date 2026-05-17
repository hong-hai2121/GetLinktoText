'use strict';

const SPREADSHEET_ID = '1cJvuMXBuPz4-b92gzIOEytiLpMD0wMqDC2IXlAi4mWQ';
const SHEET_GID = 0;

const HEADERS = [
  'Ngày GD', 'Tên', 'Số TK', 'Ngân hàng', 'Số tham chiếu',
  'Số tiền', 'Số dư cuối', 'Mã FACEBK', 'App Code', 'Nội dung đầy đủ',
];

async function apiGet(url, token) {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message ?? `HTTP ${res.status}`);
  }
  return res.json();
}

async function getSheetName(token) {
  const data = await apiGet(
    `https://sheets.googleapis.com/v4/spreadsheets/${SPREADSHEET_ID}?fields=sheets.properties`,
    token
  );
  const sheet = data.sheets?.find(s => s.properties.sheetId === SHEET_GID);
  return sheet?.properties.title ?? 'Sheet1';
}

async function isSheetEmpty(token, sheetName) {
  const data = await apiGet(
    `https://sheets.googleapis.com/v4/spreadsheets/${SPREADSHEET_ID}/values/${encodeURIComponent(sheetName)}!A1`,
    token
  );
  return !data.values?.length;
}

async function appendRows(token, sheetName, rows) {
  const range = encodeURIComponent(sheetName);
  const res = await fetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${SPREADSHEET_ID}/values/${range}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ values: rows }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message ?? `HTTP ${res.status}`);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== 'WRITE_TO_SHEET') return;

  chrome.identity.getAuthToken({ interactive: true }, async (token) => {
    if (chrome.runtime.lastError || !token) {
      sendResponse({ ok: false, reason: chrome.runtime.lastError?.message ?? 'Không lấy được token Google' });
      return;
    }

    try {
      const sheetName = await getSheetName(token);
      const empty = await isSheetEmpty(token, sheetName);

      const dataRows = msg.transactions.map(t => [
        t.customerDate, t.name, t.accountNumber, t.bankName, t.reference,
        t.amount, t.closingBalance, t.refFromDesc, t.cardNumber, t.description,
      ]);

      // Write headers only if sheet is empty
      const toWrite = empty ? [HEADERS, ...dataRows] : dataRows;
      await appendRows(token, sheetName, toWrite);

      sendResponse({ ok: true, count: dataRows.length });
    } catch (err) {
      sendResponse({ ok: false, reason: err.message });
    }
  });

  return true; // keep message channel open for async response
});
