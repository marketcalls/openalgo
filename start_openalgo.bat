@echo off
cd /d G:\rigoalgo\openalgo
set VIRTUAL_ENV=
echo [%date% %time%] Starting OpenAlgo server... >> openalgo_server.log
start "OpenAlgo Server" uv run app.py
