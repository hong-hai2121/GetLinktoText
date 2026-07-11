from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vietlott_data.db"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "crawler.log"
EXPORT_DIR = BASE_DIR / "exports"

DEFAULT_BASE_URL = "https://vietlott.vn"
DEFAULT_PAGE_DELAY = 0.2
DEFAULT_SITE_ID = "main.frontend.vi"
AJAX_RENDER_PATH = "/ajaxpro/Vietlott.Utility.WebEnvironments,Vietlott.Utility.ashx"


@dataclass(frozen=True)
class GameConfig:
    game_type: str
    display_name: str
    default_url: str
    ajax_draw_path: str
    has_special_num: bool
    number_bands: int


GAME_CONFIGS = {
    "power655": GameConfig(
        game_type="power655",
        display_name="Power 6/55",
        default_url=(
            "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/"
            "winning-number-655"
        ),
        ajax_draw_path=(
            "/ajaxpro/Vietlott.PlugIn.WebParts.Game655CompareWebPart,"
            "Vietlott.PlugIn.WebParts.ashx"
        ),
        has_special_num=True,
        number_bands=5,
    ),
    "mega645": GameConfig(
        game_type="mega645",
        display_name="Mega 6/45",
        default_url=(
            "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/"
            "winning-number-645"
        ),
        ajax_draw_path=(
            "/ajaxpro/Vietlott.PlugIn.WebParts.Game645CompareWebPart,"
            "Vietlott.PlugIn.WebParts.ashx"
        ),
        has_special_num=False,
        number_bands=6,
    ),
}
DEFAULT_GAME_TYPE = "power655"
DEFAULT_URL = GAME_CONFIGS[DEFAULT_GAME_TYPE].default_url
DEFAULT_AJAX_DRAW_PATH = GAME_CONFIGS[DEFAULT_GAME_TYPE].ajax_draw_path


@dataclass(frozen=True)
class DrawResult:
    game_type: str
    draw_date: str
    draw_period: str
    numbers: tuple[str, str, str, str, str, str]
    special_num: str
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
    """Create the SQLite database and required tables if they do not exist."""
    ensure_dirs()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draw_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_type TEXT NOT NULL,
            draw_date TEXT NOT NULL,
            draw_period TEXT NOT NULL,
            num1 TEXT NOT NULL,
            num2 TEXT NOT NULL,
            num3 TEXT NOT NULL,
            num4 TEXT NOT NULL,
            num5 TEXT NOT NULL,
            num6 TEXT NOT NULL,
            special_num TEXT NOT NULL,
            source_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(game_type, draw_period)
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
    migrate_draw_results_unique_constraint(conn)
    return conn


def get_draw_results_unique_indexes(conn: sqlite3.Connection) -> list[list[str]]:
    unique_indexes: list[list[str]] = []
    for index in conn.execute("PRAGMA index_list('draw_results')").fetchall():
        index_name = index[1]
        is_unique = bool(index[2])
        if not is_unique:
            continue
        columns = [
            row[2]
            for row in conn.execute(f"PRAGMA index_info('{index_name}')").fetchall()
        ]
        unique_indexes.append(columns)
    return unique_indexes


