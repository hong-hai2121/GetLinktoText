from __future__ import annotations

"""
Thống kê theo TỪNG SỐ cho dữ liệu Vietlott.

Hai thứ được tính và LƯU vào DB (bảng number_frequency, number_streaks):

1) Tần suất: mỗi số đã về bao nhiêu lần trong toàn bộ lịch sử.

2) Phân bố chuỗi về liên tiếp (đếm CHÍNH XÁC độ dài):
   Xếp các kỳ theo thứ tự thời gian (cũ -> mới). Với mỗi số, một "chuỗi" là
   số kỳ nó về liên tục không đứt. Đếm số lần mỗi độ dài chuỗi xuất hiện.

   Ví dụ số 07 qua các kỳ:  ✓✓ ✗ ✓ ✗✗ ✓✓✓ ✗
     -> các chuỗi thực tế: [dài 2] [dài 1] [dài 3]
     -> đếm: dài 1 = 1 lần, dài 2 = 1 lần, dài 3 = 1 lần

3) Phân bố theo VỊ TRÍ (position_distribution / position_summary):
   Mỗi kỳ sort tăng dần x1 <= x2 <= ... <= x6. Với từng vị trí, đếm mỗi GIÁ TRỊ
   xuất hiện bao nhiêu lần, kèm dải dao động min..max, giá trị hay gặp nhất và
   trung bình. Ví dụ x1 (số bé nhất) có thể dao động 1..17. Dữ liệu để vẽ biểu đồ.

Chỉ tính 6 số chính (num1..num6), bỏ qua số đặc biệt của Power 6/55
(có thể bật lại bằng --include-special; riêng phần vị trí LUÔN chỉ dùng 6 số chính).

Các bảng thống kê được TÍNH LẠI TOÀN BỘ mỗi lần chạy (xoá rồi ghi lại theo
từng game_type) nên luôn khớp với draw_results. crawl.py gọi hàm này tự động
sau khi cào; cũng chạy tay được: python number_stats.py
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from crawl import DB_PATH, EXPORT_DIR, current_timestamp, ensure_dirs, init_db

NUM_COLUMNS = ["num1", "num2", "num3", "num4", "num5", "num6"]
POSITIONS = len(NUM_COLUMNS)  # 6 vị trí x1..x6 sau khi sort tăng dần

# Tổng số quả cầu theo từng loại hình -> quyết định dải số 1..N cần liệt kê.
GAME_NUMBER_RANGE = {
    "power655": 55,
    "mega645": 45,
}


def init_stats_tables(conn) -> None:
    """Tạo 2 bảng thống kê nếu chưa có (không đụng bảng draw_results)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS number_frequency (
            game_type TEXT NOT NULL,
            number INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            current_streak INTEGER NOT NULL,
            max_streak INTEGER NOT NULL,
            gap_since_last INTEGER NOT NULL,
            last_period TEXT,
            last_date TEXT,
            total_draws INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (game_type, number)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS number_streaks (
            game_type TEXT NOT NULL,
            number INTEGER NOT NULL,
            streak_length INTEGER NOT NULL,
            occurrences INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (game_type, number, streak_length)
        )
        """
    )
    # Phân bố giá trị theo vị trí (x1..x6 sau khi sort tăng dần mỗi kỳ).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS position_distribution (
            game_type TEXT NOT NULL,
            position INTEGER NOT NULL,
            value INTEGER NOT NULL,
            occurrences INTEGER NOT NULL,
            total_draws INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (game_type, position, value)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS position_summary (
            game_type TEXT NOT NULL,
            position INTEGER NOT NULL,
            min_value INTEGER NOT NULL,
            max_value INTEGER NOT NULL,
            mode_value INTEGER NOT NULL,
            mean_value REAL NOT NULL,
            total_draws INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (game_type, position)
        )
        """
    )
    conn.commit()


def fetch_draws_chrono(
    conn,
    game_type: str,
    include_special: bool = False,
) -> list[tuple[str, str, set[int]]]:
    """Đọc các kỳ của một game theo thứ tự thời gian CŨ -> MỚI.

    Trả về [(draw_period, draw_date, {các số đã về}), ...].
    """
    rows = conn.execute(
        f"""
        SELECT draw_period, draw_date, {", ".join(NUM_COLUMNS)}, special_num
        FROM draw_results
        WHERE game_type = ?
        ORDER BY draw_date ASC, CAST(draw_period AS INTEGER) ASC
        """,
        (game_type,),
    ).fetchall()

    draws: list[tuple[str, str, set[int]]] = []
    for row in rows:
        nums: set[int] = set()
        for col in NUM_COLUMNS:
            try:
                nums.add(int(row[col]))
            except (TypeError, ValueError):
                continue
        if include_special:
            try:
                nums.add(int(row["special_num"]))
            except (TypeError, ValueError):
                pass
        if nums:
            draws.append((row["draw_period"], row["draw_date"], nums))
    return draws


