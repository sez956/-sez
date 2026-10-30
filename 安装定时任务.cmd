@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_schedule.ps1" -Engine free
pause
