# -*- coding: utf-8 -*-
"""Tìm file thực thi của các CLI AI (claude / codex / gemini) một cách bền hơn shutil.which.

Vấn đề: app mở từ shortcut Desktop nhận PATH của Explorer — có thể thiếu thư mục nvm/npm (biến
%NVM_SYMLINK% chưa mở rộng, PATH đổi sau khi đăng nhập) hoặc xếp thư mục npm cũ TRƯỚC thư mục nvm mới.
Khi đó `shutil.which("codex")` không thấy gì hoặc lấy nhầm bản cũ (bản cũ không chạy được model mới).

Cách làm: quét PATH + các thư mục npm/nvm quen thuộc, trả về mọi bản tìm được; muốn chọn bản mới nhất
thì xếp theo `--version`.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAU_COMMAND_MAC = r"""#!/bin/zsh -l
printf "\033]0;@TIEU_DE@\007"
export PATH="@PATH@:$PATH"
cd ~
if @LENH@; then
  echo; echo "✓ Xong. Cửa sổ này tự đóng sau 3 giây."; sleep 3
else
  echo; echo "✗ Có lỗi (xem ở trên). Bấm Enter để đóng cửa sổ."; read -r _
fi
touch "@MOC@"
exit 0
"""
DUOI = (".cmd", ".exe", ".bat", "")


def thu_muc_ung_vien() -> list[str]:
    """PATH của tiến trình + những chỗ npm/nvm/installer hay đặt lệnh (không trùng, giữ thứ tự)."""
    ds = [d.strip().strip('"') for d in os.environ.get("PATH", "").split(os.pathsep) if d.strip()]
    home = Path.home()
    them = [
        os.environ.get("NVM_SYMLINK", ""),                       # nvm-windows: thư mục node đang chọn
        r"C:\nvm4w\nodejs",
        str(home / "AppData" / "Roaming" / "npm"),               # npm prefix mặc định (bản cũ hay nằm đây)
        str(home / ".local" / "bin"),                            # claude bản native installer
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs"),
        str(home / "AppData" / "Local" / "Programs" / "claude"),
    ]
    nvm_home = os.environ.get("NVM_HOME") or str(home / "AppData" / "Local" / "nvm")
    try:                                                         # các bản node khác của nvm, mới nhất trước
        them += [str(p) for p in sorted(Path(nvm_home).glob("v*"), reverse=True) if p.is_dir()]
    except OSError:
        pass
    if os.name != "nt":                                          # macOS/Linux: Homebrew, npm global, nvm
        them += ["/opt/homebrew/bin", "/usr/local/bin", str(home / ".npm-global" / "bin")]
        for mau in (home / ".nvm" / "versions" / "node", Path("/opt/homebrew/Cellar/node")):
            try:
                them += [str(p / "bin") for p in sorted(mau.glob("*"), reverse=True) if (p / "bin").is_dir()]
            except OSError:
                pass
    thay = {d.lower() for d in ds}
    for t in them:
        if t and t.lower() not in thay:
            ds.append(t)
            thay.add(t.lower())
    return ds


def _bo_sung_path() -> None:
    """macOS/Linux: claude/codex/gemini là script `#!/usr/bin/env node` -> app mở từ Finder (PATH tối giản) vẫn
    phải thấy node, nên thêm các thư mục quen thuộc vào PATH của tiến trình (và mọi lệnh con)."""
    if os.name != "nt":
        os.environ["PATH"] = os.pathsep.join(thu_muc_ung_vien())


_bo_sung_path()


def tim_lenh(ten: str) -> list[str]:
    """Mọi file thực thi `ten` tìm được (theo thứ tự thư mục), mỗi file một lần (đã resolve symlink)."""
    kq, thay = [], set()
    for d in thu_muc_ung_vien():
        for duoi in DUOI:
            p = Path(d) / (ten + duoi)
            try:
                if not p.is_file():
                    continue
                key = str(p.resolve()).lower()
            except OSError:
                continue
            if key not in thay:
                thay.add(key)
                kq.append(str(p))
            break
    return kq


def mo_cua_so_lenh(lenh_win: str, lenh_mac: str, tieu_de: str, env: dict | None = None) -> None:
    """Mở một cửa sổ lệnh để người dùng nhìn thấy (đăng nhập / cài CLI).
    Windows: cmd /k `lenh_win` trong console mới. macOS: ghi `lenh_mac` vào file .command rồi mở bằng Terminal
    (Terminal mở shell mới nên `env` không truyền sang; biến cần thiết đặt ngay trong `lenh_mac`)."""
    if os.name == "nt":
        subprocess.Popen(["cmd", "/k", f"chcp 65001>nul & title {tieu_de} & {lenh_win}"],
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), env=env)
        return
    import tempfile
    import threading
    them_path = ":".join(d for d in thu_muc_ung_vien() if d)
    fd, duong_dan = tempfile.mkstemp(prefix="ghep_video_", suffix=".command")
    moc = duong_dan + ".xong"                                    # .command chạm file này khi xong -> app đóng cửa sổ Terminal
    noi_dung = (MAU_COMMAND_MAC.replace("@TIEU_DE@", tieu_de).replace("@PATH@", them_path)
                .replace("@LENH@", lenh_mac).replace("@MOC@", moc))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(noi_dung)
    os.chmod(duong_dan, 0o755)
    subprocess.Popen(["open", "-a", "Terminal", duong_dan])

    def _dong_cua_so():
        """Chờ .command báo xong (tối đa 30 phút) rồi đóng cửa sổ Terminal có tiêu đề đó (shell đã thoát nên không hỏi gì)."""
        import time
        het = time.time() + 1800
        while time.time() < het and not os.path.exists(moc):
            time.sleep(0.5)
        if os.path.exists(moc):
            time.sleep(0.7)
            q = tieu_de.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'tell application "Terminal" to close (every window whose name contains "{q}")'],
                           capture_output=True, timeout=30)
        for f_ in (moc, duong_dan):
            try:
                os.remove(f_)
            except OSError:
                pass

    threading.Thread(target=_dong_cua_so, daemon=True, name="dong-terminal").start()


def phien_ban(exe: str) -> tuple:
    """(2, 1, 233) từ `<exe> --version`; không đọc được -> (0,)."""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW,
                             encoding="utf-8", errors="replace").stdout.strip()
        so = re.findall(r"\d+", out.splitlines()[-1] if out else "")
        return tuple(int(x) for x in so[:3]) or (0,)
    except Exception:
        return (0,)


_CACHE: dict = {}


def tim_lenh_moi_nhat(ten: str) -> list[tuple[str, tuple]]:
    """[(exe, phiên bản)] bản mới nhất trước; nhớ theo PATH (chạy --version mỗi bản một lần)."""
    ky = (ten, os.environ.get("PATH", ""))
    if _CACHE.get(ky) is not None:
        return _CACHE[ky]
    ds = [(p, phien_ban(p)) for p in tim_lenh(ten)]
    ds.sort(key=lambda t: t[1], reverse=True)
    _CACHE[ky] = ds
    return ds


def chuoi_phien_ban(v: tuple) -> str:
    return ".".join(map(str, v)) if v and v != (0,) else ""


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for ten in sys.argv[1:] or ("claude", "codex", "gemini"):
        print(ten, tim_lenh_moi_nhat(ten))
