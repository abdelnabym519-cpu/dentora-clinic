@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo       Dentora - Safe Restore
echo ==========================================

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: Windows PowerShell is required.
  pause
  exit /b 1
)

if /I "%~1"=="--recover" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dentora_backup_restore.ps1" recover
  if errorlevel 1 (
    echo ERROR: Dentora restore recovery did not complete.
    pause
    exit /b 1
  )
  echo Restore recovery completed.
  pause
  exit /b 0
)

if "%~1"=="" (
  echo ERROR: Provide the full path to a Dentora backup ZIP.
  echo Example: RESTORE_DENTORA.bat "C:\Dentora\backups\dentora-20260823T120000Z-ab12cd34.zip"
  echo To recover an interrupted restore: RESTORE_DENTORA.bat --recover
  pause
  exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dentora_backup_restore.ps1" restore -ArtifactPath "%~1"
if errorlevel 1 (
  echo.
  echo ERROR: Dentora restore failed safely. Review the message above.
  echo If an interrupted restore journal remains, run: RESTORE_DENTORA.bat --recover
  pause
  exit /b 1
)

echo.
echo Restore completed and validated successfully.
pause
endlocal
