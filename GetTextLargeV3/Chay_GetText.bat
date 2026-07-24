@echo off
rem ── Launcher 1-cu-nhap cho GetTextLargeV3 (chay tren MAY NAY) ──
rem Dung venv cha (..\venv) va mo GUI qua run_lnk.pyw (an cua so den).
setlocal
cd /d "%~dp0"
set "PYW=%~dp0..\venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo [LOI] Khong tim thay venv tai: %~dp0..\venv
  echo Du an nay can venv cha (co openai-whisper + torch) de chay.
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0run_lnk.pyw"
exit /b 0
