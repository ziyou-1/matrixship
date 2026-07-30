@echo off
setlocal
cd /d "%~dp0"
if "%CENTRAL_HOST%"=="" set "CENTRAL_HOST=0.0.0.0"
if "%CENTRAL_PORT%"=="" set "CENTRAL_PORT=9080"
if "%CENTRAL_NODE_SECRET%"=="" set "CENTRAL_NODE_SECRET=matrix-node-secret-change-me"
echo Starting MatrixShip Central Scheduler on http://%CENTRAL_HOST%:%CENTRAL_PORT%
echo IMPORTANT: set CENTRAL_NODE_SECRET to a strong secret in production.
python central_server.py
pause
