# gui_misa_xbh.py — MISA Bảng Kê → Phiếu Xuất Bán Hàng Liên Tục

import os
import sys
import threading
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

# ── Bảng màu ──────────────────────────────────────────────────────────────────
BG        = "#EEF4FB"
WHITE     = "#FFFFFF"
CARD_BDR  = "#C2D8F0"
BLUE      = "#0D6EAB"
BLUE_H    = "#0A5A8E"
TEAL      = "#0A8F75"
TEAL_H    = "#076F5B"
BTN_NTR   = "#DDE9F5"
BTN_NTR_H = "#BDD4EC"
LOG_BG    = "#0D1B2A"
LOG_FG    = "#D6E8FA"
GREEN     = "#1B6B3A"
RED       = "#B71C1C"
MUTED     = "#4E6E8A"
DARK      = "#0D2B45"

F_LBL  = ("Segoe UI", 9)
F_BOLD = ("Segoe UI", 9, "bold")
F_BTN  = ("Segoe UI", 9, "bold")
F_LOG  = ("Consolas", 9)

LOG_COLORS = {
    logging.DEBUG:    "#5B8DB8",
    logging.INFO:     "#7EC8E3",
    logging.WARNING:  "#F4A261",
    logging.ERROR:    "#E76F51",
    logging.CRITICAL: "#E63946",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def bordered_btn(parent, text, command, bg, bg_h, fg=WHITE, font=None, padx=20, pady=10):
    font = font or ("Segoe UI", 10, "bold")
    wrap = tk.Frame(parent, bg=bg, padx=1, pady=1)
    btn = tk.Button(wrap, text=text, command=command,
                    bg=bg, fg=fg, font=font, relief="flat", cursor="hand2",
                    activebackground=bg_h, activeforeground=fg, padx=padx, pady=pady, bd=0)
    btn.pack(fill="both")
    btn.bind("<Enter>", lambda _: btn.configure(bg=bg_h))
    btn.bind("<Leave>", lambda _: btn.configure(bg=bg))
    return wrap, btn


# ── TextHandler ────────────────────────────────────────────────────────────────
class TextHandler(logging.Handler):
    def __init__(self, widget: tk.Text):
        super().__init__()
        self.widget = widget

    def emit(self, record):
        msg = self.format(record)
        color = LOG_COLORS.get(record.levelno, LOG_FG)
        self.widget.after(0, self._append, msg, color)

    def _append(self, msg, color):
        tag = f"c{color}"
        self.widget.configure(state="normal")
        self.widget.tag_configure(tag, foreground=color)
        self.widget.tag_configure("ts", foreground="#3A6B9A")
        ts = datetime.now().strftime("%H:%M:%S")
        self.widget.insert("end", f"[{ts}] ", "ts")
        self.widget.insert("end", msg + "\n", tag)
        self.widget.configure(state="disabled")
        self.widget.see("end")


# ── DMHangHoaEditor ───────────────────────────────────────────────────────────
class DMHangHoaEditor(tk.Toplevel):
    """Cửa sổ xem/thêm/sửa/xóa Danh mục hàng hóa."""

    COLS = ("stt", "ma_hang", "ten_hang", "dvt")

    def __init__(self, parent, file_path: str):
        super().__init__(parent)
        self.title("Danh mục hàng hóa")
        self.file_path = file_path
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(620, 440)
        w, h = 760, 540
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self._build_ui()
        self._load()
        self.grab_set()

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BLUE, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Danh mục hàng hóa", bg=BLUE, fg=WHITE,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=16)
        tk.Label(hdr, text=self.file_path, bg=BLUE, fg="#A8CFEA",
                 font=("Segoe UI", 8)).pack(side="left")

        # Treeview
        tree_card = tk.Frame(self, bg=WHITE,
                             highlightbackground=CARD_BDR, highlightthickness=1)
        tree_card.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        self.tree = ttk.Treeview(tree_card, columns=self.COLS,
                                  show="headings", selectmode="browse")
        self.tree.heading("stt",      text="#",          anchor="center")
        self.tree.heading("ma_hang",  text="Mã hàng",    anchor="w")
        self.tree.heading("ten_hang", text="Tên hàng",   anchor="w")
        self.tree.heading("dvt",      text="ĐVT",        anchor="center")
        self.tree.column("stt",      width=40,  minwidth=40,  stretch=False, anchor="center")
        self.tree.column("ma_hang",  width=90,  minwidth=70,  stretch=False)
        self.tree.column("ten_hang", width=440, minwidth=160, stretch=True)
        self.tree.column("dvt",      width=70,  minwidth=60,  stretch=False, anchor="center")
        self.tree.tag_configure("odd",  background="#F5FAFF")
        self.tree.tag_configure("even", background=WHITE)

        sb = ttk.Scrollbar(tree_card, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=4)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _: self._on_select())

        # Edit fields
        edit_card = tk.Frame(self, bg=WHITE,
                             highlightbackground=CARD_BDR, highlightthickness=1)
        edit_card.pack(fill="x", padx=14, pady=(8, 0))

        fields_f = tk.Frame(edit_card, bg=WHITE)
        fields_f.pack(fill="x", padx=10, pady=8)

        self.v_ma   = tk.StringVar()
        self.v_ten  = tk.StringVar()
        self.v_dvt  = tk.StringVar()

        tk.Label(fields_f, text="Mã hàng", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=0, column=0, sticky="w", padx=(0, 6))
        tk.Entry(fields_f, textvariable=self.v_ma, font=F_LBL, bg="#F0F7FF",
                 relief="solid", width=12).grid(row=0, column=1, sticky="ew", padx=(0, 14))

        tk.Label(fields_f, text="Tên hàng", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=0, column=2, sticky="w", padx=(0, 6))
        tk.Entry(fields_f, textvariable=self.v_ten, font=F_LBL, bg="#F0F7FF",
                 relief="solid").grid(row=0, column=3, sticky="ew", padx=(0, 14))

        tk.Label(fields_f, text="ĐVT", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=0, column=4, sticky="w", padx=(0, 6))
        tk.Entry(fields_f, textvariable=self.v_dvt, font=F_LBL, bg="#F0F7FF",
                 relief="solid", width=8).grid(row=0, column=5)
        fields_f.columnconfigure(3, weight=1)

        # Buttons
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=14, pady=(6, 10))

        tk.Label(btn_row, text="⚠ Nhớ ấn Cập nhật trước khi Lưu file",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8, "italic")).pack(side="bottom", pady=(0, 4))

        bordered_btn(btn_row, "Thêm mới", self._add,
                     BLUE, BLUE_H, padx=16, pady=8)[0].pack(side="left", padx=(0, 6))
        bordered_btn(btn_row, "Cập nhật", self._update,
                     TEAL, TEAL_H, padx=16, pady=8)[0].pack(side="left", padx=(0, 6))
        bordered_btn(btn_row, "Xóa dòng", self._delete,
                     RED, "#8B0000", padx=16, pady=8)[0].pack(side="left")
        bordered_btn(btn_row, "Lưu file", self._save,
                     BLUE, BLUE_H, padx=16, pady=8)[0].pack(side="right")

    # ── Data ──────────────────────────────────────────────────────────────────
    def _load(self):
        if not os.path.isfile(self.file_path):
            messagebox.showerror("Lỗi", f"Không tìm thấy file:\n{self.file_path}", parent=self)
            self.destroy()
            return
        try:
            import pandas as pd
            df = pd.read_excel(self.file_path, engine="openpyxl", dtype=str)
            df.columns = [str(c).strip() for c in df.columns]
        except Exception as e:
            messagebox.showerror("Lỗi đọc file", str(e), parent=self)
            self.destroy()
            return

        # Tìm cột
        self._col_ma = self._col_ten = self._col_dvt = None
        for c in df.columns:
            cl = c.lower().strip()
            if self._col_ma  is None and any(k in cl for k in ("mã hàng", "ma hang", "mã")):
                self._col_ma  = c
            if self._col_ten is None and any(k in cl for k in ("tên hàng", "ten hang", "tên")):
                self._col_ten = c
            if self._col_dvt is None and "đvt" in cl:
                self._col_dvt = c

        if not self._col_ma or not self._col_ten:
            messagebox.showerror("Lỗi",
                f"Không nhận ra cột Mã hàng / Tên hàng.\nCột: {list(df.columns)}",
                parent=self)
            self.destroy()
            return

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for i, (_, row) in enumerate(df.iterrows(), 1):
            ma  = str(row.get(self._col_ma,  "")).strip()
            ten = str(row.get(self._col_ten, "")).strip()
            dvt = str(row.get(self._col_dvt, "")).strip() if self._col_dvt else ""
            if not ma and not ten:
                continue
            for v in (ma, ten, dvt):
                if v.lower() in ("nan", "none"):
                    v = ""
            tag = "odd" if i % 2 else "even"
            self.tree.insert("", "end",
                             values=(i, ma, ten, dvt if dvt.lower() not in ("nan","none") else ""),
                             tags=(tag,))
        self._reindex()

    def _reindex(self):
        for i, iid in enumerate(self.tree.get_children(), 1):
            vals = list(self.tree.item(iid, "values"))
            tag  = "odd" if i % 2 else "even"
            self.tree.item(iid, values=(i, vals[1], vals[2], vals[3]), tags=(tag,))

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        _, ma, ten, dvt = self.tree.item(sel[0], "values")
        self.v_ma.set(ma)
        self.v_ten.set(ten)
        self.v_dvt.set(dvt)

    def _validate(self):
        ma  = self.v_ma.get().strip()
        ten = self.v_ten.get().strip()
        if not ma:
            messagebox.showwarning("Thiếu dữ liệu", "Vui lòng nhập Mã hàng.", parent=self)
            return None, None, None
        if not ten:
            messagebox.showwarning("Thiếu dữ liệu", "Vui lòng nhập Tên hàng.", parent=self)
            return None, None, None
        return ma, ten, self.v_dvt.get().strip()

    def _add(self):
        ma, ten, dvt = self._validate()
        if ma is None:
            return
        n   = len(self.tree.get_children()) + 1
        tag = "odd" if n % 2 else "even"
        self.tree.insert("", "end", values=(n, ma, ten, dvt), tags=(tag,))
        self.tree.yview_moveto(1)
        self.v_ma.set("")
        self.v_ten.set("")
        self.v_dvt.set("")

    def _update(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn", "Chọn một dòng để cập nhật.", parent=self)
            return
        ma, ten, dvt = self._validate()
        if ma is None:
            return
        vals = self.tree.item(sel[0], "values")
        self.tree.item(sel[0], values=(vals[0], ma, ten, dvt))

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn", "Chọn một dòng để xóa.", parent=self)
            return
        ten = self.tree.item(sel[0], "values")[2]
        if not messagebox.askyesno("Xác nhận xóa", f"Xóa hàng hóa:\n{ten}?", parent=self):
            return
        self.tree.delete(sel[0])
        self._reindex()
        self.v_ma.set("")
        self.v_ten.set("")
        self.v_dvt.set("")

    def _save(self):
        import pandas as pd
        rows = []
        for iid in self.tree.get_children():
            _, ma, ten, dvt = self.tree.item(iid, "values")
            rows.append({
                self._col_ma  or "Mã hàng":  ma,
                self._col_ten or "Tên hàng": ten,
                self._col_dvt or "ĐVT":      dvt,
            })
        if not rows:
            messagebox.showwarning("Trống", "Danh mục đang trống.", parent=self)
            return
        try:
            pd.DataFrame(rows).to_excel(self.file_path, index=False, engine="openpyxl")
            messagebox.showinfo("Lưu thành công",
                f"Đã lưu {len(rows)} mặt hàng vào:\n{os.path.basename(self.file_path)}",
                parent=self)
        except PermissionError:
            messagebox.showerror("Lỗi",
                "File đang mở trong Excel — đóng file rồi thử lại.", parent=self)
        except Exception as e:
            messagebox.showerror("Lỗi lưu file", str(e), parent=self)


# ── App ────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MISA Bảng Kê → Phiếu Xuất Bán Hàng")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(700, 500)
        w, h = 860, 600
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self._build_ui()
        self._setup_logging()

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BLUE, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="MISA  →  Phiếu Xuất Bán Hàng Liên Tục",
                 bg=BLUE, fg=WHITE, font=("Segoe UI", 12, "bold")).pack(side="left", padx=16)
        tk.Label(hdr, text="Chuyển bảng kê MISA sang mẫu import XBH-01",
                 bg=BLUE, fg="#A8CFEA", font=("Segoe UI", 8)).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="x", padx=14, pady=(12, 0))

        if getattr(sys, "frozen", False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        xlsx_types = [("Excel", "*.xlsx *.xls"), ("All files", "*.*")]
        xls_types  = [("Excel 97-2003", "*.xls"), ("All files", "*.*")]
        today = datetime.now().strftime("%d-%m-%Y")

        _EXCLUDE = {"DM hang hoa.xlsx", "DM hang hoa.xls"}
        _src_default = ""
        try:
            _candidates = [
                f for f in os.listdir(script_dir)
                if f.lower().endswith((".xlsx", ".xls"))
                and f not in _EXCLUDE
                and not f.startswith("~$")
            ]
            _candidates.sort(
                key=lambda f: os.path.getmtime(os.path.join(script_dir, f)),
                reverse=True,
            )
            if _candidates:
                _src_default = os.path.join(script_dir, _candidates[0])
        except Exception:
            pass
        self.v_source   = tk.StringVar(value=_src_default)
        self.v_template = tk.StringVar(value=os.path.join(script_dir,
            "Phieu-Xuat-Ban-Hang-Lien-Tuc.xls"))
        self.v_output   = tk.StringVar(value=os.path.join(downloads,
            f"XBH_{today}.xls"))

        # TK mặc định
        self.v_tk_no_th     = tk.StringVar(value="5111")
        self.v_tk_no_tt     = tk.StringVar(value="33311")
        self.v_tk_co_th     = tk.StringVar(value="131")
        self.v_tk_no_gv     = tk.StringVar(value="632")
        self.v_tk_co_gt     = tk.StringVar(value="156")
        self.v_ma_kho       = tk.StringVar(value="K1")
        self.v_nhom_hd      = tk.StringVar(value="R6")
        self.v_mau_so       = tk.StringVar(value="1")
        self.v_dien_giai    = tk.StringVar(value="Bán hàng cho khách HĐ:")
        self.v_ng_nhan      = tk.StringVar(value="Khách hàng không cung cấp thông tin")
        self.v_ten_khach_df = tk.StringVar(value="Khách hàng không cung cấp thông tin")

        # ── Layout: left (files + TK) | right (buttons) ─────────────────────
        right = tk.Frame(body, bg=WHITE,
                         highlightbackground=CARD_BDR, highlightthickness=1)
        right.pack(side="right", fill="y", padx=(10, 0))

        left = tk.Frame(body, bg=WHITE,
                        highlightbackground=CARD_BDR, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)

        # File pickers
        tk.Frame(left, bg=WHITE, height=8).pack()
        self._file_row(left, "File nguồn MISA *", self.v_source,   xlsx_types, open_mode=True)
        self._file_row(left, "File mẫu template *", self.v_template, xls_types,  open_mode=True)
        tk.Frame(left, bg=CARD_BDR, height=1).pack(fill="x", padx=10, pady=(2, 4))
        self._file_row(left, "File kết quả *", self.v_output, xls_types, open_mode=False)
        tk.Frame(left, bg=CARD_BDR, height=1).pack(fill="x", padx=10, pady=(2, 4))

        # Tài khoản kế toán
        tk_frame = tk.Frame(left, bg=WHITE)
        tk_frame.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(tk_frame, text="Tài khoản kế toán", bg=WHITE, fg=DARK,
                 font=F_BOLD).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 4))

        tk_fields = [
            ("TK Nợ (Tiền hàng)", self.v_tk_no_th, 1, 0),
            ("TK Nợ (Tiền thuế)", self.v_tk_no_tt, 1, 2),
            ("TK Có (Tiền hàng)", self.v_tk_co_th, 1, 4),
            ("TK Nợ (Giá vốn)",   self.v_tk_no_gv, 2, 0),
            ("TK Có (Giảm trừ)",  self.v_tk_co_gt, 2, 2),
            ("Mã Kho",            self.v_ma_kho,   2, 4),
        ]
        for label, var, r, c in tk_fields:
            tk.Label(tk_frame, text=label, bg=WHITE, fg=DARK, font=F_LBL).grid(
                row=r, column=c, sticky="w", padx=(0 if c == 0 else 8, 4))
            tk.Entry(tk_frame, textvariable=var, font=F_LBL, bg="#F0F7FF",
                     relief="solid", width=10).grid(row=r, column=c+1, sticky="ew", padx=(0, 4))
        tk_frame.columnconfigure(1, weight=1)
        tk_frame.columnconfigure(3, weight=1)
        tk_frame.columnconfigure(5, weight=1)

        # Nhóm HĐ / Mẫu số / Diễn giải
        extra_frame = tk.Frame(left, bg=WHITE)
        extra_frame.pack(fill="x", padx=12, pady=(0, 4))
        for col_idx, (label, var, width) in enumerate([
            ("Nhóm HĐ",    self.v_nhom_hd,   8),
            ("Mẫu số",     self.v_mau_so,    10),
        ]):
            tk.Label(extra_frame, text=label, bg=WHITE, fg=DARK, font=F_LBL).grid(
                row=0, column=col_idx*2, sticky="w", padx=(0 if col_idx == 0 else 8, 4))
            tk.Entry(extra_frame, textvariable=var, font=F_LBL, bg="#F0F7FF",
                     relief="solid", width=width).grid(row=0, column=col_idx*2+1, sticky="ew", padx=(0, 4))
        tk.Label(extra_frame, text="Diễn giải (F)", bg=WHITE, fg=DARK, font=F_LBL).grid(
            row=0, column=4, sticky="w", padx=(8, 4))
        tk.Entry(extra_frame, textvariable=self.v_dien_giai, font=F_LBL, bg="#FFF8E1",
                 relief="solid", width=28).grid(row=0, column=5, sticky="ew")
        tk.Label(extra_frame, text="({ten_hang}, {ten_khach}, {so_hd})",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 7, "italic")).grid(
                 row=1, column=5, sticky="w")
        extra_frame.columnconfigure(5, weight=1)

        # Ng Nhận hàng / Tên khách mặc định
        ng_frame = tk.Frame(left, bg=WHITE)
        ng_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(ng_frame, text="Ng Nhận hàng (E)", bg=WHITE, fg=DARK, font=F_LBL).grid(
            row=0, column=0, sticky="w", padx=(0, 4))
        tk.Entry(ng_frame, textvariable=self.v_ng_nhan, font=F_LBL, bg="#FFF8E1",
                 relief="solid").grid(row=0, column=1, sticky="ew", padx=(0, 14))
        tk.Label(ng_frame, text="Tên khách mặc định (AF)", bg=WHITE, fg=DARK, font=F_LBL).grid(
            row=0, column=2, sticky="w", padx=(0, 4))
        tk.Entry(ng_frame, textvariable=self.v_ten_khach_df, font=F_LBL, bg="#FFF8E1",
                 relief="solid").grid(row=0, column=3, sticky="ew")
        ng_frame.columnconfigure(1, weight=1)
        ng_frame.columnconfigure(3, weight=1)

        # Right: buttons
        tk.Frame(right, bg=WHITE, height=8).pack()
        run_wrap, self.btn_run = bordered_btn(
            right, "▶  Chạy chuyển đổi", self._run,
            bg=BLUE, bg_h=BLUE_H, fg=WHITE,
            font=("Segoe UI", 10, "bold"), padx=22, pady=14)
        run_wrap.pack(padx=14, pady=(6, 6), fill="x")

        open_wrap, _ = bordered_btn(
            right, "📂  Mở thư mục", self._open_folder,
            bg=TEAL, bg_h=TEAL_H, fg=WHITE,
            font=("Segoe UI", 10, "bold"), padx=22, pady=14)
        open_wrap.pack(padx=14, pady=(0, 6), fill="x")

        tk.Frame(right, bg=CARD_BDR, height=1).pack(fill="x", padx=10, pady=(2, 4))

        dm_wrap, _ = bordered_btn(
            right, "Danh mục hàng hóa", self._open_dm_editor,
            bg=BTN_NTR, bg_h=BTN_NTR_H, fg=DARK,
            font=("Segoe UI", 9, "bold"), padx=22, pady=10)
        dm_wrap.pack(padx=14, pady=(0, 6), fill="x")

        tk.Frame(right, bg=WHITE, height=8).pack()

        # ── Log ─────────────────────────────────────────────────────────────
        log_card = tk.Frame(self, bg=WHITE,
                            highlightbackground=CARD_BDR, highlightthickness=1)
        log_card.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        log_hdr = tk.Frame(log_card, bg=WHITE)
        log_hdr.pack(fill="x", padx=10, pady=(5, 0))
        tk.Label(log_hdr, text="Log", bg=WHITE, fg=MUTED, font=F_BOLD).pack(side="left")
        tk.Button(log_hdr, text="Xóa", command=self._clear_log,
                  bg=BTN_NTR, fg=MUTED, font=("Segoe UI", 8),
                  relief="flat", padx=8, cursor="hand2",
                  activebackground=BTN_NTR_H).pack(side="right")

        log_inner = tk.Frame(log_card, bg=LOG_BG)
        log_inner.pack(fill="both", expand=True, padx=10, pady=(3, 10))
        self.log_text = tk.Text(log_inner, bg=LOG_BG, fg=LOG_FG, font=F_LOG,
                                relief="flat", state="disabled", wrap="word",
                                padx=8, pady=6)
        sb = ttk.Scrollbar(log_inner, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        # ── Progress + status ────────────────────────────────────────────────
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=14, pady=(6, 1))

        self.status_var = tk.StringVar(value="Sẵn sàng")
        self.status_lbl = tk.Label(self, textvariable=self.status_var,
                                   bg=BG, fg=MUTED, font=F_LBL)
        self.status_lbl.pack(anchor="w", padx=16, pady=(2, 8))

    def _file_row(self, parent, label, var, filetypes, open_mode=True):
        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(row, text=label, bg=WHITE, fg=DARK, font=F_LBL,
                 width=22, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, font=F_LBL, bg="#F0F7FF",
                 relief="solid").pack(side="left", fill="x", expand=True, padx=(0, 6))
        if open_mode:
            def browse(v=var):
                p = filedialog.askopenfilename(filetypes=filetypes)
                if p:
                    v.set(p)
            btn_text = "Chọn..."
        else:
            def browse(v=var):
                dl = os.path.join(os.path.expanduser("~"), "Downloads")
                p = filedialog.asksaveasfilename(
                    filetypes=filetypes, defaultextension=".xls",
                    initialdir=dl,
                    initialfile=f"XBH_{datetime.now().strftime('%d-%m-%Y')}.xls",
                )
                if p:
                    v.set(p)
            btn_text = "Lưu tại..."
        tk.Button(row, text=btn_text, command=browse,
                  bg=BTN_NTR, fg=DARK, font=F_BTN,
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  activebackground=BTN_NTR_H).pack(side="left")

    def _setup_logging(self):
        self.gui_handler = TextHandler(self.log_text)
        self.gui_handler.setFormatter(logging.Formatter("%(message)s"))
        self.gui_handler.setLevel(logging.INFO)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _validate(self) -> bool:
        errors = []
        for label, var in [
            ("File nguồn MISA", self.v_source),
            ("File mẫu template", self.v_template),
        ]:
            path = var.get().strip()
            if not path:
                errors.append(f"Chưa chọn {label}.")
            elif not os.path.exists(path):
                errors.append(f"{label} không tìm thấy:\n{path}")
        if not self.v_output.get().strip():
            errors.append("Chưa chọn đường dẫn file kết quả.")
        if errors:
            messagebox.showerror("Thiếu thông tin", "\n\n".join(errors))
            return False
        return True

    def _run(self):
        if not self._validate():
            return
        self.btn_run.configure(state="disabled", text="⏳  Đang xử lý...")
        self.progress.start(12)
        self.status_var.set("Đang chạy...")
        self.status_lbl.configure(fg=MUTED)
        self._clear_log()
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _run_worker(self):
        import convert_misa_xbh as core

        core.CONFIG["SOURCE_FILE"]        = self.v_source.get().strip()
        core.CONFIG["TEMPLATE_FILE"]      = self.v_template.get().strip()
        core.CONFIG["OUTPUT_FILE"]        = self.v_output.get().strip()
        core.CONFIG["TK_NO_TIEN_HANG"]   = self.v_tk_no_th.get().strip()
        core.CONFIG["TK_NO_TIEN_THUE"]   = self.v_tk_no_tt.get().strip()
        core.CONFIG["TK_CO_TIEN_HANG"]   = self.v_tk_co_th.get().strip()
        core.CONFIG["TK_NO_GIA_VON"]     = self.v_tk_no_gv.get().strip()
        core.CONFIG["TK_CO_GIAM_TRU"]      = self.v_tk_co_gt.get().strip()
        core.CONFIG["MA_KHO"]             = self.v_ma_kho.get().strip()
        core.CONFIG["NHOM_HD"]            = self.v_nhom_hd.get().strip()
        core.CONFIG["MAU_SO"]             = self.v_mau_so.get().strip()
        core.CONFIG["DIEN_GIAI"]          = self.v_dien_giai.get().strip()
        core.CONFIG["DEFAULT_NG_NHAN"]    = self.v_ng_nhan.get().strip()
        core.CONFIG["DEFAULT_TEN_KHACH"]  = self.v_ten_khach_df.get().strip()

        # Hướng logging về GUI
        core_log = logging.getLogger()
        core_log.setLevel(logging.DEBUG)
        for h in core_log.handlers[:]:
            core_log.removeHandler(h)
        core_log.addHandler(self.gui_handler)

        self._actual_output = core.CONFIG["OUTPUT_FILE"]
        success = False
        try:
            core.main()
            self._actual_output = core.CONFIG.get("_ACTUAL_OUTPUT", core.CONFIG["OUTPUT_FILE"])
            success = True
        except SystemExit:
            pass
        except PermissionError:
            logging.error("File output đang mở — đóng file rồi thử lại.")
        except Exception as e:
            logging.error(f"Lỗi: {e}", exc_info=True)

        self.after(0, self._run_done, success)

    def _run_done(self, success: bool):
        self.progress.stop()
        self.btn_run.configure(state="normal", text="▶  Chạy chuyển đổi")
        if success:
            out = getattr(self, "_actual_output", self.v_output.get().strip())
            self.status_var.set(f"✓  Hoàn thành — {os.path.basename(out)}")
            self.status_lbl.configure(fg=GREEN)
            if messagebox.askyesno("Hoàn thành",
                                   f"Chuyển đổi thành công!\nMở file kết quả ngay?\n\n{out}"):
                try:
                    os.startfile(out)
                except Exception:
                    pass
        else:
            self.status_var.set("✗  Có lỗi — xem log bên trên")
            self.status_lbl.configure(fg=RED)
            messagebox.showerror("Lỗi", "Chuyển đổi thất bại.\nXem chi tiết trong log.")

    def _open_folder(self):
        out = self.v_output.get().strip()
        folder = os.path.dirname(os.path.abspath(out)) if out else os.path.expanduser("~")
        try:
            os.startfile(folder)
        except Exception:
            pass

    def _open_dm_editor(self):
        import convert_misa_xbh as core
        path = core.CONFIG.get("DM_FILE", "DM hang hoa.xlsx")
        if not os.path.isabs(path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(script_dir, path)
        DMHangHoaEditor(self, path)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    App().mainloop()
