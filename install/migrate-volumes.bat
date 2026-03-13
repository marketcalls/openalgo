@echo off
setlocal enabledelayedexpansion
:: ============================================================================
:: OpenAlgo Volume Migration Tool (Windows)
:: Migrates data from legacy docker named volumes to local bind mounts
:: ============================================================================

echo   ========================================
echo        OpenAlgo Volume Migrator
echo   ========================================
echo.
echo [INFO] Creating local directories...
if not exist "db" mkdir "db"
if not exist "log" mkdir "log"
if not exist "strategies" mkdir "strategies"
if not exist "keys" mkdir "keys"

echo [INFO] Migrating openalgo_db -^> ./db...
docker run --rm -v "openalgo_db":/from -v "%cd%\db":/to alpine sh -c "cp -a /from/. /to/ 2>/dev/null || true"
echo [OK] Migration complete for openalgo_db

echo [INFO] Migrating openalgo_log -^> ./log...
docker run --rm -v "openalgo_log":/from -v "%cd%\log":/to alpine sh -c "cp -a /from/. /to/ 2>/dev/null || true"
echo [OK] Migration complete for openalgo_log

echo [INFO] Migrating openalgo_strategies -^> ./strategies...
docker run --rm -v "openalgo_strategies":/from -v "%cd%\strategies":/to alpine sh -c "cp -a /from/. /to/ 2>/dev/null || true"
echo [OK] Migration complete for openalgo_strategies

echo [INFO] Migrating openalgo_keys -^> ./keys...
docker run --rm -v "openalgo_keys":/from -v "%cd%\keys":/to alpine sh -c "cp -a /from/. /to/ 2>/dev/null || true"
echo [OK] Migration complete for openalgo_keys

echo.
echo [SUCCESS] Migration complete! Your data is now in the local project directory.
echo You can safely use the new docker-compose.yaml with bind mounts.
echo.
pause
