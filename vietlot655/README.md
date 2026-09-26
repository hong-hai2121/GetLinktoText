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

`crawl.py` cao duoc CA HAI game (`--game power655|mega645|all`);
`crawl_mega645.py` chi la wrapper mong tro san `--game mega645` + DB rieng
(xem `README_MEGA645.md`). HTTP co retry 3 lan (backoff 1s/2s/4s) cho loi mang
va 5xx/52x (Cloudflare); so trung cao ve duoc validate dai 1..55 (Power) /
1..45 (Mega) — so ngoai dai hay trung nhau la bo qua ky do + ghi warning vao
log thay vi nap du lieu ban vao DB.

Exit code: `0` = tron ven, `2` = partial (loi giua chung nhung DA luu duoc
trang moi), `1` = fail trang — Task Scheduler dat canh bao theo ma nay duoc.

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

## Backtest 7 giai thuat tren ket qua that

Moi lan chay `crawl.py`, truoc khi cao ve, chuong trinh tu chot 1000 bo so cho
moi giai thuat (`balanced` / `hot` / `gan` / `pairs` / `payout` / `spread` /
`cover`) dua tren
lich su hien co, luu vao `prediction_batches` + `prediction_sets`. Cao xong, ky moi
da nam trong DB thi cac bo do duoc cham diem ngay.

Vi bo so duoc chot TRUOC khi ky moi ve nen khong the "nhin truoc ket qua" —
diem cham tich luy qua nhieu ky cho biet giai thuat nao dang trung nhieu nhat.

