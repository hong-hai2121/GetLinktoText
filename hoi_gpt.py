# -*- coding: utf-8 -*-
"""Hỏi GPT từ code Python qua Codex CLI (`codex exec`), dùng tài khoản ChatGPT đang đăng nhập
trên máy — KHÔNG cần API key OpenAI (tính vào hạn mức gói ChatGPT).

Dùng trong code (giống hoi_claude.py):
    from hoi_gpt import hoi, Phien
    print(hoi("Thủ đô Việt Nam là gì?").text)
    p = Phien(he_thong="Trả lời ngắn gọn bằng tiếng Việt.")
    print(p.hoi("Tôi tên Hải.")); print(p.hoi("Tôi tên gì?"))

Dòng lệnh: python hoi_gpt.py "câu hỏi"   |   python hoi_gpt.py  (chat nhiều lượt)

Cách chạy bên dưới: `codex exec --skip-git-repo-check -s read-only -C <thư mục> --json [-m model]`,
câu hỏi đưa qua stdin; hỏi tiếp = `codex exec resume <thread_id> - ...` (stdin). `--json` in từng dòng
JSON (thread.started / item.completed agent_message / turn.completed / error). Codex không có
"system prompt" riêng nên `he_thong` được ghép vào đầu câu hỏi lượt đầu.
Sandbox read-only: GPT chỉ đọc được file trong thư mục làm việc, không ghi/không chạy lệnh.
Yêu cầu: Codex CLI >= 0.163 (`npm install -g @openai/codex@latest`) và đã `codex login` bằng ChatGPT.
"""
from __future__ import annotations

import argparse
import base64
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

TEN = "GPT"
CLI = "codex"
LENH_CAI = "npm install -g @openai/codex@latest"
LENH_DANG_NHAP = "codex login"              # mở trình duyệt, chọn "Continue with Google" (hoặc cách khác)
LENH_DANG_XUAT = "codex logout"
THOI_GIAN_CHO = 600
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GptLoi(RuntimeError):
    """Không gọi được codex, hoặc codex trả lỗi (chưa đăng nhập, model không hợp, hết hạn mức...)."""


@dataclass
class TraLoi:
    text: str
    session_id: str            # thread_id của Codex -> hỏi tiếp cùng ngữ cảnh
    model: str = ""
    cost_usd: float = 0.0      # Codex không báo tiền; để cùng khuôn với hoi_claude
    raw: dict = field(default_factory=dict, repr=False)   # {"events": [...], "usage": {...}}

    def __str__(self) -> str:
        return self.text


def cac_ban_codex() -> list[tuple[str, tuple]]:
    """Mọi bản codex tìm được (PATH + thư mục npm/nvm quen thuộc) kèm phiên bản, bản MỚI NHẤT trước.
    Máy có thể còn bản cũ ở %APPDATA%\\npm đứng trước bản mới (nvm) trong PATH của Explorer -> shutil.which
    lấy nhầm bản cũ, bản cũ lại không chạy được model mới của tài khoản ("requires a newer version of Codex")."""
    return cli_chung.tim_lenh_moi_nhat(CLI)


def _exe() -> str:
    ds = cac_ban_codex()
    if not ds:
        raise GptLoi(f"Không tìm thấy lệnh `{CLI}` trên PATH. Cài bằng: {LENH_CAI}")
    return ds[0][0]


