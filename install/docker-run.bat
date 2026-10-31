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
REM   setup    - Create .env if there is none yet (an existing .env is kept)
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
REM Use the directory where the script is located
set OPENALGO_DIR=%~dp0
REM Remove trailing backslash
if "%OPENALGO_DIR:~-1%"=="\" set OPENALGO_DIR=%OPENALGO_DIR:~0,-1%
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
if /i "%CMD%"=="migrate" goto migrate
if /i "%CMD%"=="help" goto help
goto help

:setup
echo [INFO] Setting up OpenAlgo in %OPENALGO_DIR%...
echo.

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

REM Docker creates a folder named .env when the file is missing at container start
if exist "%OPENALGO_DIR%\%ENV_FILE%\" (
    echo [ERROR] .env is a folder, not a file. Docker created it because the .env file was missing.
    echo Delete the empty .env folder in !OPENALGO_DIR!, then run docker-run.bat again to create the file.
    set SETUP_FAILED=1
    goto setup_end
)

REM An existing .env is never replaced: its keys protect the saved data.
if exist "%OPENALGO_DIR%\%ENV_FILE%" (
    echo [OK] Kept the existing .env and its keys. It was not changed.
    goto setup_end
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
    echo [WARNING] Python not found. Keys will be generated using PowerShell.
    for /f %%i in ('powershell -Command "[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')"') do set APP_KEY=%%i
    for /f %%i in ('powershell -Command "[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')"') do set API_KEY_PEPPER=%%i
) else (
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set APP_KEY=%%i
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set API_KEY_PEPPER=%%i
)

