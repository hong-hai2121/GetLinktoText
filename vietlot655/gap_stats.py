from __future__ import annotations

"""
Tính thống kê khoảng cách (gap) giữa các số trong mỗi kỳ Vietlott.

Mỗi kỳ gồm 6 số. Sau khi SORT tăng dần: x1 <= x2 <= ... <= x6.
- 5 khoảng cách:  g[j] = x[j+1] - x[j]   (j = 1..5)
- Tổng khoảng trải: range = x6 - x1 = g1 + g2 + g3 + g4 + g5

Các trung bình qua N kỳ:
  (a) Trung bình từng vị trí khoảng cách:  gbar_j = mean(g_j) với j = 1..5
  (b) Trung bình chung của một khoảng cách bất kỳ (gộp 5*N giá trị): gbar
  (c) Trung bình tổng khoảng trải: range_bar

Giá trị lý thuyết (máy quay công bằng), với n số tổng, k = 6 số chọn:
  E[mỗi gap]  = (n + 1) / (k + 1)
  E[range]    = (k - 1) * E[mỗi gap] = 5 * (n + 1) / (k + 1)

  Power 6/55 -> n = 55 -> E[gap] = 56/7 = 8.0,  E[range] = 40.0
  Mega  6/45 -> n = 45 -> E[gap] = 46/7 ≈ 6.571, E[range] ≈ 32.857
"""

import argparse
import csv
import sqlite3
import statistics
import sys
from pathlib import Path

from crawl import DB_PATH, EXPORT_DIR, ensure_dirs

NUM_COLUMNS = ["num1", "num2", "num3", "num4", "num5", "num6"]
K = 6  # số lượng số được chọn mỗi kỳ
NUM_GAPS = K - 1  # = 5 khoảng cách

# Tổng số quả cầu (n) theo từng loại hình -> quyết định giá trị lý thuyết.
GAME_NUMBER_RANGE = {
    "power655": 55,
    "mega645": 45,
}
DEFAULT_N = 55  # mặc định Power 6/55 nếu không xác định được


