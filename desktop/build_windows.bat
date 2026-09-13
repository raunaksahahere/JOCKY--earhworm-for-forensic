@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
if errorlevel 1 (
  echo.
  echo JOCKY build failed.
  pause
  exit /b 1
)
echo.
echo JOCKY build completed successfully.
pause
