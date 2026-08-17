@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".env.client" (
  echo ERROR: .env.client is missing.
  pause
  exit /b 1
)

set "DB_USER=dental"
set "DB_NAME=dental_clinic"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_USER=" ".env.client"') do set "DB_USER=%%B"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_DB=" ".env.client"') do set "DB_NAME=%%B"

echo Applying Dental Care Clinic profile...
docker compose --env-file .env.client -f docker-compose.client.yml exec -T db psql -U %DB_USER% -d %DB_NAME% -c "UPDATE clinics SET name='Dental Care Clinic', phone='+20 10 1234 5678', email='info@dentalcare.com', timezone='Africa/Cairo', currency='EGP';"
if errorlevel 1 (
  echo ERROR: Could not update the clinic profile.
  echo Complete the first-run setup in the browser before running this file.
  pause
  exit /b 1
)

echo.
echo Clinic profile configured:
echo   Dental Care Clinic
echo   +20 10 1234 5678
echo   info@dentalcare.com
echo   Africa/Cairo / EGP
pause
endlocal
