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
import sqlite3
import statistics
import sys
import webbrowser
from datetime import datetime
from itertools import combinations
from pathlib import Path

import gap_stats
from crawl import DB_PATH, EXPORT_DIR, ensure_dirs

DEFAULT_HTML_PATH = EXPORT_DIR / "stats.html"

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
        "overdue": overdue,
        "hot": hot,
        "pairs": [{"a": a, "b": b, "count": c} for (a, b), c in top_pairs],
        "exp_pair": round(exp_pair, 1),
    }


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
                "values": values_by_pos.get(pos, []),
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


HTML_TEMPLATE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thống kê Vietlott</title>
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
    <button class="btn" id="themeBtn" type="button">◐ Sáng/Tối</button>
  </header>

  <div class="bar-row">
    <div class="tabs" id="gameTabs"></div>
  </div>

  <div class="cards" id="cards"></div>

  <h2>Phân bố theo vị trí <span class="hint">mỗi kỳ sort tăng dần x1 ≤ … ≤ x6 · giá trị nào hay là xN</span></h2>
  <div class="grid6" id="positions"></div>

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
  </div>

  <h2>Số gan &amp; phong độ <span class="hint">lâu chưa về vs nóng gần đây</span></h2>
  <div class="panel" id="ganPanel"><div class="grid3"
      style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
    <div><div class="pc" id="ganTitle">Gan nhất — số kỳ chưa về</div><div id="ganChart"></div></div>
    <div><div class="pc" id="hotTitle">Nóng gần đây — số lần về</div><div id="hotChart"></div></div>
  </div></div>

  <h2>Cặp số hay đi cùng <span class="hint" id="pairHint"></span></h2>
  <div class="panel" id="pairPanel" style="max-width:560px"><div id="pairTable"></div></div>

  <h2>Bộ số gợi ý <span class="hint">chỉ để tham khảo — KHÔNG tăng xác suất trúng</span></h2>
  <div class="panel" id="sugPanel" style="max-width:760px">
    <div class="sugwrap">
      <div class="sugleft">
        <div id="suggestList"></div>
        <button class="btn" id="genBtn" type="button" style="margin-top:10px">🎲 Tạo bộ khác</button>
      </div>
      <div class="sugnote" id="sugNote"></div>
    </div>
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

  <footer id="footer"></footer>
</div>

<div id="tip"></div>

<script>
const DATA = %%DATA%%;
const GENERATED = "%%GENERATED%%";
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

  // positions x1..x6
  const pos = document.getElementById('positions');
  pos.innerHTML = '';
  for(const p of g.positions){
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.innerHTML =
      `<div class="pt">${esc(p.name)}</div>`+
      `<div class="pc">dao động ${p.min}–${p.max} · hay gặp ${p.mode} · TB ${p.mean}</div>`+
      `<div class="chart"></div>`;
    pos.appendChild(panel);
    columnChart(panel.querySelector('.chart'),
      p.values.map(v=>({label:v.value, value:v.occ})),
      {W:360, H:200, labelMax:true, softNonMax:true, labelEvery:5,
       tipTitle:d=>('giá trị '+esc(d.label))});
  }

  renderFreq();

  // streaks (đếm chính xác độ dài; ít cột nên nhãn tất cả)
  columnChart(document.getElementById('streakChart'),
    g.streaks.map(s=>({label:s.length+' kỳ', value:s.occ})),
    {W:400, H:230, labelAll:true, labelEvery:1,
     tipTitle:d=>('chuỗi dài đúng '+esc(d.label))});

  renderGap();
  renderBalance();
  renderGanHot();
  renderPairs();
  renderSuggest();
  renderSim();

  document.getElementById('footer').textContent =
    'Nguồn: vietlott_data.db · tạo lúc ' + GENERATED;
}

