from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vietlott_mega645_data.db"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "crawler_mega645.log"
EXPORT_DIR = BASE_DIR / "exports"

GAME_TYPE = "mega645"
DEFAULT_BASE_URL = "https://vietlott.vn"
DEFAULT_URL = (
    "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/"
    "winning-number-645"
)
DEFAULT_PAGE_DELAY = 0.2
DEFAULT_SITE_ID = "main.frontend.vi"

AJAX_RENDER_PATH = "/ajaxpro/Vietlott.Utility.WebEnvironments,Vietlott.Utility.ashx"
AJAX_DRAW_PATH = (
    "/ajaxpro/Vietlott.PlugIn.WebParts.Game645CompareWebPart,"
    "Vietlott.PlugIn.WebParts.ashx"
)


@dataclass(frozen=True)
class DrawResult:
    game_type: str
    draw_date: str
    draw_period: str
    numbers: tuple[str, str, str, str, str, str]
    source_url: str | None


@dataclass
class CrawlSummary:
    total_found: int = 0
    new_records: int = 0
    duplicate_records: int = 0
    pages_processed: int = 0


class PartialCrawlError(Exception):
    def __init__(self, message: str, summary: CrawlSummary) -> None:
        super().__init__(message)
        self.summary = summary


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def current_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draw_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_type TEXT NOT NULL,
            draw_date TEXT NOT NULL,
            draw_period TEXT NOT NULL UNIQUE,
            num1 TEXT NOT NULL,
            num2 TEXT NOT NULL,
            num3 TEXT NOT NULL,
            num4 TEXT NOT NULL,
            num5 TEXT NOT NULL,
            num6 TEXT NOT NULL,
            special_num TEXT NOT NULL DEFAULT '',
            source_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_time TEXT NOT NULL,
            status TEXT NOT NULL,
            total_found INTEGER NOT NULL DEFAULT 0,
            new_records INTEGER NOT NULL DEFAULT 0,
            duplicate_records INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def get_logger() -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger("vietlott_mega645_crawler")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )
        logger.addHandler(handler)

    return logger


