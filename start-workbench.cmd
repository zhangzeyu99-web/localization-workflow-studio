@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-workbench.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Check .tmp\runtime logs.
  pause
)
