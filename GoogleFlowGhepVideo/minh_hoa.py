# -*- coding: utf-8 -*-
"""Cảnh minh họa (B-roll) theo TỪ KHÓA cho phần sau của video.

Luồng:
  1. doc_kho()       : đọc KHO minh họa từ Google Sheet (CSV export, sheet chia sẻ "ai có link") hoặc file CSV
                       trên máy. Mỗi dòng một clip/ảnh: Từ khóa (nhiều từ, cách nhau dấu phẩy) + Link Drive
                       (hoặc đường dẫn trên máy). Dòng chưa có link thì bỏ qua.
  2. tach_cau()      : từ danh sách từ đã có mốc thời gian của viet_sub (kịch bản khớp giọng đọc) -> các CÂU
                       kèm giây bắt đầu/kết thúc.
  3. hoi_ai_chon()   : gửi kịch bản (đánh số câu) + DANH SÁCH TỪ KHÓA ĐANG CÓ TRONG KHO cho AI (GPT / Claude /
                       Gemini qua hoi_*.py ở gốc repo) -> JSON: câu nào minh họa bằng từ khóa nào. AI chỉ được
                       chọn từ khóa có trong kho; câu muốn minh họa mà kho thiếu thì ghi "gợi ý" -> lưu vào
                       file "thiếu" để bổ sung kho dần.
  4. len_ke_hoach()  : quy tắc ghép: mỗi cảnh TOI_THIEU_GIAY..toi_da_giay (bắt đầu đúng lúc câu vang lên, cắt về
                       bác sĩ trước khi câu hết nếu câu dài), không minh họa câu đầu và câu cuối, hai cảnh cách
                       nhau ít nhất một câu, tổng không quá ti_le_toi_da thời lượng phần sau, cùng từ khóa thì
                       xoay vòng các clip.
  5. tai_clip()      : tải clip về cache `video minh họa/` cạnh tool theo ID file Drive (tải một lần, dùng mãi).
ghep_tieude.py nhận danh sách cảnh và đè lên phần sau bằng overlay theo giây (tắt tiếng, phủ kín khung).

Dùng riêng để thử:  python minh_hoa.py --kho <link sheet|csv> --kich-ban kb.docx --audio giong.mp3 [--ai gpt]
"""
from __future__ import annotations

import csv
import io
import json
import random
import re
import sys
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))             # hoi_claude / hoi_gpt / hoi_gemini
CACHE_DIR = HERE / "video minh họa"              # clip tải từ Drive (gitignore)
FILE_THIEU = CACHE_DIR / "thieu_minh_hoa.jsonl"  # từ khóa AI muốn dùng mà kho chưa có
DUOI_VIDEO = (".mp4", ".mov", ".mkv", ".m4v", ".webm")
DUOI_ANH = (".jpg", ".jpeg", ".png", ".webp")
TOI_THIEU_GIAY = 2.5          # cảnh ngắn hơn thì bỏ (lóe lên không kịp nhìn)
TOI_DA_GIAY = 6.0             # cảnh dài hơn thì cắt về bác sĩ
TI_LE_TOI_DA = 0.45           # tổng thời gian minh họa / thời lượng phần sau
CACH_CAU = 1                  # giữa hai cảnh có ít nhất bấy nhiêu câu không minh họa
CSV_TTL = 300                 # giây: dùng lại CSV đã tải nếu còn mới (đỡ gọi Google liên tục)
DAU_HET_CAU = ".?!:;…"


def khong_dau(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower()).replace("đ", "d")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


# ============================================================== 1. kho minh họa
@dataclass
class Clip:
    id: str
    ten: str
    tu_khoa: list[str]          # đã chuẩn hóa không dấu
    tu_khoa_hien: list[str]     # như trong Sheet
    mo_ta: str
    loai: str                   # "video" | "anh"
    link: str
    thoi_luong: float = 0.0
    duong_dan: Path | None = None   # file trên máy (sau khi tải)


def _cot(ten: str) -> str:
    """Tên cột trong Sheet -> khóa chuẩn."""
    k = khong_dau(ten)
    for khoa, mau in (("id", ("id", "ma")), ("ten", ("ten", "ten file", "ten clip")), ("tu_khoa", ("tu khoa", "tag", "tags", "keyword")),
                      ("mo_ta", ("mo ta", "mota", "noi dung")), ("loai", ("loai", "kieu", "type")),
                      ("thoi_luong", ("thoi luong", "giay", "duration")), ("link", ("link", "link drive", "drive", "url", "duong dan")),
                      ("ghi_chu", ("ghi chu", "note"))):
        if k in mau or any(k.startswith(m) for m in mau):
            return khoa
    return k


