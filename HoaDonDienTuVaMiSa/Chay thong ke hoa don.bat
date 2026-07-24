@echo off
chcp 65001 >nul
cd /d "%~dp0"
python hoa_don_stats_web.py
if errorlevel 1 (
  echo.
  echo Co loi khi chay thong ke.
  pause
)
