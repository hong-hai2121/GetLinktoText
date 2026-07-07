# -*- coding: utf-8 -*-
"""
GetReelStats.py — Crawl chỉ số Reel Facebook bằng Firefox + Selenium.

Mục đích: quét các Reel của 1 trang/profile, lấy lượt thích / bình luận / chia sẻ
để CHỌN video có tương tác tốt nhất đem đi chạy quảng cáo.

Luồng (theo yêu cầu):
  1. Lấy danh sách link Reel từ trang profile/Page (cuộn để nạp thêm).
  2. Mở từng link Reel.
  3. Chờ trang tải xong.
  4. Tìm khu vực hiển thị lượt thích / bình luận / chia sẻ và đọc số.
  5. (TẮT mặc định) Bấm mở comment.
  6. (TẮT mặc định) Cuộn comment.
  7. (TẮT mặc định) Lưu text/tên/thời gian comment.
  8. Xuất Excel (.xlsx) — mặc định; hoặc Google Sheet nếu có service account.

Dùng Firefox profile đã đăng nhập sẵn (giống các tool khác trong repo).

VÍ DỤ CHẠY:
    # Quét reels của 1 Page theo username, lấy tối đa 40 reel, xuất Excel:
    python GetReelStats.py --source lamdep.official --max 40

    # Quét từ URL trang reels đầy đủ:
    python GetReelStats.py --source "https://www.facebook.com/lamdep.official/reels/"

    # Đọc sẵn danh sách link Reel từ file .txt (mỗi dòng 1 link):
    python GetReelStats.py --source reel_links.txt

    # Đổi profile Firefox + chạy ẩn (headless):
    python GetReelStats.py --source lamdep.official --profile Profile02 --headless

    # In toàn bộ aria-label để dò lại selector khi Facebook đổi giao diện:
    python GetReelStats.py --source "https://www.facebook.com/reel/123456" --debug

LƯU Ý QUAN TRỌNG:
  - Firefox KHÔNG được mở sẵn bằng chính profile này (profile bị khoá) — hãy
    đóng hết cửa sổ Firefox trước, hoặc thêm cờ --kill-firefox để script tự tắt.
  - Giao diện Facebook hay đổi. Nếu số đọc sai/trống, chạy lại với --debug rồi
    chỉnh danh sách từ khoá trong LABEL_KEYWORDS ở dưới.
"""

import argparse
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from html.parser import HTMLParser

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# File này nằm trong thư mục con ReelStats/. config.py và profiles_config.py ở
# thư mục gốc dự án -> thêm thư mục cha vào sys.path để import được.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import GECKODRIVER_PATH
from profiles_config import FIREFOX_PROFILE_PATH, PROFILES

# ── Từ khoá aria-label để nhận diện nút Thích / Bình luận / Chia sẻ ───────────
# Facebook đặt aria-label theo ngôn ngữ của profile. Thêm biến thể nếu cần.
LABEL_KEYWORDS = {
    "likes": ["thích", "cảm xúc", "like", "reaction"],
    "comments": ["bình luận", "comment"],
    "shares": ["chia sẻ", "share"],
}

REEL_HREF_RE = re.compile(r"/reel/(\d+)")

# File link mặc định (khi bấm Run trong IDE, không truyền --source).
DEFAULT_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reel_links.txt")


# ── Chuyển "1,2 N" / "1.2K" / "3,4 Tr" ... → số nguyên ───────────────────────
def parse_count(text):
    """Đọc số tương tác từ chuỗi hiển thị (hỗ trợ locale VN và EN).

    VN: dấu phẩy = thập phân, dấu chấm = phân cách nghìn; N=nghìn, Tr=triệu.
    EN: K=nghìn, M=triệu, B=tỷ.
    Ví dụ: '1,2 N' -> 1200 ; '1.234' -> 1234 ; '1.2K' -> 1200 ; '999' -> 999.
    Trả về None nếu không tìm thấy số.
    """
    if text is None:
        return None
    t = str(text).replace("\xa0", " ").strip()
    if not t:
        return None

    m = re.search(r"(\d[\d.,]*)\s*(nghìn|triệu|tr|n|k|m|b)?", t, re.IGNORECASE)
    if not m:
        return None

    num_str = m.group(1)
    suffix = (m.group(2) or "").lower()
    mult = {
        "": 1, "n": 1_000, "k": 1_000, "nghìn": 1_000,
        "tr": 1_000_000, "triệu": 1_000_000, "m": 1_000_000, "b": 1_000_000_000,
    }.get(suffix, 1)

    try:
        if suffix:  # có hậu tố (1,2 N / 1.2K) -> phần số là thập phân ngắn, không có nghìn
            num_str = num_str.replace(",", ".")
            value = float(num_str) * mult
        else:  # không hậu tố -> chấm/phẩy đều là phân cách nghìn
            num_str = num_str.replace(".", "").replace(",", "")
            value = float(num_str)
    except ValueError:
        return None
    return int(round(value))


