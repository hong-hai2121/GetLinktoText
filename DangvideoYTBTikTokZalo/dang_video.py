# -*- coding: utf-8 -*-
"""Đăng / lên lịch MỘT video lên YouTube, TikTok, Zalo (chọn 1 hoặc cả 3) từ dòng lệnh.

Chạy đủ các bước đã chốt với user (15/10/2026):
  YouTube : tiêu đề + mô tả đầy đủ + thẻ (<= 500 ký tự) + danh sách phát + lên lịch (Studio mới).
  TikTok  : mô tả = tiêu đề (1 dòng) + từng hashtag gõ + Enter; lên lịch (bước 5 phút).
  Zalo    : nội dung = tiêu đề + hashtag; hẹn giờ; nút Đăng video của form.
Hashtag cho TikTok/Zalo: --hashtag "#a #b" hoặc tự lấy dòng cuối của mô tả nếu dòng đó toàn hashtag.

Ví dụ:
  python dang_video.py --nen-tang youtube tiktok zalo ^
      --video "C:\\Users\\PC\\Downloads\\clip.mp4" ^
      --tieu-de "2 Cốc Nước ... | Bác sĩ Hội" --mo-ta-file mo_ta.txt ^
      --the "cách giảm trào ngược, bác sĩ hội" --playlist "Dạ dày tiêu hóa" ^
      --lich "2026-10-16 08:00" [--chay-thu]
Trình duyệt/profile/token từng nền tảng lấy ở config.json mục "platforms" (chrome_cdp.platform_config).
Mỗi nền tảng: mở relay -> extension nối -> Playwright điều khiển 1 tab mới -> làm xong thì ngắt.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import chrome_cdp
from dang_common import hashtags_from_text


def chay_mot(nen_tang, args, log):
    cfg = chrome_cdp.platform_config(chrome_cdp.load_config(), nen_tang)
    log(f"\n===== {nen_tang.upper()} — profile '{cfg['profile_dir']}' =====")
    chrome_cdp.launch_chrome(cfg, log)
    pw, _browser, page = chrome_cdp.connect_playwright(cfg, log)
    xong = False
    try:
        lich = datetime.strptime(args.lich, "%Y-%m-%d %H:%M") if args.lich else None
        mo_ta = Path(args.mo_ta_file).read_text(encoding="utf-8-sig").strip() if args.mo_ta_file else (args.mo_ta or "")
        hashtags = args.hashtag.split() if args.hashtag else hashtags_from_text(mo_ta)
        if nen_tang == "youtube":
            import youtube_upload
            the = [t.strip() for t in (args.the or "").split(",") if t.strip()]
            kq = youtube_upload.upload_video(
                page, args.video, args.tieu_de, mo_ta, playlist=args.playlist or None, tags=the,
                visibility="SCHEDULE" if lich else args.che_do, schedule_at=lich,
                made_for_kids=False, log=log, dry_run=args.chay_thu)
        elif nen_tang == "tiktok":
            import tiktok_upload
            kq = tiktok_upload.upload_video(page, args.video, args.tieu_de, hashtags,
                                            schedule_at=lich, log=log, dry_run=args.chay_thu)
        else:
            import zalo_upload
            kq = zalo_upload.upload_video(page, args.video, args.tieu_de, hashtags,
                                          schedule_at=lich, log=log, dry_run=args.chay_thu)
        xong = True
        return kq
    finally:
        if args.chay_thu or not xong:
            # chạy thử hoặc LỖI: để tab mở cho bạn xem (popup, form...), chỉ ngắt Playwright
            log("(" + ("chạy thử" if args.chay_thu else "có lỗi") + ": tab để mở cho bạn kiểm tra)")
            time.sleep(3)
            chrome_cdp.disconnect(pw)
        else:
            chrome_cdp.disconnect(pw, page=page)     # xong việc: đóng tab điều khiển


def main():
    ap = argparse.ArgumentParser(description="Đăng/lên lịch video lên YouTube, TikTok, Zalo")
    ap.add_argument("--nen-tang", nargs="+", choices=["youtube", "tiktok", "zalo"], required=True)
    ap.add_argument("--video", required=True, help="đường dẫn file video trên máy")
    ap.add_argument("--tieu-de", required=True, help="tiêu đề (TikTok/Zalo dùng làm nội dung 1 dòng)")
    ap.add_argument("--mo-ta", default="", help="mô tả YouTube (chuỗi)")
    ap.add_argument("--mo-ta-file", help="file .txt chứa mô tả YouTube (ưu tiên hơn --mo-ta)")
    ap.add_argument("--the", default="", help="thẻ YouTube, cách nhau dấu phẩy (tổng <= 500 ký tự)")
    ap.add_argument("--hashtag", default="", help="hashtag cho TikTok/Zalo, cách nhau dấu cách; trống = lấy dòng cuối mô tả")
    ap.add_argument("--playlist", default="", help="danh sách phát YouTube")
    ap.add_argument("--lich", help="giờ công khai 'YYYY-MM-DD HH:MM' (trống = đăng ngay / riêng tư)")
    ap.add_argument("--che-do", default="PRIVATE", choices=["PRIVATE", "UNLISTED", "PUBLIC"],
                    help="chế độ YouTube khi KHÔNG lên lịch (mặc định PRIVATE)")
    ap.add_argument("--chay-thu", action="store_true", help="làm hết các bước nhưng DỪNG trước nút đăng/lên lịch cuối")
    args = ap.parse_args()
    if not Path(args.video).exists():
        sys.exit(f"Không thấy file video: {args.video}")

    log = print
    ket_qua = {}
    for nt in args.nen_tang:
        try:
            ket_qua[nt] = ("OK", chay_mot(nt, args, log))
        except Exception as e:          # noqa: BLE001
            ket_qua[nt] = ("LỖI", str(e)[:300])
            log(f"✗ {nt}: {e}")
    log("\n===== KẾT QUẢ =====")
    for nt, (tt, chi_tiet) in ket_qua.items():
        log(f"  {nt:8s} {tt}: {chi_tiet}")
    if any(tt == "LỖI" for tt, _ in ket_qua.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
