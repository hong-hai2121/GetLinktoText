# -*- coding: utf-8 -*-
"""Hỏi Gemini từ code Python qua Antigravity CLI (`agy -p`), đăng nhập bằng tài khoản Google — KHÔNG cần API key.

Vì sao là `agy` chứ không phải `gemini`: Google đã ngừng phục vụ Gemini CLI cho tài khoản Google cá nhân từ
18/6/2026. Đăng nhập `gemini` vẫn qua, nhưng hỏi thì báo "This client is no longer supported for Gemini Code
Assist for individuals ... migrate to the Antigravity suite". Sản phẩm thay thế là Antigravity CLI (lệnh `agy`),
dùng chung đăng nhập với Antigravity IDE. Module này chuyển sang `agy` ngày 26/11/2026, giữ nguyên khuôn hàm.

Dùng trong code (giống hoi_claude.py):
    from hoi_gemini import hoi, Phien
    print(hoi("Thủ đô Việt Nam là gì?").text)
    p = Phien(he_thong="Trả lời ngắn gọn bằng tiếng Việt.")
    print(p.hoi("Tôi tên Hải.")); print(p.hoi("Tôi tên gì?"))

Dòng lệnh: python hoi_gemini.py "câu hỏi"   |   python hoi_gemini.py  (chat nhiều lượt)

Cách chạy bên dưới:
    agy --output-format json --disable-slash-commands --print-timeout <N>s [--model id] [--conversation id] -p <câu hỏi>
JSON trả về {"conversation_id","status":"SUCCESS","response",...} hoặc {"status":"ERROR","error":...}.
- `agy` là một agent có công cụ; ở chế độ in (-p) mọi công cụ cần xin phép (chạy lệnh, sửa file) tự bị từ chối,
  chỉ đọc được file trong thư mục làm việc -> chạy trong một thư mục tạm riêng, trống.
- stdin KHÔNG được coi là câu hỏi. Câu hỏi quá dài so với giới hạn dòng lệnh Windows thì ghi ra file trong thư
  mục làm việc và bảo agy đọc file đó.
- Không có "system prompt" riêng -> `he_thong` ghép vào đầu câu hỏi lượt đầu.
Đăng nhập: chạy `agy` trong cửa sổ lệnh, làm theo màn hình (trình duyệt mở trang Google). Token nằm trong kho mật
khẩu của máy (Windows Credential Manager, mục "gemini:antigravity"; macOS Keychain service "gemini" account
"antigravity") — có mục này = đã kết nối.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli_chung   # noqa: E402  (tìm CLI kể cả khi PATH của Explorer thiếu thư mục cài)

TEN = "Gemini"
CLI = "agy"                    # Antigravity CLI
LENH_CAI_WIN = ('powershell -NoProfile -ExecutionPolicy Bypass -Command '
                '"irm https://antigravity.google/cli/install.ps1 | iex"')      # cài vào %LOCALAPPDATA%\agy\bin
LENH_CAI_MAC = "curl -fsSL https://antigravity.google/cli/install.sh | bash"   # cài vào ~/.local/bin
LENH_CAI = LENH_CAI_WIN if os.name == "nt" else LENH_CAI_MAC
THU_MUC_GEMINI = Path.home() / ".gemini"
FILE_TAI_KHOAN = THU_MUC_GEMINI / "google_accounts.json"
KHO_DICH_VU, KHO_TAI_KHOAN = "gemini", "antigravity"     # mục giữ token trong kho mật khẩu của máy
GIOI_HAN_DONG_LENH = 30000     # ký tự của CẢ dòng lệnh (Windows cho tối đa 32767); dài hơn thì đưa câu hỏi qua file
THOI_GIAN_CHO = 600
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CAU_DOC_FILE = ("Toàn bộ yêu cầu nằm trong file {ten} ở thư mục làm việc hiện tại. Hãy đọc hết file đó rồi trả lời "
                "đúng theo yêu cầu ghi trong file. Chỉ in ra câu trả lời, không tạo hay sửa file nào.")
NHAC_KHONG_CONG_CU = "\n\n(Trả lời trực tiếp bằng văn bản; không dùng công cụ, không chạy lệnh.)"


class GeminiLoi(RuntimeError):
    """Không gọi được agy, hoặc agy trả lỗi (chưa đăng nhập, hết hạn mức, model sai...)."""


@dataclass
class TraLoi:
    text: str
    session_id: str
    model: str = ""
    cost_usd: float = 0.0      # tính theo gói tài khoản; để cùng khuôn với hoi_claude
    raw: dict = field(default_factory=dict, repr=False)

    def __str__(self) -> str:
        return self.text


def _exe() -> str:
    """agy mới nhất tìm được (PATH + thư mục cài quen thuộc — app mở từ shortcut có thể thiếu PATH)."""
    ds = cli_chung.tim_lenh_moi_nhat(CLI)
    if not ds:
        raise GeminiLoi(f"Không tìm thấy lệnh `{CLI}` (Antigravity CLI). Cài bằng: {LENH_CAI}")
    return ds[0][0]


def _thu_muc_lam_viec() -> Path:
    """Thư mục tạm riêng, trống: agy đọc được file trong thư mục làm việc nên không cho nó đứng ở thư mục thật."""
    d = Path(tempfile.gettempdir()) / "hoi_gemini_agy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_json(out: str) -> dict | None:
    """Dòng JSON kết quả trong stdout (agy có thể in thêm dòng chữ phía trước)."""
    for dong in reversed(out.strip().splitlines()):
        dong = dong.strip()
        if not dong.startswith("{"):
            continue
        try:
            d = json.loads(dong)
        except ValueError:
            continue
        if isinstance(d, dict) and ("status" in d or "response" in d):
            return d
    return None


def _goi(noi_dung: str, model: str | None, phien: str | None, thu_muc: str | Path | None, thoi_gian: float) -> dict:
    """Chạy agy một lượt, trả về dict JSON kết quả (status SUCCESS). Lỗi -> GeminiLoi."""
    wd = Path(thu_muc) if thu_muc else _thu_muc_lam_viec()
    dau = [_exe(), "--output-format", "json", "--disable-slash-commands", "--print-timeout", f"{max(5, int(thoi_gian))}s"]
    if model:
        dau += ["--model", model]
    if phien:
        dau += ["--conversation", phien]
    cmd = dau + ["-p", noi_dung]
    tep = None
    if len(subprocess.list2cmdline(cmd)) > GIOI_HAN_DONG_LENH:
        tep = wd / f"cau_hoi_{uuid.uuid4().hex[:8]}.txt"
        tep.write_text(noi_dung, encoding="utf-8")
        cmd = dau + ["-p", CAU_DOC_FILE.format(ten=tep.name)]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(wd), timeout=thoi_gian + 20, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise GeminiLoi(f"Gemini không trả lời trong {thoi_gian:.0f}s.") from None
    finally:
        if tep is not None:
            try:
                tep.unlink()
            except OSError:
                pass
    d = _doc_json(r.stdout)
    if d is None:                                  # có khi lỗi chỉ in ra stderr dạng chữ
        raise GeminiLoi(_rut_gon_loi(r.stderr.strip() or r.stdout.strip() or f"agy thoát mã {r.returncode}"))
    if d.get("error") or str(d.get("status") or "SUCCESS").upper() != "SUCCESS":
        loi = str(d.get("error") or d.get("status"))
        if "print timeout" in loi:
            raise GeminiLoi(f"Gemini không trả lời trong {thoi_gian:.0f}s.")
        raise GeminiLoi(_rut_gon_loi(loi))
    return d


def hoi(cau_hoi: str, *, he_thong: str | None = None, model: str | None = None, phien: str | None = None,
        thu_muc: str | Path | None = None, thoi_gian: float = THOI_GIAN_CHO) -> TraLoi:
    """Gửi một câu hỏi, trả về TraLoi. `phien` = session_id (conversation_id) lượt trước để hỏi tiếp.
    `model`: id trong danh_sach_model(), vd "gemini-3.8-flash-medium"; None = mặc định của Antigravity."""
    noi_dung = f"{he_thong.strip()}\n\n{cau_hoi}" if (he_thong and not phien) else cau_hoi
    d = _goi(noi_dung, model, phien, thu_muc, thoi_gian)
    text = str(d.get("response") or "").strip()
    if not text and d.get("denied_actions"):
        # model định dùng công cụ (bị từ chối ở chế độ in) thay vì trả lời -> nhắc rồi hỏi lại MỘT lần
        d = _goi(noi_dung + NHAC_KHONG_CONG_CU, model, phien, thu_muc, thoi_gian)
        text = str(d.get("response") or "").strip()
    if not text:
        cc = ", ".join(str(a.get("display_name") or a.get("action")) for a in (d.get("denied_actions") or []) if isinstance(a, dict))
        raise GeminiLoi("Gemini không trả lời bằng chữ" + (f" (định dùng công cụ: {cc})." if cc else "."))
    return TraLoi(text=text, session_id=str(d.get("conversation_id") or phien or ""), model=model or "", raw=d)


def _rut_gon_loi(s: str) -> str:
    s = s.strip()
    thuong = s.lower()
    if "invalid model selection" in thuong:
        return ("Model này không có trong Antigravity CLI — chọn lại model trong danh sách (hoặc để mặc định).\n"
                + s.splitlines()[0])[:2000]
    if any(t in thuong for t in ("not signed in", "unauthenticated", "sign in to", "please log in", "login required", " 401")):
        s = "Chưa đăng nhập Google cho Antigravity CLI — bấm Kết nối (hoặc chạy `agy` trong terminal) để đăng nhập.\n" + s
    return s[:2000]


class Phien:
    """Hội thoại nhiều lượt (Antigravity CLI nhớ ngữ cảnh qua --conversation id)."""

    def __init__(self, he_thong: str | None = None, model: str | None = None, thu_muc: str | Path | None = None):
        self.he_thong, self.model, self.thu_muc = he_thong, model, thu_muc
        self.session_id: str | None = None
        self.lich_su: list[TraLoi] = []

    def hoi(self, cau_hoi: str, **kw) -> str:
        r = hoi(cau_hoi, he_thong=self.he_thong, model=self.model, phien=self.session_id, thu_muc=self.thu_muc, **kw)
        self.session_id = r.session_id or self.session_id
        self.lich_su.append(r)
        return r.text

    def lam_moi(self):
        self.session_id, self.lich_su = None, []


# Dùng khi chưa hỏi được `agy models` (chưa đăng nhập / mất mạng); id lấy từ `agy models` bản 1.4.0.
MODEL_MAC_DINH = [{"id": "gemini-4-neon-high", "ten": "Gemini 4 Neon (High)"},
                  {"id": "gemini-4-carbon-medium", "ten": "Gemini 4 Carbon (Medium)"},
                  {"id": "gemini-3.8-flash-medium", "ten": "Gemini 3.8 Flash (Medium)"}]
MODEL_NHO, MODEL_NHO_LOI = 6 * 3600, 300           # giây nhớ danh sách: hỏi được / không hỏi được
_MODEL_CACHE: dict = {}


def danh_sach_model() -> list[dict]:
    """[{"id","ten"}] các model Gemini mà Antigravity CLI đang cho dùng (`agy models`, lọc id bắt đầu "gemini-").
    Lệnh này cần mạng nên kết quả được nhớ MODEL_NHO giây; chưa đăng nhập / lỗi thì trả danh sách mặc định."""
    ds = cli_chung.tim_lenh_moi_nhat(CLI)
    if not ds:
        return list(MODEL_MAC_DINH)
    exe = ds[0][0]
    bay_gio = time.time()
    if _MODEL_CACHE.get("exe") == exe and bay_gio < _MODEL_CACHE.get("het", 0):
        return _MODEL_CACHE["kq"]
    kq: list[dict] = []
    if _da_dang_nhap():                            # chưa đăng nhập thì không gọi (tránh agy tự bật đăng nhập)
        try:
            r = subprocess.run([exe, "models"], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=str(_thu_muc_lam_viec()), timeout=40, creationflags=NO_WINDOW)
            for dong in r.stdout.splitlines():     # "gemini-4-neon-high<TAB>Gemini 4 Neon (High)"
                phan = re.split(r"\t+|\s{2,}", dong.strip(), maxsplit=1)
                if len(phan) == 2 and phan[0].startswith("gemini-") and phan[1].strip():
                    kq.append({"id": phan[0], "ten": phan[1].strip()})
        except Exception:                          # noqa: BLE001
            kq = []
    _MODEL_CACHE.update(exe=exe, kq=kq or list(MODEL_MAC_DINH), het=bay_gio + (MODEL_NHO if kq else MODEL_NHO_LOI))
    return _MODEL_CACHE["kq"]


# ------------------------------------------------------------------ kho mật khẩu của máy (nơi agy giữ token)
def _kho_win():
    import ctypes
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.CredReadW.restype = wintypes.BOOL
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredDeleteW.restype = wintypes.BOOL
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, adv


def _kho_doc_win(dich_vu: str, tai_khoan: str) -> bytes | None:
    """Nội dung mục `dich_vu:tai_khoan` trong Windows Credential Manager; không có mục -> None."""
    ctypes, adv = _kho_win()
    from ctypes import wintypes

    class CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    p = ctypes.c_void_p()
    if not adv.CredReadW(f"{dich_vu}:{tai_khoan}", 1, 0, ctypes.byref(p)):      # 1 = CRED_TYPE_GENERIC
        return None
    try:
        c = ctypes.cast(p, ctypes.POINTER(CRED)).contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
    finally:
        adv.CredFree(p)


def _email_dang_nhap() -> str:
    """Email tài khoản Google mà Antigravity ĐANG đăng nhập, đọc từ id_token trong kho mật khẩu (Windows).
    KHÔNG lấy từ ~/.gemini/google_accounts.json: file đó Gemini CLI cũ cũng ghi, nên có thể là tài khoản khác hẳn
    (26/11/2026: file ghi một email, token Antigravity thuộc email khác). Chỉ lấy email, không giữ token."""
    try:
        if os.name == "nt":
            blob = _kho_doc_win(KHO_DICH_VU, KHO_TAI_KHOAN)
            if not blob:
                return ""
            import base64
            jwt = str((json.loads(blob.decode("utf-8")) or {}).get("id_token") or "")
            than = jwt.split(".")[1]
            return str(json.loads(base64.urlsafe_b64decode(than + "=" * (-len(than) % 4))).get("email") or "")
        # macOS: đọc nội dung Keychain sẽ bật hộp xin quyền mỗi lần dò -> đành theo file tài khoản (có thể lệch)
        return str((json.loads(FILE_TAI_KHOAN.read_text(encoding="utf-8")) or {}).get("active") or "")
    except Exception:                              # noqa: BLE001
        return ""


def _kho_co(dich_vu: str = KHO_DICH_VU, tai_khoan: str = KHO_TAI_KHOAN) -> bool:
    """Có mục `dich_vu:tai_khoan` trong kho mật khẩu không."""
    try:
        if os.name == "nt":
            return _kho_doc_win(dich_vu, tai_khoan) is not None
        if sys.platform == "darwin":
            return subprocess.run(["security", "find-generic-password", "-s", dich_vu, "-a", tai_khoan],
                                  capture_output=True, timeout=15).returncode == 0
    except Exception:                              # noqa: BLE001
        pass
    return False


def _kho_xoa(dich_vu: str = KHO_DICH_VU, tai_khoan: str = KHO_TAI_KHOAN) -> bool:
    try:
        if os.name == "nt":
            _, adv = _kho_win()
            return bool(adv.CredDeleteW(f"{dich_vu}:{tai_khoan}", 1, 0))
        if sys.platform == "darwin":
            return subprocess.run(["security", "delete-generic-password", "-s", dich_vu, "-a", tai_khoan],
                                  capture_output=True, timeout=15).returncode == 0
    except Exception:                              # noqa: BLE001
        pass
    return False


def _da_dang_nhap() -> bool:
    return _kho_co()


# ------------------------------------------------------------------ trạng thái / đăng nhập (cho ket_noi_ai.py)
def trang_thai() -> dict:
    """{"ten","cli","cai","phien_ban","ket_noi","email","ghi_chu"} — chỉ xem máy, không mở mạng."""
    kq = dict(ten=TEN, cli=CLI, cai=False, phien_ban="", ket_noi=False, email="", ghi_chu="", duong_dan="")
    ds = cli_chung.tim_lenh_moi_nhat(CLI)
    if not ds:
        kq["ghi_chu"] = "chưa cài Antigravity CLI (lệnh agy) — bấm Cài đặt"
        return kq
    exe, ver = ds[0]
    kq["cai"] = True
    kq["duong_dan"] = exe
    kq["phien_ban"] = cli_chung.chuoi_phien_ban(ver)
    if _da_dang_nhap():
        kq["ket_noi"] = True
        kq["email"] = _email_dang_nhap()
        kq["ghi_chu"] = "đăng nhập Google (Antigravity CLI)"
    else:
        kq["ghi_chu"] = "chưa đăng nhập Google"
    return kq


def dang_nhap() -> None:
    """Mở cửa sổ lệnh chạy `agy` (tương tác): chưa đăng nhập thì nó dẫn sang trình duyệt để chọn tài khoản Google.
    Đăng nhập xong đóng cửa sổ đó là được."""
    exe = _exe()
    cli_chung.mo_cua_so_lenh(f'"{exe}"', f'"{exe}"', "Ket noi Gemini (Antigravity CLI - dang nhap Google)")


def dang_xuat() -> str:
    """Xoá token Google của Antigravity trong kho mật khẩu của máy. Antigravity IDE dùng chung token này nên cũng
    bị đăng xuất theo."""
    if not _kho_co():
        return "chưa đăng nhập"
    if _kho_xoa():
        _MODEL_CACHE.clear()
        return "đã đăng xuất Antigravity (CLI và IDE dùng chung đăng nhập này)"
    return "không xoá được token — mở `agy` rồi đăng xuất trong đó"


def cai_dat() -> None:
    cli_chung.mo_cua_so_lenh(LENH_CAI_WIN, LENH_CAI_MAC, "Cai Antigravity CLI (agy)")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Hỏi Gemini qua Antigravity CLI (đăng nhập Google, không cần API key).")
    ap.add_argument("cau_hoi", nargs="*", help="câu hỏi; bỏ trống = chat nhiều lượt")
    ap.add_argument("--model", help="id model, xem --models (mặc định: của Antigravity)")
    ap.add_argument("--he-thong", help="chỉ dẫn chung, ghép vào đầu câu hỏi lượt đầu")
    ap.add_argument("--trang-thai", action="store_true", help="chỉ in trạng thái đăng nhập")
    ap.add_argument("--models", action="store_true", help="in danh sách model Gemini dùng được")
    ap.add_argument("--dang-nhap", action="store_true", help="mở cửa sổ đăng nhập Google")
    args = ap.parse_args()
    if args.trang_thai:
        print(json.dumps(trang_thai(), ensure_ascii=False, indent=1)); return
    if args.models:
        for m in danh_sach_model():
            print(f"{m['id']}\t{m['ten']}")
        return
    if args.dang_nhap:
        dang_nhap(); print("Đã mở cửa sổ đăng nhập."); return
    p = Phien(he_thong=args.he_thong, model=args.model)
    if args.cau_hoi:
        try:
            print(p.hoi(" ".join(args.cau_hoi)))
        except GeminiLoi as e:
            sys.exit(f"LỖI: {e}")
        return
    print("Chat với Gemini (Enter trống để thoát, /moi = hội thoại mới).")
    while True:
        try:
            cau = input("\nBạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cau:
            break
        if cau == "/moi":
            p.lam_moi(); print("(đã bắt đầu hội thoại mới)"); continue
        try:
            print(f"\nGemini: {p.hoi(cau)}")
        except GeminiLoi as e:
            print(f"LỖI: {e}")


if __name__ == "__main__":
    main()
