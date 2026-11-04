@echo off
rem Double-clicked by the client. Published in the release zip as "Install <product>.cmd".
rem Runs install-desktop.ps1 past PowerShell's script policy: a .ps1 double-clicked opens in Notepad.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-desktop.ps1" %*
if errorlevel 1 (
  echo.
  echo The installation did not finish. Read the message above, then press any key to close.
  pause >nul
)
