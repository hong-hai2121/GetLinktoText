#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from typing import Any, List, Union, Optional

# =============================
# 🔧 CẤU HÌNH
# =============================
JSON_FILE_PATH = r"C:\Users\PC\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\10\draft_content.json"

# 1) Match volume (so as string for CapCut float)
TARGET_KEY = "volume"
TARGET_VALUE_STR = "2.818382740020752"

# 2) Optional filters (set to None to disable)
ONLY_TRACK_INDEX = 3              # e.g. 3 to only keep $.tracks[3], set None to disable
ONLY_SEGMENT_INDEX = None         # e.g. 48 to only keep $.tracks[3].segments[48], set None to disable
ONLY_SEGMENT_PATH = None          # e.g. "$.tracks[3].segments[48]", set None to disable
ONLY_SEGMENT_ID = None            # e.g. "67C8F312-....", set None to disable
ONLY_MATERIAL_ID = None           # e.g. "403A85F1-....", set None to disable
ONLY_TARGET_START = None          # e.g. 1900000, set None to disable (will compare as int)

MAX_RESULTS = 200                 # set None to export all
OUTPUT_FILE_NAME = "result.json"
# =============================

Json = Union[dict, list, str, int, float, bool, None]


def fmt_path(path: List[Union[str, int]]) -> str:
    out = "$"
    for p in path:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += f".{p}"
    return out


def get_node_by_list_path(root: Json, path: List[Union[str, int]]) -> Optional[Json]:
    cur: Json = root
    try:
        for p in path:
            if isinstance(p, int):
                if not isinstance(cur, list):
                    return None
                cur = cur[p]
            else:
                if not isinstance(cur, dict):
                    return None
                cur = cur[p]
        return cur
    except Exception:
        return None


def walk_json(data: Json):
    stack = [([], data)]
    while stack:
        path, node = stack.pop()

        if isinstance(node, dict):
            if TARGET_KEY in node and str(node[TARGET_KEY]) == TARGET_VALUE_STR:
                yield path, node

            for k, v in node.items():
                stack.append((path + [k], v))

        elif isinstance(node, list):
            for i, v in enumerate(node):
                stack.append((path + [i], v))


def main():
    if not os.path.exists(JSON_FILE_PATH):
        print("❌ Không tìm thấy file JSON:", JSON_FILE_PATH)
        return

    with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []

    for match_path, seg in walk_json(data):
        # segment should be at $.tracks[i].segments[j]
        if not (len(match_path) >= 4 and match_path[-4] == "tracks" and isinstance(match_path[-3], int) and match_path[-2] == "segments" and isinstance(match_path[-1], int)):
            continue

        track_index = match_path[-3]
        segment_index = match_path[-1]
        track_path = match_path[:-2]  # ['tracks', i]

        segment_path_str = fmt_path(match_path)
        track_path_str = fmt_path(track_path)

        # ---- Apply filters ----
        if ONLY_TRACK_INDEX is not None and track_index != ONLY_TRACK_INDEX:
            continue
        if ONLY_SEGMENT_INDEX is not None and segment_index != ONLY_SEGMENT_INDEX:
            continue
        if ONLY_SEGMENT_PATH is not None and segment_path_str != ONLY_SEGMENT_PATH:
            continue
        if ONLY_SEGMENT_ID is not None and seg.get("id") != ONLY_SEGMENT_ID:
            continue
        if ONLY_MATERIAL_ID is not None and seg.get("material_id") != ONLY_MATERIAL_ID:
            continue
        if ONLY_TARGET_START is not None:
            tt = seg.get("target_timerange") or {}
            if not isinstance(tt, dict) or tt.get("start") != ONLY_TARGET_START:
                continue
        # -----------------------

        track_obj = get_node_by_list_path(data, track_path)
        item = {
            "segment_path": segment_path_str,
            "track_path": track_path_str,
            "track_id": track_obj.get("id") if isinstance(track_obj, dict) else None,
            "segment_id": seg.get("id"),
            "material_id": seg.get("material_id"),
            "volume": seg.get("volume"),
            "target_timerange": seg.get("target_timerange"),
            "source_timerange": seg.get("source_timerange"),
            "segment_object": seg,
            "track_object": track_obj if isinstance(track_obj, dict) else None,
        }

        items.append(item)

        if MAX_RESULTS is not None and len(items) >= MAX_RESULTS:
            break

    output_path = os.path.join(os.path.dirname(JSON_FILE_PATH), OUTPUT_FILE_NAME)
    payload = {
        "query": {
            "file": JSON_FILE_PATH,
            "match": {TARGET_KEY: TARGET_VALUE_STR},
            "filters": {
                "ONLY_TRACK_INDEX": ONLY_TRACK_INDEX,
                "ONLY_SEGMENT_INDEX": ONLY_SEGMENT_INDEX,
                "ONLY_SEGMENT_PATH": ONLY_SEGMENT_PATH,
                "ONLY_SEGMENT_ID": ONLY_SEGMENT_ID,
                "ONLY_MATERIAL_ID": ONLY_MATERIAL_ID,
                "ONLY_TARGET_START": ONLY_TARGET_START,
            }
        },
        "total_exported": len(items),
        "items": items
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("✅ DONE")
    print(f"🔎 Exported: {len(items)} match(es)")
    print(f"📄 Output: {output_path}")

    # Quick summary table (first 10)
    if items:
        print("\n--- Quick view (first 10) ---")
        for i, it in enumerate(items[:10]):
            tt = it.get("target_timerange") or {}
            print(f"[{i}] {it['segment_path']} | seg_id={it['segment_id']} | start={tt.get('start')} | dur={tt.get('duration')} | mat={it['material_id']}")


if __name__ == "__main__":
    main()
