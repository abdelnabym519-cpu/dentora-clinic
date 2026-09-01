@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ACTION=apply"
if /I "%~1"=="--check" set "ACTION=check"
if /I "%~1"=="--recover" set "ACTION=recover"

powershell.exe -NoProfile -File "%~dp0scripts\dentora_auto_update.ps1" -Action %ACTION%
if errorlevel 1 (
  echo.
  echo ERROR: Dentora Auto Update did not complete successfully.
  echo If an update was interrupted, run UPDATE_DENTORA.bat --recover as Administrator.
  pause
  exit /b 1
)

echo.
echo Dentora Auto Update completed successfully.
pause
endlocal
