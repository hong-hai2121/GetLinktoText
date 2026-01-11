import threading

from src import browser_client
from src import config
from src import io
from src.gui import GetTextApp


def launch_gui():
    def open_firefox_async():
        """Mở Firefox trong background thread (an toàn, không mở trùng)."""
        with browser_client.DRIVER_LOCK:
            if browser_client.is_driver_alive(browser_client.global_driver):
                print("✅ Firefox đã sẵn sàng (đã có driver).")
                browser_client.FIREFOX_INIT_EVENT.set()
                return
            if browser_client.FIREFOX_INIT_IN_PROGRESS:
                print("⏳ Firefox đang được khởi tạo, không mở thêm.")
                return
            browser_client.FIREFOX_INIT_IN_PROGRESS = True
            browser_client.FIREFOX_INIT_EVENT.clear()

        try:
            print("🌐 Đang mở Firefox...")
            drv = browser_client.init_firefox()
            with browser_client.DRIVER_LOCK:
                browser_client.global_driver = drv
            print("✅ Firefox đã sẵn sàng!")
        except Exception as e:
            print(f"❌ Lỗi mở Firefox: {e}")
        finally:
            with browser_client.DRIVER_LOCK:
                browser_client.FIREFOX_INIT_IN_PROGRESS = False
            browser_client.FIREFOX_INIT_EVENT.set()

    firefox_thread = threading.Thread(target=open_firefox_async, daemon=True)
    firefox_thread.start()

    print("🎨 Đang khởi động giao diện...")
    import tkinter as tk

    root = tk.Tk()
    app = GetTextApp(root)
    root.mainloop()


def main():
    if config.FFMPEG_PATH is None:
        print("⚠️ ffmpeg không có trong PATH. Hãy cài đặt ffmpeg để tiếp tục.")
        raise SystemExit(1)

    config.ensure_directories()
    io.clear_output_directory(config.OUTPUT_VIDEO_DIR)
    launch_gui()


if __name__ == "__main__":
    main()
