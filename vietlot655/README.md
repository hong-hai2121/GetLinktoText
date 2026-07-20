# Vietlott Power 6/55 local crawler

## Install

```powershell
cd D:\Python\GetLinktoText\vietlot655
python -m pip install -r requirements.txt
```

## Crawl from web

```powershell
python crawl.py
```

By default, this is daily-update mode: the crawler starts from the newest page,
imports new draw periods, and stops as soon as it reaches a page where every
draw period already exists in SQLite. Vietlott uses links like
`javascript:NextPage(1);`; `crawl.py` calls the same AjaxPro endpoint directly
with `PageIndex=1,2,3...`.

Or pass a custom URL:

```powershell
python crawl.py --url "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-655"
```

Limit the number of pages when testing:

```powershell
python crawl.py --max-pages 20
python crawl.py --max-pages 1
```

Use `--full-crawl` only when you want to keep crawling old pages until Vietlott
returns an empty or repeated page:

```powershell
python crawl.py --full-crawl
```

While running, the crawler imports each page immediately and prints progress:

```text
Da import trang 1 (PageIndex=0): tim thay 8 ky, them moi 8, trung 0, tu ky 01370 (2026-07-11) den ky 01363 (2026-06-25)
Da import trang 2 (PageIndex=1): tim thay 8 ky, them moi 8, trung 0, tu ky 01362 (2026-06-23) den ky 01355 (2026-06-07)
```

If the run stops or fails later, pages already printed as imported have already
been committed to SQLite.

## Crawl from saved HTML

```powershell
python crawl.py --html-file "C:\path\to\vietlott.html"
```

Local HTML mode parses that file only. To follow `NextPage(n)` automatically,
run from the full Vietlott web URL so the crawler can read the Ajax key from the
page.

## Backtest 5 giai thuat tren ket qua that

Moi lan chay `crawl.py`, truoc khi cao ve, chuong trinh tu chot 1000 bo so cho
moi giai thuat (`balanced` / `hot` / `gan` / `pairs` / `payout`) dua tren lich su
hien co, luu vao `prediction_batches` + `prediction_sets`. Cao xong, ky moi da
nam trong DB thi cac bo do duoc cham diem ngay.

Vi bo so duoc chot TRUOC khi ky moi ve nen khong the "nhin truoc ket qua" —
diem cham tich luy qua nhieu ky cho biet giai thuat nao dang trung nhieu nhat.

```text
Du doan: power655: da chot batch #7 (1000 bo x 5 che do) sau ky 01372
... (cao) ...
Da cham diem 1 ky du doan (con 0 ky dang cho ket qua).
```

Chay lai `crawl.py` nhieu lan trong cung mot ky khong tao batch chong — batch
dang cho duoc giu nguyen. Tat bang `--no-predict`, doi so bo bang
`--predict-sets 5000`.

Xem bang xep hang:

```powershell
python predict_track.py board          # bang tren console
python stats_web.py                    # muc "Giai thuat nao dang trung nhieu nhat?"
```

### Chay lai lich su (backfill) — co bang xep hang ngay

Doi tung ky moi ve thi rat lau (moi tuan 3 ky). Lenh `backfill` duyet nguoc lich su:
voi moi ky, tinh ho so thong ke CHI tu cac ky TRUOC no, sinh bo so roi cham voi
chinh ky do.

```powershell
python predict_track.py backfill --periods 300 -n 1000
```

300 ky x 5 che do x 1000 bo = 1,5 trieu ve, mat ~15-20 phut, DB tang ~100MB.
Khong ky nao nhin thay ket qua cua chinh no nen van trung thuc nhu chay that.
Idempotent: ky nao da co batch thi bo qua, chay lai khong tao chong.

**KHONG can xoa lich su draw_results de "chay lai".** `crawl.py` chi chot 1 batch
moi lan chay, nen xoa 300 ky roi cao lai chi cho ra 1 ky co diem, khong phai 300.

### Luu tru: chi giu KET QUA, khong giu tung ve

- `prediction_sets` (ve chi tiet) chi ton tai trong luc CHO cham: sinh truoc khi ky
  moi ve, giu 5.000 ve lam bang chung da chot truoc.
- Cham xong, ket qua duoc gom vao `prediction_stats` — moi che do 1 dong voi so dem
  theo muc trung `c0..c6` (bao nhieu ve trung 0,1,2,3,4,5,6 so) — roi **xoa het ve**.
- 1 ky: 5.000 dong -> 5 dong. Moi so lieu cua bang xep hang (TB, >=3/4/5/6, tot nhat,
  phan bo, t-test) deu suy ra duoc tu c0..c6.

DB tao bang ban cu (luu tung ve) thu nho bang:

```powershell
python predict_track.py compact
```

Da kiem chung khong mat so lieu: 301 ky, 1.505.000 dong -> 1.505 dong, DB 71MB -> 0,5MB,
moi con so trong bang xep hang giu nguyen.

**Doi cong thuc sinh so = phai reset bang theo doi.** Neu sua thuat toan cua bat ky
che do nao, bang xep hang cu se tron 2 phien ban khac nhau duoi cung mot ten:

```powershell
python -c "import sqlite3;c=sqlite3.connect('vietlott_data.db');c.execute('delete from prediction_sets');c.execute('delete from prediction_batches');c.commit()"
```

## Boi so goi y & che do "Tranh so dong"

O muc **Bo so goi y** tren trang, o "So bo" nhan tu do 1–5000. Tu 21 bo tro len la
che do **boi so**: bo qua rang buoc "cac bo phai khac nhau >=2 so" (O(n^2), bat kha
thi o quy mo lon), chi dam bao khong trung lap, va hien them o van ban de chep/in
toan bo danh sach.

Che do **Tranh so dong** dung mo hinh do pho bien: ne so nhieu nguoi danh (ngay sinh
1–31, thang 1–12, duoi 8/6), uu tien duoi 0/9 va so >31, loai thang bo toan ngay
sinh / cap so cong / cung mot hang chuc. Moi lan boc 5 bo roi giu bo it nguoi danh
nhat.

**Quan trong:** viec nay KHONG lam tang xac suat trung. Vietlott chia Jackpot cho
nhung nguoi cung trung, nen bo it nguoi danh chi giup PHAI CHIA IT HON khi da trung.

Mo hinh nam o 2 noi va phai giong het nhau, neu khong bang xep hang doc tu DB se
lech voi backtest chay tren trang:

- `predict_track.py`: `pop_of_number` / `pop_of_set` / `is_crowded_set`
- `stats_web.py` (JS): `popOfNumber` / `popOfSet` / `isCrowdedSet`

He so theo duoi 8/6/4 la GIA DINH thoi quen VN (phat/loc/tu), khong lay tu nghien
cuu — Vietlott khong cong bo du lieu ve ban ra nen khong kiem chung duoc.

## Export

```powershell
python export_excel.py --format xlsx
python export_excel.py --format csv
python export_excel.py --format both
```

Outputs:

- `vietlott_data.db`
- `logs\crawler.log`
- `exports\vietlott_power655.xlsx`
- `exports\vietlott_power655.csv`

## Windows Task Scheduler

Create a daily task with:

- Program/script: `python`
- Add arguments: `"D:\Python\GetLinktoText\vietlot655\crawl.py"`
- Start in: `D:\Python\GetLinktoText\vietlot655`

If the website URL changes, edit `DEFAULT_URL` in `crawl.py` or set the
`VIETLOTT_URL` environment variable.
