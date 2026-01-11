import re

import yt_dlp
from src.notifications import play_sound


def get_video_title_facebook(url, browser=None):  # vẫn giữ tham số browser để tương thích code cũ
    """
    Lấy tiêu đề video Facebook bằng yt_dlp mà không cần dùng trình duyệt Selenium.
    """
    try:
        print(f"🔍 Đang xử lý: {url}")
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("description", "Video không có tiêu đề")
            print(f"🎬 Tiêu đề gốc: {title}")

            # Làm sạch tiêu đề
            title_cleaned = title

            # Xóa từ đầu đến "views"
            title_cleaned = re.sub(r"^.*?views", "", title_cleaned, flags=re.IGNORECASE)

            # Xóa tiếp từ đầu đến "reaction" hoặc "reactions"
            title_cleaned = re.sub(r"^.*?reactions?", "", title_cleaned, flags=re.IGNORECASE)

            # Xóa ký tự không hợp lệ trong tên file
            title = re.sub(r"[\\/*?:\"<>|]", "", title_cleaned).strip()

            print(f"✅ Tiêu đề đã làm sạch: {title}")
            return title

    except Exception as e:
        print(f"❌ Lỗi khi lấy tiêu đề bằng yt_dlp: {e}")
        return "Không thể lấy tiêu đề"


def get_facebook_video_url(video_url):
    """Lấy URL thực tế của video Facebook bằng yt-dlp"""
    try:
        ydl_opts = {"quiet": True, "format": "bestaudio/best"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info["url"]
    except Exception as e:
        print(f"❌ Lỗi khi lấy video URL: {e}")
        play_sound("error")
        return None


def download_video(video_url, output_path):
    """Tải video về thư mục output_video"""
    try:
        ydl_opts = {"quiet": True, "outtmpl": output_path}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
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
