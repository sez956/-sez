@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0free_digest.py" --force
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
  if errorlevel 1 goto failed
  "%~dp0.venv\Scripts\python.exe" "%~dp0free_digest.py" --force
)
if errorlevel 1 pause
exit /b
:failed
pause
