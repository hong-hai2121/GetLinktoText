@echo off
rem Mở cửa sổ trạng thái server ghép video (không hiện console); giao diện đầy đủ tự mở ở trình duyệt.
start "" "%~dp0..\venv\Scripts\pythonw.exe" "%~dp0app_gui.py"
