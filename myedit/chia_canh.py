# -*- coding: utf-8 -*-
"""Bước 2 — Chia transcript thành các CẢNH + từ khóa tìm ảnh minh họa.

Có GEMINI_API_KEY trong .env gốc repo → gọi thẳng Gemini API:
    python chia_canh.py mau/transcript.json

Chưa có key → xuất prompt ra file, tự dán vào Gemini/ChatGPT trên web,
lưu JSON trả về rồi nhập lại:
    python chia_canh.py mau/transcript.json --xuat-prompt
    python chia_canh.py mau/transcript.json --nhap mau/tra_loi.json

Kết quả: canh.json nằm cùng thư mục với transcript.
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cauhinh import key

GEMINI_MODEL_MAC_DINH = "gemini-2.5-flash"


def tao_prompt(tr: dict) -> str:
    dur = tr["thoi_luong"]
    dong = "\n".join(
        f"[{d['bat_dau']}-{d['ket_thuc']}] {d['noi_dung']}" for d in tr["doan"]
    )
    return f"""Bạn là đạo diễn dựng video. Dưới đây là transcript của một audio dài {dur} giây, mỗi dòng có mốc thời gian [bắt_đầu-kết_thúc] tính bằng giây.

Nhiệm vụ: chia TOÀN BỘ audio thành các CẢNH liên tiếp nhau, mỗi cảnh dài 8-20 giây. Cảnh sau phải bắt đầu đúng lúc cảnh trước kết thúc, cảnh đầu bắt đầu tại 0, cảnh cuối kết thúc tại {dur}. Mỗi cảnh sẽ được minh họa bằng 1 ảnh tìm trên kho ảnh stock.

Trả về DUY NHẤT một mảng JSON (không giải thích gì thêm), mỗi phần tử có dạng:
{{"bat_dau": <giây>, "ket_thuc": <giây>, "y_chinh": "<tóm tắt ngắn nội dung cảnh bằng tiếng Việt>", "tu_khoa_anh": "<3-6 từ khóa TIẾNG ANH để tìm ảnh stock, cụ thể và giàu hình ảnh, ví dụ: laptop facebook ads dashboard office>"}}

Transcript:
{dong}
"""


def goi_gemini(prompt: str, api_key: str) -> str:
    import requests

    model = key("GEMINI_MODEL") or GEMINI_MODEL_MAC_DINH
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    print(f"🤖 Gọi Gemini API ({model})...")
    r = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": 65536,
                "temperature": 0.4,
            },
        },
        timeout=600,
    )
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def boc_json(text: str) -> list:
    """Bóc mảng JSON khỏi câu trả lời (bỏ rào ```json nếu có)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    dau = text.find("[")
    cuoi = text.rfind("]")
    if dau == -1 or cuoi == -1:
        raise ValueError("Không tìm thấy mảng JSON trong câu trả lời")
    return json.loads(text[dau:cuoi + 1])


def chuan_hoa(canh_raw: list, thoi_luong: float) -> list:
    """Kiểm tra + vá các cảnh: sắp xếp, khớp mốc nối nhau, đánh số thứ tự."""
    canh = []
    for c in canh_raw:
        try:
            bd = float(c["bat_dau"])
            kt = float(c["ket_thuc"])
            tk = str(c["tu_khoa_anh"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if kt <= bd or not tk:
            continue
        canh.append({
            "bat_dau": round(bd, 2),
            "ket_thuc": round(min(kt, thoi_luong), 2),
            "y_chinh": str(c.get("y_chinh", "")).strip(),
            "tu_khoa_anh": tk,
        })
    canh.sort(key=lambda c: c["bat_dau"])
    if not canh:
        raise ValueError("Không có cảnh hợp lệ nào")
    # Vá cho liền mạch: cảnh đầu về 0, cảnh sau nối đúng cảnh trước, cảnh cuối chạm hết audio
    canh[0]["bat_dau"] = 0.0
    for i in range(1, len(canh)):
        canh[i]["bat_dau"] = canh[i - 1]["ket_thuc"]
        if canh[i]["ket_thuc"] <= canh[i]["bat_dau"]:
            canh[i]["ket_thuc"] = round(canh[i]["bat_dau"] + 1, 2)
    canh[-1]["ket_thuc"] = thoi_luong
    for i, c in enumerate(canh, 1):
        c["tt"] = i
    return canh


def chia_canh(transcript: Path, xuat_prompt: bool = False, nhap: Path | None = None) -> Path | None:
    tr = json.loads(transcript.read_text(encoding="utf-8"))
    ra = transcript.parent / "canh.json"

    if nhap:
        text = nhap.read_text(encoding="utf-8")
    elif xuat_prompt or not key("GEMINI_API_KEY"):
        f = transcript.parent / "prompt_chia_canh.txt"
        f.write_text(tao_prompt(tr), encoding="utf-8")
        print(f"📝 Chưa có GEMINI_API_KEY — đã ghi prompt ra:\n   {f}")
        print("   → Dán vào Gemini/ChatGPT trên web, lưu JSON trả về thành file,")
        print(f"   rồi chạy: python chia_canh.py {transcript} --nhap <file JSON>")
        return None
    else:
        text = goi_gemini(tao_prompt(tr), key("GEMINI_API_KEY"))

    canh = chuan_hoa(boc_json(text), tr["thoi_luong"])
    ra.write_text(json.dumps({
        "audio": tr["audio"],
        "thoi_luong": tr["thoi_luong"],
        "canh": canh,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {len(canh)} cảnh → {ra}")
    return ra


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Chia transcript thành cảnh + từ khóa ảnh")
    ap.add_argument("transcript", help="đường dẫn transcript.json")
    ap.add_argument("--xuat-prompt", action="store_true", help="chỉ xuất prompt ra file để dán tay")
    ap.add_argument("--nhap", help="file JSON trả lời (khi dán tay từ web)")
    a = ap.parse_args()
    chia_canh(Path(a.transcript).resolve(), a.xuat_prompt,
              Path(a.nhap).resolve() if a.nhap else None)
