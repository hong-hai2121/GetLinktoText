from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# 📌 Đặt đường dẫn ChromeDriver mới
chromedriver_path = r"D:\Tools\chromedriver.exe"

# ✅ Cấu hình ChromeOptions
chrome_options = Options()
chrome_options.add_argument("--headless")  # Chạy không giao diện
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920x1080")

# ✅ Sử dụng ChromeDriver mới
service = Service(chromedriver_path)
driver = webdriver.Chrome(service=service, options=chrome_options)

print("✅ ChromeDriver khởi động thành công với Chrome 133!")
driver.quit()