# ── Khởi tạo Firefox với profile đã đăng nhập ────────────────────────────────
def kill_firefox():
    """Tắt mọi tiến trình Firefox để giải phóng profile đang bị khoá."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "firefox.exe"], timeout=5)
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Không tắt được Firefox (có thể chưa mở): {e}")


def build_driver(profile_path, headless=False, page_load_timeout=45):
    """Mở Firefox bằng Selenium với profile chỉ định (giống browser_client.init_firefox)."""
    options = FirefoxOptions()
    options.add_argument("-profile")
    options.add_argument(profile_path)
    if headless:
        options.add_argument("-headless")
    service = FirefoxService(executable_path=GECKODRIVER_PATH)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_page_load_timeout(page_load_timeout)
    return driver


# ── Bước 1: lấy danh sách link Reel ──────────────────────────────────────────
def build_collection_url(source):
    """Chuẩn hoá `source` thành URL trang chứa các Reel để quét.

    - username thuần  -> https://www.facebook.com/<user>/reels/
    - URL profile     -> thêm /reels/ nếu chưa có
    - URL đã có /reel -> giữ nguyên
    """
    if source.startswith("http"):
        url = source.rstrip("/")
        if "/reel" not in url:
            url += "/reels/"
        return url
    return f"https://www.facebook.com/{source.strip('/')}/reels/"


def collect_reel_links(driver, source, max_reels, scrolls, pause=2.0):
    """Cuộn trang profile/Page để gom link Reel (dedupe, giữ thứ tự)."""
    url = build_collection_url(source)
    print(f"🌐 Mở trang reels: {url}")
    driver.get(url)
    time.sleep(5)

    found = {}  # id -> url (dict giữ thứ tự chèn, tự dedupe)
    stagnant = 0
    for i in range(scrolls):
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/reel/']")
        before = len(found)
        for a in anchors:
            href = a.get_attribute("href") or ""
            m = REEL_HREF_RE.search(href)
            if m:
                rid = m.group(1)
                found.setdefault(rid, f"https://www.facebook.com/reel/{rid}")

        print(f"  ↕ Cuộn {i + 1}/{scrolls} — đã thấy {len(found)} reel.")
        if len(found) >= max_reels:
            break

        if len(found) == before:
            stagnant += 1
            if stagnant >= 4:  # 4 lần cuộn liên tiếp không thêm gì -> dừng
                print("  ⛔ Không nạp thêm reel mới, dừng cuộn.")
                break
        else:
            stagnant = 0

        driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
        time.sleep(pause)

    links = list(found.values())[:max_reels]
    print(f"✅ Thu được {len(links)} link Reel.")
    return links


def read_links_file(path):
    """Đọc danh sách link Reel từ file .txt (mỗi dòng 1 link; bỏ dòng trống và dòng '#')."""
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    links = []
    for ln in lines:
        m = REEL_HREF_RE.search(ln)
        links.append(f"https://www.facebook.com/reel/{m.group(1)}" if m else ln)
    print(f"✅ Đọc {len(links)} link từ {path}.")
    return links


# ── Bước 4: đọc chỉ số trên trang Reel ───────────────────────────────────────
def _count_near(el, levels=3):
    """Đi ngược lên tối đa `levels` ông cha, tìm span ngắn có nội dung là 1 con số."""
    node = el
    for _ in range(levels):
        try:
            parent = node.find_element(By.XPATH, "./..")
        except Exception:
            break
        for span in parent.find_elements(By.XPATH, ".//span"):
            txt = (span.text or "").strip()
            if txt and len(txt) <= 8:
                c = parse_count(txt)
                if c is not None:
                    return c
        node = parent
    return None


def _count_for(driver, keywords):
    """Tìm nút theo aria-label khớp `keywords` rồi lấy số: từ nhãn -> text nút -> span gần."""
    for el in driver.find_elements(By.CSS_SELECTOR, "[aria-label]"):
        try:
            label = (el.get_attribute("aria-label") or "").lower()
        except Exception:
            continue
        if not any(k in label for k in keywords):
            continue
        for candidate in (parse_count(label), parse_count(el.text), _count_near(el)):
            if candidate is not None:
                return candidate
    return None


def extract_reel_metrics(driver, url, wait_seconds, debug=False):
    """Mở 1 Reel, chờ tải, đọc likes/comments/shares + caption. Trả về dict."""
    row = {
        "url": url,
        "reel_id": (REEL_HREF_RE.search(url).group(1) if REEL_HREF_RE.search(url) else ""),
        "likes": None, "comments": None, "shares": None,
        "caption": "", "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "",
    }
    try:
        driver.get(url)
    except Exception as e:
        row["note"] = f"lỗi tải trang: {e}"
        return row

    # Bước 3: chờ trang tải xong (body xuất hiện + nghỉ thêm để JS render).
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass
    time.sleep(wait_seconds)

    if debug:
        _dump_aria_labels(driver)

    row["likes"] = _count_for(driver, LABEL_KEYWORDS["likes"])
    row["comments"] = _count_for(driver, LABEL_KEYWORDS["comments"])
    row["shares"] = _count_for(driver, LABEL_KEYWORDS["shares"])
    row["caption"] = _extract_caption(driver)

    print(
        f"  👍 {row['likes']}   💬 {row['comments']}   ↪ {row['shares']}"
        f"   | {row['caption'][:50]}"
    )
    return row


def _extract_caption(driver):
    """Lấy mô tả/caption reel để dễ nhận diện video (best-effort)."""
    for meta in ("meta[property='og:description']", "meta[name='description']"):
        try:
            el = driver.find_element(By.CSS_SELECTOR, meta)
            content = (el.get_attribute("content") or "").strip()
            if content:
                return content
        except Exception:
            continue
    return ""


def _dump_aria_labels(driver):
    """Chế độ --debug: in mọi aria-label + số dò được để chỉnh lại từ khoá/selector."""
    print("  ── DEBUG: các aria-label trên trang ──")
    seen = set()
    for el in driver.find_elements(By.CSS_SELECTOR, "[aria-label]"):
        try:
            label = (el.get_attribute("aria-label") or "").strip()
        except Exception:
            continue
        if label and label not in seen:
            seen.add(label)
            print(f"     aria-label={label!r}  near={_count_near(el)}")
    print("  ── HẾT DEBUG ──")


def engagement_score(row):
    """Điểm xếp hạng để chọn video chạy ads: like + 2*comment + 3*share."""
    likes = row.get("likes") or 0
    comments = row.get("comments") or 0
    shares = row.get("shares") or 0
    return likes + comments * 2 + shares * 3


# ── Bước 8: xuất kết quả ─────────────────────────────────────────────────────
HEADERS = [
    "STT", "Reel ID", "Link", "Lượt thích", "Bình luận", "Chia sẻ",
    "Lượt xem", "Điểm tương tác", "Caption", "Thời điểm lấy", "Ghi chú",
]


def _save_workbook(wb, path):
    """Lưu workbook; nếu file đang mở trong Excel -> báo lỗi dễ hiểu."""
    try:
        wb.save(path)
    except PermissionError:
        raise PermissionError(
            f"Không ghi được vào:\n{path}\n\n"
            f"File Excel đang MỞ. Hãy ĐÓNG file đó trong Excel rồi thử lại."
        )


def export_excel(rows, out_path):
    """Ghi kết quả ra .xlsx, sắp xếp theo điểm tương tác giảm dần."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    rows_sorted = sorted(rows, key=engagement_score, reverse=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Reel Stats"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for i, r in enumerate(rows_sorted, start=1):
        ws.append([
            i, r.get("reel_id", ""), r.get("url", ""),
            r.get("likes"), r.get("comments"), r.get("shares"),
            r.get("views"), engagement_score(r), r.get("caption", ""),
            r.get("collected_at", ""), r.get("note", ""),
        ])

    widths = [5, 16, 42, 11, 11, 10, 10, 14, 50, 20, 24]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = w

    _save_workbook(wb, out_path)
    print(f"💾 Đã lưu Excel: {out_path} ({len(rows_sorted)} reel).")


