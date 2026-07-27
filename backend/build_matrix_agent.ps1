param(
  [string]$Python = "",
  [string]$Name = "MatrixShipAgent"
)

# Builds the MatrixShip local client (MatrixShipAgent.exe).
#
# CRITICAL: Douyin request signing (a_bogus / X-Bogus / login) runs
# static/*.js through PyExecJS, which needs (1) the JS files, (2) node_modules
# (jsrsasign) and (3) a Node runtime. End-user machines may not have Node, so we
# bundle vendor/node/node.exe and runtime_paths.ensure_node_on_path() puts it on
# PATH at startup. Omit any of these and signing silently breaks. There is a
# frozen self-test (sign_selftest.py) — run it after building to verify.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not $Python) {
  $py312 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
  if (Test-Path $py312) {
    $Python = $py312
  } else {
    $Python = "python"
  }
}

try {
  $resolvedPython = if (Test-Path $Python) { $Python } else { (Get-Command $Python -ErrorAction Stop).Source }
  if ($resolvedPython -like "*hermes-agent*") {
    $py312 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $py312) {
      $Python = $py312
    }
  }
} catch {
}

Write-Host "[1/6] Checking PyInstaller..."
@'
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("PyInstaller") else 1)
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { & $Python -m pip install pyinstaller }

Write-Host "[2/6] Ensuring node_modules (jsrsasign)..."
if (-not (Test-Path "node_modules\jsrsasign")) {
  if (Get-Command npm -ErrorAction SilentlyContinue) { npm install --no-audit --no-fund }
  else { throw "npm not found and node_modules/jsrsasign missing — signing will break." }
}

Write-Host "[3/6] Staging a stable node.exe for bundling..."
$nodeCmd = (Get-Command node -ErrorAction SilentlyContinue).Source
New-Item -ItemType Directory -Force -Path "vendor\node" | Out-Null
if ($nodeCmd -and (Test-Path $nodeCmd)) {
  Copy-Item -Force $nodeCmd "vendor\node\node.exe"
  Write-Host "  bundled node: $nodeCmd"
} elseif (-not (Test-Path "vendor\node\node.exe")) {
  throw "node.exe not found on PATH and none staged at vendor\node\node.exe — signing will break on machines without Node."
}

Write-Host "[4/6] Compiling source (sanity)..."
& $Python -m py_compile agent_launcher.py api_server.py runtime_paths.py sign_selftest.py `
  edge_ui_comment.py send_comment.py utils\cookie_util.py utils\common_util.py utils\dy_util.py `
  builder\header.py builder\params.py dy_apis\douyin_api.py

$common = @(
  "--noconfirm", "--clean",
  "--add-data", "static;static",
  "--add-data", "assets;assets",
  "--add-data", "legal;legal",
  "--add-data", "node_modules;node_modules",
  "--add-data", "vendor\node\node.exe;node",
  "--collect-all", "playwright",
  "--hidden-import", "execjs",
  "--hidden-import", "static.Live_pb2",
  "--hidden-import", "static.Request_pb2",
  "--hidden-import", "static.Response_pb2",
  "--hidden-import", "google.protobuf",
  "--hidden-import", "playwright.sync_api",
  "--hidden-import", "playwright.async_api",
  "--hidden-import", "pyautogui",
  "--hidden-import", "pygetwindow",
  "--hidden-import", "pyperclip",
  "--hidden-import", "PIL",
  "--hidden-import", "requests",
  "--collect-submodules", "builder",
  "--collect-submodules", "dy_apis",
  "--collect-submodules", "dy_live",
  "--collect-submodules", "utils"
)

Write-Host "[5/6] Building self-test exe (signer proof)..."
& $Python -m PyInstaller @common --console --name "SignSelfTest" `
  --hidden-import execjs sign_selftest.py

Write-Host "[6/6] Building $Name.exe (native Qt desktop client)..."
& $Python -m PyInstaller @common --windowed --icon "assets\app.ico" --name $Name matrix_native_client.py

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $Root\dist\$Name\$Name.exe"
Write-Host "Verify signing in the frozen bundle by running:"
Write-Host "  $Root\dist\SignSelfTest\SignSelfTest.exe   (expect FROZEN_SIGNER_OK)"
Write-Host "[7/7] Building installer (Inno Setup)..."
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
  & $iscc "installer\MatrixShipAgent.iss"
  $setup = Join-Path $Root "dist\installer\MatrixShipAgent-Setup.exe"
  if (Test-Path $setup) {
    Write-Host "Installer -> $setup"
  }
} else {
  Write-Host "Inno Setup not found. Install once (winget install JRSoftware.InnoSetup), then:"
  Write-Host "  & 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' installer\MatrixShipAgent.iss"
}

Write-Host ""
Write-Host "First run: user runs the installed exe -> signs in through the native client. Config saved to:"
Write-Host "  %APPDATA%\MatrixShipAgent\data\client_config.json"
