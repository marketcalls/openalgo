@echo off
REM OpenAlgo Docker Build and Deployment Script for Windows
REM This script builds and deploys OpenAlgo with numba/llvmlite support

setlocal enabledelayedexpansion

set IMAGE_NAME=openalgo
set IMAGE_TAG=latest
set CONTAINER_NAME=openalgo-web

echo.
echo ========================================
echo OpenAlgo Docker Build ^& Deploy
echo ========================================
echo.

REM Check if .env exists
echo [1/8] Checking environment configuration...
if not exist ".env" (
    echo ERROR: .env file not found!
    echo Please copy .sample.env to .env and configure your settings
    exit /b 1
)
echo OK: .env file found

REM Check for docker-compose
where docker-compose >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: docker-compose not found!
    echo Please install Docker Desktop for Windows
    exit /b 1
)

REM Stop existing container
echo.
echo [2/8] Cleaning up existing containers...
docker-compose down 2>nul
echo OK: Cleanup complete

REM Build image
echo.
echo [3/8] Building Docker image...
echo This may take 5-10 minutes...
docker-compose build --no-cache
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker build failed!
    exit /b 1
)
echo OK: Docker image built successfully

REM Verify dependencies
echo.
echo [4/8] Verifying dependencies...
docker run -d --name temp-verify %IMAGE_NAME%:%IMAGE_TAG% sleep 10 >nul 2>nul
docker exec temp-verify dpkg -l | findstr "libopenblas0" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo OK: libopenblas0 installed
) else (
    echo WARNING: libopenblas0 not found
)
docker exec temp-verify dpkg -l | findstr "libgomp1" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo OK: libgomp1 installed
) else (
    echo WARNING: libgomp1 not found
)
docker stop temp-verify >nul 2>nul
docker rm temp-verify >nul 2>nul

REM Start container
echo.
echo [5/8] Starting OpenAlgo container...
docker-compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to start container!
    exit /b 1
)
echo OK: Container started
timeout /t 5 /nobreak >nul

REM Health check
echo.
echo [6/8] Running health checks...
docker ps | findstr "%CONTAINER_NAME%" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo OK: Container is running
) else (
    echo ERROR: Container is not running!
    docker-compose logs --tail=50
    exit /b 1
)

REM Wait for application
echo Waiting for application to start (up to 30 seconds)...
set /a counter=0
:wait_loop
curl -s -f http://127.0.0.1:5000/auth/check-setup >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo OK: Application is responding
    goto :continue
)
set /a counter+=1
if !counter! GEQ 30 (
    echo WARNING: Application not responding after 30 seconds
    echo This is normal for first-time startup
    goto :continue
)
timeout /t 1 /nobreak >nul
goto :wait_loop

:continue
REM Test Python dependencies
echo.
echo [7/8] Testing Python dependencies...
docker-compose exec -T openalgo python -c "import numba; import llvmlite; import scipy; print('SUCCESS')" 2>nul | findstr "SUCCESS" >nul
if %ERRORLEVEL% EQU 0 (
    echo OK: numba, llvmlite, scipy imports successful
) else (
    echo WARNING: Failed to import dependencies - check logs
)

docker-compose exec -T openalgo python -c "from numba import jit; import numpy as np; jit(nopython=True)(lambda x: x*2)(np.array([1,2,3])); print('SUCCESS')" 2>nul | findstr "SUCCESS" >nul
if %ERRORLEVEL% EQU 0 (
    echo OK: Numba JIT compilation works
) else (
    echo WARNING: Numba JIT compilation test failed
)

docker-compose exec -T openalgo python -c "from scipy import stats; print('SUCCESS' if abs(stats.norm.cdf(0) - 0.5) ^< 0.001 else 'FAILED')" 2>nul | findstr "SUCCESS" >nul
if %ERRORLEVEL% EQU 0 (
    echo OK: SciPy operations work
) else (
    echo WARNING: SciPy operations test failed
)

REM Display access information
echo.
echo [8/8] Deployment Complete!
echo.
echo ========================================
echo        OpenAlgo is now running!
echo ========================================
echo.
echo Access URLs:
echo   Web UI:       http://127.0.0.1:5000
echo   WebSocket:    ws://127.0.0.1:8765
echo   API Docs:     http://127.0.0.1:5000/api/docs
echo   React UI:     http://127.0.0.1:5000/react
echo.
echo Useful Commands:
echo   View logs:        docker-compose logs -f
echo   Stop container:   docker-compose down
echo   Restart:          docker-compose restart
echo   Shell access:     docker-compose exec openalgo bash
echo.

REM Detect configured broker
findstr /C:"fyers" .env >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Configured Broker: Fyers
    echo Callback URL: http://127.0.0.1:5000/fyers/callback
)

echo.
echo Next Steps:
echo   1. Open http://127.0.0.1:5000 in your browser
echo   2. Complete the initial setup wizard
echo   3. Configure your broker credentials
echo   4. Start trading with Python strategies!
echo.
echo Note: First-time startup may take 30-60 seconds
echo.

pause
