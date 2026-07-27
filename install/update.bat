@echo off
REM ============================================================================
REM OpenAlgo Update Script for Windows
REM ============================================================================
REM
REM Usage: update.bat
REM
REM This script updates OpenAlgo to the latest version using the UV method.
REM Run from the install\ directory or the openalgo project root.
REM
REM Prerequisites:
REM   - Python 3.12+
REM   - uv package manager (pip install uv)
REM   - Git
REM   - Node.js 20+ (optional, for frontend build)
REM
REM ============================================================================

setlocal enabledelayedexpansion

REM Banner
echo.
echo   ========================================
echo        OpenAlgo Update Script
echo        Windows Edition
echo   ========================================
echo.

REM Detect OpenAlgo directory
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Check if we're in the install\ directory or the project root
if exist "%SCRIPT_DIR%\app.py" (
    set "OPENALGO_DIR=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%\..\app.py" (
    pushd "%SCRIPT_DIR%\.."
    set "OPENALGO_DIR=!CD!"
    popd
) else (
    REM Try current directory
    if exist "app.py" (
        set "OPENALGO_DIR=%CD%"
    ) else (
        echo [ERROR] Could not find OpenAlgo directory.
        echo.
        echo Please run this script from:
        echo   - The openalgo project root directory, OR
        echo   - The install\ directory within openalgo
        echo.
        pause
        exit /b 1
    )
)

echo [INFO] OpenAlgo directory: %OPENALGO_DIR%
echo.

REM Verify git repository
if not exist "%OPENALGO_DIR%\.git" (
    echo [ERROR] Not a git repository: %OPENALGO_DIR%
    echo Please ensure OpenAlgo was installed via git clone.
    echo.
    pause
    exit /b 1
)

REM Check prerequisites
echo [INFO] Checking prerequisites...

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed or not in PATH.
    echo Download from: https://git-scm.com/download/win
    pause
    exit /b 1
)
echo   [OK] Git found

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo   [OK] Python found

REM Check for uv
set "UV_CMD="
where uv >nul 2>&1
if not errorlevel 1 (
    set "UV_CMD=uv"
    echo   [OK] uv found (standalone)
) else (
    python -m uv --version >nul 2>&1
    if not errorlevel 1 (
        set "UV_CMD=python -m uv"
        echo   [OK] uv found (Python module)
    ) else (
        echo [ERROR] uv is not installed.
        echo Install with: pip install uv
        echo.
        pause
        exit /b 1
    )
)
echo.

REM Get current version
pushd "%OPENALGO_DIR%"

for /f "tokens=*" %%i in ('git rev-parse --short HEAD 2^>nul') do set "CURRENT_COMMIT=%%i"
for /f "tokens=*" %%i in ('git branch --show-current 2^>nul') do set "CURRENT_BRANCH=%%i"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=main"

echo [INFO] Current version: %CURRENT_COMMIT% (branch: %CURRENT_BRANCH%)
echo.

REM Generate timestamp for backups
for /f "tokens=2 delims==" %%i in ('wmic os get localdatetime /value 2^>nul ^| findstr LocalDateTime') do set "DT=%%i"
set "TIMESTAMP=%DT:~0,8%_%DT:~8,6%"

REM ========================================
REM Step 1: Backup databases
REM ========================================
echo [Step 1/5] Backing up databases...

set "BACKUP_DIR=%OPENALGO_DIR%\db\backup_%TIMESTAMP%"
set "BACKUP_COUNT=0"

if exist "%OPENALGO_DIR%\db\" (
    md "%BACKUP_DIR%" 2>nul

    for %%f in (openalgo.db logs.db latency.db sandbox.db) do (
        if exist "%OPENALGO_DIR%\db\%%f" (
            copy /y "%OPENALGO_DIR%\db\%%f" "%BACKUP_DIR%\%%f" >nul 2>&1
            echo   Backed up: %%f
            set /a BACKUP_COUNT+=1
        )
    )

    if exist "%OPENALGO_DIR%\db\historify.duckdb" (
        copy /y "%OPENALGO_DIR%\db\historify.duckdb" "%BACKUP_DIR%\historify.duckdb" >nul 2>&1
        echo   Backed up: historify.duckdb
        set /a BACKUP_COUNT+=1
    )

    if !BACKUP_COUNT! EQU 0 (
        echo   No databases found to backup (fresh installation)
        rd "%BACKUP_DIR%" 2>nul
    ) else (
        echo   [OK] Backup location: %BACKUP_DIR%
    )
) else (
    echo   No database directory found (fresh installation)
)
echo.

