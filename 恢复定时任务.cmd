@echo off
powershell.exe -NoProfile -Command "Enable-ScheduledTask -TaskName 'EmbodiedAI-Daily-0900' | Out-Null"
pause
