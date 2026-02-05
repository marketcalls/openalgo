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
REM Use the directory where the script is located
set OPENALGO_DIR=%~dp0
REM Remove trailing backslash
if "%OPENALGO_DIR:~-1%"=="\" set OPENALGO_DIR=%OPENALGO_DIR:~0,-1%
set SETUP_FAILED=0

REM XTS Brokers that require market data credentials
set XTS_BROKERS=fivepaisaxts,compositedge,ibulls,iifl,jainamxts,wisdom

REM Valid brokers list
set VALID_BROKERS=fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha

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
    echo [WARNING] Python not found. Keys will be generated using PowerShell.
    for /f %%i in ('powershell -Command "[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')"') do set APP_KEY=%%i
    for /f %%i in ('powershell -Command "[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')"') do set API_KEY_PEPPER=%%i
) else (
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set APP_KEY=%%i
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set API_KEY_PEPPER=%%i
)

REM Update .env file with generated keys
echo [INFO] Updating configuration with secure keys...
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace '3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84', '%APP_KEY%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772', '%API_KEY_PEPPER%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
echo [OK] Secure keys generated and saved.

REM Get broker configuration
echo.
echo   ========================================
echo   Broker Configuration
echo   ========================================
echo.
echo   Valid brokers:
echo   fivepaisa, fivepaisaxts, aliceblue, angel, compositedge,
echo   definedge, dhan, dhan_sandbox, firstock, flattrade, fyers,
echo   groww, ibulls, iifl, indmoney, jainamxts, kotak, motilal,
echo   mstock, paytm, pocketful, samco, shoonya, tradejini,
echo   upstox, wisdom, zebu, zerodha
echo.

:get_broker
set /p BROKER_NAME="Enter broker name (e.g., zerodha, fyers, angel): "

REM Validate broker name
echo,%VALID_BROKERS%, | findstr /i /c:",%BROKER_NAME%," >nul
if errorlevel 1 (
    echo [ERROR] Invalid broker: %BROKER_NAME%
    echo Please enter a valid broker name from the list above.
    goto get_broker
)

echo [OK] Broker: %BROKER_NAME%

REM Get broker API credentials
echo.
set /p BROKER_API_KEY="Enter your %BROKER_NAME% API Key: "
set /p BROKER_API_SECRET="Enter your %BROKER_NAME% API Secret: "

if "%BROKER_API_KEY%"=="" (
    echo [ERROR] API Key is required!
    set SETUP_FAILED=1
    goto setup_end
)

if "%BROKER_API_SECRET%"=="" (
    echo [ERROR] API Secret is required!
    set SETUP_FAILED=1
    goto setup_end
)

REM Check if XTS broker (requires market data credentials)
set IS_XTS=0
echo,%XTS_BROKERS%, | findstr /i /c:",%BROKER_NAME%," >nul
if not errorlevel 1 (
    set IS_XTS=1
    echo.
    echo [INFO] %BROKER_NAME% is an XTS-based broker.
    echo        Additional market data credentials are required.
    echo.
    set /p BROKER_API_KEY_MARKET="Enter Market Data API Key: "
    set /p BROKER_API_SECRET_MARKET="Enter Market Data API Secret: "

    if "!BROKER_API_KEY_MARKET!"=="" (
        echo [ERROR] Market Data API Key is required for XTS brokers!
        set SETUP_FAILED=1
        goto setup_end
    )
    if "!BROKER_API_SECRET_MARKET!"=="" (
        echo [ERROR] Market Data API Secret is required for XTS brokers!
        set SETUP_FAILED=1
        goto setup_end
    )
)

REM Update .env with broker configuration
echo.
echo [INFO] Updating broker configuration...

REM Update broker credentials
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_KEY = ''YOUR_BROKER_API_KEY''', 'BROKER_API_KEY = ''%BROKER_API_KEY%''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_SECRET = ''YOUR_BROKER_API_SECRET''', 'BROKER_API_SECRET = ''%BROKER_API_SECRET%''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"

REM Update redirect URL with broker name (replace <broker> placeholder)
powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace '<broker>', '%BROKER_NAME%' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"

REM Update XTS market data credentials if applicable
if "%IS_XTS%"=="1" (
    powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_KEY_MARKET = ''YOUR_BROKER_MARKET_API_KEY''', 'BROKER_API_KEY_MARKET = ''!BROKER_API_KEY_MARKET!''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
    powershell -Command "(Get-Content '%OPENALGO_DIR%\%ENV_FILE%') -replace 'BROKER_API_SECRET_MARKET = ''YOUR_BROKER_MARKET_API_SECRET''', 'BROKER_API_SECRET_MARKET = ''!BROKER_API_SECRET_MARKET!''' | Set-Content '%OPENALGO_DIR%\%ENV_FILE%'"
)

echo [OK] Broker configuration saved.
echo.
echo   ========================================
echo   Setup Complete!
echo   ========================================
echo.
echo   Broker:         %BROKER_NAME%
if "%IS_XTS%"=="1" (
    echo   Type:           XTS API [with market data]
)
echo   Data directory: %OPENALGO_DIR%
echo   Config file:    %OPENALGO_DIR%\%ENV_FILE%
echo   Database:       %OPENALGO_DIR%\db\
echo   Strategies:     %OPENALGO_DIR%\strategies\
echo   Logs:           %OPENALGO_DIR%\log\
echo.
echo   Redirect URL for broker portal:
echo   http://127.0.0.1:5000/%BROKER_NAME%/callback
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
docker stop %CONTAINER% >nul 2>&1
docker rm %CONTAINER% >nul 2>&1

REM Calculate dynamic resource limits based on available RAM
for /f "tokens=2 delims==" %%i in ('wmic computersystem get TotalPhysicalMemory /value ^| findstr TotalPhysicalMemory') do set TOTAL_RAM_BYTES=%%i
set /a TOTAL_RAM_MB=%TOTAL_RAM_BYTES:~0,-6%

REM Get CPU cores
for /f "tokens=2 delims==" %%i in ('wmic cpu get NumberOfCores /value ^| findstr NumberOfCores') do set CPU_CORES=%%i
if "%CPU_CORES%"=="" set CPU_CORES=2

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

:migrate
echo [INFO] Running database migrations...
docker exec -it %CONTAINER% /app/.venv/bin/python /app/upgrade/migrate_all.py
if errorlevel 1 (
    echo [WARNING] Some migrations may have had issues. Check the output above.
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
echo   - Config:     %OPENALGO_DIR%\.env
echo   - Database:   %OPENALGO_DIR%\db\
echo   - Strategies: %OPENALGO_DIR%\strategies\
echo   - Logs:       %OPENALGO_DIR%\log\
echo.
echo XTS Brokers (require market data credentials):
echo   fivepaisaxts, compositedge, ibulls, iifl, jainamxts, wisdom
echo.
goto end

:end
endlocal
