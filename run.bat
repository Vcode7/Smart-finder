@echo off
setlocal EnableDelayedExpansion

REM ==============================================================================
REM Smart Find AI — Production & Demo Launcher
REM ==============================================================================
title Smart Find AI — Launcher

REM Resolve absolute path to project root regardless of launch location
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo ==============================================================================
echo                 SMART FIND AI — APPLICATION LAUNCHER                          
echo ==============================================================================
echo Project Directory: %PROJECT_ROOT%
echo.

REM ------------------------------------------------------------------------------
REM Pre-flight Check: Ensure setup.bat has been run
REM ------------------------------------------------------------------------------
set "VENV_ACTIVATE=%PROJECT_ROOT%backend\venv\Scripts\activate.bat"
set "NODE_MODULES=%PROJECT_ROOT%workspace\node_modules"

if not exist "%VENV_ACTIVATE%" (
    echo [ERROR] Backend virtual environment not found at:
    echo         %PROJECT_ROOT%backend\venv
    echo.
    echo Please run setup.bat first to initialize the environment, install
    echo dependencies, and verify AI/ML models!
    echo ==============================================================================
    pause
    exit /b 1
)

if not exist "%NODE_MODULES%" (
    echo [ERROR] Frontend node_modules not found at:
    echo         %PROJECT_ROOT%workspace\node_modules
    echo.
    echo Please run setup.bat first to install all frontend dependencies!
    echo ==============================================================================
    pause
    exit /b 1
)

if not exist "%PROJECT_ROOT%backend\.env" (
    echo [ERROR] Configuration file backend\.env not found!
    echo Please run setup.bat first to initialize project configurations.
    echo ==============================================================================
    pause
    exit /b 1
)

REM ------------------------------------------------------------------------------
REM Start Backend Server
REM ------------------------------------------------------------------------------
echo [1/3] Starting Smart Find AI Python Backend (Port 8000)...
start "Smart Find AI — Backend (Port 8000)" cmd /k "cd /d "%PROJECT_ROOT%backend" && call "%VENV_ACTIVATE%" && python run.py"

REM ------------------------------------------------------------------------------
REM Wait for Backend to be Ready
REM ------------------------------------------------------------------------------
echo [2/3] Waiting for Backend API to become ready on http://127.0.0.1:8000/health...

set "BACKEND_READY=0"
set "ATTEMPTS=0"
set "MAX_ATTEMPTS=40"

:WAIT_LOOP
set /a ATTEMPTS+=1

powershell -Command "try { $res = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2 -UseBasicParsing; if ($res.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "BACKEND_READY=1"
    goto :BACKEND_UP
)

if %ATTEMPTS% geq %MAX_ATTEMPTS% (
    echo [WARNING] Backend is taking longer than usual to respond.
    echo Proceeding to start frontend, but backend may still be initializing models.
    goto :BACKEND_UP
)

timeout /t 1 /nobreak >nul
goto :WAIT_LOOP

:BACKEND_UP
if "%BACKEND_READY%"=="1" (
    echo [PASS] Backend is online and operational!
)
echo.

REM ------------------------------------------------------------------------------
REM Start Frontend Dev Server
REM ------------------------------------------------------------------------------
echo [3/3] Starting Smart Find AI Next.js Frontend (Port 3000)...
start "Smart Find AI — Frontend (Port 3000)" cmd /k "cd /d "%PROJECT_ROOT%workspace" && npm run dev"

REM Brief pause for Next.js to bind port
timeout /t 2 /nobreak >nul

REM ------------------------------------------------------------------------------
REM Startup Summary & Dashboard
REM ------------------------------------------------------------------------------
echo.
echo ==============================================================================
echo                 SMART FIND AI — SERVICES STARTED                              
echo ==============================================================================
echo.
echo   Web Application:    http://localhost:3000
echo   Backend API:        http://localhost:8000
echo   API Documentation:  http://localhost:8000/docs
echo   Health Check:       http://localhost:8000/health
echo.
echo ==============================================================================
echo Both services are running in their dedicated terminal windows.
echo To stop the application, close the respective terminal windows.
echo ==============================================================================
echo.

REM Optionally open browser to frontend
set /p OPEN_BROWSER="Open Web App in default browser now? [Y/n]: "
if /i not "%OPEN_BROWSER%"=="n" (
    start http://localhost:3000
)

exit /b 0
