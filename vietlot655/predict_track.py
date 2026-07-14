from __future__ import annotations

"""
Backtest thực cho 5 chế độ "Bộ số gợi ý": mỗi chế độ tạo 1000 vé (bộ 6 số),
LƯU lại kèm kỳ gốc, rồi khi kỳ tiếp theo có kết quả thật (crawl về DB) sẽ TỰ CHẤM
xem chế độ nào trùng nhiều số hơn — tích luỹ qua nhiều kỳ thành bảng xếp hạng.

Quy trình:
  1. Trước mỗi kỳ:   python predict_track.py generate            (lưu 5×1000 bộ vào DB)
  2. Sau khi có KQ:  python predict_track.py evaluate            (tự chấm các kỳ đang chờ)
  3. Xem bảng:       python predict_track.py board               (in bảng xếp hạng)
     (stats_web.py cũng tự gọi evaluate + hiện bảng ngay trên trang)

LƯU Ý TRUNG THỰC: xổ số độc lập từng kỳ. Không chế độ nào tăng xác suất trúng;
kỳ vọng lý thuyết ~36/n số trùng mỗi vé (≈0,65 với Power 6/55). Chênh lệch giữa
các chế độ hầu như chỉ là nhiễu — bảng này để KIỂM CHỨNG điều đó bằng dữ liệu thật.
"""

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime
from itertools import combinations
from math import comb
from pathlib import Path

import gap_stats
from crawl import DB_PATH, ensure_dirs

# 5 chế độ đúng như dropdown "Bộ số gợi ý" trong stats_web.py.
METHODS = ["balanced", "hot", "gan", "pairs", "payout"]
MODE_NAME = {
    "balanced": "Cân đối",
    "hot": "Thiên số nóng",
    "gan": "Thiên số gan",
    "pairs": "Theo cặp hay đi cùng",
    "payout": "Tránh số đông",
}
DEFAULT_SETS = 1000


# --------------------------------------------------------------------------- #
# DB
# --------------------------------------------------------------------------- #
def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_type TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            after_period TEXT,
            after_date TEXT,
            n_sets INTEGER NOT NULL,
            target_period TEXT,
            target_date TEXT,
            target_numbers TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            numbers TEXT NOT NULL,
            matched INTEGER
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_predsets_batch ON prediction_sets(batch_id)"
    )
    conn.commit()


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_tables(conn)
    return conn


