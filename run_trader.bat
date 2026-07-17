@echo off
cd /d G:\rigoalgo\openalgo
set VIRTUAL_ENV=
echo [%date% %time%] Sector ORB Trader starting... >> sector_trader_run.log
uv run sector_orb_trader.py >> sector_trader_run.log 2>&1
echo [%date% %time%] Trader exited. >> sector_trader_run.log
