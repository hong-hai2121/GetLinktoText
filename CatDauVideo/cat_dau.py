# -*- coding: utf-8 -*-
"""Cắt đoạn đọc tiêu đề bị lặp ở đầu video (user 11/11/2026).

Video của Sheet "Kich Bản BS Hội Tiêu Hóa" mở đầu bằng câu tiêu đề (cột B) đọc SAI tiếng Việt, nghỉ một nhịp rồi mới đọc
kịch bản (cột C — tự nó cũng mở đầu bằng câu tiêu đề, lần này đọc chuẩn). Tool bỏ lần đọc sai để câu đầu tiên là kịch bản:

  1. Đọc tab Sheet qua đường xuất CSV công khai. Cột tìm theo TÊN ở dòng 1: "Tiêu đề", "Nội dung kịch bản", "Link Đăng"
     (không thấy tên thì lấy B, C, F).
  2. Tải file ở cột Link Đăng về <Downloads>\\CatDauVideo\\<tên Sheet - tên tab>\\goc\\ (đã tải đủ dung lượng thì dùng lại).
  3. Nghe 20 giây đầu bằng faster-whisper large-v3-turbo (mốc từng từ), tìm chỗ lời nói khớp phần MỞ ĐẦU CỘT C nhất. Cửa sổ
     so khớp dài hơn tiêu đề 12 từ nên lần đọc sai (theo sau là tiêu đề lần hai chứ không phải nội dung) luôn thua điểm.
     Mọi thứ trước chỗ khớp là đoạn cần bỏ. Mốc cắt dời vào khoảng lặng ngay trước từ đầu tiên, chừa 0,2 giây lấy hơi.
  4. Render lại từ mốc cắt tới hết (GPU NVENC -> Quick Sync -> AMF -> CPU libx264, tiếng AAC, mờ dần 0,04 giây chống tiếng
     "bụp") ra "<tên tải về> v2.mp4" ngay trong thư mục tab; bản gốc nằm nguyên trong goc\\.
  5. Nghe lại 8 giây đầu của bản v2: câu đầu phải khớp phần mở đầu cột C, không thì đánh dấu ⚠ để nghe lại.
  6. Ghi bao_cao_<ngày giờ>.txt: dòng -> link -> mốc cắt -> đoạn bị bỏ -> câu đầu mới. so_tay.json nhớ link nào đã làm.

Không cắt mà chỉ báo "cần xem lại" khi: lời nói không khớp kịch bản (điểm < 72), hoặc đoạn phải bỏ dài bất thường.
Video không có đoạn lặp (kịch bản bắt đầu trong 0,5 giây đầu) thì bỏ qua, không tạo v2.

Có giao diện: bấm đúp chay.bat (giao_dien.py — bảng các dòng của Sheet, tick dòng cần chạy, nút làm thử một dòng, khung
xem lại video, nút tải bản v2 lên Drive).
Tải lên Drive (len_drive.py): bản v2 vào thư mục ở cột "Link video" (E) của dòng, link mới ghi vào cột H.

Chạy bằng dòng lệnh:
  python cat_dau.py                          hỏi link Sheet (Enter = link lần trước) rồi hỏi chạy dòng nào
  python cat_dau.py --dong 2-6,9             dòng theo số dòng trên Sheet (dòng 1 là tiêu đề cột)
  python cat_dau.py --dong tat-ca            mọi dòng có link
  python cat_dau.py --sheet "<link tab>" --dong 2 --chi-xem     chỉ tải + dò mốc cắt, không render
  thêm: --lam-lai (làm lại dòng đã có v2) · --giay 20 · --out <thư mục> · --cpu (không dùng GPU cho nhận diện)
        --tai-len (cắt xong tải bản v2 lên Drive + ghi cột H; dòng có cảnh báo thì không tự tải)
"""
import argparse
import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
SHEET_MAC_DINH = ("https://docs.google.com/spreadsheets/d/1J1n-v3xuXMvFKWPxat4bQpWFnPb0V6qDyL7NK88hoq8/"
                  "edit?gid=440048821#gid=440048821")
FILE_CAU_HINH = HERE / "cau_hinh.json"           # nhớ link Sheet lần trước
MODEL = "large-v3-turbo"                         # user chốt: KHÔNG hạ model nhỏ hơn
THU_MUC_MODEL = [HERE / "models", HERE.parent / "GetTextFromLink" / "whisper_cache"]

GIAY_NGHE = 20.0            # nghe bấy nhiêu giây đầu để tìm mốc cắt
GIAY_NGHE_THEM = 40.0       # 20 giây chưa đủ khớp -> nghe rộng ra
GIAY_KIEM_TRA = 8.0         # nghe lại đầu bản v2
SO_TU_SAU_TIEU_DE = 12      # cửa sổ so khớp = số từ tiêu đề + bấy nhiêu từ nội dung
DIEM_KHOP = 72              # điểm (0-100) tối thiểu để tin chỗ khớp
KHONG_CAT_DUOI = 0.5        # kịch bản bắt đầu sớm hơn mốc này -> không có đoạn lặp
CHUA_LAY_HOI = 0.20         # chừa bấy nhiêu giây lặng trước từ đầu tiên (0,12 dễ phạm hơi lấy đầu câu)
LANG_TOI_THIEU = 0.12       # khoảng lặng ngắn hơn thì không coi là chỗ nghỉ giữa hai lần đọc
KHONG_THAY_LANG = "mốc từ của Whisper (không thấy khoảng lặng rõ)"
GIAY_NGHE_LAI = 9.0         # nghe riêng từ một chỗ nghỉ: đủ dài để gồm cả câu tiêu đề lẫn vài từ nội dung
CAT_TOI_DA = 12.5           # không tìm lần đọc chuẩn bắt đầu muộn hơn mốc này
DIEM_MO_DAU = 80            # 5 từ đầu của đoạn nghe lại phải khớp 5 từ đầu kịch bản (chống cắt vào giữa câu tiêu đề)
BAM_LANG_TAY = 0.8          # cắt tay: giây người dùng chỉ được bám vào khoảng lặng cách nó không quá chừng này
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_ENC_CACHE = {}
_model = {}


def log(*a):
    print(*a, flush=True)


def buoc(ten: str):
    """Báo bước đang làm của dòng hiện tại. Dòng lệnh không cần; giao_dien.py gán hàm khác vào đây để hiện lên bảng."""


