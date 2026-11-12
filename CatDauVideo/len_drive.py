# -*- coding: utf-8 -*-
"""Tải bản v2 lên Drive rồi ghi link mới vào Sheet (user 11/11/2026: "ở cột E có link thư mục lưu video, tải video lên
Drive rồi update link mới qua cột H").

Mỗi dòng của Sheet có thư mục riêng ở cột "Link video" (E). Bản "<tên> v2.mp4" được tải vào đúng thư mục đó, bật "ai có
link đều xem được" (như file ở cột Link Đăng, để tool đăng video tải về được), rồi link ghi vào cột H cùng dòng. Ô H1
trống thì ghi tên cột "Link v2". Tải lại một dòng đã tải thì ĐÈ lên đúng file cũ trên Drive (link giữ nguyên).

Dùng chung đăng nhập Google của app Ghép video (GoogleFlowGhepVideo/drive_len.py: OAuth của chính user, token ở
~/.ghep_video_flow_google_token.json, quyền Drive + Sheets) nên không phải đăng nhập lần nữa.

Trước khi ghi một dòng, đọc lại đúng dòng đó trên Sheet: ô Link Đăng phải còn là video này (đề phòng Sheet vừa bị chèn /
xóa dòng), và ô H nếu đang có chữ không phải link thì không ghi đè.
"""
import sys
from pathlib import Path

import cat_dau as cd

HERE = Path(__file__).resolve().parent
_GHEP = HERE.parent / "GoogleFlowGhepVideo"
COT_LINK_MOI = "H"              # user chốt: link bản v2 ghi vào cột H
TEN_COT_MOI = "Link v2"         # tên ghi vào H1 khi ô đó trống (không chứa chữ "Link Đăng" để tool khác khỏi tìm nhầm cột)


class ChuaDangNhap(RuntimeError):
    """Chưa có đăng nhập Google dùng được -> giao diện hỏi rồi gọi dang_nhap()."""


def _dl():
    if not (_GHEP / "drive_len.py").is_file():
        raise RuntimeError(f"Không thấy {_GHEP / 'drive_len.py'} (phần đăng nhập Google dùng chung với app Ghép video).")
    if str(_GHEP) not in sys.path:
        sys.path.append(str(_GHEP))
    import drive_len
    return drive_len


def tai_khoan() -> str:
    """Email tài khoản Google đang đăng nhập; chưa đăng nhập -> ''."""
    t = _dl().trang_thai()
    return (t.get("email") or "?") if t.get("da_dang_nhap") else ""


def dang_nhap(log=print) -> str:
    """Mở trình duyệt cho user đăng nhập Google và cấp quyền Drive + Sheets. -> email."""
    _dl().creds(True, log)
    return tai_khoan()


class TabSheet:
    """Tab Sheet đang làm, mở một lần cho cả loạt: tìm cột Link Đăng theo tên, lo ô tiêu đề H1, đọc / ghi từng dòng."""

    def __init__(self, link_sheet: str, log=print):
        dl = _dl()
        c = dl.creds(False, log)
        if not c:
            raise ChuaDangNhap("Chưa đăng nhập Google.")
        self.dl, self.sh = dl, dl._sheets(c)
        self.sid, gid = dl.sheet_id_gid(link_sheet)
        if not self.sid:
            raise RuntimeError("Không nhận ra link Google Sheet.")
        self.tab, _ = dl._tab(self.sh, self.sid, gid)
        dau = self._doc("1:1")
        chuan = [dl._chuan_tieu_de(x) for x in dau]
        if "link dang" not in chuan:
            raise RuntimeError(f"Không thấy cột “Link Đăng” ở dòng 1 của tab “{self.tab}”.")
        self.i_dang, self.i_moi = chuan.index("link dang"), dl._so_cot(COT_LINK_MOI)
        h1 = dau[self.i_moi].strip() if len(dau) > self.i_moi else ""
        if not h1:
            dl.ghi_o(self.sid, self.tab, 1, COT_LINK_MOI, TEN_COT_MOI)
            log(f"  Ô {COT_LINK_MOI}1 đang trống → ghi tên cột “{TEN_COT_MOI}”.")

    def _doc(self, vung: str) -> list[str]:
        r = self.sh.spreadsheets().values().get(spreadsheetId=self.sid, range=f"'{self.tab}'!{vung}").execute()
        return [str(x) for x in (r.get("values") or [[]])[0]]

    def dong(self, n: int) -> tuple[str, str]:
        """(ô Link Đăng, ô cột H) đang có trên Sheet ở dòng n."""
        row = self._doc(f"A{n}:{COT_LINK_MOI}{n}")
        o = lambda i: row[i].strip() if i < len(row) else ""       # noqa: E731
        return o(self.i_dang), o(self.i_moi)

    def ghi(self, n: int, link: str):
        self.dl.ghi_o(self.sid, self.tab, n, COT_LINK_MOI, link)


def tai_len(d, thu_muc: Path, so_tay: dict, tab: TabSheet, log=print, tien_do=None) -> str:
    """Tải bản v2 của dòng d lên thư mục ở cột Link video, ghi link vào cột H, nhớ vào so_tay. -> link. Lỗi thì raise."""
    dl = tab.dl
    fid = cd.id_drive(d.link) or ""
    cu = so_tay.get(fid) or {}
    v2 = thu_muc / cu["v2"] if cu.get("v2") else None
    if v2 is None or not v2.is_file():
        raise RuntimeError("dòng này chưa có bản v2 để tải lên.")
    fid_tm = dl.folder_id(d.thu_muc_drive) if "/folders/" in d.thu_muc_drive else None
    if not fid_tm:
        raise RuntimeError("cột Link video (E) của dòng này không phải link thư mục Drive.")
    dang, h_cu = tab.dong(d.dong)
    if fid not in dang:
        raise RuntimeError(f"dòng {d.dong} trên Sheet không còn là video này (ô Link Đăng đã đổi) — bấm Tải danh sách rồi làm lại.")
    if h_cu and not h_cu.lower().startswith("http"):
        raise RuntimeError(f"ô {COT_LINK_MOI}{d.dong} đang có nội dung khác (“{h_cu[:40]}”) — không ghi đè.")
    kq = dl.tai_len(v2, fid_tm, v2.name, log=log, chia_se=True, tien_do=tien_do)
    tab.ghi(d.dong, kq["link"])
    so_tay[fid] = {**cu, "link_v2": kq["link"], "drive_v2": kq["id"]}
    log(f"  ✓ Đã ghi link vào ô {COT_LINK_MOI}{d.dong}" + (" (đè lên bản cũ trên Drive, link giữ nguyên)" if kq["de"] else ""))
    return kq["link"]


def nen_tu_tai(kq: dict) -> bool:
    """Dòng vừa cắt xong có nên tự tải lên không: có v2, chưa có link, và không có cảnh báo cần nghe lại."""
    if not kq.get("v2") or kq.get("link_v2"):
        return False
    return (kq["trang_thai"] == "xong" and not kq.get("ghi_chu")) or (kq["trang_thai"] == "đã có" and not kq.get("canh_bao"))
