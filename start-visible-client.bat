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
set "LOCAL_API_PORT=9081"
set "API_PORT=%LOCAL_API_PORT%"
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
rem 只按端口杀不够：抢不到 9081 的那个客户端进程会活下来，它内嵌的
rem local-browser worker 继续轮询中心服并把任务打到别人的 9081 引擎上，
rem 于是同一批任务被执行两遍（浏览器反复弹窗）。按命令行清掉全部残留客户端。
rem 进程名必须是 python/pythonw：否则执行这行的 powershell.exe 会因为自己的
rem 命令行里带着关键字而自杀。$PID 排除同理，双保险。
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.ProcessId -ne $PID -and $_.CommandLine -like '*matrix_native_client.py*' } | ForEach-Object { Write-Host ('Stopping stale client PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul
exit /b 0
