"""
Lấy danh sách Page đang quản lý (Graph API /me/accounts) và hiển thị GUI để chọn.

- Tích chọn 1 hoặc nhiều page → bấm "Lấy chi tiết chiến dịch".
- Tool ghi các page đã chọn ra _pages_selected.json rồi MỞ get_page_campaigns.py
  (một tiến trình / cửa sổ Python mới) để quét các TKQC, lọc campaign chạy cho
  page đó và ghi vào Google Sheets.

Chạy:  python get_pages.py
"""

import sys
import json
import subprocess
import threading
from pathlib import Path

# Console Windows có thể là cp1252 → ép UTF-8 để log tiếng Việt không crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    tk = None

from config import ACCESS_TOKEN
from fb_api import graph_paginate, api_summary

BASE_DIR = Path(__file__).parent
FB_API_VERSION = "v20.0"

DETAIL_SCRIPT = BASE_DIR / "get_page_campaigns.py"
SELECTED_FILE = BASE_DIR / "_pages_selected.json"
PAGES_JSON = BASE_DIR / "pages.json"


# ── Facebook Graph API ───────────────────────────────────────────────────────

def fetch_managed_pages(access_token: str) -> list[dict]:
    """Trả về danh sách Page user/token đang có quyền (/me/accounts)."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/me/accounts"
    params = {
        "fields": "id,name,category,tasks",
        "access_token": access_token,
        "limit": 200,
    }
    return graph_paginate(url, params, label="me/accounts")


def save_pages_json(pages: list[dict]):
    with open(PAGES_JSON, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)
    print(f"Đã lưu danh sách page → {PAGES_JSON}")


def launch_detail(pages: list[dict]):
    """Ghi page đã chọn ra file rồi mở get_page_campaigns.py (tiến trình mới)."""
    with open(SELECTED_FILE, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    if not DETAIL_SCRIPT.exists():
        raise FileNotFoundError(f"Không tìm thấy {DETAIL_SCRIPT.name}")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_CONSOLE  # cửa sổ console riêng

    subprocess.Popen(
        [sys.executable, str(DETAIL_SCRIPT), str(SELECTED_FILE)],
        cwd=str(BASE_DIR),
        creationflags=creationflags,
    )


# ── GUI ──────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    BG         = "#eef2f6"
    CARD       = "#f8fafc"
    BORDER     = "#cbd5e1"
    ACCENT     = "#3b82f6"
    ACCENT_HV  = "#2563eb"
    ACCENT_DIS = "#93c5fd"
    TEXT       = "#334155"
    MUTED      = "#64748b"

    def __init__(self):
        super().__init__()
        self.title("Get Pages – Chọn Page Quản Lý")

        w, h = 760, 460
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(560, 320)
        self.configure(bg=self.BG)

        self._items: list[dict] = []

        self._apply_styles()
        self._build_ui()
        self._load_async()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=self.BG)
        s.configure("TLabel", background=self.BG,
                    font=("Segoe UI", 10), foreground=self.TEXT)
        s.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(14, 7),
                    background=self.BORDER, foreground=self.TEXT,
                    bordercolor=self.BORDER, relief="flat", borderwidth=1)
        s.map("TButton",
              background=[("active", "#cbd5e1"), ("disabled", self.BG)],
              foreground=[("disabled", self.MUTED)])
        s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(22, 9), background=self.ACCENT,
                    foreground="#FFFFFF", relief="flat", borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", self.ACCENT_HV), ("disabled", self.ACCENT_DIS)],
              foreground=[("disabled", "#ffffff")])
        s.configure("Treeview", font=("Segoe UI", 9), rowheight=28,
                    background=self.CARD, fieldbackground=self.CARD,
                    foreground=self.TEXT, borderwidth=0)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background=self.BORDER, foreground=self.MUTED,
                    relief="flat", padding=(8, 6))
        s.map("Treeview",
              background=[("selected", self.ACCENT)],
              foreground=[("selected", "#ffffff")])
        s.configure("TProgressbar", background=self.ACCENT,
                    troughcolor=self.BORDER, borderwidth=0, thickness=6)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=18, pady=14)

        hdr = tk.Frame(outer, bg=self.BG)
        hdr.pack(fill="x", pady=(0, 10))
        tk.Label(hdr, text="Get Pages", bg=self.BG,
                 font=("Segoe UI Semibold", 15), fg=self.TEXT).pack(side="left")
        self._status_lbl = tk.Label(hdr, text="Đang kết nối...",
                                     bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED)
        self._status_lbl.pack(side="right")

        tk.Label(outer,
                 text="Click dòng để bật / tắt. Tích page rồi bấm \"Lấy chi tiết chiến dịch\" "
                      "để mở cửa sổ quét campaign của page.",
                 bg=self.BG, font=("Segoe UI", 9), fg=self.MUTED,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        bot = tk.Frame(outer, bg=self.BG)
        bot.pack(fill="x", pady=(12, 0), side="bottom")

        card = tk.Frame(outer, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = ("chon", "page_name", "page_id", "category")
        self._tree = ttk.Treeview(card, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("chon",      text="Chọn",       anchor="center")
        self._tree.heading("page_name", text="Tên Page",   anchor="w")
        self._tree.heading("page_id",   text="Page ID",    anchor="w")
        self._tree.heading("category",  text="Danh Mục",   anchor="w")
        self._tree.column("chon",      width=56,  stretch=False, anchor="center", minwidth=50)
        self._tree.column("page_name", width=260, stretch=True,  minwidth=140)
        self._tree.column("page_id",   width=170, stretch=False, minwidth=110)
        self._tree.column("category",  width=170, stretch=False, minwidth=110)

        vsb = ttk.Scrollbar(card, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(card, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("on",  foreground="#198754")
        self._tree.tag_configure("off", foreground="#dc3545")
        self._tree.tag_configure("odd", background="#f1f3f5")

        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind("<space>",           self._on_space)

        ttk.Button(bot, text="Bật tất cả",
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bot, text="Tắt tất cả",
                   command=lambda: self._set_all(False)).pack(side="left", padx=(6, 0))

        self._count_lbl = tk.Label(bot, text="", bg=self.BG,
                                   font=("Segoe UI", 9), fg=self.MUTED)
        self._count_lbl.pack(side="left", padx=10)

        self._run_btn = ttk.Button(bot, text="Lấy chi tiết chiến dịch",
                                   style="Accent.TButton",
                                   command=self._run, state="disabled")
        self._run_btn.pack(side="right")
        ttk.Button(bot, text="Đóng", command=self.destroy).pack(side="right", padx=(0, 8))
        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=110)
        self._progress.pack(side="right", padx=(0, 10))

    # ── Load pages ──────────────────────────────────────────────────────────────

    def _load_async(self):
        self._progress.start(12)
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self):
        try:
            pages = fetch_managed_pages(ACCESS_TOKEN)
            save_pages_json(pages)
            api_summary()
            self.after(0, lambda: self._load_items(pages))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"Lỗi: {e}", error=True))
            self.after(0, self._progress.stop)

    def _load_items(self, pages: list[dict]):
        self._progress.stop()
        self._set_status(f"Tìm thấy {len(pages)} page đang quản lý")
        self._items = []
        for i, pg in enumerate(pages):
            tags = ("odd", "off") if i % 2 != 0 else ("off",)
            iid = self._tree.insert("", "end", values=(
                "✗",
                pg.get("name", ""),
                pg.get("id", ""),
                pg.get("category", ""),
            ), tags=tags)
            self._items.append({
                "id": pg.get("id", ""),
                "name": pg.get("name", ""),
                "category": pg.get("category", ""),
                "iid": iid,
                "selected": False,
            })
        self._refresh_count()

    # ── Toggle ──────────────────────────────────────────────────────────────────

    def _update_item_ui(self, item: dict):
        idx = self._items.index(item)
        base_tag = "on" if item["selected"] else "off"
        tags = ("odd", base_tag) if idx % 2 != 0 else (base_tag,)
        self._tree.item(item["iid"], values=(
            "✓" if item["selected"] else "✗",
            item["name"], item["id"], item["category"],
        ), tags=tags)

    def _toggle(self, iid: str):
        item = next((i for i in self._items if i["iid"] == iid), None)
        if item is None:
            return
        item["selected"] = not item["selected"]
        self._update_item_ui(item)
        self._refresh_count()
        self._run_btn.configure(
            state="normal" if any(i["selected"] for i in self._items) else "disabled"
        )

    def _on_click(self, event):
        iid = self._tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _on_space(self, _):
        for iid in self._tree.selection():
            self._toggle(iid)

    def _set_all(self, value: bool):
        for item in self._items:
            item["selected"] = value
            self._update_item_ui(item)
        self._refresh_count()
        self._run_btn.configure(state="normal" if value and self._items else "disabled")

    def _refresh_count(self):
        total = len(self._items)
        selected = sum(1 for i in self._items if i["selected"])
        self._count_lbl.configure(
            text=f"{selected}/{total} được chọn" if total else "Danh sách trống"
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def _run(self):
        pages = [{"id": i["id"], "name": i["name"]} for i in self._items if i["selected"]]
        if not pages:
            messagebox.showwarning("Chưa chọn", "Chưa tích page nào.")
            return
        try:
            launch_detail(pages)
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            return
        names = ", ".join(p["name"] for p in pages)
        self._set_status(f"Đã mở cửa sổ lấy chi tiết cho {len(pages)} page")
        messagebox.showinfo(
            "Đã mở",
            f"Đang lấy chi tiết chiến dịch cho:\n{names}\n\n"
            "Một cửa sổ mới (get_page_campaigns.py) đã mở để xử lý.",
        )

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, foreground="#dc3545" if error else self.MUTED
        )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if tk is None:
        sys.exit("Cần tkinter để chạy giao diện (có sẵn trong Python chuẩn trên Windows).")
    App().mainloop()
