@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo       DentalPin Egypt Demo - STATUS
echo ==========================================

docker compose ^
  -p dentalpin-egypt-demo ^
  --env-file .egypt-demo.env ^
  -f docker-compose.client.yml ^
  -f .egypt-demo.override.yml ^
  ps

echo.
pause

endlocal
