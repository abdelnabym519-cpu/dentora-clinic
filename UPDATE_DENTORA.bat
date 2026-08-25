@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where powershell.exe >nul 2>&1 || (echo ERROR: Windows PowerShell is required.& pause & exit /b 1)
if not exist ".env.client" (echo ERROR: .env.client is missing. Start Dentora first.& pause & exit /b 1)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\client-update.ps1" -Mode Update
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Update did not complete. See .dentora-update\status.json and transaction logs.
pause
exit /b %RESULT%
