@echo off
setlocal
set "APPDATA_DIR=%~dp0datas"
if not exist "%APPDATA_DIR%" mkdir "%APPDATA_DIR%"
set "MATRIX_AGENT_DATA_DIR=%APPDATA_DIR%"
set "DY_DATA_DIR=%APPDATA_DIR%"
set "DY_PROFILE_DIR=%APPDATA_DIR%\dy_profile"
set "API_HOST=127.0.0.1"
set "API_PORT=9080"
set "MATRIX_AGENT_TOKEN_AUTH=1"
set "DY_COMMENT_EDGE_UI_FALLBACK=1"
cd /d "%~dp0"
echo Starting MatrixShipAgent on http://127.0.0.1:9080 ...
python agent_launcher.py
pause
