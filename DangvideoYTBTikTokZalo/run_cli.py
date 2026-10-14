# -*- coding: utf-8 -*-
"""Đăng video YouTube từ dòng lệnh (không cần GUI).

Ví dụ:
  python run_cli.py --video "C:\\...\\video.mp4" --title "tiêu đề" --desc "nội dung" ^
      --playlist "Dạ dày tiêu hóa" --tags "test 1, test 2" --visibility PRIVATE
Link Drive: thay --video bằng --drive "https://drive.google.com/file/d/..."
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import chrome_cdp
import youtube_upload
from drive_download import download_drive


def main():
    ap = argparse.ArgumentParser(description="Đăng video YouTube tự động qua CDP")
    ap.add_argument("--video", help="Đường dẫn file video trên máy")
    ap.add_argument("--drive", help="Link Google Drive của video")
    ap.add_argument("--title", required=True, help="Tiêu đề video")
    ap.add_argument("--desc", default="", help="Nội dung mô tả")
    ap.add_argument("--playlist", default="", help="Tên danh sách phát")
    ap.add_argument("--tags", default="", help="Các thẻ, cách nhau dấu phẩy")
    ap.add_argument("--visibility", default="PRIVATE",
                    choices=["PRIVATE", "UNLISTED", "PUBLIC"], help="Chế độ hiển thị")
    ap.add_argument("--kids", action="store_true", help="Video dành cho trẻ em")
    ap.add_argument("--dry-run", action="store_true",
                    help="Chạy thử: làm hết các bước (kể cả chế độ hiển thị) rồi dừng, KHÔNG bấm Lưu")
    ap.add_argument("--check-login", action="store_true",
                    help="Chỉ kiểm tra đăng nhập YouTube Studio rồi thoát")
    ap.add_argument("--token", default="",
                    help="Token Playwright Extension (PLAYWRIGHT_MCP_EXTENSION_TOKEN=...), lưu vào config.json")
    args = ap.parse_args()

    log = print
    cfg = chrome_cdp.load_config()
    if args.token:
        cfg["extension_token"] = chrome_cdp.normalize_token(args.token)
        chrome_cdp.save_config(cfg)
        log("✓ Đã lưu token extension vào config.json.")

    chrome_cdp.launch_chrome(cfg, log=log)
    pw, browser, page = chrome_cdp.connect_playwright(cfg, log=log)

    try:
        if args.check_login:
            page.goto("https://studio.youtube.com/", wait_until="domcontentloaded",
                      timeout=60000)
            page.wait_for_timeout(5000)
            url = page.url
            log(f"URL hiện tại: {url}")
            if "accounts.google.com" in url:
                log("❌ CHƯA đăng nhập — hãy đăng nhập Google trong cửa sổ Chrome này.")
            else:
                try:
                    name = page.locator("#account-name, ytcp-navigation-drawer "
                                        "#entity-name").first.inner_text(timeout=10000)
                    log(f"✓ ĐÃ đăng nhập — kênh: {name.strip()}")
                except Exception:
                    log("✓ Đã vào được Studio (không đọc được tên kênh).")
            return

        if args.drive:
            video_path = download_drive(args.drive, log=log)
        elif args.video:
            video_path = args.video
            if not os.path.isfile(video_path):
                raise FileNotFoundError(f"Không thấy file: {video_path}")
        else:
            ap.error("Cần --video hoặc --drive")

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        youtube_upload.upload_video(
            page, video_path, args.title, args.desc,
            playlist=args.playlist or None, tags=tags,
            visibility=args.visibility, made_for_kids=args.kids, log=log,
            dry_run=args.dry_run)
    finally:
        chrome_cdp.disconnect(pw)  # ngắt Playwright + relay; Chrome và tab vẫn mở


if __name__ == "__main__":
    main()
