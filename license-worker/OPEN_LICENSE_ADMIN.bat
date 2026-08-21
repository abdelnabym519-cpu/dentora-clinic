@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo   DentalPin License Administration
 echo ==========================================

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not available in PATH.
  pause
  exit /b 1
)

python admin_cli.py

if errorlevel 1 (
  echo.
  echo License administration exited with an error.
)

pause
endlocal
