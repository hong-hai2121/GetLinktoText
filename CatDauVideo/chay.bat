@echo off
rem Cat doan doc tieu de lap o dau video.
rem   Bam dup             -> mo giao dien (bang cac dong cua Sheet, tick dong can chay).
rem   chay.bat --dong 2-6 -> chay bang dong lenh, khong mo giao dien (xem dau file cat_dau.py).
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
    start "" "..\venv\Scripts\pythonw.exe" -X utf8 giao_dien.py
    exit /b
)
"..\venv\Scripts\python.exe" -X utf8 cat_dau.py %*
echo.
pause
