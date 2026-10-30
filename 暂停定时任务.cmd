@echo off
powershell.exe -NoProfile -Command "Disable-ScheduledTask -TaskName 'EmbodiedAI-Daily-0900' | Out-Null"
pause