def sheet_csv_url(nguon: str) -> str | None:
    """Link Google Sheet (có/không gid) -> link export CSV của đúng tab đó. Không phải link Sheet -> None."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", nguon)
    if not m:
        return None
    gid = re.search(r"[#&?]gid=(\d+)", nguon)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid.group(1) if gid else 0}"


def _tai_csv(url: str, log: Callable[[str], None]) -> str:
    """Tải CSV của Sheet; lỗi mạng thì dùng bản đã tải lần trước nếu có."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / ("kho_" + re.sub(r"\W+", "_", url)[-80:] + ".csv")
    if cache.exists() and time.time() - cache.stat().st_mtime < CSV_TTL:
        return cache.read_text(encoding="utf-8-sig")
    try:
        r = requests.get(url, timeout=30, allow_redirects=True)
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", "") and "<html" in r.text[:200].lower():
            raise RuntimeError("Google trả trang web thay vì CSV — Sheet chưa chia sẻ 'Bất kỳ ai có đường liên kết'?")
        cache.write_text(r.text, encoding="utf-8")
        return r.text
    except Exception as e:
        if cache.exists():
            log(f"  kho minh họa: không tải được Sheet ({e}), dùng bản đã tải lúc trước")
            return cache.read_text(encoding="utf-8-sig")
        raise


def doc_kho(nguon: str, log: Callable[[str], None] = print) -> list[Clip]:
    """nguon = link Google Sheet (tab Kho minh họa) hoặc đường dẫn file CSV. -> các clip CÓ link."""
    nguon = (nguon or "").strip()
    if not nguon:
        return []
    p = Path(nguon)
    if p.is_file():
        text = p.read_text(encoding="utf-8-sig")
    else:
        url = sheet_csv_url(nguon)
        if not url:
            raise ValueError(f"Kho minh họa phải là link Google Sheet hoặc file CSV: {nguon}")
        text = _tai_csv(url, log)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    cot = [_cot(c) for c in rows[0]]
    kq, bo_link = [], 0
    for i, r in enumerate(rows[1:], 2):
        d = {cot[j]: (r[j].strip() if j < len(r) else "") for j in range(len(cot))}
        link = d.get("link", "")
        tags = [t.strip() for t in re.split(r"[,;/|]", d.get("tu_khoa", "")) if t.strip()]
        if not tags:
            continue
        if not link:
            bo_link += 1
            continue
        ten = d.get("ten") or tags[0]
        duoi = Path(ten).suffix.lower() or Path(urllib.parse.urlparse(link).path).suffix.lower()
        loai = (d.get("loai") or "").lower()
        if loai.startswith(("anh", "ảnh", "image", "img")) or duoi in DUOI_ANH:
            loai = "anh"
        else:
            loai = "video"
        try:
            tl = float(str(d.get("thoi_luong", "")).replace(",", ".") or 0)
        except ValueError:
            tl = 0.0
        kq.append(Clip(id=d.get("id") or f"dong{i}", ten=ten, tu_khoa=[khong_dau(t) for t in tags], tu_khoa_hien=tags,
                       mo_ta=d.get("mo_ta", ""), loai=loai, link=link, thoi_luong=tl))
    if bo_link:
        log(f"  kho minh họa: {bo_link} dòng chưa có link, bỏ qua")
    return kq


def tu_khoa_trong_kho(kho: list[Clip]) -> list[str]:
    """Danh sách từ khóa (như trong Sheet, không trùng, giữ thứ tự) để đưa cho AI chọn."""
    thay, ds = set(), []
    for c in kho:
        for t, k in zip(c.tu_khoa_hien, c.tu_khoa):
            if k not in thay:
                thay.add(k)
                ds.append(t)
    return ds


# ============================================================== 2. câu + mốc thời gian
@dataclass
class Cau:
    so: int                     # 1-based
    text: str
    start: float
    end: float


