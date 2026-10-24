# -*- coding: utf-8 -*-
"""viet_sub.py - Phụ đề tiếng Việt KHỚP KỊCH BẢN.

Nguyên tắc: kịch bản (docx/txt) là chuẩn về CHỮ; nhận diện giọng nói (faster-whisper,
model large-v3-turbo) chỉ dùng để lấy MỐC THỜI GIAN từng từ. Từ nào máy nghe sai thì vẫn
hiện đúng chữ trong kịch bản; từ nào máy bỏ sót thì nội suy thời gian từ các từ lân cận.

Các bước:
  1. doc_kich_ban()   : đọc docx/txt -> lời đọc (lấy đoạn "Nội dung quay:", bỏ "Tiêu đề:")
  2. nhan_dien()      : nhận diện từng nguồn audio (hook, giọng đọc) kèm offset thời gian
  3. can_chinh()      : so khớp từ kịch bản với từ máy nghe (difflib), gán/nội suy mốc
  4. gom_cau()        : gom từ thành câu phụ đề ngắn (ngắt theo dấu câu, giới hạn ký tự)
  5. ghi_srt()        : ghi file .srt; ghep_tieude.py đốt vào video bằng filter subtitles

Model: tìm theo thứ tự  models/ cạnh tool (bản đóng gói)  ->  ../whisper_cache (máy dev,
dùng chung với GetTextFromLink)  ->  cache Hugging Face mặc định (tự tải ~1,5 GB lần đầu).
Model nạp xong được giữ suốt phiên, KHÔNG del (ctranslate2 có thể abort 0xC0000409 khi hủy
model GPU); chương trình gọi os._exit() lúc kết thúc để bỏ qua bước hủy.

Đóng gói gửi người khác: copy thư mục snapshot của model vào GoogleFlowGhepVideo/models/
(giữ nguyên cấu trúc models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/...), cài
faster-whisper (kèm ctranslate2); máy không có GPU NVIDIA thì tự chạy CPU int8 (chậm hơn).
"""
from __future__ import annotations

import difflib
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_MAC_DINH = "large-v3-turbo"
THU_MUC_MODEL = [HERE / "models", HERE.parent / "whisper_cache"]   # ưu tiên từ trên xuống

TOC_DO_UOC = 0.30      # giây/từ dùng khi phải ước lượng mốc ở đầu/cuối (không có từ neo)
CUE_TOI_DA = 46        # số ký tự tối đa một câu phụ đề (libass tự xuống 2 dòng)
CUE_TOI_DA_HOA = 34    # kiểu karaoke chữ IN HOA rộng hơn ~30% -> câu ngắn hơn để vẫn tối đa 2 dòng
KIEU_SUB = ("karaoke", "thuong")   # karaoke = in hoa, trắng viền đen đậm, từ đang đọc tô vàng (ASS) | thuong = SRT như cũ
MAU_NHAN = "&H00FFFF&"             # màu từ đang đọc, ASS ghi BGR: 00FFFF = vàng
VIEN_KARAOKE = 2.5                 # độ dày viền đen theo thang 288 (2,5 ~ 17px trên video 1920; kiểu thường là 2)
CUE_NGAN_NHAT = 0.9    # giây, câu phụ đề ngắn hơn thì kéo dài ra
CUE_DEM_SAU = 0.15     # giây cộng thêm sau từ cuối
DAU_HET_CAU = ".?!:;…"
SO_CHU = {"0": "khong", "1": "mot", "2": "hai", "3": "ba", "4": "bon", "5": "nam",
          "6": "sau", "7": "bay", "8": "tam", "9": "chin", "10": "muoi"}

_models: dict = {}      # tên -> WhisperModel, giữ suốt phiên


