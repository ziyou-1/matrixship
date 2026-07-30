param(
  [string]$ExePath = "",
  [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "MatrixShipAgent"
$AppDir = Join-Path $InstallDir "app"
if (-not $DataDir) {
  $DataDir = Join-Path $PSScriptRoot "datas"
}
New-Item -ItemType Directory -Force -Path $AppDir, $DataDir | Out-Null

if (-not $ExePath) {
  $candidate = Join-Path $PSScriptRoot "dist\MatrixShipAgent\MatrixShipAgent.exe"
  if (Test-Path $candidate) { $ExePath = $candidate }
}

if ($ExePath -and (Test-Path $ExePath)) {
  Copy-Item -Force $ExePath (Join-Path $AppDir "MatrixShipAgent.exe")
  $Target = Join-Path $AppDir "MatrixShipAgent.exe"
} else {
  Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "*") $AppDir
  $Target = Join-Path $AppDir "start-matrix-agent.bat"
}

$Wsh = New-Object -ComObject WScript.Shell
$ShortcutDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Shortcut = $Wsh.CreateShortcut((Join-Path $ShortcutDir "矩阵星舰本地助手.lnk"))
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = Split-Path -Parent $Target
$Shortcut.Description = "MatrixShipAgent 本地助手"
$Shortcut.Save()

Write-Host "Installed MatrixShipAgent"
Write-Host "App : $AppDir"
Write-Host "Data: $DataDir"
Write-Host "Start menu shortcut: 矩阵星舰本地助手"