def tach_cau(tu, tu_giay: float = 0.0) -> list[Cau]:
    """viet_sub.Tu (đã có start/end) -> câu theo dấu hết câu; chỉ lấy câu bắt đầu từ `tu_giay` (bỏ hook)."""
    cau, hien = [], []
    for t in tu:
        hien.append(t)
        if t.hien.rstrip('"”’)').endswith(tuple(DAU_HET_CAU)):
            cau.append(hien)
            hien = []
    if hien:
        cau.append(hien)
    kq = []
    for ws in cau:
        if ws[0].start is None or ws[-1].end is None or ws[0].start < tu_giay:
            continue
        kq.append(Cau(len(kq) + 1, " ".join(w.hien for w in ws), float(ws[0].start), float(ws[-1].end)))
    return kq


# ============================================================== 3. AI chọn từ khóa
MAU_CAU_HOI = """Bạn là biên tập viên dựng video y khoa ngắn (bác sĩ nói trước ống kính, khán giả là cô chú 45-70 tuổi).
Dưới đây là KỊCH BẢN đã đánh số câu và DANH SÁCH TỪ KHÓA của kho cảnh minh họa (b-roll) hiện có.

Nhiệm vụ: chọn những câu nên chèn cảnh minh họa và từ khóa minh họa cho câu đó.
Quy tắc bắt buộc:
- "tu_khoa" CHỈ được lấy NGUYÊN VĂN từ DANH SÁCH TỪ KHÓA bên dưới. Không tự nghĩ từ khóa mới.
- Không có từ khóa nào hợp nhưng câu đó rất nên có minh họa thì để "tu_khoa" rỗng và ghi "goi_y" (2-5 từ, cảnh cần quay/tìm).
- Không chọn câu 1 và câu cuối. Hai câu được chọn cách nhau ít nhất 1 câu. Chọn tối đa {toi_da_canh} câu, ưu tiên câu có
  hình ảnh cụ thể (hành động, đồ ăn, tư thế, triệu chứng), bỏ câu nói chung chung.
- Chỉ trả về MỘT mảng JSON, không giải thích, dạng: [{{"cau": 3, "tu_khoa": "nằm sau ăn", "goi_y": ""}}, ...]

DANH SÁCH TỪ KHÓA: {tu_khoa}

KỊCH BẢN:
{kich_ban}"""


def _nha(ten: str):
    import importlib
    return importlib.import_module({"gpt": "hoi_gpt", "claude": "hoi_claude", "gemini": "hoi_gemini"}[ten])


def _json_trong_tra_loi(text: str):
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b <= a:
        raise ValueError("AI không trả về mảng JSON")
    return json.loads(text[a:b + 1])


