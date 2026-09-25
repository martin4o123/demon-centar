@echo off
rem ============================================================
rem  ROBOT - DEMON control center
rem  No argument = start. Usage: ROBOT start|stop|status|update
rem ============================================================
setlocal
set "BASE=%~dp0"
set "STOP=%BASE%STOP.flag"

if "%~1"=="stop" goto STOP
if "%~1"=="status" goto STATUS
if "%~1"=="update" goto UPDATE
if "%~1"=="uninstall" goto UNINST

:START
if exist "%STOP%" del "%STOP%"
where py >nul 2>nul
if errorlevel 1 goto NOPY
for /f "delims=" %%i in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE goto NOPY
"%PYEXE%" -c "import flask, MetaTrader5, cryptography, webview" 2>nul
if errorlevel 1 (
  echo [ROBOT] Installing missing libraries, 1-2 min...
  "%PYEXE%" -m pip install --quiet --disable-pip-version-check flask MetaTrader5 cryptography pywebview
)
netstat -ano | find ":5123" | find "LISTENING" >nul
if not errorlevel 1 goto OPEN
start "" "%PYEXE%" "%BASE%scripts\app.py"
timeout /t 10 >nul
netstat -ano | find ":5123" | find "LISTENING" >nul
if errorlevel 1 goto NODEAD
:OPEN
echo [ROBOT] DEMON started.
exit /b 0
:NOPY
echo [ROBOT] ERROR: Python 3.12 not found on this computer!
echo [ROBOT] Run DEMON-Setup.exe again - it installs Python automatically.
pause
exit /b 1
:NODEAD
echo [ROBOT] No response. Retrying after library repair...
"%PYEXE%" -m pip install --quiet --disable-pip-version-check flask MetaTrader5 cryptography pywebview 2>nul
start "" "%PYEXE%" "%BASE%scripts\app.py"
timeout /t 12 >nul
netstat -ano | find ":5123" | find "LISTENING" >nul
if not errorlevel 1 goto OK2
echo.
echo [ROBOT] Still not running. REAL ERROR (screenshot it and send to the seller):
echo -------------------------------------------------------------------
"%PYEXE%" "%BASE%scripts\app.py" 2^>^&1
echo -------------------------------------------------------------------
echo.
pause
exit /b 1
:OK2
echo [ROBOT] DEMON started.
exit /b 0

:STOP
echo stop > "%STOP%"
echo [ROBOT] STOP.flag created - no new trades or restarts.
exit /b 0

:STATUS
py -3.12 "%BASE%scripts\preflight.py"
exit /b 0

:UPDATE
py -3.12 "%BASE%scripts\update_client.py" --apply
exit /b 0

:UNINST
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%uninstall.ps1"
exit /b 0
