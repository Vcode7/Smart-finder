@echo off
setlocal EnableDelayedExpansion

REM ==============================================================================
REM Smart Find AI — Complete Automated Setup & Validation Script
REM ==============================================================================
title Smart Find AI — Setup & Validation

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

set "STATUS_BACKEND=FAIL"
set "STATUS_FRONTEND=FAIL"
set "STATUS_DEPENDENCIES=FAIL"
set "STATUS_MODELS=FAIL"
set "STATUS_STARTUP=FAIL"
set "STATUS_ENDPOINTS=FAIL"
set "STATUS_CORE=FAIL"
set "STATUS_BUILD=FAIL"

echo ==============================================================================
echo                 SMART FIND AI — PROJECT SETUP AND VALIDATION                  
echo ==============================================================================
echo Project Root: %PROJECT_ROOT%
echo.

REM ------------------------------------------------------------------------------
REM STEP 1: Detect and Validate Prerequisites
REM ------------------------------------------------------------------------------
echo [STEP 1/7] Detecting and Validating Required Prerequisites...

REM 1.1 Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Python 3 was not found in PATH!
    echo Please install Python 3.10+ and ensure "Add Python to PATH" is checked.
    goto :FAIL_STOP
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo [PASS] Python detected: %PY_VER%

REM 1.2 Node.js
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Node.js was not found in PATH!
    echo Please install Node.js 18+ from https://nodejs.org/
    goto :FAIL_STOP
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do set "NODE_VER=%%v"
echo [PASS] Node.js detected: %NODE_VER%

REM 1.3 npm
where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FAIL] npm was not found in PATH!
    goto :FAIL_STOP
)
for /f "tokens=*" %%v in ('npm --version 2^>^&1') do set "NPM_VER=%%v"
echo [PASS] npm detected: %NPM_VER%

REM 1.4 Optional tools check (ffmpeg, tesseract, git)
where git >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [PASS] git detected
) else (
    echo [INFO] git not in PATH (optional)
)

where ffmpeg >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [PASS] ffmpeg detected
) else (
    echo [INFO] ffmpeg not in PATH (InsightFace/media fallback will use internal handlers)
)

where tesseract >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [PASS] tesseract OCR detected
) else if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo [PASS] tesseract OCR detected at "C:\Program Files\Tesseract-OCR\tesseract.exe"
) else (
    echo [INFO] tesseract OCR not found in default locations (optional for OCR)
)
echo.

REM ------------------------------------------------------------------------------
REM STEP 2: Configure Environment Files & Directory Structure
REM ------------------------------------------------------------------------------
echo [STEP 2/7] Checking Environment Configuration Files...

REM Backend .env
if not exist "%PROJECT_ROOT%backend\.env" (
    if exist "%PROJECT_ROOT%backend\.env.example" (
        echo [INFO] Creating backend\.env from backend\.env.example...
        copy "%PROJECT_ROOT%backend\.env.example" "%PROJECT_ROOT%backend\.env" >nul
        echo [PASS] Created backend\.env
    ) else (
        echo [FAIL] Missing backend\.env and backend\.env.example!
        goto :FAIL_STOP
    )
) else (
    echo [PASS] backend\.env exists
)

REM Workspace .env
if not exist "%PROJECT_ROOT%workspace\.env" (
    if exist "%PROJECT_ROOT%workspace\.env.example" (
        echo [INFO] Creating workspace\.env from workspace\.env.example...
        copy "%PROJECT_ROOT%workspace\.env.example" "%PROJECT_ROOT%workspace\.env" >nul
        echo [PASS] Created workspace\.env
    ) else (
        echo [FAIL] Missing workspace\.env and workspace\.env.example!
        goto :FAIL_STOP
    )
) else (
    echo [PASS] workspace\.env exists
)

REM Ensure required storage directories exist
if not exist "%PROJECT_ROOT%workspace\data" mkdir "%PROJECT_ROOT%workspace\data"
if not exist "%PROJECT_ROOT%workspace\uploads" mkdir "%PROJECT_ROOT%workspace\uploads"
if not exist "%PROJECT_ROOT%workspace\knowledge_base" mkdir "%PROJECT_ROOT%workspace\knowledge_base"
echo [PASS] Storage directories verified (data, uploads, knowledge_base)
echo.

REM ------------------------------------------------------------------------------
REM STEP 3: Setup Backend Virtual Environment & Dependencies
REM ------------------------------------------------------------------------------
echo [STEP 3/7] Setting Up Backend Python Virtual Environment...

set "VENV_DIR=%PROJECT_ROOT%backend\venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [INFO] Creating dedicated virtual environment at backend\venv...
    python -m venv --system-site-packages "%VENV_DIR%"
    if !ERRORLEVEL! neq 0 (
        echo [FAIL] Failed to create Python virtual environment!
        goto :FAIL_STOP
    )
    echo [PASS] Virtual environment created successfully.
) else (
    echo [PASS] Reusing existing virtual environment at backend\venv.
)

