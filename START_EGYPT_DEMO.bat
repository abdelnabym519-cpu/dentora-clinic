@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo       DentalPin Egypt Demo - START
echo ==========================================

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running.
  pause
  exit /b 1
)

docker compose ^
  -p dentalpin-egypt-demo ^
  --env-file .egypt-demo.env ^
  -f docker-compose.client.yml ^
  -f .egypt-demo.override.yml ^
  up -d

if errorlevel 1 (
  echo ERROR: DentalPin Egypt Demo failed to start.
  pause
  exit /b 1
)

echo.
echo DentalPin Egypt Demo:
echo http://localhost:8090
echo.

start "" "http://localhost:8090"

endlocal
