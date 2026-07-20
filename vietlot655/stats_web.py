from __future__ import annotations

"""
Sinh trang HTML tĩnh (self-contained) hiển thị thống kê Vietlott lên webview.

Đọc các bảng do number_stats.py tạo trong vietlott_data.db:
  - position_distribution / position_summary  -> 6 biểu đồ x1..x6
  - number_frequency                          -> tần suất từng số
  - number_streaks                            -> phân bố chuỗi về liên tiếp

Xuất ra exports/stats.html (không phụ thuộc mạng, mở được offline) rồi tự mở
trình duyệt. Chạy: python stats_web.py  [--game power655] [--no-open]
"""

import argparse
import json
import math
import random
import re
import sqlite3
import statistics
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

import gap_stats
from crawl import DB_PATH, EXPORT_DIR, ensure_dirs

DEFAULT_HTML_PATH = EXPORT_DIR / "stats.html"
MEGA_DB_PATH = DB_PATH.parent / "vietlott_mega645_data.db"
MEGA_HTML_PATH = EXPORT_DIR / "stats_mega645.html"

POSITION_NAMES = {
    1: "x1 · nhỏ nhất",
    2: "x2",
    3: "x3",
    4: "x4",
    5: "x5",
    6: "x6 · lớn nhất",
}


def compute_gap_stats(db_path: Path | str, game_type: str) -> dict | None:
    """Dùng lại gap_stats.py để tính khoảng cách gap; trả None nếu không có dữ liệu."""
    try:
        draws = gap_stats.fetch_draws(db_path, game_type=game_type)
        n = gap_stats.resolve_n(None, game_type)
        gs = gap_stats.compute_stats(draws, n)
    except Exception:
        return None

    labels = ["g1 (x1→x2)", "g2 (x2→x3)", "g3 (x3→x4)",
              "g4 (x4→x5)", "g5 (x5→x6)"]
    rel = abs(gs["gbar"] - gs["expected_gap"]) / gs["expected_gap"]
    return {
        "N": gs["N"],
        "expected_gap": round(gs["expected_gap"], 3),
        "expected_range": round(gs["expected_range"], 3),
        "per_position": [
            {
                "label": labels[i],
                "mean": round(gs["gbar_per_position"][i], 3),
                "std": round(gs["gstd_per_position"][i], 3),
            }
            for i in range(len(gs["gbar_per_position"]))
        ],
        "gbar": round(gs["gbar"], 4),
        "gstd": round(gs["gstd"], 3),
        "range_bar": round(gs["range_bar"], 3),
        "range_std": round(gs["range_std"], 3),
        "range_min": gs["range_min"],
        "range_max": gs["range_max"],
        "rel_diff": round(rel * 100, 2),
        "ok": rel < 0.05,
    }


def _gammq(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a,x) — để tính p-value chi-square."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:  # khai triển chuỗi cho P
        ap, summ, delv = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1.0
            delv *= x / ap
            summ += delv
            if abs(delv) < abs(summ) * 1e-14:
                break
        return 1.0 - summ * math.exp(-x + a * math.log(x) - gln)
    # phân số liên tục cho Q
    b, c = x + 1.0 - a, 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delv = d * c
        h *= delv
        if abs(delv - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def compute_tests(db_path: Path | str, game_type: str) -> dict | None:
    """Chi-square (55 số có ra đều không?) + Runs test (chuỗi tổng có ngẫu nhiên không?)."""
    draws = gap_stats.fetch_draws(db_path, game_type=game_type)  # mới -> cũ
    total = len(draws)
    if total < 30:
        return None
    n = gap_stats.resolve_n(None, game_type)

    # --- Chi-square goodness-of-fit: mỗi số kỳ vọng ra total*6/n lần ---
    count = {x: 0 for x in range(1, n + 1)}
    for d in draws:
        for x in d:
            count[x] += 1
    expected = total * 6 / n
    chi2 = sum((count[x] - expected) ** 2 / expected for x in range(1, n + 1))
    df = n - 1
    p_chi = _gammq(df / 2.0, chi2 / 2.0)

    # --- Runs test trên chuỗi tổng 6 số so với trung vị (theo thời gian) ---
    sums_chrono = [sum(d) for d in reversed(draws)]  # cũ -> mới
    med = statistics.median(sums_chrono)
    seq = [1 if s > med else 0 for s in sums_chrono if s != med]
    n1 = sum(seq)
    n2 = len(seq) - n1
    runs = 1 + sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1]) if seq else 0
    z = None
    if n1 > 0 and n2 > 0:
        er = 2 * n1 * n2 / (n1 + n2) + 1
        var = (2 * n1 * n2 * (2 * n1 * n2 - n1 - n2)) / (
            (n1 + n2) ** 2 * (n1 + n2 - 1)
        )
        z = (runs - er) / math.sqrt(var) if var > 0 else 0.0

    return {
        "chi2": {
            "stat": round(chi2, 2),
            "df": df,
            "expected": round(expected, 1),
            "p": round(p_chi, 4),
            "ok": p_chi > 0.05,
        },
        "runs": {
            "runs": runs,
            "expected": round(2 * n1 * n2 / (n1 + n2) + 1, 1) if (n1 and n2) else None,
            "z": round(z, 3) if z is not None else None,
            "n1": n1,
            "n2": n2,
            "ok": (z is not None and abs(z) < 1.96),
        },
    }


