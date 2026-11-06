@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "visionExit=%errorlevel%"
if not "%visionExit%"=="0" pause
exit /b %visionExit%
