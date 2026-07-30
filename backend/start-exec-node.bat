@echo off
setlocal
cd /d "%~dp0"

REM ---- edit these for each node ----
if "%CENTRAL_URL%"=="" set "CENTRAL_URL=http://YOUR-CENTRAL-SERVER:9080"
if "%CENTRAL_NODE_SECRET%"=="" set "CENTRAL_NODE_SECRET=matrix-node-secret-change-me"
if "%NODE_NAME%"=="" set "NODE_NAME=%COMPUTERNAME%"
if "%NODE_REGION%"=="" set "NODE_REGION=default"

REM Local node API is private to this machine.  Use 9081 to avoid colliding with
REM central_server when both are tested on the same computer.
if "%LOCAL_API_PORT%"=="" set "LOCAL_API_PORT=9081"
set "LOCAL_API=http://127.0.0.1:%LOCAL_API_PORT%"
set "API_HOST=127.0.0.1"
set "API_PORT=%LOCAL_API_PORT%"
set "MATRIX_AGENT_TOKEN_AUTH=0"
set "DY_COMMENT_EDGE_UI_FALLBACK=1"

echo Starting local execution API on %LOCAL_API% ...
start "MatrixShip Node Local API" cmd /c python api_server.py
timeout /t 5 /nobreak >nul

echo Starting node worker -> %CENTRAL_URL% ...
python agent_worker.py --central "%CENTRAL_URL%" --node-secret "%CENTRAL_NODE_SECRET%" --name "%NODE_NAME%" --region "%NODE_REGION%" --local-api "%LOCAL_API%"
pause