def migrate_draw_results_unique_constraint(conn: sqlite3.Connection) -> None:
    """Migrate old DBs from UNIQUE(draw_period) to UNIQUE(game_type, draw_period)."""
    unique_indexes = get_draw_results_unique_indexes(conn)
    if ["game_type", "draw_period"] in unique_indexes:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            CREATE TABLE draw_results_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_type TEXT NOT NULL,
                draw_date TEXT NOT NULL,
                draw_period TEXT NOT NULL,
                num1 TEXT NOT NULL,
                num2 TEXT NOT NULL,
                num3 TEXT NOT NULL,
                num4 TEXT NOT NULL,
                num5 TEXT NOT NULL,
                num6 TEXT NOT NULL,
                special_num TEXT NOT NULL,
                source_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(game_type, draw_period)
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO draw_results_new (
                id,
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
            SELECT
                id,
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
            FROM draw_results
            ORDER BY id
            """
        )
        conn.execute("DROP TABLE draw_results")
        conn.execute("ALTER TABLE draw_results_new RENAME TO draw_results")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def get_logger() -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger("vietlott_crawler")
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
    total_found: int,
    new_records: int,
    duplicate_records: int,
    error_message: str | None = None,
) -> None:
    """Save one crawl run to SQLite and to logs/crawler.log."""
    run_time = current_timestamp()
    created_at = run_time
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
            run_time,
            status,
            total_found,
            new_records,
            duplicate_records,
            error_message,
            created_at,
        ),
    )
    conn.commit()

    message = (
        f"status={status}; total_found={total_found}; "
        f"new_records={new_records}; duplicate_records={duplicate_records}; "
        f"error={error_message or ''}"
    )
    logger = get_logger()
    if status == "success":
        logger.info(message)
    else:
        logger.error(message)


def save_file_log_only(
    status: str,
    total_found: int,
    new_records: int,
    duplicate_records: int,
    error_message: str | None,
) -> None:
    message = (
        f"status={status}; total_found={total_found}; "
        f"new_records={new_records}; duplicate_records={duplicate_records}; "
        f"error={error_message or ''}"
    )
    logger = get_logger()
    if status == "success":
        logger.info(message)
    else:
        logger.error(message)


def build_http_session():
    import requests

    session = requests.Session()
    headers = {
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
    session.headers.update(headers)
    return session


def fetch_html(url: str, timeout: int = 30, session=None) -> str:
    if session is None:
        session = build_http_session()

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def ajax_url(base_url: str, path: str) -> str:
    return urljoin(base_url, path)


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
    base_url: str = DEFAULT_BASE_URL,
    site_id: str = DEFAULT_SITE_ID,
    timeout: int = 30,
) -> dict:
    payload = {"SiteId": site_id}
    data = post_ajaxpro(
        session,
        ajax_url(base_url, AJAX_RENDER_PATH),
        "ServerSideFrontEndCreateRenderInfo",
        payload,
        timeout,
    )
    render_info = data.get("value")
    if not isinstance(render_info, dict):
        raise ValueError("Could not create Vietlott render info")
    render_info["SiteLang"] = "vi"
    return render_info


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


def extract_next_page_indices(html: str) -> list[int]:
    page_indices = {
        int(value)
        for value in re.findall(r"NextPage\(\s*(\d+)\s*\)", html)
    }
    return sorted(page_indices)


def fetch_ajax_draw_page(
    session,
    page_index: int,
    key: str,
    render_info: dict,
    game_draw_id: str,
    base_url: str = DEFAULT_BASE_URL,
    ajax_draw_path: str = DEFAULT_AJAX_DRAW_PATH,
    number_bands: int = 5,
    timeout: int = 30,
) -> str:
    array_numbers = [[""] * 18 for _ in range(number_bands)]
    payload = {
        "ORenderInfo": render_info,
        "Key": key,
        "GameDrawId": game_draw_id,
        "ArrayNumbers": array_numbers,
        "CheckMulti": False,
        "PageIndex": page_index,
    }
    data = post_ajaxpro(
        session,
        ajax_url(base_url, ajax_draw_path),
        "ServerSideDrawResult",
        payload,
        timeout,
    )
    value = data.get("value")
    if not isinstance(value, dict):
        raise ValueError(f"Invalid AjaxPro response for page {page_index}")
    if value.get("Error"):
        message = value.get("InfoMessage") or "Vietlott AjaxPro returned an error"
        raise ValueError(f"Page {page_index}: {message}")
    html = value.get("HtmlContent")
    if not isinstance(html, str):
        raise ValueError(f"Page {page_index}: missing HtmlContent")
    return html


def read_html_file(path: Path | str) -> str:
    html_path = Path(path)
    return html_path.read_text(encoding="utf-8", errors="replace")


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


def extract_period(period_text: str) -> str | None:
    period_text = clean_text(period_text)
    match = re.search(r"\d+", period_text)
    return match.group(0) if match else None


def extract_numbers(
    number_cell,
    has_special_num: bool = True,
) -> tuple[tuple[str, str, str, str, str, str], str] | None:
    numbers: list[str] = []

    for span in number_cell.find_all("span"):
        classes = span.get("class", [])
        text = clean_text(span.get_text())
        if "bong_tron" in classes and re.fullmatch(r"\d{1,2}", text):
            numbers.append(normalize_number(text))

    if has_special_num and len(numbers) >= 7:
        return (tuple(numbers[:6]), numbers[6])  # type: ignore[return-value]
    if not has_special_num and len(numbers) >= 6:
        return (tuple(numbers[:6]), "")  # type: ignore[return-value]

    text = clean_text(number_cell.get_text(" "))
    if has_special_num and "|" in text:
        main_text, special_text = text.split("|", 1)
        main_numbers = re.findall(r"\d{1,2}", main_text)
        special_numbers = re.findall(r"\d{1,2}", special_text)
        if len(main_numbers) >= 6 and special_numbers:
            main = tuple(normalize_number(n) for n in main_numbers[:6])
            special = normalize_number(special_numbers[0])
            return (main, special)  # type: ignore[return-value]

    fallback_numbers = re.findall(r"\d{1,2}", text)
    if has_special_num and len(fallback_numbers) >= 7:
        main = tuple(normalize_number(n) for n in fallback_numbers[:6])
        special = normalize_number(fallback_numbers[6])
        return (main, special)  # type: ignore[return-value]
    if not has_special_num and len(fallback_numbers) >= 6:
        main = tuple(normalize_number(n) for n in fallback_numbers[:6])
        return (main, "")  # type: ignore[return-value]

    return None


def parse_draw_rows(
    html: str,
    game_type: str = DEFAULT_GAME_TYPE,
    source_page_url: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    has_special_num: bool = True,
) -> list[DrawResult]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr")
    if not rows:
        rows = soup.find_all("tr")

    draws: list[DrawResult] = []
    page_or_base_url = source_page_url or base_url

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        draw_date = normalize_date(cells[0].get_text())
        period_link = cells[1].find("a")
        period_text = period_link.get_text() if period_link else cells[1].get_text()
        draw_period = extract_period(period_text)
        extracted_numbers = extract_numbers(cells[2], has_special_num=has_special_num)

        if not draw_period or not extracted_numbers:
            continue

        source_url = source_page_url
        if period_link and period_link.get("href"):
            source_url = urljoin(page_or_base_url, period_link["href"])

        main_numbers, special_num = extracted_numbers
        draws.append(
            DrawResult(
                game_type=game_type,
                draw_date=draw_date,
                draw_period=draw_period,
                numbers=main_numbers,
                special_num=special_num,
                source_url=source_url,
            )
        )

    return draws


def draw_exists(conn: sqlite3.Connection, game_type: str, draw_period: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM draw_results
        WHERE game_type = ? AND draw_period = ?
        LIMIT 1
        """,
        (game_type, draw_period),
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
            draw.special_num,
            draw.source_url,
            now,
            now,
        ),
    )


