@echo off
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "AGENT_DATA=%BACKEND%\datas"
set "PYTHON=%ROOT%\.venv-win\Scripts\python.exe"
set "PYTHONW=%ROOT%\.venv-win\Scripts\pythonw.exe"
set "MATRIX_CENTRAL=http://127.0.0.1:9080"
set "CENTRAL_HOST=127.0.0.1"
set "CENTRAL_PORT=9080"
set "CENTRAL_DATA_DIR=%BACKEND%\central_data"
set "CENTRAL_ADMIN_PASSWORD=test123456"
set "MATRIX_AGENT_DATA_DIR=%AGENT_DATA%"
set "DY_DATA_DIR=%AGENT_DATA%"
set "DY_PROFILE_DIR=%AGENT_DATA%\dy_profile"

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
echo Starting MatrixShip client ...
"%PYTHONW%" matrix_native_client.py
exit /b 0

:check_central
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9080/api/health' -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } } catch { }; exit 1"
exit /b %errorlevel%