def compute_extra_stats(
    db_path: Path | str, game_type: str, recent_n: int = 30
) -> dict | None:
    """Các phân tích hỗ trợ dựng bộ số: tổng/chẵn-lẻ/thấp-cao/đầu số, gan, nóng, cặp.

    LƯU Ý: chỉ là thống kê mô tả, KHÔNG tăng xác suất trúng (xổ số độc lập).
    """
    draws = gap_stats.fetch_draws(db_path, game_type=game_type)  # mới -> cũ
    total = len(draws)
    if not draws:
        return None
    n = gap_stats.resolve_n(None, game_type)
    low_max = n // 2  # 1..low_max = "thấp", còn lại "cao"

    # --- Tổng 6 số ---
    sums = sorted(sum(d) for d in draws)

    def pct(p: float) -> int:
        idx = min(len(sums) - 1, max(0, round(p * (len(sums) - 1))))
        return sums[idx]

    smin, smax = sums[0], sums[-1]
    bin_w = 15
    start = (smin // bin_w) * bin_w
    edges = list(range(start, smax + 1, bin_w))
    counts = {edge: 0 for edge in edges}
    for s in sums:
        counts[start + ((s - start) // bin_w) * bin_w] += 1
    sum_bins = [
        {"label": str(edge), "range": f"{edge}–{edge + bin_w - 1}", "occ": counts[edge]}
        for edge in edges
    ]

    # --- Chẵn/lẻ, thấp/cao (đếm theo số phần tử mỗi kỳ) ---
    odd = [0] * 7
    low = [0] * 7
    for d in draws:
        odd[sum(1 for x in d if x % 2 == 1)] += 1
        low[sum(1 for x in d if x <= low_max)] += 1

    # --- Đầu số (hàng chục) ---
    bands = [(1, 9), (10, 19), (20, 29), (30, 39), (40, 49), (50, n)]
    decade = [
        {"label": f"{lo}-{hi}", "occ": sum(1 for d in draws for x in d if lo <= x <= hi)}
        for lo, hi in bands
    ]

    # --- Số gan (lâu chưa về) + nóng gần đây ---
    gap_of = {}
    for num in range(1, n + 1):
        g = total
        for i, d in enumerate(draws):  # mới nhất trước
            if num in d:
                g = i
                break
        gap_of[num] = g
    overdue = sorted(
        ({"number": k, "gap": v} for k, v in gap_of.items()),
        key=lambda r: (-r["gap"], r["number"]),
    )[:12]

    rn = min(recent_n, total)
    recent = {num: 0 for num in range(1, n + 1)}
    for d in draws[:rn]:
        for x in d:
            recent[x] += 1
    hot = sorted(
        ({"number": k, "count": v} for k, v in recent.items()),
        key=lambda r: (-r["count"], r["number"]),
    )[:12]

    # --- Cặp số hay đi cùng ---
    pair_count: dict[tuple[int, int], int] = {}
    for d in draws:
        for a, b in combinations(d, 2):  # d đã sort tăng dần nên a < b
            pair_count[(a, b)] = pair_count.get((a, b), 0) + 1
    top_pairs = sorted(pair_count.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    exp_pair = total * (6 / n) * (5 / (n - 1))  # kỳ vọng ngẫu nhiên cho 1 cặp

    # Ma trận đồng xuất hiện đầy đủ (cho chế độ "theo cặp" ở bộ gợi ý).
    cooc_mat = [[0] * n for _ in range(n)]
    for (a, b), c in pair_count.items():
        cooc_mat[a - 1][b - 1] = c
        cooc_mat[b - 1][a - 1] = c

    # --- Cấu trúc bộ số bổ sung: số liên tiếp, đuôi số ---
    consec_dist: dict[int, int] = defaultdict(int)
    last_digit = [0] * 10
    for d in draws:
        consec_dist[sum(1 for i in range(5) if d[i + 1] == d[i] + 1)] += 1
        for x in d:
            last_digit[x % 10] += 1
    consecutive = [
        {"label": str(k), "occ": consec_dist.get(k, 0)}
        for k in range((max(consec_dist) if consec_dist else 0) + 1)
    ]
    with_consec = total - consec_dist.get(0, 0)

    # --- Số lặp lại từ kỳ ngay trước ---
    rep = [0] * 7
    for t in range(total - 1):
        rep[len(set(draws[t]) & set(draws[t + 1]))] += 1
    comparisons = total - 1
    repeat_prev = [{"label": str(k), "occ": rep[k]} for k in range(7)]
    repeat_mean = (
        round(sum(k * rep[k] for k in range(7)) / comparisons, 2) if comparisons else 0
    )

    # --- Khoảng nghỉ trung bình mỗi số (bổ sung cho "số gan") ---
    appear_idx: dict[int, list[int]] = {num: [] for num in range(1, n + 1)}
    for i, d in enumerate(draws):
        for x in d:
            appear_idx[x].append(i)

    def _avg_rest(num: int):
        idxs = appear_idx[num]
        if len(idxs) < 2:
            return None
        return round((idxs[-1] - idxs[0]) / (len(idxs) - 1), 1)

    for o in overdue:
        o["rest"] = _avg_rest(o["number"])

    return {
        "total": total,
        "n": n,
        "low_max": low_max,
        "recent_n": rn,
        "latest": list(draws[0]),  # kỳ mới nhất (6 số đã sort) để prefill mô phỏng
        "sum": {
            "bins": sum_bins,
            "mean": round(statistics.fmean(sums), 1),
            "p10": pct(0.10),
            "p90": pct(0.90),
            "min": smin,
            "max": smax,
        },
        "odd": odd,
        "low": low,
        "decade": decade,
        "consecutive": consecutive,
        "with_consec": with_consec,
        "last_digit": [{"label": str(k), "occ": last_digit[k]} for k in range(10)],
        "repeat_prev": repeat_prev,
        "repeat_mean": repeat_mean,
        "exp_rest": round(n / 6, 1),
        "overdue": overdue,
        "hot": hot,
        "pairs": [{"a": a, "b": b, "count": c} for (a, b), c in top_pairs],
        "exp_pair": round(exp_pair, 1),
        "cooc": cooc_mat,
    }


def compute_algo_picks(
    db_path: Path | str, game_type: str, recent_w: int = 30, decay: float = 0.97
) -> list[dict] | None:
    """Chạy từng thuật toán lên lịch sử, mỗi cái xuất ra 1 bộ 6 số theo cách tính riêng.

    LƯU Ý QUAN TRỌNG: đây chỉ là "áp dụng thuật toán để ra một con số"; khi backtest
    tất cả đều xấp xỉ ngẫu nhiên (~0,65 số/kỳ). Không cái nào dự đoán được kỳ tới.
    """
    draws = gap_stats.fetch_draws(db_path, game_type=game_type)  # mới -> cũ, mỗi kỳ sort tăng
    total = len(draws)
    if total < 10:
        return None
    n = gap_stats.resolve_n(None, game_type)
    nums = list(range(1, n + 1))

    count = {x: 0 for x in nums}
    weighted = {x: 0.0 for x in nums}
    gap = {x: total for x in nums}
    recent = {x: 0 for x in nums}
    seen: set[int] = set()
    win = min(recent_w, total)
    cooc = [[0] * (n + 1) for _ in range(n + 1)]

    for i, d in enumerate(draws):
        w = decay ** i
        for x in d:
            count[x] += 1
            weighted[x] += w
            if x not in seen:
                gap[x] = i
                seen.add(x)
            if i < win:
                recent[x] += 1
        for a, b in combinations(d, 2):
            cooc[a][b] += 1
            cooc[b][a] += 1

    recent_rate = {x: recent[x] / win for x in nums}
    posterior = {x: (count[x] + 1) / (total + 2) for x in nums}
    last = draws[0]  # kỳ mới nhất
    cooc_last = {j: sum(cooc[j][i] for i in last) for j in nums}

    # Markov bậc 1: từ 6 số kỳ mới nhất -> số hay ra ở kỳ liền sau.
    prev_occ = {x: 0 for x in nums}
    conext = [[0] * (n + 1) for _ in range(n + 1)]
    for t in range(total - 1):
        older, newer = draws[t + 1], draws[t]
        for i in older:
            prev_occ[i] += 1
            for j in newer:
                conext[i][j] += 1
    markov = {
        j: sum(conext[i][j] / prev_occ[i] for i in last if prev_occ[i]) for j in nums
    }

    def top6(score, largest=True):
        return sorted(nums, key=lambda x: (-score[x] if largest else score[x], x))[:6]

    def zmap(d):
        vals = list(d.values())
        m = statistics.fmean(vals)
        sd = statistics.pstdev(vals) or 1.0
        return {k: (v - m) / sd for k, v in d.items()}

    def greedy(seed_set):
        s = list(seed_set)
        while len(s) < 6:
            best, bv = None, -1
            for x in nums:
                if x in s:
                    continue
                v = sum(cooc[x][y] for y in s)
                if v > bv:
                    bv, best = v, x
            s.append(best)
        return sorted(s)

    zc, zr, zg, zl = zmap(count), zmap(recent_rate), zmap(gap), zmap(cooc_last)
    composite = {x: zc[x] + zr[x] + zg[x] + zl[x] for x in nums}

    # Cặp support cao nhất -> seed cho "frequent itemset".
    top_pair, tpv = (1, 2), -1
    for a in nums:
        for b in range(a + 1, n + 1):
            if cooc[a][b] > tpv:
                tpv, top_pair = cooc[a][b], (a, b)

    # Monte Carlo & ngẫu nhiên có trọng số (seed cố định để tái lập).
    rnd = random.Random(1234)
    mc_pick = sorted(rnd.sample(nums, 6))

    def weighted_sample():
        rr = random.Random(5678)
        pool, wts, chosen = nums[:], [count[x] for x in nums], []
        for _ in range(6):
            tot = sum(wts)
            if tot <= 0:
                idx = rr.randrange(len(pool))
            else:
                t, acc, idx = rr.random() * tot, 0.0, 0
                for k, ww in enumerate(wts):
                    acc += ww
                    if acc >= t:
                        idx = k
                        break
            chosen.append(pool.pop(idx))
            wts.pop(idx)
        return sorted(chosen)

    # Thuật toán di truyền: tối đa hoá "độ điển hình" (cặp mạnh + cân đối tổng/chẵn-lẻ/thấp-cao).
    target_sum = 3 * (n + 1)
    low_max = n // 2

    def fix6(lst, rr):
        out: list[int] = []
        for x in lst:
            if 1 <= x <= n and x not in out:
                out.append(x)
            if len(out) == 6:
                break
        while len(out) < 6:
            c = rr.randint(1, n)
            if c not in out:
                out.append(c)
        return sorted(out)

    def fitness(s):
        co = sum(cooc[a][b] for a, b in combinations(s, 2)) / (tpv * 15 + 1)
        odd = sum(1 for x in s if x % 2)
        low = sum(1 for x in s if x <= low_max)
        bal = -abs(odd - 3) - abs(low - 3) - abs(sum(s) - target_sum) / (target_sum * 0.15)
        return co + bal

    gr = random.Random(999)
    pop = [fix6(gr.sample(nums, 6), gr) for _ in range(60)]
    for _ in range(60):
        pop.sort(key=fitness, reverse=True)
        pop = pop[:20]
        while len(pop) < 60:
            p1, p2 = gr.choice(pop[:10]), gr.choice(pop[:20])
            child = list(dict.fromkeys(p1 + p2))
            if len(child) > 6:
                child = gr.sample(child, 6)
            if gr.random() < 0.3:
                child[gr.randrange(len(child))] = gr.randint(1, n)
            pop.append(fix6(child, gr))
    pop.sort(key=fitness, reverse=True)
    ga_pick = sorted(pop[0])

    return [
        {"key": "hot", "group": "Tần suất & thời gian", "name": "Tần suất cao (số nóng)",
         "note": "6 số về nhiều nhất toàn lịch sử", "pick": top6(count)},
        {"key": "cold", "group": "Tần suất & thời gian", "name": "Tần suất thấp (số lạnh)",
         "note": "6 số về ít nhất toàn lịch sử", "pick": top6(count, largest=False)},
        {"key": "weighted", "group": "Tần suất & thời gian", "name": "Tần suất có trọng số",
         "note": f"ưu tiên kỳ gần (giảm dần {decay}^kỳ)", "pick": top6(weighted)},
        {"key": "ma", "group": "Tần suất & thời gian", "name": "Trung bình trượt",
         "note": f"tỉ lệ về cao nhất trong {win} kỳ gần nhất", "pick": top6(recent_rate)},
        {"key": "gap", "group": "Tần suất & thời gian", "name": "Khoảng cách xuất hiện (số gan)",
         "note": "6 số lâu chưa về nhất", "pick": top6(gap)},
        {"key": "bayes", "group": "Tần suất & thời gian", "name": "Xác suất Bayes",
         "note": "hậu nghiệm Beta(1,1) — tần suất làm mượt", "pick": top6(posterior)},
        {"key": "markov", "group": "Quan hệ cặp/nhóm", "name": "Chuỗi Markov (bậc 1)",
         "note": "từ 6 số kỳ mới nhất → số hay ra ở kỳ liền sau", "pick": top6(markov)},
        {"key": "cooc", "group": "Quan hệ cặp/nhóm", "name": "Ma trận đồng xuất hiện",
         "note": "số đồng xuất hiện nhiều nhất với 6 số kỳ mới nhất", "pick": top6(cooc_last)},
        {"key": "pairs", "group": "Quan hệ cặp/nhóm", "name": "Cặp & nhóm số (tham lam)",
         "note": "khởi từ số nóng nhất, ghép dần theo cặp hay đi cùng",
         "pick": greedy([max(nums, key=lambda x: (count[x], -x))])},
        {"key": "itemset", "group": "Quan hệ cặp/nhóm", "name": "Apriori / FP-Growth",
         "note": "ghép từ cặp support cao nhất — 2 thuật toán cho cùng kết quả, chỉ khác tốc độ",
         "pick": greedy(list(top_pair))},
        {"key": "composite", "group": "Tổng hợp & ngẫu nhiên", "name": "Chấm điểm tổng hợp",
         "note": "cộng z-score: tần suất + phong độ + độ gan + đồng xuất hiện", "pick": top6(composite)},
        {"key": "ga", "group": "Tổng hợp & ngẫu nhiên", "name": "Thuật toán di truyền",
         "note": "tiến hoá bộ số tối đa hoá 'độ điển hình' (cặp mạnh + cân đối)", "pick": ga_pick},
        {"key": "wrand", "group": "Tổng hợp & ngẫu nhiên", "name": "Ngẫu nhiên có trọng số",
         "note": "bốc 6 số, xác suất tỉ lệ thuận tần suất", "pick": weighted_sample()},
        {"key": "mc", "group": "Tổng hợp & ngẫu nhiên", "name": "Mô phỏng Monte Carlo",
         "note": "mọi số xấp xỉ đều → kết quả ~ bốc ngẫu nhiên", "pick": mc_pick},
    ]


def compute_track(db_path: Path | str, game_type: str) -> dict | None:
    """Bảng xếp hạng 5 giải thuật trên KẾT QUẢ THẬT đã tích luỹ trong DB.

    Bộ số được crawl.py chốt trước mỗi lần cập nhật lịch sử (bảng
    prediction_batches / prediction_sets), rồi chấm điểm khi kỳ mới về. Ở đây chỉ
    đọc ra — có gọi evaluate() một lần cho chắc, phòng khi DB được cập nhật bằng
    đường khác. Thiếu bảng / lỗi thì trả None và trang vẫn chạy bình thường.
    """
    try:
        import predict_track

        predict_track.evaluate(db_path, game_type)
        return predict_track.load_scoreboard(db_path, game_type)
    except Exception:  # noqa: BLE001
        return None


def load_game_data(
    conn: sqlite3.Connection, db_path: Path | str, game_type: str
) -> dict:
    total_row = conn.execute(
        "SELECT MAX(total_draws) FROM number_frequency WHERE game_type = ?",
        (game_type,),
    ).fetchone()
    total_draws = total_row[0] if total_row and total_row[0] else 0

    # Tần suất từng số.
    frequency = [
        {
            "number": row["number"],
            "count": row["total_count"],
            "current_streak": row["current_streak"],
            "max_streak": row["max_streak"],
            "gap": row["gap_since_last"],
        }
        for row in conn.execute(
            """
            SELECT number, total_count, current_streak, max_streak, gap_since_last
            FROM number_frequency
            WHERE game_type = ?
            ORDER BY number ASC
            """,
            (game_type,),
        )
    ]

    # Phân bố chuỗi về liên tiếp (gộp mọi số).
    streaks = [
        {"length": row["streak_length"], "occ": row["total"]}
        for row in conn.execute(
            """
            SELECT streak_length, SUM(occurrences) AS total
            FROM number_streaks
            WHERE game_type = ?
            GROUP BY streak_length
            ORDER BY streak_length ASC
            """,
            (game_type,),
        )
    ]

    # Phân bố theo vị trí x1..x6.
    summary_by_pos = {
        row["position"]: row
        for row in conn.execute(
            """
            SELECT position, min_value, max_value, mode_value, mean_value
            FROM position_summary
            WHERE game_type = ?
            """,
            (game_type,),
        )
    }
    values_by_pos: dict[int, list[dict]] = {}
    for row in conn.execute(
        """
        SELECT position, value, occurrences
        FROM position_distribution
        WHERE game_type = ?
        ORDER BY position ASC, value ASC
        """,
        (game_type,),
    ):
        values_by_pos.setdefault(row["position"], []).append(
            {"value": row["value"], "occ": row["occurrences"]}
        )

    positions = []
    for pos in sorted(summary_by_pos):
        s = summary_by_pos[pos]
        positions.append(
            {
                "position": pos,
                "name": POSITION_NAMES.get(pos, f"x{pos}"),
                "min": s["min_value"],
                "max": s["max_value"],
                "mode": s["mode_value"],
                "mean": round(s["mean_value"], 2),
                # "values" (phân bố đầy đủ từng vị trí) đã bỏ: mục hiển thị không còn,
                # chỉ min/max còn được sugEngine dùng làm ràng buộc sinh số.
            }
        )

    return {
        "game_type": game_type,
        "total_draws": total_draws,
        "positions": positions,
        "frequency": frequency,
        "streaks": streaks,
        "gaps": compute_gap_stats(db_path, game_type),
        "extra": compute_extra_stats(db_path, game_type),
        "algos": compute_algo_picks(db_path, game_type),
        "tests": compute_tests(db_path, game_type),
        "track": compute_track(db_path, game_type),
    }


def load_all(
    conn: sqlite3.Connection, db_path: Path | str, game_types: list[str] | None
) -> list[dict]:
    if not game_types:
        game_types = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT game_type FROM number_frequency ORDER BY game_type"
            )
        ]
    data = []
    for game_type in game_types:
        game = load_game_data(conn, db_path, game_type)
        if game["total_draws"]:
            data.append(game)
    return data


def compute_frequency_list(
    db_path: Path | str, game_type: str, n: int
) -> list[dict]:
    """Tính count + gap (kỳ chưa về) từng số trực tiếp từ draw_results.

    Dùng cho trang rút gọn (Mega) khi DB chưa có bảng number_frequency — chỉ cần
    'count' và 'gap' để chế độ số nóng/số gan ở phần Gợi ý & Backtest chạy đúng.
    """
    draws = gap_stats.fetch_draws(db_path, game_type=game_type)  # mới -> cũ
    total = len(draws)
    count = {x: 0 for x in range(1, n + 1)}
    gap = {x: total for x in range(1, n + 1)}
    seen: set[int] = set()
    for i, d in enumerate(draws):
        for x in d:
            count[x] += 1
            if x not in seen:
                gap[x] = i
                seen.add(x)
    return [
        {
            "number": x,
            "count": count[x],
            "current_streak": 0,
            "max_streak": 0,
            "gap": gap[x],
        }
        for x in range(1, n + 1)
    ]


def load_game_data_minimal(db_path: Path | str, game_type: str) -> dict | None:
    """Nạp dữ liệu tối thiểu cho trang rút gọn (Gợi ý / Backtest / Mô phỏng).

    Không cần các bảng number_frequency / position_* / number_streaks — mọi thứ
    tính thẳng từ draw_results, nên chạy được cả khi DB chưa qua number_stats.py.
    """
    extra = compute_extra_stats(db_path, game_type)
    if not extra:
        return None
    return {
        "game_type": game_type,
        "total_draws": extra["total"],
        "positions": [],
        "frequency": compute_frequency_list(db_path, game_type, extra["n"]),
        "streaks": [],
        "gaps": None,
        "extra": extra,
        "algos": None,
        "tests": None,
        "track": compute_track(db_path, game_type),
    }


def load_all_minimal(
    conn: sqlite3.Connection, db_path: Path | str, game_types: list[str] | None
) -> list[dict]:
    if not game_types:
        game_types = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT game_type FROM draw_results ORDER BY game_type"
            )
        ]
    data = []
    for game_type in game_types:
        game = load_game_data_minimal(db_path, game_type)
        if game and game["total_draws"]:
            data.append(game)
    return data