def number_range_for(game_type: str, draws: list[tuple[str, str, set[int]]]) -> int:
    """Dải số 1..N: lấy theo loại hình, nếu lạ thì suy từ số lớn nhất từng về."""
    if game_type in GAME_NUMBER_RANGE:
        return GAME_NUMBER_RANGE[game_type]
    max_seen = 0
    for _period, _date, nums in draws:
        if nums:
            max_seen = max(max_seen, max(nums))
    return max_seen


def compute_number_stats(
    draws: list[tuple[str, str, set[int]]],
    n: int,
) -> tuple[dict[int, dict[str, object]], int]:
    """Tính tần suất + phân bố chuỗi cho từng số 1..N.

    draws đã sắp CŨ -> MỚI. Trả về (stats_per_number, total_draws).
    """
    total_draws = len(draws)

    freq = {num: 0 for num in range(1, n + 1)}
    current_run = {num: 0 for num in range(1, n + 1)}   # chuỗi đang chạy
    max_run = {num: 0 for num in range(1, n + 1)}       # chuỗi dài nhất từng có
    last_index = {num: None for num in range(1, n + 1)}  # kỳ gần nhất số về
    # streak_counts[num][do_dai] = so lan chuoi do_dai da HOÀN TẤT (bị đứt)
    streak_counts: dict[int, dict[int, int]] = {
        num: defaultdict(int) for num in range(1, n + 1)
    }

    for idx, (_period, _date, present) in enumerate(draws):
        for num in range(1, n + 1):
            if num in present:
                freq[num] += 1
                current_run[num] += 1
                if current_run[num] > max_run[num]:
                    max_run[num] = current_run[num]
                last_index[num] = idx
            elif current_run[num] > 0:
                # Chuỗi vừa bị đứt -> ghi nhận đúng độ dài của nó.
                streak_counts[num][current_run[num]] += 1
                current_run[num] = 0

    stats: dict[int, dict[str, object]] = {}
    for num in range(1, n + 1):
        active = current_run[num]  # >0 nghĩa là số vẫn đang về ở kỳ mới nhất
        distribution = dict(streak_counts[num])
        if active > 0:
            # Chuỗi đang chạy cũng tính là một lần đạt độ dài đó (tính tới giờ).
            distribution[active] = distribution.get(active, 0) + 1

        li = last_index[num]
        gap_since_last = (total_draws - 1 - li) if li is not None else total_draws
        last_period = draws[li][0] if li is not None else None
        last_date = draws[li][1] if li is not None else None

        stats[num] = {
            "total_count": freq[num],
            "current_streak": active,
            "max_streak": max_run[num],
            "gap_since_last": gap_since_last,
            "last_period": last_period,
            "last_date": last_date,
            "streaks": distribution,  # {do_dai: so_lan}
        }
    return stats, total_draws


def fetch_sorted_draws(conn, game_type: str) -> list[list[int]]:
    """Đọc các kỳ của một game, trả về [x1..x6] đã sort tăng dần (chỉ 6 số chính)."""
    rows = conn.execute(
        f"SELECT {', '.join(NUM_COLUMNS)} FROM draw_results WHERE game_type = ?",
        (game_type,),
    ).fetchall()

    draws: list[list[int]] = []
    for row in rows:
        try:
            nums = sorted(int(row[col]) for col in NUM_COLUMNS)
        except (TypeError, ValueError):
            continue
        if len(nums) == POSITIONS:
            draws.append(nums)
    return draws


