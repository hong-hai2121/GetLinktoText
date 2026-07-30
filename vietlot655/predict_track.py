from __future__ import annotations

"""
Backtest thực cho 6 chế độ "Bộ số gợi ý": mỗi chế độ tạo 1000 vé (bộ 6 số),
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

THỨ DUY NHẤT CẢI THIỆN ĐƯỢC là ĐỘ PHỦ của cả bội số (xem coverage3): xác suất của
từng vé thì cố định, nhưng nếu các vé chồng lấn nhau thì tiền mua vé sau bị phí.
Vì vậy bảng xếp hạng sắp theo độ phủ, không theo TB trùng (vốn chỉ là nhiễu).
"""

import argparse
import json
import random
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from itertools import combinations
from math import comb, sqrt
from pathlib import Path

import gap_stats
from crawl import DB_PATH, ensure_dirs

# 6 chế độ đúng như dropdown "Bộ số gợi ý" trong stats_web.py.
METHODS = ["balanced", "hot", "gan", "pairs", "payout", "spread"]
MODE_NAME = {
    "balanced": "Cân đối",
    "hot": "Thiên số nóng",
    "gan": "Thiên số gan",
    "pairs": "Theo cặp hay đi cùng",
    "payout": "Tránh số đông",
    "spread": "Phủ rộng",
}
DEFAULT_SETS = 1000

# Chế độ "Phủ rộng": mỗi lần bốc SPREAD_TRIES bộ ứng viên, giữ bộ phủ được NHIỀU
# bộ-3 MỚI nhất so với các vé đã chọn. Xem giải thích ở coverage3()/gen_spread().
SPREAD_TRIES = 40


# --------------------------------------------------------------------------- #
# Mô hình "độ phổ biến" — ước lượng có bao nhiêu người CÙNG đánh một số / một bộ
# --------------------------------------------------------------------------- #
# Dùng cho chế độ "Tránh số đông" (payout): bốc theo NGHỊCH ĐẢO độ phổ biến.
#
# KHÔNG làm tăng xác suất trúng. Vietlott chia Jackpot cho những người cùng trúng,
# nên bộ số ít người đánh chỉ giúp PHẢI CHIA ÍT HƠN khi đã trúng.
#
# Cơ sở: nghiên cứu hành vi chọn số (Cambridge JDM, UPenn) cho thấy người chơi dồn
# vào ngày sinh 1–31, tháng 1–12, và né số tận cùng 0/9.
# CẢNH BÁO: các hệ số theo đuôi 8/6/4 là GIẢ ĐỊNH thói quen VN (phát/lộc/tử),
# KHÔNG lấy từ nghiên cứu — Vietlott không công bố dữ liệu vé bán ra nên không thể
# kiểm chứng. Sửa ở đây nếu bạn có số liệu thật.
#
# ĐỒNG BỘ: bản JS trong stats_web.py (popOfNumber/popOfSet/isCrowdedSet) phải giống
# hệt các hệ số dưới đây, nếu không bảng xếp hạng DB sẽ lệch với trang web.
POP_BIRTHDAY = 1.60      # x <= 31: ngày sinh — yếu tố mạnh nhất
POP_MONTH = 1.25         # x <= 12: thêm nữa vì còn là tháng
POP_TAIL = {0: 0.85, 9: 0.85, 8: 1.15, 6: 1.08, 4: 0.92}
POP_SET_ALL_BIRTHDAY = 2.2   # cả 6 số <= 31
POP_SET_CONSECUTIVE = 1.25   # mỗi cặp liên tiếp
POP_SET_ARITHMETIC = 3.0     # cấp số cộng đều (1-8-15-22-29-36)
POP_SET_ONE_DECADE = 1.8     # cả 6 số cùng một hàng chục
POP_SET_SAME_TAIL = 1.5      # >= 4 số cùng đuôi
# Chỉ chỉnh trọng số từng số là KHÔNG ĐỦ: ràng buộc "điển hình" (passes) bóp chặt
# tới mức chế độ payout gần như trùng với balanced. Nên bốc thêm ở MỨC BỘ: sinh
# POP_TOURNAMENT bộ ứng viên rồi giữ bộ ít phổ biến nhất.
POP_WEIGHT_EXP = 1.5         # làm sắc trọng số nghịch đảo: (1/pop)^exp
POP_TOURNAMENT = 5           # số ứng viên mỗi lần bốc, giữ bộ pop thấp nhất