def _chay(args: list[str], stdin: str, thoi_gian: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=thoi_gian, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise GptLoi(f"GPT không trả lời trong {thoi_gian:.0f}s.") from None


def hoi(cau_hoi: str, *, he_thong: str | None = None, model: str | None = None, phien: str | None = None,
        thu_muc: str | Path | None = None, thoi_gian: float = THOI_GIAN_CHO) -> TraLoi:
    """Gửi một câu hỏi, trả về TraLoi. `phien` = session_id lượt trước để hỏi tiếp.
    `model`: vd "gpt-6-astra"; None = model mặc định trong ~/.codex/config.toml."""
    exe = _exe()
    chung = ["--skip-git-repo-check", "--json"] + (["-m", model] if model else [])
    if phien:
        # resume không nhận -s/-C: sandbox + thư mục lấy theo phiên cũ; "-" = đọc câu hỏi từ stdin
        cmd = [exe, "exec", "resume", *chung, phien, "-"]
        noi_dung = cau_hoi
    else:
        cmd = [exe, "exec", *chung, "-s", "read-only", "-C", str(thu_muc or Path.home())]
        noi_dung = (f"{he_thong.strip()}\n\n{cau_hoi}" if he_thong else cau_hoi)
    r = _chay(cmd, noi_dung, thoi_gian)
    events, text, thread_id, loi, usage = [], "", "", "", {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        events.append(ev)
        t = ev.get("type")
        if t == "thread.started":
            thread_id = ev.get("thread_id", "")
        elif t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
            text = ev["item"].get("text", "")
        elif t == "turn.completed":
            usage = ev.get("usage") or {}
        elif t in ("error", "turn.failed"):
            loi = ev.get("message") or (ev.get("error") or {}).get("message") or loi
    if not text:
        chi_tiet = loi or next((l for l in r.stderr.splitlines() if "ERROR" in l or "error" in l.lower()), "") \
            or r.stderr.strip()[-600:] or f"codex thoát mã {r.returncode}"
        if "model is not supported" in chi_tiet or "requires a newer version" in chi_tiet:
            chi_tiet += f"  -> thử model khác (-m) hoặc cập nhật: {LENH_CAI}"
        raise GptLoi(chi_tiet.strip()[:2000])
    return TraLoi(text=text.strip(), session_id=thread_id or (phien or ""), model=model or _model_mac_dinh(),
                  raw={"events": events, "usage": usage})


def danh_sach_model() -> list[dict]:
    """[{"id","ten"}] model tài khoản ChatGPT dùng được — đọc ~/.codex/models_cache.json (Codex tự tải lại
    mỗi lần chạy nên luôn mới); model mặc định trong config.toml đứng đầu."""
    kq = []
    try:
        d = json.loads((Path.home() / ".codex" / "models_cache.json").read_text(encoding="utf-8"))
        ms = [m for m in d.get("models", []) if m.get("slug") and m.get("visibility", "list") == "list"]
        ms.sort(key=lambda m: m.get("priority", 99))
        kq = [{"id": m["slug"], "ten": m.get("display_name") or m["slug"]} for m in ms]
    except Exception:
        pass
    md = _model_mac_dinh()
    if md:
        kq = [{"id": md, "ten": f"{md} (mặc định config)"}] + [m for m in kq if m["id"] != md]
    return kq


def _model_mac_dinh() -> str:
    try:
        for line in (Path.home() / ".codex" / "config.toml").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("model") and "=" in line and not line.strip().startswith("model_"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


class Phien:
    """Hội thoại nhiều lượt (Codex nhớ ngữ cảnh qua thread_id)."""

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


# ------------------------------------------------------------------ trạng thái / đăng nhập (cho ket_noi_ai.py)
def _email_tu_auth_json() -> tuple[str, str]:
    """(email, loại gói) đọc từ id_token trong ~/.codex/auth.json (giải mã tại chỗ, không gọi mạng)."""
    try:
        d = json.loads((Path.home() / ".codex" / "auth.json").read_text(encoding="utf-8"))
        idt = (d.get("tokens") or {}).get("id_token") or ""
        p = idt.split(".")[1]
        p += "=" * (-len(p) % 4)
        c = json.loads(base64.urlsafe_b64decode(p))
        return c.get("email") or "", (c.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type") or ""
    except Exception:
        return "", ""


def trang_thai() -> dict:
    """{"ten","cli","cai","phien_ban","ket_noi","email","ghi_chu"} — không mở mạng, chỉ hỏi CLI tại chỗ."""
    kq = dict(ten=TEN, cli=CLI, cai=False, phien_ban="", ket_noi=False, email="", ghi_chu="", duong_dan="")
    ds = cac_ban_codex()
    if not ds:
        kq["ghi_chu"] = f"chưa cài Codex CLI ({LENH_CAI})"
        return kq
    exe, ver = ds[0]
    kq["cai"] = True
    kq["duong_dan"] = exe
    kq["phien_ban"] = cli_chung.chuoi_phien_ban(ver)
    if len(ds) > 1:
        kq["ghi_chu_them"] = "bỏ qua bản cũ: " + ", ".join(f"{Path(p).parent} ({cli_chung.chuoi_phien_ban(v)})" for p, v in ds[1:])
    try:
        st = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=20,
                            creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        dong = (st.stdout + st.stderr).strip().splitlines()
        dong = dong[-1] if dong else ""
        kq["ket_noi"] = "logged in" in dong.lower() and "not logged" not in dong.lower()
        kq["ghi_chu"] = dong
    except Exception as e:                     # noqa: BLE001
        kq["ghi_chu"] = f"không hỏi được codex: {e}"
    if kq["ket_noi"]:
        email, goi = _email_tu_auth_json()
        kq["email"] = email
        if goi:
            kq["ghi_chu"] = f"ChatGPT gói {goi}"
    if kq.pop("ghi_chu_them", ""):
        kq["ghi_chu"] = (kq["ghi_chu"] + " · " if kq["ghi_chu"] else "") + f"dùng bản {kq['phien_ban']} ở {Path(exe).parent}"
    return kq


def dang_nhap() -> None:
    """Mở cửa sổ lệnh chạy `codex login`: trình duyệt hiện trang đăng nhập ChatGPT -> chọn Google."""
    cli_chung.mo_cua_so_lenh(LENH_DANG_NHAP, LENH_DANG_NHAP, "Ket noi GPT (Codex)")


def dang_xuat() -> str:
    r = subprocess.run([_exe(), "logout"], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW,
                       encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip()


def cai_dat() -> None:
    cli_chung.mo_cua_so_lenh(LENH_CAI, LENH_CAI, "Cai Codex CLI")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Hỏi GPT qua Codex CLI (tài khoản ChatGPT đang đăng nhập).")
    ap.add_argument("cau_hoi", nargs="*", help="câu hỏi; bỏ trống = chat nhiều lượt")
    ap.add_argument("--model", help="vd gpt-6-astra (mặc định: model trong ~/.codex/config.toml)")
    ap.add_argument("--he-thong", help="chỉ dẫn chung, ghép vào đầu câu hỏi lượt đầu")
    ap.add_argument("--trang-thai", action="store_true", help="chỉ in trạng thái đăng nhập")
    args = ap.parse_args()
    if args.trang_thai:
        print(json.dumps(trang_thai(), ensure_ascii=False, indent=1)); return
    p = Phien(he_thong=args.he_thong, model=args.model)
    if args.cau_hoi:
        try:
            print(p.hoi(" ".join(args.cau_hoi)))
        except GptLoi as e:
            sys.exit(f"LỖI: {e}")
        return
    print("Chat với GPT (Enter trống để thoát, /moi = hội thoại mới).")
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
            print(f"\nGPT: {p.hoi(cau)}")
        except GptLoi as e:
            print(f"LỖI: {e}")


if __name__ == "__main__":
    main()
