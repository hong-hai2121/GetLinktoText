# -*- coding: utf-8 -*-
"""Tìm clip kho theo NGHĨA bằng vector câu (sentence embedding) chạy trên máy — mức 4 của bộ khớp từ khóa (minh_hoa.py).
Model sentence-transformers/paraphrase-multilingual-mpnet-base-v2 (đa ngôn ngữ, ~1,1 GB, tải một lần vào cache Hugging
Face), nạp bằng transformers + torch đã có trong venv (không cài thêm gì; GPU nếu có, CPU vẫn chạy).
Dải điểm đo thử 22/10/2026: cảnh đúng 0,74–1,0, cảnh không liên quan 0,30–0,50 -> sàn NGUONG 0,70; nhóm "trùng" để random
= các clip đạt ≥ NHOM (90%) điểm cao nhất và vượt sàn.
Mỗi clip có nhiều vector: MỖI từ khóa một vector (so chính), và một vector "tên + mô tả" (so phụ, nhân 0,9) — để
"bác sĩ tư vấn" không trúng ảnh mô hình dạ dày chỉ vì mô tả có mấy chữ đó.
Cache vector theo văn bản ở video minh họa\\vector_kho.npz: chỉ tính dòng mới / dòng đổi chữ."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "video minh họa"
CACHE = CACHE_DIR / "vector_kho.npz"
MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
NGUONG = 0.70            # sàn: điểm cosine tối thiểu để coi là "cùng nghĩa" (thử 22/10: đúng 0,89–1,0; lệch kiểu "kẹt xe"~"cứng khớp buổi sáng" 0,74)
NHOM = 0.97              # clip đạt ≥ 97% điểm cao nhất (user 23/10: 90% rộng quá) (và vượt sàn) thì cùng nhóm -> planner random giữa chúng (user chốt 22/10)
HE_SO_MO_TA = 0.9        # vector tên + mô tả chỉ là phụ
TOI_DA_NHOM = 4          # nhóm trả về tối đa bấy nhiêu clip

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_st: dict = {"model": None, "tok": None, "dev": "", "vec": {}, "cache_doc": False, "loi": ""}


def san_sang() -> tuple[bool, str]:
    """(dùng được không, mô tả/lý do). Chỉ kiểm tra thư viện, không nạp model."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"thiếu torch/transformers trong venv ({e}) — bỏ mức vector, dùng so chữ"
    return True, MODEL


def _nap(log: Callable[[str], None] = print) -> bool:
    if _st["model"] is not None:
        return True
    if _st["loi"]:
        return False
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
        t0 = time.time()
        tok = AutoTokenizer.from_pretrained(MODEL)
        model = AutoModel.from_pretrained(MODEL).eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(dev)
        _st.update(model=model, tok=tok, dev=dev)
        log(f"  vector: nạp {MODEL.split('/')[-1]} ({dev}) {time.time() - t0:.1f}s")
        return True
    except Exception as e:  # noqa: BLE001
        _st["loi"] = str(e)
        log(f"  vector: không nạp được model ({e}) — bỏ mức vector")
        return False


def _doc_cache() -> None:
    if _st["cache_doc"]:
        return
    _st["cache_doc"] = True
    if not CACHE.exists():
        return
    try:
        z = np.load(CACHE, allow_pickle=False)
        texts = json.loads(str(z["texts"]))
        M = z["M"].astype(np.float32)
        if M.shape[0] == len(texts):
            _st["vec"].update({t: M[i] for i, t in enumerate(texts)})
    except Exception:  # noqa: BLE001
        pass


def _ghi_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    texts = list(_st["vec"])
    M = np.stack([_st["vec"][t] for t in texts]) if texts else np.zeros((0, 1), np.float32)
    tam = CACHE.with_suffix(".tmp.npz")
    np.savez(tam, texts=json.dumps(texts, ensure_ascii=False), M=M)
    tam.replace(CACHE)


def _tinh(texts: list[str]) -> np.ndarray:
    import torch
    tok, model, dev = _st["tok"], _st["model"], _st["dev"]
    ra = []
    for i in range(0, len(texts), 64):
        b = tok(texts[i:i + 64], padding=True, truncation=True, max_length=128, return_tensors="pt").to(dev)
        with torch.no_grad():
            h = model(**b).last_hidden_state
        m = b["attention_mask"].unsqueeze(-1).float()
        v = (h * m).sum(1) / m.sum(1)
        ra.append(torch.nn.functional.normalize(v, dim=-1).cpu().numpy().astype(np.float32))
    return np.concatenate(ra) if ra else np.zeros((0, 768), np.float32)


