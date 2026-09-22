@echo off
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" -Mode Stop
if errorlevel 1 pause
