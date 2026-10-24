# -*- coding: utf-8 -*-
"""Google Drive + Sheets bằng TÀI KHOẢN GOOGLE của user (OAuth, đăng nhập một lần qua trình duyệt, token lưu ngoài dự án),
chạy độc lập không cần Claude:
  - đọc Sheet lịch đăng (cột D tiêu đề, F link thư mục nguyên liệu, G link video) -> các dòng cần ghép;
  - tải video đã ghép lên thư mục Drive đích (tải từng khúc 8 MB, file lớn vẫn ổn), bật "ai có link đều xem được";
  - ghi link video vào cột G đúng dòng.
client_secret.json: OAuth client loại Desktop (dùng chung với tool đăng YouTube ở omnivoice/.../YOUTUBE; chép sang cạnh
file này, gitignore). Token: ~/.ghep_video_flow_google_token.json (quyền drive + spreadsheets).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
CLIENT_SECRET = HERE / "client_secret.json"
CLIENT_SECRET_DU_PHONG = Path(r"D:\Python\omnivoice\OmniVoice\myvoice\YOUTUBE\client_secret.json")
TOKEN = Path.home() / ".ghep_video_flow_google_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
COT_LINK_NGUYEN_LIEU, COT_LINK_VIDEO, COT_TIEU_DE = "F", "G", "D"      # tab "Lịch đăng video"
KHUC_TAI = 8 * 1024 * 1024

_lock = threading.Lock()
_cache: dict = {"creds": None, "email": "", "loi": ""}


def file_client_secret() -> Path | None:
    for p in (CLIENT_SECRET, CLIENT_SECRET_DU_PHONG):
        if p.is_file():
            return p
    return None


def thong_tin_client() -> dict:
    """{co, duong_dan, project, kieu} của client_secret.json đang dùng (để hiện ở tab Cài đặt)."""
    p = file_client_secret()
    if not p:
        return {"co": False, "duong_dan": str(CLIENT_SECRET), "project": "", "kieu": ""}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        k = next(iter(d))
        return {"co": True, "duong_dan": str(p), "project": d[k].get("project_id", ""), "kieu": k}
    except Exception as e:     # noqa: BLE001
        return {"co": False, "duong_dan": str(p), "project": "", "kieu": "", "loi": f"file client hỏng: {e}"}


def dat_client(nguon: Path) -> dict:
    """Chép file client_secret.json mới (tải từ Google Cloud Console, loại Desktop) vào cạnh app; token cũ bỏ."""
    d = json.loads(Path(nguon).read_text(encoding="utf-8"))
    k = next(iter(d))
    if k not in ("installed", "web") or "client_id" not in d[k]:
        raise ValueError("Không phải file OAuth client của Google (cần loại Desktop app, có 'installed').")
    if k == "web":
        raise ValueError("File này là client loại Web; app cần loại Desktop app (tạo lại: Application type = Desktop app).")
    CLIENT_SECRET.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    dang_xuat()
    return thong_tin_client()


def _doc_token():
    from google.oauth2.credentials import Credentials
    if not TOKEN.is_file():
        return None
    try:
        d = json.loads(TOKEN.read_text(encoding="utf-8"))
        if not set(SCOPES) <= set(d.get("scopes") or []):      # token cũ thiếu quyền -> coi như chưa đăng nhập
            return None
        return Credentials.from_authorized_user_info(d, SCOPES)
    except Exception:          # noqa: BLE001
        return None


def creds(dang_nhap: bool = False, log: Callable[[str], None] = print):
    """Credentials hợp lệ: token đã lưu (tự làm mới), hoặc mở trình duyệt đăng nhập khi dang_nhap=True.
    Trả None nếu chưa đăng nhập (và không được phép mở trình duyệt)."""
    from google.auth.transport.requests import Request
    with _lock:
        c = _cache["creds"] or _doc_token()
        if c and c.valid:
            _cache["creds"] = c
            return c
        if c and c.expired and c.refresh_token:
            try:
                c.refresh(Request())
                TOKEN.write_text(c.to_json(), encoding="utf-8")
                _cache["creds"] = c
                return c
            except Exception as e:      # noqa: BLE001
                log(f"làm mới token Google thất bại ({e}), cần đăng nhập lại")
        if not dang_nhap:
            return None
        cs = file_client_secret()
        if not cs:
            raise FileNotFoundError(f"Chưa có client_secret.json (OAuth client loại Desktop) ở {CLIENT_SECRET}")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
        log("mở trình duyệt để đăng nhập Google và cấp quyền Drive + Sheets…")
        try:
            c = flow.run_local_server(port=0, prompt="consent", timeout_seconds=300,
                                      authorization_prompt_message="", success_message="Đã đăng nhập, quay lại app Ghép video Flow.")
        except TypeError:                  # thư viện cũ không có timeout_seconds
            c = flow.run_local_server(port=0, prompt="consent", authorization_prompt_message="",
                                      success_message="Đã đăng nhập, quay lại app Ghép video Flow.")
        TOKEN.write_text(c.to_json(), encoding="utf-8")
        _cache.update(creds=c, email="")
        return c


def dang_xuat() -> None:
    with _lock:
        _cache.update(creds=None, email="")
        if TOKEN.exists():
            TOKEN.unlink()


HTTP_TIMEOUT = 180      # giây; mặc định httplib2 ngắn, tải khúc 8 MB qua mạng chậm hay bị "read operation timed out"


def _http(c):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    h = httplib2.Http(timeout=HTTP_TIMEOUT)
    # BẮT BUỘC như googleapiclient.http.build_http(): tải từng khúc, Google trả 308 "Resume Incomplete" (không có Location);
    # để follow_redirects mặc định thì httplib2 ném "Redirected but the response is missing a Location: header" ở khúc 2
    h.follow_redirects = False
    return AuthorizedHttp(c, http=h)


def _nen_thu_lai(e: Exception) -> bool:
    """Chỉ thử lại khi lỗi do mạng / máy chủ tạm thời; lỗi 4xx (hết dung lượng, không có quyền, thư mục mất) thì dừng ngay."""
    import socket
    import ssl
    from googleapiclient.errors import HttpError
    if isinstance(e, HttpError):
        return e.resp.status in (408, 429) or e.resp.status >= 500
    return isinstance(e, (socket.timeout, TimeoutError, ssl.SSLError, ConnectionError, OSError))


def _drive(c):
    from googleapiclient.discovery import build
    return build("drive", "v3", http=_http(c), cache_discovery=False)


def _sheets(c):
    from googleapiclient.discovery import build
    return build("sheets", "v4", http=_http(c), cache_discovery=False)


def trang_thai() -> dict:
    """{co_client, da_dang_nhap, email, loi} — gọi mỗi giây từ /api/state nên không gọi mạng trừ lần đầu lấy email."""
    cl = thong_tin_client()
    kq = {"co_client": cl["co"], "client": cl, "da_dang_nhap": False, "email": "", "loi": _cache["loi"] or cl.get("loi", ""),
          "token": str(TOKEN)}
    try:
        c = creds(False, log=lambda s: None)
    except Exception as e:     # noqa: BLE001
        kq["loi"] = str(e)
        return kq
    if not c:
        return kq
    kq["da_dang_nhap"] = True
    if not _cache["email"]:
        try:
            u = _drive(c).about().get(fields="user(emailAddress)").execute()
            _cache["email"] = u.get("user", {}).get("emailAddress", "")
        except Exception as e:  # noqa: BLE001
            _cache["email"] = "?"
            kq["loi"] = f"không đọc được tài khoản: {e}"
    kq["email"] = _cache["email"]
    return kq


# ================================================================ Drive
def folder_id(link: str) -> str | None:
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", link or "") or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", link or "")
    return m.group(1) if m else (link.strip() if re.fullmatch(r"[A-Za-z0-9_-]{20,}", (link or "").strip()) else None)


def thong_tin_thu_muc(fid: str, c=None) -> dict:
    """{id, ten, link, chu} — lỗi (không có quyền / không tồn tại) thì raise."""
    c = c or creds()
    if not c:
        raise RuntimeError("Chưa đăng nhập Google.")
    f = _drive(c).files().get(fileId=fid, fields="id,name,mimeType,owners(emailAddress),webViewLink",
                              supportsAllDrives=True).execute()
    if f.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError(f"{f.get('name')} không phải thư mục.")
    return {"id": f["id"], "ten": f["name"].strip(), "link": f.get("webViewLink") or f"https://drive.google.com/drive/folders/{f['id']}",
            "chu": (f.get("owners") or [{}])[0].get("emailAddress", "")}


def _lit(s: str) -> str:
    """Chuỗi trong câu truy vấn Drive: nháy đơn, escape \\ và ' (KHÔNG dùng json.dumps: nó đổi tiếng Việt thành \\uXXXX,
    Drive trả 400 Invalid Value)."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _tim_file(drive, fid: str, ten: str) -> str | None:
    """ID file (không phải thư mục, chưa xóa) tên đúng `ten` trong thư mục `fid`; không có -> None."""
    q = (f"'{fid}' in parents and trashed=false and name={_lit(ten)} and mimeType!='application/vnd.google-apps.folder'")
    r = drive.files().list(q=q, fields="files(id,name)", pageSize=5, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    f = r.get("files") or []
    return f[0]["id"] if f else None


def xoa_file_cu(fid: str, chua: str, duoi: str, giu: str = "", log: Callable[[str], None] = print) -> int:
    """Cho vào thùng rác các file trong thư mục `fid` có tên chứa `chua` và đuôi `duoi` (trừ tên `giu`): dọn bản txt
    minh họa của lần ghép trước để thư mục chỉ còn bản mới. -> số file đã bỏ."""
    c = creds()
    if not c:
        return 0
    drive = _drive(c)
    q = f"'{fid}' in parents and trashed=false and name contains {_lit(chua)}"
    r = drive.files().list(q=q, fields="files(id,name)", pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    n = 0
    for f in r.get("files") or []:
        if f["name"].lower().endswith(duoi.lower()) and f["name"] != giu:
            drive.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
            log(f"  bỏ bản cũ: {f['name']}")
            n += 1
    return n


def ten_file_an_toan(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]+', " ", s or "").strip(" .")
    return re.sub(r"\s+", " ", s)[:150] or "video"


MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".txt": "text/plain", ".srt": "text/plain", ".ass": "text/plain",
        ".jpg": "image/jpeg", ".png": "image/png", ".mp3": "audio/mpeg"}


def tao_thu_muc(fid_cha: str, ten: str, chia_se: bool = True, log: Callable[[str], None] = print) -> dict:
    """Thư mục con tên `ten` trong `fid_cha`: đã có (chưa xóa) thì dùng lại, chưa có thì tạo; chia_se = ai có link đều
    xem (file bên trong kế thừa). -> {id, link, ten, moi}."""
    c = creds()
    if not c:
        raise RuntimeError("Chưa đăng nhập Google (tab Cài đặt → Đăng nhập).")
    drive = _drive(c)
    ten = ten_file_an_toan(ten)
    q = (f"'{fid_cha}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder' and name={_lit(ten)}")
    r = drive.files().list(q=q, fields="files(id,name,webViewLink)", pageSize=5, supportsAllDrives=True,
                           includeItemsFromAllDrives=True).execute()
    co = r.get("files") or []
    if co:
        f, moi = co[0], False
    else:
        f = drive.files().create(body={"name": ten, "mimeType": "application/vnd.google-apps.folder", "parents": [fid_cha]},
                                 fields="id,name,webViewLink", supportsAllDrives=True).execute()
        moi = True
        if chia_se:
            try:
                drive.permissions().create(fileId=f["id"], body={"type": "anyone", "role": "reader"},
                                           supportsAllDrives=True).execute()
            except Exception as e:  # noqa: BLE001
                log(f"  không bật 'ai có link đều xem' cho thư mục được: {e}")
    link = f.get("webViewLink") or f"https://drive.google.com/drive/folders/{f['id']}"
    log(f"  thư mục Drive “{f['name']}”: " + ("tạo mới" if moi else "đã có, dùng lại") + f" → {link}")
    return {"id": f["id"], "link": link, "ten": f["name"], "moi": moi}


def tai_len(duong_dan: Path, fid: str, ten: str, log: Callable[[str], None] = print, chia_se: bool = True,
            tien_do: Callable[[int], None] | None = None) -> dict:
    """Tải file lên thư mục Drive `fid` với tên `ten` (giữ đuôi của `ten`), tải từng khúc KHUC_TAI. Đã có file cùng tên
    (chưa xóa) thì ĐÈ LÊN đúng file đó (giữ nguyên ID -> link cũ ở cột G vẫn mở ra bản mới). chia_se = ai có link đều
    xem. -> {id, link, ten, de (True = đã đè)}."""
    from googleapiclient.http import MediaFileUpload
    c = creds()
    if not c:
        raise RuntimeError("Chưa đăng nhập Google (tab Cài đặt → Đăng nhập).")
    drive = _drive(c)
    duoi = Path(ten).suffix.lower() or Path(duong_dan).suffix.lower()
    goc = ten[: -len(duoi)] if duoi and ten.lower().endswith(duoi) else ten
    ten = ten_file_an_toan(goc) + duoi                                   # bỏ ? : trước khi nối đuôi, khỏi "GÌ .mp4"
    media = MediaFileUpload(str(duong_dan), mimetype=MIME.get(duoi, "application/octet-stream"), chunksize=KHUC_TAI,
                            resumable=True)
    cu = _tim_file(drive, fid, ten)
    if cu:
        log(f"  đã có “{ten}” trên Drive → đè lên bản cũ (giữ nguyên link)")
        req = drive.files().update(fileId=cu, media_body=media, fields="id,webViewLink", supportsAllDrives=True)
    else:
        req = drive.files().create(body={"name": ten, "parents": [fid]}, media_body=media, fields="id,webViewLink",
                                   supportsAllDrives=True)
    kq, t0, bao, loi_lien_tiep = None, time.time(), 0.0, 0
    while kq is None:
        try:
            st, kq = req.next_chunk(num_retries=5)
            loi_lien_tiep = 0
        except Exception as e:      # noqa: BLE001 — mạng chập chờn (timeout, SSL, 5xx): chờ rồi tiếp tục từ khúc đang dở
            if not _nen_thu_lai(e):
                raise
            loi_lien_tiep += 1
            if loi_lien_tiep > 6:
                raise RuntimeError(f"tải lên thất bại sau {loi_lien_tiep} lần mạng lỗi: {e}") from e
            cho = 3 * loi_lien_tiep
            log(f"  mạng lỗi ({type(e).__name__}: {str(e)[:80]}), chờ {cho}s rồi tải tiếp…")
            time.sleep(cho)
            continue
        if st and time.time() - bao > 2:
            bao = time.time()
            pct = int(st.progress() * 100)
            log(f"  tải lên {ten}: {pct}%")
            if tien_do:
                tien_do(pct)
    if tien_do:
        tien_do(100)
    link = kq.get("webViewLink") or f"https://drive.google.com/file/d/{kq['id']}/view"
    if chia_se:
        try:
            drive.permissions().create(fileId=kq["id"], body={"type": "anyone", "role": "reader"},
                                       supportsAllDrives=True).execute()
        except Exception as e:  # noqa: BLE001
            log(f"  không bật 'ai có link đều xem' được: {e}")
    log(f"  tải lên xong {time.time() - t0:.0f}s" + (" (đã đè bản cũ)" if cu else "") + f": {link}")
    return {"id": kq["id"], "link": link, "ten": ten, "de": bool(cu)}


# ================================================================ Sheet lịch đăng
def sheet_id_gid(link: str) -> tuple[str | None, int | None]:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", link or "")
    g = re.search(r"[#?&]gid=(\d+)", link or "")
    return (m.group(1) if m else None), (int(g.group(1)) if g else None)


def _tab(sheets, sid: str, gid: int | None) -> tuple[str, str]:
    """(tên tab theo gid — không có gid thì tab đầu, tiêu đề Sheet)."""
    meta = sheets.spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties(sheetId,title)").execute()
    tabs = [s["properties"] for s in meta.get("sheets", [])]
    chon = next((t for t in tabs if gid is not None and t["sheetId"] == gid), tabs[0] if tabs else None)
    if not chon:
        raise RuntimeError("Sheet không có tab nào.")
    return chon["title"], meta.get("properties", {}).get("title", "")


def _so_cot(chu: str) -> int:
    n = 0
    for ch in chu.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def doc_lich(link: str, log: Callable[[str], None] = print) -> dict:
    """Đọc tab lịch đăng: -> {id, gid, tab, tieu_de_sheet, dong: [{dong, tieu_de, link_f, fid, link_g}], cot_f, cot_g}.
    Chỉ lấy dòng có tiêu đề (D) hoặc link nguyên liệu (F)."""
    sid, gid = sheet_id_gid(link)
    if not sid:
        raise RuntimeError("Không phải link Google Sheet.")
    c = creds()
    if not c:
        raise RuntimeError("Chưa đăng nhập Google (tab Cài đặt → Đăng nhập).")
    sh = _sheets(c)
    tab, tieu_de = _tab(sh, sid, gid)
    cuoi = chr(ord("A") + max(_so_cot(COT_LINK_VIDEO), _so_cot(COT_TIEU_DE), _so_cot(COT_LINK_NGUYEN_LIEU)))
    r = sh.spreadsheets().values().get(spreadsheetId=sid, range=f"'{tab}'!A2:{cuoi}").execute()
    iD, iF, iG = _so_cot(COT_TIEU_DE), _so_cot(COT_LINK_NGUYEN_LIEU), _so_cot(COT_LINK_VIDEO)
    dong = []
    for i, row in enumerate(r.get("values", []), start=2):
        lay = lambda k: (row[k].strip() if k < len(row) and row[k] else "")   # noqa: E731
        td, lf, lg = lay(iD), lay(iF), lay(iG)
        if not td and not lf:
            continue
        dong.append({"dong": i, "tieu_de": td, "link_f": lf, "fid": folder_id(lf) if lf else None, "link_g": lg})
    log(f"Sheet “{tieu_de}” tab “{tab}”: {len(dong)} dòng có tiêu đề/nguyên liệu")
    return {"id": sid, "gid": gid, "tab": tab, "tieu_de_sheet": tieu_de, "dong": dong,
            "cot_f": COT_LINK_NGUYEN_LIEU, "cot_g": COT_LINK_VIDEO}


def ghi_o(sid: str, tab: str, dong: int, cot: str, gia_tri: str) -> None:
    c = creds()
    if not c:
        raise RuntimeError("Chưa đăng nhập Google.")
    _sheets(c).spreadsheets().values().update(spreadsheetId=sid, range=f"'{tab}'!{cot}{dong}", valueInputOption="USER_ENTERED",
                                              body={"values": [[gia_tri]]}).execute()


if __name__ == "__main__":      # thử nhanh: python drive_len.py dangnhap | trangthai | sheet <link> | thumuc <link>
    import sys
    a = sys.argv[1:] or ["trangthai"]
    if a[0] == "dangnhap":
        creds(True)
        print(trang_thai())
    elif a[0] == "sheet":
        print(json.dumps(doc_lich(a[1]), ensure_ascii=False, indent=1))
    elif a[0] == "thumuc":
        print(thong_tin_thu_muc(folder_id(a[1])))
    else:
        print(trang_thai())
