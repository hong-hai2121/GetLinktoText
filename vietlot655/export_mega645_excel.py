from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vietlott_mega645_data.db"
EXPORT_DIR = BASE_DIR / "exports"
DEFAULT_XLSX_PATH = EXPORT_DIR / "vietlott_mega645.xlsx"
DEFAULT_CSV_PATH = EXPORT_DIR / "vietlott_mega645.csv"

EXPORT_COLUMNS = [
    "id",
    "game_type",
    "draw_date",
    "draw_period",
    "num1",
    "num2",
    "num3",
    "num4",
    "num5",
    "num6",
    "special_num",
    "source_url",
    "created_at",
    "updated_at",
]


def fetch_rows(db_path: Path | str = DB_PATH) -> list[dict[str, object]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT {", ".join(EXPORT_COLUMNS)}
            FROM draw_results
            ORDER BY draw_date DESC, draw_period DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def export_csv(
    db_path: Path | str = DB_PATH,
    output_path: Path | str = DEFAULT_CSV_PATH,
) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = fetch_rows(db_path)

    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return output


def export_excel(
    db_path: Path | str = DB_PATH,
    output_path: Path | str = DEFAULT_XLSX_PATH,
) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = fetch_rows(db_path)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError as exc:
        raise RuntimeError(
            "Missing openpyxl. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "mega645"
    sheet.append(EXPORT_COLUMNS)

    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append([row[column] for column in EXPORT_COLUMNS])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column_cells in sheet.columns:
        column_letter = column_cells[0].column_letter
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 60)

    workbook.save(output)
    return output


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Mega 6/45 data.")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path.")
    parser.add_argument(
        "--format",
        choices=("xlsx", "csv", "both"),
        default="xlsx",
    )
    parser.add_argument("--xlsx-output", default=str(DEFAULT_XLSX_PATH))
    parser.add_argument("--csv-output", default=str(DEFAULT_CSV_PATH))
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    exported: list[Path] = []

    try:
        if args.format in ("xlsx", "both"):
            exported.append(export_excel(args.db, args.xlsx_output))
        if args.format in ("csv", "both"):
            exported.append(export_csv(args.db, args.csv_output))
    except Exception as exc:
        print(f"Export failed: {type(exc).__name__}: {exc}")
        return 1

    for path in exported:
        print(f"Exported: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
