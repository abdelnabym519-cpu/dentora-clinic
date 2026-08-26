@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "DENTORA_CONFIG=%CD%\dentora-workstation.conf"
set "DENTORA_CA_FILE=%CD%\dentora-lan-ca.crt"
set "DENTORA_URL="
set "DENTORA_CA_SHA256="
set "DENTORA_SERVER_IP="

echo ==========================================
echo       Dentora - Workstation Setup
echo ==========================================

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: Windows PowerShell is required.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 1 }"
if errorlevel 1 (
  echo ERROR: Workstation setup must be run as Administrator.
  echo Right-click SETUP_DENTORA_WORKSTATION.bat and choose "Run as administrator".
  pause
  exit /b 1
)

if not exist "%DENTORA_CONFIG%" (
  echo ERROR: dentora-workstation.conf is missing.
  echo Copy the complete Dentora_Workstation_Kit folder from the Mini PC.
  pause
  exit /b 1
)

if not exist "%DENTORA_CA_FILE%" (
  echo ERROR: dentora-lan-ca.crt is missing.
  echo Copy the complete Dentora_Workstation_Kit folder from the Mini PC.
  pause
  exit /b 1
)

for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"DENTORA_URL=" "%DENTORA_CONFIG%"') do set "DENTORA_URL=%%B"
for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"DENTORA_CA_SHA256=" "%DENTORA_CONFIG%"') do set "DENTORA_CA_SHA256=%%B"

if not defined DENTORA_URL (
  echo ERROR: DENTORA_URL is missing from dentora-workstation.conf.
  pause
  exit /b 1
)
if not defined DENTORA_CA_SHA256 (
  echo ERROR: DENTORA_CA_SHA256 is missing from dentora-workstation.conf.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%I in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $uri=[Uri]$env:DENTORA_URL; if ($uri.Scheme -ne 'https') { throw 'Dentora URL must use HTTPS' }; $ip=$null; if (-not [System.Net.IPAddress]::TryParse($uri.Host,[ref]$ip)) { throw 'Dentora URL must use the Mini PC IPv4 address' }; if ($ip.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'IPv4 is required' }; $b=$ip.GetAddressBytes(); $private=($b[0] -eq 10) -or (($b[0] -eq 172) -and ($b[1] -ge 16) -and ($b[1] -le 31)) -or (($b[0] -eq 192) -and ($b[1] -eq 168)); if (-not $private) { throw 'Dentora URL must use a private RFC1918 address' }; if (($uri.Port -ne 443) -and -not $uri.IsDefaultPort) { throw 'Dentora workstation setup expects HTTPS on port 443' }; if (($uri.AbsolutePath -ne '/') -or $uri.Query -or $uri.Fragment) { throw 'Dentora URL must be the origin only' }; $uri.Host"`) do set "DENTORA_SERVER_IP=%%I"
if not defined DENTORA_SERVER_IP (
  echo ERROR: Unsupported Dentora workstation URL: %DENTORA_URL%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $actual=(Get-FileHash -Algorithm SHA256 $env:DENTORA_CA_FILE).Hash.ToLowerInvariant(); $expected=$env:DENTORA_CA_SHA256.Trim().ToLowerInvariant(); if ($actual -ne $expected) { throw ('Dentora LAN CA SHA256 mismatch. Expected ' + $expected + ', got ' + $actual) }; $cert=[System.Security.Cryptography.X509Certificates.X509Certificate2]::new((Resolve-Path $env:DENTORA_CA_FILE)); if ($cert.HasPrivateKey) { throw 'The workstation CA must not contain a private key' }; if ($cert.Subject -ne $cert.Issuer) { throw 'Expected a self-signed root CA certificate' }; if ($cert.NotAfter -le (Get-Date)) { throw 'The Dentora LAN CA certificate is expired' }"
if errorlevel 1 (
  echo ERROR: The Dentora LAN CA file failed integrity or certificate validation.
  echo Regenerate the workstation kit on the Mini PC and copy the complete folder again.
  pause
  exit /b 1
)

echo Checking access to the Mini PC on TCP 443...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ok=Test-NetConnection -ComputerName $env:DENTORA_SERVER_IP -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue; if (-not $ok) { exit 1 }"
if errorlevel 1 (
  echo ERROR: Cannot reach %DENTORA_SERVER_IP% on TCP 443.
  echo Confirm this workstation is on the clinic LAN and the Mini PC is running Dentora.
  pause
  exit /b 1
)

echo Installing the Dentora LAN CA in the Windows machine trust store...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $imported=Import-Certificate -FilePath $env:DENTORA_CA_FILE -CertStoreLocation 'Cert:\LocalMachine\Root'; if (-not $imported) { throw 'Certificate import returned no certificate' }; $source=[System.Security.Cryptography.X509Certificates.X509Certificate2]::new((Resolve-Path $env:DENTORA_CA_FILE)); if (-not (Test-Path ('Cert:\LocalMachine\Root\' + $source.Thumbprint))) { throw 'Imported Dentora CA was not found in LocalMachine Root' }"
if errorlevel 1 (
  echo ERROR: Could not trust the Dentora LAN CA on this workstation.
  pause
  exit /b 1
)

echo Verifying Dentora HTTPS without certificate bypasses...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $health=$env:DENTORA_URL.TrimEnd('/') + '/health'; $r=Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 8; if ($r.StatusCode -ne 200) { throw ('Dentora health returned HTTP ' + $r.StatusCode) }"
if errorlevel 1 (
  echo ERROR: HTTPS verification failed for %DENTORA_URL%.
  echo Confirm the workstation kit came from the same Mini PC and that its fixed IP did not change.
  pause
  exit /b 1
)

echo Creating a Dentora shortcut for all users on this workstation...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $desktop=Join-Path $env:PUBLIC 'Desktop'; if (-not (Test-Path $desktop)) { New-Item -ItemType Directory -Path $desktop -Force | Out-Null }; $shortcut=Join-Path $desktop 'Dentora Clinic.url'; $content='[InternetShortcut]' + [Environment]::NewLine + 'URL=' + $env:DENTORA_URL + [Environment]::NewLine; [System.IO.File]::WriteAllText($shortcut,$content,(New-Object System.Text.UTF8Encoding($false))); if (-not (Test-Path $shortcut)) { throw 'Shortcut was not created' }"
if errorlevel 1 (
  echo ERROR: Dentora HTTPS works, but the desktop shortcut could not be created.
  pause
  exit /b 1
)

echo.
echo ==========================================
echo Workstation setup completed successfully.
echo Dentora URL: %DENTORA_URL%
echo HTTPS trust: verified
echo Shortcut: Public Desktop - Dentora Clinic
echo ==========================================
echo.
echo This workstation does not need Docker, PostgreSQL, Dentora secrets, or a local Dentora database.
echo Use the Dentora Clinic shortcut for daily access.
start "" "%DENTORA_URL%"
pause
endlocal
