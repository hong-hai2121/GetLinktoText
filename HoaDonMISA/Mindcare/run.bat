@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%venv\Scripts\pythonw.exe"
set "VENV_PY_CON=%SCRIPT_DIR%venv\Scripts\python.exe"
set "GUI=%SCRIPT_DIR%gui.py"

:: ── 1. Venv sẵn có và dùng được ─────────────────────────────────────────────
"%VENV_PY_CON%" --version > nul 2>&1
if %errorlevel% == 0 (
    start "" "%VENV_PYTHON%" "%GUI%"
    exit /b 0
)

echo ============================================================
echo   Mindcare ^| Khoi tao lan dau
echo ============================================================
echo.

:: ── 2. Tìm Python hệ thống ───────────────────────────────────────────────────
call :find_python
if defined SYSTEM_PY goto :setup_venv

:: ── 3. Tự cài Python qua winget ──────────────────────────────────────────────
echo  [1/3] Khong tim thay Python. Dang tu dong cai Python 3.11...
echo.
winget --version > nul 2>&1
if %errorlevel% == 0 (
    echo  Dung winget de cai Python...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    :: Tìm lại sau khi cài
    call :find_python_after_install
    if defined SYSTEM_PY goto :setup_venv
)

:: ── 4. Winget không có / thất bại → tải installer thủ công ──────────────────
echo  Dang tai Python installer tu python.org (~25MB)...
set "PY_INSTALLER=%TEMP%\python_installer.exe"
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%PY_INSTALLER%' -UseBasicParsing"
if not exist "%PY_INSTALLER%" (
    echo.
    echo  [LOI] Khong tai duoc Python. Kiem tra ket noi mang.
    echo  Cai thu cong tai: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  Dang cai Python (khong can quyen Admin)...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0
del "%PY_INSTALLER%" > nul 2>&1

:: Tìm lại sau khi cài thủ công
call :find_python_after_install
if not defined SYSTEM_PY (
    echo.
    echo  [LOI] Cai Python that bai. Vui long cai thu cong.
    pause
    exit /b 1
)

:: ── Setup venv ────────────────────────────────────────────────────────────────
:setup_venv
echo  [2/3] Tao moi truong ao (venv)...
"%SYSTEM_PY%" -m venv "%SCRIPT_DIR%venv"
if errorlevel 1 (
    echo  [LOI] Tao venv that bai.
    pause
    exit /b 1
)

echo  [3/3] Cai thu vien can thiet...
"%VENV_PY_CON%" -m pip install --quiet --upgrade pip
"%VENV_PY_CON%" -m pip install --quiet -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 (
    echo  [LOI] Cai thu vien that bai.
    pause
    exit /b 1
)

echo.
echo  Hoan tat! Dang khoi dong ung dung...
echo.
start "" "%VENV_PYTHON%" "%GUI%"
exit /b 0

:: ── Hàm tìm Python ───────────────────────────────────────────────────────────
:find_python
set "SYSTEM_PY="
for %%P in (python python3 py) do (
    if not defined SYSTEM_PY (
        where %%P > nul 2>&1
        if not errorlevel 1 (
            for /f "delims=" %%V in ('%%P --version 2^>^&1') do (
                echo %%V | findstr /r "3\.[89]\. 3\.1[0-9]\." > nul
                if not errorlevel 1 set "SYSTEM_PY=%%P"
            )
        )
    )
)
exit /b 0

:find_python_after_install
set "SYSTEM_PY="
:: Đường dẫn cài user (không cần Admin)
set "USER_PY=%LOCALAPPDATA%\Programs\Python"
for /d %%D in ("%USER_PY%\Python3*") do (
    if exist "%%D\python.exe" (
        if not defined SYSTEM_PY set "SYSTEM_PY=%%D\python.exe"
    )
)
:: Đường dẫn cài system (Admin)
if not defined SYSTEM_PY (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if exist "%%D\python.exe" (
            set "SYSTEM_PY=%%D\python.exe"
        )
    )
)
:: Thử lại PATH (sau khi PrependPath=1 có hiệu lực trong phiên mới)
if not defined SYSTEM_PY call :find_python
exit /b 0