def compute_position_distribution(
    draws: list[list[int]],
) -> tuple[dict[int, dict[int, int]], dict[int, dict[str, object]], int]:
    """Với mỗi vị trí x1..x6: đếm mỗi giá trị xuất hiện bao nhiêu lần + min/max/mode/mean.

    Trả về (counts[position][value] = occ, summary[position] = {...}, total_draws).
    """
    total_draws = len(draws)
    counts: dict[int, dict[int, int]] = {
        pos: defaultdict(int) for pos in range(1, POSITIONS + 1)
    }
    for draw in draws:  # draw đã sort tăng dần
        for j in range(POSITIONS):
            counts[j + 1][draw[j]] += 1

    summary: dict[int, dict[str, object]] = {}
    for pos in range(1, POSITIONS + 1):
        dist = counts[pos]
        if not dist:
            continue
        values = sorted(dist)
        min_v, max_v = values[0], values[-1]
        # Điền 0 cho các giá trị trong khoảng min..max chưa từng xuất hiện
        # -> danh sách liền mạch (vd x1: đủ 1..37 kể cả 35, 36), tiện vẽ biểu đồ.
        for value in range(min_v, max_v + 1):
            dist.setdefault(value, 0)
        # mode: giá trị hay gặp nhất; nếu hoà thì lấy giá trị nhỏ hơn.
        mode_value = max(range(min_v, max_v + 1), key=lambda v: dist[v])
        mean_value = sum(v * c for v, c in dist.items()) / total_draws
        summary[pos] = {
            "min": min_v,
            "max": max_v,
            "mode": mode_value,
            "mean": mean_value,
        }
    return counts, summary, total_draws


