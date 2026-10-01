"""
fb_billing_import_web.py — Nhập file FB Billing Scraper + báo cáo Ads Manager → Google Sheet.
Giao diện WEB mở trong CHROME (server nội bộ 127.0.0.1), KHÔNG cần Facebook API.

  • Chạy file này → tự mở tab Chrome (không có Chrome thì dùng trình duyệt mặc định)
  • Bước 1: chọn Google Sheet đích (mặc định: sheet dùng gần nhất; có lịch sử + tên gợi nhớ)
  • Bước 2: Import file — tool tự phân loại theo TÊN FILE:
        có "_fb_billing"  → file billing (extension FB Billing Scraper)
                            tab = phần tên trước "_fb_billing" (CHI_TIET → "<tên> Chi tiết"),
                            upsert theo "ID giao dịch", chỉ giữ "Đã thanh toán", lọc tháng đa số
        còn lại           → báo cáo xuất tay từ Ads Manager (Nhóm quảng cáo / Chiến dịch / Quảng cáo)
                            tab = "Camp <Tên TK>", chỉ giữ dòng "Số tiền đã chi tiêu" ≠ 0, ghi đè cả tab
  • Bước 3: Tổng hợp — tab "Tổng Hợp T{m}" (tong_hop.py): dòng 1.1 từ tab billing, 1.3 từ tab Camp
                            (chỉ cộng nhóm QC có tên và "Ngân sách nhóm quảng cáo" ≠ 0 — bỏ dòng tổng của Ads Manager)
                            + dòng phụ Lệch, CP Tổng, Đơn (Lượt mua), Doanh Số (Giá trị chuyển đổi lượt mua), Tỷ lệ CP
                            + dòng "ID tài khoản" (thay nhãn "1. NGÂN SÁCH - TẠM ỨNG", tra tab "Danh Sách" theo tên TK)
  • Đóng tab trình duyệt (hoặc bấm "Thoát") → server tự tắt sau vài giây
  • Logic đọc/lọc/upsert: billing_core.py · giao diện: ui/index.html

Chạy:  python fb_billing_import_web.py   (hoặc nhấp đúp run.bat)
"""

import atexit
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from gspread.exceptions import APIError, SpreadsheetNotFound

from billing_core import (
    SA_FILE, ID_COL,
    get_client, sa_email, default_sheet_id_from_config, extract_sheet_id,
    is_quota_error, load_settings, save_settings, default_sheet_title,
    tab_name_from_stem, read_file, filter_by_status, filter_by_month,
    _month_label, analyze_structure, upsert_with_retry,
    parse_report_stem, match_account_tab, read_ads_report, filter_spend_rows, sheet_cells,
    report_tab_name,
)
import tong_hop

BASE_DIR = Path(__file__).parent
UI_FILE  = BASE_DIR / "ui" / "index.html"

# File upload từ trình duyệt được lưu tạm ở %TEMP%, xóa khi thoát (không để lại trong dự án)
TMP_DIR = Path(tempfile.mkdtemp(prefix="fb_ads_noApi_"))
atexit.register(shutil.rmtree, TMP_DIR, ignore_errors=True)

_FS_BAD = re.compile(r'[<>:"/\\|?*]')
BILLING_MARK = "_fb_billing"          # có trong tên file → file billing; không có → báo cáo Ads Manager

NO_CLIENT_GRACE   = 8      # giây không còn tab nào mở → tắt server
NO_CLIENT_STARTUP = 120    # giây chờ tab đầu tiên; quá hạn thì tắt (in URL để mở tay)


def find_chrome():
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if p.is_file():
                return p
    return None


def open_in_chrome(url: str) -> str:
    chrome = find_chrome()
    if chrome:
        try:
            subprocess.Popen([str(chrome), url])
            return "Chrome"
        except OSError:
            pass
    webbrowser.open(url)
    return "trình duyệt mặc định"


def is_billing_file(name: str) -> bool:
    return BILLING_MARK in name.casefold()