# ============================================================== 1. kịch bản
def doc_kich_ban(path: Path) -> str:
    """docx/txt -> lời đọc. Có đoạn 'Nội dung (quay):' thì lấy đoạn đó (bỏ nhãn);
    không có thì ghép mọi đoạn trừ đoạn 'Tiêu đề:'."""
    if path.suffix.lower() == ".docx":
        from xml.etree import ElementTree as ET
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
        paras = ["".join(x.text or "" for x in p.iter(w + "t")) for p in root.iter(w + "p")]
    else:
        paras = path.read_text(encoding="utf-8-sig").splitlines()
    paras = [p.strip() for p in paras if p.strip()]
    noi_dung = [re.sub(r"^\s*nội dung(?:\s+quay)?\s*:\s*", "", p, flags=re.I)
                for p in paras if re.match(r"^\s*nội dung", p, re.I)]
    if noi_dung:
        return " ".join(noi_dung)
    return " ".join(p for p in paras if not re.match(r"^\s*tiêu đề\s*:", p, re.I))


# ============================================================== 2. từ & khóa so khớp
@dataclass
class Tu:
    hien: str                       # chữ hiển thị (giữ dấu câu, hoa thường)
    khoa: str                       # khóa so khớp: thường, bỏ dấu thanh, bỏ dấu câu
    start: float | None = None
    end: float | None = None
    khop: bool = False              # True = lấy mốc trực tiếp từ máy nghe


def khoa(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower()).replace("đ", "d")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]", "", s)
    return SO_CHU.get(s, s)


def tach_tu(text: str) -> list[Tu]:
    """Tách kịch bản thành từ; mẩu chỉ có dấu câu (– " ...) dính vào từ trước."""
    tu: list[Tu] = []
    for raw in text.split():
        k = khoa(raw)
        if not k and tu:
            tu[-1].hien += raw
            continue
        if k:
            tu.append(Tu(hien=raw, khoa=k))
    return tu


# ============================================================== 3. nhận diện
def nap_model(ten: str = MODEL_MAC_DINH, thu_muc: Path | None = None, log=print):
    """Nạp faster-whisper một lần cho cả phiên. GPU NVIDIA -> float16, không thì CPU int8."""
    if ten in _models:
        return _models[ten]
    import ctranslate2
    from faster_whisper import WhisperModel
    gpu = ctranslate2.get_cuda_device_count() > 0
    device, ctype = ("cuda", "float16") if gpu else ("cpu", "int8")
    root = thu_muc or next((d for d in THU_MUC_MODEL if d.is_dir()), None)
    log(f"Nạp model {ten} ({'GPU ' + ctype if gpu else 'CPU ' + ctype}; cache: {root or 'HF mặc định'})...")
    t0 = time.time()
    m = WhisperModel(ten, device=device, compute_type=ctype,
                     download_root=str(root) if root else None)
    log(f"  xong {time.time() - t0:.1f}s")
    _models[ten] = m
    return m


def nhan_dien(nguon: list[tuple[Path, float, float | None]], ten_model: str = MODEL_MAC_DINH,
              thu_muc_model: Path | None = None, log=print) -> list[tuple[str, float, float]]:
    """nguon = [(file audio/video, offset giây trong video cuối, chỉ lấy tới giây thứ N hoặc None)].
    Trả về danh sách (từ, start, end) đã cộng offset, theo thứ tự thời gian."""
    m = nap_model(ten_model, thu_muc_model, log)
    out: list[tuple[str, float, float]] = []
    for path, offset, gioi_han in nguon:
        t0 = time.time()
        kw = dict(language="vi", beam_size=5, word_timestamps=True, vad_filter=True,
                  vad_parameters=dict(min_silence_duration_ms=300), condition_on_previous_text=False)
        if gioi_han:
            kw["clip_timestamps"] = f"0,{gioi_han:.2f}"
        segs, _ = m.transcribe(str(path), **kw)
        n = 0
        for s in segs:
            for w in s.words or []:
                if khoa(w.word):
                    out.append((w.word.strip(), w.start + offset, w.end + offset))
                    n += 1
        log(f"  nhận diện {path.name}: {n} từ, {time.time() - t0:.1f}s")
    out.sort(key=lambda x: x[1])
    return out


