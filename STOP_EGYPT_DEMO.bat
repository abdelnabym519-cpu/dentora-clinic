@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo       DentalPin Egypt Demo - STOP
echo ==========================================

docker compose ^
  -p dentalpin-egypt-demo ^
  --env-file .egypt-demo.env ^
  -f docker-compose.client.yml ^
  -f .egypt-demo.override.yml ^
  stop

echo.
echo Data and license volumes were preserved.
echo.

endlocal
