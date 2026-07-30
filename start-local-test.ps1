# One-click local test for the central server and desktop client.
# This script intentionally uses the project Python 3.12 virtual environment.

$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Data = Join-Path $Backend 'central_data'
$AgentData = Join-Path $Backend 'datas'
$Python = Join-Path $Root '.venv-win\Scripts\python.exe'
$Central = 'http://127.0.0.1:9099'
$Exe = Join-Path $Backend 'dist\MatrixShipAgent\MatrixShipAgent.exe'

if (-not (Test-Path $Python)) {
  throw "Python 3.12 virtual environment is missing: $Python. Create it with the bundled Python and install backend\requirements.txt."
}

$version = & $Python --version
if ($version -notmatch 'Python 3\.12\.') {
  throw "Expected Python 3.12 from .venv-win, got: $version"
}

Write-Host 'Starting central server (9099) ...' -ForegroundColor Cyan
$env:CENTRAL_DATA_DIR = $Data
$env:CENTRAL_ADMIN_PASSWORD = 'test123456'
$env:CENTRAL_HOST = '127.0.0.1'
$env:CENTRAL_PORT = '9099'
Start-Process $Python -WorkingDirectory $Backend -ArgumentList 'central_server.py'
Start-Sleep -Seconds 4

Write-Host 'Starting desktop client ...' -ForegroundColor Cyan
$env:MATRIX_CENTRAL = $Central
$env:MATRIX_AGENT_DATA_DIR = $AgentData
$env:DY_DATA_DIR = $AgentData
$env:DY_PROFILE_DIR = Join-Path $AgentData 'dy_profile'
if (Test-Path $Exe) {
  Start-Process $Exe
} else {
  Write-Host 'Client exe is not built; starting from source.' -ForegroundColor Yellow
  Start-Process $Python -WorkingDirectory $Backend -ArgumentList 'matrix_native_client.py'
}

Write-Host ''
Write-Host '================ Local test ================' -ForegroundColor Green
Write-Host '1. Log in with admin / test123456 in the client window.'
Write-Host '2. Use account login from the client to open the local browser flow.'
Write-Host '3. Downloads and publishing run through this machine and its network.'
Write-Host 'Client log: backend\datas\logs'
Write-Host '===========================================' -ForegroundColor Green