def fetch_draws(
    db_path: Path | str = DB_PATH,
    game_type: str | None = None,
    limit: int | None = None,
) -> list[list[int]]:
    """Đọc các kỳ, trả về danh sách [n1..n6] đã ép về int, sort tăng dần.

    Sắp xếp theo kỳ mới nhất trước; nếu `limit` được đặt thì chỉ lấy N kỳ gần nhất.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        query = f"SELECT {', '.join(NUM_COLUMNS)} FROM draw_results"
        params: list[object] = []
        if game_type:
            query += " WHERE game_type = ?"
            params.append(game_type)
        query += " ORDER BY draw_date DESC, draw_period DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    draws: list[list[int]] = []
    for row in rows:
        try:
            nums = sorted(int(row[col]) for col in NUM_COLUMNS)
        except (TypeError, ValueError):
            # Bỏ qua kỳ có ô trống/không phải số thay vì làm hỏng toàn bộ.
            continue
        if len(nums) == K:
            draws.append(nums)
    return draws


def gaps_of(draw: list[int]) -> list[int]:
    """5 khoảng cách g[j] = x[j+1] - x[j] của một kỳ đã sort."""
    return [draw[j + 1] - draw[j] for j in range(NUM_GAPS)]


def compute_stats(draws: list[list[int]], n: int) -> dict[str, object]:
    """Tính toàn bộ (a)(b)(c) + giá trị lý thuyết + độ lệch chuẩn."""
    if not draws:
        raise ValueError("Không có kỳ nào để tính. Kiểm tra DB / bộ lọc game_type.")

    N = len(draws)
    all_gaps: list[int] = []              # gộp 5*N giá trị -> phục vụ (b)
    per_position: list[list[int]] = [[] for _ in range(NUM_GAPS)]  # -> (a)
    ranges: list[int] = []                # -> (c)

    for draw in draws:
        g = gaps_of(draw)
        all_gaps.extend(g)
        for j in range(NUM_GAPS):
            per_position[j].append(g[j])
        ranges.append(draw[-1] - draw[0])  # x6 - x1

    # (a) trung bình + độ lệch chuẩn từng vị trí
    gbar_per_position = [statistics.fmean(pos) for pos in per_position]
    gstd_per_position = [
        statistics.pstdev(pos) if len(pos) > 1 else 0.0 for pos in per_position
    ]

    # (b) trung bình chung
    gbar = statistics.fmean(all_gaps)
    gstd = statistics.pstdev(all_gaps) if len(all_gaps) > 1 else 0.0

    # (c) trung bình tổng khoảng trải
    range_bar = statistics.fmean(ranges)
    range_std = statistics.pstdev(ranges) if len(ranges) > 1 else 0.0

    # Lý thuyết
    expected_gap = (n + 1) / (K + 1)
    expected_range = NUM_GAPS * expected_gap

    return {
        "N": N,
        "n": n,
        "gbar_per_position": gbar_per_position,
        "gstd_per_position": gstd_per_position,
        "gbar": gbar,
        "gstd": gstd,
        "range_bar": range_bar,
        "range_std": range_std,
        "range_min": min(ranges),
        "range_max": max(ranges),
        "expected_gap": expected_gap,
        "expected_range": expected_range,
    }


def format_report(stats: dict[str, object]) -> str:
    """Dựng báo cáo dạng text dễ đọc."""
    N = stats["N"]
    n = stats["n"]
    exp_gap = stats["expected_gap"]
    exp_range = stats["expected_range"]

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"  THỐNG KÊ KHOẢNG CÁCH — Vietlott {n} số  (N = {N} kỳ)")
    lines.append("=" * 60)

    lines.append("")
    lines.append("(a) Trung bình từng vị trí khoảng cách  [LT = %.3f]" % exp_gap)
    labels = ["g1 (x1→x2)", "g2 (x2→x3)", "g3 (x3→x4)",
              "g4 (x4→x5)", "g5 (x5→x6)"]
    for label, mean, std in zip(
        labels, stats["gbar_per_position"], stats["gstd_per_position"]
    ):
        diff = mean - exp_gap
        lines.append(
            f"    {label:<12}: {mean:6.3f}  (±{std:4.2f})   lệch LT {diff:+6.3f}"
        )

    lines.append("")
    lines.append("(b) Trung bình chung MỘT khoảng cách bất kỳ (gộp 5×N)")
    lines.append(
        f"    gbar = {stats['gbar']:.4f}  (±{stats['gstd']:.3f})"
        f"   | lý thuyết = {exp_gap:.4f}"
        f"   | lệch {stats['gbar'] - exp_gap:+.4f}"
    )

    lines.append("")
    lines.append("(c) Trung bình TỔNG khoảng trải (range = x6 - x1)")
    lines.append(
        f"    range_bar = {stats['range_bar']:.4f}  (±{stats['range_std']:.3f})"
        f"   | lý thuyết = {exp_range:.4f}"
        f"   | lệch {stats['range_bar'] - exp_range:+.4f}"
    )
    lines.append(
        f"    range min/max thực tế: {stats['range_min']} … {stats['range_max']}"
    )

    lines.append("")
    lines.append("-" * 60)
    # Nhận xét nhanh: máy quay có "ổn" không (lệch < 5% giá trị lý thuyết).
    rel_diff = abs(stats["gbar"] - exp_gap) / exp_gap
    if rel_diff < 0.05:
        verdict = f"✔ gbar lệch {rel_diff*100:.2f}% so với lý thuyết → máy quay ỔN."
    else:
        verdict = (
            f"⚠ gbar lệch {rel_diff*100:.2f}% so với lý thuyết "
            f"(>5%) → cần xem thêm dữ liệu."
        )
    lines.append("  " + verdict)
    lines.append("-" * 60)
    return "\n".join(lines)


def export_per_draw_csv(
    draws: list[list[int]],
    output_path: Path | str,
) -> Path:
    """Xuất chi tiết từng kỳ: 6 số đã sort + 5 gap + range."""
    ensure_dirs()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    header = (
        [f"x{i}" for i in range(1, K + 1)]
        + [f"g{j}" for j in range(1, NUM_GAPS + 1)]
        + ["range"]
    )
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for draw in draws:
            g = gaps_of(draw)
            writer.writerow(draw + g + [draw[-1] - draw[0]])
    return output


def resolve_n(args_n: int | None, game_type: str | None) -> int:
    """Ưu tiên --n người dùng đưa; nếu không thì suy từ game_type."""
    if args_n:
        return args_n
    if game_type and game_type in GAME_NUMBER_RANGE:
        return GAME_NUMBER_RANGE[game_type]
    return DEFAULT_N


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tính thống kê khoảng cách (gap) giữa các số Vietlott."
    )
    parser.add_argument("--db", default=str(DB_PATH), help="Đường dẫn file SQLite.")
    parser.add_argument(
        "--game-type",
        default="power655",
        help="Lọc theo loại hình (mặc định power655). Để trống '' = tất cả.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=None,
        help="Tổng số quả cầu n (bỏ trống = tự suy: power655→55, mega645→45).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Chỉ tính N kỳ gần nhất (bỏ trống = toàn bộ lịch sử).",
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        nargs="?",
        const=str(EXPORT_DIR / "gap_details.csv"),
        default=None,
        help="Xuất chi tiết gap từng kỳ ra CSV (mặc định exports/gap_details.csv).",
    )
    return parser


def main() -> int:
    # Console Windows mặc định cp1252 -> ép UTF-8 để in được tiếng Việt.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_arg_parser().parse_args()
    game_type = args.game_type or None  # '' -> None = không lọc

    try:
        draws = fetch_draws(args.db, game_type=game_type, limit=args.limit)
        n = resolve_n(args.n, game_type)
        stats = compute_stats(draws, n)
    except Exception as exc:
        print(f"Lỗi: {type(exc).__name__}: {exc}")
        return 1

    print(format_report(stats))

    if args.csv:
        path = export_per_draw_csv(draws, args.csv)
        print(f"\nĐã xuất chi tiết: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
