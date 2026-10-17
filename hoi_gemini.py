# -*- coding: utf-8 -*-
"""Hỏi Gemini từ code Python qua Gemini CLI (`gemini -p`), đăng nhập bằng tài khoản Google
("Login with Google") — KHÔNG cần API key (mức miễn phí của Google cho Gemini CLI).

Dùng trong code (giống hoi_claude.py):
    from hoi_gemini import hoi, Phien
    print(hoi("Thủ đô Việt Nam là gì?").text)
    p = Phien(he_thong="Trả lời ngắn gọn bằng tiếng Việt.")
    print(p.hoi("Tôi tên Hải.")); print(p.hoi("Tôi tên gì?"))

Dòng lệnh: python hoi_gemini.py "câu hỏi"   |   python hoi_gemini.py  (chat nhiều lượt)

Cách chạy bên dưới: `gemini -p <câu hỏi> -o json --skip-trust [-m model] [-r session_id]`
(câu hỏi dài hơn GIOI_HAN_DONG_LENH ký tự thì đưa qua stdin, -p chỉ còn câu dẫn). JSON trả về
{"session_id","response","stats"} hoặc {"session_id","error":{"message","code"}}.
Gemini CLI không có "system prompt" riêng -> `he_thong` ghép vào đầu câu hỏi lượt đầu.
Đăng nhập: ghi ~/.gemini/settings.json security.auth.selectedType = "oauth-personal" rồi chạy
gemini trong cửa sổ lệnh -> trình duyệt mở trang Google -> chọn tài khoản; token lưu ở
~/.gemini/oauth_creds.json (có file này = đã kết nối).
Yêu cầu: Node >= 20 và `npm install -g @google/gemini-cli`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli_chung   # noqa: E402  (tìm CLI kể cả khi PATH của Explorer thiếu thư mục npm/nvm)

TEN = "Gemini"
CLI = "gemini"
LENH_CAI = "npm install -g @google/gemini-cli"
THU_MUC_GEMINI = Path.home() / ".gemini"
FILE_CREDS = THU_MUC_GEMINI / "oauth_creds.json"
FILE_TAI_KHOAN = THU_MUC_GEMINI / "google_accounts.json"
FILE_SETTINGS = THU_MUC_GEMINI / "settings.json"
GIOI_HAN_DONG_LENH = 6000      # ký tự; dài hơn thì đưa câu hỏi qua stdin
THOI_GIAN_CHO = 600
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


class GeminiLoi(RuntimeError):
    """Không gọi được gemini, hoặc gemini trả lỗi (chưa đăng nhập, hết hạn mức...)."""


@dataclass
class TraLoi:
    text: str
    session_id: str
    model: str = ""
    cost_usd: float = 0.0      # mức miễn phí; để cùng khuôn với hoi_claude
    raw: dict = field(default_factory=dict, repr=False)

    def __str__(self) -> str:
        return self.text


def _exe() -> str:
    """gemini mới nhất tìm được (PATH + thư mục npm/nvm — app mở từ shortcut có thể thiếu PATH)."""
    ds = cli_chung.tim_lenh_moi_nhat(CLI)
    if not ds:
        raise GeminiLoi(f"Không tìm thấy lệnh `{CLI}`. Cài bằng: {LENH_CAI}")
    return ds[0][0]


def _env() -> dict:
    env = dict(os.environ)
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"     # headless không hỏi "trust folder"
    env["NO_BROWSER"] = "1"                        # khi gọi từ code thì KHÔNG tự bật trình duyệt đăng nhập
    return env


def hoi(cau_hoi: str, *, he_thong: str | None = None, model: str | None = None, phien: str | None = None,
        thu_muc: str | Path | None = None, thoi_gian: float = THOI_GIAN_CHO) -> TraLoi:
    """Gửi một câu hỏi, trả về TraLoi. `phien` = session_id lượt trước để hỏi tiếp.
    `model`: vd "gemini-2.5-pro" / "gemini-2.5-flash"; None = mặc định của CLI."""
    noi_dung = f"{he_thong.strip()}\n\n{cau_hoi}" if (he_thong and not phien) else cau_hoi
    cmd = [_exe(), "-o", "json", "--skip-trust"]
    if model:
        cmd += ["-m", model]
    if phien:
        cmd += ["-r", phien]
    if len(noi_dung) <= GIOI_HAN_DONG_LENH:
        cmd += ["-p", noi_dung]
        stdin = ""
    else:                                          # -p được NỐI SAU nội dung stdin
        cmd += ["-p", "(Trả lời nội dung ở trên.)"]
        stdin = noi_dung
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(thu_muc or Path.home()), env=_env(), timeout=thoi_gian, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise GeminiLoi(f"Gemini không trả lời trong {thoi_gian:.0f}s.") from None
    out = r.stdout.strip()
    d = None
    if out.startswith("{"):
        try:
            d = json.loads(out)
        except ValueError:
            d = None
    if d is None:                                  # có khi lỗi in ra stderr dạng chữ
        loi = r.stderr.strip() or out or f"gemini thoát mã {r.returncode}"
        raise GeminiLoi(_rut_gon_loi(loi))
    if d.get("error"):
        raise GeminiLoi(_rut_gon_loi(str(d["error"].get("message") or d["error"])))
    text = d.get("response")
    if text is None:
        raise GeminiLoi(f"gemini trả JSON không có 'response': {out[:300]}")
    stats = d.get("stats") or {}
    models = stats.get("models") or {}
    return TraLoi(text=str(text).strip(), session_id=str(d.get("session_id") or phien or ""),
                  model=model or (next(iter(models), "") if isinstance(models, dict) else ""), raw=d)


def _rut_gon_loi(s: str) -> str:
    s = s.strip()
    if "Manual authorization is required" in s or "Please set an Auth method" in s or "login" in s.lower():
        s = "Chưa đăng nhập Google cho Gemini CLI — bấm Kết nối (hoặc chạy `gemini` trong terminal) để đăng nhập.\n" + s
    return s[:2000]


class Phien:
    """Hội thoại nhiều lượt (Gemini CLI nhớ ngữ cảnh qua -r session_id)."""

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


MODEL_MAC_DINH = [{"id": "gemini-2.5-pro", "ten": "Gemini 2.5 Pro"}, {"id": "gemini-2.5-flash", "ten": "Gemini 2.5 Flash"},
                  {"id": "gemini-2.5-flash-lite", "ten": "Gemini 2.5 Flash Lite"}]
_MODEL_CACHE: dict = {}


def _thu_muc_bundle() -> Path | None:
    ds = cli_chung.tim_lenh_moi_nhat(CLI)
    if not ds:
        return None
    exe = ds[0][0]
    for goc in (Path(exe).parent, Path(exe).resolve().parent):
        b = goc / "node_modules" / "@google" / "gemini-cli" / "bundle"
        if b.is_dir():
            return b
    return None


def danh_sach_model() -> list[dict]:
    """[{"id","ten"}] các model Gemini mà bản CLI đang cài biết (quét tên trong bundle JS; cập nhật khi
    nâng cấp CLI). Không quét được thì dùng danh sách mặc định."""
    b = _thu_muc_bundle()
    if b is None:
        return list(MODEL_MAC_DINH)
    js = sorted(b.glob("*.js"))
    ky = (str(b), tuple((p.name, p.stat().st_mtime_ns) for p in js))
    if _MODEL_CACHE.get("ky") == ky:
        return _MODEL_CACHE["kq"]
    mau = re.compile(rb"gemini-(\d+)\.(\d+)-(pro|flash-lite|flash)(-preview)?(?![\w-])")
    thay: dict[str, tuple] = {}
    for p in js:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        for m in mau.finditer(data):
            ten = m.group(0).decode()
            hang = {b"pro": 0, b"flash": 1, b"flash-lite": 2}[m.group(3)]
            thay[ten] = (-int(m.group(1)), -int(m.group(2)), hang, 1 if m.group(4) else 0)
    kq = [{"id": t, "ten": t.replace("gemini-", "Gemini ").replace("-", " ").title().replace("Lite", "Lite")}
          for t, _ in sorted(thay.items(), key=lambda kv: kv[1])] or list(MODEL_MAC_DINH)
    _MODEL_CACHE.update(ky=ky, kq=kq)
    return kq


# ------------------------------------------------------------------ trạng thái / đăng nhập (cho ket_noi_ai.py)
def chon_dang_nhap_google() -> None:
    """Ghi ~/.gemini/settings.json: cách xác thực = Login with Google (giữ các mục khác)."""
    try:
        d = json.loads(FILE_SETTINGS.read_text(encoding="utf-8")) if FILE_SETTINGS.exists() else {}
    except ValueError:
        d = {}
    d.setdefault("security", {}).setdefault("auth", {})["selectedType"] = "oauth-personal"
    THU_MUC_GEMINI.mkdir(exist_ok=True)
    FILE_SETTINGS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def trang_thai() -> dict:
    """{"ten","cli","cai","phien_ban","ket_noi","email","ghi_chu"} — chỉ xem file, không mở mạng."""
    kq = dict(ten=TEN, cli=CLI, cai=False, phien_ban="", ket_noi=False, email="", ghi_chu="", duong_dan="")
    ds = cli_chung.tim_lenh_moi_nhat(CLI)
    if not ds:
        kq["ghi_chu"] = f"chưa cài Gemini CLI ({LENH_CAI})"
        return kq
    exe, ver = ds[0]
    kq["cai"] = True
    kq["duong_dan"] = exe
    kq["phien_ban"] = cli_chung.chuoi_phien_ban(ver)
    if FILE_CREDS.exists():
        kq["ket_noi"] = True
        try:
            kq["email"] = (json.loads(FILE_TAI_KHOAN.read_text(encoding="utf-8")) or {}).get("active") or ""
        except Exception:
            pass
        kq["ghi_chu"] = "đăng nhập Google (Gemini CLI)"
    else:
        kq["ghi_chu"] = "chưa đăng nhập Google"
    return kq


def dang_nhap() -> None:
    """Mở cửa sổ lệnh: gemini hỏi một câu -> chưa có token thì tự mở trình duyệt trang đăng nhập Google;
    đăng nhập xong nó trả lời rồi cửa sổ giữ lại để xem. Không được thì chạy gemini tương tác."""
    chon_dang_nhap_google()
    exe = _exe()
    lenh = (f'chcp 65001>nul & title Ket noi Gemini (dang nhap Google) & set GEMINI_CLI_TRUST_WORKSPACE=true & '
            f'"{exe}" -p "Xin chao! Toi da ket noi Gemini CLI thanh cong chua? Tra loi mot cau." || "{exe}"')
    env = {k: v for k, v in os.environ.items() if k != "NO_BROWSER"}
    subprocess.Popen(["cmd", "/k", lenh], creationflags=NEW_CONSOLE, env=env)


def dang_xuat() -> str:
    if FILE_CREDS.exists():
        FILE_CREDS.unlink()
        return "đã xoá oauth_creds.json"
    return "chưa đăng nhập"


def cai_dat() -> None:
    subprocess.Popen(["cmd", "/k", f"chcp 65001>nul & title Cai Gemini CLI & {LENH_CAI}"], creationflags=NEW_CONSOLE)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Hỏi Gemini qua Gemini CLI (đăng nhập Google, không cần API key).")
    ap.add_argument("cau_hoi", nargs="*", help="câu hỏi; bỏ trống = chat nhiều lượt")
    ap.add_argument("--model", help="vd gemini-2.5-pro / gemini-2.5-flash (mặc định: của CLI)")
    ap.add_argument("--he-thong", help="chỉ dẫn chung, ghép vào đầu câu hỏi lượt đầu")
    ap.add_argument("--trang-thai", action="store_true", help="chỉ in trạng thái đăng nhập")
    ap.add_argument("--dang-nhap", action="store_true", help="mở cửa sổ đăng nhập Google")
    args = ap.parse_args()
    if args.trang_thai:
        print(json.dumps(trang_thai(), ensure_ascii=False, indent=1)); return
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