def save_log(
    conn: sqlite3.Connection,
    status: str,
    summary: CrawlSummary,
    error_message: str | None = None,
) -> None:
    now = current_timestamp()
    conn.execute(
        """
        INSERT INTO crawl_logs (
            run_time,
            status,
            total_found,
            new_records,
            duplicate_records,
            error_message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            status,
            summary.total_found,
            summary.new_records,
            summary.duplicate_records,
            error_message,
            now,
        ),
    )
    conn.commit()

    message = (
        f"status={status}; pages={summary.pages_processed}; "
        f"total_found={summary.total_found}; new_records={summary.new_records}; "
        f"duplicate_records={summary.duplicate_records}; error={error_message or ''}"
    )
    logger = get_logger()
    if status == "success":
        logger.info(message)
    else:
        logger.error(message)


def build_http_session():
    import requests

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
        }
    )
    return session


def fetch_html(session, url: str, timeout: int) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def post_ajaxpro(
    session,
    url: str,
    method: str,
    payload: dict,
    timeout: int,
) -> dict:
    response = session.post(
        url,
        data=json.dumps(payload, separators=(",", ":")),
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "X-AjaxPro-Method": method,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def fetch_render_info(
    session,
    base_url: str,
    site_id: str,
    timeout: int,
) -> dict:
    data = post_ajaxpro(
        session,
        urljoin(base_url, AJAX_RENDER_PATH),
        "ServerSideFrontEndCreateRenderInfo",
        {"SiteId": site_id},
        timeout,
    )
    render_info = data.get("value")
    if not isinstance(render_info, dict):
        raise ValueError("Could not create Vietlott render info")
    render_info["SiteLang"] = "vi"
    return render_info


def fetch_ajax_draw_page(
    session,
    base_url: str,
    key: str,
    render_info: dict,
    game_draw_id: str,
    page_index: int,
    timeout: int,
) -> str:
    payload = {
        "ORenderInfo": render_info,
        "Key": key,
        "GameDrawId": game_draw_id,
        "ArrayNumbers": [[""] * 18 for _ in range(6)],
        "CheckMulti": False,
        "PageIndex": page_index,
    }
    data = post_ajaxpro(
        session,
        urljoin(base_url, AJAX_DRAW_PATH),
        "ServerSideDrawResult",
        payload,
        timeout,
    )
    value = data.get("value")
    if not isinstance(value, dict):
        raise ValueError(f"Invalid AjaxPro response for PageIndex={page_index}")
    if value.get("Error"):
        message = value.get("InfoMessage") or "Vietlott AjaxPro returned an error"
        raise ValueError(f"PageIndex={page_index}: {message}")
    html = value.get("HtmlContent")
    if not isinstance(html, str):
        raise ValueError(f"PageIndex={page_index}: missing HtmlContent")
    return html


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_number(value: str) -> str:
    return value.strip().zfill(2)


def normalize_date(value: str) -> str:
    value = clean_text(value)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def extract_ajax_key(html: str) -> str | None:
    match = re.search(r"ServerSideDrawResult\(\s*RenderInfo\s*,\s*'([^']+)'", html)
    return match.group(1) if match else None


def extract_game_draw_id(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find(id="drpSelectGameDraw")
    if not select:
        return ""

    selected = select.find("option", selected=True)
    if selected is not None:
        return selected.get("value", "")

    first_option = select.find("option")
    if first_option is not None:
        return first_option.get("value", "")

    return ""


def extract_period(period_text: str) -> str | None:
    match = re.search(r"\d+", clean_text(period_text))
    return match.group(0) if match else None


def extract_numbers(number_cell) -> tuple[str, str, str, str, str, str] | None:
    numbers: list[str] = []
    for span in number_cell.find_all("span"):
        classes = span.get("class", [])
        text = clean_text(span.get_text())
        if "bong_tron" in classes and re.fullmatch(r"\d{1,2}", text):
            numbers.append(normalize_number(text))

    if len(numbers) >= 6:
        return tuple(numbers[:6])  # type: ignore[return-value]

    fallback_numbers = re.findall(r"\d{1,2}", clean_text(number_cell.get_text(" ")))
    if len(fallback_numbers) >= 6:
        return tuple(normalize_number(n) for n in fallback_numbers[:6])  # type: ignore[return-value]

    return None


def parse_draw_rows(
    html: str,
    source_page_url: str | None,
    base_url: str,
) -> list[DrawResult]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr") or soup.find_all("tr")
    draws: list[DrawResult] = []
    page_or_base_url = source_page_url or base_url

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        period_link = cells[1].find("a")
        period_text = period_link.get_text() if period_link else cells[1].get_text()
        draw_period = extract_period(period_text)
        numbers = extract_numbers(cells[2])
        if not draw_period or not numbers:
            continue

        source_url = source_page_url
        if period_link and period_link.get("href"):
            source_url = urljoin(page_or_base_url, period_link["href"])

        draws.append(
            DrawResult(
                game_type=GAME_TYPE,
                draw_date=normalize_date(cells[0].get_text()),
                draw_period=draw_period,
                numbers=numbers,
                source_url=source_url,
            )
        )

    return draws


def draw_exists(conn: sqlite3.Connection, draw_period: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM draw_results WHERE draw_period = ? LIMIT 1",
        (draw_period,),
    ).fetchone()
    return row is not None


def insert_draw(conn: sqlite3.Connection, draw: DrawResult) -> None:
    now = current_timestamp()
    conn.execute(
        """
        INSERT INTO draw_results (
            game_type,
            draw_date,
            draw_period,
            num1,
            num2,
            num3,
            num4,
            num5,
            num6,
            special_num,
            source_url,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draw.game_type,
            draw.draw_date,
            draw.draw_period,
            draw.numbers[0],
            draw.numbers[1],
            draw.numbers[2],
            draw.numbers[3],
            draw.numbers[4],
            draw.numbers[5],
            "",
            draw.source_url,
            now,
            now,
        ),
    )