def pop_of_number(x: int) -> float:
    """Độ phổ biến của 1 số: >1 = nhiều người đánh, <1 = ít người đánh."""
    p = 1.0
    if x <= 31:
        p *= POP_BIRTHDAY
    if x <= 12:
        p *= POP_MONTH
    p *= POP_TAIL.get(x % 10, 1.0)
    if x == 13:
        p *= 0.90
    return p


def _is_arithmetic(s: list[int]) -> bool:
    step = s[1] - s[0]
    return step > 0 and all(s[i] - s[i - 1] == step for i in range(1, len(s)))


def pop_of_set(s: list[int]) -> float:
    """Độ phổ biến của cả bộ: trung bình từng số, nhân thêm phạt các dạng hay gặp."""
    p = sum(pop_of_number(x) for x in s) / len(s)
    if all(x <= 31 for x in s):
        p *= POP_SET_ALL_BIRTHDAY
    cons = sum(1 for i in range(len(s) - 1) if s[i + 1] == s[i] + 1)
    if cons:
        p *= POP_SET_CONSECUTIVE ** cons
    if _is_arithmetic(s):
        p *= POP_SET_ARITHMETIC
    if len({(x - 1) // 10 for x in s}) == 1:
        p *= POP_SET_ONE_DECADE
    tails: dict[int, int] = {}
    for x in s:
        tails[x % 10] = tails.get(x % 10, 0) + 1
    if max(tails.values()) >= 4:
        p *= POP_SET_SAME_TAIL
    return p


def is_crowded_set(s: list[int]) -> bool:
    """Dạng bộ đông người đánh nhất — chế độ payout loại thẳng."""
    if all(x <= 31 for x in s):
        return True
    if _is_arithmetic(s):
        return True
    if len({(x - 1) // 10 for x in s}) == 1:
        return True
    return False


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
    # Kết quả đã chấm, chỉ giữ SỐ ĐẾM theo mức trùng (c0..c6) — không giữ từng vé.
    # 1 batch 5000 vé thu lại còn 5 dòng. prediction_sets chỉ còn dùng để CHỜ chấm:
    # sinh trước khi kỳ mới về (bằng chứng đã chốt), chấm xong là xoá.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_stats (
            batch_id INTEGER NOT NULL,
            method   TEXT    NOT NULL,
            n_sets   INTEGER NOT NULL,
            c0 INTEGER NOT NULL DEFAULT 0,
            c1 INTEGER NOT NULL DEFAULT 0,
            c2 INTEGER NOT NULL DEFAULT 0,
            c3 INTEGER NOT NULL DEFAULT 0,
            c4 INTEGER NOT NULL DEFAULT 0,
            c5 INTEGER NOT NULL DEFAULT 0,
            c6 INTEGER NOT NULL DEFAULT 0,
            cov3 INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (batch_id, method)
        )
        """
    )
    # DB tạo bằng bản cũ chưa có cột cov3 — CREATE TABLE IF NOT EXISTS không thêm cột.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prediction_stats)")}
    if "cov3" not in cols:
        conn.execute(
            "ALTER TABLE prediction_stats ADD COLUMN cov3 INTEGER NOT NULL DEFAULT 0"
        )
    conn.commit()


_CCOLS = "c0,c1,c2,c3,c4,c5,c6"


def _write_stats(
    conn: sqlite3.Connection,
    batch_id: int,
    counts: dict[str, list[int]],
    covs: dict[str, int] | None = None,
) -> None:
    """Ghi phân bố số trùng + độ phủ của 1 batch rồi vứt các vé chi tiết đi."""
    covs = covs or {}
    conn.executemany(
        f"INSERT OR REPLACE INTO prediction_stats (batch_id, method, n_sets, {_CCOLS}, cov3) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(batch_id, m, sum(c), *c, covs.get(m, 0)) for m, c in counts.items()],
    )
    conn.execute("DELETE FROM prediction_sets WHERE batch_id=?", (batch_id,))


def _derive(row: sqlite3.Row) -> dict:
    """Từ c0..c6 suy ra các số liệu mà bảng xếp hạng cần."""
    c = [row[f"c{k}"] for k in range(7)]
    n = row["n_sets"] or sum(c)
    total = sum(k * c[k] for k in range(7))
    best = max((k for k in range(7) if c[k]), default=0)
    cov = row["cov3"] if "cov3" in row.keys() else 0
    return {
        "n": n, "dist": c, "sum": total, "cov3": cov or 0,
        "avg": (total / n) if n else 0.0,
        "hit3": c[3] + c[4] + c[5] + c[6],
        "hit4": c[4] + c[5] + c[6],
        "hit5": c[5] + c[6],
        "hit6": c[6],
        "best": best,
    }


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
            # càng ít người đánh càng dễ được bốc
            return (1.0 / pop_of_number(x)) ** POP_WEIGHT_EXP
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

    base = gen_pair if method == "pairs" else sample_weighted
    if method != "payout":
        return base

    def gen_unpopular() -> list[int]:
        """Bốc POP_TOURNAMENT bộ, giữ bộ ít người đánh nhất."""
        best: list[int] | None = None
        best_pop = 0.0
        for _ in range(POP_TOURNAMENT):
            s = base()
            if len(s) != 6:
                continue
            p = pop_of_set(s)
            if best is None or p < best_pop:
                best, best_pop = s, p
        return best if best is not None else base()

    return gen_unpopular


# --------------------------------------------------------------------------- #
# Độ phủ — thước đo DUY NHẤT thật sự cải thiện được khi mua nhiều vé
# --------------------------------------------------------------------------- #
# Xác suất trúng của TỪNG vé là cố định (6/n mỗi số, không chế độ nào đổi được).
# Cái đổi được là mức CHỒNG LẤN giữa các vé trong cùng một bội số: hai vé chung 5 số
# thì gần như luôn cùng trúng hoặc cùng trượt, tức là tiền mua vé thứ hai bị phí.
#
# Đo bằng số bộ-3 KHÁC NHAU mà cả bội số phủ được (mỗi vé có C(6,3)=20 bộ-3, nên
# k vé phủ tối đa 20k bộ-3). Càng gần mức trần, cơ hội "có ít nhất 1 vé trúng ≥3/≥4
# số" càng cao — với cùng số tiền bỏ ra.
def coverage3(sets: list[list[int]]) -> int:
    """Số bộ-3 khác nhau mà cả bội số phủ được."""
    seen: set[tuple[int, ...]] = set()
    for s in sets:
        seen.update(combinations(sorted(s), 3))
    return len(seen)


def coverage_cap(k: int, n: int) -> int:
    """Trần độ phủ của k vé trên dải 1..n.

    Không phải 20k: cả trò chơi chỉ có C(n,3) bộ-3, nên khi 20k vượt quá con số đó
    thì trần thật là C(n,3). Với Mega 6/45 và 1000 vé, C(45,3)=14.190 < 20.000 —
    lấy 20k làm mẫu số sẽ khiến MỌI chế độ trông tệ đi một cách giả tạo.
    """
    return min(20 * k, comb(n, 3))


def gen_spread(prof: dict, k: int) -> list[list[int]]:
    """k vé bốc tham lam theo ĐỘ PHỦ: mỗi bước giữ ứng viên phủ nhiều bộ-3 mới nhất.

    KHÔNG áp ràng buộc `passes` — ràng buộc "điển hình" thu hẹp không gian bốc nên
    làm giảm chính thứ chế độ này đang tối ưu, trong khi không hề nâng kỳ vọng trúng
    của từng vé (kỳ vọng luôn là 36/n dù chọn bộ nào).
    """
    n = prof["n"]
    pool = list(range(1, n + 1))
    covered: set[tuple[int, ...]] = set()
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for _ in range(k):
        best: tuple[int, ...] | None = None
        best_new = -1
        for _ in range(SPREAD_TRIES):
            cand = tuple(sorted(random.sample(pool, 6)))
            if cand in seen:
                continue
            new = sum(1 for c in combinations(cand, 3) if c not in covered)
            if new > best_new:
                best, best_new = cand, new
            if new == 20:          # đã phủ toàn bộ-3 mới, không cần thử tiếp
                break
        if best is None:           # cực hiếm: mọi ứng viên đều trùng vé đã có
            best = tuple(sorted(random.sample(pool, 6)))
        seen.add(best)
        covered.update(combinations(best, 3))
        out.append(list(best))
    return out


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
    if method == "spread":
        return gen_spread(prof, k)
    gen = _make_generator(method, prof)
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    budget = k * 200
    # Chế độ "tránh số đông" loại thêm các dạng bộ đông người đánh (toàn ngày sinh,
    # cấp số cộng, cùng một hàng chục) — bỏ ở pha 3 để luôn đủ số lượng.
    crowded = is_crowded_set if method == "payout" else (lambda s: False)

    # Chống "cày không ra": chế độ pairs bốc tham lam nên số bộ DUY NHẤT nó sinh
    # được có hạn (~vài nghìn). Khi k lớn, pha 1 sẽ quay vòng vô ích rất lâu —
    # đếm số lần liên tiếp không ra bộ mới để thoát sớm sang pha 2.
    stall, stall_max = 0, 20000

    tries = 0
    while len(out) < k and tries < budget and stall < stall_max:  # pha 1: qua ràng buộc + không trùng
        tries += 1
        s = gen()
        if len(s) != 6 or not passes(s, prof) or crowded(s):
            stall += 1
            continue
        key = tuple(s)
        if key in seen:
            stall += 1
            continue
        seen.add(key)
        out.append(s)
        stall = 0
    while len(out) < k and tries < budget * 2:  # pha 2: qua ràng buộc, cho trùng
        tries += 1
        s = gen()
        if len(s) == 6 and passes(s, prof) and not crowded(s):
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
            return {
                "ok": False,
                "reason": "no_data",
                "draws": len(draws),
                "msg": f"Chưa đủ dữ liệu ({len(draws)} kỳ) để tạo dự đoán.",
            }
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
                "reason": "exists",
                "batch_id": existing["id"],
                "status": existing["status"],
                "after_period": after_period,
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
            counts: dict[str, list[int]] = {}
            by_method: dict[str, list[list[int]]] = {}
            for r in conn.execute(
                "SELECT method, numbers FROM prediction_sets WHERE batch_id=?",
                (b["id"],),
            ):
                nums = [int(x) for x in r["numbers"].split(",")]
                hit = sum(1 for x in nums if x in win)
                counts.setdefault(r["method"], [0] * 7)[hit] += 1
                by_method.setdefault(r["method"], []).append(nums)
            covs = {m: coverage3(v) for m, v in by_method.items()}
            _write_stats(conn, b["id"], counts, covs)
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
# Chạy lại lịch sử (backfill / walk-forward)
# --------------------------------------------------------------------------- #
def _fetch_draws_chrono(conn: sqlite3.Connection, game_type: str) -> list[dict]:
    """Toàn bộ kỳ theo thứ tự CŨ -> MỚI, kèm kỳ/ngày (fetch_draws chỉ trả số)."""
    rows = conn.execute(
        """
        SELECT draw_period, draw_date, num1, num2, num3, num4, num5, num6
        FROM draw_results
        WHERE game_type = ?
        ORDER BY draw_date ASC, draw_period ASC
        """,
        (game_type,),
    ).fetchall()
    return [
        {"period": r["draw_period"], "date": r["draw_date"], "nums": _row_numbers(r)}
        for r in rows
    ]


def backfill(
    db_path: Path | str,
    game_type: str = "power655",
    periods: int = 300,
    n_sets: int = DEFAULT_SETS,
    progress=None,
    redo: bool = False,
) -> dict:
    """Dựng bảng xếp hạng ngay từ lịch sử thay vì chờ từng kỳ mới về.

    Với mỗi kỳ trong `periods` kỳ gần nhất: tính hồ sơ thống kê CHỈ từ các kỳ TRƯỚC
    nó, sinh n_sets bộ mỗi chế độ, rồi chấm với chính kỳ đó. Không kỳ nào được nhìn
    thấy kết quả của mình -> vẫn trung thực như chạy thật, chỉ nhanh hơn.

    Idempotent: kỳ nào đã có batch (theo after_period) thì bỏ qua.
    """
    conn = _connect(db_path)
    try:
        chrono = _fetch_draws_chrono(conn, game_type)
        total = len(chrono)
        if total < 60:
            return {"ok": False, "msg": f"Chỉ có {total} kỳ, không đủ để chạy lại."}
        # chừa tối thiểu 50 kỳ làm lịch sử gốc cho kỳ đầu tiên được chấm
        periods = max(1, min(periods, total - 50))
        n = gap_stats.resolve_n(None, game_type)
        start = total - periods

        if redo:
            # Xoá các kỳ ĐÃ CHẤM để dựng lại từ đầu (cần khi thêm chế độ mới hoặc khi
            # DB cũ chưa lưu độ phủ). Batch 'pending' được giữ: vé của nó đã chốt
            # trước khi kỳ mới về, xoá đi là mất bằng chứng "không nhìn trước kết quả".
            conn.execute(
                """
                DELETE FROM prediction_stats WHERE batch_id IN
                    (SELECT id FROM prediction_batches WHERE game_type=? AND status='scored')
                """,
                (game_type,),
            )
            conn.execute(
                "DELETE FROM prediction_batches WHERE game_type=? AND status='scored'",
                (game_type,),
            )
            conn.commit()

        existing = {
            r[0]
            for r in conn.execute(
                "SELECT after_period FROM prediction_batches WHERE game_type=?",
                (game_type,),
            )
        }

        done = skipped = 0
        for i in range(start, total):
            target, anchor = chrono[i], chrono[i - 1]
            if anchor["period"] in existing:
                skipped += 1
                continue
            hist = [d["nums"] for d in reversed(chrono[:i])]  # mới -> cũ
            prof = compute_profile(hist, n)
            win = set(target["nums"])

            cur = conn.execute(
                """
                INSERT INTO prediction_batches
                    (game_type, generated_at, after_period, after_date, n_sets,
                     target_period, target_date, target_numbers, status)
                VALUES (?,?,?,?,?,?,?,?, 'scored')
                """,
                (game_type, datetime.now().isoformat(timespec="seconds"),
                 anchor["period"], anchor["date"], n_sets,
                 target["period"], target["date"], json.dumps(sorted(win))),
            )
            batch_id = cur.lastrowid
            # Chấm ngay trong bộ nhớ, chỉ ghi phân bố xuống DB.
            counts: dict[str, list[int]] = {}
            covs: dict[str, int] = {}
            for method in METHODS:
                c = [0] * 7
                sets = generate_sets(method, prof, n_sets)
                for s in sets:
                    c[sum(1 for x in s if x in win)] += 1
                counts[method] = c
                covs[method] = coverage3(sets)
            _write_stats(conn, batch_id, counts, covs)
            conn.commit()
            done += 1
            if progress:
                progress(done, periods, target)

        return {"ok": True, "done": done, "skipped": skipped, "periods": periods}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Móc nối tự động với crawl.py (cập nhật lịch sử)
# --------------------------------------------------------------------------- #
def auto_generate(
    db_path: Path | str, game_types: list[str], n_sets: int = DEFAULT_SETS
) -> list[str]:
    """Gọi TRƯỚC khi cào: chốt 1000 bộ/chế độ dựa trên lịch sử hiện có.

    Quan trọng: phải chạy trước khi kỳ mới được ghi vào DB thì bộ số mới thật sự
    "mù" với kết quả sắp về. Nếu kỳ hiện tại đã có batch chờ thì giữ nguyên, không
    tạo chồng — cào nhiều lần trong cùng một kỳ vẫn chỉ có 1 batch.
    """
    # Chi tra ve chuoi ASCII: crawl.py in ra console Windows (cp1252) nen chu co
    # dau se lam vo tien trinh cao.
    msgs = []
    for game_type in game_types:
        try:
            res = generate(db_path, game_type, n_sets)
        except Exception as exc:  # noqa: BLE001
            msgs.append(f"{game_type}: khong tao duoc du doan ({type(exc).__name__}: {exc})")
            continue
        if res.get("ok"):
            msgs.append(
                f"{game_type}: da chot batch #{res['batch_id']} "
                f"({res['n_sets']} bo x {len(METHODS)} che do) sau ky {res['after_period']}"
            )
        elif res.get("reason") == "exists":
            msgs.append(
                f"{game_type}: giu batch #{res['batch_id']} da chot cho ky sau "
                f"{res['after_period']} ({res['status']}), khong tao chong"
            )
        elif res.get("reason") == "no_data":
            msgs.append(
                f"{game_type}: chua du du lieu ({res['draws']} ky) de chot bo so"
            )
        else:
            msgs.append(f"{game_type}: bo qua")
    return msgs


def compact(db_path: Path | str) -> dict:
    """Gom các batch ĐÃ CHẤM còn giữ vé chi tiết thành prediction_stats rồi xoá vé.

    Dùng cho DB tạo bằng bản cũ (lưu từng vé). Batch đang 'pending' được giữ nguyên
    vì vé của nó còn cần để chấm khi kỳ mới về.
    """
    conn = _connect(db_path)
    try:
        todo = [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT ps.batch_id
                FROM prediction_sets ps
                JOIN prediction_batches b ON b.id = ps.batch_id
                WHERE b.status='scored'
                """
            )
        ]
        before = conn.execute("SELECT COUNT(*) FROM prediction_sets").fetchone()[0]
        for batch_id in todo:
            counts: dict[str, list[int]] = {}
            for r in conn.execute(
                "SELECT method, matched FROM prediction_sets WHERE batch_id=?",
                (batch_id,),
            ):
                m = r["matched"]
                if m is None or not (0 <= m <= 6):
                    continue
                counts.setdefault(r["method"], [0] * 7)[m] += 1
            if counts:
                _write_stats(conn, batch_id, counts)
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM prediction_sets").fetchone()[0]
        conn.execute("VACUUM")
        return {"batches": len(todo), "rows_before": before, "rows_after": after}
    finally:
        conn.close()


def auto_evaluate(db_path: Path | str) -> dict:
    """Gọi SAU khi cào: chấm mọi batch đang chờ mà kỳ kế tiếp đã có kết quả thật."""
    return evaluate(db_path)


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
        # tỉ lệ % lý thuyết cho từng mức trùng 0..6 — để đối chiếu với thực tế
        "pct": [round(prob[m] * 100, 4) for m in range(7)],
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

        # Mọi số liệu đều suy ra từ prediction_stats (c0..c6) — không cần vé chi tiết.
        agg: dict[str, dict] = {}
        per_batch: dict[int, dict[str, float]] = {}
        dist: dict[str, list[int]] = {k: [0] * 7 for k in METHODS}
        for row in conn.execute(
            f"""
            SELECT ps.batch_id AS bid, ps.method AS method, ps.n_sets AS n_sets,
                   {_CCOLS}, ps.cov3 AS cov3
            FROM prediction_stats ps
            JOIN prediction_batches b ON b.id = ps.batch_id
            WHERE b.game_type=? AND b.status='scored'
            """,
            (game_type,),
        ):
            d = _derive(row)
            m = row["method"]
            per_batch.setdefault(row["bid"], {})[m] = d["avg"]
            a = agg.setdefault(
                m, {"sets": 0, "sum": 0, "hit3": 0, "hit4": 0, "hit5": 0, "hit6": 0,
                    "best": 0, "cov_sum": 0, "cov_cap": 0, "cov_batches": 0}
            )
            a["sets"] += d["n"]
            a["sum"] += d["sum"]
            for k in ("hit3", "hit4", "hit5", "hit6"):
                a[k] += d[k]
            a["best"] = max(a["best"], d["best"])
            # Độ phủ là thuộc tính của TỪNG bội số, không cộng dồn được giữa các kỳ —
            # lấy trung bình, kèm trần lý thuyết (coverage_cap) để quy ra %.
            if d["cov3"]:
                a["cov_sum"] += d["cov3"]
                a["cov_cap"] += coverage_cap(d["n"], n)
                a["cov_batches"] += 1
            if m in dist:
                for k in range(7):
                    dist[m][k] += d["dist"][k]
        for a in agg.values():
            a["avg"] = a["sum"] / a["sets"] if a["sets"] else 0.0
            a["cov"] = (a["cov_sum"] / a["cov_batches"]) if a["cov_batches"] else 0.0
            a["cov_rate"] = (a["cov_sum"] / a["cov_cap"] * 100) if a["cov_cap"] else 0.0

        wins = {key: 0.0 for key in METHODS}
        for per in per_batch.values():
            if not per:
                continue
            top = max(per.values())
            winners = [k for k, v in per.items() if v == top]
            for k in winners:
                wins[k] = wins.get(k, 0.0) + 1.0 / len(winners)

        # Kiểm định: mỗi KỲ là 1 quan sát độc lập (1000 vé trong cùng kỳ dùng chung
        # một kết quả nên KHÔNG độc lập với nhau — coi 300.000 vé là 300.000 quan sát
        # sẽ thổi phồng ý nghĩa thống kê lên hàng chục lần).
        # t = (TB thực − kỳ vọng lý thuyết) / sai số chuẩn giữa các kỳ.
        base_avg = 6 * 6 / n
        stats_by_method: dict[str, dict] = {}
        for key in METHODS:
            vals = [p[key] for p in per_batch.values() if key in p]
            if len(vals) < 3:
                continue
            mean = sum(vals) / len(vals)
            sd = statistics.stdev(vals)
            se = sd / sqrt(len(vals)) if sd > 0 else 0.0
            t = (mean - base_avg) / se if se > 0 else 0.0
            stats_by_method[key] = {
                "sd": round(sd, 4),
                "t": round(t, 2),
                "periods": len(vals),
                # ngưỡng 2.58 (p<0.01) thay vì 1.96: đang so 5 chế độ cùng lúc nên
                # phải chặt hơn, không thì cứ 20 lần thử là có 1 cái "trúng" do may.
                "beats_random": abs(t) > 2.58,
            }

        methods = []
        for key in METHODS:
            r = agg.get(key)
            if not r or not r["sets"]:
                methods.append({"key": key, "name": MODE_NAME[key], "sets": 0,
                                "wins": 0})
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
                "wins": round(wins.get(key, 0.0), 2),
                "dist": dist[key],
                "cov": round(r["cov"]),
                "cov_rate": round(r["cov_rate"], 1),
                **stats_by_method.get(key, {}),
            })
        # Xếp hạng theo ĐỘ PHỦ, không theo TB trùng.
        # TB trùng của mọi chế độ đều dao động quanh 36/n do may rủi (xem `beats_random`
        # — chưa chế độ nào vượt ngưỡng t=2,58), nên xếp theo nó là xếp theo nhiễu và
        # đẩy nhầm chế độ chồng lấn nặng lên đầu bảng. Độ phủ mới là thứ khác nhau thật
        # giữa các chế độ, đo được, và quyết định cơ hội có vé trúng khi mua cả bội số.
        methods.sort(key=lambda m: (m["sets"] == 0, -(m.get("cov") or 0)))

        recent = []
        for b in conn.execute(
            """
            SELECT id, target_period, target_date, target_numbers
            FROM prediction_batches
            WHERE game_type=? AND status='scored'
            ORDER BY target_date DESC, id DESC LIMIT 30
            """,
            (game_type,),
        ):
            per = {
                m: round(v, 3) for m, v in per_batch.get(b["id"], {}).items()
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
    print(f"{'Chế độ':<20}{'Phủ':>8}{'Vé':>8}{'TB':>8}{'Thắng kỳ':>10}"
          f"{'≥3':>7}{'≥4':>6}{'≥5':>5}{'6':>4}{'Tốt':>5}")
    print("-" * 81)
    for m in sb["methods"]:
        if not m.get("sets"):
            print(f"{m['name']:<20}{'—':>8}{'(chưa có dữ liệu)':>40}")
            continue
        cov = f"{m['cov_rate']:.0f}%" if m.get("cov") else "—"
        print(f"{m['name']:<20}{cov:>8}{m['sets']:>8}{m['avg']:>8.3f}{m['wins']:>10}"
              f"{m['hit3']:>7}{m['hit4']:>6}{m['hit5']:>5}{m['hit6']:>4}{m['best']:>5}")
    print("\nXếp theo ĐỘ PHỦ (bộ-3 khác nhau / trần lý thuyết). TB trùng của mọi chế độ\n"
          "đều quanh mức ngẫu nhiên — chênh lệch ở cột TB là nhiễu, không phải thứ hạng.")
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

    bf = sub.add_parser(
        "backfill",
        help="Chạy lại N kỳ lịch sử gần nhất để có bảng xếp hạng ngay (không chờ kỳ mới).",
    )
    bf.add_argument("--game", default="power655")
    bf.add_argument("--periods", type=int, default=300, help="Số kỳ gần nhất (mặc định 300).")
    bf.add_argument("-n", "--sets", type=int, default=DEFAULT_SETS)
    bf.add_argument(
        "--redo",
        action="store_true",
        help="Xoá các kỳ đã chấm rồi dựng lại từ đầu (cần khi thêm chế độ mới).",
    )

    sub.add_parser(
        "compact",
        help="Gom vé chi tiết của các kỳ đã chấm thành số liệu rồi xoá vé (thu nhỏ DB).",
    )
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
    if args.cmd == "compact":
        res = compact(args.db)
        print(f"Đã gom {res['batches']} kỳ · vé chi tiết {res['rows_before']:,} → "
              f"{res['rows_after']:,} dòng.")
        return 0
    if args.cmd == "backfill":
        t0 = time.time()

        def show(done: int, total: int, target: dict) -> None:
            if done == 1 or done % 10 == 0 or done == total:
                el = time.time() - t0
                eta = el / done * (total - done)
                print(f"  [{done}/{total}] kỳ {target['period']} ({target['date']}) "
                      f"· đã {el/60:.1f} phút · còn ~{eta/60:.1f} phút", flush=True)

        print(f"Chạy lại {args.periods} kỳ gần nhất, {args.sets} bộ/chế độ "
              f"({args.sets*len(METHODS):,} vé/kỳ)…", flush=True)
        if args.redo:
            print("--redo: xoá các kỳ ĐÃ CHẤM của game này rồi dựng lại từ đầu.", flush=True)
        res = backfill(args.db, args.game, args.periods, args.sets,
                       progress=show, redo=args.redo)
        if not res["ok"]:
            print(res["msg"])
            return 1
        print(f"\nXong: chấm {res['done']} kỳ"
              + (f", bỏ qua {res['skipped']} kỳ đã có sẵn" if res["skipped"] else "")
              + f" · tổng {time.time()-t0:.0f}s.")
        _print_board(args.db, args.game)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
