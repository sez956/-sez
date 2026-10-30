$ErrorActionPreference = 'Stop'
$taskName = 'EmbodiedAI-Daily-0900'
$python = (Get-Command python.exe).Source
$pythonHidden = Join-Path (Split-Path $python) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonHidden) { $python = $pythonHidden }
$runner = Join-Path $PSScriptRoot 'run_daily.py'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $runner + '"') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '09:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Actions.Arguments -notlike ('*' + $runner + '*')) { throw '已有同名任务，且不是本工作流；请先检查，未覆盖。' }
$description = '具身智能中文科研日报：北京时间每天09:00开始检索，完成后归档并桌面通知；使用当前用户Codex登录。'
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description -Force | Out-Null
Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $PSScriptRoot '定时任务.xml') -Encoding utf8
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime,LastTaskResult
