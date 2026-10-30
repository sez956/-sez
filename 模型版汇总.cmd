@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0run_daily.py" --force
) else (
  python "%~dp0run_daily.py" --force
)
if errorlevel 1 pause
