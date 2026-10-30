@echo off
python "%~dp0run_daily.py" --force
if errorlevel 1 pause
