@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo       Dentora - Start Clinic System
echo ==========================================

if exist ".dentora-restore-journal.json" (
  echo ERROR: An interrupted Dentora restore requires recovery before startup.
  echo Run RESTORE_DENTORA.bat --recover as Administrator.
  pause
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not installed or docker.exe is not in PATH.
  pause
  exit /b 1
)

if not exist ".env.client" (
  echo First start detected. Creating a private installation configuration...

  if not exist ".env.client.example" (
    echo ERROR: .env.client.example is missing.
    pause
    exit /b 1
  )

  where powershell.exe >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Windows PowerShell is required to generate secure installation secrets.
    pause
    exit /b 1
  )

  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; function New-Hex([int]$n) { $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create(); try { $b=New-Object byte[] $n; $rng.GetBytes($b); return ([BitConverter]::ToString($b).Replace('-','').ToLowerInvariant()) } finally { $rng.Dispose() } }; $text=Get-Content -Raw '.env.client.example'; $pg=New-Hex 24; $secret=New-Hex 32; $budget=New-Hex 32; try { $machine=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography' -ErrorAction Stop).MachineGuid } catch { $machine=$env:COMPUTERNAME }; if ([string]::IsNullOrWhiteSpace($machine)) { throw 'Could not determine Windows machine identity' }; $sha=[System.Security.Cryptography.SHA256]::Create(); try { $fp=[BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes(('Dentora|' + $machine)))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }; $text=[regex]::Replace($text,'(?m)^POSTGRES_PASSWORD=.*$',('POSTGRES_PASSWORD=' + $pg)); $text=[regex]::Replace($text,'(?m)^SECRET_KEY=.*$',('SECRET_KEY=' + $secret)); $text=[regex]::Replace($text,'(?m)^BUDGET_PUBLIC_SECRET_KEY=.*$',('BUDGET_PUBLIC_SECRET_KEY=' + $budget)); $text=[regex]::Replace($text,'(?m)^LICENSE_MACHINE_FINGERPRINT=.*$',('LICENSE_MACHINE_FINGERPRINT=' + $fp)); [System.IO.File]::WriteAllText((Join-Path (Get-Location) '.env.client'),$text,(New-Object System.Text.UTF8Encoding($false)))"
  if errorlevel 1 (
    echo ERROR: Could not create .env.client.
    pause
    exit /b 1
  )

  for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"POSTGRES_PASSWORD=" ".env.client"') do set "CHECK_PG=%%B"
  for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"SECRET_KEY=" ".env.client"') do set "CHECK_SECRET=%%B"
  for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"BUDGET_PUBLIC_SECRET_KEY=" ".env.client"') do set "CHECK_BUDGET=%%B"
  for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"LICENSE_MACHINE_FINGERPRINT=" ".env.client"') do set "CHECK_FP=%%B"

  if not defined CHECK_PG (
    echo ERROR: Generated PostgreSQL password is empty.
    del /q ".env.client" >nul 2>&1
    pause
    exit /b 1
  )
  if not defined CHECK_SECRET (
    echo ERROR: Generated application secret is empty.
    del /q ".env.client" >nul 2>&1
    pause
    exit /b 1
  )
  if not defined CHECK_BUDGET (
    echo ERROR: Generated public budget secret is empty.
    del /q ".env.client" >nul 2>&1
    pause
    exit /b 1
  )
  if not defined CHECK_FP (
    echo ERROR: Generated machine fingerprint is empty.
    del /q ".env.client" >nul 2>&1
    pause
    exit /b 1
  )

  echo Private installation secrets and machine fingerprint created successfully.
  echo Do not copy .env.client from one clinic to another.
  echo.
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running.
  echo Start Docker Desktop, wait until it is ready, then run this file again.
  pause
  exit /b 1
)

echo Starting Dentora...
docker compose --env-file .env.client -f docker-compose.client.yml up -d --build
if errorlevel 1 (
  echo ERROR: Dentora failed to start.
  pause
  exit /b 1
)

set "APP_URL=http://localhost"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"PUBLIC_URL=" ".env.client"') do set "APP_URL=%%B"

echo.
echo Dentora is starting at: %APP_URL%
echo The first start can take several minutes while images are built.
"%SystemRoot%\System32\timeout.exe" /t 5 /nobreak >nul
start "" "%APP_URL%"

endlocal