REM Activate Virtual Environment
call "%VENV_DIR%\Scripts\activate.bat"
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Failed to activate virtual environment!
    goto :FAIL_STOP
)
echo [PASS] Virtual environment activated.

echo [INFO] Installing / verifying backend dependencies from backend\requirements.txt...
"%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%backend\requirements.txt"
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Failed to install backend dependencies!
    goto :FAIL_STOP
)
echo [PASS] Backend dependencies verified.
set "STATUS_DEPENDENCIES=PASS"
echo.

REM ------------------------------------------------------------------------------
REM STEP 4: Install Frontend Dependencies
REM ------------------------------------------------------------------------------
echo [STEP 4/7] Checking Frontend Dependencies...

if not exist "%PROJECT_ROOT%workspace\node_modules" (
    echo [INFO] Installing frontend dependencies with npm install in workspace...
    call npm --prefix "%PROJECT_ROOT%workspace" install
    if !ERRORLEVEL! neq 0 (
        echo [FAIL] Failed to install frontend npm dependencies!
        goto :FAIL_STOP
    )
    echo [PASS] Frontend dependencies installed.
) else (
    echo [PASS] Reusing existing frontend node_modules.
)
set "STATUS_FRONTEND=PASS"
echo.

REM ------------------------------------------------------------------------------
REM STEP 5: Verify AI/ML Models & Local Caches
REM ------------------------------------------------------------------------------
echo [STEP 5/7] Verifying AI/ML Models (Qwen3, Jina CLIP, InsightFace, Whisper)...

"%VENV_PYTHON%" -c "import sys; sys.path.insert(0, r'%PROJECT_ROOT%backend'); from app.search.model_pipeline import get_text_embedding, _get_insightface_app, _get_whisper_model; v = get_text_embedding('test'); assert v and len(v)==1024; _get_insightface_app(); _get_whisper_model(); print('[PASS] Core AI/ML models loaded and functional.')"
if %ERRORLEVEL% neq 0 (
    echo [FAIL] AI/ML model verification failed!
    goto :FAIL_STOP
)
echo [PASS] AI/ML models verified without re-downloading existing weights.
set "STATUS_MODELS=PASS"
echo.

REM ------------------------------------------------------------------------------
REM STEP 6: Execute Backend Validation & API Endpoint Testing
REM ------------------------------------------------------------------------------
echo [STEP 6/7] Running Automated Backend Validation & Live Endpoint Tests...

"%VENV_PYTHON%" "%PROJECT_ROOT%backend\validate_backend.py"
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Backend validation or endpoint tests failed!
    goto :FAIL_STOP
)
set "STATUS_BACKEND=PASS"
set "STATUS_STARTUP=PASS"
set "STATUS_ENDPOINTS=PASS"
set "STATUS_CORE=PASS"
echo.

REM ------------------------------------------------------------------------------
REM STEP 7: Validate Frontend Build
REM ------------------------------------------------------------------------------
echo [STEP 7/7] Validating Frontend Production Build (Next.js Turbopack)...

call npm --prefix "%PROJECT_ROOT%workspace" run build
if %ERRORLEVEL% neq 0 (
    echo [FAIL] Frontend build validation failed!
    goto :FAIL_STOP
)
echo [PASS] Frontend compiled and built successfully with 0 errors.
set "STATUS_BUILD=PASS"
echo.

REM ------------------------------------------------------------------------------
REM FINAL SUMMARY
REM ------------------------------------------------------------------------------
:PRINT_SUMMARY
echo ==============================================================================
echo SETUP COMPLETE
echo ==============================================================================
echo Backend: %STATUS_BACKEND%
echo Frontend: %STATUS_FRONTEND%
echo Dependencies: %STATUS_DEPENDENCIES%
echo Models: %STATUS_MODELS%
echo Backend startup: %STATUS_STARTUP%
echo API endpoints: %STATUS_ENDPOINTS%
echo Core functionality: %STATUS_CORE%
echo Frontend build: %STATUS_BUILD%
echo ==============================================================================
echo You can now launch the application by running: run.bat
echo ==============================================================================
exit /b 0

:FAIL_STOP
echo.
echo ==============================================================================
echo SETUP FAILED
echo ==============================================================================
echo Backend: %STATUS_BACKEND%
echo Frontend: %STATUS_FRONTEND%
echo Dependencies: %STATUS_DEPENDENCIES%
echo Models: %STATUS_MODELS%
echo Backend startup: %STATUS_STARTUP%
echo API endpoints: %STATUS_ENDPOINTS%
echo Core functionality: %STATUS_CORE%
echo Frontend build: %STATUS_BUILD%
echo ==============================================================================
echo Please resolve the error above and rerun setup.bat.
exit /b 1
