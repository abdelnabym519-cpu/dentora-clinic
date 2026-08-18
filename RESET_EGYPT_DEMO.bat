@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PROJECT=dentalpin-egypt-demo"
set "ENVFILE=.egypt-demo.env"
set "OVERRIDE=.egypt-demo.override.yml"

rem This is intentionally the external DB volume currently used by
rem the permanent owner demo. Do not generalize this value.
set "PGVOLUME=dentalpin-egypt-demo-smoke_pgdata"

set "DBCONTAINER=%PROJECT%-db-1"
set "BACKEND=%PROJECT%-backend-1"
set "FRONTEND=%PROJECT%-frontend-1"
set "CADDY=%PROJECT%-caddy-1"

echo ==========================================
echo       DentalPin Egypt Demo - RESET
echo ==========================================
echo.
echo This resets ONLY the Egyptian demo database.
echo The owner license/storage volume is preserved.
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker.exe was not found.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running.
  exit /b 1
)

if not exist "%ENVFILE%" (
  echo ERROR: %ENVFILE% is missing.
  exit /b 1
)

if not exist "%OVERRIDE%" (
  echo ERROR: %OVERRIDE% is missing.
  exit /b 1
)

findstr /C:"name: %PGVOLUME%" "%OVERRIDE%" >nul
if errorlevel 1 (
  echo ERROR: Expected dedicated demo database volume is not configured.
  exit /b 1
)

docker volume inspect "%PGVOLUME%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Dedicated demo database volume does not exist.
  exit /b 1
)

set "PGDB="
set "PGUSER="

for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_DB=" "%ENVFILE%"') do (
  set "PGDB=%%B"
)

for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_USER=" "%ENVFILE%"') do (
  set "PGUSER=%%B"
)

if not defined PGDB (
  echo ERROR: POSTGRES_DB is missing.
  exit /b 1
)

if not defined PGUSER (
  echo ERROR: POSTGRES_USER is missing.
  exit /b 1
)

if /I not "%PGDB%"=="dentalpin_egypt_demo" (
  echo ERROR: Refusing reset because database name is not the dedicated Egypt demo DB.
  exit /b 1
)

if /I not "%PGUSER%"=="dentalpin_demo" (
  echo ERROR: Refusing reset because database user is not the dedicated demo user.
  exit /b 1
)

set "CURRENT_PG="

for /f "usebackq delims=" %%V in (`docker inspect "%DBCONTAINER%" --format "{{range .Mounts}}{{if eq .Destination \"/var/lib/postgresql/data\"}}{{.Name}}{{end}}{{end}}" 2^>nul`) do (
  set "CURRENT_PG=%%V"
)

if defined CURRENT_PG (
  if /I not "!CURRENT_PG!"=="%PGVOLUME%" (
    echo ERROR: Running demo DB container points to a different volume.
    echo RESET ABORTED.
    exit /b 1
  )
)

echo PROJECT=%PROJECT%
echo DATABASE=%PGDB%
echo DATABASE_VOLUME=%PGVOLUME%
echo LICENSE_STORAGE_WILL_BE_PRESERVED=YES
echo SAFETY_PRECHECK=PASSED

if /I "%~1"=="CHECK" (
  echo DRY_RUN_ONLY=YES
  exit /b 0
)

echo.
set /p "CONFIRM=Type RESET-EGYPT-DEMO to continue: "

if /I not "%CONFIRM%"=="RESET-EGYPT-DEMO" (
  echo Reset cancelled.
  exit /b 2
)

echo.
echo [1/8] Stopping dedicated owner demo...

docker compose ^
  -p "%PROJECT%" ^
  --env-file "%ENVFILE%" ^
  -f docker-compose.client.yml ^
  -f "%OVERRIDE%" ^
  stop

if errorlevel 1 (
  echo ERROR: Could not stop the demo.
  exit /b 1
)

echo.
echo [2/8] Removing dedicated DB container only...

docker compose ^
  -p "%PROJECT%" ^
  --env-file "%ENVFILE%" ^
  -f docker-compose.client.yml ^
  -f "%OVERRIDE%" ^
  rm -f db

if errorlevel 1 (
  echo ERROR: Could not remove the dedicated DB container.
  exit /b 1
)

echo.
echo [3/8] Recreating dedicated database volume...

docker volume rm "%PGVOLUME%"
if errorlevel 1 (
  echo ERROR: Could not remove the dedicated database volume.
  echo No other volume was touched.
  exit /b 1
)

docker volume create "%PGVOLUME%" >nul
if errorlevel 1 (
  echo ERROR: Could not recreate the dedicated database volume.
  exit /b 1
)

echo DATABASE_VOLUME_RECREATED=YES

echo.
echo [4/8] Starting fresh PostgreSQL...

docker compose ^
  -p "%PROJECT%" ^
  --env-file "%ENVFILE%" ^
  -f docker-compose.client.yml ^
  -f "%OVERRIDE%" ^
  up -d --no-build db

if errorlevel 1 (
  echo ERROR: Could not start PostgreSQL.
  exit /b 1
)

set "DB_STATUS="

for /L %%I in (1,1,40) do (
  for /f "delims=" %%S in ('docker inspect "%DBCONTAINER%" --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul') do (
    set "DB_STATUS=%%S"
  )

  echo DB_CHECK_%%I=!DB_STATUS!

  if /I "!DB_STATUS!"=="healthy" goto DB_READY

  ping 127.0.0.1 -n 3 >nul
)