def recompute_game(conn, game_type: str, include_special: bool = False) -> int:
    """Tính lại và GHI ĐÈ thống kê cho một game_type. Trả về số kỳ đã dùng."""
    draws = fetch_draws_chrono(conn, game_type, include_special=include_special)
    now = current_timestamp()

    conn.execute("BEGIN")
    try:
        # Xoá dữ liệu cũ của đúng game này trước khi ghi lại.
        conn.execute("DELETE FROM number_frequency WHERE game_type = ?", (game_type,))
        conn.execute("DELETE FROM number_streaks WHERE game_type = ?", (game_type,))
        conn.execute(
            "DELETE FROM position_distribution WHERE game_type = ?", (game_type,)
        )
        conn.execute("DELETE FROM position_summary WHERE game_type = ?", (game_type,))

        # Phân bố theo vị trí x1..x6 (luôn chỉ dùng 6 số chính, đã sort).
        sorted_draws = fetch_sorted_draws(conn, game_type)
        if sorted_draws:
            pos_counts, pos_summary, pos_total = compute_position_distribution(
                sorted_draws
            )
            for position in range(1, POSITIONS + 1):
                for value, occ in sorted(pos_counts[position].items()):
                    conn.execute(
                        """
                        INSERT INTO position_distribution (
                            game_type, position, value, occurrences,
                            total_draws, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (game_type, position, value, occ, pos_total, now),
                    )
                s = pos_summary.get(position)
                if s is not None:
                    conn.execute(
                        """
                        INSERT INTO position_summary (
                            game_type, position, min_value, max_value,
                            mode_value, mean_value, total_draws, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            game_type,
                            position,
                            s["min"],
                            s["max"],
                            s["mode"],
                            s["mean"],
                            pos_total,
                            now,
                        ),
                    )

        if draws:
            n = number_range_for(game_type, draws)
            stats, total_draws = compute_number_stats(draws, n)
            for num in range(1, n + 1):
                s = stats[num]
                conn.execute(
                    """
                    INSERT INTO number_frequency (
                        game_type, number, total_count, current_streak,
                        max_streak, gap_since_last, last_period, last_date,
                        total_draws, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_type,
                        num,
                        s["total_count"],
                        s["current_streak"],
                        s["max_streak"],
                        s["gap_since_last"],
                        s["last_period"],
                        s["last_date"],
                        total_draws,
                        now,
                    ),
                )
                for length, occ in sorted(s["streaks"].items()):
                    conn.execute(
                        """
                        INSERT INTO number_streaks (
                            game_type, number, streak_length, occurrences, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (game_type, num, length, occ, now),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return len(draws)


def distinct_game_types(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT game_type FROM draw_results ORDER BY game_type"
    ).fetchall()
    return [row[0] for row in rows]


def recompute_stats(
    conn=None,
    game_types: list[str] | None = None,
    db_path: Path | str = DB_PATH,
    include_special: bool = False,
) -> dict[str, int]:
    """Tính lại thống kê cho các game_type (mặc định: tất cả game có trong DB).

    Nếu không truyền conn thì tự mở/đóng DB. Trả về {game_type: số kỳ}.
    """
    owns_conn = conn is None
    if conn is None:
        conn = init_db(db_path)

    init_stats_tables(conn)
    if game_types is None:
        game_types = distinct_game_types(conn)

    result: dict[str, int] = {}
    try:
        for game_type in game_types:
            result[game_type] = recompute_game(
                conn, game_type, include_special=include_special
            )
    finally:
        if owns_conn:
            conn.close()
    return result


# --------------------------------------------------------------------------- #
# Báo cáo & xuất file (tuỳ chọn)
# --------------------------------------------------------------------------- #

def format_report(conn, game_type: str) -> str:
    freq_rows = conn.execute(
        """
        SELECT number, total_count, current_streak, max_streak,
               gap_since_last, last_period, total_draws
        FROM number_frequency
        WHERE game_type = ?
        ORDER BY total_count DESC, number ASC
        """,
        (game_type,),
    ).fetchall()

    if not freq_rows:
        return f"[{game_type}] Chưa có dữ liệu thống kê."

    total_draws = freq_rows[0]["total_draws"]
    lines: list[str] = []
    lines.append("=" * 66)
    lines.append(f"  THỐNG KÊ SỐ — {game_type}  (tổng {total_draws} kỳ)")
    lines.append("=" * 66)

    lines.append("")
    lines.append("Top 15 số về nhiều nhất:")
    lines.append(f"  {'Số':>3} | {'Về':>5} | {'streak now':>10} | "
                 f"{'dài nhất':>8} | {'chưa về':>7}")
    for row in freq_rows[:15]:
        lines.append(
            f"  {row['number']:>3} | {row['total_count']:>5} | "
            f"{row['current_streak']:>10} | {row['max_streak']:>8} | "
            f"{row['gap_since_last']:>7}"
        )

    # Phân bố độ dài chuỗi (gộp tất cả số).
    streak_rows = conn.execute(
        """
        SELECT streak_length, SUM(occurrences) AS total
        FROM number_streaks
        WHERE game_type = ?
        GROUP BY streak_length
        ORDER BY streak_length ASC
        """,
        (game_type,),
    ).fetchall()

    lines.append("")
    lines.append("Phân bố độ dài chuỗi về liên tiếp (gộp tất cả số):")
    for row in streak_rows:
        lines.append(
            f"  liên tiếp {row['streak_length']:>2} kỳ  ->  {row['total']:>6} lần"
        )

    # Dải dao động theo vị trí x1..x6.
    pos_rows = conn.execute(
        """
        SELECT position, min_value, max_value, mode_value, mean_value
        FROM position_summary
        WHERE game_type = ?
        ORDER BY position ASC
        """,
        (game_type,),
    ).fetchall()

    if pos_rows:
        lines.append("")
        lines.append("Dải dao động theo vị trí (mỗi kỳ sort tăng dần x1..x6):")
        pos_names = {
            1: "x1 (nhỏ nhất)",
            POSITIONS: f"x{POSITIONS} (lớn nhất)",
        }
        for row in pos_rows:
            pos = row["position"]
            name = pos_names.get(pos, f"x{pos}")
            lines.append(
                f"  {name:<14}: dao động {row['min_value']:>2}..{row['max_value']:<2}"
                f"  | hay gặp = {row['mode_value']:>2}"
                f"  | TB = {row['mean_value']:.2f}"
            )

    return "\n".join(lines)


def format_position_detail(conn, game_type: str) -> str:
    """In đầy đủ: mỗi vị trí x1..x6, từng giá trị xuất hiện mấy lần."""
    rows = conn.execute(
        """
        SELECT position, value, occurrences
        FROM position_distribution
        WHERE game_type = ?
        ORDER BY position ASC, value ASC
        """,
        (game_type,),
    ).fetchall()
    if not rows:
        return f"[{game_type}] Chưa có dữ liệu phân bố vị trí."

    by_pos: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row in rows:
        by_pos[row["position"]].append((row["value"], row["occurrences"]))

    lines: list[str] = []
    lines.append("=" * 66)
    lines.append(f"  CHI TIẾT PHÂN BỐ THEO VỊ TRÍ — {game_type}")
    lines.append("  (mỗi kỳ sort tăng dần x1..x6; giá trị : số lần là xN)")
    lines.append("=" * 66)
    for position in sorted(by_pos):
        pairs = by_pos[position]
        total = sum(occ for _v, occ in pairs)
        lines.append("")
        lines.append(f"x{position}  (dao động {pairs[0][0]}..{pairs[-1][0]}, tổng {total} kỳ):")
        # In gọn nhiều cột trên một dòng.
        cells = [f"{value:>2}:{occ:<4}" for value, occ in pairs]
        for i in range(0, len(cells), 6):
            lines.append("   " + " ".join(cells[i:i + 6]))
    return "\n".join(lines)


def export_game_csv(conn, game_type: str, export_dir: Path) -> list[Path]:
    ensure_dirs()
    export_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    freq_path = export_dir / f"number_frequency_{game_type}.csv"
    freq_cols = [
        "number", "total_count", "current_streak", "max_streak",
        "gap_since_last", "last_period", "last_date", "total_draws",
    ]
    freq_rows = conn.execute(
        f"SELECT {', '.join(freq_cols)} FROM number_frequency "
        "WHERE game_type = ? ORDER BY number ASC",
        (game_type,),
    ).fetchall()
    with freq_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(freq_cols)
        for row in freq_rows:
            writer.writerow([row[col] for col in freq_cols])
    outputs.append(freq_path)

    streak_path = export_dir / f"number_streaks_{game_type}.csv"
    streak_rows = conn.execute(
        "SELECT number, streak_length, occurrences FROM number_streaks "
        "WHERE game_type = ? ORDER BY number ASC, streak_length ASC",
        (game_type,),
    ).fetchall()
    with streak_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["number", "streak_length", "occurrences"])
        for row in streak_rows:
            writer.writerow([row["number"], row["streak_length"], row["occurrences"]])
    outputs.append(streak_path)

    # Phân bố giá trị theo vị trí (long-format: position, value, occurrences).
    pos_path = export_dir / f"position_distribution_{game_type}.csv"
    pos_rows = conn.execute(
        "SELECT position, value, occurrences FROM position_distribution "
        "WHERE game_type = ? ORDER BY position ASC, value ASC",
        (game_type,),
    ).fetchall()
    with pos_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["position", "value", "occurrences"])
        for row in pos_rows:
            writer.writerow([row["position"], row["value"], row["occurrences"]])
    outputs.append(pos_path)

    summary_path = export_dir / f"position_summary_{game_type}.csv"
    summary_cols = ["position", "min_value", "max_value", "mode_value",
                    "mean_value", "total_draws"]
    summary_rows = conn.execute(
        f"SELECT {', '.join(summary_cols)} FROM position_summary "
        "WHERE game_type = ? ORDER BY position ASC",
        (game_type,),
    ).fetchall()
    with summary_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(summary_cols)
        for row in summary_rows:
            writer.writerow([row[col] for col in summary_cols])
    outputs.append(summary_path)

    return outputs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Thống kê tần suất & chuỗi về liên tiếp của từng số Vietlott."
    )
    parser.add_argument("--db", default=str(DB_PATH), help="Đường dẫn file SQLite.")
    parser.add_argument(
        "--game",
        default="all",
        help="power655, mega645, all, hoặc để tự lấy các game có trong DB.",
    )
    parser.add_argument(
        "--include-special",
        action="store_true",
        help="Tính cả số đặc biệt (Power 6/55) vào tần suất/chuỗi.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Xuất bảng thống kê ra CSV trong thư mục exports.",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="In đầy đủ số lần xuất hiện của TỪNG giá trị theo từng vị trí x1..x6.",
    )
    return parser


def main() -> int:
    # Console Windows mặc định cp1252 -> ép UTF-8 để in tiếng Việt.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_arg_parser().parse_args()

    if args.game in ("all", ""):
        game_types: list[str] | None = None
    else:
        game_types = [args.game]

    conn = init_db(Path(args.db))
    try:
        init_stats_tables(conn)
        if game_types is None:
            game_types = distinct_game_types(conn)

        if not game_types:
            print("Không có dữ liệu trong draw_results.")
            return 1

        for game_type in game_types:
            count = recompute_game(
                conn, game_type, include_special=args.include_special
            )
            if count == 0:
                print(f"[{game_type}] 0 kỳ, bỏ qua.")
                continue
            print(format_report(conn, game_type))
            print("")
            if args.detail:
                print(format_position_detail(conn, game_type))
                print("")
            if args.csv:
                for path in export_game_csv(conn, game_type, EXPORT_DIR):
                    print(f"Đã xuất: {path}")
                print("")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
