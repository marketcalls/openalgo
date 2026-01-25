@echo off
REM ============================================================================
REM OpenAlgo Docker Runner for Windows
REM ============================================================================
REM
REM Usage: docker-run.bat [command]
REM
REM Commands:
REM   start    - Start OpenAlgo container (default)
REM   stop     - Stop and remove container
REM   restart  - Restart container
REM   logs     - View container logs (live)
REM   pull     - Pull latest image from Docker Hub
REM   status   - Show container status
REM   shell    - Open bash shell in container
REM   setup    - Initial setup (create .env from sample)
REM   help     - Show this help
REM
REM Prerequisites:
REM   1. Docker Desktop installed and running
REM   2. .env file configured (run 'docker-run.bat setup' first)
REM
REM ============================================================================

setlocal enabledelayedexpansion

REM Configuration
set IMAGE=marketcalls/openalgo:latest
set CONTAINER=openalgo
set ENV_FILE=.env
set SAMPLE_ENV=.sample.env

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
REM Go to parent directory (project root)
cd /d "%SCRIPT_DIR%.."
set PROJECT_DIR=%cd%

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

REM Check if .env already exists
if exist "%PROJECT_DIR%\%ENV_FILE%" (
    echo [WARNING] .env file already exists!
    set /p OVERWRITE="Do you want to overwrite it? (y/n): "
    if /i not "!OVERWRITE!"=="y" (
        echo [INFO] Setup cancelled. Using existing .env file.
        goto end
    )
)

REM Check if sample.env exists
if not exist "%PROJECT_DIR%\%SAMPLE_ENV%" (
    echo [ERROR] %SAMPLE_ENV% not found!
    echo Please ensure you are in the OpenAlgo project directory.
    goto end
)

REM Copy sample.env to .env
copy "%PROJECT_DIR%\%SAMPLE_ENV%" "%PROJECT_DIR%\%ENV_FILE%" >nul
echo [OK] Created .env from %SAMPLE_ENV%

REM Generate random keys
echo [INFO] Generating secure keys...
for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set APP_KEY=%%i
for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set API_KEY_PEPPER=%%i

REM Display keys for manual update
echo.
echo [IMPORTANT] Add these keys to your .env file:
echo.
echo   APP_KEY=%APP_KEY%
echo   API_KEY_PEPPER=%API_KEY_PEPPER%
echo.
echo [INFO] Opening .env file in Notepad for editing...
echo.
echo Please update:
echo   1. APP_KEY and API_KEY_PEPPER with the values above
echo   2. BROKER_API_KEY and BROKER_API_SECRET with your broker credentials
echo   3. Any other settings as needed
echo.
pause

REM Open .env in notepad
notepad "%PROJECT_DIR%\%ENV_FILE%"

echo.
echo [OK] Setup complete! Run 'docker-run.bat start' to launch OpenAlgo.
goto end

:start
echo [INFO] Starting OpenAlgo...
echo.

REM Check if .env exists
if not exist "%PROJECT_DIR%\%ENV_FILE%" (
    echo [ERROR] .env file not found!
    echo.
    echo Please run setup first:
    echo   docker-run.bat setup
    echo.
    goto end
)

REM Create db directory if not exists
if not exist "%PROJECT_DIR%\db" (
    echo [INFO] Creating db directory...
    mkdir "%PROJECT_DIR%\db"
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
    -v "%PROJECT_DIR%\db:/app/db" ^
    -v "%PROJECT_DIR%\.env:/app/.env:ro" ^
    --restart unless-stopped ^
    %IMAGE%

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start container!
    echo.
    echo Troubleshooting:
    echo   1. Check if ports 5000 and 8765 are available
    echo   2. Ensure Docker Desktop is running
    echo   3. Check .env file for errors
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
call :stop
echo.
call :start
goto end

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
echo   start    Start OpenAlgo container (default)
echo   stop     Stop and remove container
echo   restart  Restart container
echo   logs     View container logs (live)
echo   pull     Pull latest image from Docker Hub
echo   status   Show container status
echo   shell    Open bash shell in container
echo   setup    Initial setup (create .env from sample)
echo   help     Show this help
echo.
echo Prerequisites:
echo   1. Docker Desktop for Windows installed and running
echo      Download: https://www.docker.com/products/docker-desktop
echo.
echo   2. .env file configured
echo      Run 'docker-run.bat setup' for initial configuration
echo.
echo Examples:
echo   docker-run.bat setup     First time setup
echo   docker-run.bat start     Start OpenAlgo
echo   docker-run.bat logs      View live logs
echo   docker-run.bat restart   Restart after config changes
echo.
goto end

:end
endlocal
