from __future__ import annotations

"""Wrapper mong: cao Mega 6/45 bang chinh engine cua crawl.py.

Truoc day file nay la ban copy ~700 dong cua crawl.py va hai ban da bat dau
lech nhau (retry, validate, finally...). crawl.py von co san
GAME_CONFIGS["mega645"] nen o day chi con viec tro dung DB + log rieng.

Giu ten file de shortcut Desktop va stats_web.run_update() khong phai doi.
Moi tham so them (vd --max-pages 5) duoc chuyen thang cho crawl.py.

LUU Y lan chay dau sau khi gop: crawl.init_db() tu migrate schema cua
vietlott_mega645_data.db tu UNIQUE(draw_period) sang
UNIQUE(game_type, draw_period) — vo hai (DB chi co mega645), du lieu giu nguyen.
"""

import sys
from pathlib import Path
from typing import Iterable

import crawl

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vietlott_mega645_data.db"
LOG_FILE = crawl.LOG_DIR / "crawler_mega645.log"
GAME_TYPE = "mega645"


def main(argv: Iterable[str] | None = None) -> int:
    # Giu log Mega tach rieng nhu truoc khi gop. Phai set TRUOC lan goi
    # get_logger() dau tien vi handler chi duoc tao 1 lan.
    crawl.LOG_FILE = LOG_FILE
    extra = list(argv) if argv is not None else sys.argv[1:]
    # Tham so nguoi dung dat SAU nen thang khi trung (argparse lay lan cuoi).
    return crawl.main(["--game", GAME_TYPE, "--db", str(DB_PATH)] + extra)


if __name__ == "__main__":
    sys.exit(main())