# ============================================================== 4. căn chỉnh
def can_chinh(tu: list[Tu], asr: list[tuple[str, float, float]], tong_dai: float) -> dict:
    """Gán mốc thời gian cho từng từ kịch bản. Từ khớp -> mốc trực tiếp; từ bị nghe sai nhưng
    cùng vị trí -> mốc của từ máy nghe tương ứng; từ máy bỏ sót -> nội suy giữa hai từ neo."""
    a = [t.khoa for t in tu]
    b = [khoa(w) for w, _, _ in asr]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    n_khop = n_thay = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                tu[i1 + k].start, tu[i1 + k].end, tu[i1 + k].khop = asr[j1 + k][1], asr[j1 + k][2], True
            n_khop += i2 - i1
        elif tag == "replace" and j2 > j1:       # nghe sai chữ nhưng có từ ở đúng chỗ -> mượn mốc
            na, nb = i2 - i1, j2 - j1
            for k in range(na):
                j = j1 + min(nb - 1, int(k * nb / na))
                tu[i1 + k].start, tu[i1 + k].end = asr[j][1], asr[j][2]
            n_thay += na
        # 'delete' (kịch bản có, máy không nghe) -> để None rồi nội suy; 'insert' (máy nghe thừa) -> bỏ

    # nội suy các từ chưa có mốc
    n = len(tu)
    i = 0
    while i < n:
        if tu[i].start is not None:
            i += 1
            continue
        j = i
        while j < n and tu[j].start is None:
            j += 1
        trai = tu[i - 1].end if i > 0 else None
        phai = tu[j].start if j < n else None
        so = j - i
        if trai is None and phai is None:
            trai, phai = 0.0, min(tong_dai, so * TOC_DO_UOC)
        elif trai is None:
            trai = max(0.0, phai - so * TOC_DO_UOC)
        elif phai is None:
            phai = min(tong_dai, trai + so * TOC_DO_UOC)
        if phai < trai:
            phai = trai
        nang = [max(1, len(t.khoa)) for t in tu[i:j]]
        tong = sum(nang)
        t = trai
        for k, w in enumerate(nang):
            d = (phai - trai) * w / tong
            tu[i + k].start, tu[i + k].end = t, t + d
            t += d
        i = j
    # ép đơn điệu: mốc sau không được sớm hơn mốc trước
    for k in range(1, n):
        if tu[k].start < tu[k - 1].end - 0.02:
            tu[k].start = tu[k - 1].end
        if tu[k].end < tu[k].start:
            tu[k].end = tu[k].start + 0.05
    return dict(tong=n, khop=n_khop, muon=n_thay, noi_suy=n - n_khop - n_thay)


# ============================================================== 5. gom câu + srt
@dataclass
class Cue:
    start: float
    end: float
    text: str
    tu: list = field(default_factory=list)


def _do_dai(ws: list[Tu]) -> int:
    return len(" ".join(t.hien for t in ws))


def _chia_can_bang(ws: list[Tu], toi_da: int) -> list[list[Tu]]:
    """Câu dài hơn toi_da -> chia đôi tại điểm gần giữa (ưu tiên sau dấu phẩy ở 1/4..3/4 câu),
    đệ quy tới khi mọi mẩu đủ ngắn. Tránh để một hai từ lẻ loi ở cuối."""
    if _do_dai(ws) <= toi_da or len(ws) < 2:
        return [ws]
    tong = _do_dai(ws)
    # vị trí ký tự kết thúc của từng từ
    vi_tri, c = [], 0
    for t in ws:
        c += len(t.hien)
        vi_tri.append(c)
        c += 1
    giua = tong / 2
    ung_vien = [i for i in range(len(ws) - 1) if ws[i].hien.endswith(",") and tong / 4 <= vi_tri[i] <= 3 * tong / 4]
    if not ung_vien:
        ung_vien = [i for i in range(len(ws) - 1) if 1 <= i <= len(ws) - 3] or [0]
    cat = min(ung_vien, key=lambda i: abs(vi_tri[i] - giua))
    return _chia_can_bang(ws[:cat + 1], toi_da) + _chia_can_bang(ws[cat + 1:], toi_da)