def save_draws(conn: sqlite3.Connection, draws: list[DrawResult]) -> CrawlSummary:
    summary = CrawlSummary(total_found=len(draws), pages_processed=1)
    for draw in draws:
        if draw_exists(conn, draw.draw_period):
            summary.duplicate_records += 1
            continue
        try:
            insert_draw(conn, draw)
            summary.new_records += 1
        except sqlite3.IntegrityError:
            summary.duplicate_records += 1
    conn.commit()
    return summary


def add_summary(total: CrawlSummary, current: CrawlSummary) -> None:
    total.total_found += current.total_found
    total.new_records += current.new_records
    total.duplicate_records += current.duplicate_records
    total.pages_processed += current.pages_processed


def print_import_progress(
    page_index: int,
    draws: list[DrawResult],
    summary: CrawlSummary,
) -> None:
    newest = draws[0]
    oldest = draws[-1]
    message = (
        f"Da import mega645 trang {page_index + 1} (PageIndex={page_index}): "
        f"tim thay {summary.total_found} ky, "
        f"them moi {summary.new_records}, "
        f"trung {summary.duplicate_records}, "
        f"tu ky {newest.draw_period} ({newest.draw_date}) "
        f"den ky {oldest.draw_period} ({oldest.draw_date})"
    )
    print(message, flush=True)
    get_logger().info(message)


def print_crawl_stop(page_index: int, reason: str) -> None:
    message = f"Dung o PageIndex={page_index}: {reason}"
    print(message, flush=True)
    get_logger().info(message)


def crawl(args: argparse.Namespace, conn: sqlite3.Connection) -> CrawlSummary:
    total_summary = CrawlSummary()
    seen_page_signatures: set[tuple[str, ...]] = set()
    max_pages = args.max_pages if args.max_pages and args.max_pages > 0 else None

    def import_html(page_index: int, html: str, source_page_url: str | None) -> bool:
        draws = parse_draw_rows(html, source_page_url, args.base_url)
        signature = tuple(draw.draw_period for draw in draws)
        if not signature:
            print_crawl_stop(page_index, "khong con ky quay trong HTML tra ve")
            return False
        if signature in seen_page_signatures:
            print_crawl_stop(page_index, "server tra lai trang da import truoc do")
            return False

        seen_page_signatures.add(signature)
        page_summary = save_draws(conn, draws)
        add_summary(total_summary, page_summary)
        print_import_progress(page_index, draws, page_summary)
        if args.stop_on_existing_page and page_summary.duplicate_records > 0:
            print_crawl_stop(
                page_index,
                "da gap ky da co trong DB, dung cap nhat",
            )
            return False
        return True

    try:
        session = build_http_session()
        session.headers.update({"Referer": args.url})

        first_html = fetch_html(session, args.url, args.timeout)
        if not import_html(0, first_html, args.url):
            if total_summary.pages_processed:
                return total_summary
            raise ValueError("No draw rows found in first page HTML")
        if max_pages == 1:
            return total_summary

        ajax_key = extract_ajax_key(first_html)
        if not ajax_key:
            raise ValueError("Could not extract Vietlott Ajax key")

        render_info = fetch_render_info(
            session,
            base_url=args.base_url,
            site_id=args.site_id,
            timeout=args.timeout,
        )
        game_draw_id = args.game_draw_id or extract_game_draw_id(first_html)

        page_index = 1
        while max_pages is None or page_index < max_pages:
            html = fetch_ajax_draw_page(
                session,
                base_url=args.base_url,
                key=ajax_key,
                render_info=render_info,
                game_draw_id=game_draw_id,
                page_index=page_index,
                timeout=args.timeout,
            )
            source_page_url = f"{args.url}#page-index={page_index}"
            if not import_html(page_index, html, source_page_url):
                break
            time.sleep(args.page_delay)
            page_index += 1

        return total_summary
    except Exception as exc:
        if total_summary.pages_processed:
            raise PartialCrawlError(
                f"Stopped after importing {total_summary.pages_processed} pages: "
                f"{type(exc).__name__}: {exc}",
                total_summary,
            ) from exc
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl Vietlott Mega 6/45 results into a separate SQLite DB."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Mega 6/45 result URL.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page limit for testing. Omit or set 0 to crawl until the end.",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=DEFAULT_PAGE_DELAY,
        help="Delay in seconds between paginated requests.",
    )
    parser.add_argument("--site-id", default=DEFAULT_SITE_ID)
    parser.add_argument("--game-draw-id", help="Optional drpSelectGameDraw value.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--full-crawl",
        dest="stop_on_existing_page",
        action="store_false",
        default=True,
        help=(
            "Keep crawling old pages even after reaching a page where every draw "
            "already exists in the database."
        ),
    )
    parser.add_argument(
        "--predict-sets",
        type=int,
        default=1000,
        help=(
            "So bo so moi che do se chot TRUOC khi cao (backtest 5 giai thuat). "
            "Dat 0 de tat."
        ),
    )
    parser.add_argument(
        "--no-predict",
        dest="predict",
        action="store_false",
        default=True,
        help="Khong chot bo so du doan va khong cham diem khi cao.",
    )
    return parser