function renderGap(){
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

function renderBalance(){
  const ex = DATA[current].extra;
  const panel = document.getElementById('balPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('lowMax').textContent = ex.low_max;

  const oK = argmax(ex.odd), lK = argmax(ex.low);
  document.getElementById('balCards').innerHTML =
    mkTile('Tổng TB', ex.sum.mean.toLocaleString('vi'),
      'thực tế '+ex.sum.min+'–'+ex.sum.max) +
    mkTile('Vùng tổng hay gặp', ex.sum.p10+'–'+ex.sum.p90, '~80% số kỳ') +
    mkTile('Chẵn/lẻ hay gặp', oK+' lẻ · '+(6-oK)+' chẵn', '') +
    mkTile('Thấp/cao hay gặp', lK+' thấp · '+(6-lK)+' cao', '1–'+ex.low_max+' là thấp');

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
}

function renderGanHot(){
  const ex = DATA[current].extra;
  const panel = document.getElementById('ganPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  document.getElementById('hotTitle').textContent =
    'Nóng '+ex.recent_n+' kỳ gần nhất — số lần về';
  columnChart(document.getElementById('ganChart'),
    ex.overdue.map(o=>({label:o.number, value:o.gap})),
    {W:460,H:200,labelAll:true,labelEvery:1,tipTitle:d=>('số '+esc(d.label)+' · chưa về')});
  columnChart(document.getElementById('hotChart'),
    ex.hot.map(o=>({label:o.number, value:o.count})),
    {W:460,H:200,labelAll:true,labelEvery:1,tipTitle:d=>('số '+esc(d.label)+' · lần về')});
}

function renderPairs(){
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

function genSet(ex){
  const n = ex.n, lowMax = ex.low_max, p10 = ex.sum.p10, p90 = ex.sum.p90;
  for(let t=0;t<3000;t++){
    const set = new Set();
    while(set.size < 6) set.add(1 + Math.floor(Math.random()*n));
    const arr = [...set];
    const s = arr.reduce((a,b)=>a+b,0);
    const odd = arr.filter(x=>x%2===1).length;
    const low = arr.filter(x=>x<=lowMax).length;
    if(s>=p10 && s<=p90 && odd>=2 && odd<=4 && low>=2 && low<=4)
      return arr.sort((a,b)=>a-b);
  }
  return [1,2,3,4,5,6];
}
function renderSuggest(){
  const ex = DATA[current].extra;
  const panel = document.getElementById('sugPanel');
  if(!ex){ panel.style.display='none'; return; }
  panel.style.display='';
  let html='';
  for(let i=0;i<5;i++){
    const arr = genSet(ex);
    const s = arr.reduce((a,b)=>a+b,0);
    const odd = arr.filter(x=>x%2===1).length;
    const low = arr.filter(x=>x<=ex.low_max).length;
    html += '<div class="setrow"><span class="lbl">Bộ '+(i+1)+'</span>'+
      arr.map(x=>'<span class="chip">'+x+'</span>').join('')+
      '<span class="setmeta">tổng '+s+' · '+odd+' lẻ/'+(6-odd)+' chẵn · '+
      low+' thấp/'+(6-low)+' cao</span></div>';
  }
  document.getElementById('suggestList').innerHTML = html;

  document.getElementById('sugNote').innerHTML =
    '<div class="notet">Vì sao chọn được các số này?</div>'+
    'Mỗi bộ là 6 số bốc ngẫu nhiên, nhưng chỉ giữ lại bộ "trông giống" một kỳ '+
    'quay điển hình — phải thỏa cả 3 điều kiện lấy từ chính lịch sử:'+
    '<ol>'+
    '<li>Tổng 6 số nằm trong vùng hay gặp <b>'+ex.sum.p10+'–'+ex.sum.p90+
      '</b> (~80% số kỳ).</li>'+
    '<li>Cân đối chẵn/lẻ: <b>2–4 số lẻ</b> (lịch sử hay gặp 3 lẻ/3 chẵn).</li>'+
    '<li>Cân đối thấp/cao: <b>2–4 số</b> thuộc 1–'+ex.low_max+'.</li>'+
    '</ol>'+
    'Bộ nào lệch (tổng quá to/nhỏ, gần như toàn lẻ, dồn hết số thấp…) bị loại.'+
    '<span class="wl">⚠ Chỉ giúp bộ số "trông cân đối" — KHÔNG tăng xác suất trúng.</span>';
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
document.getElementById('freqSort').onclick = (e)=>{
  freqByCount = !freqByCount;
  e.target.textContent = 'Sắp theo: ' + (freqByCount?'số lần':'số');
  renderFreq();
};
document.getElementById('genBtn').onclick = ()=>{ renderSuggest(); };
document.getElementById('simRun').onclick = startSim;
document.getElementById('simStop').onclick = ()=>{ finishSim(false); };
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


def render_html(all_data: list[dict]) -> str:
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        HTML_TEMPLATE
        .replace("%%DATA%%", json.dumps(all_data, ensure_ascii=False))
        .replace("%%GENERATED%%", generated)
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sinh trang HTML thống kê Vietlott và mở trình duyệt."
    )
    parser.add_argument("--db", default=str(DB_PATH), help="Đường dẫn file SQLite.")
    parser.add_argument(
        "--game",
        default="all",
        help="power655, mega645, all (mặc định: mọi game có trong DB).",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_HTML_PATH),
        help="Đường dẫn file HTML xuất ra.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Chỉ tạo file, không tự mở trình duyệt.",
    )
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_arg_parser().parse_args()
    game_types = None if args.game in ("all", "") else [args.game]

    ensure_dirs()
    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    try:
        all_data = load_all(conn, args.db, game_types)
    finally:
        conn.close()

    if not all_data:
        print("Không có dữ liệu thống kê. Chạy number_stats.py trước.")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(all_data), encoding="utf-8")
    print(f"Đã tạo: {out}")

    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
