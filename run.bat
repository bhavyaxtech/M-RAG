@echo off
setlocal
cd /d "%~dp0"
title M-RAG demo
mode con: cols=88 lines=30

echo.
echo   ================================================
echo     M-RAG  -  Multimodal datasheet retrieval demo
echo   ================================================
echo.

REM ---------- 1. Find Python ----------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if defined PY goto :have_python
where python >nul 2>&1 && set "PY=python"
if defined PY goto :have_python
goto :no_python
:have_python

%PY% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info < (3,14) else 1)" >nul 2>&1
if errorlevel 1 goto :bad_python_version

REM ---------- 2. Settings file ----------
REM Without one, run in free mode: local search model + Codex on a ChatGPT login.
if exist ".env" goto :have_env
echo   No .env file found. Creating one for free mode (local search + Codex).
echo.
> ".env" echo EMBED_PROVIDER=local
>> ".env" echo LLM_PROVIDER=codex
:have_env
set "USE_LOCAL="
set "USE_CODEX="
findstr /R /I /C:"^ *EMBED_PROVIDER *= *local" ".env" >nul 2>&1 && set "USE_LOCAL=1"
findstr /R /I /C:"^ *LLM_PROVIDER *= *codex" ".env" >nul 2>&1 && set "USE_CODEX=1"

REM ---------- 3. Create the virtual environment (first run only) ----------
if exist ".venv\Scripts\python.exe" goto :have_venv
echo   First run detected. Setting up - this takes about 3 minutes.
echo   You only ever have to wait for this once.
echo.
echo   [1/2] Creating the Python environment...
%PY% -m venv .venv
if errorlevel 1 goto :fail_venv
:have_venv

REM ---------- 4. Install dependencies (first run only) ----------
if exist ".venv\.demo-deps-installed" goto :have_deps
echo   [2/2] Installing dependencies. Please leave this window alone...
echo.
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements-demo.txt --quiet --disable-pip-version-check
if errorlevel 1 goto :fail_deps
echo ok> ".venv\.demo-deps-installed"
echo   Setup complete.
echo.
:have_deps

if not defined USE_LOCAL goto :have_local_deps
if exist ".venv\.local-deps-installed" goto :have_local_deps
echo   Installing the local search model runtime. About 300 MB, first run only...
echo.
".venv\Scripts\python.exe" -m pip install -r requirements-local.txt --quiet --disable-pip-version-check
if errorlevel 1 goto :fail_deps
echo ok> ".venv\.local-deps-installed"
:have_local_deps

REM ---------- 4b. Codex CLI (free mode only) ----------
if not defined USE_CODEX goto :have_codex
where codex >nul 2>&1 && goto :codex_installed
where npm >nul 2>&1 || goto :no_node
echo   Installing the Codex CLI...
call npm install -g @openai/codex@latest
if errorlevel 1 goto :fail_codex_install
:codex_installed
call codex login status >nul 2>&1
if not errorlevel 1 goto :have_codex
echo.
echo   Codex needs you to sign in with a ChatGPT account.
echo   A browser window will open. Sign in there, then come back here.
echo.
call codex login
:have_codex

REM ---------- 4c. Check everything works before starting ----------
set "PREFLIGHT_ARGS="
if exist ".venv\.preflight-embed-ok" set "PREFLIGHT_ARGS=--skip-embed"
if not defined USE_LOCAL if not defined USE_CODEX goto :preflight_done
echo   Checking the setup...
echo.
".venv\Scripts\python.exe" -m scripts.preflight %PREFLIGHT_ARGS%
if errorlevel 1 goto :fail_preflight
if defined USE_LOCAL echo ok> ".venv\.preflight-embed-ok"
echo.
:preflight_done

REM ---------- 5. Open the browser once the server answers ----------
if defined MRAG_NO_BROWSER goto :browser_done
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 90;$i++){try{$null=Invoke-WebRequest -Uri 'http://localhost:8000/api/health' -UseBasicParsing -TimeoutSec 2; Start-Process 'http://localhost:8000'; break}catch{Start-Sleep -Seconds 1}}"
:browser_done

REM ---------- 6. Run ----------
echo   Starting the demo server...
echo.
echo   Your browser will open automatically at:  http://localhost:8000
echo.
echo   Leave this black window OPEN for the whole demo.
echo   Closing it shuts the demo down.
echo.
echo   ------------------------------------------------
echo.
".venv\Scripts\python.exe" -m uvicorn api.server:app --port 8000
goto :end

REM ---------- Failure messages ----------
:no_python
echo   PROBLEM: Python is not installed, or Windows cannot find it.
echo.
echo   Fix it like this:
echo     1. Go to  https://www.python.org/downloads/
echo     2. Download Python 3.12 for Windows and run the installer.
echo     3. IMPORTANT: on the very first installer screen, tick the box
echo        that says "Add python.exe to PATH" before clicking Install.
echo     4. Restart the computer, then double-click run.bat again.
echo.
goto :end

:bad_python_version
echo   PROBLEM: your Python version is too old or too new for this demo.
echo.
%PY% --version
echo.
echo   This demo needs Python 3.10, 3.11, 3.12 or 3.13.
echo   Install Python 3.12 from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup.
echo.
goto :end

:no_node
echo   PROBLEM: Node.js is not installed. Codex needs it.
echo.
echo   Fix it like this:
echo     1. Go to  https://nodejs.org/
echo     2. Download the LTS version for Windows and run the installer
echo        with the default options.
echo     3. Close this window, then double-click run.bat again.
echo.
goto :end

:fail_codex_install
echo.
echo   PROBLEM: could not install the Codex CLI.
echo   Check your internet connection and run this file again.
echo   If it keeps failing, take a photo of this window and send it to Abhilash.
echo.
goto :end

:fail_preflight
echo   The demo did not start because of the problem above.
echo   Fix it, then double-click run.bat again.
echo   If you are stuck, take a photo of this window and send it to Abhilash.
echo.
goto :end

:fail_venv
echo.
echo   PROBLEM: could not create the Python environment.
echo   Take a photo of this window and send it to Abhilash.
echo.
goto :end

:fail_deps
echo.
echo   PROBLEM: could not install the dependencies.
echo   Check your internet connection and run this file again.
echo   If it keeps failing, take a photo of this window and send it to Abhilash.
echo.
goto :end

:end
echo.
pause
endlocal