class Core:
    """Trạng thái + nghiệp vụ. Mọi request HTTP gọi vào đây; có lock vì server đa luồng."""

    _TAB_BAD = re.compile(r"[\[\]\*\?/\\:]")
    HISTORY_MAX = 20

    def __init__(self):
        self._gc = None
        self._ss = None
        self._ws: dict = {}            # title → worksheet
        self._hdr_cache: dict = {}
        self._items: dict = {}         # id → item (kind = "billing" | "report")
        self._next_id = 1
        self._settings = load_settings()
        self._lock = threading.RLock()
        self._subs: list = []          # hàng đợi SSE của từng tab đang mở
        self.had_client = False
        self.importing = False
        self.quitting = False

    # ── SSE ──────────────────────────────────────────────────────────────────

    def subscribe(self, q):
        with self._lock:
            self._subs.append(q)
            self.had_client = True

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def client_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def request_quit(self):
        self.quitting = True
        with self._lock:
            for q in self._subs:
                q.put(None)            # đánh thức vòng SSE để nó thoát

    def _emit(self, event: str, payload):
        msg = json.dumps({"event": event, "payload": payload}, ensure_ascii=False, default=str)
        with self._lock:
            for q in self._subs:
                q.put(msg)

    # ── Lịch sử sheet đã dùng (settings["sheets"], mới nhất trước) ───────────

    def _history(self) -> list:
        hist = self._settings.get("sheets")
        if not isinstance(hist, list):
            hist = []
            sid = self._settings.get("sheet_id")
            if sid:                                   # nâng cấp từ settings cũ chỉ có sheet_id
                hist = [{"id": sid, "name": "", "title": "",
                         "url": f"https://docs.google.com/spreadsheets/d/{sid}", "last_used": ""}]
            self._settings["sheets"] = hist
        return hist

    def _remember_sheet(self, ss, name: str = ""):
        hist = self._history()
        old = next((h for h in hist if h.get("id") == ss.id), {})
        entry = {"id": ss.id, "name": (name or old.get("name") or ss.title).strip(), "title": ss.title,
                 "url": ss.url, "last_used": datetime.now().isoformat(timespec="seconds")}
        self._settings["sheets"] = [entry] + [h for h in hist if h.get("id") != ss.id][: self.HISTORY_MAX - 1]
        self._settings["sheet_id"] = ss.id
        save_settings(self._settings)

    def save_sheet_name(self, sheet_id: str, name: str):
        with self._lock:
            for h in self._history():
                if h.get("id") == sheet_id:
                    h["name"] = str(name).strip() or h.get("title") or sheet_id
            save_settings(self._settings)
            return self._history()

    def forget_sheet(self, sheet_id: str):
        with self._lock:
            self._settings["sheets"] = [h for h in self._history() if h.get("id") != sheet_id]
            if self._settings.get("sheet_id") == sheet_id:
                self._settings["sheet_id"] = self._settings["sheets"][0]["id"] if self._settings["sheets"] else ""
            save_settings(self._settings)
            return self._history()

    # ── Item (2 loại) ────────────────────────────────────────────────────────

    def _public(self, it: dict) -> dict:
        base = {"id": it["id"], "kind": it["kind"], "file": it["path"].name, "tab": it["tab"],
                "status": it["status"], "error": it["error"]}
        if it["kind"] == "billing":
            base.update({"rows": len(it["rows"]) if it["headers"] else None, "info": it.get("info")})
        else:
            base.update({"rows": it["rows_spend"] if it["headers"] else None, "rows_total": it["rows_total"],
                         "level": it["level"], "period": it["period"], "account": it["account"],
                         "matched": it.get("matched", ""), "spend_col": it["spend_col"],
                         "cols": len(it["headers"])})
        return base

    def _all_public(self) -> list:
        return [self._public(i) for i in self._items.values()]

    def _sheet_public(self):
        return {"title": self._ss.title, "url": self._ss.url, "id": self._ss.id} if self._ss else None

    # billing ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_info(it: dict):
        if not it["headers"]:
            return None
        filtered, skipped = filter_by_status(it["headers"], it["rows"])
        _, dropped, target, _un = filter_by_month(it["headers"], filtered)
        cnt = Counter(_month_label(k) for _, k in dropped)
        a = it.get("analysis") or {}
        return {"import_rows": len(filtered), "skipped": skipped,
                "has_id": ID_COL in it["headers"],
                "month": _month_label(target) if target else "",
                "dropped": [[lb, c] for lb, c in cnt.items()],
                "new_cols": a.get("new_cols", []), "missing": a.get("missing", []),
                "sheet_empty": a.get("sheet_empty", True)}

    def _analyze_billing(self, it: dict):
        """So cột file với tab đích (đọc header tab qua API nếu chưa cache) → đặt status."""
        if not it["headers"]:
            return
        if self._ss is None:
            it["analysis"] = analyze_structure(it["headers"], [])
            it["status"] = "no_sheet"
        else:
            ws = self._ws.get(it["tab"])
            if ws is None:
                it["analysis"] = analyze_structure(it["headers"], [])
                it["status"] = "new_tab"
            else:
                hdr = self._hdr_cache.get(ws.title)
                if hdr is None:
                    hdr = ws.row_values(1)
                    self._hdr_cache[ws.title] = hdr
                a = analyze_structure(it["headers"], hdr)
                it["analysis"] = a
                it["status"] = ("ready" if a["sheet_empty"] or (not a["new_cols"] and not a["missing"])
                                else "mismatch")
        it["info"] = self._build_info(it)

    # report ─────────────────────────────────────────────────────────────────

    def _analyze_report(self, it: dict):
        if not it["headers"] or not it["rows"]:
            return
        if self._ss is None:
            it["status"] = "no_sheet"
            return
        matched = match_account_tab(it["account"], self._ws.keys())
        it["matched"] = matched
        if matched and not it.get("tab_edited"):
            it["tab"] = report_tab_name(matched)      # "Camp " + tên TK đúng chính tả như tab billing
        it["status"] = "replace" if it["tab"] in self._ws else "new_tab"

    def _analyze(self, it: dict):
        try:
            if it["kind"] == "billing":
                self._analyze_billing(it)
            else:
                self._analyze_report(it)
        except Exception as e:
            it["status"], it["error"] = "error", f"Đọc cột sheet lỗi: {e}"

    # ── API: trạng thái ban đầu ──────────────────────────────────────────────

    def get_state(self):
        rm, ry = tong_hop.default_month_year()
        with self._lock:
            return {"sa_email": sa_email(),
                    "default_title": default_sheet_title(),
                    "share_email": self._settings.get("share_email", ""),
                    "default_sheet_id": self._settings.get("sheet_id") or default_sheet_id_from_config(),
                    "sheets": self._history(),
                    "sheet": self._sheet_public(),
                    "items": self._all_public(),
                    "report_month": rm, "report_year": ry,
                    "template_sheet_id": self._settings.get("template_sheet_id")
                                         or tong_hop.TEMPLATE_SHEET_DEFAULT}

    # ── API: kết nối / tạo sheet ─────────────────────────────────────────────

    def connect(self, choice: dict):
        mode = choice.get("mode", "new")
        created, share_err = False, ""
        try:
            if self._gc is None:
                self._gc = get_client()
            if mode == "new":
                ss = self._gc.create(choice["title"])
                created = True
                if choice.get("email"):
                    try:
                        ss.share(choice["email"], perm_type="user", role="writer", notify=True)
                    except Exception as e:          # tạo được nhưng chia sẻ lỗi → vẫn tiếp tục
                        share_err = str(e)
            else:
                sid = extract_sheet_id(choice.get("sheet", ""))
                if not sid:
                    return {"ok": False, "quota": False,
                            "error": "Link/ID không hợp lệ. Dán link dạng …/spreadsheets/d/<ID>/…"}
                ss = self._gc.open_by_key(sid)
            wss = ss.worksheets()
        except Exception as e:
            quota = mode == "new" and is_quota_error(e)
            if isinstance(e, SpreadsheetNotFound):
                msg = ("Không tìm thấy Google Sheet với ID đã nhập. Kiểm tra lại link, "
                       "hoặc sheet chưa được chia sẻ cho service account.")
            elif isinstance(e, APIError) and "403" in str(e) and not quota:
                msg = (f"Không có quyền truy cập sheet. Kiểm tra quyền Editor của {sa_email()} trên Sheet này. "
                       "Nếu chưa có, thêm riêng email này trong Share / Chia sẻ. "
                       "Giữ Quyền truy cập chung = Bị hạn chế (Restricted).")
            else:
                msg = str(e)
            return {"ok": False, "quota": quota, "error": msg}

        with self._lock:
            self._ss = ss
            self._ws = {w.title: w for w in wss}
            self._hdr_cache.clear()
            self._settings["share_email"] = choice.get("email") or self._settings.get("share_email", "")
            self._remember_sheet(ss, choice.get("name", ""))
            for it in self._items.values():          # đổi sheet → so lại với sheet mới
                if it["status"] != "importing" and it["headers"]:
                    it["error"] = ""
                    self._analyze(it)
            return {"ok": True, "created": created, "share_err": share_err,
                    "sheet": self._sheet_public(), "tabs": len(wss), "sheets": self._history(),
                    "items": self._all_public()}

    # ── API: file (tự phân loại theo tên) ────────────────────────────────────

    def add_upload(self, name: str, data: bytes) -> dict:
        """File do trình duyệt gửi lên: lưu tạm với ĐÚNG tên gốc (để suy ra tên tab) rồi nạp."""
        safe = _FS_BAD.sub("_", Path(name).name).strip() or "file.xlsx"
        p = TMP_DIR / safe
        with self._lock:
            dup = next((i for i in self._items.values() if i["path"] == p), None)
            if dup:
                return self._public(dup)
            p.write_bytes(data)
            it = {"id": self._next_id, "path": p, "status": "loading", "error": "", "headers": [], "rows": []}
            self._next_id += 1
            self._items[it["id"]] = it
            try:
                if is_billing_file(p.name):
                    it.update({"kind": "billing", "tab": tab_name_from_stem(p.stem), "analysis": None, "info": None})
                    it["headers"], it["rows"] = read_file(p)
                    self._analyze(it)
                else:
                    info = parse_report_stem(p.stem)
                    it.update({"kind": "report", "tab": report_tab_name(info["account"]),
                               "account": info["account"], "level": info["level"] or "?",
                               "period": info["period"], "matched": "", "rows_total": 0,
                               "rows_spend": 0, "spend_col": ""})
                    headers, rows = read_ads_report(p)
                    kept, skipped, idx = filter_spend_rows(headers, rows)
                    it.update({"headers": headers, "rows": kept, "rows_total": len(rows),
                               "rows_spend": len(kept), "spend_col": headers[idx] if idx is not None else ""})
                    if idx is None:
                        it["status"], it["error"] = "error", ("Không thấy cột 'Số tiền đã chi tiêu' — "
                                                              "không phải file báo cáo Ads Manager?")
                    elif not kept:
                        it["status"], it["error"] = "error", "Không có dòng nào có chi tiêu khác 0."
                    else:
                        self._analyze(it)
            except Exception as e:
                it.setdefault("kind", "billing")
                it.setdefault("tab", p.stem)
                it["status"], it["error"] = "error", str(e)
            return self._public(it)

    def set_tab(self, item_id: int, tab: str):
        with self._lock:
            it = self._items.get(int(item_id))
            if it is None:
                return None
            tab = self._TAB_BAD.sub("_", str(tab).strip())[:100]
            if tab and it["status"] != "importing":
                it["tab"], it["tab_edited"] = tab, True
                if it["headers"]:
                    it["error"] = ""
                    self._analyze(it)
            return self._public(it)

    def remove_items(self, ids: list):
        with self._lock:
            for i in ids:
                it = self._items.get(int(i))
                if it and it["status"] != "importing":
                    del self._items[int(i)]
                    try:
                        if it["path"].parent == TMP_DIR:
                            it["path"].unlink()
                    except OSError:
                        pass
        return True

    # ── API: import (cả 2 loại trong một lượt) ───────────────────────────────

    def import_items(self, ids: list, replace: bool, month_filter: bool):
        with self._lock:
            items = [self._items[int(i)] for i in ids if int(i) in self._items and self._items[int(i)]["headers"]]
            if self._ss is None or not items or self.importing:
                return {"started": 0}
            self.importing = True
        threading.Thread(target=self._import_worker,
                         args=(items, bool(replace), bool(month_filter)), daemon=True).start()
        return {"started": len(items)}

    def _import_billing(self, it: dict, replace: bool, month_filter: bool, st: dict):
        ws = self._ws.get(it["tab"])
        if ws is None:
            ws = self._ss.add_worksheet(title=it["tab"], rows=max(len(it["rows"]) + 1, 100),
                                        cols=max(len(it["headers"]), 1))
            self._ws[it["tab"]] = ws
        filtered, _ = filter_by_status(it["headers"], it["rows"])
        if month_filter:
            filtered, dropped, target, _un = filter_by_month(it["headers"], filtered)
            if dropped:
                cnt = Counter(_month_label(k) for _, k in dropped)
                st["dropped_report"].append([it["path"].name, _month_label(target),
                                             [[lb, c] for lb, c in cnt.items()]])
                st["dropped"] += len(dropped)
        s = upsert_with_retry(ws, it["headers"], filtered, replace)
        self._hdr_cache.pop(ws.title, None)
        st["added"] += s["added"]
        st["updated"] += s["updated"]

    def _import_report(self, it: dict, st: dict):
        values = [it["headers"]] + sheet_cells(it["rows"])
        n_rows, n_cols = len(values), len(it["headers"])
        ws = self._ws.get(it["tab"])
        if ws is None:
            ws = self._ss.add_worksheet(title=it["tab"], rows=max(n_rows + 20, 100), cols=max(n_cols, 1))
            self._ws[it["tab"]] = ws
        else:
            ws.clear()                                   # ghi đè toàn bộ tab
            if ws.row_count < n_rows or ws.col_count < n_cols:
                ws.resize(rows=max(ws.row_count, n_rows + 20), cols=max(ws.col_count, n_cols))
        ws.update(range_name="A1", values=values, value_input_option="RAW")
        ws.freeze(rows=1)
        self._hdr_cache.pop(ws.title, None)
        st["report_rows"] += len(it["rows"])

    def _import_worker(self, items: list, replace: bool, month_filter: bool):
        st = {"total": len(items), "billing": sum(1 for i in items if i["kind"] == "billing"),
              "reports": sum(1 for i in items if i["kind"] == "report"),
              "added": 0, "updated": 0, "errors": 0, "dropped": 0, "dropped_report": [], "report_rows": 0}
        try:
            for it in items:
                it["status"] = "importing"
                self._emit("item", self._public(it))
                try:
                    if it["kind"] == "billing":
                        self._import_billing(it, replace, month_filter, st)
                    else:
                        self._import_report(it, st)
                    it["status"], it["error"] = "done", ""
                except Exception as e:
                    it["status"], it["error"] = "error", str(e)
                    st["errors"] += 1
                self._emit("item", self._public(it))
        finally:
            self.importing = False
        st["tabs"] = len(self._ws)
        self._emit("done", st)

    # ── API: bảng tổng hợp (bước 3) ──────────────────────────────────────────

    def tong_hop(self, month: int, year: int, all_months: bool = False):
        """Tạo/cập nhật tab 'Tổng Hợp T{month}' trong sheet đang kết nối (dòng 1.1 + 1.3)."""
        if self._ss is None:
            return {"ok": False, "error": "Chưa kết nối Google Sheet."}
        try:
            with self._lock:
                r = tong_hop.build_summary(
                    self._ss, int(month), int(year), all_months=bool(all_months),
                    template_sheet_id=self._settings.get("template_sheet_id", ""), gc=self._gc)
                self._ws = {w.title: w for w in self._ss.worksheets()}   # có tab mới
            return r
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ── HTTP server ────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    core: Core = None
    ALLOWED = {"get_state", "connect", "set_tab", "remove_items", "import_items", "tong_hop",
               "save_sheet_name", "forget_sheet"}

    def log_message(self, fmt, *args):       # im lặng, không spam console
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(UI_FILE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/events":
            self._sse()
        else:
            self._json({"error": "not found"}, 404)

    def _sse(self):
        q: queue.Queue = queue.Queue()
        self.core.subscribe(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while not self.core.quitting:
                try:
                    msg = q.get(timeout=3)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")       # giữ kết nối + phát hiện tab đã đóng
                    self.wfile.flush()
                    continue
                if msg is None:
                    break
                self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self.core.unsubscribe(q)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path = parsed.path
        try:
            if path == "/api/upload":
                name = unquote(parse_qs(parsed.query).get("name", ["file.xlsx"])[0])
                self._json(self.core.add_upload(name, body))
            elif path == "/api/quit":
                self._json({"ok": True})
                self.core.request_quit()
            elif path.startswith("/api/"):
                name = path[5:]
                if name not in self.ALLOWED:
                    self._json({"error": f"unknown api {name}"}, 404)
                    return
                args = json.loads(body.decode("utf-8") or "{}").get("args", [])
                self._json(getattr(self.core, name)(*args))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)


def serve(core: Core, port: int = 0):
    """Khởi động server ở thread nền, trả (server, url)."""
    Handler.core = core
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def main():
    if not SA_FILE.exists():
        sys.exit(f"Thiếu {SA_FILE} — cần file service account để ghi Google Sheet.")
    if not UI_FILE.exists():
        sys.exit(f"Thiếu {UI_FILE}")

    core = Core()
    server, url = serve(core)
    print(f"FB Billing Import đang chạy tại  {url}")
    print(f"Mở bằng: {open_in_chrome(url)}")
    print("Đóng tab trình duyệt hoặc bấm 'Thoát' trên trang để tắt. (Ctrl+C cũng được)")

    started = time.time()
    no_client_since = None
    try:
        while not core.quitting:
            time.sleep(1)
            if core.client_count() > 0:
                no_client_since = None
                continue
            if not core.had_client:
                if time.time() - started > NO_CLIENT_STARTUP:
                    print(f"Không thấy trình duyệt kết nối sau {NO_CLIENT_STARTUP}s → tắt. "
                          f"Nếu cần, chạy lại và mở tay: {url}")
                    break
                continue
            no_client_since = no_client_since or time.time()
            if time.time() - no_client_since > NO_CLIENT_GRACE and not core.importing:
                print("Không còn tab nào mở → tắt server.")
                break
    except KeyboardInterrupt:
        pass
    core.request_quit()
    server.shutdown()


if __name__ == "__main__":
    main()
