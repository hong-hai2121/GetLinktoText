# -*- coding: utf-8 -*-
"""Cảnh minh họa (B-roll) theo TỪ KHÓA cho phần sau của video.

Luồng:
  1. doc_kho()       : đọc KHO minh họa từ Google Sheet (CSV export, sheet chia sẻ "ai có link") hoặc file CSV
                       trên máy. Mỗi dòng một clip/ảnh: Từ khóa (nhiều từ, cách nhau dấu phẩy) + Link Drive
                       (hoặc đường dẫn trên máy). Dòng CHƯA có link: tìm trong THƯ MỤC VIDEO MẪU (mặc định
                       `video minh họa/` cạnh tool) file trùng Tên clip hoặc ID (vd MH01.mp4) -> dùng luôn;
                       không có thì bỏ qua. trang_thai_kho() liệt kê từng dòng đã có / chưa có video cho GUI.
  2. tach_cau()      : từ danh sách từ đã có mốc thời gian của viet_sub (kịch bản khớp giọng đọc) -> các CÂU
                       kèm giây bắt đầu/kết thúc.
  3. hoi_ai_chon()   : gửi kịch bản (đánh số câu) cho AI (GPT / Claude / Gemini qua hoi_*.py ở gốc repo), KHÔNG gửi
                       danh sách từ khóa kho (kho lớn thì prompt phình). AI tự đề xuất 2-4 từ khóa hình ảnh + mô tả
                       cảnh cho mỗi câu, ưu tiên 1/3 đầu kịch bản. khop_tu_khoa() so đề xuất với kho 3 mức:
                       ĐÚNG (trùng hẳn, bỏ dấu/hoa thường) → CHỨA (cụm từ nằm trong / bao trùm từ khóa kho, ≥2 từ)
                       → GẦN (≥75% từ đặc trưng, giữ dấu, có trong từ khóa + tên + mô tả của một clip). Không khớp
                       → "thiếu": ghi file jsonl + tab 'Thiếu' của Sheet (ghi_thieu_sheet, service account).
                       (tu_do=False = cách cũ gửi cả danh sách, AI chỉ được chọn trong đó.)
  4. len_ke_hoach()  : quy tắc ghép: mỗi cảnh TOI_THIEU_GIAY..toi_da_giay (bắt đầu đúng lúc câu vang lên, cắt về
                       bác sĩ trước khi câu hết nếu câu dài), không minh họa câu đầu và câu cuối, hai cảnh cách
                       nhau ít nhất một câu, tổng không quá ti_le_toi_da thời lượng phần sau, cùng từ khóa thì
                       xoay vòng các clip.
  5. tai_clip()      : tải clip về thư mục video mẫu (mặc định `video minh họa/` cạnh tool) theo ID file Drive
                       (tải một lần, dùng mãi). tai_tat_ca() tải trước mọi clip có link (nút trên GUI).
ghep_tieude.py nhận danh sách cảnh và đè lên phần sau bằng overlay theo giây (tắt tiếng, phủ kín khung).

Dùng riêng để thử:  python minh_hoa.py --kho <link sheet|csv> --kich-ban kb.docx --audio giong.mp3 [--ai gpt]

CHẾ ĐỘ KẾ HOẠCH (--ke-hoach, không render, không tải clip): đưa cho AI CẢ dòng kho chưa có video, ra văn bản
"câu nào → clip MH nào, giây nào, đã có video chưa" + danh sách clip cần quay/tải cho đúng video này.
  python minh_hoa.py --ke-hoach --drive <link thư mục Drive của tập>
  python minh_hoa.py --ke-hoach --kich-ban kb.docx --audio giong.mp3
CHẾ ĐỘ CHUẨN BỊ (--chuan-bi): như ghép thật nhưng dừng trước render — AI chọn trên dòng đã có video, tải clip khớp Sheet
về thư mục video mẫu, SAO CHÉP vào <thư mục tập>\\Minh họa\\ (đánh số theo thứ tự xuất hiện).
--drive tải cả thư mục Drive về Downloads\\<tên thư mục Drive = tên kịch bản>\\ (đã có thì dùng lại, chỉ tải file thiếu);
báo cáo (kèm trả lời thô của AI) ghi <thư mục tập>\\Kế hoạch minh họa.txt, không có --drive thì ra Downloads.

NHỚ TRẢ LỜI AI (bo_nho): trả lời thô của AI được ghi vào <thư mục tập>\\gpt_minh_hoa.json kèm chữ ký câu hỏi (AI, chế độ,
kịch bản đã đánh số câu). Chạy lại cùng kịch bản -> dùng lại, không hỏi AI (chỉ ghép lại với bộ xếp cảnh hiện tại);
kịch bản / cách tách câu / chế độ / AI đổi -> hỏi mới. --hoi-lai (ghep_tieude: --minh-hoa-hoi-lai) ép hỏi mới và ghi đè.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
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
CSV_TTL = 12 * 3600           # giây: dùng lại CSV đã tải; app.py tải mới MỘT lần đầu mỗi lượt chạy + nút "Cập nhật" (user 22/10)
VEC_NGUONG_MAC_DINH = 0.70    # mức 4 (vector nghĩa, vector_kho.py): sàn điểm cosine để nhận
VEC_NHOM_MAC_DINH = 0.97      # clip đạt ≥ 97% điểm cao nhất (user 23/10: 90% rộng quá) (và vượt sàn) thì cùng nhóm -> planner random (đa dạng giữa các video)
FILE_DA_DUNG = CACHE_DIR / "da_dung.json"   # số lần mỗi clip đã được dùng ở các tập trước (xoay vòng cảnh toàn kênh)
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


def _tai_csv(url: str, log: Callable[[str], None], moi: bool = False) -> str:
    """Tải CSV của Sheet; lỗi mạng thì dùng bản đã tải lần trước nếu có. moi=True: bỏ bản đệm, tải lại ngay."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / ("kho_" + re.sub(r"\W+", "_", url)[-80:] + ".csv")
    if not moi and cache.exists() and time.time() - cache.stat().st_mtime < CSV_TTL:
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


def _doc_dong(nguon: str, log: Callable[[str], None] = print, moi: bool = False) -> list[dict]:
    """Các dòng CÓ từ khóa của Sheet/CSV -> dict cột chuẩn: id, ten, tags (list), mo_ta, loai ('video'|'anh'),
    thoi_luong (float), link, ghi_chu, dong (số dòng trong Sheet). Chưa xét có link hay không."""
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
        text = _tai_csv(url, log, moi)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    cot = [_cot(c) for c in rows[0]]
    kq = []
    for i, r in enumerate(rows[1:], 2):
        d = {cot[j]: (r[j].strip() if j < len(r) else "") for j in range(len(cot))}
        tags = [t.strip() for t in re.split(r"[,;/|]", d.get("tu_khoa", "")) if t.strip()]
        if not tags:
            continue
        link = d.get("link", "")
        ten = d.get("ten") or tags[0]
        duoi = Path(ten).suffix.lower() or Path(urllib.parse.urlparse(link).path).suffix.lower()
        loai = (d.get("loai") or "").lower()
        loai = "anh" if loai.startswith(("anh", "ảnh", "image", "img")) or duoi in DUOI_ANH else "video"
        try:
            tl = float(str(d.get("thoi_luong", "")).replace(",", ".") or 0)
        except ValueError:
            tl = 0.0
        kq.append(dict(id=d.get("id") or f"dong{i}", ten=ten, tags=tags, mo_ta=d.get("mo_ta", ""), loai=loai,
                       thoi_luong=tl, link=link, ghi_chu=d.get("ghi_chu", ""), dong=i))
    return kq


def _chi_muc_file(thu_muc: Path) -> dict[str, Path]:
    """Các file video/ảnh trong thư mục video mẫu, khóa = tên file và tên không đuôi (không dấu, chữ thường)."""
    chi_muc: dict[str, Path] = {}
    if not thu_muc.is_dir():
        return chi_muc
    for p in sorted(thu_muc.iterdir()):
        if p.is_file() and p.suffix.lower() in DUOI_VIDEO + DUOI_ANH:
            for k in (khong_dau(p.name), khong_dau(p.stem)):
                chi_muc.setdefault(k, p)
    return chi_muc


def _file_theo_ten(chi_muc: dict[str, Path], ma: str, ten: str) -> Path | None:
    """Dòng Sheet chưa có link -> file trong thư mục trùng Tên clip (có/không đuôi) hoặc ID."""
    for ung_vien in (ten, Path(ten).stem if ten else "", ma):
        k = khong_dau(ung_vien)
        if k and k in chi_muc:
            return chi_muc[k]
    return None


def _lap_clip(d: dict, link: str) -> Clip:
    return Clip(id=d["id"], ten=d["ten"], tu_khoa=[khong_dau(t) for t in d["tags"]], tu_khoa_hien=d["tags"],
                mo_ta=d["mo_ta"], loai=d["loai"], link=link, thoi_luong=d["thoi_luong"])


def doc_kho(nguon: str, log: Callable[[str], None] = print, thu_muc: str | Path | None = None,
            moi: bool = False, ca_chua_co: bool = False) -> list[Clip]:
    """nguon = link Google Sheet (tab Kho minh họa) hoặc đường dẫn file CSV. -> các clip CÓ video:
    có Link Drive / đường dẫn, hoặc chưa có link nhưng trong thư mục video mẫu có file trùng Tên clip / ID.
    ca_chua_co=True (chế độ kế hoạch): giữ cả dòng chưa có video, link để rỗng — KHÔNG được đưa vào render."""
    thu_muc = Path(thu_muc) if thu_muc else CACHE_DIR
    chi_muc = _chi_muc_file(thu_muc)
    kq, bo_link, tu_thu_muc = [], 0, 0
    for d in _doc_dong(nguon, log, moi):
        link = d["link"]
        if not link:
            p = _file_theo_ten(chi_muc, d["id"], d["ten"])
            if p is not None:
                link, tu_thu_muc = str(p), tu_thu_muc + 1
            else:
                bo_link += 1
                if not ca_chua_co:
                    continue
        kq.append(_lap_clip(d, link))
    if tu_thu_muc:
        log(f"  kho minh họa: {tu_thu_muc} dòng chưa có link, dùng file trùng tên trong {thu_muc.name}")
    if bo_link:
        log(f"  kho minh họa: {bo_link} dòng chưa có video (không link, không file trong {thu_muc.name})"
            + (" — chế độ kế hoạch vẫn đưa cho AI chọn" if ca_chua_co else ", bỏ qua"))
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


CAU_DAI_TOI_DA = 8.0          # câu dài hơn (giây) thì tách theo mệnh đề (dấu phẩy, "và") để mỗi ý một cảnh
MANH_TOI_THIEU = 1.0          # mảnh tách ra ngắn hơn thì nhập vào mảnh trước (user 21/10: chỉ dưới 1 giây mới gộp)
CAU_NGAN_GOP = 1.0            # câu (sau khi tách) ngắn hơn bấy nhiêu giây thì nhập vào câu bên cạnh (user 21/10: trước là 3s, đổi thành 1s — câu 2 giây vẫn là một cảnh riêng)
GOP_NOI_RONG = 1.15           # khi nhập câu ngắn vào câu bên cạnh, cho tổng vượt CAU_DAI_TOI_DA tới 15% (8s -> 9,2s) thay vì để cảnh 2s lẻ
SO_THU_TU = ("nhat", "hai", "ba", "tu", "bon", "nam", "sau", "bay", "tam", "chin", "muoi")


def _dai(ws) -> float:
    return float(ws[-1].end - ws[0].start) if ws and ws[0].start is not None and ws[-1].end is not None else 0.0


def _bat_dau_muc(ws, i: int) -> bool:
    """Từ thứ i mở đầu một mục liệt kê: 'Thứ nhất/hai/…', 'Một/Hai/Ba… là' -> luôn cắt câu ở đây."""
    k = ws[i].khoa
    sau = ws[i + 1].khoa if i + 1 < len(ws) else ""
    truoc = ws[i - 1].khoa if i > 0 else ""
    # "Thứ hai là kho quẹt": mục bắt đầu ở "Thứ" (vế đầu); KHÔNG được coi "hai là" là mục mới nữa, kẻo cắt rời chữ "Thứ"
    return (k == "thu" and sau in SO_THU_TU) or (k in ("mot", "hai", "ba", "bon", "nam", "sau", "bay") and sau == "la" and truoc != "thu")


def _chia_cau_dai(ws, toi_da: float = CAU_DAI_TOI_DA) -> list[list]:
    """Một câu (danh sách Tu) -> các mảnh: cắt TRƯỚC mục liệt kê ('Thứ nhất…'); câu dài hơn `toi_da` giây thì cắt
    thêm ở mệnh đề (sau dấu phẩy, trước 'và'/'rồi'), gộp mệnh đề tới khi vượt `toi_da`; mảnh ngắn hơn MANH_TOI_THIEU
    nhập vào mảnh trước. Câu ngắn, không có mục liệt kê -> giữ nguyên."""
    co_muc = any(_bat_dau_muc(ws, i) for i in range(1, len(ws)))
    if not co_muc and _dai(ws) <= toi_da:
        return [ws]
    menh_de, hien = [], []
    for i, w in enumerate(ws):
        if hien and (_bat_dau_muc(ws, i) or w.khoa in ("va", "roi")):
            menh_de.append(hien)
            hien = []
        hien.append(w)
        if w.hien.rstrip('"”’)').endswith((",", ";")):
            menh_de.append(hien)
            hien = []
    if hien:
        menh_de.append(hien)
    manh, hien = [], []
    for md in menh_de:
        bat_buoc = _bat_dau_muc(md, 0)
        if hien and (bat_buoc or _dai(hien + md) > toi_da):
            manh.append(hien)
            hien = []
        hien = hien + md
    if hien:
        manh.append(hien)
    ket: list[list] = []
    for m in manh:                                   # mảnh quá ngắn -> nhập vào mảnh trước (không nhập vào mục mới)
        if ket and _dai(m) < MANH_TOI_THIEU and not _bat_dau_muc(m, 0):
            ket[-1] = ket[-1] + m
        else:
            ket.append(m)
    return ket


def tach_cau(tu, tu_giay: float = 0.0, cau_dai_toi_da: float = CAU_DAI_TOI_DA) -> list[Cau]:
    """viet_sub.Tu (đã có start/end) -> câu theo dấu hết câu, rồi tách câu dài / mục liệt kê thành mảnh
    (_chia_cau_dai) để mỗi ý một cảnh; chỉ lấy câu bắt đầu từ `tu_giay` (bỏ hook)."""
    cau, hien = [], []
    for t in tu:
        hien.append(t)
        if t.hien.rstrip('"”’)').endswith(tuple(DAU_HET_CAU)):
            cau.append(hien)
            hien = []
    if hien:
        cau.append(hien)
    manh = []
    for ws0 in cau:
        for ws in _chia_cau_dai(ws0, cau_dai_toi_da):
            if ws[0].start is None or ws[-1].end is None or ws[0].start < tu_giay:
                continue
            # câu quá ngắn (vd "Hãy tôn trọng dạ dày.") -> nhập câu trước để tránh một cảnh lóe 2 giây, NHƯNG gộp lại
            # không được vượt câu dài tối đa (trừ khi câu trước bé xíu) — trước đây gộp vô điều kiện nên kịch bản đọc
            # nhanh, nhiều câu 2 giây liên tiếp bị gộp thành một "câu" 18 giây rồi còn 2 câu -> "quá ít câu" (21/10)
            if manh and _dai(ws) < CAU_NGAN_GOP and (_dai(manh[-1] + ws) <= cau_dai_toi_da * GOP_NOI_RONG or _dai(manh[-1]) < MANH_TOI_THIEU):
                manh[-1] = manh[-1] + ws
            else:
                manh.append(ws)
    # mảnh còn ngắn (câu đầu = đuôi tiêu đề 0 giây, hay mảnh không nhập được vào câu trước vì câu trước đã dài) -> thử
    # nhập vào câu SAU, không được thì câu trước; vẫn không vượt câu dài tối đa (câu bé xíu thì cho vượt)
    i = 0
    while i < len(manh) and len(manh) > 1:
        m = manh[i]
        if _dai(m) < CAU_NGAN_GOP:
            be = _dai(m) < MANH_TOI_THIEU
            if i + 1 < len(manh) and (be or _dai(m + manh[i + 1]) <= cau_dai_toi_da * GOP_NOI_RONG):
                manh[i + 1] = m + manh[i + 1]
                del manh[i]
                continue
            if i > 0 and (be or _dai(manh[i - 1] + m) <= cau_dai_toi_da * GOP_NOI_RONG):
                manh[i - 1] = manh[i - 1] + m
                del manh[i]
                continue
        i += 1
    return [Cau(i, " ".join(w.hien for w in ws), float(ws[0].start), float(ws[-1].end)) for i, ws in enumerate(manh, 1)]