def nhung(texts: list[str], log: Callable[[str], None] = print, luu: bool = False) -> np.ndarray | None:
    """Vector (chuẩn hóa) cho từng chuỗi; lấy từ cache, thiếu thì tính (cần model). None nếu không nạp được model."""
    _doc_cache()
    texts = [t.strip() for t in texts]
    thieu = [t for t in dict.fromkeys(texts) if t and t not in _st["vec"]]
    if thieu:
        if not _nap(log):
            return None
        V = _tinh(thieu)
        for t, v in zip(thieu, V):
            _st["vec"][t] = v
        if luu:
            _ghi_cache()
    dim = next(iter(_st["vec"].values())).shape[0] if _st["vec"] else 768
    return np.stack([_st["vec"].get(t, np.zeros(dim, np.float32)) for t in texts]) if texts else np.zeros((0, dim), np.float32)


def van_ban_clip(c) -> tuple[list[str], str]:
    """(các từ khóa hiển thị của clip, chuỗi tên + mô tả)."""
    kw = [k.strip() for k in (c.tu_khoa_hien or []) if k and k.strip()]
    ten = Path(c.ten).stem if c.ten else ""
    mo_ta = f"{ten}. {c.mo_ta}".strip(". ") if (ten or c.mo_ta) else ""
    return kw, mo_ta


def cap_nhat(kho, log: Callable[[str], None] = print) -> dict:
    """Tính vector cho mọi từ khóa / mô tả của kho còn thiếu trong cache rồi ghi cache. -> {moi, tong, giay, loi}."""
    ok, ly_do = san_sang()
    if not ok:
        return {"moi": 0, "tong": 0, "giay": 0.0, "loi": ly_do}
    _doc_cache()
    texts: list[str] = []
    for c in kho:
        kw, mt = van_ban_clip(c)
        texts += kw + ([mt] if mt else [])
    texts = list(dict.fromkeys(t for t in texts if t))
    thieu = [t for t in texts if t not in _st["vec"]]
    t0 = time.time()
    if thieu:
        if nhung(thieu, log, luu=True) is None:
            return {"moi": 0, "tong": len(texts), "giay": 0.0, "loi": _st["loi"]}
    kq = {"moi": len(thieu), "tong": len(texts), "giay": round(time.time() - t0, 1), "loi": ""}
    log(f"  vector kho: {kq['tong']} chuỗi (từ khóa + mô tả), tính mới {kq['moi']}" + (f" trong {kq['giay']}s" if thieu else " (đã có sẵn)"))
    return kq


_mt: dict = {"ky": None, "rows": [], "M": None}


def _ma_tran(kho):
    """Ma trận vector của cả kho: mỗi dòng = (chỉ số clip, 'tk'|'mt', chuỗi); cache theo chữ ký kho (id + chữ)."""
    ky = tuple((c.id, tuple(c.tu_khoa_hien or []), c.ten, c.mo_ta) for c in kho)
    if _mt["ky"] == ky and _mt["M"] is not None:
        return _mt["rows"], _mt["M"]
    rows, texts = [], []
    for i, c in enumerate(kho):
        kw, mt = van_ban_clip(c)
        for k in kw:
            rows.append((i, "tk", k)); texts.append(k)
        if mt:
            rows.append((i, "mt", mt)); texts.append(mt)
    M = nhung(texts, log=lambda s: None, luu=True)
    if M is None:
        return [], None
    _mt.update(ky=ky, rows=rows, M=M)
    return rows, M


