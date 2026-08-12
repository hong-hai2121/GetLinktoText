# -*- coding: utf-8 -*-
"""
gop_csv.py — Gộp nhiều file CSV do extension ReelStats xuất ra thành 1 file.

Chạy:  python gop_csv.py

Chức năng:
  - Chọn nhiều file CSV (thêm được nhiều lần, bỏ bớt từng file).
  - Gộp theo hợp các cột: file cũ thiếu cột mới vẫn gộp được, ô thiếu để trống.
  - Bỏ trùng theo id (giữ dòng có nhiều dữ liệu hơn / lượt xem cao hơn).
  - Sắp xếp giảm dần theo lượt xem (rỗng thì theo cảm xúc, bình luận).
  - Thêm cột `nguon_file` ghi file gốc của từng dòng.
  - Kết quả ghi ra thư mục Downloads, tên có mốc thời gian nên không đè file cũ.

File nguồn chỉ đọc, không bao giờ bị sửa.
"""

import csv
import os
import re
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

# Cột chuẩn của CSV do extension xuất — dùng làm thứ tự ưu tiên khi gộp.
COLS_CHUAN = [
    "kind", "id", "type", "url", "video_url", "title", "page", "page_url",
    "followers", "duration", "duration_sec", "date", "views", "views_text",
    "reactions", "comments", "shares", "description", "thumb",
]
COT_NGUON = "nguon_file"

# csv mặc định giới hạn ~131k ký tự/ô; mô tả bài viết dài có thể vượt.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


# ── Phần xử lý (tách khỏi GUI để test được) ─────────────────────────────────
def doc_csv(path):
    """Đọc 1 file CSV -> (danh sách dòng dạng dict, danh sách cột theo thứ tự)."""
    # utf-8-sig để nuốt BOM extension ghi cho Excel.
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = []
        for r in reader:
            r.pop(None, None)              # cột thừa khi dòng lệch số ô
            rows.append({k: (v or "") for k, v in r.items()})
    return rows, cols


def _so(v):
    """'1200' / '1.200' / '' -> int | None."""
    if v is None:
        return None
    s = str(v).strip().replace(".", "").replace(",", "")
    return int(s) if s.isdigit() else None


def _diem(row):
    """Đếm ô có dữ liệu, để giữ lại bản đầy đặn hơn khi trùng id."""
    return sum(1 for v in row.values() if str(v).strip())


def _sap_xep_key(row):
    for c in ("views", "reactions", "comments"):
        n = _so(row.get(c))
        if n is not None:
            return n
    return -1


def gop(paths, bo_trung=True, sap_xep=True, them_cot_nguon=True):
    """Gộp các file -> (rows, cols, thong_ke)."""
    cols = []
    for c in COLS_CHUAN:
        cols.append(c)

    tat_ca = []
    thong_ke = {"files": [], "tong_doc": 0, "trung": 0, "loi": []}

    for p in paths:
        try:
            rows, cols_file = doc_csv(p)
        except Exception as e:                       # noqa: BLE001 - báo lên GUI
            thong_ke["loi"].append(f"{os.path.basename(p)}: {e}")
            continue

        for c in cols_file:                          # cột lạ -> nối vào cuối
            if c and c not in cols:
                cols.append(c)

        ten = os.path.basename(p)
        for r in rows:
            if them_cot_nguon:
                r[COT_NGUON] = ten
            tat_ca.append(r)

        thong_ke["files"].append((ten, len(rows)))
        thong_ke["tong_doc"] += len(rows)

    if them_cot_nguon and COT_NGUON not in cols:
        cols.append(COT_NGUON)

    if bo_trung:
        theo_id = {}
        for r in tat_ca:
            khoa = (r.get("id") or "").strip() or (r.get("url") or "").strip()
            if not khoa:                             # không có khoá -> giữ nguyên
                theo_id[id(r)] = r
                continue
            cu = theo_id.get(khoa)
            if cu is None:
                theo_id[khoa] = r
                continue
            thong_ke["trung"] += 1
            moi_hon = (_diem(r), _sap_xep_key(r)) > (_diem(cu), _sap_xep_key(cu))
            if moi_hon:
                theo_id[khoa] = r
        tat_ca = list(theo_id.values())

    if sap_xep:
        tat_ca.sort(key=_sap_xep_key, reverse=True)

    return tat_ca, cols, thong_ke


COLS_TRANG = ["page", "page_url", "followers", "views", "tieu_de", COT_NGUON]

_HOST = re.compile(r"^https?://(?:www\.|web\.|m\.|mbasic\.|touch\.)?facebook\.com", re.I)