HTML_TEMPLATE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>
  :root{
    --plane:#f9f9f7; --surface:#fcfcfb; --text:#0b0b0b; --text2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --baseline:#c3c2b7; --series:#2a78d6;
    --series-soft:#cde2fb; --border:rgba(11,11,11,.10);
    --good:#006300; --warn:#9a6700;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --plane:#0d0d0d; --surface:#1a1a19; --text:#fff; --text2:#c3c2b7;
      --muted:#898781; --grid:#2c2c2a; --baseline:#383835; --series:#3987e5;
      --series-soft:#184f95; --border:rgba(255,255,255,.10);
      --good:#0ca30c; --warn:#fab219;
    }
  }
  :root[data-theme="light"]{
    --plane:#f9f9f7; --surface:#fcfcfb; --text:#0b0b0b; --text2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --baseline:#c3c2b7; --series:#2a78d6;
    --series-soft:#cde2fb; --border:rgba(11,11,11,.10);
    --good:#006300; --warn:#9a6700;
  }
  :root[data-theme="dark"]{
    --plane:#0d0d0d; --surface:#1a1a19; --text:#fff; --text2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --baseline:#383835; --series:#3987e5;
    --series-soft:#184f95; --border:rgba(255,255,255,.10);
    --good:#0ca30c; --warn:#fab219;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--text);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
  .wrap{max-width:1120px;margin:0 auto;padding:24px 20px 64px}
  header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px 18px;margin-bottom:4px}
  h1{font-size:22px;margin:0;font-weight:650}
  .sub{color:var(--text2);font-size:13px}
  .bar-row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:18px 0 8px}
  .tabs{display:flex;gap:6px}
  .btn{appearance:none;border:1px solid var(--border);background:var(--surface);
    color:var(--text2);padding:6px 12px;border-radius:8px;font-size:13px;cursor:pointer}
  .btn:hover{color:var(--text)}
  .btn.active{background:var(--series);border-color:var(--series);color:#fff}
  .spacer{flex:1}
  .cards{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0 6px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
    padding:12px 16px;min-width:130px}
  .card .k{font-size:12px;color:var(--muted)}
  .card .v{font-size:26px;font-weight:650;margin-top:2px}
  .card .s{font-size:11px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums}
  .good{color:var(--good)} .warn{color:var(--warn)}
  .grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
  .setrow{display:flex;align-items:center;gap:8px;margin:7px 0;flex-wrap:wrap}
  .setrow .lbl{color:var(--muted);font-size:12px;min-width:44px}
  .chip{width:30px;height:30px;border-radius:50%;background:var(--series);color:#fff;
    display:inline-flex;align-items:center;justify-content:center;font-size:13px;
    font-weight:600;font-variant-numeric:tabular-nums}
  .setmeta{color:var(--muted);font-size:11.5px;margin-left:4px}
  .ptbl{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
  .ptbl td{padding:3px 6px;border-bottom:1px solid var(--border)}
  .ptbl .pair{white-space:nowrap;font-weight:600}
  .ptbl .barcell{width:60%}
  .ptbl .track{height:10px;border-radius:5px;background:var(--series)}
  .sugwrap{display:flex;gap:18px;flex-wrap:wrap}
  .sugleft{flex:1 1 320px;min-width:300px}
  .sugnote{flex:0 1 268px;font-size:12.5px;color:var(--text2);line-height:1.55;
    border-left:2px solid var(--series);padding-left:14px}
  .sugnote .notet{font-weight:600;color:var(--text);margin-bottom:6px}
  .sugnote ol{margin:6px 0;padding-left:18px}
  .sugnote li{margin:3px 0}
  .sugnote b{color:var(--text)}
  .sugnote .wl{color:var(--warn);display:block;margin-top:8px}
  #trackBody .wl{color:var(--warn);display:block;margin-top:8px}
  .sugctl{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:end;margin-bottom:8px}
  .sugctl label{display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--muted)}
  .sugctl select,.sugctl input{background:var(--surface);border:1px solid var(--border);
    color:var(--text);border-radius:7px;padding:6px 9px;font-size:13px}
  .sugctl input{width:104px;font-variant-numeric:tabular-nums}
  .chip.lock{background:var(--good)}
  .setmeta b{color:var(--text);font-size:13px}
  .simrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px}
  .simrow input{background:var(--surface);border:1px solid var(--border);color:var(--text);
    border-radius:8px;padding:7px 11px;font-size:13px;min-width:230px;flex:1;
    font-variant-numeric:tabular-nums}
  .btn[disabled]{opacity:.45;cursor:default}
  .simcount{font-size:13px;color:var(--text2);margin:4px 0 8px;font-variant-numeric:tabular-nums}
  .simtbl{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
  .simtbl th,.simtbl td{border-bottom:1px solid var(--border);padding:5px 8px;text-align:right}
  .simtbl th:first-child,.simtbl td:first-child{text-align:left}
  .simtbl th{color:var(--muted);font-weight:500;font-size:11.5px}
  .simtbl .hit{color:var(--good);font-weight:600}
  .simtbl .wait{color:var(--muted)}
  .btgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:10px;margin-top:8px}
  .btcol{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
  .btcol.lead{border-color:var(--good);box-shadow:0 0 0 1px var(--good) inset}
  .btcol .nm{font-size:12.5px;font-weight:600;display:flex;justify-content:space-between;
    align-items:center;gap:6px}
  .btcol .nm .star{color:var(--good)}
  .btcol .big{font-size:24px;font-weight:650;margin:6px 0 0;font-variant-numeric:tabular-nums}
  .btcol .k{font-size:11px;color:var(--muted)}
  .btcol .k b{color:var(--text);font-weight:600}
  .btcol .mini{margin-top:8px;border-top:1px solid var(--border);padding-top:6px}
  .btcol .hl{display:flex;align-items:center;gap:6px;font-size:11.5px;margin:3px 0;
    font-variant-numeric:tabular-nums}
  .btcol .hl .num{width:20px;color:var(--text2)}
  .btcol .hl .bar{flex:1;height:6px;border-radius:3px;background:var(--series-soft)}
  .btcol .hl .bar>span{display:block;height:6px;border-radius:3px;background:var(--series)}
  .btcol .hl .pct{width:34px;text-align:right;color:var(--muted)}
  .btwin{border-top:1px solid var(--border);padding:8px 0}
  .btwin .wtitle{font-size:13px;font-weight:600}
  .btwin .wcount{font-weight:400;color:var(--muted);font-size:11.5px;margin-left:6px;
    font-variant-numeric:tabular-nums}
  .wlevel{font-size:11.5px;color:var(--muted);margin:7px 0 3px}
  .wsets{display:flex;flex-wrap:wrap;gap:8px}
  .wset{display:inline-flex;gap:3px;padding:3px 5px;border:1px solid var(--border);border-radius:8px}
  .wset .chip{width:24px;height:24px;font-size:11px}
  .chip.win{background:var(--good)}
  .wmore{align-self:center;color:var(--muted);font-size:11.5px}
  #btSets,#sugSets{width:100%;min-height:120px;max-height:280px;margin-top:6px;resize:vertical;
    background:var(--surface);border:1px solid var(--border);color:var(--text);
    border-radius:8px;padding:8px 10px;font-family:ui-monospace,Consolas,monospace;
    font-size:12px;line-height:1.45;font-variant-numeric:tabular-nums}
  .algogrp{font-size:12px;color:var(--muted);font-weight:600;margin:14px 0 4px;
    text-transform:uppercase;letter-spacing:.04em}
  .algorow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:8px 0;
    border-bottom:1px solid var(--border)}
  .algoinfo{flex:1 1 240px;min-width:220px}
  .algoinfo b{font-size:13px}
  .algoinfo .note{color:var(--muted);font-size:11.5px;display:block;margin-top:1px}
  .algorow .chips{flex:0 0 auto}
  .algorow .chip{width:27px;height:27px;font-size:12px}
  .banner{background:var(--series-soft);border:1px solid var(--border);border-radius:10px;
    padding:10px 14px;font-size:12.5px;color:var(--text);margin-bottom:6px}
  h2{font-size:15px;font-weight:600;margin:30px 0 4px}
  h2 .hint{font-weight:400;color:var(--muted);font-size:12.5px;margin-left:8px}
  .grid6{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 12px 8px}
  .panel .pt{font-size:13.5px;font-weight:600}
  .panel .pc{font-size:12px;color:var(--text2);margin:1px 0 4px;font-variant-numeric:tabular-nums}
  svg{width:100%;height:auto;display:block;overflow:visible}
  .grid line{stroke:var(--grid);stroke-width:1}
  .base line{stroke:var(--baseline);stroke-width:1}
  .tick{fill:var(--muted);font-size:10px;font-variant-numeric:tabular-nums}
  .bar{fill:var(--series)}
  .bar.soft{fill:var(--series-soft)}
  .dlabel{fill:var(--text2);font-size:10px;font-variant-numeric:tabular-nums}
  .refline{stroke:var(--text2);stroke-width:2;stroke-dasharray:0}
  .reftext{fill:var(--text2);font-size:10px}
  details{margin-top:8px}
  summary{cursor:pointer;color:var(--muted);font-size:12.5px}
  table{border-collapse:collapse;font-size:12px;margin-top:8px;width:100%;
    font-variant-numeric:tabular-nums}
  th,td{border-bottom:1px solid var(--border);padding:3px 8px;text-align:right}
  th:first-child,td:first-child{text-align:left}
  #tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .08s;
    background:var(--text);color:var(--surface);padding:6px 9px;border-radius:7px;
    font-size:12px;z-index:10;white-space:nowrap;box-shadow:0 4px 14px rgba(0,0,0,.25)}
  footer{color:var(--muted);font-size:12px;margin-top:34px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Thống kê Vietlott</h1>
    <span class="sub" id="subtitle"></span>
    <div class="spacer"></div>
    %%NAV%%
    <button class="btn" id="themeBtn" type="button">◐ Sáng/Tối</button>
  </header>

  <div class="bar-row">
    <div class="tabs" id="gameTabs"></div>
  </div>

  <div class="cards" id="cards"></div>

  <h2>Bộ số gợi ý <span class="hint">chỉ để tham khảo — KHÔNG tăng xác suất trúng</span></h2>
  <div class="panel" id="sugPanel" style="max-width:840px">
    <div class="sugctl">
      <label>Chế độ
        <select id="sugMode">
          <option value="balanced">Cân đối (điển hình)</option>
          <option value="hot">Thiên số nóng</option>
          <option value="gan">Thiên số gan</option>
          <option value="pairs">Theo cặp hay đi cùng</option>
          <option value="payout">Tránh số đông</option>
        </select>
      </label>
      <label>Số bộ<input id="sugCount" type="text" inputmode="numeric" value="5"
        style="width:78px" title="1–5000 · trên 20 bộ là chế độ bội số"></label>
      <label>Khoá số<input id="sugLock" type="text" inputmode="numeric" placeholder="vd: 7 22"></label>
      <label>Loại số<input id="sugExcl" type="text" inputmode="numeric" placeholder="vd: 13"></label>
      <button class="btn" id="genBtn" type="button">🎲 Tạo</button>
    </div>
    <div class="pc warn" id="sugMsg"></div>
    <div class="pc" id="sugStat"></div>
    <details id="sugSetsWrap" style="margin-top:6px"><summary>Xem &amp; chép toàn bộ bội số</summary>
      <textarea id="sugSets" readonly placeholder="Nhập số bộ &gt; 20 rồi bấm Tạo"></textarea>
    </details>
    <div class="sugwrap">
      <div class="sugleft"><div id="suggestList"></div></div>
      <div class="sugnote" id="sugNote"></div>
    </div>
  </div>

  <h2>Bảng xếp hạng chế độ (backtest thực) <span class="hint">Tạo &amp; lưu bội số trước · sau khi có kết quả thì nhập vào &amp; So sánh (dữ liệu lưu trong trình duyệt, mở lại vẫn còn)</span></h2>
  <div class="panel" id="btPanel" style="max-width:1000px">
    <div class="sugctl">
      <label>Số bộ / giải thuật<input id="btCount" type="text" inputmode="numeric" value="1000"></label>
      <button class="btn" id="btGen" type="button">🎲 Tạo &amp; lưu</button>
      <span style="flex:1"></span>
      <label>Kết quả trúng (6 số)<input id="btInput" type="text" inputmode="numeric" placeholder="Nhập 6 số" style="width:220px"></label>
      <button class="btn" id="btCmp" type="button">🔍 So sánh</button>
    </div>
    <div class="pc warn" id="btMsg"></div>
    <div class="pc" id="btStatus"></div>
    <details id="btSetsWrap" style="margin-top:6px"><summary>Xem các bội số đã tạo &amp; lưu</summary>
      <textarea id="btSets" readonly placeholder="Chưa có — bấm Tạo &amp; lưu"></textarea>
    </details>
    <div id="btBody"></div>
  </div>

  <h2>Giải thuật nào đang trúng nhiều nhất? <span class="hint">dữ liệu thật, tích luỹ trong DB · mỗi lần cập nhật lịch sử: chốt 1000 bộ/giải thuật TRƯỚC, kỳ mới về thì tự chấm</span></h2>
  <div class="panel" id="trackPanel" style="max-width:1000px">
    <div class="pc" id="trackStatus"></div>
    <div id="trackBody"></div>
  </div>

  <h2>Mô phỏng: cần tạo bao nhiêu bộ để trúng? <span class="hint">nhập 6 số kết quả — máy tạo vé ngẫu nhiên liên tục tới khi trùng</span></h2>
  <div class="panel" id="simPanel" style="max-width:680px">
    <div class="simrow">
      <input id="simInput" type="text" inputmode="numeric" placeholder="Nhập 6 số">
      <button class="btn" id="simRun" type="button">▶ Chạy</button>
      <button class="btn" id="simStop" type="button" disabled>■ Dừng</button>
    </div>
    <div class="pc warn" id="simMsg"></div>
    <div class="simcount" id="simCount"></div>
    <table class="simtbl" id="simTable"></table>
    <div class="pc" style="margin-top:10px">Mỗi "bộ" là 1 vé 6 số ngẫu nhiên. Trúng 6/6 trung bình cần hàng chục triệu bộ — không có cách rút ngắn vì mỗi kỳ độc lập.</div>
  </div>

  <!--LOWER_START-->
  <h2>Tần suất từng số <span class="hint">số lần mỗi số đã về</span>
    <button class="btn" id="freqSort" type="button" style="margin-left:10px">Sắp theo: số</button>
  </h2>
  <div class="panel"><div id="freqChart"></div>
    <details><summary>Xem bảng</summary><div id="freqTable"></div></details>
  </div>

  <h2>Phân bố độ dài chuỗi về liên tiếp <span class="hint">gộp tất cả số</span></h2>
  <div class="panel" style="max-width:520px"><div id="streakChart"></div></div>

  <h2>Khoảng cách giữa các số (gap) <span class="hint">gN = x(N+1) − xN mỗi kỳ · so với máy quay công bằng</span></h2>
  <div class="panel" id="gapPanel" style="max-width:640px">
    <div class="cards" id="gapCards" style="margin:0 0 6px"></div>
    <div id="gapChart"></div>
    <div class="pc" id="gapVerdict" style="margin-top:8px"></div>
  </div>

  <h2>Kiểm định thống kê <span class="hint">máy quay có ĐỀU và NGẪU NHIÊN không? (không dùng để chọn số)</span></h2>
  <div class="panel" id="testPanel" style="max-width:660px">
    <div class="cards" id="testCards" style="margin:0 0 8px"></div>
    <div class="pc" id="testNote"></div>
  </div>

  <h2>Tổng &amp; cân bằng bộ số <span class="hint">giúp loại bộ số quá lệch</span></h2>
  <div class="panel" id="balPanel">
    <div class="cards" id="balCards" style="margin:0 0 8px"></div>
    <div class="pc">Phân bố tổng 6 số</div>
    <div id="sumChart"></div>
    <div class="grid3" style="margin-top:12px">
      <div><div class="pc">Số lẻ mỗi kỳ (còn lại là chẵn)</div><div id="oddChart"></div></div>
      <div><div class="pc">Số "thấp" (1–<span id="lowMax"></span>) mỗi kỳ</div><div id="lowChart"></div></div>
      <div><div class="pc">Đầu số (theo hàng chục)</div><div id="decChart"></div></div>
    </div>
    <div class="grid3" style="margin-top:12px">
      <div><div class="pc">Đuôi số (chữ số cuối 0–9)</div><div id="tailChart"></div></div>
      <div><div class="pc">Số cặp liên tiếp mỗi kỳ</div><div id="consecChart"></div></div>
      <div><div class="pc" id="repTitle">Số lặp lại từ kỳ trước</div><div id="repChart"></div></div>
    </div>
  </div>

  <h2>Số gan &amp; phong độ <span class="hint">lâu chưa về vs nóng gần đây</span></h2>
  <div class="panel" id="ganPanel"><div class="grid3"
      style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
    <div><div class="pc" id="ganTitle">Gan nhất — số kỳ chưa về</div><div id="ganChart"></div></div>
    <div><div class="pc" id="hotTitle">Nóng gần đây — số lần về</div><div id="hotChart"></div></div>
  </div></div>

  <h2>Cặp số hay đi cùng <span class="hint" id="pairHint"></span></h2>
  <div class="panel" id="pairPanel" style="max-width:560px"><div id="pairTable"></div></div>

  <h2>Bộ số theo từng thuật toán <span class="hint">chạy thuật toán trên lịch sử → ra 6 số theo cách tính của nó</span></h2>
  <div class="panel" id="algoPanel">
    <div class="banner">⚠ Đây là <b>kết quả tính từ lịch sử theo đúng từng thuật toán</b> — để hiểu thuật toán làm gì, KHÔNG phải để tin nó trúng. Khi backtest, tất cả đều xấp xỉ ngẫu nhiên (~0,65 số/kỳ).</div>
    <div id="algoList"></div>
    <div class="pc" style="margin-top:12px">Nhóm máy học (Logistic, Random Forest, XGBoost, Mạng nơ-ron, LSTM) cần thư viện ngoài (sklearn/xgboost/torch) và khi backtest cũng cho kết quả ~ ngẫu nhiên — mình để riêng, làm nếu bạn cần.</div>
  </div>
  <!--LOWER_END-->

  <footer id="footer"></footer>
</div>

<div id="tip"></div>

<script>
const DATA = %%DATA%%;
const GENERATED = "%%GENERATED%%";
const SOURCE = "%%SOURCE%%";
let current = 0, freqByCount = false;
let simRunning = false, simTarget = null, simAttempts = 0, simHits = null;
const SIM_CAP = 100000000, SIM_CHUNK = 300000;

const tip = document.getElementById('tip');
function showTip(html, x, y){
  tip.innerHTML = html; tip.style.opacity = 1;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let nx = x + 14, ny = y + 14;
  if(nx + w > window.innerWidth) nx = x - w - 14;
  if(ny + h > window.innerHeight) ny = y - h - 14;
  tip.style.left = nx + 'px'; tip.style.top = ny + 'px';
}
function hideTip(){ tip.style.opacity = 0; }

// --- reusable column chart (single blue series, magnitude) -----------------
function niceTicks(max, count){
  if(max <= 0) return [0];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const ticks = [];
  for(let v = 0; v <= max + 1e-9; v += step) ticks.push(Math.round(v));
  if(ticks[ticks.length-1] < max) ticks.push(Math.round(ticks[ticks.length-1]+step));
  return ticks;
}
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
function mkTile(k,v,sub){
  return `<div class="card"><div class="k">${k}</div><div class="v">${v}</div>`+
         (sub?`<div class="s">${sub}</div>`:'')+`</div>`;
}

// series: [{label, value, sub, highlight}]
function columnChart(mount, series, opt){
  opt = opt || {};
  const W = opt.W || 720, H = opt.H || 240;
  const mL = 34, mR = 8, mT = 14, mB = 20;
  const iw = W - mL - mR, ih = H - mT - mB;
  const n = series.length || 1;
  const maxV = Math.max(1, ...series.map(d => d.value));
  const ticks = niceTicks(maxV, 4);
  const top = ticks[ticks.length - 1];
  const band = iw / n;
  const bw = Math.min(band - 2, 24);
  const y = v => mT + ih - (v / top) * ih;
  const labelEvery = opt.labelEvery || Math.ceil(n / 12);

  let s = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
  s += `<g class="grid">`;
  for(const t of ticks) s += `<line x1="${mL}" y1="${y(t)}" x2="${W-mR}" y2="${y(t)}"/>`;
  s += `</g><g class="tick" text-anchor="end">`;
  for(const t of ticks) s += `<text x="${mL-6}" y="${y(t)+3}">${t.toLocaleString('vi')}</text>`;
  s += `</g>`;
  // columns
  for(let i=0;i<n;i++){
    const d = series[i];
    const x = mL + i*band + (band-bw)/2;
    const yt = y(d.value), yb = mT + ih;
    const r = Math.min(4, bw/2, Math.max(0, yb-yt));
    const cls = 'bar' + (d.highlight ? '' : (opt.softNonMax && d.value!==maxV ? ' soft':''));
    if(d.value>0){
      s += `<path class="${cls}" d="M${x} ${yb} L${x} ${yt+r} Q${x} ${yt} ${x+r} ${yt} `
         + `L${x+bw-r} ${yt} Q${x+bw} ${yt} ${x+bw} ${yt+r} L${x+bw} ${yb} Z" `
         + `data-i="${i}"></path>`;
    } else {
      s += `<rect x="${x}" y="${yb-1}" width="${bw}" height="1" class="bar" data-i="${i}"></rect>`;
    }
  }
  // x labels (bỏ nhãn cuối nếu quá sát nhãn kề để tránh chồng chữ)
  const showLast = ((n-1) % labelEvery) >= Math.ceil(labelEvery/2);
  s += `<g class="tick" text-anchor="middle">`;
  for(let i=0;i<n;i++){
    if(i % labelEvery === 0 || (i === n-1 && showLast)){
      const x = mL + i*band + band/2;
      s += `<text x="${x}" y="${H-6}">${esc(series[i].label)}</text>`;
    }
  }
  s += `</g>`;
  // baseline
  s += `<g class="base"><line x1="${mL}" y1="${mT+ih}" x2="${W-mR}" y2="${mT+ih}"/></g>`;
  // đường lý thuyết (reference line)
  if(opt.refLine != null && opt.refLine <= top){
    const yv = y(opt.refLine);
    s += `<line class="refline" x1="${mL}" y1="${yv}" x2="${W-mR}" y2="${yv}"/>`;
    if(opt.refLabel)
      s += `<text class="reftext" text-anchor="end" x="${W-mR}" y="${yv-4}">${esc(opt.refLabel)}</text>`;
  }
  // selective direct label on the tallest column
  if(opt.labelMax){
    const i = series.findIndex(d=>d.value===maxV);
    if(i>=0){ const x = mL + i*band + band/2;
      s += `<text class="dlabel" text-anchor="middle" x="${x}" y="${y(maxV)-4}">${maxV.toLocaleString('vi')}</text>`; }
  }
  // label every column (dùng khi ít cột, vd biểu đồ chuỗi)
  if(opt.labelAll){
    for(let i=0;i<n;i++){ const d=series[i]; if(d.value<=0) continue;
      const x = mL + i*band + band/2;
      s += `<text class="dlabel" text-anchor="middle" x="${x}" y="${y(d.value)-4}">${d.value.toLocaleString('vi')}</text>`;
    }
  }
  s += `</svg>`;
  mount.innerHTML = s;

  // hover
  const svg = mount.querySelector('svg');
  svg.addEventListener('mousemove', e=>{
    const t = e.target.closest('[data-i]');
    if(!t){ hideTip(); return; }
    const d = series[+t.getAttribute('data-i')];
    showTip((opt.tipTitle?opt.tipTitle(d):esc(d.label)) + '<br>' +
            d.value.toLocaleString('vi') + ' lần' +
            (d.sub?('<br>'+d.sub):''), e.clientX, e.clientY);
  });
  svg.addEventListener('mouseleave', hideTip);
}

// --- render one game -------------------------------------------------------
function render(){
  const g = DATA[current];
  document.getElementById('subtitle').textContent =
    g.game_type + ' · ' + g.total_draws.toLocaleString('vi') + ' kỳ';

  // tabs active
  [...document.querySelectorAll('#gameTabs .btn')].forEach((b,i)=>
    b.classList.toggle('active', i===current));

  // cards
  const cards = document.getElementById('cards');
  cards.innerHTML = '';
  const hot = [...g.frequency].sort((a,b)=>b.count-a.count)[0];
  const cold = [...g.frequency].sort((a,b)=>b.gap-a.gap)[0];
  const mk = (k,v)=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  cards.innerHTML =
    mk('Tổng số kỳ', g.total_draws.toLocaleString('vi')) +
    mk('Số về nhiều nhất', hot ? (hot.number+' · '+hot.count+' lần') : '—') +
    mk('Lâu chưa về nhất', cold ? (cold.number+' · '+cold.gap+' kỳ') : '—');

  // Mục "Phân bố theo vị trí" đã bỏ khỏi trang. Dữ liệu g.positions VẪN được giữ
  // trong payload vì sugEngine dùng min/max từng vị trí làm ràng buộc sinh số —
  // bỏ đi thì bộ số trên web sẽ khác với predict_track.py sinh cho DB.

  renderFreq();

  // streaks (đếm chính xác độ dài; ít cột nên nhãn tất cả)
  const streakEl = document.getElementById('streakChart');
  if(streakEl){
    columnChart(streakEl,
      g.streaks.map(s=>({label:s.length+' kỳ', value:s.occ})),
      {W:400, H:230, labelAll:true, labelEvery:1,
       tipTitle:d=>('chuỗi dài đúng '+esc(d.label))});
  }

  renderGap();
  renderTests();
  renderBalance();
  renderGanHot();
  renderPairs();
  renderSuggest();
  renderBacktest();
  renderTrack();
  renderSim();
  renderAlgos();

  document.getElementById('footer').textContent =
    'Nguồn: ' + SOURCE + ' · tạo lúc ' + GENERATED;
}

function renderGap(){
  if(!document.getElementById('gapPanel')) return;
  const gp = DATA[current].gaps;
  const panel = document.getElementById('gapPanel');
  if(!gp){ panel.style.display='none'; return; }
  panel.style.display='';

  const dgap = gp.gbar - gp.expected_gap;
  document.getElementById('gapCards').innerHTML =
    mkTile('Gap TB chung', gp.gbar.toLocaleString('vi'),
      'LT '+gp.expected_gap+' · lệch '+(dgap>=0?'+':'')+dgap.toFixed(2)+' · ±'+gp.gstd) +
    mkTile('Range TB', gp.range_bar.toLocaleString('vi'),
      'LT '+gp.expected_range+' · ±'+gp.range_std) +
    mkTile('Range nhỏ–lớn', gp.range_min+'–'+gp.range_max, gp.N.toLocaleString('vi')+' kỳ');

  columnChart(document.getElementById('gapChart'),
    gp.per_position.map(p=>({label:p.label.split(' ')[0], value:p.mean, sub:'±'+p.std})),
    {W:540, H:220, labelAll:true, labelEvery:1,
     refLine:gp.expected_gap, refLabel:'LT '+gp.expected_gap,
     tipTitle:d=>('khoảng cách '+esc(d.label))});

  document.getElementById('gapVerdict').innerHTML = gp.ok
    ? '<span class="good">✓ gbar lệch '+gp.rel_diff+'% so với lý thuyết → máy quay ỔN.</span>'
    : '<span class="warn">⚠ gbar lệch '+gp.rel_diff+'% (&gt;5%) → nên xem thêm dữ liệu.</span>';
}

const argmax = arr => arr.reduce((bi,v,i,a)=> v>a[bi]?i:bi, 0);

function renderTests(){
  if(!document.getElementById('testPanel')) return;
  const t = DATA[current].tests;
  const panel = document.getElementById('testPanel');
  if(!t){ panel.style.display='none'; return; }
  panel.style.display='';
  const c=t.chi2, r=t.runs;
  document.getElementById('testCards').innerHTML =
    mkTile('Chi-square (đồng đều?)', 'χ² = '+c.stat,
      'df='+c.df+' · p='+c.p+' · '+(c.ok?'ĐỀU':'LỆCH')) +
    mkTile('Runs test (ngẫu nhiên?)', (r.z!=null?('Z = '+r.z):'—'),
      'runs='+r.runs+(r.expected!=null?(' / kỳ vọng '+r.expected):'')+
      ' · '+(r.ok?'NGẪU NHIÊN':'BẤT THƯỜNG'));
  document.getElementById('testNote').innerHTML =
    (c.ok
      ? '<span class="good">✓ Chi-square p='+c.p+' (&gt;0,05): 55 số ra ĐỀU nhau, không số nào bị thiên vị.</span>'
      : '<span class="warn">⚠ Chi-square p='+c.p+' (≤0,05): có dấu hiệu lệch phân phối.</span>')
    + '<br>' +
    (r.ok
      ? '<span class="good">✓ Runs test |Z|&lt;1,96: chuỗi tổng không có streak bất thường → ngẫu nhiên.</span>'
      : '<span class="warn">⚠ Runs test |Z|≥1,96: chuỗi có dấu hiệu bất thường.</span>')
    + '<br><span style="color:var(--muted)">Hai kiểm định chỉ xác nhận máy công bằng — KHÔNG dùng để chọn số.</span>';
}

function renderBalance(){
  if(!document.getElementById('balPanel')) return;
  const ex = DATA[current].extra;
  const panel = document.getElementById('balPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('lowMax').textContent = ex.low_max;

  const oK = argmax(ex.odd), lK = argmax(ex.low);
  const consecPct = Math.round(ex.with_consec/ex.total*100);
  document.getElementById('balCards').innerHTML =
    mkTile('Tổng TB', ex.sum.mean.toLocaleString('vi'),
      'thực tế '+ex.sum.min+'–'+ex.sum.max) +
    mkTile('Vùng tổng hay gặp', ex.sum.p10+'–'+ex.sum.p90, '~80% số kỳ') +
    mkTile('Chẵn/lẻ hay gặp', oK+' lẻ · '+(6-oK)+' chẵn', '') +
    mkTile('Thấp/cao hay gặp', lK+' thấp · '+(6-lK)+' cao', '1–'+ex.low_max+' là thấp') +
    mkTile('Kỳ có số liên tiếp', consecPct+'%', ex.with_consec+' / '+ex.total+' kỳ') +
    mkTile('Lặp lại từ kỳ trước', ex.repeat_mean+' số', 'trung bình mỗi kỳ');

  const bins = ex.sum.bins;
  columnChart(document.getElementById('sumChart'),
    bins.map(b=>({label:b.label, value:b.occ, range:b.range})),
    {W:760, H:220, labelEvery: Math.ceil(bins.length/10),
     tipTitle:d=>('tổng '+esc(d.range))});

  const kLabels = ['0','1','2','3','4','5','6'];
  columnChart(document.getElementById('oddChart'),
    ex.odd.map((v,i)=>({label:kLabels[i], value:v})),
    {W:340,H:170,labelAll:true,labelEvery:1,tipTitle:d=>(esc(d.label)+' số lẻ')});
  columnChart(document.getElementById('lowChart'),
    ex.low.map((v,i)=>({label:kLabels[i], value:v})),
    {W:340,H:170,labelAll:true,labelEvery:1,tipTitle:d=>(esc(d.label)+' số thấp')});
  columnChart(document.getElementById('decChart'),
    ex.decade.map(d=>({label:d.label, value:d.occ})),
    {W:340,H:170,labelEvery:1,tipTitle:d=>('đầu số '+esc(d.label))});

  columnChart(document.getElementById('tailChart'),
    ex.last_digit.map(d=>({label:d.label, value:d.occ})),
    {W:340,H:170,labelAll:true,labelEvery:1,tipTitle:d=>('đuôi '+esc(d.label))});
  columnChart(document.getElementById('consecChart'),
    ex.consecutive.map(d=>({label:d.label, value:d.occ})),
    {W:340,H:170,labelAll:true,labelEvery:1,tipTitle:d=>(esc(d.label)+' cặp liên tiếp')});
  columnChart(document.getElementById('repChart'),
    ex.repeat_prev.map(d=>({label:d.label, value:d.occ})),
    {W:340,H:170,labelAll:true,labelEvery:1,tipTitle:d=>(esc(d.label)+' số lặp lại')});
  document.getElementById('repTitle').textContent =
    'Số lặp lại từ kỳ trước (TB '+ex.repeat_mean+')';
}

function renderGanHot(){
  if(!document.getElementById('ganPanel')) return;
  const ex = DATA[current].extra;
  const panel = document.getElementById('ganPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('ganTitle').textContent =
    'Gan nhất — số kỳ chưa về (nghỉ TB lý thuyết ~'+ex.exp_rest+' kỳ)';
  document.getElementById('hotTitle').textContent =
    'Nóng '+ex.recent_n+' kỳ gần nhất — số lần về';
  columnChart(document.getElementById('ganChart'),
    ex.overdue.map(o=>({label:o.number, value:o.gap, sub:'nghỉ TB '+(o.rest==null?'—':o.rest)+' kỳ'})),
    {W:460,H:200,labelAll:true,labelEvery:1,tipTitle:d=>('số '+esc(d.label)+' · chưa về')});
  columnChart(document.getElementById('hotChart'),
    ex.hot.map(o=>({label:o.number, value:o.count})),
    {W:460,H:200,labelAll:true,labelEvery:1,tipTitle:d=>('số '+esc(d.label)+' · lần về')});
}

function renderPairs(){
  if(!document.getElementById('pairPanel')) return;
  const ex = DATA[current].extra;
  const panel = document.getElementById('pairPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('pairHint').textContent =
    'kỳ vọng ngẫu nhiên ≈ '+ex.exp_pair+' lần/cặp — top cao hơn chủ yếu do biến động';
  const mx = ex.pairs.length ? ex.pairs[0].count : 1;
  const rows = ex.pairs.map(p=>{
    const w = Math.round(p.count/mx*100);
    return `<tr><td class="pair">${p.a} · ${p.b}</td>`+
      `<td class="barcell"><div class="track" style="width:${w}%"></div></td>`+
      `<td style="text-align:right">${p.count}</td></tr>`;
  }).join('');
  document.getElementById('pairTable').innerHTML = '<table class="ptbl"><tbody>'+rows+'</tbody></table>';
}

function sugInputs(){
  const parse = id => (document.getElementById(id).value.match(/\d+/g)||[]).map(Number);
  return {
    mode: document.getElementById('sugMode').value,
    count: Math.max(1, Math.min(parseInt(document.getElementById('sugCount').value,10)||5, 5000)),
    lock: parse('sugLock'),
    excl: parse('sugExcl'),
  };
}
function overlap(a,b){ let c=0; for(const x of a) if(b.includes(x)) c++; return c; }

// --- Mô hình "độ phổ biến": ước lượng bao nhiêu người CÙNG đánh một số / một bộ ---
// Dùng cho chế độ "Tránh số đông": bốc theo NGHỊCH ĐẢO độ phổ biến.
// KHÔNG tăng xác suất trúng — Vietlott chia Jackpot cho những người cùng trúng, nên
// bộ ít người đánh chỉ giúp PHẢI CHIA ÍT HƠN khi đã trúng.
// Cơ sở: nghiên cứu hành vi chọn số (Cambridge JDM, UPenn) — người chơi dồn vào ngày
// sinh 1–31, tháng 1–12, né số tận cùng 0/9. Hệ số theo đuôi 8/6/4 là GIẢ ĐỊNH thói
// quen VN (phát/lộc/tử), không lấy từ nghiên cứu và không kiểm chứng được.
// ĐỒNG BỘ: phải giống hệt pop_of_number/pop_of_set/is_crowded_set trong predict_track.py,
// nếu không bảng xếp hạng đọc từ DB sẽ lệch với backtest chạy trên trang này.
const POP_TAIL = {0:0.85, 9:0.85, 8:1.15, 6:1.08, 4:0.92};
const POP_WEIGHT_EXP = 1.5, POP_TOURNAMENT = 5;
function popOfNumber(x){
  let p = 1;
  if(x <= 31) p *= 1.60;               // ngày sinh — yếu tố mạnh nhất
  if(x <= 12) p *= 1.25;               // tháng
  p *= (POP_TAIL[x % 10] || 1);
  if(x === 13) p *= 0.90;
  return p;
}
function popIsArith(s){
  const step = s[1]-s[0];
  if(step <= 0) return false;
  for(let i=1;i<s.length;i++) if(s[i]-s[i-1] !== step) return false;
  return true;
}
function popOfSet(s){
  let p = s.reduce((a,x)=>a+popOfNumber(x),0)/s.length;
  if(s.every(x=>x<=31)) p *= 2.2;                        // bộ "toàn ngày sinh"
  let cons=0; for(let i=0;i<s.length-1;i++) if(s[i+1]===s[i]+1) cons++;
  if(cons) p *= Math.pow(1.25, cons);
  if(popIsArith(s)) p *= 3.0;                            // cấp số cộng đều
  if(new Set(s.map(x=>Math.floor((x-1)/10))).size === 1) p *= 1.8;
  const tail={}; s.forEach(x=>{ tail[x%10]=(tail[x%10]||0)+1; });
  if(Math.max.apply(null,Object.values(tail)) >= 4) p *= 1.5;
  return p;
}
function isCrowdedSet(s){
  if(s.every(x=>x<=31)) return true;
  if(popIsArith(s)) return true;
  if(new Set(s.map(x=>Math.floor((x-1)/10))).size === 1) return true;
  return false;
}
// Bốc POP_TOURNAMENT bộ, giữ bộ ít người đánh nhất. Chỉ chỉnh trọng số từng số là
// KHÔNG đủ — ràng buộc "điển hình" bóp tới mức payout gần trùng balanced.
function popTournament(gen){
  let best=null, bestP=0;
  for(let i=0;i<POP_TOURNAMENT;i++){
    const s=gen(); if(!s || s.length<6) continue;
    const p=popOfSet(s);
    if(best===null || p<bestP){ best=s; bestP=p; }
  }
  return best || gen();
}

function sugEngine(){
  const g = DATA[current], ex = g.extra, n = ex.n;
  const positions = g.positions || [], cooc = ex.cooc;
  const freq = {}; (g.frequency||[]).forEach(f=>freq[f.number]=f);
  const latest = new Set(ex.latest||[]);
  const {mode,count,lock,excl} = sugInputs();
  const exclSet = new Set(excl.filter(x=>x>=1&&x<=n));
  const locked = [...new Set(lock.filter(x=>x>=1&&x<=n&&!exclSet.has(x)))].slice(0,5);

  const sumBinMax = Math.max(1,...ex.sum.bins.map(b=>b.occ));
  const oddMax = Math.max(1,...ex.odd), lowMx = Math.max(1,...ex.low);
  const consMax = Math.max(1,...ex.consecutive.map(c=>c.occ));
  const repMax = Math.max(1,...ex.repeat_prev.map(r=>r.occ));
  const sumBinOcc = s => { for(const b of ex.sum.bins){ const e=+b.label;
    if(s>=e&&s<=e+14) return b.occ; } return 0; };

  function score(set){
    const sum=set.reduce((a,b)=>a+b,0);
    const odd=set.filter(x=>x%2).length;
    const low=set.filter(x=>x<=ex.low_max).length;
    let cons=0; for(let i=0;i<5;i++) if(set[i+1]===set[i]+1) cons++;
    const rep=set.filter(x=>latest.has(x)).length;
    const parts={
      'Tổng':      sumBinOcc(sum)/sumBinMax,
      'Chẵn/lẻ':   (ex.odd[odd]||0)/oddMax,
      'Thấp/cao':  (ex.low[low]||0)/lowMx,
      'Liên tiếp': ((ex.consecutive[cons]||{occ:0}).occ)/consMax,
      'Lặp':       ((ex.repeat_prev[rep]||{occ:0}).occ)/repMax,
    };
    const vals=Object.values(parts);
    return {set,sum,odd,low,cons,rep,parts,
      score:Math.round(vals.reduce((a,b)=>a+b,0)/vals.length*100)};
  }
  function passes(m){
    if(m.sum<ex.sum.p10||m.sum>ex.sum.p90) return false;
    if(m.odd<2||m.odd>4||m.low<2||m.low>4||m.cons>1||m.rep>2) return false;
    if(new Set(m.set.map(x=>Math.floor((x-1)/10))).size<3) return false;
    for(let i=0;i<6;i++){ const p=positions[i]; if(p&&(m.set[i]<p.min||m.set[i]>p.max)) return false; }
    return true;
  }
  const weightOf = x => exclSet.has(x)?0:
    mode==='hot' ? (freq[x]?freq[x].count:0)+1 :
    mode==='gan' ? (freq[x]?freq[x].gap:0)+1 :
    mode==='payout' ? Math.pow(1/popOfNumber(x), POP_WEIGHT_EXP) : 1;
  // Trọng số từng số KHÔNG đổi giữa các lần bốc -> tính sẵn 1 lần. Trước đây dựng lại
  // mảng + gọi weightOf (có Math.pow ở chế độ payout) cho mỗi lần bốc, khiến sinh bội
  // số 5000 bộ mất ~12s và đơ trình duyệt.
  const W0 = new Float64Array(n+1);
  for(let x=1;x<=n;x++) W0[x] = exclSet.has(x) ? 0 : weightOf(x);
  function sampleWeighted(){
    const chosen=[...locked], used=new Uint8Array(n+1);
    for(const x of chosen) used[x]=1;
    while(chosen.length<6){
      let tot=0; for(let x=1;x<=n;x++) if(!used[x]) tot+=W0[x];
      if(tot<=0){ const rem=[]; for(let x=1;x<=n;x++) if(!used[x]&&!exclSet.has(x)) rem.push(x);
        if(!rem.length) break; const p=rem[Math.random()*rem.length|0]; chosen.push(p); used[p]=1; continue; }
      let r=Math.random()*tot, acc=0, pick=-1;
      for(let x=1;x<=n;x++){ if(used[x]) continue; acc+=W0[x]; if(acc>=r){pick=x;break;} }
      if(pick<0){ for(let x=n;x>=1;x--) if(!used[x]&&W0[x]>0){ pick=x; break; } }
      if(pick<0) break;
      chosen.push(pick); used[pick]=1;
    }
    return chosen.sort((a,b)=>a-b);
  }
  function genPair(){
    const s=[...locked], used=new Set(s);
    if(!s.length){ let tot=0,w=new Array(n+1).fill(0);
      for(let x=1;x<=n;x++){ if(exclSet.has(x)) continue; w[x]=(freq[x]?freq[x].count:1); tot+=w[x]; }
      let r=Math.random()*tot,acc=0,pk=1; for(let x=1;x<=n;x++){acc+=w[x];if(acc>=r){pk=x;break;}}
      s.push(pk); used.add(pk); }
    while(s.length<6){
      const cand=[];
      for(let x=1;x<=n;x++){ if(used.has(x)||exclSet.has(x)) continue;
        let v=0; for(const y of s) v+=cooc[x-1][y-1]; cand.push([x,v]); }
      if(!cand.length) break;
      cand.sort((a,b)=>b[1]-a[1]);
      const top=cand.slice(0,3), pk=top[Math.random()*top.length|0][0];
      s.push(pk); used.add(pk);
    }
    return s.sort((a,b)=>a-b);
  }
  const rawGen = mode==='pairs'? genPair : sampleWeighted;
  // payout: bốc ở mức BỘ (giữ bộ ít người đánh nhất) + loại thẳng dạng đụng hàng nặng.
  const gen = mode==='payout' ? (()=>popTournament(rawGen)) : rawGen;
  const crowded = mode==='payout' ? isCrowdedSet : (()=>false);

  // Bội số: ngân sách phải co giãn theo count, nếu không xin 1000 bộ sẽ chỉ ra vài chục.
  const bulk = count > 20;
  const poolTarget = bulk ? Math.ceil(count*1.4) : count*10;
  const tries1 = Math.max(9000, count*40), tries2 = Math.max(4000, count*20);
  // Chống "cày không ra": chế độ pairs bốc tham lam nên số bộ DUY NHẤT có hạn
  // (~1.6k với 6/55); hết bộ mới thì thoát sớm thay vì quay vòng vô ích.
  const STALL_MAX = 4000;

  const pool=[], seen=new Set(); let relaxed=false, stall=0;
  for(let t=0;t<tries1 && pool.length<poolTarget && stall<STALL_MAX; t++){
    const s=gen(); if(!s||s.length<6){ stall++; continue; }
    const key=s.join(','); if(seen.has(key)){ stall++; continue; }
    if(crowded(s)){ stall++; continue; }
    const m=score(s); if(!passes(m)){ stall++; continue; }
    seen.add(key); pool.push(m); stall=0;
  }
  if(pool.length<count){ relaxed=true; stall=0;
    for(let t=0;t<tries2 && pool.length<count && stall<STALL_MAX; t++){
      const s=gen(); if(!s||s.length<6){ stall++; continue; }
      const key=s.join(',');
      if(seen.has(key)){ stall++; continue; }
      seen.add(key); pool.push(score(s)); stall=0;
    }
  }
  pool.sort((a,b)=>b.score-a.score);
  let out;
  if(bulk){
    // Với bội số, ràng buộc "khác nhau ≥2 số" là O(n²) và gần như bất khả thi —
    // chỉ cần các bộ không trùng lặp (đã lọc bằng `seen`).
    out = pool.slice(0, count);
  }else{
    out=[];
    for(const c of pool){ if(out.every(o=>overlap(o.set,c.set)<=4)){ out.push(c); if(out.length>=count) break; } }
    for(let i=0;out.length<count&&i<pool.length;i++) if(!out.includes(pool[i])) out.push(pool[i]);
    out = out.slice(0,count);
  }
  return {out, relaxed, mode, locked, excl:[...exclSet], bulk, asked:count};
}

const MODE_NAME = {balanced:'Cân đối',hot:'Thiên số nóng',gan:'Thiên số gan',
  pairs:'Theo cặp hay đi cùng',payout:'Tránh số đông'};
function renderSuggest(){
  const ex = DATA[current].extra;
  const panel = document.getElementById('sugPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('sugCount').value = sugInputs().count;   // ghim lại 1–5000
  const res = sugEngine();
  const SHOW = 50;                       // bội số: chỉ vẽ chip 50 bộ đầu cho nhẹ DOM
  let html='';
  res.out.slice(0,SHOW).forEach((c,i)=>{
    html += '<div class="setrow"><span class="lbl">#'+(i+1)+'</span>'+
      c.set.map(x=>'<span class="chip'+(res.locked.includes(x)?' lock':'')+'">'+x+'</span>').join('')+
      '<span class="setmeta">điểm <b>'+c.score+'</b> · tổng '+c.sum+' · '+c.odd+' lẻ · '+
      c.low+' thấp · '+c.cons+' liên tiếp · lặp '+c.rep+
      ' · phổ biến <b>'+popOfSet(c.set).toFixed(2)+'</b></span></div>';
  });
  if(res.out.length>SHOW)
    html += '<div class="pc">… và '+(res.out.length-SHOW).toLocaleString('vi')+
      ' bộ nữa — xem đủ ở ô "Xem &amp; chép toàn bộ bội số" phía trên.</div>';
  document.getElementById('suggestList').innerHTML = html ||
    '<div class="pc">Không tạo được bộ nào với khoá/loại số hiện tại.</div>';

  // Ô văn bản + thống kê chỉ có ý nghĩa ở chế độ bội số.
  const wrap = document.getElementById('sugSetsWrap');
  const ta = document.getElementById('sugSets');
  const stat = document.getElementById('sugStat');
  if(res.bulk){
    wrap.style.display='';
    ta.value = res.out.map(c=>c.set.join(' ')).join('\n');
    const uniq = new Set(res.out.map(c=>c.set.join(','))).size;
    const pops = res.out.map(c=>popOfSet(c.set));
    const avgPop = pops.reduce((a,b)=>a+b,0)/(pops.length||1);
    const avgScore = res.out.reduce((a,c)=>a+c.score,0)/(res.out.length||1);
    stat.innerHTML = 'Đã tạo <b>'+res.out.length.toLocaleString('vi')+'</b> bộ'+
      (uniq<res.out.length ? ' (chỉ <b>'+uniq.toLocaleString('vi')+'</b> bộ khác nhau — '+
        'chế độ này không bốc thêm được bộ mới)' : ' · tất cả khác nhau')+
      ' · điểm điển hình TB <b>'+avgScore.toFixed(0)+'</b>'+
      ' · độ phổ biến TB <b>'+avgPop.toFixed(2)+'</b> (thấp = ít người đánh trùng)'+
      ' · tổng tiền <b>'+(res.out.length*10000).toLocaleString('vi')+'đ</b> nếu mua hết.';
  }else{
    wrap.style.display='none'; ta.value=''; stat.innerHTML='';
  }

  document.getElementById('sugMsg').textContent = res.relaxed
    ? '⚠ Không đủ bộ qua ràng buộc (khoá số? số bộ quá lớn?) — đã nới lỏng để đủ '
      +res.out.length+'/'+res.asked+' bộ.' : '';

  document.getElementById('sugNote').innerHTML =
    '<div class="notet">Cách chấm điểm &amp; chế độ</div>'+
    '<b>Điểm điển hình</b> = mức bộ số khớp với thói quen lịch sử ở 5 mặt: '+
    'tổng, chẵn/lẻ, thấp/cao, số liên tiếp, số lặp kỳ trước (100 = giống nhất).'+
    '<div style="margin-top:6px">Bộ còn phải qua ràng buộc: tổng trong '+
    ex.sum.p10+'–'+ex.sum.p90+', 2–4 lẻ, 2–4 thấp, ≤1 cặp liên tiếp, trải ≥3 hàng chục, '+
    'mỗi vị trí x1–x6 trong dải lịch sử, lặp kỳ trước ≤2.</div>'+
    '<div style="margin-top:6px"><b>Chế độ '+MODE_NAME[res.mode]+':</b> '+
    ({balanced:'bốc đều, chỉ cần điển hình.',hot:'thiên số về nhiều.',
      gan:'thiên số lâu chưa về.',pairs:'ghép theo cặp hay đi cùng.',
      payout:'né số nhiều người đánh (ngày sinh 1–31, tháng 1–12, đuôi 8/6), '+
             'ưu tiên đuôi 0/9 và số &gt;31; loại bộ toàn ngày sinh, cấp số cộng, '+
             'cùng một hàng chục. Mỗi lần bốc '+POP_TOURNAMENT+' bộ rồi giữ bộ ít người đánh nhất.'
    }[res.mode])+'</div>'+
    (res.mode==='payout'
      ? '<div style="margin-top:6px"><b>Độ phổ biến</b> = ước lượng mức đông người cùng đánh '+
        '(1,0 ≈ trung bình; thấp hơn là tốt). Dựa trên nghiên cứu hành vi chọn số; phần '+
        'đuôi 8/6/4 là <b>giả định thói quen VN</b>, Vietlott không công bố dữ liệu vé bán '+
        'ra nên không kiểm chứng được.</div>' : '')+
    '<span class="wl">⚠ Không chế độ nào tăng xác suất trúng. "Tránh số đông" KHÔNG giúp dễ '+
    'trúng hơn — chỉ giảm khả năng phải chia giải với người khác khi đã trúng.</span>';
}

// --- So sánh 5 giải thuật với 1 kết quả (mỗi lần Chạy tạo mới 1000 bộ/giải thuật) ---
const BT_MODES = [['balanced','Cân đối'],['hot','Thiên số nóng'],['gan','Thiên số gan'],
  ['pairs','Theo cặp hay đi cùng'],['payout','Tránh số đông']];

function btBuildGen(){
  const g = DATA[current], ex = g.extra, n = ex.n;
  const cooc = ex.cooc;
  const freq = {}; (g.frequency||[]).forEach(f=>freq[f.number]=f);

  function wArr(mode){
    const w = new Float64Array(n+1);
    for(let x=1;x<=n;x++) w[x] =
      mode==='hot'    ? (freq[x]?freq[x].count:0)+1 :
      mode==='gan'    ? (freq[x]?freq[x].gap:0)+1 :
      mode==='payout' ? Math.pow(1/popOfNumber(x), POP_WEIGHT_EXP) : 1;
    return w;
  }
  const W = {balanced:wArr('balanced'), hot:wArr('hot'), gan:wArr('gan'), payout:wArr('payout')};
  const pairSeed = (()=>{ const w=new Float64Array(n+1);
    for(let x=1;x<=n;x++) w[x] = freq[x]?freq[x].count:1; return w; })();

  // Bốc 6 số theo trọng số của giải thuật (KHÔNG lọc "điển hình" — đây là backtest,
  // lọc theo kỳ mới nhất sẽ chặn mọi bộ trùng >2 số với kết quả và làm hỏng thống kê).
  function sampleWeighted(w){
    const used=new Uint8Array(n+1), chosen=[];
    for(let c=0;c<6;c++){
      let tot=0; for(let x=1;x<=n;x++) if(!used[x]) tot+=w[x];
      let r=Math.random()*tot, acc=0, pick=1;
      for(let x=1;x<=n;x++){ if(used[x]) continue; acc+=w[x]; if(acc>=r){pick=x;break;} }
      used[pick]=1; chosen.push(pick);
    }
    return chosen.sort((a,b)=>a-b);
  }
  function genPair(){
    const used=new Uint8Array(n+1), s=[];
    let tot=0; for(let x=1;x<=n;x++) tot+=pairSeed[x];
    let r=Math.random()*tot, acc=0, pk=1;
    for(let x=1;x<=n;x++){ acc+=pairSeed[x]; if(acc>=r){pk=x;break;} }
    s.push(pk); used[pk]=1;
    while(s.length<6){
      const cand=[];
      for(let x=1;x<=n;x++){ if(used[x]) continue;
        let v=0; for(const y of s) v+=cooc[x-1][y-1]; cand.push([x,v]); }
      cand.sort((a,b)=>b[1]-a[1]);
      const top=cand.slice(0,3), pick=top[Math.random()*top.length|0][0];
      s.push(pick); used[pick]=1;
    }
    return s.sort((a,b)=>a-b);
  }
  // payout dùng cùng mô hình độ phổ biến như "Bộ số gợi ý": bốc ở mức BỘ rồi loại
  // dạng đụng hàng nặng — để bội số backtest khớp với bội số đem đi chơi thật.
  const gen = mode => {
    if(mode === 'payout'){
      let s, guard = 0;
      do { s = popTournament(()=>sampleWeighted(W.payout)); } while(isCrowdedSet(s) && ++guard < 20);
      return s;
    }
    return mode==='pairs' ? genPair() : sampleWeighted(W[mode]);
  };
  return {n, gen};
}

// --- Lưu / nạp bội số đã tạo (localStorage — sống qua F5 & mở lại trình duyệt) ---
let btSaved = null;                    // batch trong phiên: {game,n,count,created,sets{mode:[[..],..]}}
function btKey(){ return 'vietlott_bt_' + DATA[current].game_type; }
function btWidth(n){ return n < 10 ? 1 : n < 100 ? 2 : 3; }
function encSets(arr, w){ let s=''; for(const set of arr) for(const x of set)
  s += String(x).padStart(w,'0'); return s; }
function decSets(str, w){ const step=6*w, out=[];
  for(let i=0;i+step<=str.length;i+=step){ const set=[];
    for(let j=0;j<step;j+=w) set.push(parseInt(str.substr(i+j,w),10)); out.push(set); }
  return out; }
function btSave(batch){
  try{
    const w=btWidth(batch.n), enc={v:1,game:batch.game,n:batch.n,count:batch.count,
      created:batch.created,sets:{}};
    for(const k in batch.sets) enc.sets[k]=encSets(batch.sets[k],w);
    localStorage.setItem(btKey(), JSON.stringify(enc));
    return true;
  }catch(e){ return false; }
}
function btLoad(){
  try{
    const raw=localStorage.getItem(btKey()); if(!raw) return null;
    const enc=JSON.parse(raw), w=btWidth(enc.n), sets={};
    for(const k in enc.sets) sets[k]=decSets(enc.sets[k],w);
    return {game:enc.game,n:enc.n,count:enc.count,created:enc.created,sets};
  }catch(e){ return null; }
}
function btNow(){ const d=new Date(), p=x=>String(x).padStart(2,'0');
  return p(d.getDate())+'/'+p(d.getMonth()+1)+'/'+d.getFullYear()+' '+p(d.getHours())+':'+p(d.getMinutes()); }

function fillSetsTextarea(batch){
  const ta=document.getElementById('btSets'); if(!ta) return;
  const PREV=200;                      // xem trước tối đa 200 bộ/giải thuật cho nhẹ
  let txt='';
  BT_MODES.forEach(([k,nm])=>{
    const arr=batch.sets[k]||[];
    txt += '== '+nm+' ('+arr.length.toLocaleString('vi')+' bộ) ==\n';
    arr.slice(0,PREV).forEach(s=> txt += s.join(' ')+'\n');
    if(arr.length>PREV) txt += '… và '+(arr.length-PREV).toLocaleString('vi')+' bộ nữa (đã lưu đủ)\n';
    txt += '\n';
  });
  ta.value = txt.trimEnd();
}

// NÚT TẠO: sinh count bộ/giải thuật, LƯU (ghi đè bộ cũ), hiện ra ô văn bản.
function btGenerate(){
  const ex = DATA[current].extra; if(!ex) return;
  const msg = document.getElementById('btMsg');
  let count = parseInt(document.getElementById('btCount').value,10) || 1000;
  count = Math.max(50, Math.min(count, 20000));           // giới hạn để lưu vừa localStorage
  document.getElementById('btCount').value = count;
  const btn = document.getElementById('btGen'), old = btn.textContent;
  btn.disabled=true; btn.textContent='Đang tạo…';
  msg.className='pc warn'; msg.textContent='';
  document.getElementById('btBody').innerHTML='';         // kết quả so sánh cũ không còn đúng
  setTimeout(()=>{
    const eng = btBuildGen(), sets={};
    BT_MODES.forEach(([k])=>{ const a=new Array(count);
      for(let i=0;i<count;i++) a[i]=eng.gen(k); sets[k]=a; });
    const batch = {game:DATA[current].game_type, n:ex.n, count, created:btNow(), sets};
    btSaved = batch;
    const ok = btSave(batch);
    fillSetsTextarea(batch);
    document.getElementById('btStatus').innerHTML =
      '✅ Đã tạo &amp; ' + (ok
        ? 'lưu <b>'+count.toLocaleString('vi')+'</b> bộ/giải thuật lúc <b>'+batch.created+
          '</b> (mở lại trang vẫn còn) — đã xoá bộ cũ, thay bằng bộ mới.'
        : 'giữ <b>'+count.toLocaleString('vi')+'</b> bộ/giải thuật trong PHIÊN này (không lưu được vào trình duyệt).') +
      ' Giờ nhập kết quả trúng rồi bấm <b>So sánh</b>.';
    msg.textContent = ok ? '' : '⚠ Không lưu lâu dài được (trình duyệt chặn localStorage ở file://) — đóng trang sẽ mất.';
    btn.disabled=false; btn.textContent=old;
  }, 20);
}

// Thống kê mức trùng của MỘT tập bộ ĐÃ LƯU với kết quả win.
function btStatsFromSets(mode, sets, win){
  const dist=[0,0,0,0,0,0,0], numHit={}, wins={3:[],4:[],5:[],6:[]};
  let sumMatched=0, best=0;
  for(const s of sets){
    let c=0; for(const x of s) if(win.has(x)){ c++; numHit[x]=(numHit[x]||0)+1; }
    dist[c]++; sumMatched+=c; if(c>best) best=c;
    if(c>=3) wins[c].push(s);
  }
  const made=sets.length;
  return {mode, made, dist, best, numHit, wins,
    avg: made ? sumMatched/made : 0,
    hit3: dist[3]+dist[4]+dist[5]+dist[6],
    hit4: dist[4]+dist[5]+dist[6],
    hit5: dist[5]+dist[6], hit6: dist[6]};
}

// NÚT SO SÁNH: đối chiếu kết quả với bội số ĐÃ LƯU trước đó.
function btCompare(){
  const ex = DATA[current].extra; if(!ex) return;
  const msg = document.getElementById('btMsg');
  const target = parseTicket(document.getElementById('btInput').value, ex.n);
  if(!target){ msg.className='pc warn';
    msg.textContent='Nhập đúng 6 số khác nhau trong khoảng 1–'+ex.n+'.'; return; }
  const batch = btSaved || btLoad();
  if(!batch || !batch.sets){ msg.className='pc warn';
    msg.textContent='Chưa có bội số đã lưu — bấm "Tạo & lưu" trước.'; return; }
  if(batch.game !== DATA[current].game_type){ msg.className='pc warn';
    msg.textContent='Bội số đã lưu thuộc game khác ('+batch.game+') — bấm "Tạo & lưu" lại.'; return; }
  msg.textContent='';
  const win = new Set(target);
  const stats = BT_MODES.map(([k])=>btStatsFromSets(k, batch.sets[k]||[], win));
  renderBtResult(target, stats, batch.count, batch.created);
}

function renderBtResult(target, stats, count, created){
  const ex = DATA[current].extra, n = ex.n;
  const baseline = Math.round(36/n*1000)/1000;
  const bestAvg = Math.max(...stats.map(s=>s.avg));
  const nameOf = {}; BT_MODES.forEach(([k,nm])=>nameOf[k]=nm);

  let cols='';
  stats.forEach(s=>{
    const lead = s.avg===bestAvg;
    const rates = target.map(x=>({x, r: s.made ? (s.numHit[x]||0)/s.made*100 : 0}))
                        .sort((a,b)=>b.r-a.r);
    let mini='';
    rates.forEach(o=>{ mini +=
      '<div class="hl"><span class="num">'+o.x+'</span>'+
      '<span class="bar"><span style="width:'+Math.round(o.r)+'%"></span></span>'+
      '<span class="pct">'+o.r.toFixed(0)+'%</span></div>'; });
    cols += '<div class="btcol'+(lead?' lead':'')+'">'+
      '<div class="nm"><span>'+esc(nameOf[s.mode])+'</span>'+(lead?'<span class="star">★</span>':'')+'</div>'+
      '<div class="k">TB trùng / vé</div>'+
      '<div class="big">'+s.avg.toFixed(3)+'</div>'+
      '<div class="k" style="margin-top:4px">≥3: <b>'+s.hit3+'</b> · ≥4: <b>'+s.hit4+
        '</b> · ≥5: <b>'+s.hit5+'</b> · 6: <b>'+s.hit6+'</b></div>'+
      '<div class="k">Tốt nhất <b>'+s.best+'</b> số · '+s.made.toLocaleString('vi')+' bộ</div>'+
      '<div class="mini"><div class="k" style="margin-bottom:4px">Số KQ có trong bộ (tỉ lệ)</div>'+mini+'</div>'+
    '</div>';
  });

  // Kiểu so sánh 2: liệt kê các BỘ TRÚNG (3/4/5/6 số) của từng giải thuật.
  const win = new Set(target);
  const WCAP = 15;
  let winHtml='';
  stats.forEach(s=>{
    let body='', any=false;
    [6,5,4,3].forEach(l=>{
      const arr=s.wins[l]; if(!arr.length) return; any=true;
      let sets='';
      arr.slice(0,WCAP).forEach(set=>{ sets+='<span class="wset">'+
        set.map(x=>'<span class="chip'+(win.has(x)?' win':'')+'">'+x+'</span>').join('')+'</span>'; });
      if(arr.length>WCAP) sets+='<span class="wmore">+'+(arr.length-WCAP)+' bộ nữa</span>';
      body+='<div class="wlevel">Trúng '+l+' số ('+arr.length+' bộ):</div><div class="wsets">'+sets+'</div>';
    });
    if(!any) body='<div class="wlevel">Không có bộ nào trúng ≥3 số.</div>';
    winHtml += '<div class="btwin"><div class="wtitle">'+esc(nameOf[s.mode])+
      ' <span class="wcount">6:'+s.wins[6].length+' · 5:'+s.wins[5].length+
      ' · 4:'+s.wins[4].length+' · 3:'+s.wins[3].length+'</span></div>'+body+'</div>';
  });

  const isLatest = (ex.latest||[]).join(',') === target.join(',');
  const latestNote = isLatest
    ? '<div class="banner" style="margin-top:10px">ℹ Bạn đang đối chiếu với <b>chính kỳ mới nhất</b> — thống kê (nóng/gan/cặp) đã bao gồm kỳ này, nên <b>số nóng &amp; cặp</b> trùng cao hơn còn <b>số gan gần như không trúng</b> (các số vừa ra thì không còn "gan"). Muốn so công bằng, hãy nhập kết quả một kỳ khác.</div>'
    : '';

  document.getElementById('btStatus').innerHTML =
    'Đối chiếu kết quả <b>'+target.join(' ')+'</b> với <b>'+count.toLocaleString('vi')+
    '</b> bộ/giải thuật đã lưu'+(created?' lúc <b>'+created+'</b>':'')+
    ' · ngẫu nhiên lý thuyết TB <b>'+baseline+'</b> số trùng/vé.';
  document.getElementById('btBody').innerHTML =
    '<div class="btgrid">'+cols+'</div>'+ latestNote +
    '<div class="pc" style="margin-top:10px">Mỗi cột là 1 giải thuật: <b>TB trùng/vé</b> = trung bình số trùng với kết quả; '+
    '<b>≥3…6</b> = số bộ đạt mức đó; hàng dưới là tỉ lệ mỗi số kết quả xuất hiện trong '+count.toLocaleString('vi')+' bộ. '+
    '★ = TB cao nhất. So sánh dùng <b>đúng bộ đã lưu</b> nên kết quả cố định; bấm <b>Tạo &amp; lưu</b> để bốc bộ mới. Chênh lệch giữa các giải thuật hầu như chỉ là nhiễu.</div>'+
    '<details open style="margin-top:12px"><summary>Bộ số trúng của từng giải thuật (nhóm theo 3/4/5/6 số · số trúng tô xanh)</summary>'+
    winHtml+'</details>';
}

function renderBacktest(){
  const ex = DATA[current].extra;
  const panel = document.getElementById('btPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('btInput').placeholder = 'Nhập 6 số (1–'+ex.n+')';
  document.getElementById('btMsg').textContent='';
  document.getElementById('btBody').innerHTML='';
  const batch = btLoad();
  btSaved = batch;
  const status = document.getElementById('btStatus');
  const ta = document.getElementById('btSets');
  if(batch && batch.sets){
    fillSetsTextarea(batch);
    status.innerHTML = '💾 Đang có <b>'+(batch.count||0).toLocaleString('vi')+
      '</b> bộ/giải thuật đã lưu lúc <b>'+(batch.created||'?')+
      '</b>. Nhập kết quả trúng rồi bấm <b>So sánh</b>. (Bấm <b>Tạo &amp; lưu</b> để thay bằng bộ mới.)';
  } else {
    if(ta) ta.value='';
    status.innerHTML = 'Chưa có bội số nào được lưu. Bấm <b>Tạo &amp; lưu</b> để tạo &amp; lưu bội số cho từng giải thuật '+
      '(lần sau mở lại vẫn còn để So sánh).';
  }
}

// --- Xếp hạng giải thuật trên KẾT QUẢ THẬT (đọc từ DB, do crawl.py chấm) ---
function renderTrack(){
  const panel = document.getElementById('trackPanel');
  if(!panel) return;
  const tr = DATA[current].track;
  if(!tr){ panel.style.display='none'; return; }
  panel.style.display='';
  const status = document.getElementById('trackStatus');
  const body   = document.getElementById('trackBody');

  if(!tr.scored_batches){
    status.innerHTML = tr.pending
      ? 'Đã chốt sẵn <b>'+tr.pending+'</b> kỳ bộ số, đang chờ kết quả. Khi kỳ tiếp theo về '+
        'và bạn chạy <b>cập nhật lịch sử</b>, hệ thống tự chấm rồi bảng xếp hạng hiện ra đây.'
      : 'Chưa có dữ liệu. Lần chạy <b>cập nhật lịch sử</b> (crawl.py) tới sẽ tự chốt '+
        '1000 bộ/giải thuật cho kỳ sắp về, rồi tự chấm khi có kết quả.';
    body.innerHTML='';
    return;
  }

  // Cột mỗi giải thuật — tr.methods đã xếp sẵn theo TB trùng giảm dần.
  const withData = tr.methods.filter(m=>m.sets);
  const bestAvg  = Math.max.apply(null, withData.map(m=>m.avg));
  const bestWins = Math.max.apply(null, withData.map(m=>m.wins));
  let cols='';
  tr.methods.forEach(m=>{
    if(!m.sets){
      cols += '<div class="btcol"><div class="nm"><span>'+esc(m.name)+'</span></div>'+
        '<div class="k" style="margin-top:8px">chưa có dữ liệu</div></div>';
      return;
    }
    const lead = m.avg === bestAvg;
    cols += '<div class="btcol'+(lead?' lead':'')+'">'+
      '<div class="nm"><span>'+esc(m.name)+'</span>'+(lead?'<span class="star">★</span>':'')+'</div>'+
      '<div class="k">TB trùng / vé</div>'+
      '<div class="big">'+m.avg.toFixed(3)+'</div>'+
      '<div class="k" style="margin-top:4px">Thắng kỳ: <b>'+m.wins+
        '</b>/'+tr.scored_batches+(m.wins===bestWins&&bestWins>0?' 🏆':'')+'</div>'+
      '<div class="k">≥3: <b>'+m.hit3+'</b> · ≥4: <b>'+m.hit4+
        '</b> · ≥5: <b>'+m.hit5+'</b> · 6: <b>'+m.hit6+'</b></div>'+
      '<div class="k">Tốt nhất <b>'+m.best+'</b> số · '+m.sets.toLocaleString('vi')+' vé</div>'+
      (m.t===undefined ? '' :
        '<div class="k" style="margin-top:6px;border-top:1px solid var(--border);padding-top:5px">'+
        'Dao động giữa các kỳ <b>±'+m.sd.toFixed(3)+'</b><br>t = <b>'+m.t.toFixed(2)+'</b> · '+
        (m.beats_random
          ? '<span style="color:var(--good)">lệch khỏi ngẫu nhiên</span>'
          : '<span style="color:var(--muted)">không khác ngẫu nhiên</span>')+'</div>')+
    '</div>';
  });

  // Phân bố số trùng 0..6: so 5 chế độ với nhau VÀ với tỉ lệ lý thuyết. Đây là
  // bảng trả lời thẳng "có chế độ nào lệch khỏi ngẫu nhiên không".
  let distTbl='';
  if(withData.length && withData[0].dist){
    let head='<tr><th>Trùng</th><th>Lý thuyết</th>';
    withData.forEach(m=> head += '<th>'+esc(m.name)+'</th>');
    head += '</tr>';
    let rows='';
    for(let k=6;k>=0;k--){
      const th = tr.baseline.pct ? tr.baseline.pct[k] : null;
      rows += '<tr><td><b>'+k+' số</b></td><td style="color:var(--muted)">'+
        (th===null?'—':(th<0.01? th.toFixed(4) : th.toFixed(2))+'%')+'</td>';
      withData.forEach(m=>{
        const c = m.dist[k], pct = m.sets ? c/m.sets*100 : 0;
        // lệch so với lý thuyết: chỉ tô khi mức đó đủ vé để có ý nghĩa
        const dev = (th!==null && th>0 && c>=20) ? (pct-th)/th : 0;
        const col = dev>0.15 ? 'var(--good)' : dev<-0.15 ? 'var(--warn)' : '';
        rows += '<td'+(col?' style="color:'+col+'"':'')+'>'+
          c.toLocaleString('vi')+
          '<div style="color:var(--muted);font-size:11px">'+
          (pct<0.01 && c>0 ? pct.toFixed(4) : pct.toFixed(2))+'%</div></td>';
      });
      rows += '</tr>';
    }
    distTbl = '<details open style="margin-top:12px"><summary>Phân bố số trùng của '+
      (tr.scored_batches*1).toLocaleString('vi')+' kỳ (số vé đạt từng mức · so với lý thuyết)</summary>'+
      '<table><thead>'+head+'</thead><tbody>'+rows+'</tbody></table>'+
      '<div class="pc" style="margin-top:6px">Cột <b>Lý thuyết</b> là tỉ lệ của vé bốc '+
      'ngẫu nhiên hoàn toàn. Nếu một chế độ thật sự "đoán" được thì cột của nó phải cao '+
      'hơn hẳn ở các mức 3–6 số một cách bền vững qua nhiều kỳ.</div></details>';
  }

  // Lịch sử từng kỳ: TB trùng của mỗi giải thuật, tô đậm giải thuật thắng kỳ đó.
  let hist='';
  if(tr.recent && tr.recent.length){
    const keys = tr.methods.map(m=>m.key), names = {};
    tr.methods.forEach(m=>names[m.key]=m.name);
    let head = '<tr><th>Kỳ</th><th>Kết quả</th>';
    keys.forEach(k=> head += '<th>'+esc(names[k])+'</th>');
    head += '</tr>';
    let rows='';
    tr.recent.forEach(r=>{
      const vals = keys.map(k=> (r.per_method && r.per_method[k]!=null) ? r.per_method[k] : null);
      const top  = Math.max.apply(null, vals.filter(v=>v!=null));
      rows += '<tr><td>'+esc(r.period||'—')+'<div style="color:var(--muted);font-size:11px">'+
        esc(r.date||'')+'</div></td><td>'+(r.result||[]).join(' ')+'</td>'+
        vals.map(v=> v==null ? '<td>—</td>'
          : '<td'+(v===top?' style="font-weight:650;color:var(--good)"':'')+'>'+
            v.toFixed(3)+'</td>').join('')+'</tr>';
    });
    hist = '<details style="margin-top:12px"><summary>TB trùng từng kỳ — '+
      tr.recent.length+' kỳ gần nhất (giải thuật thắng kỳ tô xanh)</summary>'+
      '<table><thead>'+head+'</thead><tbody>'+rows+'</tbody></table></details>';
  }

  // Kết luận thẳng: có chế độ nào thật sự vượt ngẫu nhiên không.
  const beat = withData.filter(m=>m.beats_random);
  const verdict = !withData.length || withData[0].t===undefined ? ''
    : beat.length
      ? '<div class="banner" style="margin-top:10px">⚑ <b>'+
        beat.map(m=>esc(m.name)).join(', ')+'</b> đang lệch khỏi ngẫu nhiên (t vượt 2,58). '+
        'Đáng xem tiếp — nhưng hãy chạy thêm kỳ trước khi tin, và kiểm tra xem có lỗi '+
        'rò rỉ kết quả trong cách sinh số không.</div>'
      : '<div class="banner" style="margin-top:10px">✓ Sau <b>'+tr.scored_batches+
        '</b> kỳ: <b>không chế độ nào</b> vượt ngẫu nhiên. Chế độ dẫn đầu bảng chỉ đang '+
        'gặp may — chênh lệch nằm trong sai số. Đúng như lý thuyết: kỳ vọng mỗi vé luôn '+
        'là 6×6/'+DATA[current].extra.n+' = <b>'+tr.baseline.avg+'</b> số trùng, '+
        '<b>bất kể chọn số nào</b>.</div>';

  status.innerHTML = 'Đã chấm <b>'+tr.scored_batches+'</b> kỳ thật'+
    (tr.pending?' · đang chờ <b>'+tr.pending+'</b> kỳ':'')+
    ' · ngẫu nhiên lý thuyết TB <b>'+tr.baseline.avg+'</b> số trùng/vé.';
  body.innerHTML = '<div class="btgrid">'+cols+'</div>'+ verdict + distTbl + hist +
    '<div class="pc" style="margin-top:10px">Khác với bảng ở trên (bộ số lưu trong trình duyệt), '+
    'bảng này dùng <b>bộ số đã chốt trong DB trước khi kỳ mới về</b> nên không thể "nhìn trước kết quả". '+
    '<b>TB trùng/vé</b> = trung bình số trùng trên toàn bộ vé đã chấm; <b>Thắng kỳ</b> = số kỳ giải thuật đó '+
    'có TB cao nhất (hoà thì chia đôi). '+
    '<span class="wl">⚠ Cần vài chục kỳ chênh lệch mới có ý nghĩa — ít kỳ thì thứ hạng chủ yếu là nhiễu, '+
    'và không giải thuật nào làm tăng xác suất trúng.</span></div>';
}

function renderAlgos(){
  if(!document.getElementById('algoPanel')) return;
  const algos = DATA[current].algos;
  const panel = document.getElementById('algoPanel');
  if(!algos){ panel.style.display='none'; return; }
  panel.style.display='';
  let html='', grp=null;
  for(const a of algos){
    if(a.group !== grp){ grp=a.group; html += '<div class="algogrp">'+esc(grp)+'</div>'; }
    html += '<div class="algorow"><div class="algoinfo"><b>'+esc(a.name)+'</b>'+
      '<span class="note">'+esc(a.note)+'</span></div>'+
      '<div class="chips">'+a.pick.map(x=>'<span class="chip">'+x+'</span>').join('')+'</div></div>';
  }
  document.getElementById('algoList').innerHTML = html;
}

// --- mô phỏng: cần bao nhiêu vé để trúng 3/4/5/6 số --------------------------
function nCr(n,k){ if(k<0||k>n) return 0; k=Math.min(k,n-k); let r=1;
  for(let i=0;i<k;i++) r = r*(n-i)/(i+1); return Math.round(r); }
function expTries(n,m){ const tot=nCr(n,6); if(!tot) return Infinity;
  let p=0; for(let j=m;j<=6;j++) p += nCr(6,j)*nCr(n-6,6-j)/tot;
  return p>0 ? Math.round(1/p) : Infinity; }
const fmtN = x => (x===Infinity ? '∞' : Math.round(x).toLocaleString('vi'));

function parseTicket(str,n){
  const parts = String(str).split(/[\s,;.]+/).filter(x=>x.length);
  if(parts.length !== 6) return null;
  const arr=[];
  for(const p of parts){ const v=parseInt(p,10);
    if(!Number.isInteger(v) || v<1 || v>n || arr.includes(v)) return null;
    arr.push(v); }
  return arr.sort((a,b)=>a-b);
}
function buildSimTable(n, hits){
  const rows = [3,4,5,6].map(m=>{
    let cell;
    if(hits && hits[m]!==null) cell = '<span class="hit">'+fmtN(hits[m])+' bộ</span>';
    else if(simRunning) cell = '<span class="wait">đang tìm…</span>';
    else cell = '<span class="wait">—</span>';
    return '<tr><td>Trúng '+m+' số</td><td>'+cell+'</td><td>'+fmtN(expTries(n,m))+'</td></tr>';
  }).join('');
  document.getElementById('simTable').innerHTML =
    '<thead><tr><th>Mức</th><th>Mô phỏng (số bộ đã tạo)</th>'+
    '<th>Kỳ vọng lý thuyết</th></tr></thead><tbody>'+rows+'</tbody>';
}
function updateSimUI(){
  document.getElementById('simCount').textContent =
    'Đã tạo: '+simAttempts.toLocaleString('vi')+' bộ';
  buildSimTable(simTarget.n, simHits);
}
function stopSim(){
  simRunning=false;
  const r=document.getElementById('simRun'), s=document.getElementById('simStop');
  if(r) r.disabled=false; if(s) s.disabled=true;
}
function finishSim(done){
  stopSim();
  const msg=document.getElementById('simMsg');
  msg.className = 'pc ' + (done ? 'good' : 'warn');
  msg.textContent = done
    ? '✓ Đã trúng đủ 3–4–5–6 số sau '+simAttempts.toLocaleString('vi')+' bộ.'
    : 'Dừng ở '+simAttempts.toLocaleString('vi')+' bộ — mức chưa đạt xem cột kỳ vọng.';
  updateSimUI();
}
function simStep(){
  if(!simRunning) return;
  const n=simTarget.n, tb=simTarget.bool, out=[0,0,0,0,0,0];
  let a=simAttempts; const end=Math.min(a+SIM_CHUNK, SIM_CAP);
  for(; a<end; a++){
    let c=0;
    while(c<6){ const v=1+(Math.random()*n|0);
      let dup=false; for(let j=0;j<c;j++){ if(out[j]===v){dup=true;break;} }
      if(!dup) out[c++]=v; }
    let cnt=0; for(let j=0;j<6;j++) if(tb[out[j]]) cnt++;
    if(cnt>=3){
      if(simHits[3]===null) simHits[3]=a+1;
      if(cnt>=4 && simHits[4]===null) simHits[4]=a+1;
      if(cnt>=5 && simHits[5]===null) simHits[5]=a+1;
      if(cnt>=6 && simHits[6]===null) simHits[6]=a+1;
    }
  }
  simAttempts=a;
  updateSimUI();
  if(simHits[6]!==null){ finishSim(true); return; }
  if(simAttempts>=SIM_CAP){ finishSim(false); return; }
  setTimeout(simStep, 0);
}
function startSim(){
  const ex = DATA[current].extra; if(!ex) return;
  const arr = parseTicket(document.getElementById('simInput').value, ex.n);
  const msg = document.getElementById('simMsg');
  if(!arr){ msg.className='pc warn';
    msg.textContent='Nhập đúng 6 số khác nhau trong khoảng 1–'+ex.n+'.'; return; }
  msg.textContent='';
  const bool = new Array(ex.n+1).fill(false); arr.forEach(v=>bool[v]=true);
  simTarget = {n:ex.n, arr, bool};
  simHits = {3:null,4:null,5:null,6:null};
  simAttempts = 0; simRunning = true;
  document.getElementById('simRun').disabled=true;
  document.getElementById('simStop').disabled=false;
  updateSimUI();
  setTimeout(simStep, 0);
}
function renderSim(){
  const ex = DATA[current].extra;
  const panel = document.getElementById('simPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  stopSim();
  simTarget = {n:ex.n}; simHits=null; simAttempts=0;
  const latest = (ex.latest||[]).join(' ');
  document.getElementById('simInput').value = latest;
  document.getElementById('simInput').placeholder = 'Nhập 6 số (1–'+ex.n+')';
  document.getElementById('simMsg').textContent='';
  document.getElementById('simCount').textContent='';
  buildSimTable(ex.n, null);
}

function renderFreq(){
  if(!document.getElementById('freqChart')) return;
  const g = DATA[current];
  let rows = g.frequency.map(f=>({
    label:f.number, value:f.count,
    sub:'chưa về '+f.gap+' kỳ · chuỗi dài nhất '+f.max_streak,
    number:f.number, gap:f.gap, cur:f.current_streak, mx:f.max_streak
  }));
  if(freqByCount) rows = [...rows].sort((a,b)=>b.value-a.value);
  columnChart(document.getElementById('freqChart'), rows,
    {W:920, H:300, labelEvery: freqByCount?4:5,
     tipTitle:d=>('số '+esc(d.label))});

  // table
  const t = ['<table><thead><tr><th>Số</th><th>Về</th><th>Chuỗi nay</th>'+
             '<th>Dài nhất</th><th>Chưa về</th></tr></thead><tbody>'];
  for(const r of [...g.frequency].sort((a,b)=>b.count-a.count)){
    t.push(`<tr><td>${r.number}</td><td>${r.count}</td><td>${r.current_streak}</td>`+
           `<td>${r.max_streak}</td><td>${r.gap}</td></tr>`);
  }
  t.push('</tbody></table>');
  document.getElementById('freqTable').innerHTML = t.join('');
}

// --- wiring ----------------------------------------------------------------
const tabs = document.getElementById('gameTabs');
DATA.forEach((g,i)=>{
  const b = document.createElement('button');
  b.className='btn'; b.type='button'; b.textContent=g.game_type;
  b.onclick=()=>{ current=i; render(); };
  tabs.appendChild(b);
});
const freqSortBtn = document.getElementById('freqSort');
if(freqSortBtn) freqSortBtn.onclick = (e)=>{
  freqByCount = !freqByCount;
  e.target.textContent = 'Sắp theo: ' + (freqByCount?'số lần':'số');
  renderFreq();
};
document.getElementById('genBtn').onclick = renderSuggest;
document.getElementById('sugMode').onchange = renderSuggest;
document.getElementById('sugCount').onchange = renderSuggest;
document.getElementById('simRun').onclick = startSim;
document.getElementById('simStop').onclick = ()=>{ finishSim(false); };
document.getElementById('btGen').onclick = btGenerate;
document.getElementById('btCmp').onclick = btCompare;
document.getElementById('btInput').addEventListener('keydown', e=>{
  if(e.key==='Enter') btCompare();
});
document.getElementById('themeBtn').onclick = ()=>{
  const cur = document.documentElement.getAttribute('data-theme');
  const isDark = cur ? cur==='dark'
    : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', isDark?'light':'dark');
  render();
};
window.addEventListener('resize', ()=>{ /* svg scales via CSS */ });
render();
</script>
</body>
</html>
"""


def render_html(
    all_data: list[dict],
    minimal: bool = False,
    source: str = "vietlott_data.db",
    title: str = "Thống kê Vietlott",
    nav: str = "",
) -> str:
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    html = HTML_TEMPLATE
    if minimal:
        # Trang rút gọn: bỏ khối "Phân bố theo vị trí" trở xuống.
        html = re.sub(
            r"<!--LOWER_START-->.*?<!--LOWER_END-->\s*", "", html, flags=re.S
        )
    return (
        html
        .replace("%%DATA%%", json.dumps(all_data, ensure_ascii=False))
        .replace("%%GENERATED%%", generated)
        .replace("%%SOURCE%%", source)
        .replace("%%TITLE%%", title)
        .replace("%%NAV%%", nav)
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sinh trang HTML thống kê Vietlott và mở trình duyệt. Mặc định tạo cả "
            "trang Power 6/55 (đầy đủ) và Mega 6/45 (rút gọn)."
        )
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Đường dẫn file SQLite (chỉ dùng khi --game là 1 loại hình cụ thể).",
    )
    parser.add_argument(
        "--game",
        default="all",
        help="power655, mega645, all (mặc định: cả hai trang).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Đường dẫn file HTML xuất ra (chỉ dùng khi --game là 1 loại hình).",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Bỏ mục 'Phân bố theo vị trí' trở xuống (mega645 vốn luôn rút gọn).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Chỉ tạo file, không tự mở trình duyệt.",
    )
    return parser


def build_page_specs(args: argparse.Namespace) -> list[dict]:
    """Danh sách trang cần sinh, dựa trên --game/--db/--out."""
    game = args.game or "all"
    specs: list[dict] = []

    if game in ("power655", "all"):
        db = args.db if (args.db and game == "power655") else str(DB_PATH)
        out = (
            args.out
            if (args.out and game == "power655")
            else str(DEFAULT_HTML_PATH)
        )
        specs.append({
            "db": db,
            "games": ["power655"],
            "out": out,
            "minimal": args.minimal,
            "source": Path(db).name,
            "title": "Thống kê Power 6/55",
            "nav": '<a class="btn" href="stats_mega645.html" '
                   'style="text-decoration:none">Mega 6/45 →</a>',
        })

    if game in ("mega645", "all"):
        db = args.db if (args.db and game == "mega645") else str(MEGA_DB_PATH)
        out = (
            args.out
            if (args.out and game == "mega645")
            else str(MEGA_HTML_PATH)
        )
        specs.append({
            "db": db,
            "games": ["mega645"],
            "out": out,
            # Mega luôn rút gọn (bỏ mục "Phân bố theo vị trí" trở xuống).
            "minimal": True,
            "source": Path(db).name,
            "title": "Thống kê Mega 6/45",
            "nav": '<a class="btn" href="stats.html" '
                   'style="text-decoration:none">← Power 6/55</a>',
        })

    return specs


def build_page_data(
    db_path: str, game_types: list[str], minimal: bool
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if minimal:
            return load_all_minimal(conn, db_path, game_types)
        return load_all(conn, db_path, game_types)
    finally:
        conn.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_arg_parser().parse_args()
    ensure_dirs()

    written: list[Path] = []
    for spec in build_page_specs(args):
        if not Path(spec["db"]).exists():
            print(f"⚠ Không thấy DB {spec['db']} — bỏ qua {spec['games']}.")
            continue
        data = build_page_data(spec["db"], spec["games"], spec["minimal"])
        if not data:
            print(
                f"⚠ Không có dữ liệu cho {spec['games']} trong {spec['db']} "
                f"— bỏ qua (có thể cần chạy number_stats.py)."
            )
            continue
        out = Path(spec["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            render_html(
                data,
                minimal=spec["minimal"],
                source=spec["source"],
                title=spec["title"],
                nav=spec["nav"],
            ),
            encoding="utf-8",
        )
        print(f"Đã tạo: {out}")
        written.append(out)

    if not written:
        print("Không tạo được trang nào. Kiểm tra dữ liệu / DB.")
        return 1

    if not args.no_open:
        for out in written:
            webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
