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
import base64
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

import gap_stats
from crawl import BASE_DIR, DB_PATH, EXPORT_DIR, ensure_dirs

DEFAULT_HTML_PATH = EXPORT_DIR / "stats.html"
MEGA_DB_PATH = DB_PATH.parent / "vietlott_mega645_data.db"
MEGA_HTML_PATH = EXPORT_DIR / "stats_mega645.html"
ICON_PATH = BASE_DIR / "vietlott_stats.ico"
SHORTCUT_NAME = "Thống kê Vietlott.lnk"

POSITION_NAMES = {
    1: "x1 · nhỏ nhất",
    2: "x2",
    3: "x3",
    4: "x4",
    5: "x5",
    6: "x6 · lớn nhất",
}


def compute_extra_stats(db_path: Path | str, game_type: str) -> dict | None:
    """Số liệu cho sugEngine + Mô phỏng: tổng, chẵn-lẻ, thấp-cao, liên tiếp, lặp, cooc.

    LƯU Ý: chỉ là thống kê mô tả, KHÔNG tăng xác suất trúng (xổ số độc lập).
    Các mục hiển thị (đầu số, số gan/nóng, cặp hay đi cùng, đuôi số...) đã bỏ khỏi
    trang nên KHÔNG tính nữa — payload chỉ giữ đúng phần score()/sugEngine đọc.
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

    # --- Ma trận đồng xuất hiện (cho chế độ "theo cặp" ở bộ gợi ý) ---
    pair_count: dict[tuple[int, int], int] = {}
    for d in draws:
        for a, b in combinations(d, 2):  # d đã sort tăng dần nên a < b
            pair_count[(a, b)] = pair_count.get((a, b), 0) + 1
    cooc_mat = [[0] * n for _ in range(n)]
    for (a, b), c in pair_count.items():
        cooc_mat[a - 1][b - 1] = c
        cooc_mat[b - 1][a - 1] = c

    # --- Số liên tiếp trong bộ ---
    consec_dist: dict[int, int] = defaultdict(int)
    for d in draws:
        consec_dist[sum(1 for i in range(5) if d[i + 1] == d[i] + 1)] += 1
    consecutive = [
        {"label": str(k), "occ": consec_dist.get(k, 0)}
        for k in range((max(consec_dist) if consec_dist else 0) + 1)
    ]

    # --- Số lặp lại từ kỳ ngay trước ---
    rep = [0] * 7
    for t in range(total - 1):
        rep[len(set(draws[t]) & set(draws[t + 1]))] += 1
    repeat_prev = [{"label": str(k), "occ": rep[k]} for k in range(7)]

    return {
        "total": total,
        "n": n,
        "low_max": low_max,
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
        "consecutive": consecutive,
        "repeat_prev": repeat_prev,
        "cooc": cooc_mat,
    }


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
        "extra": compute_extra_stats(db_path, game_type),
        "track": compute_track(db_path, game_type),
        "history": load_history(db_path, game_type),
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


def load_history(db_path: Path | str, game_type: str) -> list[dict]:
    """Toàn bộ kỳ đã về, mới nhất trước — cho mục "Lịch sử kết quả".

    Khoá đặt ngắn (p/d/n/s) vì list này nhúng thẳng vào HTML: ~1500 kỳ, tên khoá
    dài ra là trang phình thêm vài chục KB mà không thêm thông tin gì.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        rows = conn.execute(
            """
            SELECT draw_period, draw_date, num1, num2, num3, num4, num5, num6,
                   special_num
            FROM draw_results
            WHERE game_type = ?
            ORDER BY draw_date DESC, draw_period DESC
            """,
            (game_type,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    history = []
    for r in rows:
        nums = [
            int(r[f"num{i}"])
            for i in range(1, 7)
            if r[f"num{i}"] not in (None, "")
        ]
        item = {"p": r["draw_period"], "d": r["draw_date"], "n": sorted(nums)}
        # Mega 6/45 không có số đặc biệt -> bỏ hẳn khoá cho nhẹ payload.
        if r["special_num"] not in (None, ""):
            item["s"] = int(r["special_num"])
        history.append(item)
    return history


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
        "extra": extra,
        "track": compute_track(db_path, game_type),
        "history": load_history(db_path, game_type),
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
%%FAVICON%%
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
  .histctl{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
  .histctl label{display:flex;gap:6px;align-items:center;font-size:12.5px;color:var(--text2)}
  .histctl input{background:var(--surface);border:1px solid var(--border);
    color:var(--text);border-radius:6px;padding:5px 8px;font:inherit;font-size:12.5px;
    width:190px}
  .htbl{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
  .htbl th{text-align:left;padding:5px 8px;border-bottom:1px solid var(--baseline);
    color:var(--text2);font-weight:600;position:sticky;top:0;background:var(--surface)}
  .htbl td{padding:4px 8px;border-bottom:1px solid var(--border)}
  .htbl .date{color:var(--muted);white-space:nowrap}
  .htbl .balls{font-weight:650;letter-spacing:.5px}
  .htbl .sp{color:var(--warn);font-weight:650}
  .htbl mark{background:var(--series-soft);color:var(--text);border-radius:3px;padding:0 2px}
  .histwrap{max-height:520px;overflow:auto;border:1px solid var(--border);border-radius:8px}
  .sugwrap{display:flex;gap:18px;flex-wrap:wrap}
  .sugleft{flex:1 1 320px;min-width:300px}
  .sugnote{flex:0 1 268px;font-size:12.5px;color:var(--text2);line-height:1.55;
    border-left:2px solid var(--series);padding-left:14px}
  .sugnote .notet{font-weight:600;color:var(--text);margin-bottom:6px}
  .sugnote ol{margin:6px 0;padding-left:18px}
  .sugnote li{margin:3px 0}
  .sugnote b{color:var(--text)}
  /* Cảnh báo: dùng ở sugnote, sugStat, btBody và trackBody nên để selector chung.
     .wl = cả dòng riêng; .wli = tô cảnh báo ngay giữa câu. */
  .wl{color:var(--warn);display:block;margin-top:8px}
  .wli{color:var(--warn);font-weight:650}
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
          <option value="spread">Phủ rộng (ít chồng lấn nhất)</option>
        </select>
      </label>
      <label>Số bộ<input id="sugCount" type="text" inputmode="numeric" value="5"
        style="width:78px" title="1–5000 · trên 20 bộ là chế độ bội số"></label>
      <label>Khoá số<input id="sugLock" type="text" inputmode="numeric" placeholder="vd: 7 22"></label>
      <label>Loại số<input id="sugExcl" type="text" inputmode="numeric" placeholder="vd: 13"></label>
      <button class="btn" id="genBtn" type="button">🎲 Tạo</button>
    </div>
    <div class="pc" id="sugAuto"></div>
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


  <!-- Ngoài khối LOWER: lịch sử chỉ cần draw_results nên bản rút gọn vẫn có. -->
  <h2>Lịch sử kết quả <span class="hint" id="histHint"></span></h2>
  <div class="panel" id="histPanel">
    <div class="histctl">
      <label>Lọc<input id="histFind" type="text"
        placeholder="vd: 01538 · 2026-07 · 22 41"></label>
      <span class="pc" id="histCount"></span>
    </div>
    <div id="histTable"></div>
    <div style="margin-top:10px">
      <button class="btn" id="histMore" type="button">Xem thêm 100 kỳ</button>
      <button class="btn" id="histAll" type="button">Hiện tất cả</button>
      <button class="btn" id="histCopy" type="button">📋 Chép</button>
    </div>
  </div>

  <footer id="footer"></footer>
</div>

<script>
const DATA = %%DATA%%;
const GENERATED = "%%GENERATED%%";
const SOURCE = "%%SOURCE%%";
const GOLDEN = %%GOLDEN%%;
// Nhớ lựa chọn Sáng/Tối của lần trước (áp NGAY trước khi render để khỏi chớp).
try{
  const savedTheme = localStorage.getItem('vietlott_theme');
  if(savedTheme==='dark' || savedTheme==='light')
    document.documentElement.setAttribute('data-theme', savedTheme);
}catch(e){}
let current = 0;
let simRunning = false, simTarget = null, simAttempts = 0, simHits = null;
const SIM_CAP = 100000000, SIM_CHUNK = 300000;

const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const pad2 = x => String(x).padStart(2,'0');

// series: [{label, value, sub, highlight}]
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
  // Kỳ vừa về là thứ muốn xem nhất sau khi cập nhật — đưa lên đầu thay vì
  // bắt cuộn xuống mục Lịch sử cuối trang.
  const last = (g.history||[])[0];
  const lastCard = last
    ? '<div class="card"><div class="k">Kỳ mới nhất · '+esc(last.p||'—')+
      ' · '+esc(last.d||'')+'</div><div class="v" style="font-size:21px;letter-spacing:1px">'+
      last.n.map(pad2).join(' ')+
      (last.s!=null ? ' <span style="color:var(--warn)">| '+pad2(last.s)+'</span>' : '')+
      '</div></div>'
    : '';
  cards.innerHTML =
    lastCard +
    mk('Tổng số kỳ', g.total_draws.toLocaleString('vi')) +
    mk('Số về nhiều nhất', hot ? (hot.number+' · '+hot.count+' lần') : '—') +
    mk('Lâu chưa về nhất', cold ? (cold.number+' · '+cold.gap+' kỳ') : '—');

  // Các mục "Phân bố theo vị trí" / "Tần suất từng số" đã bỏ khỏi trang, nhưng
  // g.positions và g.frequency VẪN nằm trong payload: sugEngine dùng min/max
  // từng vị trí làm ràng buộc, và dùng count/gap cho chế độ số nóng/số gan. Bỏ
  // dữ liệu đi thì bộ số trên web sẽ khác với predict_track.py sinh cho DB.
  // Ba thẻ tóm tắt phía trên cũng đọc g.frequency.

  if(!sugModeTouched){
    const bm = bestTrackMode();
    if(bm) document.getElementById('sugMode').value = bm;
  }
  renderSuggest();
  renderBacktest();
  renderTrack();
  renderSim();
  histShown = HIST_STEP;   // đổi game -> về lại 100 kỳ đầu
  renderHistory();

  document.getElementById('footer').textContent =
    'Nguồn: ' + SOURCE + ' · tạo lúc ' + GENERATED;
}

// --- Lịch sử kết quả -------------------------------------------------------
let histShown = 100, histQuery = '';
const HIST_STEP = 100;

function histFilter(){
  const h = DATA[current].history || [];
  const q = histQuery.trim().toLowerCase();
  if(!q) return h;
  // Số tách rời nhau: "22 41" = kỳ nào có CẢ 22 và 41. Chữ/ngày thì so chuỗi.
  const terms = q.split(/\s+/);
  const nums = terms.filter(t=>/^\d{1,2}$/.test(t)).map(Number);
  const texts = terms.filter(t=>!/^\d{1,2}$/.test(t));
  return h.filter(r=>{
    if(nums.length && !nums.every(x=> r.n.includes(x) || r.s===x)) return false;
    if(texts.length){
      const hay = (r.p+' '+r.d).toLowerCase();
      if(!texts.every(t=> hay.includes(t))) return false;
    }
    return true;
  });
}

function renderHistory(){
  const panel = document.getElementById('histPanel');
  if(!panel) return;
  const h = DATA[current].history || [];
  if(!h.length){ panel.style.display='none'; return; }
  panel.style.display='';

  const rows = histFilter();
  const slice = rows.slice(0, histShown);
  const hasSpecial = h.some(r=> r.s!=null);
  const hi = new Set(histQuery.trim().split(/\s+/)
    .filter(t=>/^\d{1,2}$/.test(t)).map(Number));

  const ball = x => hi.has(x) ? '<mark>'+pad2(x)+'</mark>' : pad2(x);
  let body = slice.map(r=>
    '<tr><td>'+esc(r.p||'—')+'</td>'+
    '<td class="date">'+esc(r.d||'')+'</td>'+
    '<td class="balls">'+r.n.map(ball).join(' ')+'</td>'+
    (hasSpecial ? '<td class="sp">'+(r.s!=null ? ball(r.s) : '—')+'</td>' : '')+
    '</tr>').join('');
  if(!slice.length) body = '<tr><td colspan="4" class="pc">Không có kỳ nào khớp.</td></tr>';

  document.getElementById('histTable').innerHTML =
    '<div class="histwrap"><table class="htbl"><thead><tr>'+
    '<th>Kỳ</th><th>Ngày</th><th>Kết quả</th>'+
    (hasSpecial ? '<th>ĐB</th>' : '')+
    '</tr></thead><tbody>'+body+'</tbody></table></div>';

  document.getElementById('histCount').textContent =
    'Hiện ' + Math.min(histShown, rows.length).toLocaleString('vi') +
    '/' + rows.length.toLocaleString('vi') + ' kỳ' +
    (rows.length !== h.length ? ' (lọc từ '+h.length.toLocaleString('vi')+')' : '');
  document.getElementById('histHint').textContent =
    h.length.toLocaleString('vi') + ' kỳ · mới nhất trước';

  const done = histShown >= rows.length;
  document.getElementById('histMore').disabled = done;
  document.getElementById('histAll').disabled = done;
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

// --- Độ phủ: thứ DUY NHẤT cải thiện được khi mua cả một bội số ---------------
// Xác suất trúng của TỪNG vé là cố định (không chế độ nào đổi được). Cái đổi được
// là mức CHỒNG LẤN giữa các vé: hai vé chung 5 số thì gần như luôn cùng trúng hoặc
// cùng trượt, tức tiền mua vé thứ hai bị phí. Đo bằng số bộ-3 KHÁC NHAU mà cả bội
// số phủ được — mỗi vé có C(6,3)=20 bộ-3, nên k vé phủ tối đa 20k.
// ĐỒNG BỘ: giống coverage3/gen_spread trong predict_track.py.
const SPREAD_TRIES = 40;
function tripleKeys(s, n){                     // s: 6 số đã sắp tăng dần
  const out=[];
  for(let i=0;i<4;i++) for(let j=i+1;j<5;j++) for(let m=j+1;m<6;m++)
    out.push((s[i]*n + s[j])*n + s[m]);
  return out;
}
function coverage3(sets, n){
  const seen=new Set();
  for(const s of sets){ if(!s||s.length<6) continue;
    for(const k of tripleKeys(s,n)) seen.add(k); }
  return seen.size;
}
// Trần độ phủ KHÔNG phải 20×số vé: cả trò chơi chỉ có C(n,3) bộ-3, nên khi 20k vượt
// quá con số đó thì trần thật là C(n,3). Mega 6/45 với 1000 vé: C(45,3)=14.190 <
// 20.000 — lấy 20k làm mẫu số sẽ khiến MỌI chế độ trông tệ đi một cách giả tạo.
function coverageCap(k, n){ return Math.min(20*k, n*(n-1)*(n-2)/6); }
function pickRandom(pool, k){                  // Fisher–Yates một phần
  const a=pool.slice();
  for(let i=0;i<k && i<a.length;i++){
    const j=i+(Math.random()*(a.length-i)|0), t=a[i]; a[i]=a[j]; a[j]=t; }
  return a.slice(0,k);
}
// Trả về hàm sinh 1 vé; `covered` sống suốt bội số nên MỖI lần tạo bội số phải gọi
// makeSpread mới, không dùng chung một generator giữa các lần bấm Tạo.
function makeSpread(n, pool, locked){
  const covered=new Set(), need=Math.max(0, 6-locked.length);
  return function(){
    if(pool.length < need) return null;
    let best=null, bestNew=-1;
    for(let t=0;t<SPREAD_TRIES;t++){
      const c=locked.concat(pickRandom(pool,need)).sort((a,b)=>a-b);
      if(c.length<6) return null;
      let nw=0; for(const k of tripleKeys(c,n)) if(!covered.has(k)) nw++;
      if(nw>bestNew){ best=c; bestNew=nw; }
      if(nw===20) break;                       // đã phủ toàn bộ-3 mới, khỏi thử tiếp
    }
    if(best) for(const k of tripleKeys(best,n)) covered.add(k);
    return best;
  };
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
  const spreadPool = (()=>{ const p=[];
    for(let x=1;x<=n;x++) if(!exclSet.has(x) && !locked.includes(x)) p.push(x);
    return p; })();
  const rawGen = mode==='spread' ? makeSpread(n, spreadPool, locked)
               : mode==='pairs'  ? genPair : sampleWeighted;
  // payout: bốc ở mức BỘ (giữ bộ ít người đánh nhất) + loại thẳng dạng đụng hàng nặng.
  const gen = mode==='payout' ? (()=>popTournament(rawGen)) : rawGen;
  const crowded = mode==='payout' ? isCrowdedSet : (()=>false);
  // "Phủ rộng" cố tình BỎ ràng buộc điển hình: ràng buộc thu hẹp không gian bốc nên
  // bóp chính độ phủ mà chế độ này đang tối ưu, trong khi KHÔNG nâng kỳ vọng trúng
  // của từng vé (luôn là 36/n dù chọn bộ nào).
  const typical = mode==='spread' ? (()=>true) : passes;

  // Bội số: ngân sách phải co giãn theo count, nếu không xin 1000 bộ sẽ chỉ ra vài chục.
  const bulk = count > 20;
  // spread lấy đúng count bộ: sinh dư rồi cắt theo điểm sẽ vứt mất chính các vé
  // được chọn để lấp chỗ trống, làm hỏng độ phủ.
  const poolTarget = mode==='spread' ? count : (bulk ? Math.ceil(count*1.4) : count*10);
  const tries1 = Math.max(9000, count*40), tries2 = Math.max(4000, count*20);
  // Chống "cày không ra": chế độ pairs bốc tham lam nên số bộ DUY NHẤT có hạn
  // (~1.6k với 6/55); hết bộ mới thì thoát sớm thay vì quay vòng vô ích.
  const STALL_MAX = 4000;

  const pool=[], seen=new Set(); let relaxed=false, stall=0;
  for(let t=0;t<tries1 && pool.length<poolTarget && stall<STALL_MAX; t++){
    const s=gen(); if(!s||s.length<6){ stall++; continue; }
    const key=s.join(','); if(seen.has(key)){ stall++; continue; }
    if(crowded(s)){ stall++; continue; }
    const m=score(s); if(!typical(m)){ stall++; continue; }
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
  if(mode!=='spread') pool.sort((a,b)=>b.score-a.score);
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
  pairs:'Theo cặp hay đi cùng',payout:'Tránh số đông',spread:'Phủ rộng'};

// Chế độ mặc định TỰ CHỌN theo số liệu thật: lấy chế độ đứng đầu bảng xếp hạng
// DB (tr.methods đã xếp theo ĐỘ PHỦ — thứ duy nhất quyết định cơ hội có vé
// trúng ≥4 số khi mua cả bội số). KHÔNG lấy theo cột ≥4 từng vé: cột đó là
// nhiễu quanh ngẫu nhiên và hiện đang "thưởng" nhầm chế độ chồng lấn nặng nhất.
// Người dùng tự đổi tay thì tôn trọng lựa chọn đó (sugModeTouched).
let sugModeTouched = false;
function bestTrackMode(){
  const tr = DATA[current].track;
  if(!tr || !tr.methods) return null;
  const lead = tr.methods.filter(m=>m.sets && m.cov_rate);
  return lead.length ? lead[0].key : null;
}
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
    // Độ phủ: chỉ số quan trọng nhất của một BỘI SỐ — càng gần trần (xem coverageCap) thì
    // các vé càng ít chồng lấn, tức tiền bỏ ra càng ít bị phí.
    const cov = coverage3(res.out.map(c=>c.set), ex.n),
          cap = coverageCap(res.out.length, ex.n);
    const covPct = cap ? cov/cap*100 : 0;
    const covCol = covPct>=80 ? 'var(--good)' : covPct<50 ? 'var(--warn)' : '';
    stat.innerHTML = 'Đã tạo <b>'+res.out.length.toLocaleString('vi')+'</b> bộ'+
      (uniq<res.out.length ? ' (chỉ <b>'+uniq.toLocaleString('vi')+'</b> bộ khác nhau — '+
        'chế độ này không bốc thêm được bộ mới)' : ' · tất cả khác nhau')+
      ' · <b'+(covCol?' style="color:'+covCol+'"':'')+'>độ phủ '+covPct.toFixed(0)+'%</b> ('+
      cov.toLocaleString('vi')+'/'+cap.toLocaleString('vi')+' bộ-3)'+
      ' · điểm điển hình TB <b>'+avgScore.toFixed(0)+'</b>'+
      ' · độ phổ biến TB <b>'+avgPop.toFixed(2)+'</b> (thấp = ít người đánh trùng)'+
      ' · tổng tiền <b>'+(res.out.length*10000).toLocaleString('vi')+'đ</b> nếu mua hết.'+
      (covPct<50 ? '<br><span class="wl">⚠ Độ phủ thấp: các vé chồng lấn nhau nhiều nên '+
        'phần lớn số tiền này không mở thêm cơ hội trúng. Chế độ <b>Phủ rộng</b> đạt ~84% '+
        'với cùng số vé.</span>' : '');
  }else{
    wrap.style.display='none'; ta.value=''; stat.innerHTML='';
  }

  document.getElementById('sugMsg').textContent = res.relaxed
    ? '⚠ Không đủ bộ qua ràng buộc (khoá số? số bộ quá lớn?) — đã nới lỏng để đủ '
      +res.out.length+'/'+res.asked+' bộ.' : '';

  const autoEl = document.getElementById('sugAuto');
  if(autoEl){
    const bm = bestTrackMode();
    autoEl.innerHTML = (!sugModeTouched && bm && res.mode===bm)
      ? 'Tự chọn <b>'+MODE_NAME[bm]+'</b> theo số liệu thật: đứng đầu về <b>độ phủ</b> '+
        'trong mục "Giải thuật nào đang trúng nhiều nhất?" bên dưới — cùng số vé, bội số '+
        'ít chồng lấn nhất nên cơ hội có vé trúng ≥4 số cao nhất khi mua nhiều vé cùng kỳ. '+
        '(Tỉ lệ ≥4 tính trên TỪNG vé thì chế độ nào cũng như nhau — chênh lệch là nhiễu.) '+
        'Bạn đổi chế độ tay thì trang giữ lựa chọn đó.'
      : '';
  }

  document.getElementById('sugNote').innerHTML =
    '<div class="notet">Cách chấm điểm &amp; chế độ</div>'+
    '<b>Điểm điển hình</b> = mức bộ số khớp với thói quen lịch sử ở 5 mặt: '+
    'tổng, chẵn/lẻ, thấp/cao, số liên tiếp, số lặp kỳ trước (100 = giống nhất).'+
    (res.mode==='spread'
      ? '<div style="margin-top:6px">Chế độ này <b>không áp</b> ràng buộc điển hình — '+
        'xem giải thích bên dưới.</div>'
      : '<div style="margin-top:6px">Bộ còn phải qua ràng buộc: tổng trong '+
        ex.sum.p10+'–'+ex.sum.p90+', 2–4 lẻ, 2–4 thấp, ≤1 cặp liên tiếp, trải ≥3 hàng chục, '+
        'mỗi vị trí x1–x6 trong dải lịch sử, lặp kỳ trước ≤2.</div>')+
    '<div style="margin-top:6px"><b>Chế độ '+MODE_NAME[res.mode]+':</b> '+
    ({balanced:'bốc đều, chỉ cần điển hình. Độ phủ ~68%.',
      hot:'thiên số về nhiều. Độ phủ ~68%.',
      gan:'thiên số lâu chưa về. <b class="wli">Độ phủ chỉ ~46%</b> — dồn vào nhóm số ít.',
      pairs:'ghép theo cặp hay đi cùng. <b class="wli">Độ phủ chỉ ~20%</b> — bốc tham lam '+
            'nên các vé rất giống nhau, gần 80% tiền vé không mở thêm cơ hội trúng.',
      payout:'né số nhiều người đánh (ngày sinh 1–31, tháng 1–12, đuôi 8/6), '+
             'ưu tiên đuôi 0/9 và số &gt;31; loại bộ toàn ngày sinh, cấp số cộng, '+
             'cùng một hàng chục. Mỗi lần bốc '+POP_TOURNAMENT+' bộ rồi giữ bộ ít người đánh nhất. '+
             'Độ phủ ~55%.',
      spread:'mỗi lần bốc '+SPREAD_TRIES+' bộ ứng viên, giữ bộ phủ được nhiều <b>bộ-3 mới</b> '+
             'nhất so với các vé đã chọn. <b>Độ phủ ~84%</b> — cao nhất trong các chế độ. '+
             'Cố tình BỎ ràng buộc điển hình vì ràng buộc đó thu hẹp không gian bốc, '+
             'làm giảm độ phủ mà không nâng kỳ vọng trúng của từng vé.'
    }[res.mode])+'</div>'+
    (res.mode==='spread'
      ? '<div style="margin-top:6px"><b>Vì sao chế độ này khác hẳn:</b> nó KHÔNG cố đoán số. '+
        'Xác suất của từng vé vẫn y hệt các chế độ khác. Nó chỉ giảm mức <b>chồng lấn</b> '+
        'giữa các vé trong cùng bội số — hai vé chung 5 số thì gần như luôn cùng trúng hoặc '+
        'cùng trượt, nên vé thứ hai phí tiền. Đây là thứ duy nhất cải thiện được bằng cách '+
        'chọn số, và nó chỉ có ý nghĩa khi bạn mua <b>nhiều vé cùng kỳ</b>.</div>' : '')+
    (res.mode==='payout'
      ? '<div style="margin-top:6px"><b>Độ phổ biến</b> = ước lượng mức đông người cùng đánh '+
        '(1,0 ≈ trung bình; thấp hơn là tốt). Dựa trên nghiên cứu hành vi chọn số; phần '+
        'đuôi 8/6/4 là <b>giả định thói quen VN</b>, Vietlott không công bố dữ liệu vé bán '+
        'ra nên không kiểm chứng được.</div>' : '')+
    '<span class="wl">⚠ Không chế độ nào tăng xác suất trúng. "Tránh số đông" KHÔNG giúp dễ '+
    'trúng hơn — chỉ giảm khả năng phải chia giải với người khác khi đã trúng.</span>';
}

// --- So sánh 5 giải thuật với 1 kết quả (mỗi lần Chạy tạo mới 1000 bộ/giải thuật) ---
const BT_MODES = [['spread','Phủ rộng'],['balanced','Cân đối'],['hot','Thiên số nóng'],
  ['gan','Thiên số gan'],['pairs','Theo cặp hay đi cùng'],['payout','Tránh số đông']];

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
  // "Phủ rộng" phải nhớ các bộ-3 đã phủ trong SUỐT bội số, nên không dùng chung
  // `gen` không trạng thái được — mỗi lần tạo bội số gọi makeGen('spread') một lần
  // rồi gọi hàm trả về cho từng vé.
  const pool = (()=>{ const p=[]; for(let x=1;x<=n;x++) p.push(x); return p; })();
  const makeGen = mode => mode==='spread'
    ? makeSpread(n, pool, [])
    : (()=>gen(mode));
  return {n, gen, makeGen};
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
    BT_MODES.forEach(([k])=>{ const g=eng.makeGen(k), a=new Array(count);
      for(let i=0;i<count;i++) a[i]=g(); sets[k]=a; });
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
function btStatsFromSets(mode, sets, win, n){
  const dist=[0,0,0,0,0,0,0], numHit={}, wins={3:[],4:[],5:[],6:[]};
  let sumMatched=0, best=0;
  const ok=[];
  for(const s of sets){
    if(!s || s.length<6) continue;
    ok.push(s);
    let c=0; for(const x of s) if(win.has(x)){ c++; numHit[x]=(numHit[x]||0)+1; }
    dist[c]++; sumMatched+=c; if(c>best) best=c;
    if(c>=3) wins[c].push(s);
  }
  const made=ok.length;
  const uniq=new Set(ok.map(s=>s.join(','))).size;
  const cov=coverage3(ok, n), cap=coverageCap(made, n);
  return {mode, made, dist, best, numHit, wins, uniq, cov, cap,
    covPct: cap ? cov/cap*100 : 0,
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
  const stats = BT_MODES.map(([k])=>btStatsFromSets(k, batch.sets[k]||[], win, ex.n));
  renderBtResult(target, stats, batch.count, batch.created);
}

function renderBtResult(target, stats, count, created){
  const ex = DATA[current].extra, n = ex.n;
  const baseline = Math.round(36/n*1000)/1000;
  // ★ theo ĐỘ PHỦ, không theo TB trùng: TB trùng của mọi giải thuật đều dao động
  // quanh 36/n do may rủi, gắn sao cho nó là gắn sao cho nhiễu — và với 1 kỳ duy
  // nhất thì càng vô nghĩa. Độ phủ mới là khác biệt thật, đo được, không phụ thuộc
  // kết quả kỳ nào.
  const bestCov = Math.max(...stats.map(s=>s.covPct));
  const nameOf = {}; BT_MODES.forEach(([k,nm])=>nameOf[k]=nm);

  let cols='';
  stats.forEach(s=>{
    const lead = s.covPct===bestCov;
    const covCol = s.covPct>=80 ? 'var(--good)' : s.covPct<50 ? 'var(--warn)' : '';
    const rates = target.map(x=>({x, r: s.made ? (s.numHit[x]||0)/s.made*100 : 0}))
                        .sort((a,b)=>b.r-a.r);
    let mini='';
    rates.forEach(o=>{ mini +=
      '<div class="hl"><span class="num">'+o.x+'</span>'+
      '<span class="bar"><span style="width:'+Math.round(o.r)+'%"></span></span>'+
      '<span class="pct">'+o.r.toFixed(0)+'%</span></div>'; });
    cols += '<div class="btcol'+(lead?' lead':'')+'">'+
      '<div class="nm"><span>'+esc(nameOf[s.mode])+'</span>'+(lead?'<span class="star">★</span>':'')+'</div>'+
      '<div class="k">Độ phủ (bộ-3 khác nhau)</div>'+
      '<div class="big"'+(covCol?' style="color:'+covCol+'"':'')+'>'+s.covPct.toFixed(0)+'%</div>'+
      '<div class="k">'+s.cov.toLocaleString('vi')+' / '+s.cap.toLocaleString('vi')+
        (s.uniq<s.made ? ' · chỉ <b>'+s.uniq.toLocaleString('vi')+'</b> bộ khác nhau' : '')+'</div>'+
      '<div class="k" style="margin-top:6px;border-top:1px solid var(--border);padding-top:5px">'+
        'TB trùng / vé <b>'+s.avg.toFixed(3)+'</b></div>'+
      '<div class="k">≥3: <b>'+s.hit3+'</b> · ≥4: <b>'+s.hit4+
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
    '<div class="pc" style="margin-top:10px">Mỗi cột là 1 giải thuật. <b>Độ phủ</b> = số bộ-3 khác nhau '+
    'mà cả bội số phủ được, chia cho trần lý thuyết (nhỏ hơn giữa 20×số vé và C(n,3)) — '+
    'phủ càng cao thì các vé càng ít chồng lấn, '+
    'tức cùng số tiền mà mở được nhiều cơ hội hơn. <b>★ = độ phủ cao nhất.</b> '+
    '<b>TB trùng/vé</b> = trung bình số trùng với kết quả; <b>≥3…6</b> = số bộ đạt mức đó; '+
    'hàng dưới là tỉ lệ mỗi số kết quả xuất hiện trong '+count.toLocaleString('vi')+' bộ. '+
    'So sánh dùng <b>đúng bộ đã lưu</b> nên kết quả cố định; bấm <b>Tạo &amp; lưu</b> để bốc bộ mới.'+
    '<span class="wl">⚠ Đừng xếp hạng giải thuật theo TB trùng hay số bộ trúng: với 1 kỳ duy nhất '+
    'thì chênh lệch đó gần như hoàn toàn là may rủi, kỳ sau sẽ đảo thứ tự. Chỉ <b>độ phủ</b> là '+
    'ổn định và không phụ thuộc kết quả kỳ nào.</span></div>'+
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

  // Cột mỗi giải thuật — tr.methods đã xếp sẵn theo ĐỘ PHỦ giảm dần (không theo TB
  // trùng: TB trùng chỉ dao động quanh mức ngẫu nhiên nên xếp theo nó là xếp nhiễu).
  const withData = tr.methods.filter(m=>m.sets);
  const bestCov  = Math.max.apply(null, withData.map(m=>m.cov_rate||0));
  const bestWins = Math.max.apply(null, withData.map(m=>m.wins));
  let cols='';
  tr.methods.forEach(m=>{
    if(!m.sets){
      cols += '<div class="btcol"><div class="nm"><span>'+esc(m.name)+'</span></div>'+
        '<div class="k" style="margin-top:8px">chưa có dữ liệu</div></div>';
      return;
    }
    const cov = m.cov_rate || 0;
    const lead = cov>0 && cov === bestCov;
    const covCol = cov>=80 ? 'var(--good)' : cov>0 && cov<50 ? 'var(--warn)' : '';
    cols += '<div class="btcol'+(lead?' lead':'')+'">'+
      '<div class="nm"><span>'+esc(m.name)+'</span>'+(lead?'<span class="star">★</span>':'')+'</div>'+
      '<div class="k">Độ phủ (bộ-3 khác nhau)</div>'+
      '<div class="big"'+(covCol?' style="color:'+covCol+'"':'')+'>'+
        (cov ? cov.toFixed(0)+'%' : '—')+'</div>'+
      '<div class="k" style="margin-top:6px;border-top:1px solid var(--border);padding-top:5px">'+
        'TB trùng / vé <b>'+m.avg.toFixed(3)+'</b></div>'+
      '<div class="k">Thắng kỳ: <b>'+m.wins+
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
        '</b> kỳ: <b>không chế độ nào</b> vượt ngẫu nhiên. Chế độ có TB trùng cao nhất chỉ '+
        'đang gặp may — chênh lệch nằm trong sai số. Đúng như lý thuyết: kỳ vọng mỗi vé luôn '+
        'là 6×6/'+DATA[current].extra.n+' = <b>'+tr.baseline.avg+'</b> số trùng, '+
        '<b>bất kể chọn số nào</b>.'+
        '<div style="margin-top:6px">Nên thứ đáng so giữa các chế độ không phải "đoán trúng hơn" '+
        '(không chế độ nào làm được) mà là <b>độ phủ</b>: cùng số vé, bội số ít chồng lấn hơn thì '+
        'nhiều cơ hội hơn. Đó là lý do bảng này xếp theo độ phủ.</div></div>';

  status.innerHTML = 'Đã chấm <b>'+tr.scored_batches+'</b> kỳ thật'+
    (tr.pending?' · đang chờ <b>'+tr.pending+'</b> kỳ':'')+
    ' · ngẫu nhiên lý thuyết TB <b>'+tr.baseline.avg+'</b> số trùng/vé.';
  body.innerHTML = '<div class="btgrid">'+cols+'</div>'+ verdict + distTbl + hist +
    '<div class="pc" style="margin-top:10px">Khác với bảng ở trên (bộ số lưu trong trình duyệt), '+
    'bảng này dùng <b>bộ số đã chốt trong DB trước khi kỳ mới về</b> nên không thể "nhìn trước kết quả". '+
    '<b>TB trùng/vé</b> = trung bình số trùng trên toàn bộ vé đã chấm; <b>Thắng kỳ</b> = số kỳ giải thuật đó '+
    'có TB cao nhất (hoà thì chia đôi). '+
    '<b>Bảng xếp theo Độ phủ, không theo TB trùng</b> — TB trùng của mọi giải thuật đều dao động quanh '+
    'mức ngẫu nhiên, nên xếp theo nó là xếp theo may rủi và đẩy nhầm giải thuật chồng lấn nặng lên đầu. '+
    (withData.some(m=>!m.cov_rate)
      ? '<span class="wl">⚠ Các kỳ đã chấm bằng bản cũ chưa lưu độ phủ (hiện "—"). '+
        'Chạy lại backtest để có số liệu này.</span>' : '')+
    '<span class="wl">⚠ Cần vài chục kỳ chênh lệch mới có ý nghĩa — ít kỳ thì thứ hạng theo TB trùng chủ yếu là nhiễu, '+
    'và không giải thuật nào làm tăng xác suất trúng của từng vé.</span></div>';
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

// --- wiring ----------------------------------------------------------------
const tabs = document.getElementById('gameTabs');
DATA.forEach((g,i)=>{
  const b = document.createElement('button');
  b.className='btn'; b.type='button'; b.textContent=g.game_type;
  b.onclick=()=>{ current=i; render(); };
  tabs.appendChild(b);
});
document.getElementById('genBtn').onclick = renderSuggest;
document.getElementById('sugMode').onchange = ()=>{ sugModeTouched = true; renderSuggest(); };
document.getElementById('sugCount').onchange = renderSuggest;
document.getElementById('simRun').onclick = startSim;
document.getElementById('simStop').onclick = ()=>{ finishSim(false); };
document.getElementById('btGen').onclick = btGenerate;
document.getElementById('btCmp').onclick = btCompare;
document.getElementById('btInput').addEventListener('keydown', e=>{
  if(e.key==='Enter') btCompare();
});
document.getElementById('histFind').addEventListener('input', e=>{
  histQuery = e.target.value; histShown = HIST_STEP; renderHistory();
});
document.getElementById('histMore').onclick = ()=>{
  histShown += HIST_STEP; renderHistory();
};
document.getElementById('histAll').onclick = ()=>{
  histShown = (DATA[current].history||[]).length; renderHistory();
};
document.getElementById('histCopy').onclick = (e)=>{
  const txt = histFilter().slice(0, histShown).map(r=>
    [r.p, r.d, r.n.map(pad2).join(' ')].concat(r.s!=null?[pad2(r.s)]:[]).join('\t')
  ).join('\n');
  navigator.clipboard.writeText(txt).then(()=>{
    const b=e.target, old=b.textContent;
    b.textContent='✓ Đã chép'; setTimeout(()=>{ b.textContent=old; }, 1500);
  });
};
document.getElementById('themeBtn').onclick = ()=>{
  const cur = document.documentElement.getAttribute('data-theme');
  const isDark = cur ? cur==='dark'
    : window.matchMedia('(prefers-color-scheme: dark)').matches;
  const next = isDark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try{ localStorage.setItem('vietlott_theme', next); }catch(e){}
  // KHÔNG render() lại: CSS var tự đổi màu. Render sẽ bốc lại bộ số ngẫu nhiên
  // MỚI và reset lịch sử/mô phỏng — mất đúng thứ người dùng đang xem.
};

// Đối chiếu mô hình JS với bộ golden chốt trong predict_track.py. Hai bản
// Python/JS phải giống hệt nhau (xem GOLDEN_SETS bên đó) — lệch là bộ số sinh
// trên trang không còn khớp với bảng xếp hạng DB, phải sửa cho khớp ngay.
(function(){
  if(!GOLDEN || !GOLDEN.sets) return;
  const bad = [];
  for(const g of GOLDEN.sets){
    if(Math.abs(popOfSet(g.set)-g.pop) > 1e-6*Math.max(1,Math.abs(g.pop))
       || isCrowdedSet(g.set)!==g.crowded) bad.push(g.set.join(','));
  }
  for(const c of GOLDEN.caps){
    if(coverageCap(c[0],c[1])!==c[2]) bad.push('cap('+c[0]+','+c[1]+')');
  }
  if(bad.length){
    console.error('GOLDEN lệch:', bad);
    const w=document.createElement('div');
    w.className='banner';
    w.style.color='var(--warn)';
    w.textContent='⚠ Mô hình JS trên trang đã LỆCH với bản Python (predict_track.py): '+
      bad.join(' · ')+' — bộ số sinh ở đây không còn khớp với bảng xếp hạng DB.';
    document.querySelector('.wrap').prepend(w);
  }
})();
render();
</script>
</body>
</html>
"""


def _favicon_tag() -> str:
    """Nhúng vietlott_stats.ico làm icon tab (data URI — trang vẫn self-contained)."""
    try:
        if ICON_PATH.is_file() or _sinh_icon(ICON_PATH):
            b64 = base64.b64encode(ICON_PATH.read_bytes()).decode("ascii")
            return f'<link rel="icon" href="data:image/x-icon;base64,{b64}">'
    except Exception:  # noqa: BLE001 — không có icon thì trang vẫn phải sinh được
        pass
    return ""


def _golden_payload() -> str:
    """Bộ golden từ predict_track để JS tự đối chiếu; tiện thể selftest bản Python."""
    try:
        import predict_track

        errs = predict_track.selftest()
        if errs:
            print("⚠ predict_track.selftest LỆCH golden — sửa cho khớp rồi hãy tin trang:")
            for e in errs:
                print("   -", e)
        return json.dumps({
            "sets": [
                {"set": list(s), "pop": p, "crowded": c}
                for s, p, c in predict_track.GOLDEN_SETS
            ],
            "caps": [list(c) for c in predict_track.GOLDEN_CAPS],
        })
    except Exception:  # noqa: BLE001 — thiếu predict_track thì bỏ kiểm tra, trang vẫn chạy
        return "null"


def render_html(
    all_data: list[dict],
    source: str = "vietlott_data.db",
    title: str = "Thống kê Vietlott",
    nav: str = "",
) -> str:
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        HTML_TEMPLATE
        .replace("%%DATA%%", json.dumps(all_data, ensure_ascii=False))
        .replace("%%GOLDEN%%", _golden_payload())
        .replace("%%GENERATED%%", generated)
        .replace("%%SOURCE%%", source)
        .replace("%%TITLE%%", title)
        .replace("%%NAV%%", nav)
        .replace("%%FAVICON%%", _favicon_tag())
    )


def _report_update(label: str, returncode: int, failed: list[str]) -> None:
    """Diễn giải mã thoát của crawler: 0 = OK, 2 = partial (đã lưu được), 1 = fail."""
    if returncode == 0:
        return
    if returncode == 2:
        print(
            f"⚠ Cào {label} bị gián đoạn giữa chừng nhưng ĐÃ LƯU được trang mới "
            f"(partial) — trang thống kê vẫn có dữ liệu mới."
        )
        return
    print(f"⚠ Cào {label} lỗi (mã {returncode}) — dùng dữ liệu cũ.")
    failed.append(label)


def run_update(game: str) -> list[str]:
    """Cào kỳ mới về DB trước khi sinh trang. Trả về danh sách game cào lỗi.

    Power 6/55 và Mega 6/45 nằm ở 2 DB riêng nên chạy SONG SONG được (đằng nào
    cũng chờ mạng là chính — thời gian chờ giảm gần một nửa). Game đầu in thẳng
    ra console để xem tiến trình; game sau gom output rồi in trọn sau đó cho
    khỏi lẫn dòng. Lỗi của một game không chặn việc sinh trang từ dữ liệu đã có.
    """
    failed: list[str] = []
    jobs: list[tuple[str, list[str]]] = []
    if game in ("power655", "all"):
        jobs.append(("Power 6/55", [str(BASE_DIR / "crawl.py")]))
    if game in ("mega645", "all"):
        jobs.append(("Mega 6/45", [str(BASE_DIR / "crawl_mega645.py")]))
    if not jobs:
        return failed

    # Khởi động các game SAU ở chế độ nền, gom output (nhỏ, không sợ đầy pipe).
    background: list[tuple[str, subprocess.Popen | None]] = []
    for label, cmd in jobs[1:]:
        try:
            proc = subprocess.Popen(
                [sys.executable, *cmd], cwd=str(BASE_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ Không khởi động được cào {label}: {type(exc).__name__}: {exc}")
            failed.append(label)
            proc = None
        background.append((label, proc))

    first_label, first_cmd = jobs[0]
    print(f"\n=== Cập nhật {first_label} ===", flush=True)
    try:
        rc = subprocess.run([sys.executable, *first_cmd], cwd=str(BASE_DIR)).returncode
        _report_update(first_label, rc, failed)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠ Cào {first_label} lỗi: {type(exc).__name__}: {exc}")
        failed.append(first_label)

    for label, proc in background:
        if proc is None:
            continue
        out, _ = proc.communicate()
        print(f"\n=== Cập nhật {label} (đã chạy song song) ===", flush=True)
        if out and out.strip():
            print(out.rstrip(), flush=True)
        _report_update(label, proc.returncode, failed)
    print()
    return failed


def _sinh_icon(path: Path) -> bool:
    """Vẽ icon quả cầu số nền đỏ Vietlott bằng PIL. Không có PIL -> False."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, size - 8, size - 8], radius=44,
                           fill=(200, 30, 45, 255))
    draw.ellipse([46, 46, 210, 210], fill=(255, 255, 255, 255))
    draw.ellipse([84, 84, 172, 172], fill=(200, 30, 45, 255))
    try:
        img.save(path, format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
        return True
    except Exception:
        return False


def _desktop_dir() -> Path:
    import ctypes
    from ctypes import wintypes

    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(0, 0, 0, 0, buf)  # CSIDL_DESKTOP=0
    return Path(buf.value or os.path.expanduser("~/Desktop"))


def _tao_lnk_shelllink(lnk: Path, target: str, args: str, workdir: Path,
                       icon: str, desc: str) -> None:
    """Tạo .lnk qua IShellLink + IPersistFile (API Unicode thật sự).

    WScript.Shell (cả pywin32 lẫn PowerShell) lưu đường dẫn theo ANSI codepage
    nên tên file có dấu tiếng Việt ngoài CP1252 bị nuốt: "Thống" -> "Th?ng".
    """
    import pythoncom
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None,
        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
    )
    link.SetPath(target)
    link.SetArguments(args)
    link.SetWorkingDirectory(str(workdir))
    link.SetDescription(desc)
    if icon:
        link.SetIconLocation(icon, 0)
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(lnk), 0)


def _tao_lnk_powershell(lnk: Path, target: str, args: str, workdir: Path,
                        icon: str, desc: str) -> None:
    """Dự phòng khi máy không có pywin32: tạo .lnk qua PowerShell."""
    ps = (
        "$s = New-Object -ComObject WScript.Shell; "
        "$sc = $s.CreateShortcut($env:LNK); "
        "$sc.TargetPath = $env:TGT; "
        "$sc.Arguments = $env:ARG; "
        "$sc.WorkingDirectory = $env:WRK; "
        "$sc.Description = $env:DSC; "
        "$sc.WindowStyle = 1; "
        + ("$sc.IconLocation = $env:ICO; " if icon else "")
        + "$sc.Save()"
    )
    env = dict(os.environ, LNK=str(lnk), TGT=target, ARG=args,
               WRK=str(workdir), DSC=desc)
    if icon:
        env["ICO"] = icon
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        env=env, check=True,
    )


def tao_shortcut() -> int:
    """Tạo shortcut Desktop: bấm 1 phát là cào kỳ mới rồi mở trang thống kê.

    Shortcut chỉ TRỎ tới file .py này, sửa code ở đây là áp dụng ngay. Dùng
    python.exe (không phải pythonw) để còn thấy tiến trình cào chạy tới đâu.
    """
    script = Path(__file__).resolve()
    args = f'"{script}" --update'
    icon = str(ICON_PATH) if (ICON_PATH.is_file() or _sinh_icon(ICON_PATH)) else ""
    desc = "Cập nhật kết quả Vietlott rồi mở trang thống kê"

    lnk = _desktop_dir() / SHORTCUT_NAME
    try:
        _tao_lnk_shelllink(lnk, sys.executable, args, BASE_DIR, icon, desc)
    except ImportError:  # không có pywin32
        _tao_lnk_powershell(lnk, sys.executable, args, BASE_DIR, icon, desc)

    print("Đã tạo shortcut:", lnk)
    print("  Trỏ tới     :", script, "(sửa code ở đây là áp dụng ngay)")
    print("  Bấm vào sẽ  : cào kỳ mới (Power + Mega) → sinh HTML → mở trình duyệt")
    if icon:
        print("  Icon        :", icon)
    return 0


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
        "--no-open",
        action="store_true",
        help="Chỉ tạo file, không tự mở trình duyệt.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Cào kỳ mới (crawl.py + crawl_mega645.py) trước khi sinh trang.",
    )
    parser.add_argument(
        "--tao-shortcut",
        action="store_true",
        help="Tạo shortcut '%s' ra Desktop rồi thoát." % SHORTCUT_NAME,
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
            "source": Path(db).name,
            "title": "Thống kê Mega 6/45",
            "nav": '<a class="btn" href="stats.html" '
                   'style="text-decoration:none">← Power 6/55</a>',
        })

    return specs


def build_page_data(db_path: str, game_types: list[str]) -> list[dict]:
    """Nạp dữ liệu cho 1 trang, tự hạ xuống loader nhẹ nếu DB thiếu bảng.

    Trang chỉ còn các mục không cần biểu đồ, nhưng payload vẫn phải có
    `frequency` / `positions` / `extra` vì sugEngine và phần mô phỏng đọc chúng.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        try:
            return load_all(conn, db_path, game_types)
        except sqlite3.OperationalError as exc:
            # DB chưa chạy number_stats bao giờ -> thiếu number_frequency /
            # position_*. Tính thẳng từ draw_results còn hơn không có trang nào.
            print(f"⚠ {Path(db_path).name}: {exc} — tính từ draw_results.")
            return load_all_minimal(conn, db_path, game_types)
    finally:
        conn.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = build_arg_parser().parse_args()

    if args.tao_shortcut:
        return tao_shortcut()

    ensure_dirs()

    failed_updates: list[str] = []
    if args.update:
        failed_updates = run_update(args.game or "all")

    written: list[Path] = []
    for spec in build_page_specs(args):
        if not Path(spec["db"]).exists():
            print(f"⚠ Không thấy DB {spec['db']} — bỏ qua {spec['games']}.")
            continue
        data = build_page_data(spec["db"], spec["games"])
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

    # Chạy từ shortcut: console đóng ngay sau khi mở trình duyệt, nên khi cào
    # lỗi phải dừng lại cho kịp đọc thông báo.
    if failed_updates:
        print(f"⚠ Không cập nhật được: {', '.join(failed_updates)}.")
        try:
            input("Nhấn Enter để đóng...")
        except (EOFError, KeyboardInterrupt):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
