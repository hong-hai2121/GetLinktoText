# gui.py — Pancake → meInvoice Converter

import os
import sys
import threading
import logging
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

# ── Bảng màu Medical ──────────────────────────────────────────────────────────
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

F_LBL     = ("Segoe UI", 9)
F_BOLD    = ("Segoe UI", 9, "bold")
F_BTN     = ("Segoe UI", 9, "bold")
F_LOG     = ("Consolas", 9)

LOG_COLORS = {
    logging.DEBUG:    "#5B8DB8",
    logging.INFO:     "#7EC8E3",
    logging.WARNING:  "#F4A261",
    logging.ERROR:    "#E76F51",
    logging.CRITICAL: "#E63946",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def bordered_btn(parent, text, command, bg, bg_h, fg=WHITE,
                 font=None, padx=20, pady=10):
    font = font or ("Segoe UI", 10, "bold")
    wrap = tk.Frame(parent, bg=bg, padx=1, pady=1)
    btn = tk.Button(wrap, text=text, command=command,
                    bg=bg, fg=fg, font=font,
                    relief="flat", cursor="hand2",
                    activebackground=bg_h, activeforeground=fg,
                    padx=padx, pady=pady, bd=0)
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


# ── PriceTableEditor ───────────────────────────────────────────────────────────
class PriceTableEditor(tk.Toplevel):
    def __init__(self, parent, file_path: str):
        super().__init__(parent)
        self.title("Bảng giá thuốc")
        self.file_path = file_path
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(620, 440)
        w, h = 760, 520
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self._col_ten = self._col_ten_moi = self._col_gia = self._col_thue = None
        self._build_ui()
        self._load()
        self.grab_set()

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BLUE, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Bảng giá thuốc", bg=BLUE, fg=WHITE,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=16)

        # Treeview
        tree_card = tk.Frame(self, bg=WHITE,
                             highlightbackground=CARD_BDR, highlightthickness=1)
        tree_card.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        cols = ("stt", "ten", "ten_moi", "don_gia", "thue_suat")
        self.tree = ttk.Treeview(tree_card, columns=cols, show="headings",
                                  selectmode="browse")
        self.tree.heading("stt",       text="#",               anchor="center")
        self.tree.heading("ten",       text="Tên thuốc (cũ)",  anchor="w")
        self.tree.heading("ten_moi",   text="Tên Mới (HĐ)",    anchor="w")
        self.tree.heading("don_gia",   text="Đơn giá",         anchor="e")
        self.tree.heading("thue_suat", text="Thuế (%)",        anchor="center")
        self.tree.column("stt",       width=36,  minwidth=36,  stretch=False, anchor="center")
        self.tree.column("ten",       width=220, minwidth=120, stretch=True)
        self.tree.column("ten_moi",   width=260, minwidth=120, stretch=True)
        self.tree.column("don_gia",   width=110, minwidth=80,  stretch=False, anchor="e")
        self.tree.column("thue_suat", width=70,  minwidth=60,  stretch=False, anchor="center")
        self.tree.tag_configure("odd",  background="#F5FAFF")
        self.tree.tag_configure("even", background=WHITE)

        sb = ttk.Scrollbar(tree_card, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=4)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Edit fields
        edit_card = tk.Frame(self, bg=WHITE,
                             highlightbackground=CARD_BDR, highlightthickness=1)
        edit_card.pack(fill="x", padx=14, pady=(8, 0))

        fields = tk.Frame(edit_card, bg=WHITE)
        fields.pack(fill="x", padx=10, pady=8)

        self.v_ten     = tk.StringVar()
        self.v_ten_moi = tk.StringVar()
        self.v_gia     = tk.StringVar()
        self.v_thue    = tk.StringVar()

        tk.Label(fields, text="Tên thuốc (tìm kiếm)", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=0, column=0, sticky="w", padx=(0, 6))
        tk.Entry(fields, textvariable=self.v_ten, font=F_LBL, bg="#F0F7FF",
                 relief="solid").grid(row=0, column=1, sticky="ew", padx=(0, 14))
        tk.Label(fields, text="Đơn giá", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=0, column=2, sticky="w", padx=(0, 6))
        tk.Entry(fields, textvariable=self.v_gia, font=F_LBL, bg="#F0F7FF",
                 relief="solid", width=14).grid(row=0, column=3, padx=(0, 14))
        tk.Label(fields, text="Thuế (%)", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=0, column=4, sticky="w", padx=(0, 6))
        tk.Entry(fields, textvariable=self.v_thue, font=F_LBL, bg="#F0F7FF",
                 relief="solid", width=7).grid(row=0, column=5)

        tk.Label(fields, text="Tên Mới (hóa đơn)", bg=WHITE, fg=DARK,
                 font=F_LBL).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        tk.Entry(fields, textvariable=self.v_ten_moi, font=F_LBL, bg="#FFF8E1",
                 relief="solid").grid(row=1, column=1, columnspan=5, sticky="ew", pady=(4, 0))
        fields.columnconfigure(1, weight=1)

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

    def _load(self):
        if not os.path.isfile(self.file_path):
            messagebox.showerror("Lỗi", f"Không tìm thấy file:\n{self.file_path}", parent=self)
            self.destroy()
            return
        try:
            df = pd.read_excel(self.file_path, engine="openpyxl")
            df.columns = [str(c).strip() for c in df.columns]
        except Exception as e:
            messagebox.showerror("Lỗi đọc file", str(e), parent=self)
            self.destroy()
            return

        for col in df.columns:
            cl = col.lower().strip()
            if cl in ("tên mới", "ten moi", "new name"):
                self._col_ten_moi = col
            elif self._col_ten is None and any(k in cl for k in ("tên", "ten", "thuốc", "thuoc", "sản phẩm", "name")):
                self._col_ten = col
            elif self._col_gia is None and any(k in cl for k in ("đơn giá", "don gia", "giá", "gia", "price")):
                self._col_gia = col
            elif self._col_thue is None and any(k in cl for k in ("thuế", "thue", "tax")):
                self._col_thue = col

        if not self._col_ten or not self._col_gia:
            messagebox.showerror("Lỗi",
                f"Không nhận ra cột tên hoặc đơn giá.\nCột trong file: {list(df.columns)}",
                parent=self)
            self.destroy()
            return

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for i, (_, row) in enumerate(df.iterrows(), 1):
            ten = str(row.get(self._col_ten, "")).strip()
            if not ten or ten.lower() in ("nan", "none"):
                continue
            ten_moi_val = str(row.get(self._col_ten_moi, "")).strip() if self._col_ten_moi else ""
            if ten_moi_val.lower() in ("nan", "none"):
                ten_moi_val = ""
            gia  = self._parse_num(row.get(self._col_gia, 0))
            thue = self._parse_num(row.get(self._col_thue, 8)) if self._col_thue else 8.0
            tag  = "odd" if i % 2 else "even"
            self.tree.insert("", "end", values=(i, ten, ten_moi_val, int(gia), int(thue)), tags=(tag,))

        self._reindex()

    def _parse_num(self, val) -> float:
        try:
            s = str(val).strip()
            return 0.0 if s in ("", "nan", "none") else float(s)
        except (ValueError, TypeError):
            return 0.0

    def _reindex(self):
        for i, iid in enumerate(self.tree.get_children(), 1):
            vals = self.tree.item(iid, "values")
            tag  = "odd" if i % 2 else "even"
            self.tree.item(iid, values=(i, vals[1], vals[2], vals[3], vals[4]), tags=(tag,))

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        _, ten, ten_moi, gia, thue = self.tree.item(sel[0], "values")
        self.v_ten.set(ten)
        self.v_ten_moi.set(ten_moi)
        self.v_gia.set(gia)
        self.v_thue.set(thue)

    def _validate_fields(self):
        ten = self.v_ten.get().strip()
        if not ten:
            messagebox.showwarning("Thiếu dữ liệu", "Vui lòng nhập tên thuốc (tìm kiếm).", parent=self)
            return None, None, None, None
        ten_moi = self.v_ten_moi.get().strip()
        try:
            gia = int(self.v_gia.get().replace(",", "").replace(".", "").strip() or 0)
        except ValueError:
            messagebox.showwarning("Lỗi", "Đơn giá phải là số.", parent=self)
            return None, None, None, None
        try:
            thue = int(float(self.v_thue.get().strip() or 8))
        except ValueError:
            messagebox.showwarning("Lỗi", "Thuế suất phải là số.", parent=self)
            return None, None, None, None
        return ten, ten_moi, gia, thue

    def _add(self):
        ten, ten_moi, gia, thue = self._validate_fields()
        if ten is None:
            return
        n   = len(self.tree.get_children()) + 1
        tag = "odd" if n % 2 else "even"
        self.tree.insert("", "end", values=(n, ten, ten_moi, gia, thue), tags=(tag,))
        self.tree.yview_moveto(1)
        self.v_ten.set("")
        self.v_ten_moi.set("")
        self.v_gia.set("")
        self.v_thue.set("8")

    def _update(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn", "Chọn một dòng để cập nhật.", parent=self)
            return
        ten, ten_moi, gia, thue = self._validate_fields()
        if ten is None:
            return
        vals = self.tree.item(sel[0], "values")
        self.tree.item(sel[0], values=(vals[0], ten, ten_moi, gia, thue))

    def _delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn", "Chọn một dòng để xóa.", parent=self)
            return
        ten = self.tree.item(sel[0], "values")[1]
        if not messagebox.askyesno("Xác nhận xóa", f"Xóa thuốc:\n{ten}?", parent=self):
            return
        self.tree.delete(sel[0])
        self._reindex()
        self.v_ten.set("")
        self.v_ten_moi.set("")
        self.v_gia.set("")
        self.v_thue.set("")

    def _save(self):
        rows = []
        for iid in self.tree.get_children():
            _, ten, ten_moi, gia, thue = self.tree.item(iid, "values")
            rows.append({
                self._col_ten:                          ten,
                (self._col_ten_moi or "Tên Mới"):       ten_moi,
                self._col_gia:                          int(gia),
                (self._col_thue or "Thuế suất (%)"):    int(thue),
            })
        if not rows:
            messagebox.showwarning("Trống", "Bảng giá đang trống.", parent=self)
            return
        try:
            pd.DataFrame(rows).to_excel(self.file_path, index=False, engine="openpyxl")
            messagebox.showinfo("Lưu thành công",
                f"Đã lưu {len(rows)} thuốc vào:\n{os.path.basename(self.file_path)}",
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
        self.title("Pancake → meInvoice")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(640, 420)
        w, h = 780, 520
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self._build_ui()
        self._setup_logging()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BLUE, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Pancake  →  meInvoice",
                 bg=BLUE, fg=WHITE, font=("Segoe UI", 12, "bold")).pack(side="left", padx=16)
        tk.Label(hdr, text="Chuyển đổi đơn hàng sang hóa đơn điện tử",
                 bg=BLUE, fg="#A8CFEA", font=("Segoe UI", 8)).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="x", padx=14, pady=(12, 0))

        if getattr(sys, "frozen", False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        downloads  = os.path.join(os.path.expanduser("~"), "Downloads")
        xlsx_types = [("Excel", "*.xlsx *.xls"), ("All files", "*.*")]
        today      = datetime.now().strftime("%d-%m-%Y")

        self.v_pancake      = tk.StringVar()
        self.v_price_tbl    = tk.StringVar(value=os.path.join(script_dir, "bang_ten_thuoc_gia_tien.xlsx"))
        self.v_template     = tk.StringVar(value=os.path.join(script_dir, "Mau_hoa_don_GTGT_MTT.xls"))
        self.v_output       = tk.StringVar(value=os.path.join(downloads, f"{today}.xlsx"))
        self.v_invoice_date = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))

        right = tk.Frame(body, bg=WHITE,
                         highlightbackground=CARD_BDR, highlightthickness=1)
        right.pack(side="right", fill="y", padx=(10, 0))

        left = tk.Frame(body, bg=WHITE,
                        highlightbackground=CARD_BDR, highlightthickness=1)
        left.pack(side="left", fill="x", expand=True)

        # Left: file pickers
        tk.Frame(left, bg=WHITE, height=8).pack()
        self._file_row(left, "File đơn hàng Pancake *", self.v_pancake,   xlsx_types, open_mode=True)
        self._file_row(left, "Bảng giá thuốc *",         self.v_price_tbl, xlsx_types, open_mode=True)
        tk.Frame(left, bg=CARD_BDR, height=1).pack(fill="x", padx=10, pady=(2, 4))
        self._file_row(left, "File kết quả *",            self.v_output,    xlsx_types, open_mode=False)
        self._date_row(left)
        tk.Frame(left, bg=WHITE, height=8).pack()

        # Right: action buttons
        tk.Frame(right, bg=WHITE, height=8).pack()

        run_wrap, self.btn_run = bordered_btn(
            right, "▶  Chạy chuyển đổi", self._run,
            bg=BLUE, bg_h=BLUE_H, fg=WHITE,
            font=("Segoe UI", 10, "bold"), padx=22, pady=14,
        )
        run_wrap.pack(padx=14, pady=(6, 6), fill="x")

        open_wrap, _ = bordered_btn(
            right, "📂  Mở thư mục", self._open_output_folder,
            bg=TEAL, bg_h=TEAL_H, fg=WHITE,
            font=("Segoe UI", 10, "bold"), padx=22, pady=14,
        )
        open_wrap.pack(padx=14, pady=(0, 6), fill="x")

        tk.Frame(right, bg=CARD_BDR, height=1).pack(fill="x", padx=10, pady=(2, 4))

        price_wrap, _ = bordered_btn(
            right, "Bảng giá thuốc", self._open_price_editor,
            bg=BTN_NTR, bg_h=BTN_NTR_H, fg=DARK,
            font=("Segoe UI", 9, "bold"), padx=22, pady=10,
        )
        price_wrap.pack(padx=14, pady=(0, 6), fill="x")

        tk.Frame(right, bg=WHITE, height=8).pack()

        # Log
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

        # Progress + status
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
                 width=24, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, font=F_LBL, bg="#F0F7FF",
                 relief="solid", highlightbackground=CARD_BDR,
                 highlightthickness=1).pack(side="left", fill="x", expand=True, padx=(0, 6))

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
                    filetypes=filetypes, defaultextension=".xlsx",
                    initialdir=dl,
                    initialfile=datetime.now().strftime("%d-%m-%Y") + ".xlsx",
                )
                if p:
                    v.set(p)
            btn_text = "Lưu tại..."

        tk.Button(row, text=btn_text, command=browse,
                  bg=BTN_NTR, fg=DARK, font=F_BTN,
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  activebackground=BTN_NTR_H).pack(side="left")

    def _date_row(self, parent):
        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x", padx=12, pady=(0, 6))

        tk.Label(row, text="Ngày hóa đơn *", bg=WHITE, fg=DARK, font=F_LBL,
                 width=24, anchor="w").pack(side="left")

        vcmd = (self.register(self._validate_date_char), "%P")
        self._date_entry = tk.Entry(
            row, textvariable=self.v_invoice_date,
            font=F_LBL, bg="#FFF8E1", relief="solid",
            highlightbackground=CARD_BDR, highlightthickness=1,
            width=14, validate="key", validatecommand=vcmd,
        )
        self._date_entry.pack(side="left", padx=(0, 6))

        tk.Label(row, text="dd/mm/yyyy", bg=WHITE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 10))

        tk.Button(row, text="Hôm nay", command=self._set_today,
                  bg=BTN_NTR, fg=DARK, font=F_BTN,
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  activebackground=BTN_NTR_H).pack(side="left")

    def _validate_date_char(self, new_val: str) -> bool:
        return all(c.isdigit() or c == "/" for c in new_val)

    def _set_today(self):
        self.v_invoice_date.set(datetime.now().strftime("%d/%m/%Y"))

    # ── Logging ───────────────────────────────────────────────────────────────
    def _setup_logging(self):
        self.gui_handler = TextHandler(self.log_text)
        self.gui_handler.setFormatter(logging.Formatter("%(message)s"))
        self.gui_handler.setLevel(logging.INFO)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ── Validate ──────────────────────────────────────────────────────────────
    def _validate(self) -> bool:
        errors = []
        for label, var in [
            ("File Pancake", self.v_pancake),
            ("Bảng giá thuốc", self.v_price_tbl),
            ("File mẫu meInvoice", self.v_template),
        ]:
            path = var.get().strip()
            if not path:
                errors.append(f"Chưa chọn {label}.")
            elif not os.path.exists(path):
                errors.append(f"{label} không tìm thấy:\n{path}")
        if not self.v_output.get().strip():
            errors.append("Chưa chọn đường dẫn file kết quả.")
        date_str = self.v_invoice_date.get().strip()
        if not date_str:
            errors.append("Chưa nhập ngày hóa đơn.")
        else:
            try:
                datetime.strptime(date_str, "%d/%m/%Y")
            except ValueError:
                errors.append(f"Ngày hóa đơn không hợp lệ: '{date_str}'\nĐịnh dạng đúng: dd/mm/yyyy")
        if errors:
            messagebox.showerror("Thiếu thông tin", "\n\n".join(errors))
            return False
        return True

    # ── Chạy ─────────────────────────────────────────────────────────────────
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
        import convert_pancake_to_meinvoice as core

        core.CONFIG["PANCAKE_FILE"]            = self.v_pancake.get().strip()
        core.CONFIG["TEMPLATE_FILE"]           = self.v_template.get().strip()
        core.CONFIG["OUTPUT_FILE"]             = self.v_output.get().strip()
        core.CONFIG["PRICE_TABLE_FILE"]        = self.v_price_tbl.get().strip()
        core.CONFIG["DEFAULT_INVOICE_DATE"]    = self.v_invoice_date.get().strip()
        core.CONFIG["EXPORT_ALL_IF_NO_STATUS"] = True

        core_log = logging.getLogger()
        core_log.setLevel(logging.DEBUG)
        for h in core_log.handlers[:]:
            core_log.removeHandler(h)
        core_log.addHandler(self.gui_handler)

        try:
            os.chdir(os.path.dirname(os.path.abspath(core.CONFIG["PANCAKE_FILE"])))
        except Exception:
            pass

        self._actual_output = core.CONFIG["OUTPUT_FILE"]
        success = False
        try:
            core.main()
            self._actual_output = core.CONFIG.get("_ACTUAL_OUTPUT", core.CONFIG["OUTPUT_FILE"])
            success = True
        except SystemExit:
            pass
        except PermissionError:
            logging.error("File output đang mở trong Excel — đóng file rồi thử lại.")
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
            messagebox.showerror("Lỗi chuyển đổi",
                                 "Chuyển đổi bị dừng do có lỗi.\nXem chi tiết trong log bên trên.")

    def _open_output_folder(self):
        out = self.v_output.get().strip()
        folder = os.path.dirname(os.path.abspath(out)) if out else os.path.expanduser("~")
        os.startfile(folder)

    def _open_price_editor(self):
        path = self.v_price_tbl.get().strip()
        if not path:
            messagebox.showwarning("Chưa chọn file", "Vui lòng chọn file bảng giá thuốc trước.")
            return
        if not os.path.isfile(path):
            messagebox.showwarning("Không tìm thấy", f"File không tồn tại:\n{path}")
            return
        PriceTableEditor(self, path)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    App().mainloop()
