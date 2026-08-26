@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "KIT_DIR=%CD%\Dentora_Workstation_Kit"
set "DENTORA_URL="
set "DENTORA_CA_SHA256="

echo ==========================================
echo     Dentora - Prepare Workstation Kit
echo ==========================================

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: Windows PowerShell is required.
  pause
  exit /b 1
)

if not exist ".env.client" (
  echo ERROR: .env.client was not found.
  echo Run START_DENTORA.bat and SETUP_LAN_HTTPS.bat on the Mini PC first.
  pause
  exit /b 1
)

if not exist "dentora-lan-ca.crt" (
  echo ERROR: dentora-lan-ca.crt was not found.
  echo Run SETUP_LAN_HTTPS.bat successfully before preparing workstations.
  pause
  exit /b 1
)

if not exist "SETUP_DENTORA_WORKSTATION.bat" (
  echo ERROR: SETUP_DENTORA_WORKSTATION.bat is missing from this Dentora package.
  pause
  exit /b 1
)

if not exist "WORKSTATION_SETUP_AR.md" (
  echo ERROR: WORKSTATION_SETUP_AR.md is missing from this Dentora package.
  pause
  exit /b 1
)

for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"PUBLIC_URL=" ".env.client"') do set "DENTORA_URL=%%B"
if not defined DENTORA_URL (
  echo ERROR: PUBLIC_URL is missing from .env.client.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $uri=[Uri]$env:DENTORA_URL; if ($uri.Scheme -ne 'https') { throw 'PUBLIC_URL must use HTTPS before workstation setup' }; $ip=$null; if (-not [System.Net.IPAddress]::TryParse($uri.Host,[ref]$ip)) { throw 'PUBLIC_URL must use the fixed Mini PC IPv4 address' }; if ($ip.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'Dentora workstation setup currently requires IPv4' }; $b=$ip.GetAddressBytes(); $private=($b[0] -eq 10) -or (($b[0] -eq 172) -and ($b[1] -ge 16) -and ($b[1] -le 31)) -or (($b[0] -eq 192) -and ($b[1] -eq 168)); if (-not $private) { throw 'PUBLIC_URL must use a private RFC1918 address' }; if (($uri.Port -ne 443) -and -not $uri.IsDefaultPort) { throw 'Dentora workstation setup expects HTTPS on port 443' }; if (($uri.AbsolutePath -ne '/') -or $uri.Query -or $uri.Fragment) { throw 'PUBLIC_URL must be the Dentora origin only' }"
if errorlevel 1 (
  echo ERROR: PUBLIC_URL is not a supported Dentora LAN HTTPS origin: %DENTORA_URL%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $cert=[System.Security.Cryptography.X509Certificates.X509Certificate2]::new((Resolve-Path 'dentora-lan-ca.crt')); if ($cert.HasPrivateKey) { throw 'The exported workstation CA must not contain a private key' }; if ($cert.Subject -ne $cert.Issuer) { throw 'Expected a self-signed root CA certificate' }; if ($cert.NotAfter -le (Get-Date)) { throw 'The Dentora LAN CA certificate is expired' }"
if errorlevel 1 (
  echo ERROR: dentora-lan-ca.crt is not a valid Dentora workstation trust certificate.
  pause
  exit /b 1
)

if exist "%KIT_DIR%" rmdir /s /q "%KIT_DIR%"
mkdir "%KIT_DIR%"
if errorlevel 1 (
  echo ERROR: Could not create %KIT_DIR%.
  pause
  exit /b 1
)

copy /y "dentora-lan-ca.crt" "%KIT_DIR%\dentora-lan-ca.crt" >nul
copy /y "SETUP_DENTORA_WORKSTATION.bat" "%KIT_DIR%\SETUP_DENTORA_WORKSTATION.bat" >nul
copy /y "WORKSTATION_SETUP_AR.md" "%KIT_DIR%\WORKSTATION_SETUP_AR.md" >nul
if errorlevel 1 (
  echo ERROR: Could not copy the workstation setup files.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%H in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -Algorithm SHA256 '%KIT_DIR%\dentora-lan-ca.crt').Hash.ToLowerInvariant()"`) do set "DENTORA_CA_SHA256=%%H"
if not defined DENTORA_CA_SHA256 (
  echo ERROR: Could not calculate the Dentora LAN CA fingerprint.
  pause
  exit /b 1
)

> "%KIT_DIR%\dentora-workstation.conf" (
  echo DENTORA_URL=%DENTORA_URL%
  echo DENTORA_CA_SHA256=%DENTORA_CA_SHA256%
)

if errorlevel 1 (
  echo ERROR: Could not create dentora-workstation.conf.
  pause
  exit /b 1
)

echo.
echo ==========================================
echo Workstation kit is ready.
echo Folder: %KIT_DIR%
echo Dentora URL: %DENTORA_URL%
echo CA SHA256: %DENTORA_CA_SHA256%
echo ==========================================
echo.
echo Copy the entire Dentora_Workstation_Kit folder to each clinic workstation.
echo The kit contains no .env.client, database credentials, license private keys, or patient data.
echo On each workstation, run SETUP_DENTORA_WORKSTATION.bat as Administrator.
pause
endlocal