def gom_cau(tu: list[Tu], toi_da: int = CUE_TOI_DA) -> list[Cue]:
    """Tách theo dấu hết câu (. ? ! : ; …), câu dài thì chia cân bằng, rồi gán thời gian."""
    cau: list[list[Tu]] = []
    hien: list[Tu] = []
    for t in tu:
        hien.append(t)
        if t.hien.rstrip('"”’)').endswith(tuple(DAU_HET_CAU)):
            cau.append(hien); hien = []
    if hien:
        cau.append(hien)
    cues: list[Cue] = []
    for ws in cau:
        for mau in _chia_can_bang(ws, toi_da):
            cues.append(Cue(mau[0].start, mau[-1].end, " ".join(t.hien for t in mau), list(mau)))
    # thời gian: đệm sau, tối thiểu CUE_NGAN_NHAT, không đè lên câu sau
    for i, c in enumerate(cues):
        c.end = max(c.end + CUE_DEM_SAU, c.start + CUE_NGAN_NHAT)
        if i + 1 < len(cues):
            c.end = min(c.end, cues[i + 1].start - 0.05)
            if c.end <= c.start:
                c.end = c.start + 0.3
    return cues


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def ghi_srt(cues: list[Cue], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{_ts(c.start)} --> {_ts(c.end)}\n{c.text}\n\n")


def _ts_ass(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ghi_ass(cues: list[Cue], path: Path, W: int, H: int, font: str = "Arial", co: float = 11, le_duoi: int = 45,
            hoa: bool = True, mau_nhan: str = MAU_NHAN, vien: float = VIEN_KARAOKE) -> int:
    """Phụ đề ASS kiểu karaoke: cả câu chữ trắng viền đen đậm (IN HOA nếu `hoa`), TỪ ĐANG ĐỌC tô màu `mau_nhan`.
    Mỗi từ một dòng Dialogue [mốc từ, mốc từ kế) chứa nguyên câu, chỉ từ đó mang thẻ màu -> chữ đứng yên, màu chạy.
    PlayRes = kích thước video; cỡ chữ / lề / viền quy từ thang 288 (giống force_style) để cùng số thì cùng cỡ.
    Trả về số dòng Dialogue."""
    ky, kx = H / 288, W / 384
    size, outline, shadow = round(co * ky), round(vien * ky), round(1 * ky)
    mv, ml = round(le_duoi * ky), round(25 * kx)
    dong = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Sub,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{outline},{shadow},2,{ml},{ml},{mv},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def chu(s: str) -> str:
        s = s.upper() if hoa else s
        return s.replace("{", "(").replace("}", ")")      # ngoặc nhọn là thẻ ASS

    n = 0
    for c in cues:
        ws = [t for t in c.tu if t.start is not None]
        if not ws:
            dong.append(f"Dialogue: 0,{_ts_ass(c.start)},{_ts_ass(c.end)},Sub,,0,0,0,,{chu(c.text)}")
            n += 1
            continue
        tu_hien = [chu(t.hien) for t in ws]
        moc = [min(max(float(t.start), c.start), c.end) for t in ws]
        for i in range(len(ws)):
            a = moc[i] if i > 0 else c.start                   # từ đầu sáng ngay từ lúc câu hiện
            b = moc[i + 1] if i + 1 < len(ws) else c.end
            if b - a < 0.01:
                continue
            text = " ".join(f"{{\\c{mau_nhan}}}{w}{{\\r}}" if j == i else w for j, w in enumerate(tu_hien))
            dong.append(f"Dialogue: 0,{_ts_ass(a)},{_ts_ass(b)},Sub,,0,0,0,,{text}")
            n += 1
    path.write_text("\n".join(dong) + "\n", encoding="utf-8-sig")
    return n


def force_style(font: str = "Arial", co: float = 11, le_duoi: int = 45) -> str:
    """Chuỗi force_style cho filter subtitles. Kích thước tính trên PlayResY=288 của SRT->ASS,
    libass tự phóng theo chiều cao video (1920 -> nhân ~6,7: co 11 ~ 73px, le_duoi 45 ~ 300px)."""
    return (f"FontName={font},FontSize={co:g},Bold=1,PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,"
            f"Alignment=2,MarginV={le_duoi},MarginL=25,MarginR=25,WrapStyle=0")


# ============================================================== tổng hợp
def tao_srt(kich_ban: Path, nguon: list[tuple[Path, float, float | None]], tong_dai: float,
            out_srt: Path, ten_model: str = MODEL_MAC_DINH, thu_muc_model: Path | None = None,
            bo_truoc: float = 0.0, log=print, toi_da_cau: int = CUE_TOI_DA) -> dict:
    """Kịch bản + các nguồn audio -> file .srt. Trả về thống kê khớp (+ `tu` từng từ có mốc, `cues` các câu
    để ghi_ass kiểu karaoke).
    `bo_truoc`: không ghi phụ đề trước giây này (vd = thời lượng hook: 10s đầu đã có tiêu đề + ảnh
    minh họa nên để sạch). Hook vẫn được nhận diện để căn đúng mốc phần kịch bản của nó, chỉ bỏ
    lúc ghi ra. `toi_da_cau`: số ký tự tối đa một câu phụ đề (karaoke in hoa dùng CUE_TOI_DA_HOA)."""
    text = doc_kich_ban(kich_ban)
    tu = tach_tu(text)
    if not tu:
        raise ValueError(f"Kịch bản rỗng: {kich_ban}")
    log(f"Kịch bản: {len(tu)} từ")
    asr = nhan_dien(nguon, ten_model, thu_muc_model, log)
    tk = can_chinh(tu, asr, tong_dai)
    cues = gom_cau(tu, toi_da_cau)
    bo = 0
    if bo_truoc > 0:
        giu = []
        for c in cues:
            if c.end <= bo_truoc:
                bo += 1
                continue
            if c.start < bo_truoc:          # câu vắt qua mốc -> cắt phần đầu
                c.start = bo_truoc
            giu.append(c)
        cues = giu
    ghi_srt(cues, out_srt)
    # trả cả danh sách từ đã có mốc để bước khác dùng (minh_hoa.py: ghép cảnh minh họa theo câu)
    tk.update(cau=len(cues), bo=bo, srt=str(out_srt), tu=tu, cues=cues)
    log(f"Khớp: {tk['khop']}/{tk['tong']} từ trùng máy nghe, {tk['muon']} từ máy nghe sai (lấy chữ kịch bản), "
        f"{tk['noi_suy']} từ nội suy; {len(cues)} câu phụ đề"
        + (f" (bỏ {bo} câu trước giây {bo_truoc:g} vì thuộc hook)" if bo_truoc > 0 else "") + f" -> {out_srt.name}")
    return tk


if __name__ == "__main__":      # chạy riêng để thử: python viet_sub.py kichban.docx audio.mp3 [out.srt]
    import sys
    kb, au = Path(sys.argv[1]), Path(sys.argv[2])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else au.with_suffix(".srt")
    import subprocess, shutil, json
    dur = float(json.loads(subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                                           "-of", "json", str(au)], capture_output=True, text=True).stdout)["format"]["duration"])
    tao_srt(kb, [(au, 0.0, None)], dur, out)
    sys.stdout.flush()
    import os
    os._exit(0)
