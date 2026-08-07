@echo off
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "AGENT_DATA=%BACKEND%\datas"
set "PYTHON=%ROOT%\.venv-win\Scripts\python.exe"
set "PYTHONW=%ROOT%\.venv-win\Scripts\pythonw.exe"

REM Central server selection.
REM   1 = start central_server.py on this machine. There is no comic main DB
REM       (MySQL) here, so maindb.ping() fails, find_login_user() falls back to
REM       the local JSON user table, and only admin / test123456 can log in.
REM   0 = use the public central server. Comic accounts can log in, but balance,
REM       charges and tasks are then real production data.
set "START_LOCAL_CENTRAL=0"
if "%START_LOCAL_CENTRAL%"=="1" (
  set "MATRIX_CENTRAL=http://127.0.0.1:9080"
) else (
  set "MATRIX_CENTRAL=https://central.yunlingai.net"
)

set "CENTRAL_HOST=127.0.0.1"
set "CENTRAL_PORT=9080"
set "LOCAL_API_PORT=9081"
set "API_PORT=%LOCAL_API_PORT%"
set "CENTRAL_DATA_DIR=%BACKEND%\central_data"
set "CENTRAL_ADMIN_PASSWORD=test123456"
set "MATRIX_AGENT_DATA_DIR=%AGENT_DATA%"
set "DY_DATA_DIR=%AGENT_DATA%"
set "DY_PROFILE_DIR=%AGENT_DATA%\dy_profile"

REM Feature gates. The client never loads backend\.env, so these must be set in
REM the process environment; putting them in .env has no effect on the client.
REM   MATRIX_VIDEO_REPLACEMENT_ENABLED is checked by the client only; 1 enables
REM   the same-style replacement navigation entry.
REM   MATRIX_XHS_ENABLED is checked by the client, the central server and the
REM   local executor. Against the public central server the central-side value
REM   comes from that host, so setting 1 here does not change it.
set "MATRIX_VIDEO_REPLACEMENT_ENABLED=1"
set "MATRIX_XHS_ENABLED=1"

if not exist "%PYTHON%" (
  echo Missing Python virtual environment: %PYTHON%
  pause
  exit /b 1
)

if not exist "%PYTHONW%" (
  echo Missing Python windowed launcher: %PYTHONW%
  pause
  exit /b 1
)

cd /d "%BACKEND%"

if not "%START_LOCAL_CENTRAL%"=="1" (
  echo Using remote central server: %MATRIX_CENTRAL%
  goto central_ready
)

call :restart_central

call :check_central
if errorlevel 1 (
  echo Starting MatrixShip central server on %MATRIX_CENTRAL% ...
  start "MatrixShip Central" /min "%PYTHON%" central_server.py
)

for /l %%I in (1,1,30) do (
  call :check_central
  if not errorlevel 1 goto central_ready
  timeout /t 1 /nobreak >nul
)

echo Central server did not become ready: %MATRIX_CENTRAL%
echo Check backend\central_server.py output or whether port 9080 is occupied.
pause
exit /b 1

:central_ready
call :restart_local_executor
echo Starting MatrixShip client ...
"%PYTHONW%" matrix_native_client.py
exit /b 0

:check_central
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9080/api/health' -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } } catch { }; exit 1"
exit /b %errorlevel%

:restart_central
echo Restarting MatrixShip central server on %MATRIX_CENTRAL% ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%CENTRAL_PORT% .*LISTENING"') do (
  if not "%%P"=="0" (
    echo Stopping existing central server PID %%P ...
    taskkill /F /PID %%P >nul 2>nul
  )
)
timeout /t 1 /nobreak >nul
exit /b 0

:restart_local_executor
echo Restarting MatrixShip local executor on 127.0.0.1:%LOCAL_API_PORT% ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%LOCAL_API_PORT% .*LISTENING"') do (
  if not "%%P"=="0" (
    echo Stopping existing local executor PID %%P ...
    taskkill /F /PID %%P >nul 2>nul
  )
)
timeout /t 1 /nobreak >nul
exit /b 0
