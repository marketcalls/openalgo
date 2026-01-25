@echo off
REM ============================================================================
REM OpenAlgo Docker Runner for Windows
REM ============================================================================
REM
REM Quick Start (2 commands):
REM   1. Download: curl.exe -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.bat
REM   2. Run:      docker-run.bat
REM
REM Commands:
REM   start    - Start OpenAlgo container (default, runs setup if needed)
REM   stop     - Stop and remove container
REM   restart  - Restart container
REM   logs     - View container logs (live)
REM   pull     - Pull latest image from Docker Hub
REM   status   - Show container status
REM   shell    - Open bash shell in container
REM   setup    - Re-run setup (regenerate keys, edit .env)
REM   help     - Show this help
REM
REM Prerequisites:
REM   - Docker Desktop installed and running
REM
REM ============================================================================

setlocal enabledelayedexpansion

REM Configuration
set IMAGE=marketcalls/openalgo:latest
set CONTAINER=openalgo
set ENV_FILE=.env
set SAMPLE_ENV_URL=https://raw.githubusercontent.com/marketcalls/openalgo/main/.sample.env
set OPENALGO_DIR=%USERPROFILE%\openalgo
set SETUP_FAILED=0

REM Banner
echo.
echo   ========================================
echo        OpenAlgo Docker Runner
echo        Windows Desktop Edition
echo   ========================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running!
    echo.
    echo Please start Docker Desktop first:
    echo   1. Open Docker Desktop from Start Menu
    echo   2. Wait for Docker to fully start
    echo   3. Run this script again
    echo.
    pause
    exit /b 1
)

REM Parse command
set CMD=%1
if "%CMD%"=="" set CMD=start

if /i "%CMD%"=="start" goto start
if /i "%CMD%"=="stop" goto stop
if /i "%CMD%"=="restart" goto restart
if /i "%CMD%"=="logs" goto logs
if /i "%CMD%"=="pull" goto pull
if /i "%CMD%"=="status" goto status
if /i "%CMD%"=="shell" goto shell
if /i "%CMD%"=="setup" goto setup
if /i "%CMD%"=="help" goto help
goto help

:setup
echo [INFO] Setting up OpenAlgo...
echo.

REM Create openalgo directory with full path
if not exist "%OPENALGO_DIR%\" (
    echo [INFO] Creating OpenAlgo directory at %OPENALGO_DIR%...
    md "%OPENALGO_DIR%" 2>nul
    if errorlevel 1 (
        echo [ERROR] Failed to create directory %OPENALGO_DIR%
        set SETUP_FAILED=1
        goto setup_end
    )
)

REM Create db directory
if not exist "%OPENALGO_DIR%\db\" (
    echo [INFO] Creating database directory...
    md "%OPENALGO_DIR%\db" 2>nul
    if errorlevel 1 (
        echo [ERROR] Failed to create database directory
        set SETUP_FAILED=1
        goto setup_end
    )
)

REM Check if .env already exists
if exist "%OPENALGO_DIR%\%ENV_FILE%" (
    echo [WARNING] .env file already exists at %OPENALGO_DIR%\%ENV_FILE%
    set /p OVERWRITE="Do you want to overwrite it? (y/n): "
    if /i not "!OVERWRITE!"=="y" (
        echo [INFO] Setup cancelled. Using existing .env file.
        goto setup_end
    )
)

REM Download sample.env from GitHub using curl.exe (not PowerShell alias)
echo [INFO] Downloading configuration template from GitHub...

REM Try curl.exe first (Windows 10/11 has this)
where curl.exe >nul 2>&1
if errorlevel 1 (
    echo [INFO] curl.exe not found, trying PowerShell...
    powershell -Command "Invoke-WebRequest -Uri '%SAMPLE_ENV_URL%' -OutFile '%OPENALGO_DIR%\%ENV_FILE%'" 2>nul
) else (
    curl.exe -sL "%SAMPLE_ENV_URL%" -o "%OPENALGO_DIR%\%ENV_FILE%" 2>nul
)

REM Check if download succeeded
if not exist "%OPENALGO_DIR%\%ENV_FILE%" (
    echo [ERROR] Failed to download configuration template!
    echo Please check your internet connection.
    echo.
    echo Manual setup:
    echo   1. Download .sample.env from https://github.com/marketcalls/openalgo
    echo   2. Save it as %OPENALGO_DIR%\.env
    echo   3. Run this script again
    set SETUP_FAILED=1
    goto setup_end
)
echo [OK] Configuration template downloaded.

REM Generate random keys using Python
echo [INFO] Generating secure keys...
where python >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Python not found. You need to manually set APP_KEY and API_KEY_PEPPER.
    echo Generate keys at: https://www.uuidgenerator.net/
    goto open_env
)

for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set APP_KEY=%%i
for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set API_KEY_PEPPER=%%i

REM Update .env file with generated keys
echo [INFO] Updating configuration with secure keys...
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace '3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84', '%APP_KEY%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772', '%API_KEY_PEPPER%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
echo [OK] Secure keys generated and saved.

:open_env
echo.
echo   ========================================
echo   IMPORTANT: Configure your broker
echo   ========================================
echo.
echo   Please edit %OPENALGO_DIR%\%ENV_FILE%
echo   and update:
echo.
echo   1. BROKER_API_KEY=your_broker_api_key
echo   2. BROKER_API_SECRET=your_broker_api_secret
echo   3. Change broker name if needed (default: zerodha)
echo.
echo   Opening .env file in Notepad...
echo.
pause

