@echo off
setlocal
cd /d "%~dp0"
title Precision Multi-Instrument Lab Studio - One-time installation

echo.
echo Precision Multi-Instrument Lab Studio
echo One-time setup: build, test, and create desktop shortcuts.
echo After this completes, launch the app from the desktop or Start Menu.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" -CreateShortcuts -Launch
if errorlevel 1 (
    echo.
    echo INSTALLATION FAILED.
    echo Keep this window open and send the screenshot plus the newest log in:
    echo %LOCALAPPDATA%\Precision Multi-Instrument Lab Studio\install_logs
    pause
    exit /b 1
)

echo.
echo Installation complete. You can close this window.
timeout /t 3 >nul
endlocal