def chuan_hoa_page_url(u):
    """-> (khoá so sánh, link hiển thị).

    Cùng một trang nhưng viết khác nhau (thừa `/`, web./m., còn tham số, khác
    hoa thường) phải gộp về một dòng. Khoá dùng bản chữ thường; link hiển thị
    giữ nguyên hoa thường của lần gặp đầu.
    """
    s = (u or "").strip()
    if not s:
        return "", ""
    s = s.split("#")[0].rstrip("/")
    s = _HOST.sub("https://www.facebook.com", s)

    if "?" in s:                                     # bỏ tham số, trừ profile.php?id=
        goc, _, q = s.partition("?")
        pid = next((p for p in q.split("&") if p.lower().startswith("id=")), "")
        s = goc + (f"?{pid}" if pid and goc.lower().endswith("profile.php") else "")
        s = s.rstrip("/")
    return s.lower(), s


def gop_trang(paths):
    """Gộp -> mỗi trang 1 dòng, link page độc nhất.

    6 cột: page, page_url, followers, views, tieu_de, nguon_file.
    `views`   = tổng lượt xem của mọi video/bài của trang đó trong dữ liệu đã gộp.
    `tieu_de` = tiêu đề bài/video nhiều lượt xem nhất của trang đó.
    Xếp giảm dần theo followers, cùng followers thì theo views.
    """
    rows, _, tk = gop(paths, bo_trung=True, sap_xep=False, them_cot_nguon=True)

    theo_trang = {}
    for r in rows:
        khoa, hien_thi = chuan_hoa_page_url(r.get("page_url"))
        ten = (r.get("page") or "").strip()
        if not khoa:                                 # không có link -> gom theo tên
            if not ten:
                continue                             # không rõ trang nào -> bỏ
            khoa = f"ten:{ten.lower()}"
        fl = _so(r.get("followers"))
        vw = _so(r.get("views"))
        tieu_de = (r.get("title") or "").strip()
        nguon = r.get(COT_NGUON, "")

        cu = theo_trang.get(khoa)
        if cu is None:
            cu = theo_trang[khoa] = {"page": "", "page_url": "", "followers": None,
                                     "views": 0, "co_views": False,
                                     "tieu_de": "", "tieu_de_views": -1, "nguon": set()}

        # Gặp lại cùng trang: bù thông tin thiếu, giữ followers lớn nhất, cộng views.
        if not cu["page"] and ten:
            cu["page"] = ten
        if not cu["page_url"] and hien_thi:
            cu["page_url"] = hien_thi
        if fl is not None and (cu["followers"] is None or fl > cu["followers"]):
            cu["followers"] = fl
        if vw is not None:
            cu["views"] += vw
            cu["co_views"] = True
        # Giữ tiêu đề của bài nhiều lượt xem nhất; bài không có views vẫn hơn không có gì.
        if tieu_de:
            diem = vw if vw is not None else -1
            if not cu["tieu_de"] or diem > cu["tieu_de_views"]:
                cu["tieu_de"] = tieu_de
                cu["tieu_de_views"] = diem
        if nguon:
            cu["nguon"].add(nguon)

    ket = [{
        "page": v["page"],
        "page_url": v["page_url"],
        "followers": "" if v["followers"] is None else str(v["followers"]),
        "views": str(v["views"]) if v["co_views"] else "",
        "tieu_de": v["tieu_de"],
        COT_NGUON: "; ".join(sorted(v["nguon"])),
    } for v in theo_trang.values()]

    # Followers giảm dần, cùng followers thì views giảm dần; chưa có số -> xuống cuối.
    ket.sort(key=lambda r: (_so(r["followers"]) if _so(r["followers"]) is not None else -1,
                            _so(r["views"]) if _so(r["views"]) is not None else -1),
             reverse=True)

    tk["trang"] = len(ket)
    return ket, list(COLS_TRANG), tk


def thu_muc_downloads():
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def ten_file_ra(tien_to="gop_csv"):
    return f"{tien_to}_{datetime.now():%Y%m%d_%H%M%S}.csv"


def ghi_csv(path, rows, cols):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