# ============================================================== 3. AI chọn từ khóa
MAU_CAU_HOI = """Bạn là biên tập viên dựng video y khoa ngắn (bác sĩ nói trước ống kính, khán giả là cô chú 45-70 tuổi).
Dưới đây là KỊCH BẢN đã đánh số câu và DANH SÁCH TỪ KHÓA của kho cảnh minh họa (b-roll) hiện có.

Nhiệm vụ: chọn những câu nên chèn cảnh minh họa và từ khóa minh họa cho câu đó.
Quy tắc bắt buộc:
- "tu_khoa" CHỈ được lấy NGUYÊN VĂN từ DANH SÁCH TỪ KHÓA bên dưới. Không tự nghĩ từ khóa mới.
- Không có từ khóa nào hợp nhưng câu đó rất nên có minh họa thì để "tu_khoa" rỗng và ghi "goi_y" (2-5 từ, cảnh cần quay/tìm).
- Không chọn câu cuối. Hai câu được chọn cách nhau ít nhất 1 câu. Chọn tối đa {toi_da_canh} câu, ưu tiên câu có
  hình ảnh cụ thể (hành động, đồ ăn, tư thế, triệu chứng), bỏ câu nói chung chung.
- Chỉ trả về MỘT mảng JSON, không giải thích, dạng: [{{"cau": 3, "tu_khoa": "nằm sau ăn", "goi_y": ""}}, ...]

DANH SÁCH TỪ KHÓA: {tu_khoa}

KỊCH BẢN:
{kich_ban}"""

MAU_CAU_HOI_PHU_KIN = """Bạn là biên tập viên dựng video y khoa ngắn (bác sĩ nói trước ống kính, khán giả là cô chú 45-70 tuổi).
Dưới đây là KỊCH BẢN phần sau của video, đã đánh số câu (câu dài đã được tách thành từng ý).

Cách dựng: phần sau được PHỦ bằng cảnh minh họa (b-roll) lấy từ kho; chỉ chỗ nào kho không có cảnh phù hợp mới để hình
bác sĩ nói. Nhiệm vụ: với MỖI câu, đề xuất TỪ KHÓA HÌNH ẢNH để tool tìm clip trong kho. Không tìm thấy thì tool ghi lại
để quay bổ sung, nên cứ đề xuất tự nhiên, không cần biết kho có gì.
Quy tắc bắt buộc:
- Trả lời cho TẤT CẢ các câu, kể cả câu đầu và câu cuối. Câu nào thật sự nên để bác sĩ nói trước ống kính (chỉ nên là
  lời hỏi khán giả / kêu gọi bình luận ở cuối) thì để "tu_khoa" là [] và "bac_si": true.
- "tu_khoa": 3-5 cụm danh từ NGẮN (2-5 từ, tiếng Việt có dấu, chữ thường) tả VẬT hoặc HÀNH ĐỘNG nhìn thấy được, xếp từ
  sát nghĩa nhất tới rộng dần. Câu dài hoặc kể nhiều ý thì đề xuất đủ cụm cho từng ý (tool nối nhiều clip trong một câu).
  Phong cách từ khóa giống kho đang dùng, ví dụ: {vi_du}.
- Câu KÊU GỌI cuối (nhắn tin / bình luận cho bác sĩ): "tu_khoa" đầu tiên phải là đúng cụm "nhắn tin cho bác sĩ", các cụm
  sau tả hình: "gõ tin nhắn trên điện thoại", "bấm gửi tin nhắn", "hai vợ chồng cùng nhắn tin". KHÔNG dùng từ chỉ mục đích
  ("kêu gọi", "inbox", "tư vấn", "hỏi qua điện thoại") và KHÔNG dùng cụm chung chung ("điện thoại trên tay", "cầm điện thoại",
  "lướt điện thoại") vì kho có nhiều clip xem điện thoại không liên quan.
- "canh": một câu mô tả cảnh để quay nếu kho chưa có.
- Chỉ trả về MỘT mảng JSON, không giải thích, dạng:
  [{{"cau": 1, "tu_khoa": ["nước ngọt có gas", "ly nước đá", "sủi bọt"], "canh": "rót nước ngọt có gas vào ly đá", "bac_si": false}}, ...]

KỊCH BẢN:
{kich_ban}"""


MAU_CAU_HOI_TU_DO = """Bạn là biên tập viên dựng video y khoa ngắn (bác sĩ nói trước ống kính, khán giả là cô chú 45-70 tuổi).
Dưới đây là KỊCH BẢN phần sau của video, đã đánh số câu (câu 1 là câu đầu phần sau, câu cuối là lời kêu gọi).

Nhiệm vụ: chọn những câu nên chèn cảnh minh họa (b-roll) và đề xuất TỪ KHÓA HÌNH ẢNH cho câu đó. Tool sẽ dùng từ khóa
để tìm clip trong kho có sẵn; không tìm thấy thì ghi lại để quay bổ sung, nên cứ đề xuất tự nhiên, không cần biết kho có gì.
Quy tắc bắt buộc:
- ƯU TIÊN THEO VỊ TRÍ: 1/3 ĐẦU kịch bản quan trọng nhất — câu nào có hình ảnh cụ thể thì chọn, cảnh dày để giữ người xem;
  1/3 GIỮA chọn thưa hơn, chỉ câu thật đắt; 1/3 CUỐI gần như không cần, chỉ chọn khi hình ảnh đặc biệt rõ.
- Không chọn câu 1 và câu cuối. Hai câu được chọn cách nhau ít nhất 1 câu. Chọn tối đa {toi_da_canh} câu.
- Ưu tiên câu có hình ảnh cụ thể (hành động, đồ ăn, đồ uống, tư thế, triệu chứng, bối cảnh); bỏ câu nói chung chung.
- Với mỗi câu chọn, "tu_khoa" là 2-4 cụm danh từ NGẮN (2-5 từ, tiếng Việt có dấu, chữ thường) tả VẬT hoặc HÀNH ĐỘNG nhìn
  thấy được, xếp từ sát nghĩa nhất tới rộng dần; "canh" là một câu mô tả cảnh để quay nếu kho chưa có.
  Phong cách từ khóa giống kho đang dùng, ví dụ: {vi_du}.
- Chỉ trả về MỘT mảng JSON, không giải thích, dạng:
  [{{"cau": 3, "tu_khoa": ["nước ngọt có gas", "ly nước đá", "sủi bọt"], "canh": "rót nước ngọt có gas vào ly đá"}}, ...]

KỊCH BẢN:
{kich_ban}"""

# từ nối/từ chức năng (CÓ DẤU) bỏ qua khi so từ khóa của AI với kho — phải giữ dấu: bỏ dấu thì "vận" thành "vẫn",
# "động" thành "đồng", "tư vấn" thành "từ, vẫn"
# (không bỏ "quá", "nhiều", "ít", "sau", "trước": chúng đổi nghĩa — "quá giờ ăn" ≠ "đúng giờ ăn", "sau ăn" ≠ "trước ăn")
STOP_TU = set("và của cho khi lúc bị có một cái chiếc những các là với ở trong để đang thì mà này đó đã "
              "sẽ vẫn cũng hay hoặc lên xuống ra vào từ đến bởi về nên phải".split())


def _tu_co_dau(s: str) -> list[str]:
    """Từ nội dung GIỮ DẤU (chữ thường, bỏ dấu câu, bỏ từ nối). Mọi mức so từng từ đều dùng hàm này."""
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return [t for t in s.split() if t not in STOP_TU]


_tu_noi_dung = _tu_co_dau          # tên cũ


def _vec_ok() -> bool:
    try:
        import vector_kho
        return vector_kho.san_sang()[0]
    except Exception:          # noqa: BLE001
        return False