REM Open .env in notepad
notepad "%OPENALGO_DIR%\%ENV_FILE%"

echo.
echo [OK] Setup complete!
echo.
echo   Data directory: %OPENALGO_DIR%
echo   Config file:    %OPENALGO_DIR%\%ENV_FILE%
echo   Database:       %OPENALGO_DIR%\db\
echo.

:setup_end
exit /b %SETUP_FAILED%

:start
echo [INFO] Starting OpenAlgo...
echo.

REM Check if setup is needed
if not exist "%OPENALGO_DIR%\%ENV_FILE%" (
    echo [INFO] First time setup detected. Running setup...
    echo.
    call :setup
    if errorlevel 1 (
        echo.
        echo [ERROR] Setup failed. Cannot start OpenAlgo.
        echo Please fix the issues above and try again.
        goto end
    )
    echo.
    echo [INFO] Starting OpenAlgo after setup...
    echo.
)

REM Create db directory if not exists
if not exist "%OPENALGO_DIR%\db\" (
    echo [INFO] Creating database directory...
    md "%OPENALGO_DIR%\db" 2>nul
)

REM Pull latest image
echo [INFO] Pulling latest image...
docker pull %IMAGE%
if errorlevel 1 (
    echo [WARNING] Could not pull latest image. Using cached version if available.
)

REM Stop and remove existing container if exists
docker stop %CONTAINER% >nul 2>&1
docker rm %CONTAINER% >nul 2>&1

REM Run container
echo [INFO] Starting container...
docker run -d ^
    --name %CONTAINER% ^
    -p 5000:5000 ^
    -p 8765:8765 ^
    -v "%OPENALGO_DIR%\db:/app/db" ^
    -v "%OPENALGO_DIR%\.env:/app/.env:ro" ^
    --restart unless-stopped ^
    %IMAGE%

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start container!
    echo.
    echo Troubleshooting:
    echo   1. Check if ports 5000 and 8765 are available
    echo   2. Ensure Docker Desktop is running
    echo   3. Check .env file: %OPENALGO_DIR%\%ENV_FILE%
    echo.
    goto end
)

echo.
echo [SUCCESS] OpenAlgo started successfully!
echo.
echo   ========================================
echo   Web UI:     http://127.0.0.1:5000
echo   WebSocket:  ws://127.0.0.1:8765
echo   ========================================
echo.
echo   Data directory: %OPENALGO_DIR%
echo.
echo   Useful commands:
echo     docker-run.bat logs     - View logs
echo     docker-run.bat stop     - Stop OpenAlgo
echo     docker-run.bat restart  - Restart OpenAlgo
echo.
goto end

:stop
echo [INFO] Stopping OpenAlgo...
docker stop %CONTAINER% >nul 2>&1
docker rm %CONTAINER% >nul 2>&1
echo [OK] OpenAlgo stopped.
goto end

:restart
echo [INFO] Restarting OpenAlgo...
docker stop %CONTAINER% >nul 2>&1
docker rm %CONTAINER% >nul 2>&1
echo [OK] OpenAlgo stopped.
echo.
goto start

:logs
echo [INFO] Showing logs (Press Ctrl+C to exit)...
echo.
docker logs -f %CONTAINER%
goto end

:pull
echo [INFO] Pulling latest image...
docker pull %IMAGE%
if errorlevel 1 (
    echo [ERROR] Failed to pull image.
) else (
    echo [OK] Image updated successfully.
    echo [INFO] Run 'docker-run.bat restart' to apply the update.
)
goto end

:status
echo [INFO] Container status:
echo.
docker ps -a --filter "name=%CONTAINER%" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.
REM Check if container is running
docker ps --filter "name=%CONTAINER%" --filter "status=running" | findstr %CONTAINER% >nul
if errorlevel 1 (
    echo [STATUS] OpenAlgo is NOT running.
) else (
    echo [STATUS] OpenAlgo is running.
    echo.
    echo   Web UI: http://127.0.0.1:5000
)
echo.
echo   Data directory: %OPENALGO_DIR%
goto end

:shell
echo [INFO] Opening shell in container...
docker exec -it %CONTAINER% /bin/bash
goto end

:help
echo.
echo Usage: docker-run.bat [command]
echo.
echo Commands:
echo   start    Start OpenAlgo (runs setup if needed, default)
echo   stop     Stop and remove container
echo   restart  Restart container
echo   logs     View container logs (live)
echo   pull     Pull latest image from Docker Hub
echo   status   Show container status
echo   shell    Open bash shell in container
echo   setup    Re-run setup (regenerate keys, edit .env)
echo   help     Show this help
echo.
echo Quick Start:
echo   1. Install Docker Desktop: https://www.docker.com/products/docker-desktop
echo   2. Download this script (use PowerShell):
echo      curl.exe -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.bat
echo   3. Run: docker-run.bat
echo.
echo Data Location: %OPENALGO_DIR%
echo   - Config:   %OPENALGO_DIR%\.env
echo   - Database: %OPENALGO_DIR%\db\
echo.
goto end

:end
endlocal
