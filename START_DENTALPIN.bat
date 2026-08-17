@echo off
setlocal EnableExtensions
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

  for /f "usebackq delims=" %%S in (`powershell.exe -NoProfile -Command "$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create(); $b=New-Object byte[] 24; $rng.GetBytes($b); ($b ^| ForEach-Object { $_.ToString('x2') }) -join ''"`) do set "POSTGRES_PASSWORD=%%S"
  for /f "usebackq delims=" %%S in (`powershell.exe -NoProfile -Command "$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create(); $b=New-Object byte[] 32; $rng.GetBytes($b); ($b ^| ForEach-Object { $_.ToString('x2') }) -join ''"`) do set "SECRET_KEY=%%S"
  for /f "usebackq delims=" %%S in (`powershell.exe -NoProfile -Command "$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create(); $b=New-Object byte[] 32; $rng.GetBytes($b); ($b ^| ForEach-Object { $_.ToString('x2') }) -join ''"`) do set "BUDGET_PUBLIC_SECRET_KEY=%%S"
  for /f "usebackq delims=" %%S in (`powershell.exe -NoProfile -Command "try { $id=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid } catch { $id=$env:COMPUTERNAME }; $sha=[System.Security.Cryptography.SHA256]::Create(); $bytes=[System.Text.Encoding]::UTF8.GetBytes(('DentalPin|' + $id)); (($sha.ComputeHash($bytes) ^| ForEach-Object { $_.ToString('x2') }) -join '')"`) do set "LICENSE_MACHINE_FINGERPRINT=%%S"

  if not defined POSTGRES_PASSWORD (
    echo ERROR: Could not generate the PostgreSQL password.
    pause
    exit /b 1
  )
  if not defined SECRET_KEY (
    echo ERROR: Could not generate the application secret.
    pause
    exit /b 1
  )
  if not defined BUDGET_PUBLIC_SECRET_KEY (
    echo ERROR: Could not generate the public budget secret.
    pause
    exit /b 1
  )
  if not defined LICENSE_MACHINE_FINGERPRINT (
    echo ERROR: Could not create the machine fingerprint.
    pause
    exit /b 1
  )

  set "DP_POSTGRES_PASSWORD=%POSTGRES_PASSWORD%"
  set "DP_SECRET_KEY=%SECRET_KEY%"
  set "DP_BUDGET_SECRET=%BUDGET_PUBLIC_SECRET_KEY%"
  set "DP_LICENSE_FINGERPRINT=%LICENSE_MACHINE_FINGERPRINT%"

  powershell.exe -NoProfile -Command "$text=Get-Content -Raw '.env.client.example'; $text=$text -replace '(?m)^POSTGRES_PASSWORD=.*$', ('POSTGRES_PASSWORD=' + $env:DP_POSTGRES_PASSWORD); $text=$text -replace '(?m)^SECRET_KEY=.*$', ('SECRET_KEY=' + $env:DP_SECRET_KEY); $text=$text -replace '(?m)^BUDGET_PUBLIC_SECRET_KEY=.*$', ('BUDGET_PUBLIC_SECRET_KEY=' + $env:DP_BUDGET_SECRET); $text=$text -replace '(?m)^LICENSE_MACHINE_FINGERPRINT=.*$', ('LICENSE_MACHINE_FINGERPRINT=' + $env:DP_LICENSE_FINGERPRINT); [System.IO.File]::WriteAllText((Join-Path (Get-Location) '.env.client'), $text, (New-Object System.Text.UTF8Encoding($false)))"
  if errorlevel 1 (
    echo ERROR: Could not create .env.client.
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