def doc_da_dung() -> dict[str, int]:
    """Số lần mỗi clip đã dùng ở các tập trước (toàn kênh) -> planner ưu tiên clip ít dùng để các video không trùng cảnh."""
    try:
        d = json.loads(FILE_DA_DUNG.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:          # noqa: BLE001
        return {}


def ghi_da_dung(ids: list[str]) -> None:
    d = doc_da_dung()
    for i in ids:
        d[i] = d.get(i, 0) + 1
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        FILE_DA_DUNG.write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception:          # noqa: BLE001
        pass


def khop_tu_khoa(de_xuat: list[str], kho: list[Clip], vec_nguong: float | None = None,
                 vec_nhom: float | None = None, van_ban: str = "") -> dict | None:
    """So các từ khóa AI đề xuất (theo thứ tự ưu tiên) với kho, 4 mức, dừng ở mức đầu tiên khớp:
      1. ĐÚNG : đề xuất (bỏ dấu, chữ thường) trùng hẳn một từ khóa trong kho (mọi clip có từ khóa đó = một nhóm).
      2. CHỨA : tập từ nội dung (giữ dấu, bỏ từ nối) của đề xuất nằm trong hoặc bao trùm tập từ của một từ khóa kho,
                phía ngắn phải có ≥ 2 từ (vd "ly nước đá lạnh" ⊃ "nước đá lạnh"; "nước ấm" ⊂ "nước lọc ấm").
      3. GẦN  : ≥ 75% từ nội dung của đề xuất có trong clip, TÍNH NẶNG từ trùng ở cột Từ khóa (1), nhẹ từ chỉ có ở
                tên/mô tả (0,5), phải có ≥ 1 từ trùng ở cột Từ khóa và ≥ 2 từ trùng; bỏ từ quá phổ biến trong kho
                (≥ 8% clip); nếu có vector thì kiểm tra chéo nghĩa (dưới ngưỡng − 0,1 là bỏ) -> hết kiểu "bác sĩ tư vấn"
                trúng ảnh mô hình dạ dày vì mô tả có mấy chữ đó (22/10).
      4. NGHĨA: vector câu (vector_kho.py) — đồng nghĩa "ợ nóng" ~ "trào ngược"; so đề xuất (và chữ trong câu `van_ban`,
                hệ số 0,85); nhận khi điểm ≥ vec_nguong (sàn), nhóm = các clip đạt ≥ vec_nhom × điểm cao nhất (planner
                random trong nhóm). Không có torch thì bỏ mức này.
    -> {clips (nhóm ngang nhau), tu_khoa (chuẩn, '' ở mức 3-4), tu_khoa_hien, muc, giai_thich, de_xuat_khop, diem}
       hoặc None nếu không khớp."""
    vec_nguong = VEC_NGUONG_MAC_DINH if vec_nguong is None else float(vec_nguong)
    vec_nhom = VEC_NHOM_MAC_DINH if vec_nhom is None else float(vec_nhom)
    bang: dict[str, list[Clip]] = {}
    hien: dict[str, str] = {}
    for c in kho:
        for k, h in zip(c.tu_khoa, c.tu_khoa_hien):
            bang.setdefault(k, []).append(c)
            hien.setdefault(k, h)
    de_xuat = [d.strip() for d in de_xuat if d and d.strip()]
    for dx in de_xuat:                                            # mức 1
        k = khong_dau(dx)
        if k in bang:
            return dict(clips=bang[k], tu_khoa=k, tu_khoa_hien=hien[k], muc=1, de_xuat_khop=dx,
                        giai_thich=f"khớp đúng từ khóa kho “{hien[k]}”")
    tap_kho = {k: set(_tu_co_dau(hien[k])) for k in bang}        # so từ GIỮ DẤU
    for dx in de_xuat:                                            # mức 2 (đề xuất đứng trước được ưu tiên)
        a = set(_tu_co_dau(dx))
        best = None
        for k, b in tap_kho.items():
            nho, lon = (a, b) if len(a) <= len(b) else (b, a)
            if len(nho) >= 2 and nho <= lon:
                diem = len(nho) / len(lon)
                if best is None or diem > best[0]:
                    best = (diem, k)
        if best:
            k = best[1]
            quan_he = "nằm trong" if a <= tap_kho[k] else "bao trùm"
            return dict(clips=bang[k], tu_khoa=k, tu_khoa_hien=hien[k], muc=2, de_xuat_khop=dx,
                        giai_thich=f"“{dx}” {quan_he} từ khóa kho “{hien[k]}”")
    tap_clip = []                                                 # (clip, từ ở cột Từ khóa, từ ở tên + mô tả)
    for c in kho:
        tk = set(t for k in c.tu_khoa_hien for t in _tu_co_dau(k))
        mt = set(_tu_co_dau(Path(c.ten).stem)) | set(_tu_co_dau(c.mo_ta))
        tap_clip.append((c, tk, mt))
    tan_suat: dict[str, int] = {}                                 # từ có ở bao nhiêu clip -> bỏ từ quá phổ biến
    for _, tk, mt in tap_clip:
        for t in tk | mt:
            tan_suat[t] = tan_suat.get(t, 0) + 1
    pho_bien = {t for t, n in tan_suat.items() if n >= max(3, 0.08 * len(tap_clip))}
    co_vec = _vec_ok()
    ung3: list[tuple] = []                                        # mức 3: (điểm, -i_dx, clip, dx, từ trùng)
    for i_dx, dx in enumerate(de_xuat):
        a = set(_tu_co_dau(dx)) - pho_bien
        if len(a) < 2:
            continue
        for c, tk, mt in tap_clip:
            trung_tk = a & tk
            trung_mt = (a & mt) - tk
            if not trung_tk or len(trung_tk) + len(trung_mt) < 2:
                continue
            diem3 = (len(trung_tk) + 0.5 * len(trung_mt)) / len(a)
            if diem3 >= 0.75:
                ung3.append((diem3, -i_dx, c, dx, trung_tk | trung_mt))
    if ung3:
        ung3.sort(key=lambda x: (x[0], x[1]), reverse=True)
        tot = ung3[0][0]
        nhom = [x for x in ung3 if x[0] >= tot - 0.1 and x[1] == ung3[0][1]][:3]
        if co_vec:                                                # kiểm tra chéo nghĩa, bỏ clip chỉ trùng chữ
            import vector_kho
            dx0 = nhom[0][3]
            vd = vector_kho.diem_tung_clip(dx0, kho)
            giu = [x for x in nhom if vd.get(x[2].id, 1.0) >= vec_nguong - 0.1]
            if not giu:
                ung3 = []                                         # trùng chữ nhưng khác nghĩa -> rơi xuống mức 4
            nhom = giu or nhom
        if ung3:
            _, _, c, dx, chung = nhom[0]
            return dict(clips=[x[2] for x in nhom], tu_khoa="", tu_khoa_hien=dx, muc=3, de_xuat_khop=dx, diem=round(nhom[0][0], 2),
                        giai_thich=f"gần: {len(chung)}/{len(set(_tu_co_dau(dx)) - pho_bien)} từ đặc trưng của “{dx}” "
                                   f"({', '.join(sorted(chung))}) có trong [{', '.join(x[2].id for x in nhom)}]")
    if co_vec and de_xuat:                                        # mức 4: nghĩa
        import vector_kho
        nhom4 = vector_kho.diem(de_xuat, van_ban, kho, nguong=vec_nguong, nhom=vec_nhom, log=lambda s: None)
        if nhom4:
            c, s, gt = nhom4[0]
            dx = next((d for d in de_xuat if f"“{d}”" in gt), de_xuat[0])
            return dict(clips=[x[0] for x in nhom4], tu_khoa="", tu_khoa_hien=dx, muc=4, de_xuat_khop=dx, diem=round(s, 2),
                        giai_thich=f"nghĩa {s:.2f}: {gt} → [{', '.join(x[0].id for x in nhom4)}]")
    return None


NGUONG_GAN_NHAT = 0.2          # điểm tối thiểu để coi một clip là "gần" đề xuất (mức 4, chỉ ở chế độ không clip gốc)


def khop_gan_nhat(de_xuat: list[str], kho: list[Clip], van_ban: str = "", loai_tru: set[str] | None = None,
                  vec_nguong: float | None = None) -> dict | None:
    """Vớt vát khi 4 mức đều trượt (không clip gốc / cần thêm clip): vector nghĩa với ngưỡng thấp hơn 0,15 (so cả đề
    xuất lẫn chữ trong câu), không có vector thì so chữ (_khop_gan_nhat_chu). -> dict như khop_tu_khoa hoặc None."""
    vec_nguong = VEC_NGUONG_MAC_DINH if vec_nguong is None else float(vec_nguong)
    if _vec_ok():
        import vector_kho
        nhom = vector_kho.diem(de_xuat or [], van_ban, kho, loai_tru=loai_tru, nguong=max(0.4, vec_nguong - 0.15),
                               nhom=VEC_NHOM_MAC_DINH, log=lambda s: None)
        if nhom:
            c, s, gt = nhom[0]
            dx = next((d for d in (de_xuat or []) if f"“{d}”" in gt), (de_xuat or [""])[0])
            tkh = dx or (c.tu_khoa_hien[0] if c.tu_khoa_hien else c.ten)
            return dict(clips=[x[0] for x in nhom], tu_khoa=khong_dau(tkh), tu_khoa_hien=tkh, muc=4, de_xuat_khop=dx,
                        diem=round(s, 2), giai_thich=f"gần nhất theo nghĩa {s:.2f}: {gt} → [{', '.join(x[0].id for x in nhom)}]")
    return _khop_gan_nhat_chu(de_xuat, kho, van_ban, loai_tru)


def _khop_gan_nhat_chu(de_xuat: list[str], kho: list[Clip], van_ban: str = "", loai_tru: set[str] | None = None) -> dict | None:
    """Vớt vát bằng so CHỮ (khi không có vector): lấy ĐẠI clip có từ khóa GẦN nhất.
    Chấm điểm từng clip = max theo từng đề xuất của ( tỉ lệ từ nội dung (có trọng số: từ hiếm 1, từ phổ biến 0,3)
    của đề xuất có trong từ khóa + tên + mô tả clip , 0,9 × độ giống chuỗi (difflib, không dấu) với từ khóa kho ),
    đề xuất đứng trước ưu tiên nhẹ; không có đề xuất / đề xuất xa quá thì so chính các từ trong câu (hệ số 0,6).
    -> {clips (tối đa 3 clip điểm ≥ 80% clip tốt nhất), tu_khoa, tu_khoa_hien, muc=4, giai_thich, de_xuat_khop, diem}
    hoặc None khi mọi clip đều dưới NGUONG_GAN_NHAT (gọi chỗ khác tự lấy clip ít dùng nhất)."""
    import difflib
    ung = [c for c in kho if c.id not in (loai_tru or set())]
    if not ung:
        return None
    tap_clip = [(c, set(t for k in c.tu_khoa_hien for t in _tu_co_dau(k)) | set(_tu_co_dau(Path(c.ten).stem))
                 | set(_tu_co_dau(c.mo_ta))) for c in ung]
    tan_suat: dict[str, int] = {}
    for _, tokens in tap_clip:
        for t in tokens:
            tan_suat[t] = tan_suat.get(t, 0) + 1
    pho_bien = {t for t, n in tan_suat.items() if n >= max(3, 0.08 * len(tap_clip))}

    def trong(t: str) -> float:
        return 0.3 if t in pho_bien else 1.0

    de_xuat = [x.strip() for x in (de_xuat or []) if x and x.strip()]
    tu_cau = set(_tu_co_dau(van_ban))
    bang: list[tuple[float, Clip, str, str]] = []                 # (điểm, clip, đề xuất khớp, giải thích)
    for c, tokens in tap_clip:
        diem, dx_khop, ly_do = 0.0, "", ""
        for i, dx in enumerate(de_xuat):
            a = set(_tu_co_dau(dx))
            if not a:
                continue
            chung = a & tokens
            s_tu = sum(trong(t) for t in chung) / sum(trong(t) for t in a)
            kd = khong_dau(dx)
            k_gan, s_chuoi = "", 0.0
            for k, h in zip(c.tu_khoa, c.tu_khoa_hien):
                r = difflib.SequenceMatcher(None, kd, k).ratio()
                if r > s_chuoi:
                    k_gan, s_chuoi = h, r
            if s_chuoi < 0.75:            # giống chuỗi dưới 75% là nhiễu (“kẹt xe buổi sáng” ~ “thay bữa sáng” 62%) -> bỏ
                s_chuoi = 0.0
            s = max(s_tu, 0.9 * s_chuoi) * (1 - 0.05 * i)
            if s > diem:
                diem, dx_khop = s, dx
                ly_do = (f"“{dx}” có {len(chung)} từ ({', '.join(sorted(chung))}) trong clip" if s_tu >= 0.9 * s_chuoi
                         else f"“{dx}” giống từ khóa kho “{k_gan}” {s_chuoi:.0%}")
        if tu_cau:
            chung = (tu_cau & tokens) - pho_bien
            if chung:
                s = 0.6 * sum(trong(t) for t in chung) / sum(trong(t) for t in tu_cau - pho_bien or {"_"})
                if s > diem:
                    diem, dx_khop, ly_do = s, "", f"câu có {len(chung)} từ ({', '.join(sorted(chung))}) trùng clip"
        if diem > 0:
            bang.append((diem, c, dx_khop, ly_do))
    if not bang:
        return None
    bang.sort(key=lambda x: -x[0])
    tot = bang[0][0]
    if tot < NGUONG_GAN_NHAT:
        return None
    chon = [x for x in bang[:3] if x[0] >= 0.8 * tot]
    diem, c, dx, ly_do = chon[0]
    tkh = dx or (c.tu_khoa_hien[0] if c.tu_khoa_hien else c.ten)
    return dict(clips=[x[1] for x in chon], tu_khoa=khong_dau(tkh), tu_khoa_hien=tkh, muc=4, de_xuat_khop=dx, diem=round(diem, 2),
                giai_thich=f"gần nhất (điểm {diem:.2f}): {ly_do} → [{', '.join(x[1].id for x in chon)}]")


def _nha(ten: str):
    import importlib
    return importlib.import_module({"gpt": "hoi_gpt", "claude": "hoi_claude", "gemini": "hoi_gemini"}[ten])


def nha_da_ket_noi(ten: str) -> str:
    """AI `ten` nếu đã đăng nhập; chưa thì AI đầu tiên đã đăng nhập (claude -> gpt -> gemini); không AI nào -> giữ `ten`
    (để lỗi đăng nhập hiện rõ như cũ)."""
    def _ok(t):
        try:
            return bool(_nha(t).trang_thai().get("ket_noi"))
        except Exception:   # noqa: BLE001
            return False
    if _ok(ten):
        return ten
    return next((t for t in ("claude", "gpt", "gemini") if t != ten and _ok(t)), ten)


def _json_trong_tra_loi(text: str):
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b <= a:
        raise ValueError("AI không trả về mảng JSON")
    return json.loads(text[a:b + 1])


CHE_DO_MINH_HOA = ("phu_kin", "diem_xuyet")   # phủ kín (kho làm nền chính) | điểm xuyết (vài cảnh ≤ 6s, cách cũ)
FILE_BO_NHO_AI = "gpt_minh_hoa.json"           # trong thư mục tập: trả lời AI lần trước, chạy lại cùng kịch bản thì dùng lại


def _khoa_bo_nho(nha: str, che_do: str, prompt: str, vi_du: str) -> str:
    """Chữ ký câu hỏi: cùng AI, cùng chế độ, cùng kịch bản đã đánh số câu (đổi cách tách câu là đổi) và cùng mẫu
    câu hỏi. Bỏ phần ví dụ từ khóa lấy mẫu từ kho để thêm clip vào kho không làm hỏi lại."""
    return hashlib.sha1(f"{nha}\n{che_do}\n{prompt.replace(vi_du, '')}".encode("utf-8")).hexdigest()


def _doc_bo_nho(bo_nho: Path, khoa: str, ten_file: str = FILE_BO_NHO_AI) -> dict | None:
    """Trả lời đã nhớ trong <bo_nho>/<ten_file> nếu đúng chữ ký; thiếu/hỏng/khác -> None."""
    try:
        d = json.loads((bo_nho / ten_file).read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return None
    return d if isinstance(d, dict) and d.get("khoa") == khoa and str(d.get("text") or "").strip() else None


def _ghi_bo_nho(bo_nho: Path, d: dict, log: Callable[[str], None], ten_file: str = FILE_BO_NHO_AI) -> None:
    try:
        bo_nho.mkdir(parents=True, exist_ok=True)
        (bo_nho / ten_file).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:                             # noqa: BLE001
        log(f"  không ghi được {ten_file}: {e}")


FILE_BO_NHO_SOAT = "gpt_soat_canh.json"        # trong thư mục tập: AI soát cảnh đã chọn lần trước (cùng bộ cảnh thì dùng lại)

MAU_SOAT_CANH = """Bạn là biên tập viên dựng video y khoa ngắn (bác sĩ nói, khán giả là cô chú 45-70 tuổi). Tool đã chọn clip minh
họa cho từng câu kịch bản bằng cách so từ khóa. Hãy SOÁT LẠI: với MỖI dòng, clip đó chiếu lên đúng lúc câu vang có ăn nhập
với ý câu không?
- "hop": true = đúng ý, hoặc gần nghĩa / ẩn dụ người xem hiểu ngay (ví dụ "ôm bụng đau quặn" cho câu nói về cơn đau).
- "hop": false = cảnh nói chuyện khác, người xem thấy lạc đề (ví dụ câu nói về đường ruột mà chiếu "nằm sấp ép dạ dày").
  Khi đó ghi "canh_can_quay": một câu mô tả cảnh NÊN có trong kho để minh họa đúng câu này (để quay / tìm bổ sung).
- Chỉ trả về MỘT mảng JSON đủ mọi dòng, không giải thích ngoài JSON, dạng:
  [{{"stt": 1, "hop": true, "ly_do": "", "canh_can_quay": ""}}, {{"stt": 2, "hop": false, "ly_do": "ngắn gọn", "canh_can_quay": "…"}}]

CÁC CẢNH:
{danh_sach}"""


def soat_canh_ai(canh: list, nha: str = "gpt", model: str | None = None, log: Callable[[str], None] = print,
                 bo_nho: str | Path | None = None, hoi_lai: bool = False) -> list[dict]:
    """Đưa các cảnh đã chọn cho AI soát lại (user 23/10): clip nào AI thấy KHÔNG hợp câu -> trả về mục "thiếu" (ghi file +
    tab Thiếu của Sheet kho để bổ sung cảnh đúng cho lần sau) và ghi chú vào canh.khop; video vẫn giữ cảnh đã chọn.
    Trả lời nhớ trong <bo_nho>/gpt_soat_canh.json theo chữ ký bộ cảnh. -> [{cau, text, de_xuat, canh, goi_y, clip_sai, ly_do}]."""
    canh = [cn for cn in canh if getattr(cn, "cau", None) is not None]
    if not canh:
        return []
    dong = []
    for i, cn in enumerate(canh, 1):
        cl = cn.clip
        dong.append(f"{i}. Câu: \"{cn.cau.text}\"\n   Từ khóa AI đề xuất: {', '.join(cn.de_xuat) or '(không)'}\n"
                    f"   Clip đã chọn: [{cl.id}] {cl.ten} — từ khóa clip: {', '.join(cl.tu_khoa_hien or [])}"
                    + (f" — mô tả: {cl.mo_ta}" if cl.mo_ta else ""))
    prompt = MAU_SOAT_CANH.format(danh_sach="\n".join(dong))
    khoa = hashlib.sha1(f"{nha}\n{prompt}".encode("utf-8")).hexdigest()
    bo_nho = Path(bo_nho) if bo_nho else None
    cu = _doc_bo_nho(bo_nho, khoa, FILE_BO_NHO_SOAT) if bo_nho and not hoi_lai else None
    if cu:
        ten_ai, text = str(cu.get("nha") or nha.upper()), str(cu["text"])
        log(f"  dùng lại kết quả {ten_ai} soát cảnh lúc {cu.get('luc') or '?'} (cùng bộ cảnh)")
    else:
        m = _nha(nha)
        t0 = time.time()
        r = m.hoi(prompt, model=model)
        ten_ai, text = m.TEN, r.text
        log(f"  {ten_ai} soát lại {len(canh)} cảnh xong {time.time() - t0:.1f}s ({r.model})")
    try:
        ds = _json_trong_tra_loi(text)
    except Exception as e:                             # noqa: BLE001
        log(f"  không đọc được JSON soát cảnh của {ten_ai}: {e}; trả lời: {text[:200]!r}")
        return []
    if bo_nho and not cu:
        _ghi_bo_nho(bo_nho, {"khoa": khoa, "nha": ten_ai, "text": text, "luc": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "prompt": prompt}, log, FILE_BO_NHO_SOAT)
    kq: list[dict] = []
    for d in ds if isinstance(ds, list) else []:
        try:
            i = int(d.get("stt"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 1 <= i <= len(canh) or d.get("hop", True) in (True, "true", 1):
            continue
        cn = canh[i - 1]
        ly_do, can = str(d.get("ly_do") or "").strip(), str(d.get("canh_can_quay") or "").strip()
        cn.khop = (cn.khop + " | " if cn.khop else "") + f"{ten_ai} soát: CHƯA HỢP — {ly_do or '?'}" + (f"; cần: {can}" if can else "")
        log(f"  câu {cn.cau.so}: {ten_ai} thấy [{cn.clip.id}] {cn.clip.ten} chưa hợp ({ly_do or '?'})" + (f" → cần: {can}" if can else "")
            + " → ghi Thiếu")
        if cn.cau.so not in {x["cau"] for x in kq}:
            kq.append({"cau": cn.cau.so, "text": cn.cau.text, "de_xuat": list(cn.de_xuat or []),
                       "canh": f"chọn nhầm [{cn.clip.id}] {cn.clip.ten}" + (f" ({ly_do})" if ly_do else "") + (f" → cần: {can}" if can else ""),
                       "goi_y": can, "clip_sai": cn.clip.id, "ly_do": ly_do})
    if not kq:
        log(f"  {ten_ai} soát lại: {len(canh)} cảnh đều hợp câu")
    return kq


def hoi_ai_chon(cau: list[Cau], tu_khoa: list[str], nha: str = "gpt", model: str | None = None,
                toi_da_canh: int | None = None, log: Callable[[str], None] = print,
                luu_tho: dict | None = None, kho: list[Clip] | None = None, tu_do: bool = True,
                che_do: str = "phu_kin", bo_nho: str | Path | None = None, hoi_lai: bool = False,
                khong_clip_goc: bool = False, vec_nguong: float | None = None, vec_nhom: float | None = None) -> list[dict]:
    """AI chọn câu cần minh họa. vec_nguong / vec_nhom: ngưỡng mức 4 (vector nghĩa), None = mặc định.
    khong_clip_goc=True: thêm luật "không có hình bác sĩ, mọi câu phải có từ khóa, không bac_si" vào prompt phủ kín
    (prompt khác -> bộ nhớ trả lời riêng cho chế độ này).
    che_do="phu_kin" (mặc định): hỏi cho MỌI câu, AI đề xuất 3-5 từ khóa/câu, tool khớp TỪNG đề xuất với kho (nhiều clip
      nối nhau trong một câu); câu AI đánh dấu "bac_si" thì để hình bác sĩ. "diem_xuyet": cách cũ, AI chỉ chọn vài câu
      đắt, mỗi câu một cảnh ≤ 6s.
    tu_do=True (mặc định): KHÔNG gửi danh sách từ khóa kho (càng ngày càng dài); AI tự đề xuất, tool khớp bằng
      khop_tu_khoa() — không khớp thì thành "thiếu" (ghi file + Sheet tab Thiếu). tu_do=False: gửi cả danh sách (chỉ
      có ở chế độ diem_xuyet).
    -> [{"cau", "tu_khoa" (chuẩn, '' nếu không khớp), "tu_khoa_hien", "goi_y", "de_xuat": [..], "canh": str,
         "clips": [Clip] | None (phu_kin: các clip khớp, theo thứ tự đề xuất, không trùng), "khop": str giải thích,
         "bac_si": bool}] theo thứ tự câu.
    luu_tho: dict nhận prompt đã gửi + trả lời thô (text, model, nha, giay; dung_lai = lúc hỏi nếu lấy từ bộ nhớ) cho báo cáo.
    bo_nho: thư mục tập chứa gpt_minh_hoa.json — cùng chữ ký câu hỏi (AI, chế độ, kịch bản đã đánh số) thì dùng lại
      trả lời cũ, không gọi AI; trả lời mới đọc được JSON thì ghi vào đó. hoi_lai=True: bỏ qua bộ nhớ, hỏi mới, ghi đè."""
    if not cau:
        return []
    kich_ban = "\n".join(f"{c.so}. {c.text}" for c in cau)
    buoc = max(1, len(tu_khoa) // 12)
    vi_du = ", ".join(tu_khoa[::buoc][:12]) if tu_khoa else "nước ngọt có gas, ôm bụng, nằm ngay sau ăn"
    if che_do == "phu_kin":
        tu_do = True
        prompt = MAU_CAU_HOI_PHU_KIN.format(vi_du=vi_du, kich_ban=kich_ban)
        if khong_clip_goc:
            prompt = prompt.replace(
                "Quy tắc bắt buộc:",
                "Quy tắc bắt buộc:\n- Video này KHÔNG có hình bác sĩ, toàn bộ là cảnh minh họa: MỌI câu đều phải có \"tu_khoa\", "
                "kể cả câu hỏi khán giả / kêu gọi nhắn tin ở cuối (ví dụ: \"nhắn tin cho bác sĩ\", "
                "\"gõ tin nhắn trên điện thoại\"); KHÔNG dùng \"bac_si\": true.", 1)
    elif tu_do:
        toi_da_canh = toi_da_canh or max(2, len(cau) // 2)
        prompt = MAU_CAU_HOI_TU_DO.format(toi_da_canh=toi_da_canh, vi_du=vi_du, kich_ban=kich_ban)
    else:
        toi_da_canh = toi_da_canh or max(1, len(cau) // 3)
        prompt = MAU_CAU_HOI.format(toi_da_canh=toi_da_canh, tu_khoa=", ".join(tu_khoa) if tu_khoa else "(kho trống)",
                                    kich_ban=kich_ban)
    bo_nho = Path(bo_nho) if bo_nho else None
    khoa = _khoa_bo_nho(nha, che_do, prompt, vi_du)
    cu = _doc_bo_nho(bo_nho, khoa) if bo_nho and not hoi_lai else None
    if cu:                                             # cùng kịch bản -> không hỏi AI, chỉ khớp/xếp lại
        ten_ai, text, model_tl, giay = str(cu.get("nha") or nha.upper()), str(cu["text"]), str(cu.get("model") or ""), 0.0
        log(f"  dùng lại trả lời {ten_ai} lúc {cu.get('luc') or '?'} (cùng kịch bản; {FILE_BO_NHO_AI} trong {bo_nho.name})")
    else:
        m = _nha(nha)
        t0 = time.time()
        r = m.hoi(prompt, model=model)
        ten_ai, text, model_tl, giay = m.TEN, r.text, r.model, round(time.time() - t0, 1)
        log(f"  {ten_ai} chọn từ khóa xong {giay:.1f}s ({model_tl})")
    if luu_tho is not None:
        luu_tho.update(prompt=prompt, text=text, model=model_tl, nha=ten_ai, giay=giay,
                       dung_lai=str(cu.get("luc") or "?") if cu else "")
    try:
        ds = _json_trong_tra_loi(text)
    except Exception as e:
        log(f"  không đọc được JSON của {ten_ai}: {e}; trả lời: {text[:200]!r}")
        return []
    if bo_nho and not cu:                              # trả lời mới và đọc được -> nhớ cho lần chạy lại
        _ghi_bo_nho(bo_nho, {"khoa": khoa, "nha": ten_ai, "model": model_tl, "text": text,
                             "luc": time.strftime("%Y-%m-%d %H:%M:%S"), "prompt": prompt}, log)
    if tu_do and _vec_ok():                           # nhúng gộp mọi đề xuất + câu một lượt (GPU 0,2s) thay vì từng cái
        try:
            import vector_kho
            texts = [str(x).strip() for d in (ds if isinstance(ds, list) else []) if isinstance(d, dict)
                     for x in (d.get("tu_khoa") if isinstance(d.get("tu_khoa"), list) else [])]
            vector_kho.nhung(texts + [c.text for c in cau], log=lambda s: log("  " + s))
        except Exception as e:                         # noqa: BLE001
            log(f"  vector: bỏ qua ({e})")
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
        if tu_do:
            dx = d.get("tu_khoa") or []
            de_xuat = [str(x).strip() for x in (dx if isinstance(dx, list) else re.split(r"[,;/|]", str(dx))) if str(x).strip()]
            canh = str(d.get("canh") or d.get("goi_y") or "").strip()
            bac_si = bool(d.get("bac_si")) and not de_xuat
            if che_do == "phu_kin":
                # khớp TỪNG đề xuất -> chuỗi clip (không trùng) nối nhau trong câu; giải thích từng cái
                clips, giai_thich, thay_clip, tk, tkh, clip_tk = [], [], set(), "", "", {}
                for x in de_xuat:
                    kh = khop_tu_khoa([x], kho or [], vec_nguong, vec_nhom, van_ban=cau[so - 1].text)
                    if not kh:
                        continue
                    tk, tkh = tk or kh["tu_khoa"], tkh or kh["tu_khoa_hien"]
                    them = [c for c in kh["clips"] if c.id not in thay_clip]
                    thay_clip.update(c.id for c in them)
                    clips.extend(them)
                    for c in them:
                        clip_tk[c.id] = kh["tu_khoa_hien"] or x
                    giai_thich.append(kh["giai_thich"] + f" → [{', '.join(c.id for c in kh['clips'])}]")
                if bac_si:
                    kq.append({"cau": so, "tu_khoa": "", "tu_khoa_hien": "", "goi_y": "", "de_xuat": de_xuat, "canh": canh,
                               "clips": None, "khop": "AI để bác sĩ nói trước ống kính", "bac_si": True})
                elif clips:
                    kq.append({"cau": so, "tu_khoa": tk, "tu_khoa_hien": tkh, "goi_y": "", "de_xuat": de_xuat, "canh": canh,
                               "clips": clips, "clip_tk": clip_tk, "khop": "; ".join(giai_thich), "bac_si": False})
                else:
                    kq.append({"cau": so, "tu_khoa": "", "tu_khoa_hien": "", "goi_y": canh or ", ".join(de_xuat),
                               "de_xuat": de_xuat, "canh": canh, "clips": None, "bac_si": False,
                               "khop": "không khớp từ khóa nào trong kho → bác sĩ bù, ghi Thiếu"})
                continue
            kh = khop_tu_khoa(de_xuat, kho or [], vec_nguong, vec_nhom, van_ban=cau[so - 1].text)
            if kh:
                kq.append({"cau": so, "tu_khoa": kh["tu_khoa"], "tu_khoa_hien": kh["tu_khoa_hien"], "goi_y": "",
                           "de_xuat": de_xuat, "canh": canh, "clips": kh["clips"], "khop": kh["giai_thich"], "bac_si": False})
            else:
                kq.append({"cau": so, "tu_khoa": "", "tu_khoa_hien": "", "goi_y": canh or ", ".join(de_xuat),
                           "de_xuat": de_xuat, "canh": canh, "clips": None, "khop": "không khớp từ khóa nào trong kho",
                           "bac_si": False})
            continue
        k = khong_dau(str(d.get("tu_khoa") or ""))
        goi_y = str(d.get("goi_y") or "").strip()
        if k and k not in bang:                   # AI tự chế từ khóa -> coi như kho thiếu
            goi_y, k = goi_y or str(d.get("tu_khoa")), ""
        kq.append({"cau": so, "tu_khoa": k, "tu_khoa_hien": bang.get(k, ""), "goi_y": goi_y, "de_xuat": [], "canh": "",
                   "clips": None, "khop": "khớp đúng từ khóa kho" if k else "AI không chọn được từ khóa trong danh sách",
                   "bac_si": False})
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


TAB_THIEU = "Thiếu"           # tab trong Sheet kho nhận các cảnh AI muốn có mà kho chưa có


def _file_khoa_sa() -> Path | None:
    """File khóa service account để ghi Sheet: env GHEP_VIDEO_SA > service_account.json cạnh tool > của các tool Ads."""
    import os
    ung_vien = [os.environ.get("GHEP_VIDEO_SA"), HERE / "service_account.json"]
    ung_vien += [HERE.parent / "ADS_facebook" / d / "service_account.json" for d in ("fb_ads_noApi", "fb_ads_accounts", "fb_ads_tsAnhDuc")]
    for p in ung_vien:
        if p and Path(p).is_file():
            return Path(p)
    return None


def _goi_y_thieu(t: dict) -> str:
    phan = [", ".join(t.get("de_xuat") or []), t.get("canh") or ""]
    phan = [x for x in phan if x] or [t.get("goi_y") or ""]
    return " — ".join(x for x in phan if x)


def ghi_thieu_sheet(nguon: str, ten_bo: str, thieu: list[dict], log: Callable[[str], None] = print) -> str:
    """Ghi các cảnh thiếu vào tab 'Thiếu' của Sheet kho (cột: Ngày | Tập | Câu số | Nội dung câu | Gợi ý cảnh | Đã bổ sung?).
    Cần service account có quyền Editor trên Sheet (chia sẻ Sheet cho email trong file khóa). Cùng tập + cùng câu đã
    có thì không ghi lại. -> dòng thông báo (ghi được hay vì sao không)."""
    if not thieu:
        return ""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", nguon or "")
    if not m:
        return "kho không phải Google Sheet nên chỉ ghi file thiếu trên máy"
    khoa = _file_khoa_sa()
    if not khoa:
        return "không thấy service_account.json nên chỉ ghi file thiếu trên máy"
    try:
        email = json.loads(khoa.read_text(encoding="utf-8")).get("client_email", "")
    except Exception:                                  # noqa: BLE001
        email = ""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(str(khoa), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        ws = gspread.authorize(creds).open_by_key(m.group(1)).worksheet(TAB_THIEU)
        cu = {(r[1], str(r[2])) for r in ws.get_all_values()[1:] if len(r) > 2}
        rows = [[time.strftime("%Y-%m-%d %H:%M"), ten_bo, t["cau"], t.get("text", ""), _goi_y_thieu(t), ""]
                for t in thieu if (ten_bo, str(t["cau"])) not in cu]
        if rows:
            ws.append_rows(rows, value_input_option="RAW")
        da_co = len(thieu) - len(rows)
        return f"đã ghi {len(rows)} dòng vào Sheet tab '{TAB_THIEU}'" + (f" ({da_co} dòng đã có từ trước)" if da_co else "")
    except Exception as e:                             # noqa: BLE001 — lỗi Sheet không làm hỏng video
        return f"không ghi được Sheet tab '{TAB_THIEU}': {e}" + (f" (chia sẻ Sheet cho {email} quyền Editor)" if email else "")


# ============================================================== 4. kế hoạch cảnh
@dataclass
class Canh:
    start: float                # giây trong video cuối
    end: float
    clip: Clip
    cau: Cau
    tu_khoa: str
    khop: str = ""              # giải thích cách khớp (đúng / chứa / gần) — cho báo cáo
    de_xuat: list[str] = field(default_factory=list)   # từ khóa AI đề xuất cho câu này
    toc_do: float = 1.0         # phủ kín: < 1 = chiếu chậm lại (vd 0.9) để clip 6s vừa trọn câu 6,7s thay vì cắt/lặp


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
        muc_thieu = {"cau": c.so, "text": c.text, "goi_y": d.get("goi_y", ""), "de_xuat": d.get("de_xuat") or [],
                     "canh": d.get("canh", "")}
        if not d["tu_khoa"] and not d.get("clips"):
            if not d.get("bac_si"):
                thieu.append(muc_thieu)
            continue
        if c.so == len(cau):                                    # câu cuối (kêu gọi) để bác sĩ nói; câu đầu được chọn
            continue
        if c.so - cau_truoc <= CACH_CAU:
            continue
        dai = min(c.end - c.start, toi_da_giay)
        if dai < TOI_THIEU_GIAY:
            continue
        if da_dung + dai > ngan_sach:
            log(f"  minh họa: đã đủ {ti_le_toi_da:.0%} thời lượng, bỏ câu {c.so}")
            break
        ds = d.get("clips") or theo_tag.get(d["tu_khoa"]) or []
        if not ds:
            muc_thieu["goi_y"] = muc_thieu["goi_y"] or d["tu_khoa_hien"]
            thieu.append(muc_thieu)
            continue
        khoa_vong = d["tu_khoa"] or "#" + ds[0].id            # cùng từ khóa nhiều clip -> xoay vòng
        vong.setdefault(khoa_vong, rng.randrange(len(ds)))
        clip = ds[vong[khoa_vong] % len(ds)]
        vong[khoa_vong] += 1
        if clip.loai == "video" and clip.thoi_luong and clip.thoi_luong < dai:
            dai = max(TOI_THIEU_GIAY, clip.thoi_luong)
        canh.append(Canh(round(c.start, 3), round(c.start + dai, 3), clip, c, d["tu_khoa_hien"],
                         khop=d.get("khop", ""), de_xuat=d.get("de_xuat") or []))
        da_dung += dai
        cau_truoc = c.so
    return canh, thieu


ANH_GIU_GIAY = 5.0            # phủ kín: ảnh tĩnh giữ tối đa bấy nhiêu giây mỗi lần
TOI_DA_LAP = 1                # (không còn chặn) phủ kín: hết clip khác nhau thì chiếu lại — thà lặp còn hơn hở bác sĩ 1-2 giây
DOAN_TOI_THIEU = 3.0          # phủ kín: không đoạn cảnh nào ngắn hơn bấy nhiêu giây (user: "dưới 3s thì bỏ, kéo 2 clip bên cho chạm")
BS_XEN_TOI_THIEU = 2.5        # xen clip gốc: chỉ rút câu dài từ bấy nhiêu giây làm câu bác sĩ (ngắn hơn chỉ lóe lên giữa hai xfade)
CHAM_TOI_DA = 0.8             # phủ kín: clip được chiếu chậm tới tốc độ này (0.8 = dài thêm 25%) để vừa câu thay vì cắt/lặp
TOC_MH = 1.2                  # phủ kín: tốc độ chiếu clip video minh họa (user 23/10: 1,2× — clip 6s hiện 5s); khi cần phủ dài hơn thì
                              # HẠ tốc độ dần tới CHAM_TOI_DA cho vừa chỗ trống, không đứng hình kéo dài
CANH_GIAY = 5.0               # phủ kín: mỗi cảnh video ≈ bấy nhiêu giây thì đổi cảnh (câu T giây -> ceil(T / CANH_GIAY) clip, chia đều)
DUOI_CHUYEN = 1.0             # phủ kín: sau khi hết cảnh còn phải có bấy nhiêu giây HÌNH THẬT cho hiệu ứng chuyển (xfade 1s), tính vào
                              # tốc độ: toc = cap / (dai + DUOI_CHUYEN), kẹp [CHAM_TOI_DA, TOC_MH]
MANH_CANH_TOI_THIEU = DOAN_TOI_THIEU   # tên cũ


def _cung_tu_khoa(clips: list[Clip], kho_theo_tag: dict[str, list[Clip]], loai_tru: set[str]) -> list[tuple[Clip, str, Clip]]:
    """Vòng 2 khi chuỗi clip khớp chưa đủ dài: clip KHÁC trong kho có chung từ khóa với các clip đã khớp.
    -> [(clip mới, từ khóa chung (hiển thị), clip gốc)], nhiều từ khóa chung xếp trước."""
    diem: dict[str, list] = {}
    for goc in clips:
        for k, h in zip(goc.tu_khoa, goc.tu_khoa_hien):
            for khac in kho_theo_tag.get(k, []):
                if khac.id == goc.id or khac.id in loai_tru:
                    continue
                if khac.id not in diem:
                    diem[khac.id] = [0, khac, h, goc]
                diem[khac.id][0] += 1
    return [(x[1], x[2], x[3]) for x in sorted(diem.values(), key=lambda x: -x[0])]


def _clip_thay_the(d: dict, c: Cau, kho: list[Clip], loai_tru: set[str], so_lan_dung: dict[str, int], rng,
                   vec_nguong: float | None = None) -> tuple[list[Clip], str, str]:
    """Chế độ không clip gốc, câu không khớp kho: clip có từ khóa GẦN nhất (khop_gan_nhat theo đề xuất AI + chữ trong
    câu); không có clip nào gần -> lấy đại clip ÍT DÙNG nhất trong video (hòa thì rút ngẫu nhiên theo seed).
    -> (clips, lý do, từ khóa hiển thị)."""
    gan = khop_gan_nhat(d.get("de_xuat") or [], kho, van_ban=c.text, loai_tru=loai_tru, vec_nguong=vec_nguong)
    if gan:
        return gan["clips"], "lấy " + gan["giai_thich"], gan["tu_khoa_hien"]
    con = [cl for cl in kho if cl.id not in loai_tru]
    if not con:
        return [], "kho không còn clip nào dùng được", ""
    it = min(so_lan_dung.get(cl.id, 0) for cl in con)
    cl = rng.choice([cl for cl in con if so_lan_dung.get(cl.id, 0) == it])
    return [cl], f"không có từ khóa nào gần → lấy đại clip ít dùng nhất [{cl.id}] {cl.ten}", (cl.tu_khoa_hien[0] if cl.tu_khoa_hien else cl.ten)


def len_ke_hoach_phu_kin(cau: list[Cau], chon: list[dict], *, do_dai: Callable[[Clip], float],
                         kho: list[Clip] | None = None, anh_giay: float = ANH_GIU_GIAY, toi_da_lap: int = TOI_DA_LAP,
                         log: Callable[[str], None] = print, kin_het: bool = False,
                         seed: int | None = None, vec_nguong: float | None = None,
                         dem_kenh: dict | None = None, toc_mh: float = TOC_MH, canh_giay: float = CANH_GIAY,
                         duoi_giay: float = DUOI_CHUYEN, xen_bac_si: float = 0.0) -> tuple[list[Canh], list[dict], dict]:
    """PHỦ KÍN: cảnh kho là nền chính của phần sau. Mỗi câu được phủ bằng chuỗi clip khớp theo thứ tự AI đề xuất,
    thời gian câu CHIA ĐỀU cho các clip — không có đoạn nào dưới DOAN_TOI_THIEU (3s) gây nhấp nháy, không hở hình
    bác sĩ giữa hai cảnh:
      - câu ngắn hơn một clip -> một clip, CẮT lấy đoạn đầu cho vừa câu;
      - câu dài hơn -> dùng k clip với k nhỏ nhất sao cho mỗi đoạn = T/k ≤ độ dài clip / CHAM_TOI_DA (clip được KÉO
        chậm tới 25% cho chạm nhau; ảnh giữ ≤ `anh_giay`); nguồn clip theo thứ tự: clip khớp trực tiếp (kể cả cùng
        từ khóa) -> vòng 2: clip khác trong kho có CHUNG từ khóa với clip đã khớp (_cung_tu_khoa) -> vòng 3: clip có
        từ khóa GẦN nhất -> (không clip gốc) vòng 4: clip ít dùng nhất. KHÔNG clip nào đứng hai cảnh liền nhau (trong
        câu lẫn qua câu kế); chỉ khi cả kho không còn clip khác mới buộc lặp (không clip gốc) / để bác sĩ;
      - đoạn chia ra dưới 3s -> bớt clip, các clip còn lại kéo dài ra cho chạm nhau.
    Câu không khớp kho -> bác sĩ + "thiếu"; câu AI đánh dấu bac_si -> bác sĩ. Ưu tiên clip chưa dùng trong video.
    kin_het=True (KHÔNG dùng clip gốc): không câu nào được hở -> câu không khớp / AI để bác sĩ nói vẫn phải có cảnh:
      lấy clip có từ khóa GẦN nhất (khop_gan_nhat), không có thì clip ít dùng nhất (_clip_thay_the); câu vẫn ghi
      "thiếu" để bổ sung kho sau; đuôi câu không còn clip thì kéo cảnh cuối tới hết câu. phu["cau_thay"] = các câu đó.
    do_dai(clip) -> giây thật (tải nếu cần) hoặc theo Sheet; <= 0 = clip hỏng/không tải được -> bỏ qua.
    -> (canh, thieu, phu); phu = {tong, kho, bac_si, cau_bac_si, cau_thieu, cau_thay, khoang_bac_si}; khoang_bac_si =
    các khoảng (start, end) giao cho bác sĩ — ghep_tieude.kin_khoang_trong kéo cảnh phủ mọi chỗ còn lại (quãng nghỉ giữa
    câu) để hai chế độ có/không clip gốc cùng một logic, chỉ khác thứ lấp vào (user 22/10)."""
    import random as _random
    rng = _random.Random(seed)
    dem_kenh = dem_kenh or {}                                    # số lần clip đã dùng ở các tập trước (xoay vòng toàn kênh)
    ngau: dict[str, float] = {}                                  # số ngẫu nhiên cố định theo seed cho từng clip -> random trong nhóm ngang nhau
    theo_cau = {d["cau"]: d for d in chon}
    kho_theo_tag: dict[str, list[Clip]] = {}
    for cl in kho or []:
        for k in cl.tu_khoa:
            kho_theo_tag.setdefault(k, []).append(cl)
    canh, thieu = [], []
    phu = {"tong": 0.0, "kho": 0.0, "bac_si": 0.0, "cau_bac_si": [], "cau_thieu": [], "cau_thay": [],
           "khoang_bac_si": []}                                 # [(start, end)] giây trong video cuối mà kế hoạch giao cho bác sĩ
    clip_truoc = ""
    so_lan_dung: dict[str, int] = {}                             # clip đã chiếu mấy lần trong video này
    hong: set[str] = set()                                       # clip tải lỗi / không đo được -> bỏ cả video
    cap_cache: dict[str, float] = {}

    def cap(cl: Clip) -> float:
        """Độ dài tối đa một đoạn của clip (tải + đo khi cần); 0 = hỏng."""
        if cl.id not in cap_cache:
            co = do_dai(cl)
            if co <= 0:
                hong.add(cl.id)
                log(f"  bỏ clip {cl.ten}: không tải / không đo được")
            cap_cache[cl.id] = 0.0 if co <= 0 else (anh_giay if cl.loai == "anh" else co)
        return cap_cache[cl.id]

    def dai_toi_da(cl: Clip) -> float:
        """Một cảnh của clip dài tối đa bao nhiêu: video chiếu chậm nhất CHAM_TOI_DA vẫn còn DUOI_CHUYEN giây hình thật cho
        hiệu ứng chuyển; ảnh giữ anh_giay."""
        return anh_giay if cl.loai == "anh" else max(1.0, cap(cl) / CHAM_TOI_DA - duoi_giay)

    # XEN CLIP GỐC (user 25/10, chỉ khi có clip gốc): rút ngẫu nhiên theo seed một phần câu để giữ hình bác sĩ thay cảnh kho.
    # Chỉ tiêu = N câu × tỉ lệ (lẻ làm tròn xuống); câu không có cảnh tính vào trước; rút trong các câu không phải câu đầu
    # (sau hook đã là mặt bác sĩ) / câu cuối (kêu gọi giữ cảnh nhắn tin), dài ≥ BS_XEN_TOI_THIEU; lượt 1 không kề câu bác sĩ
    # khác (xen kẽ), thiếu mới cho kề ở lượt 2.
    xen: set[int] = set()
    if xen_bac_si > 0 and not kin_het:
        hop_le = [c for c in cau if c.end - c.start >= 0.3]
        n_cau = len(hop_le)
        chi_tieu = int(n_cau * xen_bac_si + 1e-9)
        bat_buoc = {c.so for c in hop_le if not ((theo_cau.get(c.so) or {}).get("clips") or [])}
        can = max(0, chi_tieu - len(bat_buoc))
        vi_tri = {c.so: i for i, c in enumerate(hop_le)}
        ung = [c for i, c in enumerate(hop_le) if 0 < i < n_cau - 1 and c.so not in bat_buoc and c.end - c.start >= BS_XEN_TOI_THIEU]
        def ke_cua(c: Cau) -> list[int]:
            i = vi_tri[c.so]
            return [x.so for x in hop_le[max(0, i - 1):i] + hop_le[i + 1:i + 2]]

        def diem(bo: set[int]) -> tuple[int, int]:
            """(chuỗi bác sĩ liền nhau dài nhất, số cặp kề nhau) của bộ câu bác sĩ = bắt buộc + bo — càng nhỏ càng xen kẽ."""
            vt = sorted(vi_tri[so] for so in (bat_buoc | bo))
            dai_nhat = run = 1 if vt else 0
            cap_ke = 0
            for a, b in zip(vt, vt[1:]):
                run = run + 1 if b == a + 1 else 1
                cap_ke += b == a + 1
                dai_nhat = max(dai_nhat, run)
            return dai_nhat, cap_ke

        tot, tot_diem = set(), (99, 99)
        for _ in range(12):                                   # thử 12 thứ tự rút (theo seed), giữ bộ xen kẽ đều nhất
            rng.shuffle(ung)
            thu, da = set(), set(bat_buoc)
            for c in ung:                                     # lượt 1: không kề câu bác sĩ nào
                if len(thu) >= can:
                    break
                if not any(so in da for so in ke_cua(c)):
                    thu.add(c.so)
                    da.add(c.so)
            for c in ung:                                     # lượt 2: không đủ chỗ xen kẽ -> cho kề nhau cho đủ chỉ tiêu
                if len(thu) >= can:
                    break
                thu.add(c.so)
            d = diem(thu)
            if d < tot_diem:
                tot, tot_diem = thu, d
        xen = set(tot)
        phu["cau_xen"], phu["xen_ti_le"] = sorted(xen), xen_bac_si
        log(f"  xen clip gốc {xen_bac_si:.0%}: {n_cau} câu -> chỉ tiêu {chi_tieu} câu bác sĩ ({len(bat_buoc)} câu không có cảnh"
            + (f"; rút thêm câu {', '.join(map(str, sorted(xen)))}" if xen else "; không rút thêm") + ")")

    for i_c, c in enumerate(cau):
        T = c.end - c.start
        if T < 0.3:                                               # câu rỗng (đuôi tiêu đề không có audio) -> bỏ
            continue
        phu["tong"] += T
        if c.so in xen:                                           # xen clip gốc: câu này giữ hình bác sĩ, không chọn cảnh kho
            phu["cau_bac_si"].append(c.so)
            phu["bac_si"] += T
            phu["khoang_bac_si"].append((round(c.start, 3), round(c.end, 3)))
            continue
        # cảnh của câu phủ luôn quãng nghỉ tới câu kế (render vẫn kéo cho chạm nhau, nhưng tính ở đây thì tốc độ/số clip đã
        # gồm cả quãng nghỉ -> không đứng hình); câu cuối giữ c.end (render kéo nốt tới hết giọng đọc)
        het = cau[i_c + 1].start if i_c + 1 < len(cau) and 0 < cau[i_c + 1].start - c.end <= 3.0 else c.end
        T2 = het - c.start
        d = dict(theo_cau.get(c.so) or {})
        clips = [cl for cl in (d.get("clips") or []) if cl.id not in hong]
        if not clips:
            if not d.get("bac_si"):
                thieu.append({"cau": c.so, "text": c.text, "goi_y": d.get("goi_y", ""), "de_xuat": d.get("de_xuat") or [],
                              "canh": d.get("canh", "")})
                phu["cau_thieu"].append(c.so)
            if not kin_het:
                phu["cau_bac_si"].append(c.so)
                phu["bac_si"] += T
                phu["khoang_bac_si"].append((round(c.start, 3), round(c.end, 3)))
                continue
            # không clip gốc: không được hở -> lấy đại clip có từ khóa gần nhất (hoặc clip ít dùng nhất)
            clips, ly_do, tkh = _clip_thay_the(d, c, kho or [], hong, so_lan_dung, rng, vec_nguong)
            if not clips:
                phu["cau_bac_si"].append(c.so)
                phu["bac_si"] += T
                phu["khoang_bac_si"].append((round(c.start, 3), round(c.end, 3)))
                continue
            d.update(khop=ly_do, tu_khoa_hien=tkh, clip_tk={cl.id: tkh for cl in clips})
            phu["cau_thay"].append(c.so)
            log(f"  câu {c.so} không khớp kho → {ly_do}")
        # ưu tiên clip CHƯA dùng trong video này (giữ thứ tự AI đề xuất giữa các clip cùng số lần), rồi tránh lặp
        # ngay clip vừa chiếu ở câu trước
        # thứ tự ứng viên: ít dùng trong video này -> ít dùng toàn kênh -> random theo seed (nhóm cùng từ khóa đa dạng giữa các video)
        clips.sort(key=lambda cl: (so_lan_dung.get(cl.id, 0), dem_kenh.get(cl.id, 0), ngau.setdefault(cl.id, rng.random())))
        clip_tk = dict(d.get("clip_tk") or {})
        ghi_chu: dict[str, str] = {}
        nguon = [cl for cl in clips if cap(cl) > 0]              # vòng 1 (tải/đo ngay, bỏ clip hỏng)
        muc_mo_rong = 0      # nguồn đã mở rộng tới đâu: 1 cùng từ khóa, 2 từ khóa gần nhất, 3 clip ít dùng nhất (chỉ không clip gốc)

        def mo_rong() -> bool:
            """Thêm clip vào `nguon` khi chuỗi chưa đủ hoặc chỉ còn clip trùng cảnh trước: vòng 2 (chung từ khóa với clip
            đã khớp) -> vòng 3 (từ khóa gần nhất với đề xuất / chữ trong câu) -> vòng 4 (clip ít dùng nhất, chỉ khi không
            clip gốc). False = hết đường mở rộng."""
            nonlocal muc_mo_rong
            loai_tru = {x.id for x in nguon} | hong
            if muc_mo_rong == 0:
                muc_mo_rong = 1
                them = _cung_tu_khoa(nguon, kho_theo_tag, loai_tru)
                them.sort(key=lambda x: so_lan_dung.get(x[0].id, 0))
                for cl2, h, goc in them:
                    if cap(cl2) > 0:
                        clip_tk[cl2.id] = h
                        ghi_chu[cl2.id] = f"nối thêm: cùng từ khóa “{h}” với [{goc.id}]"
                        nguon.append(cl2)
                return True
            if muc_mo_rong == 1:
                muc_mo_rong = 2
                gan = khop_gan_nhat(d.get("de_xuat") or [], [cl for cl in (kho or []) if cl.id not in loai_tru], van_ban=c.text,
                                    vec_nguong=vec_nguong)
                for cl2 in (gan["clips"] if gan else []):
                    if cap(cl2) > 0:
                        clip_tk[cl2.id] = gan["tu_khoa_hien"]
                        ghi_chu[cl2.id] = "nối thêm: " + gan["giai_thich"]
                        nguon.append(cl2)
                return True
            if muc_mo_rong == 2 and kin_het:
                muc_mo_rong = 3
                con = [cl for cl in (kho or []) if cl.id not in loai_tru]
                if con:
                    it = min(so_lan_dung.get(cl.id, 0) for cl in con)
                    cl2 = rng.choice([cl for cl in con if so_lan_dung.get(cl.id, 0) == it])
                    if cap(cl2) > 0:
                        clip_tk[cl2.id] = cl2.tu_khoa_hien[0] if cl2.tu_khoa_hien else cl2.ten
                        ghi_chu[cl2.id] = "nối thêm: clip ít dùng nhất (không còn clip cùng/gần từ khóa)"
                        nguon.append(cl2)
                return True
            return False

        def chuoi(k: int) -> list[Clip]:
            """k lượt chiếu: KHÔNG clip nào đứng hai cảnh liền nhau (kể cả so với cảnh cuối câu trước — user 21/10);
            ưu tiên clip chưa chiếu trong câu, rồi clip ít dùng trong video, giữ thứ tự AI đề xuất. Thiếu thì mở rộng
            nguồn (mo_rong); hết đường mở rộng -> trả chuỗi ngắn hơn k (người gọi xử lý)."""
            seq: list[Clip] = []
            while len(seq) < k:
                truoc = seq[-1].id if seq else clip_truoc
                ung = [cl for cl in nguon if cl.id != truoc]
                if not ung:
                    if mo_rong():
                        continue
                    break
                trong_seq = {x.id for x in seq}
                ung.sort(key=lambda cl: (cl.id in trong_seq, so_lan_dung.get(cl.id, 0) + sum(1 for x in seq if x.id == cl.id),
                                         dem_kenh.get(cl.id, 0), ngau.setdefault(cl.id, rng.random())))
                seq.append(ung[0])
            return seq

        if not nguon and kin_het:                                 # mọi clip khớp đều hỏng -> vẫn phải có cảnh
            clips2, ly_do, tkh = _clip_thay_the(d, c, kho or [], hong | {cl.id for cl in clips}, so_lan_dung, rng, vec_nguong)
            nguon = [cl for cl in clips2 if cap(cl) > 0]
            if nguon:
                d.update(khop=ly_do, tu_khoa_hien=tkh)
                clip_tk.update({cl.id: tkh for cl in nguon})
                if c.so not in phu["cau_thay"]:
                    phu["cau_thay"].append(c.so)
                log(f"  câu {c.so}: clip khớp hỏng → {ly_do}")
        if not nguon:
            thieu.append({"cau": c.so, "text": c.text, "goi_y": d.get("goi_y", ""), "de_xuat": d.get("de_xuat") or [],
                          "canh": d.get("canh", "")})
            phu["cau_thieu"].append(c.so)
            phu["cau_bac_si"].append(c.so)
            phu["bac_si"] += T
            phu["khoang_bac_si"].append((round(c.start, 3), round(c.end, 3)))
            continue
        # số clip k: ít nhất ceil(T2 / canh_giay) để mỗi cảnh ≈ canh_giay (user 23/10: ~5s là đổi cảnh), tăng thêm tới khi
        # T2/k vừa trong mọi clip (chiếu chậm nhất CHAM_TOI_DA vẫn còn đuôi hình thật); k bị chặn bởi số lượt có được
        k, seq, doan = max(1, math.ceil(T2 / canh_giay - 1e-6)), [], T2
        while True:
            seq = chuoi(k)
            if len(seq) < k:                                      # hết clip: dùng seq ngắn hơn, bác sĩ bù cuối câu
                seq = chuoi(len(seq)) if seq else []
                break
            doan = T2 / k
            if doan <= min(dai_toi_da(x) for x in seq):
                break
            k += 1
        if not seq and nguon:                                     # chỉ còn đúng clip vừa chiếu ở cảnh trước
            if kin_het:                                           # không clip gốc: buộc lặp (kho không còn clip nào khác)
                seq = [nguon[0]]
                log(f"  câu {c.so}: kho không còn clip nào khác, buộc chiếu lại [{nguon[0].id}] liền cảnh trước")
            else:
                log(f"  câu {c.so}: clip khớp [{nguon[0].id}] vừa chiếu ở cảnh trước, không lặp liền → để hình bác sĩ")
        if not seq:
            phu["cau_bac_si"].append(c.so)
            phu["bac_si"] += T
            phu["khoang_bac_si"].append((round(c.start, 3), round(c.end, 3)))
            continue
        n = len(seq)
        if n < k:                                                 # (chỉ khi mọi clip hỏng giữa chừng) kéo các clip còn lại cho kín câu
            doan = T2 / n
        if k > 1 and doan < DOAN_TOI_THIEU:                       # đoạn chia ra dưới 3s -> bớt clip, kéo các clip còn lại cho chạm nhau
            k = max(1, int(T2 // DOAN_TOI_THIEU))
            seq, doan, n = seq[:k], T2 / k, min(k, len(seq))
        t = c.start
        for j, clip in enumerate(seq[:n]):
            dai = doan if j < n - 1 else min(doan, het - t)
            if clip.loai == "anh":
                toc = 1.0
            else:
                # tốc độ = nguồn / (cảnh + đuôi chuyển): clip dài thì chiếu toc_mh (cắt bớt), ngắn thì hạ dần tới CHAM_TOI_DA;
                # ngắn nữa thì bỏ đuôi, chiếu chậm tới 0.4 cho vừa cảnh (render bù khung cuối phần còn thiếu)
                toc = cap(clip) / (dai + duoi_giay)
                toc = min(toc, toc_mh) if toc >= CHAM_TOI_DA else max(min(cap(clip) / dai, CHAM_TOI_DA), 0.4)
            if clip.loai == "anh" and canh and canh[-1].clip.id == clip.id and abs(canh[-1].end - t) < 0.01:
                canh[-1].end = round(t + dai, 3)                  # ảnh tĩnh chiếu lại = giữ tiếp, gộp một cảnh
            else:
                khop = d.get("khop", "") + (f" | {ghi_chu[clip.id]}" if clip.id in ghi_chu else "")
                canh.append(Canh(round(t, 3), round(t + dai, 3), clip, c, clip_tk.get(clip.id, d.get("tu_khoa_hien", "")),
                                 khop=khop, de_xuat=d.get("de_xuat") or [], toc_do=round(toc, 4)))
            phu["kho"] += max(0.0, min(t + dai, c.end) - t)     # chỉ tính phần trong câu (quãng nghỉ không tính vào tổng)
            t += dai
            clip_truoc = clip.id
            so_lan_dung[clip.id] = so_lan_dung.get(clip.id, 0) + 1
        if c.end - t > 0.05:
            if kin_het and canh and canh[-1].cau is c:            # không clip gốc: kéo cảnh cuối cho hết câu
                phu["kho"] += c.end - canh[-1].end
                canh[-1].end = round(c.end, 3)
            else:
                phu["bac_si"] += c.end - t
                phu["khoang_bac_si"].append((round(t, 3), round(c.end, 3)))   # đuôi câu không còn clip -> bác sĩ
                if c.so not in phu["cau_bac_si"]:
                    phu["cau_bac_si"].append(c.so)
    if phu["tong"]:
        log(f"  phủ kín: {phu['kho']:.1f}/{phu['tong']:.1f}s ({phu['kho'] / phu['tong']:.0%}) bằng cảnh kho, "
            f"bác sĩ {phu['bac_si']:.1f}s" + (f" (câu {', '.join(map(str, phu['cau_bac_si']))} không có cảnh)" if phu["cau_bac_si"] else "")
            + (f"; câu {', '.join(map(str, phu['cau_thay']))} lấy clip gần nhất / ít dùng nhất" if phu["cau_thay"] else ""))
    return canh, thieu, phu


def cat_clip_theo_canh(nguon: Path, dich: Path, dai: float, toc_do: float = 1.0, loai: str = "video",
                       log: Callable[[str], None] = print) -> bool:
    """Xuất bản clip ĐÃ CẮT đúng độ dài cảnh (và kéo chậm nếu toc_do < 1), tắt tiếng, 30fps — để kéo vào timeline
    nối đuôi nhau không chồng. Ảnh tĩnh -> mp4 dài `dai` giây. -> True nếu ghi được."""
    import shutil
    import subprocess
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log("  không thấy ffmpeg trên PATH, chép nguyên clip chưa cắt")
        shutil.copy2(nguon, dich)
        return True
    dich = dich.with_suffix(".mp4")
    if loai == "anh":
        cmd = [ffmpeg, "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-t", f"{dai:.3f}", "-i", str(nguon),
               "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p",
               "-r", "30", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(dich)]
    else:
        nguon_giay = dai * toc_do                                  # lấy bấy nhiêu giây nguồn rồi kéo ra `dai`
        vf = ("fps=30," + (f"setpts=PTS/{toc_do:.4f}," if toc_do < 0.999 else "") + "format=yuv420p")
        cmd = [ffmpeg, "-v", "error", "-y", "-t", f"{nguon_giay + 0.2:.3f}", "-i", str(nguon), "-vf", vf,
               "-t", f"{dai:.3f}", "-r", "30", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(dich)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception as e:                                         # noqa: BLE001
        log(f"  cắt clip {nguon.name} lỗi: {e}")
        return False


def _giay_file(p: Path | None) -> float:
    """Thời lượng thật của file video đã tải (ffprobe qua ghep_tieude); lỗi -> 0."""
    if not p:
        return 0.0
    try:
        from ghep_tieude import probe_media
        return float(probe_media(Path(p))[2] or 0.0)
    except Exception:                                  # noqa: BLE001
        return 0.0


# ============================================================== 5. tải clip
def drive_file_id(link: str) -> str | None:
    for p in (r"/file/d/([A-Za-z0-9_-]{20,})", r"[?&]id=([A-Za-z0-9_-]{20,})", r"^([A-Za-z0-9_-]{25,})$"):
        m = re.search(p, link.strip())
        if m:
            return m.group(1)
    return None


def _dich_drive(thu_muc: Path, fid: str, ten: str, loai: str) -> Path:
    """File Drive <fid> sẽ nằm ở đâu trong thư mục video mẫu: <fid><đuôi theo Tên clip, không có thì .mp4/.jpg>."""
    duoi = Path(ten).suffix.lower()
    if duoi not in DUOI_VIDEO + DUOI_ANH:
        duoi = ".jpg" if loai == "anh" else ".mp4"
    return thu_muc / f"{fid}{duoi}"


def tai_clip(clip: Clip, log: Callable[[str], None] = print, dung: Callable[[], bool] | None = None,
             thu_muc: str | Path | None = None) -> Path:
    """Link là file trên máy -> dùng luôn; link Drive -> tải về <thư mục video mẫu>/<id><đuôi> (chỉ tải khi chưa có)."""
    p = Path(clip.link)
    if p.is_file():
        clip.duong_dan = p
        return p
    fid = drive_file_id(clip.link)
    if not fid:
        raise ValueError(f"Link không phải file Drive hay file trên máy: {clip.link}")
    thu_muc = Path(thu_muc) if thu_muc else CACHE_DIR
    thu_muc.mkdir(parents=True, exist_ok=True)
    dest = _dich_drive(thu_muc, fid, clip.ten, clip.loai)
    if not dest.exists():
        import drive_thu_muc as dtm
        log(f"  tải minh họa {clip.ten} ({fid}) ...")
        n = dtm.tai_file(requests.Session(), fid, dest, log=log, dung=dung)
        log(f"    {dest.name} ({n / 1048576:.2f} MB)")
    clip.duong_dan = dest
    return dest


def trang_thai_tu_dong(dong_sheet: list[dict], thu_muc: str | Path | None = None) -> dict:
    """Từ các dòng đã đọc (_doc_dong) + thư mục video mẫu -> trạng thái từng dòng, KHÔNG gọi mạng (GUI tính lại
    mỗi khi file trong thư mục đổi). -> {thu_muc, dong: [...], co, chua_tai, thieu}.
    Mỗi dòng: id, ten, tu_khoa (chuỗi), loai, trang_thai ∈ {file_may, drive_da_tai, drive_chua_tai, link_la, thieu}, file."""
    thu_muc = Path(thu_muc) if thu_muc else CACHE_DIR
    chi_muc = _chi_muc_file(thu_muc)
    dong, dem = [], {"co": 0, "chua_tai": 0, "thieu": 0}
    for d in dong_sheet:
        link, tt, f = d["link"], "thieu", ""
        if link and Path(link).is_file():
            tt, f = "file_may", Path(link).name
        elif link and drive_file_id(link):
            dest = _dich_drive(thu_muc, drive_file_id(link), d["ten"], d["loai"])
            tt, f = ("drive_da_tai", dest.name) if dest.exists() else ("drive_chua_tai", "")
        elif link:
            tt = "link_la"                                      # có link nhưng không phải Drive/file trên máy
        else:
            p = _file_theo_ten(chi_muc, d["id"], d["ten"])
            if p is not None:
                tt, f = "file_may", p.name
        dem["co" if tt in ("file_may", "drive_da_tai") else "chua_tai" if tt == "drive_chua_tai" else "thieu"] += 1
        dong.append(dict(id=d["id"], ten=d["ten"], tu_khoa=", ".join(d["tags"]), loai=d["loai"], trang_thai=tt, file=f,
                         link=link, dong=d["dong"]))
    return {"thu_muc": str(thu_muc), "dong": dong, **dem}


def trang_thai_kho(nguon: str, thu_muc: str | Path | None = None, log: Callable[[str], None] = print,
                   moi: bool = False) -> dict:
    """Đọc Sheet/CSV rồi tính trạng thái từng dòng (xem trang_thai_tu_dong)."""
    return trang_thai_tu_dong(_doc_dong(nguon, log, moi), thu_muc)


def tai_tat_ca(nguon: str, thu_muc: str | Path | None = None, log: Callable[[str], None] = print,
               dung: Callable[[], bool] | None = None) -> dict:
    """Tải trước mọi clip có Link Drive mà thư mục video mẫu chưa có (nút 'Tải video mẫu từ Sheet' trên GUI).
    -> {tai: số file vừa tải, da_co, loi: [chuỗi]}."""
    thu_muc = Path(thu_muc) if thu_muc else CACHE_DIR
    kq = {"tai": 0, "da_co": 0, "loi": []}
    for d in _doc_dong(nguon, log, moi=True):
        if dung and dung():
            kq["loi"].append("đã dừng")
            break
        if not d["link"] or Path(d["link"]).is_file() or not drive_file_id(d["link"]):
            continue
        clip = _lap_clip(d, d["link"])
        try:
            da_co = _dich_drive(thu_muc, drive_file_id(d["link"]), d["ten"], d["loai"]).exists()
            tai_clip(clip, log, dung, thu_muc)
            kq["da_co" if da_co else "tai"] += 1
        except Exception as e:                       # noqa: BLE001 — một file lỗi không chặn file khác
            kq["loi"].append(f"{d['ten']}: {e}")
            log(f"  lỗi tải {d['ten']}: {e}")
    return kq


# ============================================================== tổng hợp
def chuan_bi(tu, *, kho_nguon: str, tong_giay: float, tu_giay: float = 0.0, nha: str = "gpt", model: str | None = None,
             toi_da_giay: float = TOI_DA_GIAY, ti_le_toi_da: float = TI_LE_TOI_DA, seed: int | None = None,
             ten_bo: str = "", log: Callable[[str], None] = print, dung: Callable[[], bool] | None = None,
             thu_muc: str | Path | None = None, luu_tho: dict | None = None, che_do: str = "phu_kin",
             bo_nho: str | Path | None = None, hoi_lai: bool = False, khong_clip_goc: bool = False,
             vec_nguong: float | None = None, vec_nhom: float | None = None, toc_mh: float = TOC_MH,
             soat: bool = True, xen_bac_si: float = 0.0) -> dict:
    """Một phát từ danh sách từ đã có mốc -> cảnh đã tải sẵn. -> {canh, thieu, so_cau, tu_khoa_kho, kho, cau, da_co, phu, loi}.
    khong_clip_goc=True: phần sau KHÔNG có clip bác sĩ -> ép phủ kín và không câu nào được hở (len_ke_hoach_phu_kin kin_het).
    che_do: "phu_kin" (mặc định) = cảnh kho phủ kín phần sau, bác sĩ chỉ bù chỗ không có cảnh; "diem_xuyet" = cách cũ,
    vài cảnh ≤ toi_da_giay trên nền bác sĩ, tổng ≤ ti_le_toi_da.
    thu_muc = thư mục video mẫu (clip tải từ Drive + file tự chép cho dòng chưa có link); None = `video minh họa/` cạnh tool.
    luu_tho: nhận prompt + trả lời thô của AI (xem hoi_ai_chon). Lỗi kho/AI không làm hỏng video: canh=[] kèm 'loi'.
    bo_nho = thư mục tập giữ gpt_minh_hoa.json: chạy lại cùng kịch bản thì dùng lại trả lời AI; hoi_lai=True ép hỏi mới."""
    che_do = "phu_kin" if khong_clip_goc else (che_do if che_do in CHE_DO_MINH_HOA else "phu_kin")
    kq = {"canh": [], "thieu": [], "so_cau": 0, "tu_khoa_kho": [], "kho": [], "cau": [], "da_co": [], "can_quay": [],
          "loi": "", "ai": nha, "che_do": che_do, "khong_clip_goc": khong_clip_goc}
    try:
        kho = doc_kho(kho_nguon, log, thu_muc)
    except Exception as e:
        kq["loi"] = f"không đọc được kho minh họa: {e}"
        log("  " + kq["loi"])
        return kq
    kq["kho"] = kho
    tags = tu_khoa_trong_kho(kho)
    kq["tu_khoa_kho"] = tags
    cau = tach_cau(tu, tu_giay)
    kq["cau"], kq["so_cau"] = cau, len(cau)
    if not kho:
        kq["loi"] = "kho minh họa chưa có clip nào (chưa có Link Drive, thư mục video mẫu cũng không có file trùng tên)"
        log("  " + kq["loi"])
        return kq
    if not cau:                                       # user 21/10: mỗi câu là một cảnh, không còn chặn "ít hơn 3 câu"
        kq["loi"] = "phần sau không có câu nào sau hook"
        return kq
    try:
        chon = hoi_ai_chon(cau, tags, nha, model, log=log, luu_tho=luu_tho, kho=kho, che_do=che_do,
                           bo_nho=bo_nho, hoi_lai=hoi_lai, khong_clip_goc=khong_clip_goc, vec_nguong=vec_nguong, vec_nhom=vec_nhom)
    except Exception as e:
        kq["loi"] = f"AI chọn từ khóa lỗi: {e}"
        log("  " + kq["loi"])
        return kq
    kq["vec"] = _vec_ok()
    if che_do == "phu_kin":
        da_do: dict[str, float] = {}

        def do_dai(cl: Clip) -> float:
            """Tải clip khi cần (kể cả clip vòng 2 cùng từ khóa) rồi đo độ dài thật; lỗi -> 0 (bỏ clip)."""
            if cl.id not in da_do:
                try:
                    tai_clip(cl, log, dung, thu_muc)
                    da_do[cl.id] = (_giay_file(cl.duong_dan) or cl.thoi_luong or toi_da_giay) if cl.loai == "video" else 1.0
                except Exception as e:               # noqa: BLE001
                    log(f"  tải {cl.ten} lỗi: {e}")
                    da_do[cl.id] = 0.0
            return da_do[cl.id]

        ok, thieu, phu = len_ke_hoach_phu_kin(cau, chon, do_dai=do_dai, kho=kho,
                                              anh_giay=min(toi_da_giay, ANH_GIU_GIAY), log=log,
                                              kin_het=khong_clip_goc, seed=seed, vec_nguong=vec_nguong, dem_kenh=doc_da_dung(),
                                              toc_mh=toc_mh, canh_giay=toi_da_giay,
                                              xen_bac_si=0.0 if khong_clip_goc else xen_bac_si)
        kq["phu"] = phu
    else:
        canh, thieu = len_ke_hoach(cau, chon, kho, tong_giay=tong_giay, toi_da_giay=toi_da_giay,
                                   ti_le_toi_da=ti_le_toi_da, seed=seed, log=log)
        ok = []
        for cn in canh:
            try:
                tai_clip(cn.clip, log, dung, thu_muc)
                ok.append(cn)
            except Exception as e:
                log(f"  bỏ cảnh câu {cn.cau.so} ({cn.clip.ten}): {e}")
    if soat and ok and che_do == "phu_kin":
        # AI soát lại cảnh đã chọn: clip chưa hợp câu -> ghi Thiếu (file + Sheet) để bổ sung cảnh đúng cho lần sau; video
        # vẫn dùng cảnh đã chọn (user 23/10). Lỗi AI không làm hỏng video.
        try:
            xau = soat_canh_ai(ok, nha, model, log, bo_nho, hoi_lai)
        except Exception as e:                       # noqa: BLE001
            log(f"  AI soát cảnh lỗi: {e}")
            xau = []
        kq["soat"] = xau
        da = {t["cau"] for t in thieu}
        thieu = thieu + [x for x in xau if x["cau"] not in da]
    kq["thieu"] = thieu
    if thieu:
        ghi_thieu(ten_bo, thieu)
        kq["thieu_sheet"] = ghi_thieu_sheet(kho_nguon, ten_bo, thieu, log)
        log("  kho thiếu: " + "; ".join(f"câu {t['cau']}: {_goi_y_thieu(t) or '?'}" for t in thieu)
            + f"  (ghi vào {FILE_THIEU.name}; {kq['thieu_sheet']})")
    kq["canh"] = ok
    thay: set[str] = set()
    kq["da_co"] = [cn.clip for cn in ok if cn.clip.id not in thay and not thay.add(cn.clip.id)]
    ghi_da_dung([c.id for c in kq["da_co"]])                     # nhớ clip đã dùng để tập sau ưu tiên clip khác
    return kq


def mo_ta_canh(canh: list[Canh]) -> str:
    return " → ".join(f"{c.start:.1f}s {c.tu_khoa} ({c.clip.ten}, {c.end - c.start:.1f}s"
                      + (f", chậm x{c.toc_do:.2f}" if c.toc_do < 0.995 else f", nhanh x{c.toc_do:.2f}" if c.toc_do > 1.005 else "") + ")" for c in canh)


def _phut_giay(s: float) -> str:
    """12.3 -> '00:12.3'; 185.0 -> '03:05.0' (mốc trong video cuối, để tua tới xem)."""
    s = max(0.0, float(s))
    return f"{int(s) // 60:02d}:{s - (int(s) // 60) * 60:04.1f}"


def _link_clip(c: Clip) -> str:
    """Link Drive như trong Sheet; dòng chưa có link (dùng file trùng tên trong thư mục video mẫu) -> ghi file đó."""
    if c.link and not Path(c.link).is_file():
        return c.link
    return f"(Sheet chưa có Link Drive — dùng file trong thư mục video mẫu: {Path(c.link).name if c.link else '?'})"


def bao_cao_da_dung(kq: dict, *, ten_bo: str = "", video_ra: str = "", kho_nguon: str = "",
                    thu_muc_mau: str | Path | None = None, seed: int | None = None, tho: dict | None = None) -> str:
    """File link cạnh video đã ghép: từng cảnh minh họa theo MỐC PHÚT:GIÂY TRONG VIDEO CUỐI (đã gồm hook) kèm
    [ID] tên clip + Link Drive, rồi bảng gộp theo clip (một clip dùng ở nhiều mốc). Xem video thấy cảnh sai thì
    tra mốc đó là biết đang dùng link nào để sửa trong Sheet / thay clip."""
    canh: list[Canh] = kq.get("canh") or []
    L = [f"MINH HỌA ĐÃ DÙNG — {ten_bo}".rstrip(" —"),
         f"Video    : {video_ra or '?'}",
         f"Lúc      : {time.strftime('%Y-%m-%d %H:%M')} · AI chọn từ khóa: {kq.get('ai', '')}"
         + (f" ({tho['model']})" if tho and tho.get("model") else "")
         + (f" — dùng lại trả lời đã nhớ lúc {tho['dung_lai']}" if tho and tho.get("dung_lai") else "")
         + f" · chế độ: {'phủ kín' if kq.get('che_do', 'phu_kin') == 'phu_kin' else 'điểm xuyết'}"
         + (" · KHÔNG dùng clip gốc (phần sau 100% cảnh kho)" if kq.get("khong_clip_goc") else "")
         + (f" · seed {seed}" if seed is not None else ""),
         f"Kho      : {kho_nguon or '?'}",
         f"Clip tải : {Path(thu_muc_mau) if thu_muc_mau else CACHE_DIR}"]
    phu = kq.get("phu")
    if phu and phu.get("tong"):
        L.append(f"Phủ      : {phu['kho']:.1f}/{phu['tong']:.1f}s ({phu['kho'] / phu['tong']:.0%}) bằng cảnh kho, "
                 f"bác sĩ {phu['bac_si']:.1f}s")
    if kq.get("loi"):
        L += ["", "KHÔNG CHÈN CẢNH NÀO: " + kq["loi"]]
    L += ["", f"CẢNH THEO THỨ TỰ TRONG VIDEO ({len(canh)}) — mốc phút:giây trong video cuối (đã gồm hook), "
              "tua tới mốc đó để đối chiếu:"]
    for i, cn in enumerate(canh, 1):
        L += [f"{i:>2}. {_phut_giay(cn.start)} → {_phut_giay(cn.end)} ({cn.end - cn.start:.1f}s"
              + (f", chậm x{cn.toc_do:.2f}" if cn.toc_do < 0.995 else f", nhanh x{cn.toc_do:.2f}" if cn.toc_do > 1.005 else "") + f")  câu {cn.cau.so}"
              + (f" · từ khóa: {cn.tu_khoa}" if cn.tu_khoa else ""),
              f"    [{cn.clip.id}] {cn.clip.ten} ({cn.clip.loai})",
              f"    {_link_clip(cn.clip)}",
              f"    “{cn.cau.text}”"]
    if not canh:
        L.append("  (không có)")
    xen = set((phu or {}).get("cau_xen") or [])
    khong = [so for so in ((phu or {}).get("cau_bac_si") or []) if so not in xen]
    if khong:
        L += ["", "Câu giữ hình bác sĩ (không có cảnh): " + ", ".join(map(str, khong))]
    if xen:
        L += ["", f"Câu xen clip gốc (rút ngẫu nhiên theo seed, tỉ lệ {phu.get('xen_ti_le', 0):.0%}): " + ", ".join(map(str, sorted(xen)))]
    if phu and phu.get("cau_thay"):
        L += ["", "Câu không khớp kho, lấy clip có từ khóa GẦN NHẤT / ít dùng nhất (không clip gốc): "
              + ", ".join(map(str, phu["cau_thay"])) + " — xem cột “từ khóa” của cảnh để kiểm tra, bổ sung kho nếu lệch"]
    # gộp theo clip: một clip có thể dùng ở nhiều mốc -> sửa link / thay clip một lần là đủ
    theo_clip: dict[str, tuple[Clip, list[float]]] = {}
    for cn in canh:
        theo_clip.setdefault(cn.clip.id, (cn.clip, []))[1].append(cn.start)
    if theo_clip:
        L += ["", f"LINK THEO CLIP ({len(theo_clip)}) — [ID] tên · các mốc đã dùng · link:"]
        L += [f"- [{c.id}] {c.ten} · {', '.join(_phut_giay(t) for t in moc)} · {_link_clip(c)}"
              for c, moc in theo_clip.values()]
    thieu = kq.get("thieu") or []
    if thieu:
        L += ["", f"KHO THIẾU — AI muốn minh họa nhưng kho chưa có cảnh khớp ({len(thieu)}):"]
        L += [f"- câu {t['cau']}: “{t['text']}” → {_goi_y_thieu(t) or '?'}" for t in thieu]
    return "\n".join(L) + "\n"


# ============================================================== 6. kế hoạch (không render, không tải)
def lap_ke_hoach(tu, *, kho_nguon: str, tong_giay: float, tu_giay: float = 0.0, nha: str = "gpt",
                 model: str | None = None, toi_da_giay: float = TOI_DA_GIAY, ti_le_toi_da: float = TI_LE_TOI_DA,
                 seed: int | None = None, thu_muc: str | Path | None = None,
                 log: Callable[[str], None] = print, luu_tho: dict | None = None, ten_bo: str = "",
                 che_do: str = "phu_kin", bo_nho: str | Path | None = None, hoi_lai: bool = False,
                 khong_clip_goc: bool = False, vec_nguong: float | None = None, vec_nhom: float | None = None,
                 toc_mh: float = TOC_MH, xen_bac_si: float = 0.0) -> dict:
    """Như chuan_bi nhưng đưa cho AI CẢ dòng kho chưa có video, không tải clip, không render (độ dài clip theo Sheet).
    bo_nho / hoi_lai / khong_clip_goc: như chuan_bi (cùng file gpt_minh_hoa.json, nên kế hoạch và ghép thật dùng chung trả lời AI).
    -> {canh, thieu, cau, so_cau, kho, tu_khoa_kho, can_quay (clip kế hoạch cần mà chưa có video), da_co, phu, loi, ai}"""
    che_do = "phu_kin" if khong_clip_goc else (che_do if che_do in CHE_DO_MINH_HOA else "phu_kin")
    kq = {"canh": [], "thieu": [], "cau": [], "so_cau": 0, "kho": [], "tu_khoa_kho": [], "can_quay": [], "da_co": [],
          "loi": "", "ai": nha, "che_do": che_do, "khong_clip_goc": khong_clip_goc}
    try:
        kho = doc_kho(kho_nguon, log, thu_muc, ca_chua_co=True)
    except Exception as e:
        kq["loi"] = f"không đọc được kho minh họa: {e}"
        log("  " + kq["loi"])
        return kq
    kq["kho"] = kho
    tags = tu_khoa_trong_kho(kho)
    kq["tu_khoa_kho"] = tags
    cau = tach_cau(tu, tu_giay)
    kq["cau"], kq["so_cau"] = cau, len(cau)
    if not kho:
        kq["loi"] = "kho minh họa trống (chưa có dòng từ khóa nào)"
        return kq
    if not cau:                                       # mỗi câu là một cảnh, không chặn theo số câu
        kq["loi"] = "phần sau không có câu nào sau hook"
        return kq
    try:
        chon = hoi_ai_chon(cau, tags, nha, model, log=log, luu_tho=luu_tho, kho=kho, che_do=che_do,
                           bo_nho=bo_nho, hoi_lai=hoi_lai, khong_clip_goc=khong_clip_goc, vec_nguong=vec_nguong, vec_nhom=vec_nhom)
    except Exception as e:
        kq["loi"] = f"AI chọn từ khóa lỗi: {e}"
        log("  " + kq["loi"])
        return kq
    kq["vec"] = _vec_ok()
    if che_do == "phu_kin":
        canh, thieu, phu = len_ke_hoach_phu_kin(cau, chon, do_dai=lambda cl: cl.thoi_luong or toi_da_giay, kho=kho,
                                                anh_giay=min(toi_da_giay, ANH_GIU_GIAY), log=log,
                                                kin_het=khong_clip_goc, seed=seed, vec_nguong=vec_nguong, dem_kenh=doc_da_dung(),
                                              toc_mh=toc_mh, canh_giay=toi_da_giay,
                                              xen_bac_si=0.0 if khong_clip_goc else xen_bac_si)
        kq["phu"] = phu
    else:
        canh, thieu = len_ke_hoach(cau, chon, kho, tong_giay=tong_giay, toi_da_giay=toi_da_giay,
                                   ti_le_toi_da=ti_le_toi_da, seed=seed, log=log)
    kq["canh"], kq["thieu"] = canh, thieu
    if thieu:
        ghi_thieu(ten_bo or "kế hoạch", thieu)
        kq["thieu_sheet"] = ghi_thieu_sheet(kho_nguon, ten_bo or "kế hoạch", thieu, log)
        log("  kho thiếu: " + "; ".join(f"câu {t['cau']}: {_goi_y_thieu(t) or '?'}" for t in thieu)
            + f"  ({kq['thieu_sheet']})")
    thay: set[str] = set()
    for cn in canh:
        if cn.clip.id not in thay:
            thay.add(cn.clip.id)
            (kq["da_co"] if cn.clip.link else kq["can_quay"]).append(cn.clip)
    return kq


def bao_cao_ke_hoach(kq: dict, ten_bo: str = "", tu_giay: float = 0.0, tho: dict | None = None,
                     sao_chep: list[Path] | None = None, thu_muc_bo: Path | None = None) -> str:
    """Văn bản kế hoạch để lưu/đọc: cảnh theo thời gian (khớp Sheet: từ khóa -> dòng MH -> file), clip cần quay/tải,
    kho thiếu, trả lời thô của AI (tho), clip đã sao chép vào thư mục tập (sao_chep). Dùng được cho cả kq của
    lap_ke_hoach (kế hoạch) lẫn chuan_bi (đã tải clip)."""
    kho = kq.get("kho") or []
    canh, thieu = kq.get("canh") or [], kq.get("thieu") or []
    co = sum(1 for c in kho if c.link)
    L = [f"KẾ HOẠCH MINH HỌA — {ten_bo}".rstrip(" —"),
         f"Lúc: {time.strftime('%Y-%m-%d %H:%M')} · AI chọn từ khóa: {kq.get('ai', '')}"
         + (f" ({tho['model']}, {tho['giay']}s)" if tho and tho.get("model") else "")]
    if thu_muc_bo:
        L.append(f"Nguyên liệu: {thu_muc_bo}")
    L += [f"Kho: {len(kho)} dòng từ khóa — {co} dòng đã có video, {len(kho) - co} dòng chưa có.",
          f"Phần sau: {kq.get('so_cau', 0)} câu (câu dài / mục liệt kê đã tách). Chế độ: "
          + ("KHÔNG DÙNG CLIP GỐC — phần sau 100% cảnh kho, câu không khớp lấy clip có từ khóa gần nhất"
             if kq.get("khong_clip_goc") else
             "PHỦ KÍN — cảnh kho là nền chính, bác sĩ chỉ bù chỗ không có cảnh" if kq.get("che_do", "phu_kin") == "phu_kin"
             else "ĐIỂM XUYẾT — vài cảnh ngắn trên nền bác sĩ") + "."]
    phu = kq.get("phu")
    if phu and phu.get("tong"):
        L.append(f"Phủ: {phu['kho']:.1f}/{phu['tong']:.1f}s ({phu['kho'] / phu['tong']:.0%}) bằng cảnh kho; bác sĩ {phu['bac_si']:.1f}s"
                 + (f" — câu không có cảnh: {', '.join(map(str, phu['cau_bac_si']))}" if phu["cau_bac_si"] else "")
                 + (f" — câu lấy clip gần nhất / ít dùng nhất: {', '.join(map(str, phu['cau_thay']))}" if phu.get("cau_thay") else ""))
    if kq.get("loi"):
        L += ["", "LỖI: " + kq["loi"]]
    L += ["", f"CẢNH MINH HỌA ({len(canh)}) — giây tính trong PHẦN SAU (video cuối = hook + phần sau, cộng thêm "
              f"thời lượng hook để ra mốc cuối). Mỗi dòng: từ khóa AI chọn → dòng kho khớp → file:"]
    for i, cn in enumerate(canh, 1):
        if cn.clip.duong_dan:
            tt = f"file: {cn.clip.duong_dan}"
        else:
            tt = "đã có video (chưa tải)" if cn.clip.link else "CHƯA CÓ VIDEO"
        L.append(f"{i:>2}. {cn.start - tu_giay:6.1f}s → {cn.end - tu_giay:6.1f}s ({cn.end - cn.start:.1f}s"
                 + (f", chậm x{cn.toc_do:.2f}" if cn.toc_do < 0.995 else f", nhanh x{cn.toc_do:.2f}" if cn.toc_do > 1.005 else "") + f")  câu {cn.cau.so:<3}"
                 f" → [{cn.clip.id}] {cn.clip.ten}  · {tt}")
        if cn.de_xuat:
            L.append(f"      AI đề xuất: {', '.join(cn.de_xuat)}  →  {cn.khop}")
        elif cn.khop:
            L.append(f"      từ khóa: {cn.tu_khoa}  →  {cn.khop}")
        L.append(f"      “{cn.cau.text}”")
    if not canh:
        L.append("  (không có)")
    can_quay = kq.get("can_quay") or []
    if can_quay:
        L += ["", f"CLIP CẦN QUAY / TẢI CHO VIDEO NÀY ({len(can_quay)}):"]
        L += [f"- [{c.id}] {c.ten} ({c.loai}) — {c.mo_ta}" for c in can_quay]
    if kq.get("da_co"):
        L += ["", f"CLIP ĐÃ CÓ VIDEO ({len(kq['da_co'])}): " + ", ".join(f"[{c.id}] {c.ten}" for c in kq["da_co"])]
    if sao_chep:
        L += ["", f"ĐÃ CẮT SẴN {len(sao_chep)} CLIP ĐÚNG ĐỘ DÀI CẢNH VÀO {sao_chep[0].parent} (đánh số theo thứ tự, tên có giây bắt "
                  f"đầu và độ dài; kéo vào timeline nối đuôi nhau là khớp, không chồng):"]
        L += [f"- {p.name}" for p in sao_chep]
    L += ["", f"KHO THIẾU — AI muốn minh họa nhưng kho chưa có cảnh khớp ({len(thieu)})"
              + (f" — {kq['thieu_sheet']}" if kq.get("thieu_sheet") else "") + ":"]
    L += [f"- câu {t['cau']}: “{t['text']}” → {_goi_y_thieu(t) or '?'}" for t in thieu] or ["  (không)"]
    if tho and tho.get("text"):
        L += ["", f"TRẢ LỜI THÔ CỦA {tho.get('nha', 'AI')} ({tho.get('model', '')})"
                  + (f" — DÙNG LẠI trả lời đã nhớ lúc {tho['dung_lai']} ({FILE_BO_NHO_AI})" if tho.get("dung_lai") else "")
                  + " — AI tự đề xuất tu_khoa + canh cho từng câu, tool khớp với kho (đúng → chứa → gần):",
              tho["text"].strip()[:4000]]
    if tho and tho.get("prompt"):
        L += ["", "PROMPT ĐÃ GỬI (nguyên văn):", "-" * 60, tho["prompt"].rstrip(), "-" * 60]
    if can_quay:
        L += ["", "Cách dùng: quay/tải các clip còn thiếu rồi chép vào thư mục video mẫu, đặt tên trùng ID (vd MH14.mp4) "
                  "hoặc dán Link Drive vào kho; sau đó chạy ghép thật."]
    return "\n".join(L)


# ============================================================== 7. âm thanh hiệu ứng (tab "Âm thanh hiệu ứng")
# Mỗi lần ghep_xfade đổi cảnh bằng một kiểu xfade, render trộn thêm MỘT tiếng hợp kiểu đó. Tab Sheet: ID | Tên file |
# Loại | Từ khóa | Mô tả | Thời lượng | Link Drive | Nguồn | Link nguồn | Ghi chú | Hiệu ứng xfade hợp (cột K: các tên
# kiểu xfade, cách nhau dấu phẩy; MỘT tiếng hợp NHIỀU kiểu — user 19/10/2026). mp3 tải về thư mục video mẫu như clip.
SFX_GID = 1214731593           # gid tab "Âm thanh hiệu ứng" trong Sheet kho Bác sĩ Hội
DUOI_AM_THANH = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


@dataclass
class Sfx:
    id: str
    ten: str
    loai: str
    giay: float                 # thời lượng (cột Thời lượng; 0 = chưa biết, render tự đo)
    link: str                   # Link Drive hoặc file trên máy
    xfade: list[str]            # kiểu xfade (ffmpeg) mà tiếng này hợp — cột K
    duong_dan: Path | None = None
    dinh: float | None = None   # cột "Đỉnh âm (giây)": mốc to nhất trong file, đo MỘT lần rồi ghi lên Sheet (user 24/10);
                                # None = Sheet chưa có -> render đo (ghep_tieude.dinh_am_thanh) rồi ghi lại (ghi_dinh_sfx)


def _cot_sfx(ten: str) -> str:
    k = khong_dau(ten)
    if k.startswith(("id", "ma")):
        return "id"
    if k.startswith("ten"):
        return "ten"
    if k.startswith("loai"):
        return "loai"
    if k.startswith(("thoi luong", "giay")):
        return "giay"
    if k == "link" or k.startswith("link drive"):
        return "link"
    if "xfade" in k or k.startswith("hieu ung"):
        return "xfade"
    if k.startswith(("dinh", "peak")):
        return "dinh"
    return k


def sfx_csv_url(nguon: str) -> str | None:
    """Link Sheet kho (tab nào cũng được) -> link CSV của tab 'Âm thanh hiệu ứng' (gid SFX_GID). Không phải Sheet -> None."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", nguon or "")
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={SFX_GID}" if m else None


def doc_kho_sfx(nguon: str, log: Callable[[str], None] = print, moi: bool = False, cung_sheet: bool = True) -> list[Sfx]:
    """Đọc tab Âm thanh hiệu ứng. nguon = link Sheet kho (cung_sheet=True: lấy tab theo SFX_GID) hoặc link chỉ thẳng
    tab (cung_sheet=False: giữ gid trong link) hoặc file CSV. -> các dòng có Link Drive/file và có cột xfade."""
    nguon = (nguon or "").strip()
    if not nguon:
        return []
    p = Path(nguon)
    if p.is_file():
        text = p.read_text(encoding="utf-8-sig")
    else:
        url = sfx_csv_url(nguon) if cung_sheet else sheet_csv_url(nguon)
        if not url:
            raise ValueError(f"Kho âm thanh phải là link Google Sheet hoặc file CSV: {nguon}")
        text = _tai_csv(url, log, moi)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    cot = [_cot_sfx(c) for c in rows[0]]
    kq = []
    for i, r in enumerate(rows[1:], 2):
        d = {cot[j]: (r[j].strip() if j < len(r) else "") for j in range(len(cot))}
        xf = [x.strip().lower() for x in re.split(r"[,;/|\s]+", d.get("xfade", "")) if x.strip()]
        if not d.get("link") or not xf:
            continue
        try:
            giay = float(str(d.get("giay", "")).replace(",", ".") or 0)
        except ValueError:
            giay = 0.0
        try:
            dinh = float(str(d.get("dinh", "")).replace(",", ".")) if str(d.get("dinh", "")).strip() else None
        except ValueError:
            dinh = None
        kq.append(Sfx(id=d.get("id") or f"dong{i}", ten=d.get("ten") or d.get("id") or f"dong{i}", loai=d.get("loai", ""),
                      giay=giay, link=d["link"], xfade=xf, dinh=dinh))
    return kq


COT_DINH_SFX = "Đỉnh âm (giây)"   # tiêu đề cột ghi mốc đỉnh âm trên tab Âm thanh hiệu ứng (thiếu thì tool tự thêm vào cuối)


def ghi_dinh_sfx(nguon: str, dinh: dict[str, float], log: Callable[[str], None] = print) -> str:
    """Ghi mốc đỉnh âm vừa đo ({id: giây}) vào cột "Đỉnh âm (giây)" của tab Âm thanh hiệu ứng (service account như tab
    Thiếu) để mọi máy dùng chung, không đo lại; cột chưa có thì thêm ở cột trống đầu tiên sau tiêu đề cuối. Lỗi Sheet
    không làm hỏng video -> trả dòng thông báo."""
    if not dinh:
        return ""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", nguon or "")
    khoa = _file_khoa_sa()
    if not m or not khoa:
        return "không ghi được đỉnh âm lên Sheet (không phải Sheet / thiếu service_account.json), chỉ nhớ trên máy"
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(str(khoa), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        ws = gspread.authorize(creds).open_by_key(m.group(1)).get_worksheet_by_id(SFX_GID)
        rows = ws.get_all_values()
        tieu_de = rows[0] if rows else []
        cot = next((j for j, t in enumerate(tieu_de) if _cot_sfx(t) == "dinh"), None)
        if cot is None:
            cot = len(tieu_de)
            ws.update_cell(1, cot + 1, COT_DINH_SFX)
        o = []
        for i, r in enumerate(rows[1:], 2):
            ma = (r[0] if r else "").strip()
            if ma in dinh and (len(r) <= cot or not r[cot].strip()):
                o.append(gspread.Cell(i, cot + 1, dinh[ma]))
        if o:
            ws.update_cells(o, value_input_option="RAW")
        return f"đã ghi đỉnh âm của {len(o)} tiếng lên Sheet tab Âm thanh hiệu ứng"
    except Exception as e:                             # noqa: BLE001
        return f"không ghi được đỉnh âm lên Sheet: {e}"


def _dich_sfx(thu_muc: Path, fid: str, ten: str) -> Path:
    duoi = Path(ten).suffix.lower()
    return thu_muc / f"{fid}{duoi if duoi in DUOI_AM_THANH else '.mp3'}"


def tai_sfx(s: Sfx, log: Callable[[str], None] = print, dung: Callable[[], bool] | None = None,
            thu_muc: str | Path | None = None) -> Path:
    """Link là file trên máy -> dùng luôn; Link Drive -> tải về <thư mục video mẫu>/<id><.mp3> (chỉ tải khi chưa có)."""
    p = Path(s.link)
    if p.is_file():
        s.duong_dan = p
        return p
    fid = drive_file_id(s.link)
    if not fid:
        raise ValueError(f"Link không phải file Drive hay file trên máy: {s.link}")
    thu_muc = Path(thu_muc) if thu_muc else CACHE_DIR
    thu_muc.mkdir(parents=True, exist_ok=True)
    dest = _dich_sfx(thu_muc, fid, s.ten)
    if not dest.exists():
        import drive_thu_muc as dtm
        log(f"  tải âm thanh {s.ten} ({fid}) ...")
        n = dtm.tai_file(requests.Session(), fid, dest, log=log, dung=dung)
        log(f"    {dest.name} ({n / 1024:.0f} KB)")
    s.duong_dan = dest
    return dest


def tai_tat_ca_sfx(kho: list[Sfx], log: Callable[[str], None] = print, dung: Callable[[], bool] | None = None,
                   thu_muc: str | Path | None = None) -> list[Sfx]:
    """Tải mọi tiếng trong kho (file nhỏ, vài chục KB); tiếng tải lỗi thì bỏ, không làm hỏng video. -> tiếng dùng được."""
    ok = []
    for s in kho:
        try:
            tai_sfx(s, log, dung, thu_muc)
            ok.append(s)
        except Exception as e:                       # noqa: BLE001
            log(f"  bỏ âm thanh {s.ten}: {e}")
    return ok


def chon_sfx(kieu: str, kho: list[Sfx], rng, tranh: str = "") -> Sfx | None:
    """Tiếng cho một lần chuyển cảnh kiểu `kieu`: rút ngẫu nhiên (rng theo seed -> chạy lại y hệt) trong các tiếng có
    kiểu đó ở cột K, tránh lặp tiếng vừa dùng (`tranh` = id) khi còn lựa chọn khác. Không tiếng nào hợp -> None (im)."""
    ds = [s for s in kho if s.duong_dan and kieu in s.xfade]
    if len(ds) > 1 and tranh:
        ds = [s for s in ds if s.id != tranh] or ds
    return rng.choice(ds) if ds else None


def mo_ta_sfx(ds: list[dict], so_chuyen: int) -> str:
    """Một dòng cho Nhật ký: ds = info['sfx'] của render (t = mốc chuyển trong video cuối, kieu, id, ten, link, bat_dau)."""
    if not ds:
        return f"{so_chuyen} lần chuyển cảnh, không gắn tiếng"
    return (f"{len(ds)}/{so_chuyen} lần chuyển cảnh có tiếng: "
            + " → ".join(f"{d['t']:.1f}s {d['id']} ({d['kieu']})" for d in ds))


def bao_cao_sfx(ds: list[dict], so_chuyen: int) -> str:
    """Đoạn nối vào file link minh họa: mốc chuyển → kiểu xfade → [ID] tiếng (lúc bắt đầu) → Link Drive."""
    L = ["", f"CHUYỂN CẢNH + ÂM THANH HIỆU ỨNG ({len(ds)}/{so_chuyen} lần chuyển có tiếng) — mốc phút:giây trong video cuối, "
             "kiểu xfade → [ID] tiếng (vào lúc; đỉnh âm đo trong file được căn rơi đúng giữa khoảng chuyển) → Link Drive:"]
    for i, d in enumerate(ds, 1):
        dinh = f", đỉnh ở {d['dinh']:.2f}s → rơi vào {_phut_giay(d['nhan'])}" if "nhan" in d else ""
        L += [f"{i:>2}. {_phut_giay(d['t'])}  {d['kieu']}  →  [{d['id']}] {d['ten']} ({d['giay']:.1f}s, vào {_phut_giay(d['bat_dau'])}{dinh})",
              f"    {d['link']}"]
    if not ds:
        L.append("  (không có)")
    return "\n".join(L) + "\n"


def tai_nguyen_lieu_drive(link: str, goc: Path, log: Callable[[str], None] = print) -> dict:
    """Tải CẢ thư mục Drive của tập về goc\\<tên thư mục Drive = tên kịch bản> (đã có thì dùng lại, chỉ tải file thiếu)
    rồi nhận diện Giọng đọc + Kịch bản theo quy ước tên. -> {ten, thu_muc, audio, kich_ban, files}; thiếu thì None."""
    import drive_thu_muc as dtm
    from ghep_tieude import vai_tro_theo_ten
    ten_tm, thu_muc, files = dtm.tai_thu_muc_theo_ten(link, goc, log=log)
    kq = {"ten": ten_tm, "thu_muc": thu_muc, "audio": None, "kich_ban": None, "files": files}
    for p in files:
        vai, _ = vai_tro_theo_ten(p)
        khoa = {"audio": "audio", "kichban": "kich_ban"}.get(vai or "")
        if khoa and kq[khoa] is None:
            kq[khoa] = p
    return kq


if __name__ == "__main__":        # thử riêng: chọn từ khóa + kế hoạch, không render
    import argparse
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    KHO_MAC_DINH = "https://docs.google.com/spreadsheets/d/1n_rCUBFRCLi5NlDZovoDvHZd3ETCLtjKeLNPxHOAqUY/edit?gid=0#gid=0"
    ap = argparse.ArgumentParser(description="Thử chọn cảnh minh họa (không render). --ke-hoach: kể cả dòng kho chưa có video.")
    ap.add_argument("--kho", default=KHO_MAC_DINH, help="link Google Sheet hoặc file CSV (mặc định: kho Bác sĩ Hội)")
    ap.add_argument("--kich-ban", help="file kịch bản .docx")
    ap.add_argument("--audio", help="giọng đọc (để lấy mốc thời gian từng câu)")
    ap.add_argument("--drive", help="thay cho --kich-ban/--audio: link thư mục Drive của tập, chỉ tải Giọng đọc + Kịch bản")
    ap.add_argument("--ke-hoach", action="store_true", help="chế độ kế hoạch: AI chọn trên CẢ dòng chưa có video, "
                                                            "không tải clip; ghi báo cáo .txt")
    ap.add_argument("--chuan-bi", action="store_true", help="chế độ chuẩn bị: AI chọn trên dòng đã có video, TẢI clip "
                                                            "khớp Sheet về thư mục video mẫu và sao chép vào thư mục "
                                                            "tập\\Minh họa; không render")
    ap.add_argument("--thu-muc-mau", default=None, help="thư mục video mẫu (mặc định 'video minh họa' cạnh tool)")
    ap.add_argument("--out", default=None, help="file báo cáo kế hoạch (mặc định Downloads\\Kế hoạch minh họa - <tên>.txt)")
    ap.add_argument("--ai", default="gpt", choices=["gpt", "claude", "gemini"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=None, help="cố định xoay vòng clip cùng từ khóa")
    ap.add_argument("--che-do", default="phu_kin", choices=list(CHE_DO_MINH_HOA),
                    help="phu_kin = cảnh kho phủ kín phần sau, bác sĩ chỉ bù (mặc định); diem_xuyet = vài cảnh ngắn (cũ)")
    ap.add_argument("--hoi-lai", action="store_true",
                    help=f"hỏi AI mới dù {FILE_BO_NHO_AI} trong thư mục tập đã có trả lời cho đúng kịch bản này (mặc định dùng lại)")
    ap.add_argument("--khong-clip-goc", action="store_true",
                    help="phần sau KHÔNG có clip bác sĩ: ép phủ kín, câu không khớp lấy clip có từ khóa gần nhất (như ghep_tieude --khong-clip-goc)")
    ap.add_argument("--vec-nguong", type=float, default=None, help=f"sàn điểm vector nghĩa (mặc định {VEC_NGUONG_MAC_DINH})")
    ap.add_argument("--vec-nhom", type=float, default=None, help=f"nhóm random: ≥ tỉ lệ này × điểm cao nhất (mặc định {VEC_NHOM_MAC_DINH})")
    a = ap.parse_args()
    import os
    import tempfile
    import viet_sub
    from ghep_tieude import downloads_dir, probe_media, unique_path

    thu_muc_bo: Path | None = None
    if a.drive:
        nl = tai_nguyen_lieu_drive(a.drive, downloads_dir())        # Downloads\<tên kịch bản>\ (đủ 5 file)
        if not nl["audio"] or not nl["kich_ban"]:
            print(f"Thư mục Drive '{nl['ten']}' thiếu {'Giọng đọc' if not nl['audio'] else 'Kịch bản'} theo quy ước tên.")
            sys.exit(2)
        kich_ban, audio, ten_bo, thu_muc_bo = nl["kich_ban"], nl["audio"], nl["ten"], nl["thu_muc"]
    elif a.kich_ban and a.audio:
        kich_ban, audio, ten_bo = Path(a.kich_ban), Path(a.audio), Path(a.audio).stem
    else:
        ap.error("cần --drive <link thư mục> hoặc cả --kich-ban và --audio")
    bo_nho = thu_muc_bo or kich_ban.parent            # gpt_minh_hoa.json nằm cạnh kịch bản của tập
    _, _, D = probe_media(audio)
    srt = Path(tempfile.gettempdir()) / "minh_hoa_thu.srt"
    tk = viet_sub.tao_srt(kich_ban, [(audio, 0.0, None)], D, srt)
    if a.ke_hoach or a.chuan_bi:
        tho: dict = {}
        if a.ke_hoach:
            kq = lap_ke_hoach(tk["tu"], kho_nguon=a.kho, tong_giay=D, nha=a.ai, model=a.model, seed=a.seed,
                              thu_muc=a.thu_muc_mau, luu_tho=tho, ten_bo=ten_bo, che_do=a.che_do,
                              bo_nho=bo_nho, hoi_lai=a.hoi_lai, khong_clip_goc=a.khong_clip_goc, vec_nguong=a.vec_nguong, vec_nhom=a.vec_nhom)
        else:
            kq = chuan_bi(tk["tu"], kho_nguon=a.kho, tong_giay=D, nha=a.ai, model=a.model, seed=a.seed, ten_bo=ten_bo,
                          thu_muc=a.thu_muc_mau, luu_tho=tho, che_do=a.che_do, bo_nho=bo_nho, hoi_lai=a.hoi_lai,
                          khong_clip_goc=a.khong_clip_goc, vec_nguong=a.vec_nguong, vec_nhom=a.vec_nhom)
        sao_chep: list[Path] = []
        if a.chuan_bi and kq["canh"]:                                 # bản CẮT SẴN vào thư mục tập, đánh số theo thứ tự
            import drive_thu_muc as dtm
            dich = (thu_muc_bo or downloads_dir()) / "Minh họa"
            dich.mkdir(parents=True, exist_ok=True)
            for i, cn in enumerate(kq["canh"], 1):
                if cn.clip.duong_dan and Path(cn.clip.duong_dan).is_file():
                    dai = cn.end - cn.start
                    p = (dich / dtm.ten_an_toan(f"{i:02d} - {cn.start:.1f}s - {dai:.1f}s - {cn.clip.id} - {cn.clip.ten}")).with_suffix(".mp4")
                    if not p.exists():
                        cat_clip_theo_canh(Path(cn.clip.duong_dan), p, dai, cn.toc_do, cn.clip.loai, log=print)
                    if p.exists():
                        sao_chep.append(p)
        bao_cao = bao_cao_ke_hoach(kq, ten_bo, tho=tho, sao_chep=sao_chep, thu_muc_bo=thu_muc_bo)
        if a.out:
            out = Path(a.out)
        elif thu_muc_bo:
            out = thu_muc_bo / "Kế hoạch minh họa.txt"
        else:
            out = unique_path(downloads_dir(), f"Kế hoạch minh họa - {ten_bo[:80]}.txt")
        out.write_text(bao_cao, encoding="utf-8")
        print(bao_cao)
        print(f"\nĐã ghi: {out}")
    else:
        kq = chuan_bi(tk["tu"], kho_nguon=a.kho, tong_giay=D, nha=a.ai, model=a.model, seed=a.seed, ten_bo=ten_bo,
                      thu_muc=a.thu_muc_mau, che_do=a.che_do, bo_nho=bo_nho, hoi_lai=a.hoi_lai)
        print("Câu:", kq["so_cau"], "| từ khóa kho:", kq["tu_khoa_kho"])
        print("Cảnh:", mo_ta_canh(kq["canh"]) or "(không)")
        print("Thiếu:", kq["thieu"])
        if kq["loi"]:
            print("Lỗi:", kq["loi"])
    sys.stdout.flush()
    os._exit(0)
