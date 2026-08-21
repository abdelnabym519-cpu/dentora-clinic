@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".env.client" (
  echo ERROR: .env.client is missing.
  pause
  exit /b 1
)

if not exist "backups" mkdir "backups"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "DB_USER=dental"
set "DB_NAME=dental_clinic"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_USER=" ".env.client"') do set "DB_USER=%%B"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_DB=" ".env.client"') do set "DB_NAME=%%B"

echo Backing up PostgreSQL...
docker compose --env-file .env.client -f docker-compose.client.yml exec -T db pg_dump -U %DB_USER% -d %DB_NAME% > "backups\database_%STAMP%.sql"
if errorlevel 1 (
  echo ERROR: Database backup failed.
  pause
  exit /b 1
)

echo Backing up uploaded files...
docker compose --env-file .env.client -f docker-compose.client.yml exec -T backend tar -C /app/storage -czf - . > "backups\storage_%STAMP%.tar.gz"
if errorlevel 1 (
  echo ERROR: Storage backup failed.
  pause
  exit /b 1
)

echo.
echo Backup completed:
echo   backups\database_%STAMP%.sql
echo   backups\storage_%STAMP%.tar.gz
pause
endlocal
