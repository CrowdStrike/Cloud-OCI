@echo off
setlocal enabledelayedexpansion

:: Set required variables
set "OCID="
set "VAULT_NAME="
set "BUCKET_URL="

:: Check for required variables
if "%OCID%"=="" (
    echo Error: OCID variable not set
    goto :error
)
if "%VAULT_NAME%"=="" (
    echo Error: VAULT_NAME variable not set
    goto :error
)
if "%BUCKET_URL%"=="" (
    echo Error: BUCKET_URL variable not set
    goto :error
)

:: Remove trailing slash from BUCKET_URL if present
if "%BUCKET_URL:~-1%"=="/" set "BUCKET_URL=%BUCKET_URL:~0,-1%"

:: Check if running as administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: This script must be run as Administrator
    goto :error
)

:: Detect system architecture
set "ARCH=x86_64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "ARCH=arm64"
) else if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" (
    set "ARCH=arm64"
)

echo Detected architecture: %ARCH%

:: Create a temporary file for the JSON response
set "TEMP_JSON=%TEMP%\bucket_listing.json"
set "TEMP_INSTALLERS=%TEMP%\installers.txt"

:: Check if PowerShell is available
where powershell >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: PowerShell is not available. Cannot proceed without PowerShell or curl.
    goto :error
)

:: Fetch the list of objects in the bucket using PowerShell with TLS 1.2
echo Fetching available installers...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try {Invoke-RestMethod -Uri '%BUCKET_URL%/' -OutFile '%TEMP_JSON%'} catch {Write-Error $_; exit 1}}"
if %errorlevel% neq 0 (
    echo Failed to get listing from bucket
    goto :error
)

:: Use PowerShell to extract the installer for our architecture and find the latest version
echo Finding latest installer for %ARCH%...
for /f "tokens=*" %%a in ('powershell -Command "& {try {$json = Get-Content '%TEMP_JSON%' | ConvertFrom-Json; $installers = $json.objects | Where-Object { $_.name -match 'falcon-installer-.*-windows-%ARCH%' } | Select-Object -ExpandProperty name; if ($installers) { $installers | Sort-Object -Property { if ($_ -match 'falcon-installer-(\\d+\\.\\d+\\.\\d+)-') { [Version]$matches[1] } else { [Version]'0.0.0' } } | Select-Object -Last 1 } else { Write-Error 'No matching installers found'; exit 1 }} catch {Write-Error $_; exit 1}}"') do (
    set "LATEST_INSTALLER=%%a"
)

if "!LATEST_INSTALLER!"=="" (
    echo Failed to find latest installer
    goto :error
)

echo Found latest installer: !LATEST_INSTALLER!
set "DOWNLOAD_URL=%BUCKET_URL%/!LATEST_INSTALLER!"
set "TEMP_INSTALLER=%TEMP%\!LATEST_INSTALLER!"

:: Download the installer using PowerShell with TLS 1.2
echo Downloading !LATEST_INSTALLER!...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try {Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%TEMP_INSTALLER%'} catch {Write-Error $_; exit 1}}"
if %errorlevel% neq 0 (
    echo Failed to download installer
    goto :error
)

echo Download successful: !TEMP_INSTALLER!

:: Execute the installer with parameters
echo Running installer...
"!TEMP_INSTALLER!" --verbose --enable-file-logging --oci-compartment-id %OCID% --oci-vault-name %VAULT_NAME%
if %errorlevel% neq 0 (
    echo Installer execution failed
    goto :error
)

echo Installation completed successfully
goto :eof

:error
echo Script execution failed
exit /b 1