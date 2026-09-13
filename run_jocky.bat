@echo off
setlocal
cd /d "%~dp0"
if exist "JOCKY.exe" (
    start "" "JOCKY.exe"
    exit /b 0
)
if exist "desktop-app\release\JOCKY-1.0.0-Windows-x64.exe" (
    start "" "desktop-app\release\JOCKY-1.0.0-Windows-x64.exe"
    exit /b 0
)
echo JOCKY executable not found.
echo Build it first with: desktop\build_windows.bat
pause