# ---------------------------------------------------------------- tiện ích chung
def downloads_dir() -> Path:
    """Thư mục Downloads thật (user có thể đã dời), fallback ~/Downloads."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
        p = Path(val)
        if p.is_dir():
            return p
    except Exception:
        pass
    return Path.home() / "Downloads"


def ten_an_toan(ten: str, toi_da: int = 150) -> str:
    """Bỏ ký tự Windows cấm trong tên file/thư mục (giống trình duyệt đổi thành _)."""
    s = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in ten).strip(" .")
    return (s[:toi_da].rstrip(" .") or "video")


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    stem, ext, i = p.stem, p.suffix, 1
    while p.exists():
        p = folder / f"{stem} ({i}){ext}"
        i += 1
    return p


def bo_dau(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def chuan(s: str) -> list[str]:
    """Chữ thường, bỏ dấu, bỏ dấu câu -> danh sách từ (để so khớp chịu được lỗi dấu của Whisper)."""
    return re.findall(r"[a-z0-9]+", bo_dau(s))


def _exe(ten: str) -> str:
    p = shutil.which(ten)
    if not p:
        raise RuntimeError(f"Chưa cài {ten} (cần ffmpeg để nghe và render video).")
    return p


def _ten_tu_header(cd: str) -> str | None:
    """Tên file từ Content-Disposition. requests giải mã header theo latin-1 nên tên tiếng Việt UTF-8 phải giải lại."""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I)
    if m:
        return requests.utils.unquote(m.group(1))
    m = re.search(r'filename="([^"]+)"', cd)
    if not m:
        return None
    raw = m.group(1)
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


# ---------------------------------------------------------------- Sheet
@dataclass
class Dong:
    dong: int           # số dòng trên Sheet (dòng 1 = tiêu đề cột)
    stt: str
    tieu_de: str
    kich_ban: str
    link: str
    thu_muc_drive: str = ""     # cột "Link video" (E): thư mục Drive của dòng, nơi tải bản v2 lên (len_drive.py)
    link_v2: str = ""           # cột H: link bản v2 đã tải lên, nếu có


def doc_sheet(link: str) -> tuple[str, list[Dong]]:
    """-> (tên bộ "<Sheet> - <tab>", các dòng có link ở cột Link Đăng)."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", link)
    if not m:
        raise ValueError(f"Không nhận ra link Google Sheet: {link}")
    gid = re.search(r"[#&?]gid=(\d+)", link)
    gid = gid.group(1) if gid else "0"
    url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"
    r = requests.get(url, timeout=60)
    if r.status_code != 200 or "text/csv" not in r.headers.get("Content-Type", ""):
        raise RuntimeError("Không đọc được Sheet — bật chia sẻ 'Bất kỳ ai có đường liên kết: Người xem' cho Sheet rồi chạy lại "
                           f"(HTTP {r.status_code}).")
    ten = _ten_tu_header(r.headers.get("Content-Disposition", "")) or f"sheet_{m.group(1)[:8]}_{gid}.csv"
    ten_bo = ten_an_toan(re.sub(r"\.csv$", "", ten, flags=re.I), 80)
    bang = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))
    if not bang:
        return ten_bo, []
    dau = [" ".join(chuan(c)) for c in bang[0]]

    def cot(tu_khoa: str, mac_dinh: int) -> int:
        return next((i for i, c in enumerate(dau) if tu_khoa in c), mac_dinh)

    i_stt, i_td, i_kb, i_link = cot("stt", 0), cot("tieu de", 1), cot("noi dung", 2), cot("link dang", 5)
    i_tm, i_v2 = cot("link video", 4), 7        # E = thư mục Drive của dòng · H = link bản v2 đã tải lên
    out = []
    for n, row in enumerate(bang[1:], start=2):
        o = lambda i: row[i].strip() if i < len(row) else ""       # noqa: E731
        if "drive.google.com" in o(i_link) or "drive.usercontent.google.com" in o(i_link):
            out.append(Dong(n, o(i_stt), o(i_td), o(i_kb), o(i_link), o(i_tm), o(i_v2) if o(i_v2).startswith("http") else ""))
    return ten_bo, out


def chon_dong(spec: str, ds: list[Dong]) -> list[Dong]:
    """'2-6,9' -> các dòng đó (theo số dòng Sheet); 'tat-ca' / 'all' / '*' -> mọi dòng có link."""
    s = " ".join(chuan(spec))
    if s in ("tat ca", "tatca", "all", "het") or spec.strip() == "*":
        return list(ds)
    muon = set()
    for phan in re.split(r"[,;\s]+", spec.strip()):
        if not phan:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", phan)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            muon.update(range(min(a, b), max(a, b) + 1))
        elif phan.isdigit():
            muon.add(int(phan))
        else:
            raise ValueError(f"Không hiểu '{phan}' — ghi kiểu 2-6,9 hoặc tat-ca.")
    return [d for d in ds if d.dong in muon]


# ---------------------------------------------------------------- Drive
def id_drive(url: str) -> str | None:
    for p in (r"/file/d/([A-Za-z0-9_-]{20,})", r"[?&]id=([A-Za-z0-9_-]{20,})", r"^([A-Za-z0-9_-]{20,})$"):
        m = re.search(p, url.strip())
        if m:
            return m.group(1)
    return None


def tai_drive(fid: str, thu_muc: Path, ten_cu: str | None = None) -> Path:
    """Tải file Drive (chia sẻ công khai) về thu_muc, giữ tên trên Drive. File cùng tên đã đủ dung lượng thì dùng lại.
    ten_cu = tên đã ghi trong sổ tay cho đúng file-id này (tránh nhầm hai file Drive trùng tên)."""
    thu_muc.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    url = "https://drive.usercontent.google.com/download"
    r = sess.get(url, params={"id": fid, "export": "download", "confirm": "t"}, stream=True, timeout=60)
    r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type", ""):
        # trang xác nhận (file lớn chưa quét virus) hoặc file không công khai / Drive tạm chặn tải
        an = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', r.text))
        r.close()
        if not an:
            raise RuntimeError("Drive không cho tải — kiểm tra file đã bật chia sẻ 'Bất kỳ ai có đường liên kết' chưa, "
                               "hoặc Drive đang tạm chặn vì tải quá nhiều (đợi rồi chạy lại).")
        r = sess.get(url, params=an, stream=True, timeout=60)
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", ""):
            r.close()
            raise RuntimeError("Drive vẫn trả về trang web thay vì file — link có thể cần đăng nhập.")
    ten = ten_an_toan(_ten_tu_header(r.headers.get("Content-Disposition", "")) or f"drive_{fid}.mp4")
    tong = int(r.headers.get("Content-Length") or 0)
    dich = thu_muc / (ten_cu or ten)
    if dich.is_file() and tong and dich.stat().st_size == tong:
        r.close()
        log(f"  Đã tải sẵn: {dich.name} ({tong / 1048576:.1f} MB)")
        return dich
    if ten_cu is None and dich.exists():
        dich = unique_path(thu_muc, ten)        # tên trùng với file của link khác -> không đè
    tam = dich.with_name(dich.name + ".part")
    xong, moc = 0, time.time()
    with open(tam, "wb") as f:
        for khuc in r.iter_content(chunk_size=1024 * 512):
            if not khuc:
                continue
            f.write(khuc)
            xong += len(khuc)
            if time.time() - moc > 4:
                log(f"    ... {xong / 1048576:.0f}/{tong / 1048576:.0f} MB" if tong else f"    ... {xong / 1048576:.0f} MB")
                moc = time.time()
    if tong and xong != tong:
        tam.unlink(missing_ok=True)
        raise RuntimeError(f"Tải dở dang ({xong}/{tong} byte) — chạy lại.")
    tam.replace(dich)
    log(f"  Đã tải: {dich.name} ({xong / 1048576:.1f} MB)")
    return dich


