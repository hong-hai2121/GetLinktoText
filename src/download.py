import re

import yt_dlp
from src.notifications import play_sound
from src import config as src_config


def _ydl_opts_with_cookies(base_opts: dict | None = None) -> dict:
    opts = base_opts.copy() if base_opts else {}
    if src_config.COOKIES_BROWSER:
        opts["cookiesfrombrowser"] = (src_config.COOKIES_BROWSER,)
    return opts


def _extract_info_with_cookie_fallback(ydl_opts: dict, url: str, download: bool = False):
    """Try with browser cookies first; if cookie extraction fails, retry without cookies."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=download)
    except Exception as e:
        err = str(e)
        if "cookie" in err.lower() or "Could not copy" in err:
            print(f"⚠️ Cookie extraction failed, retrying without cookies...")
            opts_no_cookie = {k: v for k, v in ydl_opts.items() if k != "cookiesfrombrowser"}
            with yt_dlp.YoutubeDL(opts_no_cookie) as ydl:
                return ydl.extract_info(url, download=download)
        raise


def get_video_title_facebook(url, browser=None):  # vẫn giữ tham số browser để tương thích code cũ
    """
    Lấy tiêu đề video Facebook bằng yt_dlp mà không cần dùng trình duyệt Selenium.
    """
    try:
        print(f"🔍 Đang xử lý: {url}")
        info = _extract_info_with_cookie_fallback(_ydl_opts_with_cookies(), url)
        title = info.get("description", "Video không có tiêu đề")
        print(f"🎬 Tiêu đề gốc: {title}")

        title_cleaned = title
        title_cleaned = re.sub(r"^.*?views", "", title_cleaned, flags=re.IGNORECASE)
        title_cleaned = re.sub(r"^.*?reactions?", "", title_cleaned, flags=re.IGNORECASE)
        title = re.sub(r"[\\/*?:\"<>|]", "", title_cleaned).strip()

        print(f"✅ Tiêu đề đã làm sạch: {title}")
        return title

    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề bằng yt_dlp: {e}")
        return "Không thể lấy tiêu đề"


def get_facebook_video_url(video_url):
    """Lấy URL thực tế của video Facebook bằng yt-dlp"""
    try:
        ydl_opts = _ydl_opts_with_cookies({"quiet": True, "format": "bestaudio/best"})
        info = _extract_info_with_cookie_fallback(ydl_opts, video_url)
        return info["url"]
    except Exception as e:
        print(f"❌ Lỗi khi lấy video URL: {e}")
        play_sound("error")
        return None


def get_video_duration_seconds(video_url):
    try:
        ydl_opts = _ydl_opts_with_cookies({"quiet": True, "noplaylist": True})
        info = _extract_info_with_cookie_fallback(ydl_opts, video_url)
        duration = info.get("duration")
        if duration is None:
            return None
        return float(duration)
    except Exception as e:
        print(f"⚠️ Khong lay duoc thoi luong video: {e}")
        return None


def download_video(video_url, output_path):
    """Tải video về thư mục output_video"""
    try:
        ydl_opts = _ydl_opts_with_cookies({"quiet": True, "outtmpl": output_path})
        _extract_info_with_cookie_fallback(ydl_opts, video_url, download=True)
        print("✅ Video đã được tải xuống thành công.")
        return output_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
        play_sound("error")
        return None


def download_videoTIKTOK(video_url, output_path):
    """Tải video TikTok bằng cookies từ Firefox (đăng nhập sẵn)"""
    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
        "cookiesfrombrowser": ("firefox",),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print(f"✅ Video đã tải thành công: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Lỗi khi tải video: {e}")
        play_sound("error")
        return None


def is_tiktok_link(url):
    """Kiểm tra xem một URL có phải là liên kết TikTok hay không"""
    tiktok_pattern = re.compile(r"tiktok", re.IGNORECASE)
    return bool(tiktok_pattern.search(url))
