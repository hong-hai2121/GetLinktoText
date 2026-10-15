@echo off
rem Mở cửa sổ trạng thái server đăng video (không hiện console).
start "" "%~dp0..\venv\Scripts\pythonw.exe" "%~dp0app_gui.py"
