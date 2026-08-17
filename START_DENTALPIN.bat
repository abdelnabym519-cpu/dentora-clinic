@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo       DentalPin - Start Clinic System
echo ==========================================

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not installed or docker.exe is not in PATH.
  pause
  exit /b 1
)

if not exist ".env.client" (
  echo ERROR: .env.client is missing.
  echo Copy .env.client.example to .env.client and fill the secrets first.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running.
  echo Start Docker Desktop, wait until it is ready, then run this file again.
  pause
  exit /b 1
)

echo Starting DentalPin...
docker compose --env-file .env.client -f docker-compose.client.yml up -d --build
if errorlevel 1 (
  echo ERROR: DentalPin failed to start.
  pause
  exit /b 1
)

set "APP_URL=http://localhost"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"PUBLIC_URL=" ".env.client"') do set "APP_URL=%%B"

echo.
echo DentalPin is starting at: %APP_URL%
echo The first start can take several minutes while images are built.
"%SystemRoot%\System32\timeout.exe" /t 5 /nobreak >nul
start "" "%APP_URL%"

endlocal
