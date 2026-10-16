# -*- coding: utf-8 -*-
"""Relay CDP <-> "Playwright Extension" — port Python của cdpRelay.ts / cdpRelayV2.ts /
browserModel.ts trong microsoft/playwright (packages/playwright-core/src/tools/mcp), giao thức v2.

Vấn đề: Chrome đang mở bình thường KHÔNG có cổng DevTools, và Chrome >= 136 không cho bật
cổng đó trên User Data mặc định. Giải pháp của Microsoft: extension "Playwright Extension"
(Chrome Web Store, id mmlmfj...) chạy BÊN TRONG Chrome, dùng API chrome.debugger để điều khiển
tab, rồi nối ra ngoài bằng WebSocket tới một relay. Relay giả một endpoint CDP để Playwright
`connect_over_cdp` vào y như Chrome thật.

    Playwright --CDP--> ws://127.0.0.1:PORT/cdp/<uuid>  [relay]  ws://127.0.0.1:PORT/extension/<uuid> <-- extension

Giao thức extension (v2): RPC mỏng, lệnh là tên hàm chrome.* với params dạng MẢNG VỊ TRÍ để
extension spread thẳng vào chrome.<api>.<method>(...):
    relay -> ext : {"id": n, "method": "chrome.debugger.sendCommand",
                    "params": [{"tabId": 1}, "Page.enable", {}]}
    ext -> relay : {"id": n, "result": ...}  |  {"id": n, "error": "..."}
    ext -> relay : {"method": "chrome.debugger.onEvent", "params": [source, cdpMethod, cdpParams]}
Lệnh được phép: chrome.debugger.attach/detach/sendCommand, chrome.tabs.create/remove.
Sự kiện: chrome.debugger.onEvent/onDetach, chrome.tabs.onCreated/onRemoved, extension.initialized.
Bắt tay: extension đẩy chrome.tabs.onCreated cho từng tab ban đầu rồi "extension.initialized";
relay chỉ nhận lệnh CDP của Playwright sau mốc đó để Target.setAutoAttach có đủ danh sách tab.

Cần: websockets >= 13 (dùng websockets.asyncio). Toàn bộ asyncio chạy trong một thread nền,
API công khai của ExtensionRelay là đồng bộ để gọi từ Tkinter / Playwright sync.
"""
import asyncio
import json
import os
import subprocess
import threading
import time
import uuid
from urllib.parse import urlencode

EXTENSION_ID = "mmlmfjhmonkocbjadbfplnigmagldckm"
EXTENSION_STORE_URL = f"https://chromewebstore.google.com/detail/playwright-extension/{EXTENSION_ID}"
PROTOCOL_VERSION = 2


class RelayError(RuntimeError):
    pass


class _TabSession:
    __slots__ = ("tab_id", "session_id", "target_info", "child_sessions")

    def __init__(self, tab_id, session_id, target_info):
        self.tab_id = tab_id
        self.session_id = session_id
        self.target_info = target_info or {}
        # sessionId con (worker, oopif...) thuộc tab này — theo Target.attachedToTarget/detachedFromTarget
        self.child_sessions = set()


