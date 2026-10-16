# -*- coding: utf-8 -*-
"""Hỏi Claude từ code Python qua Claude Code CLI (`claude -p`), dùng gói Claude đang đăng nhập
trên máy (Pro/Max) — KHÔNG cần API key, không mất phí riêng (tính vào hạn mức gói).

Dùng trong code:
    from hoi_claude import hoi, Phien

    r = hoi("Thủ đô Việt Nam là gì?")              # một lượt
    print(r.text)                                   # "Hà Nội"

    p = Phien(he_thong="Trả lời ngắn gọn bằng tiếng Việt.")   # nhiều lượt, nhớ ngữ cảnh
    print(p.hoi("Tôi tên Hải."))
    print(p.hoi("Tôi tên gì?"))                     # -> nhớ "Hải"

Dòng lệnh:
    python hoi_claude.py "câu hỏi"                  # hỏi một câu rồi thoát
    python hoi_claude.py                            # chat nhiều lượt, Enter trống để thoát
    python hoi_claude.py --model sonnet "câu hỏi"   # đổi model (sonnet / opus / haiku / id đầy đủ)

Cách chạy bên dưới: `claude -p --output-format json [--tools ""] [--system-prompt ...] [--model ...]
[--resume <session_id>]`, câu hỏi đưa qua stdin (không giới hạn độ dài dòng lệnh Windows).
Mặc định TẮT hết công cụ (`--tools ""`) để Claude chỉ trả lời chữ, không đọc/ghi file trên máy;
`cong_cu=True` nếu muốn nó dùng được Read/Bash/WebSearch... như trong Claude Code.
Yêu cầu: đã cài Claude Code và đã đăng nhập (`claude` chạy được trong terminal).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TEN = "Claude"
CLI = "claude"
LENH_CAI = "npm install -g @anthropic-ai/claude-code"
LENH_DANG_NHAP = "claude auth login"        # mở trình duyệt -> trang đăng nhập Claude (chọn Google hoặc email)
THOI_GIAN_CHO = 600            # giây chờ tối đa một câu trả lời
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # không bật cửa sổ console khi gọi từ pythonw/GUI
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
# gọi từ bên trong một phiên Claude Code khác thì CLI từ chối lồng nhau -> bỏ các biến này đi
_ENV_BO = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


class ClaudeLoi(RuntimeError):
    """Không gọi được claude, hoặc claude trả lỗi (chưa đăng nhập, hết hạn mức, ...)."""


@dataclass
class TraLoi:
    text: str                  # câu trả lời
    session_id: str            # dùng để hỏi tiếp cùng ngữ cảnh (hoi(..., phien=session_id))
    model: str = ""            # model thực tế đã trả lời
    cost_usd: float = 0.0      # chi phí ước tính CLI báo (chỉ để tham khảo, gói thuê bao không tính tiền lẻ)
    raw: dict = field(default_factory=dict, repr=False)   # toàn bộ JSON CLI trả về

    def __str__(self) -> str:
        return self.text


def _claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise ClaudeLoi("Không tìm thấy lệnh `claude` trên PATH. Cài Claude Code rồi chạy `claude` đăng nhập trước.")
    return exe


def hoi(cau_hoi: str, *, he_thong: str | None = None, model: str | None = None, phien: str | None = None,
        cong_cu: bool = False, thu_muc: str | Path | None = None, thoi_gian: float = THOI_GIAN_CHO) -> TraLoi:
    """Gửi một câu hỏi, chờ trả lời xong rồi trả về TraLoi.

    he_thong : chỉ dẫn hệ thống (thay toàn bộ prompt hệ thống mặc định của Claude Code), vd
               "Bạn là biên tập viên, trả lời bằng tiếng Việt, không giải thích thêm."
    model    : "sonnet" / "opus" / "haiku" hoặc id đầy đủ; None = mặc định của CLI.
    phien    : session_id của lượt trước -> hỏi tiếp cùng ngữ cảnh.
    cong_cu  : False (mặc định) = chỉ trả lời chữ; True = cho dùng công cụ (đọc file, chạy lệnh, web...).
    thu_muc  : thư mục làm việc (ảnh hưởng CLAUDE.md và nơi lưu phiên); mặc định thư mục người dùng.
    """
    cmd = [_claude_exe(), "-p", "--output-format", "json"]
    if not cong_cu:
        cmd += ["--tools", ""]
    if he_thong:
        cmd += ["--system-prompt", he_thong]
    if model:
        cmd += ["--model", model]
    if phien:
        cmd += ["--resume", phien]
    env = {k: v for k, v in os.environ.items() if k not in _ENV_BO}
    try:
        r = subprocess.run(cmd, input=cau_hoi, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(thu_muc or Path.home()), env=env, timeout=thoi_gian, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ClaudeLoi(f"Claude không trả lời trong {thoi_gian:.0f}s.") from None
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise ClaudeLoi((r.stderr or r.stdout or f"claude thoát mã {r.returncode}").strip()[:2000]) from None
    if r.returncode != 0 or d.get("is_error"):
        raise ClaudeLoi(str(d.get("result") or r.stderr or f"claude thoát mã {r.returncode}").strip()[:2000])
    model_thuc = next(iter(d.get("modelUsage") or {}), "")
    return TraLoi(text=str(d.get("result") or "").strip(), session_id=str(d.get("session_id") or ""),
                  model=model_thuc, cost_usd=float(d.get("total_cost_usd") or 0), raw=d)


class Phien:
    """Hội thoại nhiều lượt: mỗi lần .hoi() tự nối tiếp phiên trước (Claude nhớ những gì đã nói)."""

    def __init__(self, he_thong: str | None = None, model: str | None = None, cong_cu: bool = False,
                 thu_muc: str | Path | None = None):
        self.he_thong, self.model, self.cong_cu, self.thu_muc = he_thong, model, cong_cu, thu_muc
        self.session_id: str | None = None
        self.lich_su: list[TraLoi] = []

    def hoi(self, cau_hoi: str, **kw) -> str:
        r = hoi(cau_hoi, he_thong=self.he_thong, model=self.model, phien=self.session_id,
                cong_cu=self.cong_cu, thu_muc=self.thu_muc, **kw)
        self.session_id = r.session_id or self.session_id
        self.lich_su.append(r)
        return r.text

    def lam_moi(self):
        """Bắt đầu hội thoại mới (quên ngữ cảnh cũ)."""
        self.session_id, self.lich_su = None, []


# ------------------------------------------------------------------ trạng thái / đăng nhập (cho ket_noi_ai.py)
def trang_thai() -> dict:
    """{"ten","cli","cai","phien_ban","ket_noi","email","ghi_chu"} từ `claude auth status` (không mở mạng)."""
    kq = dict(ten=TEN, cli=CLI, cai=False, phien_ban="", ket_noi=False, email="", ghi_chu="")
    exe = shutil.which(CLI)
    if not exe:
        kq["ghi_chu"] = f"chưa cài Claude Code ({LENH_CAI})"
        return kq
    kq["cai"] = True
    env = {k: v for k, v in os.environ.items() if k not in _ENV_BO}
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, env=env, creationflags=NO_WINDOW).stdout
        kq["phien_ban"] = v.strip().split()[0] if v.strip() else ""
        st = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=30, env=env,
                            creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        d = json.loads(st.stdout[st.stdout.find("{"):]) if "{" in st.stdout else {}
        kq["ket_noi"] = bool(d.get("loggedIn"))
        kq["email"] = d.get("email") or ""
        goi = d.get("subscriptionType") or d.get("authMethod") or ""
        kq["ghi_chu"] = f"gói {goi}" if kq["ket_noi"] else "chưa đăng nhập"
    except Exception as e:                     # noqa: BLE001
        kq["ghi_chu"] = f"không hỏi được claude: {e}"
    return kq


def dang_nhap() -> None:
    """Mở cửa sổ lệnh chạy `claude auth login`: trình duyệt hiện trang đăng nhập Claude -> chọn Google."""
    env = {k: v for k, v in os.environ.items() if k not in _ENV_BO}
    subprocess.Popen(["cmd", "/k", f"chcp 65001>nul & title Ket noi Claude & {LENH_DANG_NHAP}"],
                     creationflags=NEW_CONSOLE, env=env)


def dang_xuat() -> str:
    env = {k: v for k, v in os.environ.items() if k not in _ENV_BO}
    r = subprocess.run([_claude_exe(), "auth", "logout"], capture_output=True, text=True, timeout=30, env=env,
                       creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip()


def cai_dat() -> None:
    subprocess.Popen(["cmd", "/k", f"chcp 65001>nul & title Cai Claude Code & {LENH_CAI}"], creationflags=NEW_CONSOLE)


def main():
    for s in (sys.stdout, sys.stderr):          # in tiếng Việt không lỗi cp1252
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Hỏi Claude qua Claude Code CLI (gói đang đăng nhập, không cần API key).")
    ap.add_argument("cau_hoi", nargs="*", help="câu hỏi; bỏ trống = chat nhiều lượt")
    ap.add_argument("--model", help="sonnet / opus / haiku hoặc id đầy đủ (mặc định: của CLI)")
    ap.add_argument("--he-thong", help="chỉ dẫn hệ thống, vd 'Trả lời ngắn gọn bằng tiếng Việt'")
    ap.add_argument("--cong-cu", action="store_true", help="cho Claude dùng công cụ (đọc file, chạy lệnh, web)")
    ap.add_argument("--trang-thai", action="store_true", help="chỉ in trạng thái đăng nhập")
    args = ap.parse_args()
    if args.trang_thai:
        print(json.dumps(trang_thai(), ensure_ascii=False, indent=1)); return

    p = Phien(he_thong=args.he_thong, model=args.model, cong_cu=args.cong_cu)
    if args.cau_hoi:
        try:
            print(p.hoi(" ".join(args.cau_hoi)))
        except ClaudeLoi as e:
            sys.exit(f"LỖI: {e}")
        return
    print("Chat với Claude (Enter trống để thoát, gõ /moi để bắt đầu hội thoại mới).")
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
            print(f"\nClaude: {p.hoi(cau)}")
        except ClaudeLoi as e:
            print(f"LỖI: {e}")


if __name__ == "__main__":
    main()
