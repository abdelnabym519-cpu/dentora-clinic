@echo off
setlocal
cd /d "%~dp0"

echo Stopping DentalPin services...
docker compose --env-file .env.client -f docker-compose.client.yml stop
if errorlevel 1 (
  echo ERROR: Could not stop DentalPin cleanly.
  pause
  exit /b 1
)

echo DentalPin stopped. Clinic data was preserved.
pause
endlocal