def diem(de_xuat: list[str], van_ban: str, kho, loai_tru: set[str] | None = None, nguong: float = NGUONG,
         nhom: float = NHOM, log: Callable[[str], None] = print) -> list[tuple]:
    """Chấm điểm nghĩa từng clip so với các đề xuất (và chữ trong câu, hệ số 0,85) -> [(clip, điểm, giải thích)] giảm
    dần, chỉ các clip ≥ nguong VÀ ≥ nhom × điểm cao nhất (tối đa TOI_DA_NHOM). [] nếu không có / không có model."""
    de_xuat = [d.strip() for d in (de_xuat or []) if d and d.strip()]
    truy_van = list(de_xuat) + ([van_ban.strip()] if van_ban and van_ban.strip() else [])
    if not truy_van or not kho:
        return []
    rows, M = _ma_tran(kho)
    if M is None or not rows:
        return []
    Q = nhung(truy_van, log)
    if Q is None:
        return []
    S = Q @ M.T                                                    # (số truy vấn, số dòng kho)
    loai_tru = loai_tru or set()
    best: dict[int, tuple[float, str]] = {}
    for qi, q in enumerate(truy_van):
        la_cau = qi >= len(de_xuat)
        he_so = 0.85 if la_cau else (1 - 0.02 * qi)                # đề xuất đứng trước ưu tiên nhẹ, chữ trong câu nhẹ hơn
        for ri, (ci, loai, chu) in enumerate(rows):
            s = float(S[qi, ri]) * he_so * (HE_SO_MO_TA if loai == "mt" else 1.0)
            if ci not in best or s > best[ci][0]:
                nguon = "câu nói" if la_cau else f"“{q}”"
                best[ci] = (s, f"{nguon} ~ {'từ khóa' if loai == 'tk' else 'mô tả'} “{chu[:40]}”")
    ung = [(kho[ci], s, gt) for ci, (s, gt) in best.items() if kho[ci].id not in loai_tru and s >= nguong]
    if not ung:
        return []
    ung.sort(key=lambda x: -x[1])
    tot = ung[0][1]
    return [x for x in ung if x[1] >= tot * nhom][:TOI_DA_NHOM]


def diem_tung_clip(truy_van: str, kho) -> dict[str, float]:
    """Điểm nghĩa của MỘT truy vấn với MỌI clip (max theo từ khóa / mô tả×0,9) -> {clip_id: điểm}; {} nếu không có model."""
    rows, M = _ma_tran(kho)
    if M is None or not rows or not truy_van.strip():
        return {}
    Q = nhung([truy_van.strip()], log=lambda s: None)
    if Q is None:
        return {}
    S = (Q @ M.T)[0]
    kq: dict[str, float] = {}
    for ri, (ci, loai, _) in enumerate(rows):
        s = float(S[ri]) * (HE_SO_MO_TA if loai == "mt" else 1.0)
        cid = kho[ci].id
        if s > kq.get(cid, -1.0):
            kq[cid] = s
    return kq


if __name__ == "__main__":      # thử: python vector_kho.py "ợ nóng" "kẹt xe" | app.py gọi: --cap-nhat <sheet> [--thu-muc D]
    import sys
    sys.path.insert(0, str(HERE))
    import minh_hoa
    SHEET = "https://docs.google.com/spreadsheets/d/1n_rCUBFRCLi5NlDZovoDvHZd3ETCLtjKeLNPxHOAqUY/edit?gid=0#gid=0"
    if len(sys.argv) > 2 and sys.argv[1] == "--cap-nhat":
        # tiến trình con của app.py: tính vector cho kho (model nạp rồi thoát, không giữ 1 GB VRAM trong server)
        tm = sys.argv[sys.argv.index("--thu-muc") + 1] if "--thu-muc" in sys.argv else None
        kho = minh_hoa.doc_kho(sys.argv[2], log=lambda s: print("  " + s, flush=True), thu_muc=tm, ca_chua_co=True)
        kq = cap_nhat(kho, log=lambda s: print(s, flush=True))
        kq.update(so_clip=len(kho), model=MODEL.split("/")[-1], thiet_bi=_st["dev"] or "chưa nạp")
        print("VECTOR " + json.dumps(kq, ensure_ascii=False), flush=True)
        sys.exit(0 if not kq.get("loi") else 1)
    kho = minh_hoa.doc_kho(SHEET, log=lambda s: None, ca_chua_co=True)
    print(cap_nhat(kho))
    for q in sys.argv[1:] or ["ợ nóng", "kẹt xe buổi sáng", "bác sĩ tư vấn"]:
        print(q, "->", [(c.id, round(s, 2), gt) for c, s, gt in diem([q], "", kho)])
