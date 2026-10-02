@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" serve %*
set "SLOI_EXIT=%ERRORLEVEL%"
if not "%SLOI_EXIT%"=="0" echo SLOI returned status %SLOI_EXIT%. Read the diagnostic report above.
pause
exit /b %SLOI_EXIT%