class _BrowserModel:
    """Port browserModel.ts — nơi DUY NHẤT dịch giữa "tiếng chrome.*" của extension và CDP của Playwright.

    Giữ ánh xạ tabId của Chrome <-> sessionId CDP (pw-tab-N) mà Playwright nhìn thấy.
    """

    def __init__(self, send_to_extension, log):
        self._send = send_to_extension  # async (method, params_list) -> result
        self._log = log
        self._emit_cb = None            # chỉ có khi Playwright đã nối
        self._known_tabs = {}           # tab_id -> tab (từ chrome.tabs.onCreated)
        self._sessions = {}             # tab_id -> _TabSession (đã attach debugger)
        self._attaching = {}            # tab_id -> Task (chống attach đôi)
        self._auto_attach = False
        self._next_id = 1

    def connect_over_cdp(self, emit):
        self._emit_cb = emit

    def _emit(self, msg):
        if self._emit_cb:
            self._emit_cb(msg)

    # ----- extension -> model -----
    def on_tab_created(self, tab):
        tab_id = tab.get("id") if isinstance(tab, dict) else None
        if tab_id is None:
            return
        self._known_tabs[tab_id] = tab
        if self._auto_attach:
            self._attach_in_background(tab_id)

    def on_tab_removed(self, tab_id):
        self._known_tabs.pop(tab_id, None)
        self._detach(tab_id)

    def on_debugger_event(self, source, method, params):
        tab_id = source.get("tabId")
        if tab_id is None:
            return
        s = self._sessions.get(tab_id)
        if s is None:
            return
        child = params.get("sessionId") if isinstance(params, dict) else None
        if method == "Target.attachedToTarget" and child:
            s.child_sessions.add(child)
        elif method == "Target.detachedFromTarget" and child:
            s.child_sessions.discard(child)
        # Sự kiện cấp tab dùng sessionId của relay; session con giữ sessionId riêng của nó.
        self._emit({"sessionId": source.get("sessionId") or s.session_id,
                    "method": method, "params": params})

    def on_debugger_detach(self, source):
        tab_id = source.get("tabId")
        if tab_id is not None:
            self._detach(tab_id)

    # ----- Playwright -> model -----
    async def enable_auto_attach(self):
        """Target.setAutoAttach ở session gốc: attach mọi tab đã biết, phát attachedToTarget cho từng tab."""
        self._auto_attach = True
        results = await asyncio.gather(*(self._attach(t) for t in list(self._known_tabs)),
                                       return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                self._log(f"[relay] attach tab lỗi: {r}")

    async def create_target(self, url):
        tab = await self._send("chrome.tabs.create", [{"url": url}])
        if not isinstance(tab, dict) or tab.get("id") is None:
            raise RelayError("Failed to create tab")
        self._known_tabs[tab["id"]] = tab
        s = await self._attach(tab["id"])
        return {"targetId": s.target_info.get("targetId")}

    async def close_target(self, target_id):
        s = self._find(lambda x: x.target_info.get("targetId") == target_id) if target_id else None
        if s is None:
            return {"success": False}
        await self._send("chrome.tabs.remove", [s.tab_id])
        return {"success": True}

    def get_target_info(self, session_id):
        if not session_id:
            return None
        s = self._find(lambda x: x.session_id == session_id)
        return s.target_info if s else None

    def first_session_id(self):
        for s in self._sessions.values():
            return s.session_id
        return None

    async def send_browser_command(self, method, params, wait_sec=5.0):
        """Lệnh cấp trình duyệt (Storage.*, Browser.*) không có sessionId: chrome.debugger cần một
        target nên mượn tab bất kỳ đang attach. Khác bản gốc: chờ tối đa wait_sec cho tab đầu
        attach xong thay vì ném lỗi ngay (Playwright có thể gửi lệnh này rất sớm lúc kết nối)."""
        deadline = time.monotonic() + wait_sec
        while not self._sessions and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if not self._sessions:
            raise RelayError(f"No attached tab to forward browser-level command: {method}")
        s = next(iter(self._sessions.values()))
        return await self._send("chrome.debugger.sendCommand",
                                self._cmd_params({"tabId": s.tab_id}, method, params))

    async def send_command(self, session_id, method, params):
        # 1) sessionId là tab của relay (pw-tab-N) -> bỏ sessionId, định tuyến theo tabId
        # 2) sessionId là session con (worker/oopif) -> tới tab chủ, GIỮ sessionId cho chrome.debugger
        s = self._find(lambda x: x.session_id == session_id)
        cdp_sid = None
        if s is None:
            s = self._find(lambda x: session_id in x.child_sessions)
            cdp_sid = session_id
        if s is None:
            raise RelayError(f"No tab found for sessionId: {session_id}")
        target = {"tabId": s.tab_id}
        if cdp_sid:
            target["sessionId"] = cdp_sid
        return await self._send("chrome.debugger.sendCommand", self._cmd_params(target, method, params))

    # ----- nội bộ -----
    @staticmethod
    def _cmd_params(target, method, params):
        # chrome.debugger.sendCommand(target, method, commandParams?) — bỏ hẳn tham số 3 nếu không có
        return [target, method, params] if params is not None else [target, method]

    def _attach_in_background(self, tab_id):
        task = asyncio.ensure_future(self._attach(tab_id))
        task.add_done_callback(self._report_task_error)

    def _report_task_error(self, task):
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            self._log(f"[relay] lỗi nền: {exc}")

    async def _attach(self, tab_id):
        s = self._sessions.get(tab_id)
        if s is not None:
            return s
        task = self._attaching.get(tab_id)
        if task is None:
            task = asyncio.ensure_future(self._do_attach(tab_id))
            self._attaching[tab_id] = task
            task.add_done_callback(lambda _t: self._attaching.pop(tab_id, None))
        return await task

    async def _do_attach(self, tab_id):
        await self._send("chrome.debugger.attach", [{"tabId": tab_id}, "1.3"])
        res = await self._send("chrome.debugger.sendCommand", [{"tabId": tab_id}, "Target.getTargetInfo"])
        info = (res or {}).get("targetInfo") or {}
        session_id = f"pw-tab-{self._next_id}"
        self._next_id += 1
        s = _TabSession(tab_id, session_id, info)
        self._sessions[tab_id] = s
        self._emit({"method": "Target.attachedToTarget",
                    "params": {"sessionId": session_id,
                               "targetInfo": {**info, "attached": True},
                               "waitingForDebugger": False}})
        return s

    def _detach(self, tab_id):
        s = self._sessions.pop(tab_id, None)
        if s is None:
            return
        self._emit({"method": "Target.detachedFromTarget",
                    "params": {"sessionId": s.session_id,
                               "targetId": s.target_info.get("targetId")}})

    def _find(self, pred):
        for s in self._sessions.values():
            if pred(s):
                return s
        return None


class _ExtensionConnection:
    """Một kết nối WebSocket từ extension: gửi lệnh có id, nhận trả lời / sự kiện."""

    def __init__(self, ws, on_event, log):
        self._ws = ws
        self._on_event = on_event
        self._log = log
        self._pending = {}  # id -> Future
        self._last_id = 0
        self.closed = False

    async def send(self, method, params):
        if self.closed:
            raise RelayError(f"Extension connection closed ({method})")
        self._last_id += 1
        mid = self._last_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        return await fut

    async def close(self, reason):
        if not self.closed:
            try:
                await self._ws.close(1000, reason[:120])
            except Exception:
                pass

    def handle_raw(self, raw):
        try:
            obj = json.loads(raw)
        except Exception as e:
            self._log(f"[relay] JSON hỏng từ extension ({e}) — đóng kết nối.")
            asyncio.ensure_future(self.close("malformed JSON"))
            return
        mid = obj.get("id")
        if mid and mid in self._pending:
            fut = self._pending.pop(mid)
            if not fut.done():
                if obj.get("error"):
                    fut.set_exception(RelayError(str(obj["error"])))
                else:
                    fut.set_result(obj.get("result"))
        elif mid:
            self._log(f"[relay] trả lời lạ từ extension: {obj}")
        else:
            self._on_event(obj.get("method"), obj.get("params") or [])

    def dispose(self):
        self.closed = True
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RelayError("WebSocket closed"))
        self._pending.clear()