def hoi_ai_chon(cau: list[Cau], tu_khoa: list[str], nha: str = "gpt", model: str | None = None,
                toi_da_canh: int | None = None, log: Callable[[str], None] = print) -> list[dict]:
    """-> [{"cau": int, "tu_khoa": str (đã chuẩn hóa, '' nếu không), "tu_khoa_hien": str, "goi_y": str}]"""
    if not cau:
        return []
    toi_da_canh = toi_da_canh or max(1, len(cau) // 3)
    prompt = MAU_CAU_HOI.format(toi_da_canh=toi_da_canh, tu_khoa=", ".join(tu_khoa) if tu_khoa else "(kho trống)",
                                kich_ban="\n".join(f"{c.so}. {c.text}" for c in cau))
    m = _nha(nha)
    t0 = time.time()
    r = m.hoi(prompt, model=model)
    log(f"  {m.TEN} chọn từ khóa xong {time.time() - t0:.1f}s ({r.model})")
    try:
        ds = _json_trong_tra_loi(r.text)
    except Exception as e:
        log(f"  không đọc được JSON của {m.TEN}: {e}; trả lời: {r.text[:200]!r}")
        return []
    bang = {khong_dau(t): t for t in tu_khoa}
    kq, thay = [], set()
    for d in ds if isinstance(ds, list) else []:
        try:
            so = int(d.get("cau"))
        except (TypeError, ValueError, AttributeError):
            continue
        if so < 1 or so > len(cau) or so in thay:
            continue
        thay.add(so)
        k = khong_dau(str(d.get("tu_khoa") or ""))
        goi_y = str(d.get("goi_y") or "").strip()
        if k and k not in bang:                   # AI tự chế từ khóa -> coi như kho thiếu
            goi_y, k = goi_y or str(d.get("tu_khoa")), ""
        kq.append({"cau": so, "tu_khoa": k, "tu_khoa_hien": bang.get(k, ""), "goi_y": goi_y})
    kq.sort(key=lambda x: x["cau"])
    return kq


def ghi_thieu(ten_bo: str, thieu: list[dict]) -> None:
    """Ghi từ khóa AI muốn dùng mà kho chưa có (để bổ sung kho): một dòng JSON mỗi mục."""
    if not thieu:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(FILE_THIEU, "a", encoding="utf-8") as f:
        for t in thieu:
            f.write(json.dumps({"luc": time.strftime("%Y-%m-%d %H:%M"), "bo": ten_bo, **t}, ensure_ascii=False) + "\n")


# ============================================================== 4. kế hoạch cảnh
@dataclass
class Canh:
    start: float                # giây trong video cuối
    end: float
    clip: Clip
    cau: Cau
    tu_khoa: str


def len_ke_hoach(cau: list[Cau], chon: list[dict], kho: list[Clip], *, tong_giay: float,
                 toi_da_giay: float = TOI_DA_GIAY, ti_le_toi_da: float = TI_LE_TOI_DA,
                 seed: int | None = None, log: Callable[[str], None] = print) -> tuple[list[Canh], list[dict]]:
    """-> (các cảnh theo thứ tự thời gian, mục thiếu [{cau, text, goi_y}])."""
    rng = random.Random(seed)
    theo_tag: dict[str, list[Clip]] = {}
    for c in kho:
        for k in c.tu_khoa:
            theo_tag.setdefault(k, []).append(c)
    vong: dict[str, int] = {k: rng.randrange(len(v)) for k, v in theo_tag.items()}   # xoay vòng clip cùng tag
    canh, thieu = [], []
    ngan_sach = tong_giay * ti_le_toi_da
    da_dung = 0.0
    cau_truoc = -10
    for d in chon:
        c = cau[d["cau"] - 1]
        if not d["tu_khoa"]:
            thieu.append({"cau": c.so, "text": c.text, "goi_y": d["goi_y"]})
            continue
        if c.so == 1 or c.so == len(cau):
            continue
        if c.so - cau_truoc <= CACH_CAU:
            continue
        dai = min(c.end - c.start, toi_da_giay)
        if dai < TOI_THIEU_GIAY:
            continue
        if da_dung + dai > ngan_sach:
            log(f"  minh họa: đã đủ {ti_le_toi_da:.0%} thời lượng, bỏ câu {c.so}")
            break
        ds = theo_tag.get(d["tu_khoa"]) or []
        if not ds:
            thieu.append({"cau": c.so, "text": c.text, "goi_y": d["goi_y"] or d["tu_khoa_hien"]})
            continue
        clip = ds[vong[d["tu_khoa"]] % len(ds)]
        vong[d["tu_khoa"]] += 1
        if clip.loai == "video" and clip.thoi_luong and clip.thoi_luong < dai:
            dai = max(TOI_THIEU_GIAY, clip.thoi_luong)
        canh.append(Canh(round(c.start, 3), round(c.start + dai, 3), clip, c, d["tu_khoa_hien"]))
        da_dung += dai
        cau_truoc = c.so
    return canh, thieu


# ============================================================== 5. tải clip
def drive_file_id(link: str) -> str | None:
    for p in (r"/file/d/([A-Za-z0-9_-]{20,})", r"[?&]id=([A-Za-z0-9_-]{20,})", r"^([A-Za-z0-9_-]{25,})$"):
        m = re.search(p, link.strip())
        if m:
            return m.group(1)
    return None


def tai_clip(clip: Clip, log: Callable[[str], None] = print, dung: Callable[[], bool] | None = None) -> Path:
    """Link là file trên máy -> dùng luôn; link Drive -> tải về CACHE_DIR/<id><đuôi> (chỉ tải khi chưa có)."""
    p = Path(clip.link)
    if p.is_file():
        clip.duong_dan = p
        return p
    fid = drive_file_id(clip.link)
    if not fid:
        raise ValueError(f"Link không phải file Drive hay file trên máy: {clip.link}")
    duoi = Path(clip.ten).suffix.lower()
    if duoi not in DUOI_VIDEO + DUOI_ANH:
        duoi = ".jpg" if clip.loai == "anh" else ".mp4"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / f"{fid}{duoi}"
    if not dest.exists():
        import drive_thu_muc as dtm
        log(f"  tải minh họa {clip.ten} ({fid}) ...")
        n = dtm.tai_file(requests.Session(), fid, dest, log=log, dung=dung)
        log(f"    {dest.name} ({n / 1048576:.2f} MB)")
    clip.duong_dan = dest
    return dest


# ============================================================== tổng hợp
def chuan_bi(tu, *, kho_nguon: str, tong_giay: float, tu_giay: float = 0.0, nha: str = "gpt", model: str | None = None,
             toi_da_giay: float = TOI_DA_GIAY, ti_le_toi_da: float = TI_LE_TOI_DA, seed: int | None = None,
             ten_bo: str = "", log: Callable[[str], None] = print, dung: Callable[[], bool] | None = None) -> dict:
    """Một phát từ danh sách từ đã có mốc -> cảnh đã tải sẵn. -> {canh, thieu, so_cau, tu_khoa_kho}.
    Lỗi kho/AI không làm hỏng video: trả về canh=[] kèm 'loi'."""
    kq = {"canh": [], "thieu": [], "so_cau": 0, "tu_khoa_kho": [], "loi": ""}
    try:
        kho = doc_kho(kho_nguon, log)
    except Exception as e:
        kq["loi"] = f"không đọc được kho minh họa: {e}"
        log("  " + kq["loi"])
        return kq
    tags = tu_khoa_trong_kho(kho)
    kq["tu_khoa_kho"] = tags
    cau = tach_cau(tu, tu_giay)
    kq["so_cau"] = len(cau)
    if not kho:
        kq["loi"] = "kho minh họa chưa có clip nào có link"
        log("  " + kq["loi"])
        return kq
    if len(cau) < 3:
        kq["loi"] = "phần sau quá ít câu để chèn minh họa"
        return kq
    try:
        chon = hoi_ai_chon(cau, tags, nha, model, log=log)
    except Exception as e:
        kq["loi"] = f"AI chọn từ khóa lỗi: {e}"
        log("  " + kq["loi"])
        return kq
    canh, thieu = len_ke_hoach(cau, chon, kho, tong_giay=tong_giay, toi_da_giay=toi_da_giay,
                               ti_le_toi_da=ti_le_toi_da, seed=seed, log=log)
    kq["thieu"] = thieu
    if thieu:
        ghi_thieu(ten_bo, thieu)
        log("  kho thiếu: " + "; ".join(f"câu {t['cau']}: {t['goi_y'] or '?'}" for t in thieu) + f"  (ghi vào {FILE_THIEU.name})")
    ok = []
    for cn in canh:
        try:
            tai_clip(cn.clip, log, dung)
            ok.append(cn)
        except Exception as e:
            log(f"  bỏ cảnh câu {cn.cau.so} ({cn.clip.ten}): {e}")
    kq["canh"] = ok
    return kq


def mo_ta_canh(canh: list[Canh]) -> str:
    return " → ".join(f"{c.start:.1f}s {c.tu_khoa} ({c.clip.ten}, {c.end - c.start:.1f}s)" for c in canh)


if __name__ == "__main__":        # thử riêng: chọn từ khóa + kế hoạch, không render
    import argparse
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--kho", required=True, help="link Google Sheet hoặc file CSV")
    ap.add_argument("--kich-ban", required=True)
    ap.add_argument("--audio", required=True, help="giọng đọc (để lấy mốc thời gian từng câu)")
    ap.add_argument("--ai", default="gpt", choices=["gpt", "claude", "gemini"])
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    import viet_sub
    from ghep_tieude import probe_media
    _, _, D = probe_media(Path(a.audio))
    import tempfile
    srt = Path(tempfile.gettempdir()) / "minh_hoa_thu.srt"
    tk = viet_sub.tao_srt(Path(a.kich_ban), [(Path(a.audio), 0.0, None)], D, srt)
    kq = chuan_bi(tk["tu"], kho_nguon=a.kho, tong_giay=D, nha=a.ai, model=a.model, ten_bo="thử")
    print("Câu:", kq["so_cau"], "| từ khóa kho:", kq["tu_khoa_kho"])
    print("Cảnh:", mo_ta_canh(kq["canh"]) or "(không)")
    print("Thiếu:", kq["thieu"])
    if kq["loi"]:
        print("Lỗi:", kq["loi"])
    sys.stdout.flush()
    import os
    os._exit(0)