REM Update .env file with generated keys
echo [INFO] Updating configuration with secure keys...
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE', '%APP_KEY%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE', '%API_KEY_PEPPER%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
REM No broker in .env: the trader adds broker keys in OpenAlgo after signing in
REM (Broker Configuration). VALID_BROKERS keeps the full list of brokers keys can be saved for.
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_KEY = ''YOUR_BROKER_API_KEY''', 'BROKER_API_KEY = ''''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_SECRET = ''YOUR_BROKER_API_SECRET''', 'BROKER_API_SECRET = ''''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_KEY_MARKET = ''YOUR_BROKER_MARKET_API_KEY''', 'BROKER_API_KEY_MARKET = ''''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_SECRET_MARKET = ''YOUR_BROKER_MARKET_API_SECRET''', 'BROKER_API_SECRET_MARKET = ''''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'REDIRECT_URL = ''http://127.0.0.1:5000/<broker>/callback''', 'REDIRECT_URL = ''''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
echo [OK] Secure keys generated and saved.
echo.
echo   ========================================
echo   Setup Complete!
echo   ========================================
echo.
echo   Data directory: %OPENALGO_DIR%
echo   Config file:    %OPENALGO_DIR%\%ENV_FILE%
echo   Database:       %OPENALGO_DIR%\db\
echo   Strategies:     %OPENALGO_DIR%\strategies\
echo   Logs:           %OPENALGO_DIR%\log\
echo.
echo   Next step: once OpenAlgo is running, sign in, open Broker Configuration and add
echo   your broker's keys. The page shows the redirect URL to register in
echo   your broker's developer console.
echo.
echo   Documentation: https://docs.openalgo.in
echo.
set /p OPEN_ENV="Open .env in Notepad for review? (y/n): "
if /i "%OPEN_ENV%"=="y" (
    start notepad "%OPENALGO_DIR%\%ENV_FILE%"
)
echo.
echo [OK] Setup complete! Run 'docker-run.bat start' to launch OpenAlgo.

:setup_end
exit /b %SETUP_FAILED%

:start
echo [INFO] Starting OpenAlgo...
echo.

REM Docker creates a folder named .env when the file is missing at container start
if exist "%OPENALGO_DIR%\%ENV_FILE%\" (
    echo [ERROR] .env is a folder, not a file. Docker created it because the .env file was missing.
    echo Delete the empty .env folder in !OPENALGO_DIR!, then run docker-run.bat again to create the file.
    goto end
)

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

REM Create db, strategies, log, keys, and tmp directories if not exist
if not exist "%OPENALGO_DIR%\db\" (
    echo [INFO] Creating database directory...
    md "%OPENALGO_DIR%\db" 2>nul
)
if not exist "%OPENALGO_DIR%\strategies\" (
    echo [INFO] Creating strategies directory...
    md "%OPENALGO_DIR%\strategies" 2>nul
    md "%OPENALGO_DIR%\strategies\scripts" 2>nul
    md "%OPENALGO_DIR%\strategies\examples" 2>nul
)
if not exist "%OPENALGO_DIR%\log\" (
    echo [INFO] Creating log directory...
    md "%OPENALGO_DIR%\log" 2>nul
    md "%OPENALGO_DIR%\log\strategies" 2>nul
)
if not exist "%OPENALGO_DIR%\keys\" (
    echo [INFO] Creating keys directory...
    md "%OPENALGO_DIR%\keys" 2>nul
)
if not exist "%OPENALGO_DIR%\tmp\" (
    echo [INFO] Creating temp directory...
    md "%OPENALGO_DIR%\tmp" 2>nul
)

REM Pull latest image
echo [INFO] Pulling latest image...
docker pull %IMAGE%
if errorlevel 1 (
    echo [WARNING] Could not pull latest image. Using cached version if available.
)

REM Stop and remove existing container if exists
docker stop -t 45 %CONTAINER% >nul 2>&1
docker rm %CONTAINER% >nul 2>&1

REM Calculate dynamic resource limits based on available RAM.
REM WMIC is absent from Windows 11 24H2 and later, so read both values from
REM PowerShell. It also returns megabytes directly, which keeps the byte count
REM out of set /a, where a machine with 4GB or more overflows 32-bit signed math.
REM Each value is checked for being all digits, because a variable left empty
REM here reaches set /a as text and evaluates to -1, which silently selects the
REM most restrictive tier on every machine.
set "TOTAL_RAM_MB="
for /f "delims=" %%i in ('powershell -NoProfile -Command "[int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)" 2^>nul') do set "TOTAL_RAM_MB=%%i"
if defined TOTAL_RAM_MB for /f "delims=0123456789" %%x in ("!TOTAL_RAM_MB!") do set "TOTAL_RAM_MB="

REM Get CPU cores, summed over every socket
set "CPU_CORES="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum" 2^>nul') do set "CPU_CORES=%%i"
if defined CPU_CORES for /f "delims=0123456789" %%x in ("!CPU_CORES!") do set "CPU_CORES="
if not defined CPU_CORES set "CPU_CORES=2"

if not defined TOTAL_RAM_MB (
    echo [NOTE] Could not read how much memory this machine has, so OpenAlgo is
    echo        starting with cautious limits: one compute thread and a 256MB
    echo        strategy memory cap. The container will run, just more slowly than
    echo        this machine allows. Windows PowerShell is what reads the memory
    echo        size, so making it available restores the full limits.
    set "TOTAL_RAM_MB=0"
)

REM shm_size: 25% of RAM (min 256MB, max 2GB)
set /a SHM_SIZE_MB=%TOTAL_RAM_MB% / 4
if %SHM_SIZE_MB% LSS 256 set SHM_SIZE_MB=256
if %SHM_SIZE_MB% GTR 2048 set SHM_SIZE_MB=2048

REM Thread limits based on RAM (prevents RLIMIT_NPROC exhaustion)
REM Less than 3GB: 1 thread | 3-6GB: 2 threads | 6GB+: min(4, cores)
REM See: https://github.com/marketcalls/openalgo/issues/822
if %TOTAL_RAM_MB% LSS 3000 (
    set THREAD_LIMIT=1
) else if %TOTAL_RAM_MB% LSS 6000 (
    set THREAD_LIMIT=2
) else (
    if %CPU_CORES% LSS 4 (
        set THREAD_LIMIT=%CPU_CORES%
    ) else (
        set THREAD_LIMIT=4
    )
)

REM Strategy memory limit based on RAM
REM Less than 3GB: 256MB | 3-6GB: 512MB | 6GB+: 1024MB
if %TOTAL_RAM_MB% LSS 3000 (
    set STRATEGY_MEM_LIMIT=256
) else if %TOTAL_RAM_MB% LSS 6000 (
    set STRATEGY_MEM_LIMIT=512
) else (
    set STRATEGY_MEM_LIMIT=1024
)

echo [INFO] System: %TOTAL_RAM_MB%MB RAM, %CPU_CORES% cores
echo [INFO] Config: shm=%SHM_SIZE_MB%MB, threads=%THREAD_LIMIT%, strategy_mem=%STRATEGY_MEM_LIMIT%MB

REM Run container
echo [INFO] Starting container...
docker run -d ^
    --name %CONTAINER% ^
    --stop-timeout 45 ^
    --shm-size=%SHM_SIZE_MB%m ^
    -p 5000:5000 ^
    -p 8765:8765 ^
    -e "OPENBLAS_NUM_THREADS=%THREAD_LIMIT%" ^
    -e "OMP_NUM_THREADS=%THREAD_LIMIT%" ^
    -e "MKL_NUM_THREADS=%THREAD_LIMIT%" ^
    -e "NUMEXPR_NUM_THREADS=%THREAD_LIMIT%" ^
    -e "NUMBA_NUM_THREADS=%THREAD_LIMIT%" ^
    -e "STRATEGY_MEMORY_LIMIT_MB=%STRATEGY_MEM_LIMIT%" ^
    -e "TZ=Asia/Kolkata" ^
    -v "%OPENALGO_DIR%\db:/app/db" ^
    -v "%OPENALGO_DIR%\strategies:/app/strategies" ^
    -v "%OPENALGO_DIR%\log:/app/log" ^
    -v "%OPENALGO_DIR%\keys:/app/keys" ^
    -v "%OPENALGO_DIR%\tmp:/app/tmp" ^
    -v "%OPENALGO_DIR%\.env:/app/.env" ^
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
docker stop -t 45 %CONTAINER% >nul 2>&1
docker rm %CONTAINER% >nul 2>&1
echo [OK] OpenAlgo stopped.
goto end

:restart
echo [INFO] Restarting OpenAlgo...
docker stop -t 45 %CONTAINER% >nul 2>&1
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

:migrate
echo [INFO] Running database migrations...
docker exec -it %CONTAINER% /app/.venv/bin/python /app/upgrade/migrate_all.py
if errorlevel 1 (
    echo [WARNING] Some migrations may have had issues. Check the output above.
    exit /b 1
) else (
    echo [OK] Migrations completed successfully.
)
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
echo   migrate  Run database migrations manually
echo   setup    Create .env if there is none yet (an existing .env is kept)
echo   help     Show this help
echo.
echo Quick Start:
echo   1. Install Docker Desktop: https://www.docker.com/products/docker-desktop
echo   2. Download this script (use PowerShell):
echo      curl.exe -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.bat
echo   3. Run: docker-run.bat
echo.
echo Data Location: %OPENALGO_DIR%
echo   - Config:     %OPENALGO_DIR%\.env
echo   - Database:   %OPENALGO_DIR%\db\
echo   - Strategies: %OPENALGO_DIR%\strategies\
echo   - Logs:       %OPENALGO_DIR%\log\
echo.
echo XTS Brokers (require market data credentials):
echo   fivepaisaxts, compositedge, ibulls, iifl, jainamxts, rmoney, wisdom
echo.
goto end

:end
endlocal