```text
Du doan: power655: da chot batch #7 (1000 bo x 7 che do) sau ky 01372
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

### DOC KY: bang xep theo DO PHU, khong theo TB trung

Sau 305 ky Power (1,83 trieu ve) va 304 ky Mega (1,82 trieu ve): **khong giai thuat
nao vuot ngau nhien**. TB trung cua ca 6 che do deu bam sat ky vong ly thuyet
36/n (0,655 voi Power 6/55; 0,800 voi Mega 6/45), `beats_random = False` toan bo.

Vi vay xep hang theo TB trung la **xep hang theo nhieu**. Truoc day bang lam dung
the va no day "Theo cap" — che do TE NHAT — len hang nhat kem dau sao. Bang chung
ro nhat o Mega: "So gan" thang 100/304 ky va la che do DUY NHAT trung tron 6/6 so,
nhung do phu chi 44%. Ai theo no la theo mot chuoi may rui.

Thu **cai thien duoc** la DO PHU. Xac suat cua TUNG ve thi co dinh, nhung muc CHONG
LAN giua cac ve trong cung mot boi so thi khong: hai ve chung 5 so gan nhu luon cung
trung hoac cung truot, tuc tien mua ve thu hai bi phi. Do bang so **bo-3 khac nhau**
ma ca boi so phu duoc (moi ve co C(6,3)=20 bo-3).

Do phu do duoc voi 1000 ve:

| Che do | Power 6/55 | Mega 6/45 |
|---|---|---|
| **Phu rong** | **84,1%** | **90,8%** |
| Can doi | 68,4% | 73,1% |
| Thien so nong | 68,0% | 72,8% |
| Tranh so dong | 54,3% | 56,7% |
| Thien so gan | 42,3% | 43,8% |
| Theo cap | 20,5% | 24,1% |

Y nghia thuc te — mo phong 4.000 ky ngau nhien, Power 6/55, 1000 ve (10 trieu dong):
P(co it nhat 1 ve trung >=4 so) la **50,9%** voi Phu rong, 45,5% voi Can doi,
**17,0% voi Theo cap**. Cung so tien bo ra, chenh gan 3 lan.

**Che do `spread` ("Phu rong")** moi lan boc `SPREAD_TRIES=40` bo ung vien roi giu bo
phu duoc nhieu **bo-3 MOI** nhat so voi cac ve da chon. No **KHONG co doan so** —
xac suat tung ve y het cac che do khac. No chi giam chong lan, va vi the chi co y
nghia khi mua NHIEU ve trong cung mot ky.

Che do nay **co tinh BO rang buoc "dien hinh"** (`passes()`): rang buoc do thu hep
khong gian boc nen bop chinh do phu ma no dang toi uu, trong khi khong he nang ky
vong trung cua tung ve.

**Che do `cover` ("Phu kin so")** di xa hon mot buoc: ve sau **khong dung lai so**
cua ve truoc cho toi khi het dai 1..n, roi moi bat dau luot phu moi (so le con sot
duoc ghep vao ve dau luot sau nen khong so nao bi bo). Trong rang buoc roi nhau do
no van boc tham lam theo bo-3 moi nhu `spread`.

Ly do: `spread` toi uu so bo-3 khac nhau — dung cho boi so LON. Nhung nguoi choi
thuong mua 5-20 ve, va o co do thu quyet dinh la boi so phu duoc bao nhieu SO khac
nhau, vi xac suat ca boi so truot sach (khong trung noi 1 so) = `C(n - so da phu, 6)
/ C(n, 6)`.

| Power 6/55 | 5 ve | 10 ve |
| --- | --- | --- |
| `cover` (ve roi nhau) | phu 30 so, truot sach **0,61%** | phu 55 so, truot sach **0** |
| `spread` | phu 24 so, truot sach 2,54% | phu 39 so, truot sach 0,03% |
| `gan` | phu 18 so, truot sach 8,02% | phu 32 so, truot sach 0,35% |

Du `ceil(n/6)` ve (10 ve Power, 8 ve Mega) la phu tron dai -> **chac chan trung it
nhat 1 so**, khong con la may rui. Doi lai, o 1000 ve/ky (co ma bang xep hang do)
do phu bo-3 cua `cover` kem `spread` khoang 0,7 diem — nen trang tu chon `cover`
khi lay <= 100 bo (`COVER_MAX_SETS` trong stats_web.py) va theo bang xep hang khi
lay nhieu hon.

Cung nhu `spread`, `cover` **co tinh BO rang buoc "dien hinh"**. No KHONG lam tung
ve de trung hon — chi khong de tien ve sau mua lai thu ve truoc da co.

**Tran do phu = `min(20 x so ve, C(n,3))`, KHONG phai `20 x so ve`.** Ca tro choi chi
co C(n,3) bo-3; Mega 6/45 co C(45,3) = 14.190 < 20.000 nen 1000 ve khong the vuot
14.190. Lay 20.000 lam mau so khien MOI che do trong te di gia tao (Phu rong bi bao
64% thay vi 90,8%). Xem `coverage_cap()` trong `predict_track.py` va `coverageCap()`
trong JS — sua mot noi thi phai sua ca hai.

Cot `cov3` trong `prediction_stats` luu do phu cua tung batch. DB tao bang ban cu
duoc `ALTER TABLE` tu dong trong `init_tables()`.

**Luu y ve `Theo cap`:** tren web no chi sinh duoc ~610-670 bo KHAC NHAU trong 1000 ve
(hon 300 ve trung lap hoan toan) vi thuat toan boc tham lam top-3. Hanh vi nay duoc
giu nguyen vi no phan anh dung ban chat che do, nhung cot cua no gio hien thang
"chi N bo khac nhau" thay vi im lang.

### Chay lai lich su (backfill) — co bang xep hang ngay

Doi tung ky moi ve thi rat lau (moi tuan 3 ky). Lenh `backfill` duyet nguoc lich su:
voi moi ky, tinh ho so thong ke CHI tu cac ky TRUOC no, sinh bo so roi cham voi
chinh ky do.

```powershell
python predict_track.py backfill --periods 300 -n 1000
```

300 ky x 6 che do x 1000 bo = 1,8 trieu ve, mat ~5-7 phut moi game (truoc
2026-08-22 la 20-27 phut; da tien tinh bang trong so trong `_make_generator` va
cap nhat cong don diem cooc trong `gen_pair` — kiem chung cung seed cho ket qua
GIONG HET tung bit, nen khong phai `--redo` vi toi uu nay).
Khong ky nao nhin thay ket qua cua chinh no nen van trung thuc nhu chay that.
Idempotent: ky nao da co batch thi bo qua, chay lai khong tao chong.
Them `--seed 123` de tai lap duoc ket qua (dung khi doi thuat toan va muon so
truoc/sau).

Muon dung lai TU DAU (khi them che do moi, hoac DB cu chua co cot do phu) thi them
`--redo` — no xoa cac ky da cham roi tinh lai:

```powershell
python predict_track.py --db vietlott_data.db backfill --game power655 --periods 305 --redo
python predict_track.py --db vietlott_mega645_data.db backfill --game mega645 --periods 304 --redo
```

`--redo` chi xoa batch `status='scored'`. Batch dang `pending` duoc GIU vi ve cua no
la bang chung da chot truoc khi ky moi ve — xoa di la mat tinh "khong nhin truoc
ket qua".

**KHONG can xoa lich su draw_results de "chay lai".** `crawl.py` chi chot 1 batch
moi lan chay, nen xoa 300 ky roi cao lai chi cho ra 1 ky co diem, khong phai 300.

### Luu tru: chi giu KET QUA, khong giu tung ve

- `prediction_sets` (ve chi tiet) chi ton tai trong luc CHO cham: sinh truoc khi ky
  moi ve, giu 5.000 ve lam bang chung da chot truoc.
- Cham xong, ket qua duoc gom vao `prediction_stats` — moi che do 1 dong voi so dem
  theo muc trung `c0..c6` (bao nhieu ve trung 0,1,2,3,4,5,6 so) va `cov3` (do phu) —
  roi **xoa het ve**.
- 1 ky: 6.000 dong -> 6 dong. Moi so lieu cua bang xep hang (TB, >=3/4/5/6, tot nhat,
  phan bo, t-test) deu suy ra duoc tu c0..c6; rieng do phu phai tinh luc con ve nen
  duoc luu san vao `cov3`.

DB tao bang ban cu (luu tung ve) thu nho bang:

```powershell
python predict_track.py compact
```

Da kiem chung khong mat so lieu: 301 ky, 1.505.000 dong -> 1.505 dong, DB 71MB -> 0,5MB,
moi con so trong bang xep hang giu nguyen.

**Doi cong thuc sinh so = phai dung lai bang theo doi.** Neu sua thuat toan cua bat ky
che do nao, bang xep hang cu se tron 2 phien ban khac nhau duoi cung mot ten. Cach
dung la chay lai backfill voi `--redo` (xem tren) — no vua xoa vua dung lai ngay:

```powershell
python predict_track.py --db vietlott_data.db backfill --game power655 --periods 305 --redo
```

Neu chi muon xoa sach ma khong dung lai:

```powershell
python -c "import sqlite3;c=sqlite3.connect('vietlott_data.db');c.execute('delete from prediction_stats');c.execute('delete from prediction_sets');c.execute('delete from prediction_batches');c.commit()"
```

## Boi so goi y & che do "Tranh so dong"

O muc **Bo so goi y** tren trang, o "So bo" nhan tu do 1–5000. Tu 21 bo tro len la
che do **boi so**: bo qua rang buoc "cac bo phai khac nhau >=2 so" (O(n^2), bat kha
thi o quy mo lon), chi dam bao khong trung lap, va hien them o van ban de chep/in
toan bo danh sach.

Dong thong ke duoi o nhap hien **do phu** cua boi so vua tao (to vang khi < 50%,
xanh khi >= 80%) kem canh bao neu cac ve chong lan nhau qua nhieu. Neu dinh mua ca
boi so thi day la con so dang nhin nhat — xem muc "bang xep theo DO PHU" o tren.
Muon phu cao nhat thi chon che do **Phu rong**.

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

Rang buoc nay duoc KHOA bang bo golden vectors (`GOLDEN_SETS` / `GOLDEN_CAPS`
trong `predict_track.py`): `python predict_track.py selftest` kiem ban Python
(stats_web.py cung tu goi luc sinh trang), va trang HTML nhung dung bo do de JS
tu doi chieu khi mo — lech ben nao la ben do bao ngay (console + banner vang),
khoi phai backfill --redo oan. DOI HE SO POP_* LA PHAI TINH LAI GOLDEN_SETS.

He so theo duoi 8/6/4 la GIA DINH thoi quen VN (phat/loc/tu), khong lay tu nghien
cuu — Vietlott khong cong bo du lieu ve ban ra nen khong kiem chung duoc.

## Muc "Lich su ket qua" (cuoi trang)

Toan bo cac ky da ve, moi nhat truoc, nhung san trong HTML nen tra cuu duoc
offline. Mac dinh hien 100 ky, co nut "Xem them 100 ky" / "Hien tat ca" /
"Chep" (chep ra dang TSV, dan thang vao Excel duoc).

O **Loc** nhan nhieu tu, cach nhau bang dau cach:

- `01538` hoac `2026-07` -> khop theo ky / ngay (so sanh chuoi)
- `22 41` -> chi cac ky co **CA HAI** so 22 va 41; so khop duoc to sang trong bang
- Tron duoc: `2026 22` = cac ky nam 2026 co so 22

So 1-2 chu so duoc hieu la SO trong bo ket qua; con lai hieu la ky/ngay. Nen
`01538` (5 chu so) tim theo ky, khong phai tim so.

Trang nang them ~100KB vi nhung ~1500 ky (khoa JSON dat ngan `p/d/n/s` cho nhe).

## Cac muc da BO khoi trang

Trang chi con 5 muc: Bo so goi y · Bang xep hang che do · Giai thuat nao dang
trung nhieu nhat · Mo phong · Lich su ket qua. Da bo (con trong git history):

- Tan suat tung so, Phan bo do dai chuoi, Khoang cach (gap), Kiem dinh thong ke,
  Tong & can bang bo so, So gan & phong do, Cap so hay di cung, Bo so theo tung
  thuat toan — cung toan bo bieu do (`columnChart`) va tooltip.
- Ham Python khong con ai goi: `compute_algo_picks`, `compute_gap_stats`,
  `compute_tests`.
- Co `--minimal` (truoc dung de cat bot muc) — gio khong con muc nao de cat.

**QUAN TRONG:** payload van giu `frequency` / `positions` / `extra` du khong con
muc nao hien thi chung. `sugEngine` dung `count`/`gap` cho che do so nong/so gan,
dung min/max tung vi tri lam rang buoc, va phan Mo phong doc `extra`. Bo di thi
bo so sinh tren web se LECH voi `predict_track.py` sinh cho DB.

Tu 2026-08-22 `extra` da duoc CAT GON dung phan sugEngine/score doc: `total`,
`n`, `low_max`, `latest`, `sum`, `odd`, `low`, `consecutive`, `repeat_prev`,
`cooc`. Cac truong chi phuc vu muc hien thi da bo (decade, last_digit, overdue,
hot, pairs, exp_pair, repeat_mean...) khong con tinh nua — muon hien thi lai
thi lay ban cu trong git history.

Vi the `crawl.py` / `crawl_mega645.py` VAN phai chay `number_stats.py` sau khi
cao — cac bang `number_frequency` / `position_*` van can, chi la khong ve ra nua.

## Shortcut Desktop — bam 1 phat la cap nhat + xem

```powershell
python stats_web.py --tao-shortcut
```

Tao `Thống kê Vietlott.lnk` ra Desktop. Bam vao no se: cao ky moi (Power qua
`crawl.py`, Mega qua `crawl_mega645.py` — hai game chay SONG SONG, Power in
truc tiep con output cua Mega in tron ven ngay sau) -> sinh lai
`exports\stats.html` + `exports\stats_mega645.html` -> mo trinh duyet.
Cao partial (loi giua chung nhung da luu duoc ky moi) khong bi coi la fail.

Shortcut chi TRO toi `stats_web.py`, khong copy code — sua file la ap dung ngay.
No dung chinh interpreter dang chay luc tao shortcut (nen chay lenh tren trong
venv de co san bs4/openpyxl). Icon `vietlott_stats.ico` duoc PIL sinh ra lan dau,
khong co PIL thi shortcut van chay, chi la khong co icon rieng.

Cua so console hien ra de xem tien trinh cao, tu dong dong khi mo trinh duyet.
Neu cao loi thi dung lai cho doc thong bao roi moi dong.

Chay thang khong can shortcut:

```powershell
python stats_web.py --update              # cao roi mo trang
python stats_web.py --update --no-open    # cao roi chi tao file
python stats_web.py                       # chi sinh trang tu DB hien co
```

Luu y: `.lnk` tao bang IShellLink chu khong phai WScript.Shell — WScript luu
duong dan theo ANSI codepage nen nuot dau tieng Viet ("Thống" -> "Th?ng").

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
