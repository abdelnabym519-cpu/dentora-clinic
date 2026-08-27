@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo       Dentora - Secure Backup
echo ==========================================

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: Windows PowerShell is required.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dentora_backup_restore.ps1" backup
if errorlevel 1 (
  echo.
  echo ERROR: Dentora backup failed safely. No backup was accepted.
  pause
  exit /b 1
)

echo.
echo Backup completed and validated successfully.
pause
endlocal
