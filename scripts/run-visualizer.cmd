@echo off
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set REPO_ROOT=%%~fI

if "%VISUALIZER_PORT%"=="" set VISUALIZER_PORT=3000
if not "%~1"=="" set VISUALIZER_PORT=%~1
if "%VISUALIZER_RESULTS_DIR%"=="" set VISUALIZER_RESULTS_DIR=%REPO_ROOT%\results

set HEADLESS_ARG=
if /I "%VISUALIZER_OPEN%"=="false" set HEADLESS_ARG=--server.headless true

set RUN_ID_ARG=
if not "%VISUALIZER_RUN_ID%"=="" set RUN_ID_ARG=--run-id "%VISUALIZER_RUN_ID%"

echo Starting Streamlit visualizer
echo   results: %VISUALIZER_RESULTS_DIR%
echo   app:     %REPO_ROOT%\tools\visualizer\streamlit_app.py
echo   port:    %VISUALIZER_PORT%

python -c "import streamlit" >NUL 2>&1
if errorlevel 1 (
	echo Error: Streamlit is not installed in this Python environment.
	echo Install it with: python -m pip install streamlit
	exit /b 3
)

python -m streamlit run "%REPO_ROOT%\tools\visualizer\streamlit_app.py" --server.port %VISUALIZER_PORT% --server.address 127.0.0.1 %HEADLESS_ARG% -- --results-dir "%VISUALIZER_RESULTS_DIR%" %RUN_ID_ARG%

endlocal