def print_summary(
    status: str,
    summary: CrawlSummary,
    error_message: str | None,
) -> None:
    print(f"Trang thai: {status}")
    print(f"So trang da import: {summary.pages_processed}")
    print(f"Tim thay: {summary.total_found} ky")
    print(f"Them moi: {summary.new_records} ky")
    print(f"Trung: {summary.duplicate_records} ky")
    if error_message:
        print(f"Loi: {error_message}")


def main() -> int:
    args = build_arg_parser().parse_args()
    conn: sqlite3.Connection | None = None
    status = "failed"
    error_message: str | None = None
    summary = CrawlSummary()

    try:
        conn = init_db(args.db)

        # Truoc khi cao: chot san bo so dua tren lich su HIEN CO, de bo so hoan
        # toan "mu" voi ky sap ve. Giong crawl.py cua Power 6/55.
        if args.predict and args.predict_sets > 0:
            try:
                from predict_track import auto_generate

                for message in auto_generate(
                    Path(args.db), [GAME_TYPE], args.predict_sets
                ):
                    print(f"Du doan: {message}", flush=True)
            except Exception as predict_exc:  # noqa: BLE001
                print(
                    f"Canh bao: khong chot duoc bo so du doan: "
                    f"{type(predict_exc).__name__}: {predict_exc}",
                    flush=True,
                )

        summary = crawl(args, conn)
        status = "success"
    except PartialCrawlError as exc:
        summary = exc.summary
        error_message = str(exc)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            save_log(conn, status, summary, error_message)

            # Cao xong -> tinh lai bang thong ke so. Loi o day khong duoc lam
            # hong ket qua cao.
            try:
                from number_stats import init_stats_tables, recompute_stats

                init_stats_tables(conn)
                recompute_stats(conn=conn, game_types=[GAME_TYPE])
                print(
                    "Da cap nhat bang thong ke so "
                    "(number_frequency, number_streaks, position_*).",
                    flush=True,
                )
            except Exception as stats_exc:  # noqa: BLE001
                print(
                    f"Canh bao: khong cap nhat duoc bang thong ke: "
                    f"{type(stats_exc).__name__}: {stats_exc}",
                    flush=True,
                )

            # Ky moi da nam trong DB -> cham diem cac batch dang cho.
            if args.predict:
                try:
                    from predict_track import auto_evaluate

                    result = auto_evaluate(Path(args.db))
                    if result["scored"]:
                        print(
                            f"Da cham diem {result['scored']} ky du doan "
                            f"(con {result['still_pending']} ky dang cho ket qua).",
                            flush=True,
                        )
                    else:
                        print(
                            f"Chua co ky moi de cham diem "
                            f"({result['still_pending']} ky dang cho ket qua).",
                            flush=True,
                        )
                except Exception as eval_exc:  # noqa: BLE001
                    print(
                        f"Canh bao: khong cham diem duoc du doan: "
                        f"{type(eval_exc).__name__}: {eval_exc}",
                        flush=True,
                    )

            conn.close()

    print_summary(status, summary, error_message)
    return 0 if status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