class ExtensionRelay:
    """Server WebSocket cục bộ: /extension/<uuid> cho extension, /cdp/<uuid> cho Playwright.

    Dùng:
        relay = ExtensionRelay(log); relay.start()
        relay.open_connect_page(chrome_exe, "Profile 9", "Tên app", token)
        relay.wait_for_extension(60)
        browser = pw.chromium.connect_over_cdp(relay.cdp_endpoint)
        ...
        relay.stop()
    """

    def __init__(self, log=print):
        self._log = log
        self._uuid = str(uuid.uuid4())
        self._cdp_path = f"/cdp/{self._uuid}"
        self._ext_path = f"/extension/{self._uuid}"
        self._loop = None
        self._thread = None
        self._stop_event = None
        self._port = None
        self._start_error = None
        self._started = threading.Event()
        self._ext_connected = threading.Event()
        self._ready = threading.Event()      # extension.initialized đã tới
        self._fail_reason = None
        self._ext = None
        self._cdp_ws = None
        self._model = _BrowserModel(self._send_to_extension, log)

    # ----- vòng đời (gọi từ thread bất kỳ) -----
    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="pw-extension-relay", daemon=True)
        self._thread.start()
        if not self._started.wait(10) or self._start_error is not None:
            raise RelayError(f"Không khởi động được relay: {self._start_error or 'hết giờ'}")

    def stop(self):
        loop, thread = self._loop, self._thread
        if loop is None or thread is None:
            return

        def _do():
            self._close_connections("Server stopped")
            if self._stop_event is not None:
                self._stop_event.set()
        try:
            loop.call_soon_threadsafe(_do)
        except RuntimeError:
            return
        thread.join(5)

    @property
    def port(self):
        return self._port

    @property
    def cdp_endpoint(self):
        return f"ws://127.0.0.1:{self._port}{self._cdp_path}"

    @property
    def extension_endpoint(self):
        return f"ws://127.0.0.1:{self._port}{self._ext_path}"

    @property
    def connected(self):
        return self._ready.is_set() and self._ext is not None

    def connect_url(self, client_name, token=None):
        """URL trang connect của extension; trang này đọc mcpRelayUrl (bắt buộc loopback),
        client, protocolVersion, token. Token đúng -> chính tab connect thành tab điều khiển, không cần bấm."""
        q = {
            "mcpRelayUrl": self.extension_endpoint,
            "client": json.dumps({"name": client_name}, ensure_ascii=False),
            "protocolVersion": str(PROTOCOL_VERSION),
        }
        if token:
            q["token"] = token
        return f"chrome-extension://{EXTENSION_ID}/connect.html?{urlencode(q)}"

    def open_connect_page(self, chrome_path, profile_dir, client_name, token=None, user_data_dir=None):
        """Mở trang connect trong đúng profile. Chrome đang chạy thì chỉ thêm 1 tab (Chrome tự
        chuyển URL sang tiến trình đang có); chưa chạy thì khởi động. Không đóng gì cả."""
        args = [chrome_path]
        if user_data_dir:  # KHÔNG truyền với User Data mặc định — Chrome tự giải quyết
            args.append(f"--user-data-dir={user_data_dir}")
        if profile_dir:
            args.append(f"--profile-directory={profile_dir}")
        args.append(self.connect_url(client_name, token))
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)

    def wait_for_extension(self, timeout=None):
        """Chờ extension nối vào và bắt tay xong. timeout=None: chờ vô hạn (người dùng phải bấm Cho phép)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.connected:
                return
            if self._fail_reason:
                raise RelayError(self._fail_reason)
            if deadline is not None and time.monotonic() > deadline:
                raise RelayError(
                    f"Extension không nối vào relay trong {int(timeout)}s sau khi mở trang connect. "
                    "Kiểm tra: extension đã cài trong đúng profile chưa, token có khớp với token "
                    "trong trang trạng thái của extension không.")
            time.sleep(0.1)

    def send_cdp(self, method, params=None, session_id=None, timeout=30.0):
        """Gửi một lệnh CDP thẳng tới tab đang điều khiển, NGOÀI Playwright (gọi từ thread bất kỳ).

        Dùng cho DOM.setFileInputFiles: Playwright coi trình duyệt nối qua connect_over_cdp là
        "không cùng máy" nên từ chối chuyển file > 50 MB; gửi thẳng đường dẫn file qua CDP thì
        không giới hạn (cần extension được phép truy cập URL tệp). Mặc định nhắm tab attach đầu
        tiên — chính là pages[0] mà connect_playwright() trả về."""
        loop = self._loop
        if loop is None or not self.connected:
            raise RelayError("Relay chưa nối với extension")

        async def _run():
            sid = session_id or self._model.first_session_id()
            if not sid:
                raise RelayError("Chưa có tab nào được attach")
            return await self._model.send_command(sid, method, params)

        return asyncio.run_coroutine_threadsafe(_run(), loop).result(timeout)

    # ----- asyncio (chạy trong thread nền) -----
    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception as e:  # lỗi khởi động (vd. import websockets)
            self._start_error = e
            self._started.set()

    async def _serve(self):
        from websockets.asyncio.server import serve
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        # max_size: websockets mặc định chặn khung > 1 MB -> HTML YouTube Studio (~900 KB sau khi
        # bọc JSON) hay screenshot lớn làm extension bị ngắt "message too big". Nới lên 256 MB
        # (chỉ loopback, không lo bị tấn công); max_queue giữ mặc định.
        async with serve(self._handler, "127.0.0.1", 0, max_size=256 * 1024 * 1024) as server:
            sockets = getattr(server, "sockets", None) or server.server.sockets
            self._port = sockets[0].getsockname()[1]
            self._started.set()
            await self._stop_event.wait()

    def _close_connections(self, reason):
        if self._cdp_ws is not None:
            asyncio.ensure_future(self._cdp_ws.close(1000, reason))
        if self._ext is not None:
            asyncio.ensure_future(self._ext.close(reason))

    async def _handler(self, ws):
        path = ws.request.path
        if path == self._cdp_path:
            await self._handle_playwright(ws)
        elif path == self._ext_path:
            await self._handle_extension(ws)
        else:
            await ws.close(1008, "Unknown path")

    # --- phía extension ---
    async def _handle_extension(self, ws):
        if self._ext is not None:
            await ws.close(1000, "Another extension connection already established")
            return
        self._log("[relay] Extension đã nối vào relay, chờ bắt tay...")
        conn = _ExtensionConnection(ws, self._on_extension_event, self._log)
        self._ext = conn
        self._ext_connected.set()
        reason = ""
        try:
            async for raw in ws:
                conn.handle_raw(raw)
        except Exception as e:
            reason = str(e)
        finally:
            reason = reason or (ws.close_reason or "")
            conn.dispose()
            self._ext = None
            if not self._ready.is_set():
                self._fail_reason = f"Extension disconnected before initialization: {reason}"
            self._log(f"[relay] Extension ngắt kết nối: {reason or '(không rõ)'}")
            if self._cdp_ws is not None:
                asyncio.ensure_future(self._cdp_ws.close(1000, f"Extension disconnected: {reason}"[:120]))

    def _on_extension_event(self, method, params):
        p = list(params) if isinstance(params, list) else []
        if method == "chrome.debugger.onEvent":
            while len(p) < 3:
                p.append(None)
            self._model.on_debugger_event(p[0] or {}, p[1], p[2])
        elif method == "chrome.debugger.onDetach":
            self._model.on_debugger_detach(p[0] if p else {})
        elif method == "chrome.tabs.onCreated":
            self._model.on_tab_created(p[0] if p else {})
        elif method == "chrome.tabs.onRemoved":
            if p:
                self._model.on_tab_removed(p[0])
        elif method == "extension.initialized":
            self._log("[relay] Extension bắt tay xong.")
            self._ready.set()
        else:
            self._log(f"[relay] sự kiện lạ từ extension: {method} {params}")

    async def _send_to_extension(self, method, params):
        if self._ext is None:
            raise RelayError("Extension not connected")
        return await self._ext.send(method, params)

    # --- phía Playwright ---
    async def _handle_playwright(self, ws):
        if self._ext is None:
            await ws.close(1000, "Extension not connected")
            return
        if self._cdp_ws is not None:
            await ws.close(1000, "Another CDP client already connected")
            return
        self._cdp_ws = ws
        self._model.connect_over_cdp(self._send_to_cdp_client)
        self._log("[relay] Playwright đã nối vào relay.")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                # Xử lý song song như bản gốc: mỗi lệnh một task, trả lời theo id
                asyncio.ensure_future(self._handle_playwright_message(msg))
        except Exception:
            pass
        finally:
            self._cdp_ws = None
            if self._ext is not None:
                # Giống bản gốc: Playwright rời đi thì ngắt luôn extension (extension gỡ debugger, tab vẫn mở)
                asyncio.ensure_future(self._ext.close("Playwright client disconnected"))

    async def _handle_playwright_message(self, msg):
        mid, sid = msg.get("id"), msg.get("sessionId")
        method, params = msg.get("method"), msg.get("params")
        try:
            result = await self._handle_cdp_command(method, params, sid)
            out = {"id": mid, "result": {} if result is None else result}
        except Exception as e:
            out = {"id": mid, "error": {"message": str(e)}}
        if sid is not None:
            out["sessionId"] = sid
        self._send_to_cdp_client(out)

    async def _handle_cdp_command(self, method, params, sid):
        if method == "Browser.getVersion":
            return {"protocolVersion": "1.3", "product": "Chrome/Extension-Bridge",
                    "userAgent": "CDP-Bridge-Server/1.0.0"}
        if method == "Browser.setDownloadBehavior":
            return {}
        if method == "Target.setAutoAttach" and not sid:
            await self._model.enable_auto_attach()
            return {}
        if method == "Target.createTarget":
            return await self._model.create_target((params or {}).get("url"))
        if method == "Target.closeTarget":
            return await self._model.close_target((params or {}).get("targetId"))
        if method == "Target.getTargetInfo":
            return {"targetInfo": self._model.get_target_info(sid) or {}}
        if not sid:
            return await self._model.send_browser_command(method, params)
        return await self._model.send_command(sid, method, params)

    def _send_to_cdp_client(self, msg):
        ws = self._cdp_ws
        if ws is None:
            return

        async def gui():
            # Kết nối Playwright có thể vừa đóng (vd. đóng tab điều khiển -> extension ngắt) ->
            # nuốt lỗi để asyncio không in "Task exception was never retrieved" ra nhật ký.
            try:
                await ws.send(json.dumps(msg))
            except Exception:
                pass
        asyncio.ensure_future(gui())