REM ========================================
REM Step 2: Pull latest code
REM ========================================
echo [Step 2/5] Pulling latest code...

REM Check for local modifications
set "HAS_CHANGES="
for /f "tokens=*" %%i in ('git status --porcelain 2^>nul ^| findstr /v "^??"') do (
    set "HAS_CHANGES=1"
)

set "STASHED="
if defined HAS_CHANGES (
    echo   Local modifications detected. Stashing changes...
    git stash push -m "auto-stash before update %TIMESTAMP%"
    set "STASHED=1"
)

git pull origin %CURRENT_BRANCH%
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to pull latest code.
    echo Please resolve any git conflicts and try again.
    if defined STASHED (
        echo Note: Your changes are stashed. Run 'git stash pop' to restore.
    )
    popd
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('git rev-parse --short HEAD 2^>nul') do set "NEW_COMMIT=%%i"

if "%CURRENT_COMMIT%"=="%NEW_COMMIT%" (
    echo   [OK] Already up to date (%CURRENT_COMMIT%)
) else (
    echo   [OK] Updated: %CURRENT_COMMIT% -^> %NEW_COMMIT%
)

if defined STASHED (
    echo   [NOTE] Local changes were stashed. Use 'git stash pop' to restore.
)
echo.

REM ========================================
REM Step 3: Check environment configuration
REM ========================================
echo [Step 3/5] Checking environment configuration...

if not exist "%OPENALGO_DIR%\.env" (
    echo   [WARNING] No .env file found. Creating from .sample.env...
    if exist "%OPENALGO_DIR%\.sample.env" (
        copy /y "%OPENALGO_DIR%\.sample.env" "%OPENALGO_DIR%\.env" >nul
        echo   [ACTION REQUIRED] Please edit .env with your broker credentials and settings.
    ) else (
        echo   [ERROR] .sample.env not found. Cannot create .env.
    )
) else (
    echo   [OK] Environment file exists.
    echo   Review .sample.env for any new variables added in this update.
)
echo.

REM ========================================
REM Step 4: Update Python dependencies
REM ========================================
echo [Step 4/5] Updating Python dependencies with uv...

%UV_CMD% sync
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to update Python dependencies.
    echo Try running manually: uv sync
    popd
    pause
    exit /b 1
)

echo   [OK] Dependencies updated successfully.
echo.

REM ========================================
REM Step 5: Run database migrations
REM ========================================
echo [Step 5/5] Running database migrations...

if exist "%OPENALGO_DIR%\upgrade\migrate_all.py" (
    %UV_CMD% run upgrade/migrate_all.py
    if errorlevel 1 (
        echo   [WARNING] Some migrations may have had issues. Check output above.
    ) else (
        echo   [OK] Database migrations completed.
    )
) else (
    echo   [WARNING] No migration script found (upgrade\migrate_all.py)
)
echo.

REM ========================================
REM Build frontend if needed
REM ========================================
if not exist "%OPENALGO_DIR%\frontend\dist\" (
    where npm >nul 2>&1
    if not errorlevel 1 (
        echo [OPTIONAL] Building React frontend (dist\ not found)...
        pushd "%OPENALGO_DIR%\frontend"
        call npm install
        call npm run build
        if errorlevel 1 (
            echo   [WARNING] Frontend build failed.
            echo   Run manually: cd frontend ^&^& npm install ^&^& npm run build
        ) else (
            echo   [OK] Frontend built successfully.
        )
        popd
    ) else (
        echo [NOTE] frontend\dist\ not found and Node.js is not installed.
        echo   Install Node.js and run: cd frontend ^&^& npm install ^&^& npm run build
    )
    echo.
)

REM ========================================
REM Summary
REM ========================================
echo.
echo   ========================================
echo   OpenAlgo Update Complete!
echo   ========================================
echo.
echo   Version:   %CURRENT_COMMIT% -^> %NEW_COMMIT%
echo   Branch:    %CURRENT_BRANCH%
echo   Directory: %OPENALGO_DIR%
if exist "%BACKUP_DIR%\" (
    echo   Backup:    %BACKUP_DIR%
)
echo.
echo   Next Steps:
echo     Start application: uv run app.py
echo     API documentation: http://127.0.0.1:5000/api/docs
echo.

if defined STASHED (
    echo   Reminder: Local changes were stashed. Use 'git stash pop' to restore.
    echo.
)

popd
pause
exit /b 0