def save_draws(conn: sqlite3.Connection, draws: list[DrawResult]) -> CrawlSummary:
    summary = CrawlSummary(total_found=len(draws))

    for draw in draws:
        if draw_exists(conn, draw.game_type, draw.draw_period):
            summary.duplicate_records += 1
            continue

        try:
            insert_draw(conn, draw)
            summary.new_records += 1
        except sqlite3.IntegrityError:
            summary.duplicate_records += 1

    return summary


def add_summary(total: CrawlSummary, current: CrawlSummary) -> None:
    total.total_found += current.total_found
    total.new_records += current.new_records
    total.duplicate_records += current.duplicate_records
    total.pages_processed += current.pages_processed


def draw_signature(draws: list[DrawResult]) -> tuple[str, ...]:
    return tuple(draw.draw_period for draw in draws)


def save_draw_page(conn: sqlite3.Connection, draws: list[DrawResult]) -> CrawlSummary:
    try:
        summary = save_draws(conn, draws)
        summary.pages_processed = 1
        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise


def print_import_progress(
    page_index: int,
    draws: list[DrawResult],
    summary: CrawlSummary,
) -> None:
    page_number = page_index + 1
    newest = draws[0]
    oldest = draws[-1]
    message = (
        f"Da import {newest.game_type} trang {page_number} (PageIndex={page_index}): "
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


def parse_and_save(
    html: str,
    conn: sqlite3.Connection | None = None,
    game_type: str = DEFAULT_GAME_TYPE,
    source_page_url: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    has_special_num: bool = True,
) -> CrawlSummary:
    """Parse HTML with BeautifulSoup and save new draw rows to SQLite."""
    owns_connection = conn is None
    if conn is None:
        conn = init_db()

    draws = parse_draw_rows(
        html,
        game_type=game_type,
        source_page_url=source_page_url,
        base_url=base_url,
        has_special_num=has_special_num,
    )

    if not draws:
        if owns_connection:
            conn.close()
        raise ValueError("No draw rows found in HTML")

    try:
        summary = save_draws(conn, draws)
        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def parse_html_pages_and_save(
    html_pages: list[tuple[str, str | None]],
    conn: sqlite3.Connection,
    game_type: str = DEFAULT_GAME_TYPE,
    base_url: str = DEFAULT_BASE_URL,
    has_special_num: bool = True,
) -> CrawlSummary:
    """Parse multiple HTML pages and save all new draw rows to SQLite."""
    draws: list[DrawResult] = []

    for html, source_page_url in html_pages:
        draws.extend(
            parse_draw_rows(
                html,
                game_type=game_type,
                source_page_url=source_page_url,
                base_url=base_url,
                has_special_num=has_special_num,
            )
        )

    if not draws:
        raise ValueError("No draw rows found in HTML")

    try:
        summary = save_draws(conn, draws)
        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise


def page_source_url(source_page_url: str, page_index: int) -> str:
    return f"{source_page_url}#page-index={page_index}"


def format_page_url(template: str, page_index: int) -> str:
    return template.format(
        page=page_index,
        page_index=page_index,
        page_number=page_index + 1,
    )


def load_html_pages_from_args(args: argparse.Namespace) -> list[tuple[str, str | None]]:
    if args.html_file:
        return [(read_html_file(args.html_file), None)]

    url = args.url or os.environ.get("VIETLOTT_URL") or DEFAULT_URL
    max_pages = args.max_pages
    if max_pages is not None and max_pages < 1:
        max_pages = None

    session = build_http_session()
    session.headers.update({"Referer": url})

    first_html = fetch_html(url, timeout=args.timeout, session=session)
    html_pages: list[tuple[str, str | None]] = [(first_html, url)]
    if max_pages == 1:
        return html_pages

    seen_page_signatures: set[tuple[str, ...]] = {
        tuple(
            draw.draw_period
            for draw in parse_draw_rows(
                first_html,
                game_type=args.game_type,
                source_page_url=url,
                base_url=args.base_url,
                has_special_num=getattr(args, "has_special_num", True),
            )
        )
    }

    if args.page_url_template:
        page_index = 1
        while max_pages is None or page_index < max_pages:
            page_url = format_page_url(args.page_url_template, page_index)
            html = fetch_html(page_url, timeout=args.timeout, session=session)
            draws = parse_draw_rows(
                html,
                game_type=args.game_type,
                source_page_url=page_url,
                base_url=args.base_url,
                has_special_num=getattr(args, "has_special_num", True),
            )
            signature = tuple(draw.draw_period for draw in draws)
            if not signature or signature in seen_page_signatures:
                break
            seen_page_signatures.add(signature)
            html_pages.append((html, page_url))
            time.sleep(args.page_delay)
            page_index += 1
        return html_pages

    ajax_key = extract_ajax_key(first_html)
    if ajax_key is None:
        next_pages = extract_next_page_indices(first_html)
        if next_pages:
            raise ValueError(
                "Found NextPage links but could not extract Vietlott Ajax key. "
                "Use a full Vietlott page URL, or pass --page-url-template."
            )
        return html_pages

    render_info = fetch_render_info(
        session,
        base_url=args.base_url,
        site_id=args.site_id,
        timeout=args.timeout,
    )
    game_draw_id = (
        args.game_draw_id
        if args.game_draw_id is not None
        else extract_game_draw_id(first_html)
    )

    page_index = 1
    while max_pages is None or page_index < max_pages:
        html = fetch_ajax_draw_page(
            session,
            page_index=page_index,
            key=ajax_key,
            render_info=render_info,
            game_draw_id=game_draw_id,
            base_url=args.base_url,
            ajax_draw_path=getattr(args, "ajax_draw_path", DEFAULT_AJAX_DRAW_PATH),
            number_bands=getattr(args, "number_bands", 5),
            timeout=args.timeout,
        )
        source_page_url = page_source_url(url, page_index)
        draws = parse_draw_rows(
            html,
            game_type=args.game_type,
            source_page_url=source_page_url,
            base_url=args.base_url,
            has_special_num=getattr(args, "has_special_num", True),
        )
        signature = tuple(draw.draw_period for draw in draws)
        if not signature or signature in seen_page_signatures:
            break
        seen_page_signatures.add(signature)
        html_pages.append((html, source_page_url))
        time.sleep(args.page_delay)
        page_index += 1

    return html_pages


def parse_page_draws(
    html: str,
    args: argparse.Namespace,
    source_page_url: str | None,
) -> list[DrawResult]:
    return parse_draw_rows(
        html,
        game_type=args.game_type,
        source_page_url=source_page_url,
        base_url=args.base_url,
        has_special_num=args.has_special_num,
    )


def import_draw_page(
    conn: sqlite3.Connection,
    page_index: int,
    draws: list[DrawResult],
    total_summary: CrawlSummary,
) -> CrawlSummary:
    page_summary = save_draw_page(conn, draws)
    add_summary(total_summary, page_summary)
    print_import_progress(page_index, draws, page_summary)
    return page_summary


def normalize_max_pages(max_pages: int | None) -> int | None:
    if max_pages is not None and max_pages < 1:
        return None
    return max_pages


def crawl_from_args(args: argparse.Namespace, conn: sqlite3.Connection) -> CrawlSummary:
    total_summary = CrawlSummary()
    seen_page_signatures: set[tuple[str, ...]] = set()
    max_pages = normalize_max_pages(args.max_pages)

    def import_html(page_index: int, html: str, source_page_url: str | None) -> bool:
        draws = parse_page_draws(html, args, source_page_url)
        signature = draw_signature(draws)
        if not signature:
            print_crawl_stop(page_index, "khong con ky quay trong HTML tra ve")
            return False
        if signature in seen_page_signatures:
            print_crawl_stop(page_index, "server tra lai trang da import truoc do")
            return False

        seen_page_signatures.add(signature)
        page_summary = import_draw_page(conn, page_index, draws, total_summary)
        if args.stop_on_existing_page and page_summary.duplicate_records > 0:
            print_crawl_stop(
                page_index,
                "da gap ky da co trong DB, dung cap nhat",
            )
            return False
        return True

    try:
        if args.html_file:
            html = read_html_file(args.html_file)
            if not import_html(0, html, None):
                if total_summary.pages_processed:
                    return total_summary
                raise ValueError("No draw rows found in HTML")
            return total_summary

        url = args.url or os.environ.get("VIETLOTT_URL") or DEFAULT_URL
        session = build_http_session()
        session.headers.update({"Referer": url})

        first_html = fetch_html(url, timeout=args.timeout, session=session)
        if not import_html(0, first_html, url):
            if total_summary.pages_processed:
                return total_summary
            raise ValueError("No draw rows found in first page HTML")
        if max_pages == 1:
            return total_summary

        if args.page_url_template:
            page_index = 1
            while max_pages is None or page_index < max_pages:
                page_url = format_page_url(args.page_url_template, page_index)
                html = fetch_html(page_url, timeout=args.timeout, session=session)
                if not import_html(page_index, html, page_url):
                    break
                time.sleep(args.page_delay)
                page_index += 1
            return total_summary

        ajax_key = extract_ajax_key(first_html)
        if ajax_key is None:
            next_pages = extract_next_page_indices(first_html)
            if next_pages:
                raise ValueError(
                    "Found NextPage links but could not extract Vietlott Ajax key. "
                    "Use a full Vietlott page URL, or pass --page-url-template."
                )
            return total_summary

        render_info = fetch_render_info(
            session,
            base_url=args.base_url,
            site_id=args.site_id,
            timeout=args.timeout,
        )
        game_draw_id = (
            args.game_draw_id
            if args.game_draw_id is not None
            else extract_game_draw_id(first_html)
        )

        page_index = 1
        while max_pages is None or page_index < max_pages:
            html = fetch_ajax_draw_page(
                session,
                page_index=page_index,
                key=ajax_key,
                render_info=render_info,
                game_draw_id=game_draw_id,
                base_url=args.base_url,
                ajax_draw_path=args.ajax_draw_path,
                number_bands=args.number_bands,
                timeout=args.timeout,
            )
            source_page_url = page_source_url(url, page_index)
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


def selected_game_configs(args: argparse.Namespace) -> list[GameConfig]:
    if args.game == "all":
        return [GAME_CONFIGS["power655"], GAME_CONFIGS["mega645"]]
    return [GAME_CONFIGS[args.game]]


def build_game_args(args: argparse.Namespace, config: GameConfig) -> argparse.Namespace:
    values = vars(args).copy()
    values["game_type"] = config.game_type
    values["has_special_num"] = config.has_special_num
    values["ajax_draw_path"] = config.ajax_draw_path
    values["number_bands"] = config.number_bands
    if args.game == "all":
        values["url"] = config.default_url
    else:
        values["url"] = args.url or config.default_url
    return argparse.Namespace(**values)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl Vietlott lottery results into local SQLite."
    )
    parser.add_argument(
        "--game",
        choices=("power655", "mega645", "all"),
        default=DEFAULT_GAME_TYPE,
        help="Game to crawl: Power 6/55, Mega 6/45, or both.",
    )
    parser.add_argument(
        "--url",
        help=(
            "Web page URL to crawl for a single game. Defaults to the built-in "
            "Vietlott URL for --game."
        ),
    )
    parser.add_argument(
        "--html-file",
        help="Read HTML from a local file instead of fetching from the web.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL used to expand relative detail links.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=(
            "Optional maximum number of result pages to crawl from the web. "
            "If omitted or set to 0, crawl until Vietlott returns an empty "
            "or repeated page. Vietlott PageIndex is zero-based, so 5 means "
            "pages 0..4. Ignored when --html-file is used."
        ),
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=DEFAULT_PAGE_DELAY,
        help="Delay in seconds between paginated requests.",
    )
    parser.add_argument(
        "--page-url-template",
        help=(
            "Optional URL template for non-Ajax pagination. Supports "
            "{page}, {page_index}, and {page_number} placeholders."
        ),
    )
    parser.add_argument(
        "--site-id",
        default=DEFAULT_SITE_ID,
        help="Vietlott site id used by AjaxPro render info.",
    )
    parser.add_argument(
        "--game-draw-id",
        help=(
            "Optional value from drpSelectGameDraw. Defaults to the first option, "
            "which is normally all draw periods."
        ),
    )
    parser.add_argument(
        "--game-type",
        default=DEFAULT_GAME_TYPE,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
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
    return parser


def print_summary(status: str, summary: CrawlSummary, error_message: str | None) -> None:
    print(f"Trang thai: {status}")
    print(f"So trang da import: {summary.pages_processed}")
    print(f"Tim thay: {summary.total_found} ky")
    print(f"Them moi: {summary.new_records} ky")
    print(f"Trung: {summary.duplicate_records} ky")
    if error_message:
        print(f"Loi: {error_message}")


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    conn: sqlite3.Connection | None = None
    status = "failed"
    error_message: str | None = None
    summary = CrawlSummary()

    try:
        conn = init_db(Path(args.db))
        for config in selected_game_configs(args):
            game_args = build_game_args(args, config)
            print(
                f"Bat dau cao {config.display_name} ({config.game_type})",
                flush=True,
            )
            try:
                game_summary = crawl_from_args(game_args, conn)
            except PartialCrawlError as exc:
                add_summary(summary, exc.summary)
                raise PartialCrawlError(
                    f"{config.display_name}: {exc}",
                    summary,
                ) from exc
            except Exception as exc:
                if summary.pages_processed:
                    raise PartialCrawlError(
                        f"{config.display_name}: {type(exc).__name__}: {exc}",
                        summary,
                    ) from exc
                raise

            add_summary(summary, game_summary)
        status = "success"
    except PartialCrawlError as exc:
        summary = exc.summary
        error_message = str(exc)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if conn is not None:
                save_log(
                    conn,
                    status=status,
                    total_found=summary.total_found,
                    new_records=summary.new_records,
                    duplicate_records=summary.duplicate_records,
                    error_message=error_message,
                )
                # Cao xong -> tinh lai bang thong ke so cho cac game da chon.
                # Loi o day khong duoc lam hong ket qua cao.
                try:
                    from number_stats import init_stats_tables, recompute_stats

                    init_stats_tables(conn)
                    game_types = [
                        config.game_type for config in selected_game_configs(args)
                    ]
                    recompute_stats(conn=conn, game_types=game_types)
                    print(
                        "Da cap nhat bang thong ke so "
                        "(number_frequency, number_streaks).",
                        flush=True,
                    )
                except Exception as stats_exc:  # noqa: BLE001
                    print(
                        f"Canh bao: khong cap nhat duoc bang thong ke: "
                        f"{type(stats_exc).__name__}: {stats_exc}",
                        flush=True,
                    )
            else:
                save_file_log_only(
                    status=status,
                    total_found=summary.total_found,
                    new_records=summary.new_records,
                    duplicate_records=summary.duplicate_records,
                    error_message=error_message,
                )
        finally:
            if conn is not None:
                conn.close()

    print_summary(status, summary, error_message)
    return 0 if status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
