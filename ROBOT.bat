@echo off
chcp 65001 >nul
rem ============================================================
rem  ROBOT — управление на DEMON (център за управления)
rem  Без аргумент = старт. Употреба: ROBOT start|stop|status|update
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
  echo [ROBOT] Липсват библиотеки — инсталирам ги автоматично, 1-2 мин...
  "%PYEXE%" -m pip install --quiet --disable-pip-version-check flask MetaTrader5 cryptography pywebview
)
netstat -ano | find ":5123" | find "LISTENING" >nul
if not errorlevel 1 goto OPEN
start "" "%PYEXE%" "%BASE%scripts\app.py"
timeout /t 10 >nul
netstat -ano | find ":5123" | find "LISTENING" >nul
if errorlevel 1 goto NODEAD
:OPEN
echo [ROBOT] DEMON се стартира...
exit /b 0
:NOPY
echo [ROBOT] ГРЕШКА: Python 3.12 не е намерен на този компютър!
echo [ROBOT] Пусни отново DEMON-Setup.exe — той инсталира Python автоматично.
pause
exit /b 1
:NODEAD
echo [ROBOT] Таблото не отговаря. Опитвам още веднъж след поправка на библиотеките...
"%PYEXE%" -m pip install --quiet --disable-pip-version-check flask MetaTrader5 cryptography pywebview 2>nul
start "" "%PYEXE%" "%BASE%scripts\app.py"
timeout /t 12 >nul
netstat -ano | find ":5123" | find "LISTENING" >nul
if not errorlevel 1 goto OK2
echo.
echo [ROBOT] Програмата пак НЕ тръгна. РЕАЛНАТА ГРЕШКА (снимай я и я пратете на продавача):
echo -------------------------------------------------------------------
"%PYEXE%" "%BASE%scripts\app.py" 2^>^&1
echo -------------------------------------------------------------------
echo.
pause
exit /b 1
:OK2
echo [ROBOT] DEMON се стартира...
exit /b 0

:STOP
echo stop > "%STOP%"
echo [ROBOT] STOP.flag е създаден — няма нови сделки и рестартове.
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