# ---------------------------------------------------------------- nghe
@dataclass
class Tu:
    chu: str
    dau: float
    cuoi: float


def thong_tin(path: Path) -> dict | None:
    try:
        out = subprocess.run([_exe("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                             capture_output=True, timeout=120, creationflags=_FLAGS).stdout
        d = json.loads(out.decode("utf-8", "replace") or "{}")
    except Exception:
        return None
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = d.get("format") or {}
    try:
        giay = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        giay = 0.0
    if v is None or giay <= 0:
        return None
    try:
        tu_so, mau_so = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
        fps = float(tu_so) / float(mau_so)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    try:
        kbps = int(float(v.get("bit_rate") or fmt.get("bit_rate") or 0) / 1000)
    except (TypeError, ValueError):
        kbps = 0
    return {"vcodec": v.get("codec_name"), "acodec": a.get("codec_name") if a else None, "width": v.get("width"),
            "height": v.get("height"), "giay": giay, "fps": fps if 1 <= fps <= 240 else 30.0, "kbps": kbps}


def doc_am_thanh(path: Path, giay: float) -> np.ndarray:
    """`giay` giây đầu, mono 16 kHz float32. Hai kênh NGƯỢC PHA (trộn mono triệt tiêu giọng) thì lấy kênh to hơn."""
    raw = subprocess.run([_exe("ffmpeg"), "-v", "error", "-t", f"{giay:.2f}", "-i", str(path), "-vn", "-ac", "2", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, timeout=300, creationflags=_FLAGS).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    if a.size < 16000:
        raise RuntimeError(f"Không đọc được âm thanh của {path.name} (video không có tiếng?).")
    st = a[: a.size // 2 * 2].reshape(-1, 2)
    trai, phai = st[:, 0], st[:, 1]
    mono = (trai + phai) / 2
    rms = lambda x: float(np.sqrt(np.mean(np.square(x))))        # noqa: E731
    r_t, r_p = rms(trai), rms(phai)
    if max(r_t, r_p) > 0.01 and rms(mono) < 0.5 * max(r_t, r_p):
        log("  ⚠ Âm thanh hai kênh ngược pha -> nghe bằng kênh to hơn.")
        mono = trai if r_t >= r_p else phai
    return np.ascontiguousarray(mono, dtype=np.float32)


def nap_model(cpu: bool = False):
    """Model giữ suốt phiên, không del (ctranslate2 có thể abort khi hủy model GPU)."""
    khoa = "cpu" if cpu else "auto"
    if khoa in _model:
        return _model[khoa]
    import ctranslate2
    from faster_whisper import WhisperModel
    gpu = (not cpu) and ctranslate2.get_cuda_device_count() > 0
    device, ctype = ("cuda", "float16") if gpu else ("cpu", "int8")
    root = next((d for d in THU_MUC_MODEL if d.is_dir()), None)
    log(f"Nạp model {MODEL} ({'GPU' if gpu else 'CPU'} {ctype})...")
    t0 = time.time()
    m = WhisperModel(MODEL, device=device, compute_type=ctype, download_root=str(root) if root else None)
    log(f"  model sẵn sàng sau {time.time() - t0:.1f}s")
    _model[khoa] = (m, gpu)
    return _model[khoa]


def nghe(am_thanh: np.ndarray, cpu: bool = False) -> list[Tu]:
    """Lời nói -> danh sách từ kèm mốc. GPU lỗi giữa chừng (driver treo) thì chạy lại bằng CPU."""
    def chay(m):
        segs, _ = m.transcribe(am_thanh, language="vi", beam_size=5, vad_filter=True, word_timestamps=True,
                               vad_parameters=dict(min_silence_duration_ms=300), condition_on_previous_text=False)
        return [Tu(w.word.strip(), float(w.start), float(w.end)) for s in segs for w in (s.words or []) if w.word.strip()]

    m, gpu = nap_model(cpu)
    try:
        return chay(m)
    except Exception as e:      # noqa: BLE001
        if not gpu:
            raise
        log(f"  ⚠ Nhận diện bằng GPU lỗi ({str(e)[:80]}) -> chạy lại bằng CPU.")
        return chay(nap_model(cpu=True)[0])


def tim_bat_dau(tu: list[Tu], kich_ban: str, tieu_de: str) -> dict | None:
    """Tìm từ (chỉ số j trong `tu`) mà từ đó lời nói khớp phần mở đầu kịch bản nhất. -> {j, diem, so_tu} hoặc None."""
    from rapidfuzz import fuzz
    kb = chuan(kich_ban)
    if len(kb) < 4:
        return None
    L = min(len(kb), max(len(chuan(tieu_de)) + SO_TU_SAU_TIEU_DE, 20))
    phang, dau_tu = [], {}              # từ đã chuẩn hóa nối phẳng; vị trí phẳng -> chỉ số từ Whisper
    for j, w in enumerate(tu):
        ts = chuan(w.chu)
        if ts:
            dau_tu[len(phang)] = j
            phang += ts
    tot = None
    for p, j in dau_tu.items():
        n = min(L, len(phang) - p)
        if n < min(L, 8):
            continue
        diem = fuzz.ratio(" ".join(kb[:n]), " ".join(phang[p:p + n]))
        if tot is None or diem > tot["diem"]:
            tot = {"j": j, "diem": float(diem), "so_tu": n}
    return tot


def tim_lan_doc_sau(am: np.ndarray, lang: list[tuple[float, float]], sau_giay: float, kich_ban: str, tieu_de: str,
                    cpu: bool = False) -> dict | None:
    """Whisper hay GỘP hai lần đọc giống nhau thành một: nó chép câu tiêu đề đúng một lần, đặt mốc ở lần đọc SAI rồi bỏ
    hẳn lần đọc chuẩn (gặp 11/11/2026, dòng 18 "mướp đắng": chữ nằm ở 0,0–4,7s, lần đọc chuẩn 5,3–8,2s không có chữ nào).
    Lúc đó bản chép khớp kịch bản ngay từ đầu video nên trông như không có đoạn lặp.
    Cách dò: nghe RIÊNG từ từng chỗ nghỉ phía sau `sau_giay` (máy không thấy phần trước nên không gộp được). Chỗ nghỉ muộn
    nhất mà lời ngay sau nó mở đầu đúng như kịch bản chính là nơi lần đọc chuẩn bắt đầu.
    -> {lang: (đầu, cuối khoảng lặng), tu: từ nghe lại (mốc theo video), diem} hoặc None."""
    from rapidfuzz import fuzz
    kb = chuan(kich_ban)
    L = min(len(kb), max(len(chuan(tieu_de)) + SO_TU_SAU_TIEU_DE, 20))
    for d, c in sorted(lang, key=lambda x: -x[1]):
        if c - d < LANG_TOI_THIEU or c <= sau_giay + 1.0 or c > CAT_TOI_DA:
            continue
        t0 = max(c - 0.25, d)
        doan = am[int(t0 * 16000): int((t0 + GIAY_NGHE_LAI) * 16000)]
        if len(doan) < 16000 * 3:
            continue
        tu2 = [Tu(w.chu, w.dau + t0, w.cuoi + t0) for w in nghe(doan, cpu)]
        p = [t for w in tu2 for t in chuan(w.chu)]
        n = min(L, len(p))
        if n < min(L, 8) or tu2[0].dau > c + 0.6:        # nghe ra quá ít, hoặc lời không bắt đầu ngay sau chỗ nghỉ
            continue
        diem = float(fuzz.ratio(" ".join(kb[:n]), " ".join(p[:n])))
        dau = float(fuzz.ratio(" ".join(kb[:5]), " ".join(p[:5])))
        if diem >= DIEM_KHOP and dau >= DIEM_MO_DAU:
            return {"lang": (d, c), "tu": tu2, "diem": diem}
    return None


def khoang_lang(am_thanh: np.ndarray, sr: int = 16000) -> list[tuple[float, float]]:
    """Các khoảng lặng (giây) theo năng lượng từng khung 10 ms; ngưỡng = 6% mức nói to (p95, cỡ -35 dB), sàn 0,003."""
    n = sr // 100
    k = len(am_thanh) // n
    if k < 10:
        return []
    rms = np.sqrt(np.mean(np.square(am_thanh[: k * n].reshape(k, n)), axis=1))
    lang = rms < max(0.003, 0.06 * float(np.percentile(rms, 95)))
    out, bat = [], None
    for i, x in enumerate(lang):
        if x and bat is None:
            bat = i
        elif not x and bat is not None:
            out.append((bat / 100, i / 100))
            bat = None
    if bat is not None:
        out.append((bat / 100, k / 100))
    return out


def moc_cat(tu: list[Tu], j: int, lang: list[tuple[float, float]]) -> tuple[float, str]:
    """Mốc cắt cho từ đầu tiên tu[j]: trong khoảng lặng dài nhất kết thúc quanh từ đó, chừa CHUA_LAY_HOI giây;
    không có khoảng lặng rõ (đọc dính liền / có nhạc nền) thì cắt giữa từ trước và từ này."""
    t_tu = tu[j].dau
    t_truoc = tu[j - 1].cuoi if j > 0 else 0.0
    # Whisper hay tính cả khoảng nghỉ vào từ đứng sau nó: mốc ĐẦU từ sớm hơn tiếng thật tới 0,65s (đo 11/11/2026), còn mốc
    # CUỐI từ thì đúng. Nên khoảng nghỉ giữa hai lần đọc = khoảng lặng dài nhất mà tiếng nói trở lại trước khi từ đầu tiên
    # đọc xong, và bắt đầu không muộn hơn mốc đầu từ 0,3s (loại chỗ ngắt sau từ đầu tiên kiểu "Bụng, nóng rát").
    thap, cao = min(t_truoc, t_tu) - 0.35, tu[j].cuoi + 0.05
    ung = [(c - d, d, c) for d, c in lang if c - d >= LANG_TOI_THIEU and thap <= c <= cao and d <= t_tu + 0.30]
    if ung:
        _, d, c = max(ung)
        return max(d + 0.03, c - CHUA_LAY_HOI, 0.0), f"khoảng lặng {d:.2f}–{c:.2f}s"
    t = (t_truoc + t_tu) / 2 if t_truoc < t_tu else t_tu - 0.05
    return max(min(t, t_tu), t_tu - 0.15, 0.0), KHONG_THAY_LANG


# ---------------------------------------------------------------- render
def _thu_ma_hoa(ffmpeg: str, ten: str) -> bool:
    """Encoder có trong ffmpeg VÀ mã hóa thử 0,2 giây thành công (driver GPU chạy được). Nhớ trong phiên."""
    if ten in _ENC_CACHE:
        return _ENC_CACHE[ten]
    ok = ten == "libx264"
    if not ok:
        try:
            if "danh_sach" not in _ENC_CACHE:
                _ENC_CACHE["danh_sach"] = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, timeout=30,
                                                         creationflags=_FLAGS).stdout.decode("utf-8", "replace")
            if ten in _ENC_CACHE["danh_sach"]:
                t = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2:r=30",
                                    "-c:v", ten, "-f", "null", "-"], capture_output=True, timeout=60, creationflags=_FLAGS)
                ok = t.returncode == 0
        except Exception:
            ok = False
    _ENC_CACHE[ten] = ok
    return ok


def bo_ma_hoa(kbps: int, diem_anh: int = 1080 * 1920) -> tuple:
    """(encoder, tên hiển thị, tham số) theo thứ tự ưu tiên. Chất lượng cố định, trần bitrate = 1,3 lần bản gốc (tối thiểu 4,5M)
    để bản v2 không kém bản gốc mà cũng không phình to. Đo 11/11/2026 trên video 1080x1920 gốc 3,9M: NVENC cq 25 ra 4,7M,
    SSIM 0,992 so với gốc; cq 21 ra 7,4M mà SSIM chỉ 0,994 -> chọn cq 24."""
    kbps = kbps or int(6000 * diem_anh / (1080 * 1920))      # ffprobe không cho bitrate -> ước theo độ phân giải
    tran = max(4500, int(kbps * 1.3))
    deu = max(4000, int(kbps * 1.15))
    return (
        ("h264_nvenc", "GPU NVIDIA NVENC", ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "24",
                                            "-b:v", "0", "-maxrate", f"{tran}k", "-bufsize", f"{tran * 2}k", "-profile:v", "high"]),
        ("h264_qsv", "GPU Intel Quick Sync", ["-c:v", "h264_qsv", "-preset", "medium", "-b:v", f"{deu}k", "-maxrate", f"{tran}k",
                                              "-bufsize", f"{tran * 2}k", "-profile:v", "high"]),
        ("h264_amf", "GPU AMD AMF", ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak", "-b:v", f"{deu}k",
                                     "-maxrate", f"{tran}k", "-bufsize", f"{tran * 2}k", "-profile:v", "high"]),
        ("libx264", "CPU libx264", ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", f"{tran}k",
                                    "-bufsize", f"{tran * 2}k", "-profile:v", "high"]),
    )


