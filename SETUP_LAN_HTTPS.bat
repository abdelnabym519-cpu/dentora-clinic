@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo   Dentora - Mini PC LAN HTTPS Setup
echo ==========================================

if "%~1"=="" (
  echo ERROR: A fixed private LAN IPv4 address is required.
  echo Example: SETUP_LAN_HTTPS.bat 192.168.1.50
  echo Reserve or configure this address for the Mini PC before continuing.
  pause
  exit /b 2
)

set "DENTORA_TARGET_IP=%~1"
set "DENTORA_CA_FILE=%CD%\dentora-lan-ca.crt"
set "DENTORA_COMPOSE=docker compose --env-file .env.client -f docker-compose.client.yml"

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: Windows PowerShell is required.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $raw=$env:DENTORA_TARGET_IP; $ip=[System.Net.IPAddress]::Parse($raw); if ($ip.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'Dentora LAN HTTPS currently requires IPv4' }; $b=$ip.GetAddressBytes(); $private=($b[0] -eq 10) -or (($b[0] -eq 172) -and ($b[1] -ge 16) -and ($b[1] -le 31)) -or (($b[0] -eq 192) -and ($b[1] -eq 168)); if (-not $private) { throw 'Use a private RFC1918 LAN IPv4 address' }"
if errorlevel 1 (
  echo ERROR: %DENTORA_TARGET_IP% is not a supported private LAN IPv4 address.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 1 }"
if errorlevel 1 (
  echo ERROR: LAN HTTPS setup must be run as Administrator.
  echo Right-click SETUP_LAN_HTTPS.bat and choose "Run as administrator".
  pause
  exit /b 1
)

if not exist ".env.client" (
  echo ERROR: .env.client does not exist yet.
  echo Run START_DENTORA.bat once before configuring LAN HTTPS.
  pause
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not installed or docker.exe is not in PATH.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running.
  echo Start Docker Desktop, wait until it is ready, then run this file again.
  pause
  exit /b 1
)

echo Configuring canonical Dentora URL as https://%DENTORA_TARGET_IP% ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $path=Join-Path (Get-Location) '.env.client'; $url='https://' + $env:DENTORA_TARGET_IP; $text=Get-Content -Raw $path; if ($text -match '(?m)^PUBLIC_URL=') { $text=[regex]::Replace($text,'(?m)^PUBLIC_URL=.*$',('PUBLIC_URL=' + $url)) } else { $text=('PUBLIC_URL=' + $url + [Environment]::NewLine + $text) }; [System.IO.File]::WriteAllText($path,$text,(New-Object System.Text.UTF8Encoding($false)))"
if errorlevel 1 (
  echo ERROR: Could not update PUBLIC_URL in .env.client.
  pause
  exit /b 1
)

echo Restricting Dentora inbound firewall access to the local subnet...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $names=@('Dentora LAN HTTP','Dentora LAN HTTPS'); foreach ($name in $names) { Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue }; New-NetFirewallRule -DisplayName 'Dentora LAN HTTP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 80 -Profile Any -RemoteAddress LocalSubnet | Out-Null; New-NetFirewallRule -DisplayName 'Dentora LAN HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 -Profile Any -RemoteAddress LocalSubnet | Out-Null"
if errorlevel 1 (
  echo ERROR: Could not configure Windows Firewall rules for Dentora.
  pause
  exit /b 1
)

echo Rebuilding Dentora for the LAN HTTPS origin...
%DENTORA_COMPOSE% up -d --build
if errorlevel 1 (
  echo ERROR: Dentora failed to start with the LAN HTTPS configuration.
  pause
  exit /b 1
)

if exist "%DENTORA_CA_FILE%" del /q "%DENTORA_CA_FILE%" >nul 2>&1

echo Waiting for Caddy local CA material...
set "DENTORA_CA_READY="
for /L %%I in (1,1,30) do (
  if not defined DENTORA_CA_READY (
    %DENTORA_COMPOSE% cp caddy:/data/caddy/pki/authorities/local/root.crt "dentora-lan-ca.crt" >nul 2>&1
    if exist "dentora-lan-ca.crt" set "DENTORA_CA_READY=1"
    if not defined DENTORA_CA_READY "%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
  )
)

if not defined DENTORA_CA_READY (
  echo ERROR: Caddy did not produce the local CA certificate.
  echo Check Caddy logs with: %DENTORA_COMPOSE% logs caddy
  pause
  exit /b 1
)

where certutil.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: certutil.exe is required to trust the Dentora local CA on the Mini PC.
  pause
  exit /b 1
)

echo Trusting the Dentora local CA on this Mini PC...
certutil.exe -f -addstore Root "%DENTORA_CA_FILE%" >nul
if errorlevel 1 (
  echo ERROR: Could not install the Dentora local CA into the Windows machine trust store.
  pause
  exit /b 1
)

set "DENTORA_APP_URL=https://%DENTORA_TARGET_IP%"
echo Verifying HTTPS health endpoint...
set "DENTORA_HEALTHY="
for /L %%I in (1,1,30) do (
  if not defined DENTORA_HEALTHY (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $r=Invoke-WebRequest -UseBasicParsing -Uri ($env:DENTORA_APP_URL + '/health') -TimeoutSec 4; if ($r.StatusCode -ne 200) { exit 1 }" >nul 2>&1
    if not errorlevel 1 set "DENTORA_HEALTHY=1"
    if not defined DENTORA_HEALTHY "%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
  )
)

if not defined DENTORA_HEALTHY (
  echo ERROR: Dentora did not become healthy over HTTPS at %DENTORA_APP_URL%.
  echo Inspect services with: %DENTORA_COMPOSE% ps
  pause
  exit /b 1
)

echo.
echo ==========================================
echo LAN HTTPS setup completed successfully.
echo Dentora URL: %DENTORA_APP_URL%
echo Root CA file: %DENTORA_CA_FILE%
echo Firewall: TCP 80 and 443, LocalSubnet only.
echo ==========================================
echo.
echo Keep the Mini PC on the fixed IP %DENTORA_TARGET_IP%.
echo The exported CA file is the trust anchor needed by clinic workstations.
echo Workstation trust installation belongs to the separate Workstation Setup stage.
start "" "%DENTORA_APP_URL%"
pause
endlocal
