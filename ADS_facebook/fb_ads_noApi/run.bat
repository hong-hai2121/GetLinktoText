@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if exist "..\..\venv\Scripts\python.exe" (
  "..\..\venv\Scripts\python.exe" -u fb_billing_import_web.py
) else (
  python -u fb_billing_import_web.py
)
if errorlevel 1 pause
