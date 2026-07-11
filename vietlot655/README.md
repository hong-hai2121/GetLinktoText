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