# ── Giao diện ───────────────────────────────────────────────────────────────
class GopCsvGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gộp CSV — ReelStats")

        self.paths = []
        self._build_ui()

        # Chiều cao tối thiểu = vừa đủ cho toàn bộ nút + bảng 5 dòng, để kéo nhỏ
        # cỡ nào cũng không mất nút.
        self.update_idletasks()
        can = self.winfo_reqheight()
        self.minsize(720, can)
        self._center_on_screen(940, max(620, can))

    def _center_on_screen(self, w: int, h: int):
        """Đặt cửa sổ kích thước w×h ngay giữa màn hình."""
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(w, sw), min(h, sh)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # Tiêu đề — neo trên.
        dau = ttk.Frame(self)
        dau.pack(side="top", fill="x")
        tk.Label(dau, text="🗂 Gộp CSV", font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=12, pady=(8, 0))
        tk.Label(
            dau,
            text="Chọn các file CSV đã tải về → Gộp → file mới nằm trong Downloads.",
            fg="#777",
        ).pack(anchor="w", padx=12)

        # QUAN TRỌNG: phần neo đáy phải pack TRƯỚC bảng file. Nếu bảng (expand=True)
        # pack trước, cửa sổ thu nhỏ sẽ đẩy nút và dòng trạng thái ra ngoài.
        self.trang_thai = tk.Label(self, text="Chưa chọn file nào.", fg="#777",
                                   anchor="w", justify="left")
        self.trang_thai.pack(side="bottom", fill="x", padx=12, pady=(6, 10))

        self.nut_chay = ttk.Button(self, text="Gộp và lưu vào Downloads", command=self.chay)
        self.nut_chay.pack(side="bottom", fill="x", padx=12)

        # Tuỳ chọn (chỉ dùng cho kiểu Đầy đủ)
        self.tuy_chon = ttk.LabelFrame(self, text="Tuỳ chọn (kiểu Đầy đủ)")
        self.tuy_chon.pack(side="bottom", fill="x", padx=12, pady=8)
        self.bo_trung = tk.BooleanVar(value=True)
        self.sap_xep = tk.BooleanVar(value=True)
        self.them_nguon = tk.BooleanVar(value=True)
        self.o_tuy_chon = [
            ttk.Checkbutton(self.tuy_chon, text="Bỏ trùng theo id (giữ dòng đầy đủ hơn)",
                            variable=self.bo_trung),
            ttk.Checkbutton(self.tuy_chon, text="Sắp xếp giảm dần theo lượt xem / cảm xúc",
                            variable=self.sap_xep),
            ttk.Checkbutton(self.tuy_chon, text=f"Thêm cột `{COT_NGUON}` ghi file gốc",
                            variable=self.them_nguon),
        ]
        for o in self.o_tuy_chon:
            o.pack(anchor="w", padx=8, pady=2)

        # Kiểu gộp
        kieu_khung = ttk.LabelFrame(self, text="Kiểu gộp")
        kieu_khung.pack(side="bottom", fill="x", padx=12, pady=(8, 0))
        self.kieu = tk.StringVar(value="trang")
        ttk.Radiobutton(
            kieu_khung, text="Danh sách trang — mỗi trang 1 dòng, xếp theo followers rồi views",
            variable=self.kieu, value="trang", command=self._doi_kieu,
        ).pack(anchor="w", padx=8, pady=(2, 0))
        tk.Label(kieu_khung, text="Cột: " + ", ".join(COLS_TRANG), fg="#777").pack(
            anchor="w", padx=30)
        ttk.Radiobutton(kieu_khung, text="Đầy đủ — giữ mọi cột, bỏ trùng theo id",
                        variable=self.kieu, value="day_du",
                        command=self._doi_kieu).pack(anchor="w", padx=8, pady=2)

        hang = ttk.Frame(self)
        hang.pack(side="bottom", fill="x", padx=12)
        ttk.Button(hang, text="Thêm file…", command=self.them_file).pack(side="left")
        ttk.Button(hang, text="Bỏ file đã chọn", command=self.bo_file).pack(side="left", padx=6)
        ttk.Button(hang, text="Bỏ hết", command=self.bo_het).pack(side="left")

        # Bảng file — pack cuối cùng, ăn hết chỗ còn thừa ở giữa.
        khung = ttk.LabelFrame(self, text="File đã chọn")
        khung.pack(side="top", fill="both", expand=True, padx=12, pady=(8, 4))

        self.cay = ttk.Treeview(khung, columns=("dong", "duong_dan"), show="headings",
                                selectmode="extended", height=5)
        self.cay.heading("dong", text="Số dòng")
        self.cay.heading("duong_dan", text="Đường dẫn")
        self.cay.column("dong", width=80, minwidth=60, anchor="e", stretch=False)
        self.cay.column("duong_dan", width=420, minwidth=200, anchor="w")
        self.cay.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)

        thanh = ttk.Scrollbar(khung, orient="vertical", command=self.cay.yview)
        thanh.pack(side="right", fill="y", pady=6, padx=(0, 6))
        self.cay.configure(yscrollcommand=thanh.set)

        self._doi_kieu()        # khớp trạng thái ban đầu với kiểu đang chọn
        # Dòng trạng thái tự xuống dòng theo bề rộng cửa sổ, khỏi kéo giãn layout.
        self.bind("<Configure>", self._chinh_wrap)

    def _chinh_wrap(self, _e=None):
        rong = max(200, self.winfo_width() - 40)
        if getattr(self, "_wrap_cu", None) != rong:
            self._wrap_cu = rong
            self.trang_thai.config(wraplength=rong)

    # ── Thao tác ────────────────────────────────────────────────────────────
    def _doi_kieu(self):
        """Kiểu 'Danh sách trang' đã cố định cách gộp -> khoá mấy ô tuỳ chọn kia."""
        bat = self.kieu.get() == "day_du"
        for o in self.o_tuy_chon:
            o.state(["!disabled"] if bat else ["disabled"])
        self.nut_chay.config(
            text="Gộp và lưu vào Downloads" if bat
            else "Xuất danh sách trang vào Downloads")

    def them_file(self):
        chon = filedialog.askopenfilenames(
            title="Chọn file CSV cần gộp",
            initialdir=thu_muc_downloads(),
            filetypes=[("File CSV", "*.csv"), ("Tất cả", "*.*")],
        )
        them, bo_qua = 0, 0
        for p in chon:
            if p in self.paths:
                bo_qua += 1
                continue
            try:
                rows, _ = doc_csv(p)
                so_dong = len(rows)
            except Exception as e:                   # noqa: BLE001
                messagebox.showwarning("Không đọc được", f"{os.path.basename(p)}\n{e}")
                continue
            self.paths.append(p)
            self.cay.insert("", "end", values=(so_dong, p))
            them += 1
        self._cap_nhat_trang_thai(f"Đã thêm {them} file"
                                  + (f", bỏ qua {bo_qua} file trùng." if bo_qua else "."))

    def bo_file(self):
        for item in self.cay.selection():
            p = self.cay.item(item, "values")[1]
            if p in self.paths:
                self.paths.remove(p)
            self.cay.delete(item)
        self._cap_nhat_trang_thai("Đã bỏ file khỏi danh sách.")

    def bo_het(self):
        self.paths.clear()
        self.cay.delete(*self.cay.get_children())
        self._cap_nhat_trang_thai("Đã xoá danh sách.")

    def _cap_nhat_trang_thai(self, them=""):
        self.trang_thai.config(
            text=f"{len(self.paths)} file trong danh sách. {them}".strip())

    def chay(self):
        if not self.paths:
            messagebox.showinfo("Chưa có file", "Bấm “Thêm file…” để chọn CSV đã tải về.")
            return

        theo_trang = self.kieu.get() == "trang"
        if theo_trang:
            rows, cols, tk_ = gop_trang(self.paths)
        else:
            rows, cols, tk_ = gop(
                self.paths,
                bo_trung=self.bo_trung.get(),
                sap_xep=self.sap_xep.get(),
                them_cot_nguon=self.them_nguon.get(),
            )
        if not rows:
            messagebox.showwarning(
                "Không có dữ liệu",
                "Các file được chọn đều rỗng."
                + (" Hoặc không file nào có cột page_url." if theo_trang else ""))
            return

        # Tên có mốc thời gian tới giây -> chạy nhiều lần không đè lên nhau.
        mac_dinh = ten_file_ra("danh_sach_trang" if theo_trang else "gop_csv")
        path = filedialog.asksaveasfilename(
            title="Lưu file gộp",
            initialdir=thu_muc_downloads(),
            initialfile=mac_dinh,
            defaultextension=".csv",
            filetypes=[("File CSV", "*.csv")],
        )
        if not path:
            return

        try:
            ghi_csv(path, rows, cols)
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("Lỗi ghi file", str(e))
            return

        if theo_trang:
            co_fl = sum(1 for r in rows if r["followers"])
            tom_tat = (f"{len(self.paths)} file → {tk_['tong_doc']} dòng, "
                       f"gộp còn {len(rows)} trang ({co_fl} trang có followers).")
        else:
            tom_tat = (f"{len(self.paths)} file → {tk_['tong_doc']} dòng, "
                       f"bỏ trùng {tk_['trung']}, còn {len(rows)} dòng, {len(cols)} cột.")
        if tk_["loi"]:
            tom_tat += "\nFile lỗi: " + "; ".join(tk_["loi"])
        self.trang_thai.config(text=tom_tat + f"\nĐã lưu: {path}")
        messagebox.showinfo("Xong", f"{tom_tat}\n\nĐã lưu:\n{path}")


if __name__ == "__main__":
    GopCsvGUI().mainloop()