def export_gsheet(rows, sheet_id, sa_path, worksheet="Reel Stats"):
    """(Tuỳ chọn) Đẩy kết quả lên Google Sheet bằng service account."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(worksheet)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet, rows=2000, cols=len(HEADERS) + 2)

    rows_sorted = sorted(rows, key=engagement_score, reverse=True)
    data = [HEADERS]
    for i, r in enumerate(rows_sorted, start=1):
        data.append([
            i, r.get("reel_id", ""), r.get("url", ""),
            r.get("likes"), r.get("comments"), r.get("shares"),
            r.get("views"), engagement_score(r), r.get("caption", ""),
            r.get("collected_at", ""), r.get("note", ""),
        ])
    ws.update(values=data, range_name="A1", value_input_option="RAW")
    print(f"💾 Đã đẩy lên Google Sheet {sheet_id} / tab '{worksheet}'.")


# ── Cập nhật lượt xem từ HTML lưới reels (copy element ở trang profile) ───────
class _ReelViewsParser(HTMLParser):
    """Duyệt HTML lưới reels; mỗi <a href=/reel/ID> chứa 1 số = lượt xem (cạnh icon mắt)."""

    def __init__(self):
        super().__init__()
        self.result = {}   # reel_id -> lượt xem (int)
        self._stack = []   # id của các thẻ <a> đang mở (an toàn khi lồng nhau)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "") or ""
            m = REEL_HREF_RE.search(href)
            self._stack.append(m.group(1) if m else None)

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if not self._stack:
            return
        rid = self._stack[-1]
        if not rid or rid in self.result:  # chỉ lấy số ĐẦU TIÊN trong mỗi anchor
            return
        text = data.strip()
        if ":" in text:  # bỏ qua thời lượng video kiểu "0:15"
            return
        v = parse_count(text)
        if v is not None:
            self.result[rid] = v


def parse_views_html(html):
    """Trả về {reel_id: lượt xem} từ đoạn HTML lưới reels đã copy."""
    parser = _ReelViewsParser()
    parser.feed(html)
    return parser.result


def update_views_in_excel(xlsx_path, views_map):
    """Điền cột 'Lượt xem' cho các dòng có Reel ID khớp `views_map`.

    Chỉ cập nhật dòng ĐÃ CÓ trong Excel (không thêm dòng mới). Nếu file cũ chưa có
    cột 'Lượt xem' thì tự thêm. Trả về (số dòng cập nhật, danh sách id không khớp).
    """
    from openpyxl import load_workbook

    if not os.path.isfile(xlsx_path):
        raise FileNotFoundError(f"Chưa có file Excel: {xlsx_path}. Hãy chạy crawl trước.")
    if not views_map:
        return 0, []

    wb = load_workbook(xlsx_path)
    ws = wb.active
    header = [c.value for c in ws[1]]

    if "Reel ID" not in header:
        raise ValueError("File Excel không có cột 'Reel ID' để đối chiếu.")
    id_col = header.index("Reel ID") + 1

    if "Lượt xem" in header:
        views_col = header.index("Lượt xem") + 1
    else:  # file cũ -> thêm cột ở cuối
        views_col = len(header) + 1
        ws.cell(row=1, column=views_col, value="Lượt xem")

    remaining = dict(views_map)
    updated = 0
    for row in range(2, ws.max_row + 1):
        rid = ws.cell(row=row, column=id_col).value
        rid = str(rid).strip() if rid is not None else ""
        if rid in remaining:
            ws.cell(row=row, column=views_col, value=remaining.pop(rid))
            updated += 1

    _save_workbook(wb, xlsx_path)
    return updated, list(remaining.keys())


# ── Xếp hạng chọn video chạy ads ─────────────────────────────────────────────
# ER%    = (like + comment + share) / view × 100   — tỷ lệ tương tác trên view.
# Share% = share / view × 100                       — tín hiệu lan truyền mạnh nhất.
# WER%   = (like + 3×comment + 5×share) / view × 100 — tương tác có trọng số.
# Điểm Ads = WER% × log10(view) — thưởng creative tương tác cao + đã phủ ở quy mô lớn.
AD_METRIC_COLS = ("ER%", "Share%", "Điểm Ads")

# Giải thích từng chỉ số — dùng cho comment trong Excel VÀ chú thích khi in bảng.
AD_METRIC_HELP = {
    "ER%": ("Tỷ lệ tương tác = (like + comment + share) / view × 100. "
            "Đo sức hút của video trên mỗi lượt xem; CAO = creative tốt, chạy ads hiệu quả."),
    "Share%": ("Tỷ lệ chia sẻ = share / view × 100. "
               "Share là tín hiệu mạnh nhất: người xem chia sẻ → lan truyền tự nhiên → CPM rẻ hơn."),
    "Điểm Ads": ("Điểm tổng hợp để chọn video chạy ads, càng CAO càng nên ưu tiên. "
                 "= WER% × log10(view), với WER% = (like + 3×comment + 5×share) / view × 100 "
                 "(chia sẻ/bình luận được tính nặng hơn like)."),
}


def ad_legend():
    """Các dòng chú thích chỉ số, in kèm bảng xếp hạng cho dễ hiểu."""
    return [
        "Chú thích chỉ số:",
        "  • Điểm Ads: điểm tổng hợp, càng CAO càng nên chạy ads (= WER% × log10(view)).",
        "  • ER%   : tỷ lệ tương tác = (like+comment+share)/view×100 — video càng hút.",
        "  • Share%: tỷ lệ chia sẻ = share/view×100 — tín hiệu lan truyền mạnh nhất.",
        "  • view  : tổng lượt xem của reel.",
    ]


def _ad_metrics(like, cmt, sh, view):
    if view <= 0:
        return 0.0, 0.0, 0.0
    er = (like + cmt + sh) / view * 100
    shr = sh / view * 100
    wer = (like + 3 * cmt + 5 * sh) / view * 100
    return round(er, 2), round(shr, 2), round(wer * math.log10(view), 1)


def rank_for_ads(xlsx_path):
    """Thêm cột ER% / Share% / Điểm Ads vào Excel, sắp xếp giảm dần theo Điểm Ads.

    Giữ nguyên mọi cột sẵn có (kể cả Ghi chú người dùng nhập). Trả về list top 10
    (dict: cap, view, er, share, ad) để hiển thị.
    """
    from openpyxl import load_workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    if not os.path.isfile(xlsx_path):
        raise FileNotFoundError(f"Chưa có file Excel: {xlsx_path}. Hãy chạy crawl trước.")

    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    values = list(ws.iter_rows(values_only=True))
    if len(values) < 2:
        raise ValueError("File Excel chưa có dữ liệu để xếp hạng.")

    header = list(values[0])
    rows = [list(r) for r in values[1:]]
    idx = {name: i for i, name in enumerate(header)}

    def need(name):
        if name not in idx:
            raise ValueError(f"File Excel thiếu cột '{name}'.")
        return idx[name]

    ci_like, ci_cmt, ci_sh, ci_view = (
        need("Lượt thích"), need("Bình luận"), need("Chia sẻ"), need("Lượt xem"))

    for col in AD_METRIC_COLS:  # thêm cột metric nếu chưa có
        if col not in idx:
            idx[col] = len(header)
            header.append(col)
    for r in rows:  # đảm bảo mọi dòng đủ độ dài cột
        r.extend([None] * (len(header) - len(r)))

    def fnum(r, i):
        try:
            return float(r[i])
        except (TypeError, ValueError):
            return 0.0

    for r in rows:
        er, shr, ad = _ad_metrics(fnum(r, ci_like), fnum(r, ci_cmt), fnum(r, ci_sh), fnum(r, ci_view))
        r[idx["ER%"]], r[idx["Share%"]], r[idx["Điểm Ads"]] = er, shr, ad

    rows.sort(key=lambda r: r[idx["Điểm Ads"]] or 0, reverse=True)
    if "STT" in idx:  # đánh lại số thứ tự sau khi sắp xếp
        for n, r in enumerate(rows, 1):
            r[idx["STT"]] = n

    ws.delete_rows(1, ws.max_row)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for col in AD_METRIC_COLS:
        ws.column_dimensions[get_column_letter(idx[col] + 1)].width = 10
        cell = ws.cell(row=1, column=idx[col] + 1)  # gắn giải thích (di chuột để xem)
        cmt = Comment(AD_METRIC_HELP[col], "ReelStats")
        cmt.width, cmt.height = 320, 120
        cell.comment = cmt
    ws.freeze_panes = "A2"
    _save_workbook(wb, xlsx_path)

    cap_i = idx.get("Caption")
    url_i = idx.get("Link")
    top = []
    for r in rows[:10]:
        cap = str(r[cap_i]).split("\n")[0][:45] if cap_i is not None and r[cap_i] else ""
        url = str(r[url_i]) if url_i is not None and r[url_i] else ""
        top.append({
            "cap": cap, "url": url, "view": fnum(r, ci_view),
            "er": r[idx["ER%"]], "share": r[idx["Share%"]], "ad": r[idx["Điểm Ads"]],
        })
    return top


# ── CLI ──────────────────────────────────────────────────────────────────────
def resolve_profile_path(name):
    if not name:
        return FIREFOX_PROFILE_PATH
    if name in PROFILES:
        return PROFILES[name]
    if os.path.isdir(name):  # cho phép truyền thẳng đường dẫn profile
        return name
    raise SystemExit(f"❌ Profile '{name}' không có trong profiles_config.PROFILES: {list(PROFILES)}")


def resolve_source(source):
    """Tìm nguồn link. Ưu tiên --source; nếu trống -> reel_links.txt; nếu vẫn không có -> hỏi nhập."""
    if source:
        return source
    if os.path.isfile(DEFAULT_LINKS_FILE):
        print(f"📄 Không có --source, dùng file mặc định: {DEFAULT_LINKS_FILE}")
        return DEFAULT_LINKS_FILE
    print("❓ Chưa có nguồn link. Nhập đường dẫn file .txt / username / URL reels")
    print(f"   (hoặc tạo sẵn file {DEFAULT_LINKS_FILE} rồi bấm Run lại):")
    try:
        answer = input("   > ").strip().strip('"')
    except EOFError:
        answer = ""
    if not answer:
        raise SystemExit("❌ Không có nguồn link. Dừng.")
    return answer


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Crawl chỉ số Reel Facebook để chọn video chạy ads.")
    p.add_argument("--source", default=None,
                   help="username, URL trang/reels, hoặc file .txt chứa link Reel. "
                        "Bỏ trống -> đọc reel_links.txt cạnh script, hoặc hỏi nhập.")
    p.add_argument("--max", type=int, default=30, help="Số reel tối đa (mặc định 30).")
    p.add_argument("--scrolls", type=int, default=15, help="Số lần cuộn khi gom link (mặc định 15).")
    p.add_argument("--wait", type=float, default=4.0, help="Giây chờ render mỗi reel (mặc định 4).")
    p.add_argument("--out", default=os.path.join(os.path.dirname(DEFAULT_LINKS_FILE), "reel_stats.xlsx"),
                   help="File Excel xuất ra (mặc định cạnh script).")
    p.add_argument("--profile", default=None, help="Tên profile trong profiles_config (vd Profile02).")
    p.add_argument("--headless", action="store_true", help="Chạy Firefox ẩn.")
    p.add_argument("--kill-firefox", action="store_true", help="Tắt Firefox đang mở trước khi chạy.")
    p.add_argument("--debug", action="store_true", help="In aria-label để dò selector.")
    p.add_argument("--gsheet", default=None, help="(Tuỳ chọn) Google Sheet ID để đẩy kết quả.")
    p.add_argument("--sa", default=os.environ.get("GOOGLE_SERVICE_ACCOUNT"),
                   help="Đường dẫn service account .json (mặc định lấy env GOOGLE_SERVICE_ACCOUNT).")
    p.add_argument("--views-html", default=None,
                   help="File .html (copy element lưới reels) -> chỉ cập nhật cột Lượt xem vào --out rồi thoát.")
    p.add_argument("--rank", action="store_true",
                   help="Chỉ tính ER%/Share%/Điểm Ads + xếp hạng file --out rồi thoát.")
    return p.parse_args(argv)


def run_pipeline(source, out, profile_path, wait=4.0, headless=False,
                 kill=False, debug=False, max_reels=30, scrolls=15,
                 gsheet=None, sa=None, stop_event=None):
    """Chạy toàn bộ luồng crawl (dùng chung cho CLI và GUI).

    - `source`: file .txt link / username / URL reels.
    - `stop_event`: threading.Event — nếu set thì dừng sau reel đang xử lý.
    Trả về danh sách rows (kể cả khi dừng giữa chừng vẫn xuất phần đã lấy).
    """
    def stopped():
        return stop_event is not None and stop_event.is_set()

    print(f"🦊 Dùng Firefox profile: {profile_path}")
    if kill:
        kill_firefox()

    driver = None
    rows = []
    try:
        driver = build_driver(profile_path, headless=headless)

        # Bước 1: lấy danh sách link Reel.
        if os.path.isfile(source):
            links = read_links_file(source)
        else:
            links = collect_reel_links(driver, source, max_reels, scrolls)

        if not links:
            print("❌ Không có link Reel nào để xử lý.")
            return rows

        # Bước 2-4: mở từng reel, đọc chỉ số.
        for idx, link in enumerate(links, start=1):
            if stopped():
                print("⏹️ Đã nhận yêu cầu dừng, ngừng xử lý các reel còn lại.")
                break
            print(f"\n🎬 [{idx}/{len(links)}] {link}")
            rows.append(extract_reel_metrics(driver, link, wait, debug=debug))

        # Bước 8: xuất kết quả.
        if rows:
            export_excel(rows, out)
            if gsheet:
                if not sa:
                    print("⚠️ Có --gsheet nhưng thiếu service account (--sa). Bỏ qua Google Sheet.")
                else:
                    export_gsheet(rows, gsheet, sa)

            best = max(rows, key=engagement_score, default=None)
            if best and engagement_score(best) > 0:
                print(
                    f"\n🏆 Reel tương tác cao nhất: {best['url']}\n"
                    f"   👍 {best['likes']}  💬 {best['comments']}  ↪ {best['shares']}"
                )
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        if "profile" in str(e).lower() or "lock" in str(e).lower():
            print("💡 Firefox có thể đang mở bằng profile này. Đóng Firefox hoặc bật 'Tắt Firefox trước khi chạy'.")
        raise
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    return rows


def main(argv=None):
    args = parse_args(argv)

    # Chế độ chỉ cập nhật lượt xem từ HTML (không crawl).
    if args.views_html:
        with open(args.views_html, "r", encoding="utf-8") as f:
            html = f.read()
        vmap = parse_views_html(html)
        print(f"🔎 Tìm thấy {len(vmap)} reel có lượt xem trong HTML.")
        updated, missing = update_views_in_excel(args.out, vmap)
        print(f"✅ Đã cập nhật lượt xem cho {updated} dòng. Không khớp Excel: {len(missing)}.")
        return

    # Chế độ chỉ xếp hạng chọn video chạy ads (không crawl).
    if args.rank:
        top = rank_for_ads(args.out)
        print("🏆 TOP 10 NÊN CHẠY ADS — chọn video bơm quảng cáo")
        for line in ad_legend():
            print("   " + line)
        print("   " + "-" * 56)
        for i, d in enumerate(top, 1):
            print(f"  {i:>2}. AdScore {d['ad']:>5} | view {int(d['view']):>7} | "
                  f"ER {d['er']}% | share {d['share']}% | {d['cap']}")
            print(f"      {d['url']}")
        return

    source = resolve_source(args.source)
    profile_path = resolve_profile_path(args.profile)
    run_pipeline(
        source, args.out, profile_path,
        wait=args.wait, headless=args.headless, kill=args.kill_firefox,
        debug=args.debug, max_reels=args.max, scrolls=args.scrolls,
        gsheet=args.gsheet, sa=args.sa,
    )


if __name__ == "__main__":
    main()