echo ERROR: PostgreSQL did not become healthy.
exit /b 1

:DB_READY
echo DATABASE_HEALTHY=YES

echo.
echo [5/8] Running migrations and Egyptian demo seeder...

docker compose ^
  -p "%PROJECT%" ^
  --env-file "%ENVFILE%" ^
  -f docker-compose.client.yml ^
  -f "%OVERRIDE%" ^
  run --rm --no-deps ^
  -e SEED_ON_STARTUP=0 ^
  -e SEED_LANG=ar ^
  -e PYTHONPATH=/app ^
  backend ^
  python /app/scripts/seed_demo.py --lang ar

if errorlevel 1 (
  echo ERROR: Egyptian demo seed failed.
  exit /b 1
)

echo EGYPT_DEMO_SEED=PASSED

echo.
echo [6/8] Starting full owner demo...

docker compose ^
  -p "%PROJECT%" ^
  --env-file "%ENVFILE%" ^
  -f docker-compose.client.yml ^
  -f "%OVERRIDE%" ^
  up -d --no-build

if errorlevel 1 (
  echo ERROR: Owner demo failed to start.
  exit /b 1
)

set "BACKEND_STATUS="
set "FRONTEND_STATUS="
set "DB_STATUS="
set "CADDY_STATUS="

for /L %%I in (1,1,40) do (

  for /f "delims=" %%S in ('docker inspect "%DBCONTAINER%" --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul') do (
    set "DB_STATUS=%%S"
  )

  for /f "delims=" %%S in ('docker inspect "%BACKEND%" --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul') do (
    set "BACKEND_STATUS=%%S"
  )

  for /f "delims=" %%S in ('docker inspect "%FRONTEND%" --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul') do (
    set "FRONTEND_STATUS=%%S"
  )

  for /f "delims=" %%S in ('docker inspect "%CADDY%" --format "{{.State.Status}}" 2^>nul') do (
    set "CADDY_STATUS=%%S"
  )

  echo CHECK_%%I DB=!DB_STATUS! BACKEND=!BACKEND_STATUS! FRONTEND=!FRONTEND_STATUS! CADDY=!CADDY_STATUS!

  if /I "!DB_STATUS!"=="healthy" (
    if /I "!BACKEND_STATUS!"=="healthy" (
      if /I "!FRONTEND_STATUS!"=="healthy" (
        if /I "!CADDY_STATUS!"=="running" goto STACK_READY
      )
    )
  )

  ping 127.0.0.1 -n 3 >nul
)

echo ERROR: Full demo did not become healthy.
exit /b 1

:STACK_READY
echo FULL_STACK_HEALTHY=YES

echo.
echo [7/8] Verifying seeded database counts...

for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM patients;"') do set "PATIENTS=%%C"
for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM treatment_catalog_items;"') do set "CATALOG=%%C"
for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM treatment_plans;"') do set "PLANS=%%C"
for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM appointments;"') do set "APPOINTMENTS=%%C"
for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM invoices;"') do set "INVOICES=%%C"
for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM payments;"') do set "PAYMENTS=%%C"
for /f "delims=" %%C in ('docker exec "%DBCONTAINER%" psql -U "%PGUSER%" -d "%PGDB%" -tAc "SELECT COUNT(*) FROM booking_settings WHERE enabled = true AND public_slug = 'dentalpin-egypt';"') do set "BOOKING=%%C"

echo PATIENTS_COUNT=!PATIENTS!
echo CATALOG_COUNT=!CATALOG!
echo PLANS_COUNT=!PLANS!
echo APPOINTMENTS_COUNT=!APPOINTMENTS!
echo INVOICES_COUNT=!INVOICES!
echo PAYMENTS_COUNT=!PAYMENTS!
echo BOOKING_SETTINGS_COUNT=!BOOKING!

if not "!PATIENTS!"=="15" exit /b 1
if not "!CATALOG!"=="129" exit /b 1
if not "!PLANS!"=="15" exit /b 1
if not "!APPOINTMENTS!"=="27" exit /b 1
if not "!INVOICES!"=="7" exit /b 1
if not "!PAYMENTS!"=="6" exit /b 1
if not "!BOOKING!"=="1" exit /b 1

echo RESET_DATA_GATE=PASSED
echo RESET_BOOKING_GATE=PASSED

echo.
echo [8/8] Verifying permanent owner license survived...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $r=Invoke-RestMethod -Uri 'http://localhost:8090/api/v1/license/status' -TimeoutSec 15; if(-not $r.data.active){throw 'License is not active'}; if($r.data.state -ne 'active'){throw 'License state is not active'}; if(-not ($r.data.features -contains 'ai')){throw 'AI feature missing'}; Write-Host 'LICENSE_ACTIVE=True'; Write-Host ('LICENSE_STATE=' + $r.data.state); Write-Host ('LICENSE_CUSTOMER=' + $r.data.customer_name); Write-Host 'RESET_LICENSE_GATE=PASSED'"

if errorlevel 1 (
  echo ERROR: Permanent demo license did not survive reset.
  exit /b 1
)

echo.
echo ==========================================
echo       EGYPT DEMO RESET PASSED
echo ==========================================
echo.
echo URL: http://localhost:8090
echo Booking: http://localhost:8090/booking/dentalpin-egypt
echo Login: admin@demo.clinic
echo Password: demo1234
echo.
echo Database rebuilt.
echo Owner license preserved.
echo AI entitlement preserved.
echo.

exit /b 0
