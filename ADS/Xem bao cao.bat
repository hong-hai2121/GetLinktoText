@echo off
chcp 65001 >nul
cd /d "%~dp0"
python xem_ads.py %*
if errorlevel 1 pause