def render(src: Path, dst: Path, t_cat: float, tt: dict) -> str:
    """Cắt bỏ t_cat giây đầu, mã hóa lại ra dst (ghi .part rồi đổi tên). -> tên bộ mã hóa đã dùng."""
    ffmpeg = _exe("ffmpeg")
    tam = dst.with_name(dst.name + ".part")
    # lùi 2 ms: t_cat nằm đúng biên khung hình, làm tròn 3 số lẻ có thể vượt qua khung đó -> hình trễ hơn tiếng một khung
    dau = [ffmpeg, "-v", "error", "-y", "-ss", f"{max(t_cat - 0.002, 0):.4f}", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0"]
    duoi = ["-pix_fmt", "yuv420p", "-af", "afade=t=in:st=0:d=0.04", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-f", "mp4", str(tam)]
    loi = ""
    for ten, hien, tham_so in bo_ma_hoa(tt["kbps"], (tt["width"] or 1080) * (tt["height"] or 1920)):
        if not _thu_ma_hoa(ffmpeg, ten):
            continue
        r = subprocess.run(dau + tham_so + duoi, capture_output=True, timeout=max(900, int(tt["giay"] * 20)),
                           creationflags=_FLAGS)
        ra = thong_tin(tam) if r.returncode == 0 else None
        if ra and abs(ra["giay"] - (tt["giay"] - t_cat)) < 1.0:
            tam.replace(dst)
            return hien
        dong_loi = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        loi = dong_loi[-1] if dong_loi else ("file ra sai thời lượng" if ra else f"ffmpeg thoát mã {r.returncode}")
        log(f"  ⚠ {hien} lỗi ({loi[:100]}) -> thử bộ mã hóa khác.")
        _ENC_CACHE[ten] = False
    tam.unlink(missing_ok=True)
    raise RuntimeError(f"Không render được {src.name}: {loi}")


# ---------------------------------------------------------------- một dòng
def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def xu_ly(d: Dong, thu_muc: Path, so_tay: dict, args) -> dict:
    """Tải -> nghe -> cắt -> kiểm tra một dòng. Trả về bản ghi cho báo cáo; trang_thai ∈
    xong | đã có | xem thử | không có đoạn lặp | cần xem lại | lỗi."""
    kq = {"dong": d.dong, "stt": d.stt, "tieu_de": d.tieu_de, "link": d.link, "trang_thai": "lỗi", "ghi_chu": ""}
    try:
        fid = id_drive(d.link)
        if not fid or "/folders/" in d.link:
            raise RuntimeError("cột Link Đăng không phải link FILE Drive (link thư mục không dùng được).")
        cu = so_tay.get(fid) or {}
        if cu.get("v2") and (thu_muc / cu["v2"]).is_file() and not args.lam_lai:
            kq.update(trang_thai="đã có", v2=cu["v2"], goc=cu.get("goc", ""), moc_cat=cu.get("moc_cat"),
                      canh_bao=cu.get("ghi_chu", ""), link_v2=cu.get("link_v2", ""), tay=bool(cu.get("tay")),
                      ghi_chu="đã làm ở lần chạy trước (thêm --lam-lai để làm lại)")
            if "doan_bo" in cu:
                kq.update(doan_bo=cu["doan_bo"], cau_dau_v2=cu.get("cau_dau", ""))
            return kq
        buoc("tải video")
        goc = tai_drive(fid, thu_muc / "goc", cu.get("goc"))
        kq["goc"] = goc.name
        so_tay[fid] = {**cu, "goc": goc.name, "dong": d.dong}
        v2 = thu_muc / f"{goc.stem} v2.mp4"
        tt = thong_tin(goc)
        if tt is None:
            raise RuntimeError("ffprobe không đọc được video tải về.")
        if tt["acodec"] is None:
            raise RuntimeError("video không có tiếng.")

        buoc("nghe đầu video")
        tu, tim, am = [], None, None
        for giay in sorted({min(args.giay, tt["giay"]), min(max(GIAY_NGHE_THEM, args.giay), tt["giay"])}):
            am = doc_am_thanh(goc, giay)
            tu = nghe(am, args.cpu)
            tim = tim_bat_dau(tu, d.kich_ban, d.tieu_de)
            if tim and tim["diem"] >= DIEM_KHOP:
                break
            log(f"  (nghe {giay:.0f}s đầu chưa khớp kịch bản: điểm {tim['diem']:.0f})" if tim else f"  (nghe {giay:.0f}s đầu không ra đủ lời)")
        nghe_duoc = " ".join(w.chu for w in tu)
        if not tim or tim["diem"] < DIEM_KHOP:
            kq.update(trang_thai="cần xem lại", nghe_duoc=nghe_duoc[:300],
                      ghi_chu=f"lời nói không khớp phần mở đầu cột C (điểm {tim['diem']:.0f} < {DIEM_KHOP})" if tim
                      else "không nghe ra lời nói ở đầu video")
            return kq
        j = tim["j"]
        lang = khoang_lang(am)
        gop = tim_lan_doc_sau(am, lang, tu[j].dau, d.kich_ban, d.tieu_de, args.cpu)
        if gop:         # máy đã gộp hai lần đọc: chỗ khớp ở trên là lần đọc SAI, lần đọc chuẩn bắt đầu sau khoảng lặng này
            dl, cl = gop["lang"]
            log(f"  Máy gộp hai lần đọc làm một; nghe riêng từ {cl:.2f}s thì thấy lần đọc chuẩn bắt đầu ở đó.")
            kq.update(diem=gop["diem"], doan_bo=" ".join(w.chu for w in tu if w.cuoi <= cl + 0.05),
                      cau_dau=" ".join(w.chu for w in gop["tu"][:14]))
            t_cat, cach = max(dl + 0.03, cl - CHUA_LAY_HOI, 0.0), f"khoảng lặng {dl:.2f}–{cl:.2f}s, nghe lại vì máy gộp hai lần đọc"
        else:
            kq.update(diem=tim["diem"], doan_bo=" ".join(w.chu for w in tu[:j]),
                      cau_dau=" ".join(w.chu for w in tu[j:j + 14]))
            if tu[j].dau < KHONG_CAT_DUOI:
                kq.update(trang_thai="không có đoạn lặp", ghi_chu=f"kịch bản bắt đầu ngay từ {tu[j].dau:.2f}s — không cắt, không tạo v2")
                return kq
            t_cat, cach = moc_cat(tu, j, lang)
        t_cat = math.floor(t_cat * tt["fps"] + 0.5) / tt["fps"]           # khớp biên khung hình -> hình và tiếng bắt đầu cùng lúc
        kq.update(moc_cat=round(t_cat, 3), cach=cach)
        so_tu_td = max(len(chuan(d.tieu_de)), 6)
        if t_cat > max(12.0, 0.8 * so_tu_td):
            kq.update(trang_thai="cần xem lại", ghi_chu=f"đoạn phải bỏ dài bất thường ({t_cat:.1f}s cho tiêu đề {so_tu_td} từ) — không tự cắt")
            return kq
        from rapidfuzz import fuzz
        canh_bao = []
        bo = chuan(kq["doan_bo"])
        if len(bo) >= 3 and fuzz.partial_ratio(" ".join(bo), " ".join(chuan(d.tieu_de))) < 45:
            canh_bao.append("đoạn bị bỏ không giống tiêu đề cột B")
        if cach == KHONG_THAY_LANG:
            canh_bao.append("không thấy khoảng lặng giữa hai lần đọc, cắt theo mốc từ — nghe lại chỗ đầu")
        log(f"  Mốc cắt {t_cat:.2f}s ({cach}; khớp kịch bản {kq['diem']:.0f}/100)")
        log(f"    bỏ : {kq['doan_bo'] or '(Whisper không nghe ra chữ)'}")
        log(f"    giữ: {kq['cau_dau']}…")
        if args.chi_xem:
            kq.update(trang_thai="xem thử", ghi_chu="; ".join(canh_bao))
            return kq

        t0 = time.time()
        buoc("render")
        bo_mh = render(goc, v2, t_cat, tt)
        log(f"  ✓ {v2.name} ({v2.stat().st_size / 1048576:.1f} MB, còn {_mmss(tt['giay'] - t_cat)}, {bo_mh}, {time.time() - t0:.0f}s)")
        buoc("nghe lại bản v2")
        kq["cau_dau_v2"], them = _kiem_tra_v2(v2, tt["giay"] - t_cat, d.kich_ban, args.cpu)
        canh_bao += them
        kq.update(trang_thai="xong", v2=v2.name, ghi_chu="; ".join(canh_bao))
        # doan_bo / cau_dau / ghi_chu: để giao diện hiện lại chi tiết của dòng đã làm ở lần mở sau
        so_tay[fid] = {"goc": goc.name, "v2": v2.name, "moc_cat": round(t_cat, 3), "dong": d.dong,
                       "doan_bo": kq["doan_bo"], "cau_dau": kq["cau_dau_v2"], "ghi_chu": kq["ghi_chu"]}
    except Exception as e:      # noqa: BLE001
        kq.update(trang_thai="lỗi", ghi_chu=f"{type(e).__name__}: {e}"[:300])
        log(f"  ✗ {kq['ghi_chu']}")
    return kq


def _kiem_tra_v2(v2: Path, con: float, kich_ban: str, cpu: bool) -> tuple[str, list[str]]:
    """Nghe lại đầu bản v2: câu đầu phải là mở đầu kịch bản. -> (câu đầu nghe được, các cảnh báo)."""
    from rapidfuzz import fuzz
    tu2 = nghe(doc_am_thanh(v2, min(GIAY_KIEM_TRA, con)), cpu)
    kb, p2 = chuan(kich_ban), [t for w in tu2 for t in chuan(w.chu)]
    n = min(8, len(kb), len(p2))
    diem2 = fuzz.ratio(" ".join(kb[:n]), " ".join(p2[:n])) if n >= 3 else 0
    canh_bao = []
    if diem2 < 70:
        canh_bao.append(f"câu đầu bản v2 chưa khớp kịch bản (điểm {diem2:.0f}) — nghe lại")
    elif tu2 and tu2[0].dau > 0.6:
        canh_bao.append(f"bản v2 lặng {tu2[0].dau:.1f}s trước câu đầu")
    return " ".join(w.chu for w in tu2[:14]), canh_bao


def cat_tay(d: Dong, thu_muc: Path, so_tay: dict, giay: float, args) -> dict:
    """Cắt theo giây NGƯỜI DÙNG chỉ (user 11/11/2026: máy dò sai hoặc không dò ra thì "để tôi chọn thủ công rồi phần mềm
    cắt"). Giây chỉ không cần chính xác: gần đó (trong BAM_LANG_TAY giây) có khoảng lặng thì mốc cắt bám vào khoảng lặng
    ấy, chừa CHUA_LAY_HOI giây lấy hơi như lúc dò tự động; không có thì cắt đúng giây đã chỉ. Luôn làm lại bản v2."""
    kq = {"dong": d.dong, "stt": d.stt, "tieu_de": d.tieu_de, "link": d.link, "trang_thai": "lỗi", "ghi_chu": "", "tay": True}
    try:
        fid = id_drive(d.link)
        if not fid or "/folders/" in d.link:
            raise RuntimeError("cột Link Đăng không phải link FILE Drive (link thư mục không dùng được).")
        cu = so_tay.get(fid) or {}
        buoc("tải video")
        goc = tai_drive(fid, thu_muc / "goc", cu.get("goc"))
        kq["goc"] = goc.name
        so_tay[fid] = {**cu, "goc": goc.name, "dong": d.dong}
        tt = thong_tin(goc)
        if tt is None:
            raise RuntimeError("ffprobe không đọc được video tải về.")
        if tt["acodec"] is None:
            raise RuntimeError("video không có tiếng.")
        if not 0 < giay < tt["giay"] - 1:
            raise RuntimeError(f"giây cắt phải nằm trong video (lớn hơn 0, nhỏ hơn {tt['giay'] - 1:.0f}).")
        buoc("dò khoảng lặng quanh giây đã chỉ")
        am = doc_am_thanh(goc, min(giay + BAM_LANG_TAY + 3.0, tt["giay"]))
        gan = [(abs(c - giay), a, c) for a, c in khoang_lang(am)
               if c - a >= LANG_TOI_THIEU and a - BAM_LANG_TAY <= giay <= c + BAM_LANG_TAY]
        if gan:
            _, a, c = min(gan)
            t_cat, cach = max(a + 0.03, c - CHUA_LAY_HOI, 0.0), f"cắt tay ở {giay:.2f}s, bám khoảng lặng {a:.2f}–{c:.2f}s"
        else:
            t_cat, cach = giay, f"cắt tay đúng {giay:.2f}s (gần đó không có khoảng lặng)"
        t_cat = math.floor(t_cat * tt["fps"] + 0.5) / tt["fps"]
        bo = am[: int(t_cat * 16000)]
        kq.update(moc_cat=round(t_cat, 3), cach=cach, doan_bo=" ".join(w.chu for w in nghe(bo, args.cpu)) if len(bo) >= 16000 else "")
        log(f"  Mốc cắt {t_cat:.2f}s ({cach})")
        log(f"    bỏ : {kq['doan_bo'] or '(Whisper không nghe ra chữ)'}")
        v2 = thu_muc / f"{goc.stem} v2.mp4"
        t0 = time.time()
        buoc("render")
        bo_mh = render(goc, v2, t_cat, tt)
        log(f"  ✓ {v2.name} ({v2.stat().st_size / 1048576:.1f} MB, còn {_mmss(tt['giay'] - t_cat)}, {bo_mh}, {time.time() - t0:.0f}s)")
        buoc("nghe lại bản v2")
        kq["cau_dau_v2"], canh_bao = _kiem_tra_v2(v2, tt["giay"] - t_cat, d.kich_ban, args.cpu)
        log(f"    giữ: {kq['cau_dau_v2']}…")
        kq.update(trang_thai="xong", v2=v2.name, ghi_chu="; ".join(canh_bao))
        so_tay[fid] = {"goc": goc.name, "v2": v2.name, "moc_cat": round(t_cat, 3), "dong": d.dong, "tay": True,
                       "doan_bo": kq["doan_bo"], "cau_dau": kq["cau_dau_v2"], "ghi_chu": kq["ghi_chu"]}
    except Exception as e:      # noqa: BLE001
        kq.update(trang_thai="lỗi", ghi_chu=f"{type(e).__name__}: {e}"[:300])
        log(f"  ✗ {kq['ghi_chu']}")
    return kq


# ---------------------------------------------------------------- báo cáo + main
def ghi_bao_cao(thu_muc: Path, sheet: str, ten_bo: str, ds_kq: list[dict]) -> Path:
    p = unique_path(thu_muc, f"bao_cao_{datetime.now():%Y%m%d_%H%M%S}.txt")
    dem = {}
    for k in ds_kq:
        dem[k["trang_thai"]] = dem.get(k["trang_thai"], 0) + 1
    dong = [f"CẮT ĐOẠN ĐỌC TIÊU ĐỀ LẶP — {ten_bo}", f"Sheet: {sheet}", f"Lúc: {datetime.now():%d/%m/%Y %H:%M:%S}",
            "Tổng: " + ", ".join(f"{v} {k}" for k, v in dem.items()), ""]
    for k in ds_kq:
        dau = "⚠" if k["ghi_chu"] and k["trang_thai"] in ("xong", "xem thử") else {"xong": "✓", "đã có": "✓", "xem thử": "·"}.get(k["trang_thai"], "✗")
        dong.append(f"{dau} Dòng {k['dong']} (STT {k['stt']}) — {k['trang_thai'].upper()}" + (f" — {k['ghi_chu']}" if k["ghi_chu"] else ""))
        dong.append(f"    Tiêu đề  : {k['tieu_de']}")
        dong.append(f"    Link     : {k['link']}")
        if k.get("goc"):
            dong.append(f"    File gốc : goc\\{k['goc']}")
        if k.get("v2"):
            dong.append(f"    File v2  : {k['v2']}")
        if k.get("link_v2"):
            dong.append(f"    Trên Drive: {k['link_v2']} (đã ghi vào cột H)")
        if k.get("loi_len"):
            dong.append(f"    Tải lên  : LỖI — {k['loi_len']}")
        if k.get("moc_cat") is not None:
            them = (f" ({k['cach']}" + (f"; khớp kịch bản {k['diem']:.0f}/100" if k.get("diem") is not None else "") + ")") if k.get("cach") else ""
            dong.append(f"    Mốc cắt  : {k['moc_cat']:.2f}s" + them)
        if "doan_bo" in k:
            dong.append(f"    Đoạn bỏ  : {k['doan_bo'] or '(Whisper không nghe ra chữ)'}")
        if k.get("cau_dau_v2") or k.get("cau_dau"):
            dong.append(f"    Câu đầu  : {k.get('cau_dau_v2') or k.get('cau_dau')}…")
        if k.get("nghe_duoc"):
            dong.append(f"    Nghe được: {k['nghe_duoc']}")
        dong.append("")
    p.write_text("\n".join(dong), encoding="utf-8-sig")
    return p


def _doc_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def thu_muc_bo(ten_bo: str, out: str | None = None) -> Path:
    """Thư mục kết quả của một tab Sheet: <Downloads>\\CatDauVideo\\<tên Sheet - tên tab>."""
    return (Path(out) if out else downloads_dir() / "CatDauVideo") / ten_bo


def nho_sheet(sheet: str):
    """Ghi link Sheet vừa dùng vào cau_hinh.json để lần sau khỏi dán lại."""
    cau_hinh = _doc_json(FILE_CAU_HINH)
    if sheet != cau_hinh.get("sheet"):
        FILE_CAU_HINH.write_text(json.dumps({**cau_hinh, "sheet": sheet}, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Cắt đoạn đọc tiêu đề lặp ở đầu video theo Sheet kịch bản.")
    ap.add_argument("--sheet", help="link tab Google Sheet (mặc định: link lần trước)")
    ap.add_argument("--dong", help="dòng cần chạy theo số dòng Sheet: 2-6,9 hoặc tat-ca")
    ap.add_argument("--giay", type=float, default=GIAY_NGHE, help="nghe bao nhiêu giây đầu (mặc định 20)")
    ap.add_argument("--out", help="thư mục kết quả (mặc định: <Downloads>\\CatDauVideo)")
    ap.add_argument("--chi-xem", action="store_true", help="chỉ tải + dò mốc cắt, không render")
    ap.add_argument("--lam-lai", action="store_true", help="làm lại cả dòng đã có v2")
    ap.add_argument("--cpu", action="store_true", help="nhận diện bằng CPU (không dùng GPU)")
    ap.add_argument("--cat-tay", type=float, metavar="GIÂY",
                    help="cắt tay ở giây này thay cho dò tự động (dùng với đúng một dòng, vd --dong 18 --cat-tay 6)")
    ap.add_argument("--tai-len", action="store_true",
                    help="cắt xong tải bản v2 lên thư mục Drive ở cột Link video (E) và ghi link vào cột H (len_drive.py)")
    args = ap.parse_args()
    hoi = sys.stdin is not None and sys.stdin.isatty()

    cau_hinh = _doc_json(FILE_CAU_HINH)
    sheet = args.sheet or cau_hinh.get("sheet") or SHEET_MAC_DINH
    if not args.sheet and not args.dong and hoi:
        log(f"Link Sheet lần trước: {sheet}")
        moi = input("Dán link tab Sheet khác (Enter = dùng link trên): ").strip()
        sheet = moi or sheet
    ten_bo, ds = doc_sheet(sheet)
    nho_sheet(sheet)
    thu_muc = thu_muc_bo(ten_bo, args.out)
    file_so_tay = thu_muc / "so_tay.json"
    so_tay = _doc_json(file_so_tay)
    co_v2 = lambda d: bool((so_tay.get(id_drive(d.link) or "") or {}).get("v2")) and (     # noqa: E731
        thu_muc / so_tay[id_drive(d.link)]["v2"]).is_file()
    log(f"\n{ten_bo}: {len(ds)} dòng có link ở cột Link Đăng. Kết quả ghi vào: {thu_muc}")
    for d in ds:
        log(f"  dòng {d.dong:>3} | STT {d.stt:>3} | {'✓ đã có v2' if co_v2(d) else '  chưa làm '} | {d.tieu_de[:70]}")
    if not ds:
        return 1
    if args.dong:
        chon = chon_dong(args.dong, ds)
    elif hoi:
        tl = input("\nChạy dòng nào? (vd 2-6,9 · tat-ca = mọi dòng · Enter = các dòng chưa làm): ").strip()
        chon = chon_dong(tl, ds) if tl else [d for d in ds if not co_v2(d)]
    else:
        log("\nChưa chọn dòng — thêm --dong 2-6,9 hoặc --dong tat-ca.")
        return 1
    if not chon:
        log("Không có dòng nào để chạy.")
        return 0
    if args.cat_tay is not None and len(chon) != 1:
        log("--cat-tay chỉ dùng với đúng một dòng (vd --dong 18 --cat-tay 6).")
        return 1
    thu_muc.mkdir(parents=True, exist_ok=True)
    log(f"\nSẽ chạy {len(chon)} dòng: {', '.join(str(d.dong) for d in chon)}" + (" (chỉ xem thử, không render)" if args.chi_xem else ""))

    ds_kq, t0, tab_sheet = [], time.time(), None
    for i, d in enumerate(chon, 1):
        log(f"\n[{i}/{len(chon)}] Dòng {d.dong} (STT {d.stt}): {d.tieu_de[:80]}")
        kq = cat_tay(d, thu_muc, so_tay, args.cat_tay, args) if args.cat_tay is not None else xu_ly(d, thu_muc, so_tay, args)
        ds_kq.append(kq)
        if kq["trang_thai"] not in ("xong", "xem thử"):
            log(f"  → {kq['trang_thai']}" + (f": {kq['ghi_chu']}" if kq["ghi_chu"] else ""))
        elif kq["ghi_chu"]:
            log(f"  ⚠ {kq['ghi_chu']}")
        if args.tai_len:            # dòng có cảnh báo thì không tự tải: nghe lại trước đã
            import len_drive
            if len_drive.nen_tu_tai(kq):
                try:
                    tab_sheet = tab_sheet or len_drive.TabSheet(sheet, log)
                    kq["link_v2"] = len_drive.tai_len(d, thu_muc, so_tay, tab_sheet, log)
                except Exception as e:      # noqa: BLE001
                    kq["loi_len"] = f"{type(e).__name__}: {e}"[:300]
                    log(f"  ✗ Không tải lên Drive được: {kq['loi_len']}")
        file_so_tay.write_text(json.dumps(so_tay, ensure_ascii=False, indent=1), encoding="utf-8")
    # lần chạy không làm gì mới (mọi dòng đều "đã có") thì không đẻ thêm file báo cáo
    bc = ghi_bao_cao(thu_muc, sheet, ten_bo, ds_kq) if any(k["trang_thai"] != "đã có" for k in ds_kq) else None
    dem = {}
    for k in ds_kq:
        dem[k["trang_thai"]] = dem.get(k["trang_thai"], 0) + 1
    canh_bao = [k for k in ds_kq if k["ghi_chu"] and k["trang_thai"] == "xong"]
    log(f"\nXong sau {time.time() - t0:.0f}s: " + ", ".join(f"{v} {k}" for k, v in dem.items())
        + (f"; {len(canh_bao)} bản v2 cần nghe lại (dòng {', '.join(str(k['dong']) for k in canh_bao)})" if canh_bao else ""))
    log(f"Thư mục kết quả: {thu_muc}")
    if bc:
        log(f"Báo cáo: {bc.name}")
    return 0 if all(k["trang_thai"] in ("xong", "đã có", "xem thử", "không có đoạn lặp") for k in ds_kq) else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        ma = main()
    except KeyboardInterrupt:
        log("\nĐã dừng theo yêu cầu.")
        ma = 130
    except Exception as e:      # noqa: BLE001
        log(f"\n✗ {type(e).__name__}: {e}")
        ma = 1
    sys.stdout.flush()
    os._exit(ma)                # không để ctranslate2 hủy model GPU lúc thoát (từng abort 0xC0000409)
