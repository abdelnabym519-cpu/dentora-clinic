@echo off
setlocal
cd /d "%~dp0"

echo Stopping Dentora services...
docker compose --env-file .env.client -f docker-compose.client.yml stop
if errorlevel 1 (
  echo ERROR: Could not stop Dentora cleanly.
  pause
  exit /b 1
)

echo Dentora stopped. Clinic data was preserved.
pause
endlocal
