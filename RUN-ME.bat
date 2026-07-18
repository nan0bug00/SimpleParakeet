@echo off
setlocal
cd /d "%~dp0"

where pwsh >nul 2>&1
if errorlevel 1 (
  echo PowerShell 7+ ^(pwsh.exe^) is required. Install it from https://aka.ms/powershell
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
if errorlevel 1 pause
