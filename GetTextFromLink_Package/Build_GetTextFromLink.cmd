@echo off
cd /d "%~dp0"
py -3.12 packaging\build_installer.py
if errorlevel 1 (
    echo Build failed. Read the error above.
) else (
    echo Installer is in dist\installer.
)
pause
