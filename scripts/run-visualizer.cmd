@echo off
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set REPO_ROOT=%%~fI

if "%VISUALIZER_PORT%"=="" set VISUALIZER_PORT=3000
if not "%~1"=="" set VISUALIZER_PORT=%~1

set OPEN_ARG=
if /I "%VISUALIZER_OPEN%"=="true" set OPEN_ARG=--open

set RUN_ID_ARG=
if not "%VISUALIZER_RUN_ID%"=="" set RUN_ID_ARG=--run-id "%VISUALIZER_RUN_ID%"

echo Starting visualizer server
echo   results: %REPO_ROOT%\results
echo   static:  %REPO_ROOT%\tools\visualizer\static
echo   port:    %VISUALIZER_PORT%

python "%REPO_ROOT%\tools\visualizer\server.py" serve --results-dir "%REPO_ROOT%\results" --static-dir "%REPO_ROOT%\tools\visualizer\static" --port %VISUALIZER_PORT% %OPEN_ARG% %RUN_ID_ARG%

endlocal