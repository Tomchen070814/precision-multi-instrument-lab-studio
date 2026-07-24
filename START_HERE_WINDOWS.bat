@echo off
setlocal
cd /d "%~dp0"
set "APP_EXE=%LOCALAPPDATA%\Programs\Precision Multi-Instrument Lab Studio\Precision-Multi-Instrument-Lab-Studio.exe"

if exist "%APP_EXE%" (
    start "" "%APP_EXE%"
    exit /b 0
)

set "APP_EXE=%~dp0dist\Precision-Multi-Instrument-Lab-Studio.exe"
if exist "%APP_EXE%" (
    start "" "%APP_EXE%"
    exit /b 0
)

echo The application has not been installed on this computer yet.
echo Starting the one-time installer...
call "%~dp0INSTALL_ONCE_WINDOWS.bat"
endlocal