def _latest_draw(conn: sqlite3.Connection, game_type: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT draw_period, draw_date, num1, num2, num3, num4, num5, num6
        FROM draw_results
        WHERE game_type = ?
        ORDER BY draw_date DESC, draw_period DESC
        LIMIT 1
        """,
        (game_type,),
    ).fetchone()


def _next_draw_after(
    conn: sqlite3.Connection, game_type: str, after_date: str, after_period: str
) -> sqlite3.Row | None:
    """Kỳ thật đầu tiên xảy ra SAU thời điểm tạo dự đoán (mục tiêu để chấm)."""
    return conn.execute(
        """
        SELECT draw_period, draw_date, num1, num2, num3, num4, num5, num6
        FROM draw_results
        WHERE game_type = ?
          AND (draw_date > ? OR (draw_date = ? AND draw_period > ?))
        ORDER BY draw_date ASC, draw_period ASC
        LIMIT 1
        """,
        (game_type, after_date, after_date, after_period),
    ).fetchone()


def _row_numbers(row: sqlite3.Row) -> list[int]:
    return sorted(int(row[c]) for c in ("num1", "num2", "num3", "num4", "num5", "num6"))


# --------------------------------------------------------------------------- #
# Hồ sơ thống kê (tự tính từ lịch sử — độc lập với stats_web để tránh vòng import)
# --------------------------------------------------------------------------- #
def compute_profile(draws: list[list[int]], n: int) -> dict:
    total = len(draws)
    count = {x: 0 for x in range(1, n + 1)}
    gap = {x: total for x in range(1, n + 1)}
    seen: set[int] = set()
    cooc = [[0] * n for _ in range(n)]
    for i, d in enumerate(draws):
        for x in d:
            count[x] += 1
            if x not in seen:
                gap[x] = i
                seen.add(x)
        for a, b in combinations(d, 2):
            cooc[a - 1][b - 1] += 1
            cooc[b - 1][a - 1] += 1

    pos_min = [min(d[i] for d in draws) for i in range(6)]
    pos_max = [max(d[i] for d in draws) for i in range(6)]

    sums = sorted(sum(d) for d in draws)

    def pct(p: float) -> int:
        idx = min(len(sums) - 1, max(0, round(p * (len(sums) - 1))))
        return sums[idx]

    return {
        "n": n,
        "total": total,
        "count": count,
        "gap": gap,
        "cooc": cooc,
        "pos_min": pos_min,
        "pos_max": pos_max,
        "p10": pct(0.10),
        "p90": pct(0.90),
        "low_max": n // 2,
        "latest_set": set(draws[0]),
    }


# --------------------------------------------------------------------------- #
# Sinh bộ số theo từng chế độ (port từ sugEngine trong stats_web.py)
# --------------------------------------------------------------------------- #
def _make_generator(method: str, prof: dict):
    n = prof["n"]
    count, gap, cooc = prof["count"], prof["gap"], prof["cooc"]

    def weight(x: int) -> float:
        if method == "hot":
            return count[x] + 1
        if method == "gan":
            return gap[x] + 1
        if method == "payout":
            return 3 if x > 31 else 1
        return 1  # balanced (và seed cho pairs)

    def sample_weighted() -> list[int]:
        used = [False] * (n + 1)
        chosen: list[int] = []
        for _ in range(6):
            tot = 0.0
            for x in range(1, n + 1):
                if not used[x]:
                    tot += weight(x)
            r = random.random() * tot
            acc, pick = 0.0, 1
            for x in range(1, n + 1):
                if used[x]:
                    continue
                acc += weight(x)
                if acc >= r:
                    pick = x
                    break
            used[pick] = True
            chosen.append(pick)
        chosen.sort()
        return chosen

    def gen_pair() -> list[int]:
        used = [False] * (n + 1)
        tot = sum(count[x] for x in range(1, n + 1))
        if tot <= 0:
            seed = random.randint(1, n)
        else:
            r = random.random() * tot
            acc, seed = 0, 1
            for x in range(1, n + 1):
                acc += count[x]
                if acc >= r:
                    seed = x
                    break
        s = [seed]
        used[seed] = True
        while len(s) < 6:
            cand = []
            for x in range(1, n + 1):
                if used[x]:
                    continue
                v = 0
                for y in s:
                    v += cooc[x - 1][y - 1]
                cand.append((v, x))
            if not cand:
                break
            cand.sort(reverse=True)
            _, pk = cand[random.randrange(min(3, len(cand)))]
            s.append(pk)
            used[pk] = True
        s.sort()
        return s

    return gen_pair if method == "pairs" else sample_weighted


def passes(s: list[int], prof: dict) -> bool:
    ssum = sum(s)
    if ssum < prof["p10"] or ssum > prof["p90"]:
        return False
    odd = sum(1 for x in s if x % 2)
    low = sum(1 for x in s if x <= prof["low_max"])
    if odd < 2 or odd > 4 or low < 2 or low > 4:
        return False
    if sum(1 for i in range(5) if s[i + 1] == s[i] + 1) > 1:
        return False
    if sum(1 for x in s if x in prof["latest_set"]) > 2:
        return False
    if len({(x - 1) // 10 for x in s}) < 3:
        return False
    for i in range(6):
        if s[i] < prof["pos_min"][i] or s[i] > prof["pos_max"][i]:
            return False
    return True


def generate_sets(method: str, prof: dict, k: int) -> list[list[int]]:
    """k bộ theo chế độ: ưu tiên qua ràng buộc 'điển hình' + không trùng, nới dần nếu bí."""
    gen = _make_generator(method, prof)
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    budget = k * 200

    tries = 0
    while len(out) < k and tries < budget:  # pha 1: qua ràng buộc + không trùng
        tries += 1
        s = gen()
        if len(s) != 6 or not passes(s, prof):
            continue
        key = tuple(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    while len(out) < k and tries < budget * 2:  # pha 2: qua ràng buộc, cho trùng
        tries += 1
        s = gen()
        if len(s) == 6 and passes(s, prof):
            out.append(s)
    while len(out) < k and tries < budget * 3:  # pha 3: nới ràng buộc để đủ số lượng
        tries += 1
        s = gen()
        if len(s) == 6:
            out.append(s)
    return out[:k]


# --------------------------------------------------------------------------- #
# generate / evaluate
# --------------------------------------------------------------------------- #
def generate(
    db_path: Path | str,
    game_type: str,
    n_sets: int = DEFAULT_SETS,
    force: bool = False,
) -> dict:
    ensure_dirs()
    conn = _connect(db_path)
    try:
        draws = gap_stats.fetch_draws(db_path, game_type=game_type)
        if len(draws) < 10:
            return {"ok": False, "msg": f"Chưa đủ dữ liệu ({len(draws)} kỳ) để tạo dự đoán."}
        n = gap_stats.resolve_n(None, game_type)

        latest = _latest_draw(conn, game_type)
        after_period = latest["draw_period"] if latest else ""
        after_date = latest["draw_date"] if latest else ""

        existing = conn.execute(
            "SELECT id, status FROM prediction_batches WHERE game_type=? AND after_period=?",
            (game_type, after_period),
        ).fetchone()
        if existing and not force:
            return {
                "ok": False,
                "msg": (
                    f"Đã có dự đoán cho kỳ sau {after_period} (batch #{existing['id']}, "
                    f"{existing['status']}). Dùng --force nếu muốn tạo thêm."
                ),
            }

        prof = compute_profile(draws, n)
        cur = conn.execute(
            """
            INSERT INTO prediction_batches
                (game_type, generated_at, after_period, after_date, n_sets, status)
            VALUES (?,?,?,?,?, 'pending')
            """,
            (game_type, datetime.now().isoformat(timespec="seconds"),
             after_period, after_date, n_sets),
        )
        batch_id = cur.lastrowid

        rows = []
        for method in METHODS:
            for s in generate_sets(method, prof, n_sets):
                rows.append((batch_id, method, ",".join(map(str, s))))
        conn.executemany(
            "INSERT INTO prediction_sets (batch_id, method, numbers) VALUES (?,?,?)",
            rows,
        )
        conn.commit()
        return {
            "ok": True,
            "batch_id": batch_id,
            "game_type": game_type,
            "after_period": after_period,
            "n_sets": n_sets,
            "total_rows": len(rows),
        }
    finally:
        conn.close()


def evaluate(db_path: Path | str, game_type: str | None = None) -> dict:
    """Chấm mọi batch đang 'pending' đã có kỳ kết quả thật kế tiếp. Idempotent."""
    conn = _connect(db_path)
    scored, still_pending = 0, 0
    try:
        q = "SELECT * FROM prediction_batches WHERE status='pending'"
        params: list[object] = []
        if game_type:
            q += " AND game_type=?"
            params.append(game_type)
        batches = conn.execute(q, params).fetchall()

        for b in batches:
            target = _next_draw_after(
                conn, b["game_type"], b["after_date"] or "", b["after_period"] or ""
            )
            if target is None:
                still_pending += 1
                continue
            win = set(_row_numbers(target))
            sets = conn.execute(
                "SELECT id, numbers FROM prediction_sets WHERE batch_id=?",
                (b["id"],),
            ).fetchall()
            updates = []
            for r in sets:
                nums = [int(x) for x in r["numbers"].split(",")]
                updates.append((sum(1 for x in nums if x in win), r["id"]))
            conn.executemany(
                "UPDATE prediction_sets SET matched=? WHERE id=?", updates
            )
            conn.execute(
                """
                UPDATE prediction_batches
                SET status='scored', target_period=?, target_date=?, target_numbers=?
                WHERE id=?
                """,
                (target["draw_period"], target["draw_date"],
                 json.dumps(sorted(win)), b["id"]),
            )
            scored += 1
        conn.commit()
        return {"scored": scored, "still_pending": still_pending}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Bảng xếp hạng
# --------------------------------------------------------------------------- #
def _baseline(n: int) -> dict:
    """Kỳ vọng lý thuyết cho 1 vé ngẫu nhiên (hypergeometric)."""
    tot = comb(n, 6)
    prob = {m: (comb(6, m) * comb(n - 6, 6 - m) / tot) for m in range(7)}
    avg = sum(m * prob[m] for m in range(7))
    return {
        "avg": round(avg, 3),
        "hit3_rate": round(sum(prob[m] for m in range(3, 7)) * 100, 3),
    }


def load_scoreboard(db_path: Path | str, game_type: str) -> dict | None:
    conn = _connect(db_path)
    try:
        n = gap_stats.resolve_n(None, game_type)
        pending = conn.execute(
            "SELECT COUNT(*) FROM prediction_batches WHERE game_type=? AND status='pending'",
            (game_type,),
        ).fetchone()[0]
        scored_batches = conn.execute(
            "SELECT COUNT(*) FROM prediction_batches WHERE game_type=? AND status='scored'",
            (game_type,),
        ).fetchone()[0]

        agg = {
            r["method"]: r
            for r in conn.execute(
                """
                SELECT ps.method AS method,
                       COUNT(*) AS sets,
                       AVG(ps.matched) AS avg,
                       SUM(ps.matched>=3) AS hit3,
                       SUM(ps.matched>=4) AS hit4,
                       SUM(ps.matched>=5) AS hit5,
                       SUM(ps.matched>=6) AS hit6,
                       MAX(ps.matched) AS best
                FROM prediction_sets ps
                JOIN prediction_batches b ON b.id = ps.batch_id
                WHERE b.game_type=? AND b.status='scored'
                GROUP BY ps.method
                """,
                (game_type,),
            )
        }

        methods = []
        for key in METHODS:
            r = agg.get(key)
            if not r or not r["sets"]:
                methods.append({"key": key, "name": MODE_NAME[key], "sets": 0})
                continue
            sets = r["sets"]
            methods.append({
                "key": key,
                "name": MODE_NAME[key],
                "sets": sets,
                "avg": round(r["avg"], 3),
                "hit3": r["hit3"], "hit4": r["hit4"],
                "hit5": r["hit5"], "hit6": r["hit6"],
                "hit3_rate": round(r["hit3"] / sets * 100, 2),
                "best": r["best"],
            })
        # xếp hạng: chế độ có dữ liệu, TB trùng cao lên trước
        methods.sort(key=lambda m: (m["sets"] == 0, -(m.get("avg") or 0)))

        recent = []
        for b in conn.execute(
            """
            SELECT id, target_period, target_date, target_numbers
            FROM prediction_batches
            WHERE game_type=? AND status='scored'
            ORDER BY target_date DESC, id DESC LIMIT 8
            """,
            (game_type,),
        ):
            per = {
                row["method"]: round(row["avg"], 3)
                for row in conn.execute(
                    "SELECT method, AVG(matched) AS avg FROM prediction_sets "
                    "WHERE batch_id=? GROUP BY method",
                    (b["id"],),
                )
            }
            recent.append({
                "period": b["target_period"],
                "date": b["target_date"],
                "result": json.loads(b["target_numbers"]) if b["target_numbers"] else [],
                "per_method": per,
            })

        return {
            "methods": methods,
            "baseline": _baseline(n),
            "pending": pending,
            "scored_batches": scored_batches,
            "recent": recent,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_board(db_path: Path | str, game_type: str) -> None:
    sb = load_scoreboard(db_path, game_type)
    if not sb:
        print("Không đọc được bảng xếp hạng.")
        return
    print(f"\n== Bảng xếp hạng chế độ · {game_type} ==")
    print(f"Đã chấm {sb['scored_batches']} kỳ · đang chờ {sb['pending']} kỳ")
    print(f"Ngẫu nhiên lý thuyết: TB {sb['baseline']['avg']} số trùng/vé · "
          f"≥3 số {sb['baseline']['hit3_rate']}%\n")
    print(f"{'Chế độ':<20}{'Vé':>8}{'TB':>8}{'≥3':>7}{'≥4':>6}{'≥5':>5}{'6':>4}{'Tốt':>5}")
    print("-" * 63)
    for m in sb["methods"]:
        if not m.get("sets"):
            print(f"{m['name']:<20}{'—':>8}{'(chưa có dữ liệu)':>40}")
            continue
        print(f"{m['name']:<20}{m['sets']:>8}{m['avg']:>8.3f}"
              f"{m['hit3']:>7}{m['hit4']:>6}{m['hit5']:>5}{m['hit6']:>4}{m['best']:>5}")
    print()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backtest 5 chế độ gợi ý số Vietlott (tạo/chấm/xếp hạng)."
    )
    p.add_argument("--db", default=str(DB_PATH), help="Đường dẫn SQLite.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Tạo & lưu N bộ cho mỗi chế độ (mặc định 1000).")
    g.add_argument("--game", default="power655")
    g.add_argument("-n", "--sets", type=int, default=DEFAULT_SETS)
    g.add_argument("--force", action="store_true", help="Tạo thêm dù kỳ này đã có batch.")

    e = sub.add_parser("evaluate", help="Chấm các kỳ đang chờ đã có kết quả thật.")
    e.add_argument("--game", default=None, help="Bỏ trống = mọi game.")

    b = sub.add_parser("board", help="In bảng xếp hạng.")
    b.add_argument("--game", default="power655")
    return p


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_arg_parser().parse_args()
    if args.cmd == "generate":
        res = generate(args.db, args.game, args.sets, args.force)
        if not res["ok"]:
            print(res["msg"])
            return 1
        print(f"Đã tạo batch #{res['batch_id']} cho {res['game_type']} "
              f"(sau kỳ {res['after_period']}): {res['n_sets']} bộ × {len(METHODS)} chế độ "
              f"= {res['total_rows']} vé.")
        ev = evaluate(args.db, args.game)  # nếu KQ có sẵn thì chấm luôn
        if ev["scored"]:
            print(f"Đã chấm ngay {ev['scored']} kỳ có sẵn kết quả.")
        else:
            print("Chờ kỳ tiếp theo có kết quả rồi chạy 'evaluate' để chấm.")
        _print_board(args.db, args.game)
        return 0
    if args.cmd == "evaluate":
        ev = evaluate(args.db, args.game)
        print(f"Đã chấm {ev['scored']} kỳ · còn {ev['still_pending']} kỳ đang chờ kết quả.")
        return 0
    if args.cmd == "board":
        _print_board(args.db, args.game)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
