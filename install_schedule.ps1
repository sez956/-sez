param([ValidateSet('free','model')][string]$Engine = 'free')
$ErrorActionPreference = 'Stop'
$taskName = 'EmbodiedAI-Daily-0900'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & (Join-Path $PSScriptRoot 'bootstrap.ps1')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) { throw '请先运行“安装环境.cmd”。' }
}
$pythonHidden = Join-Path (Split-Path $python) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonHidden) { $python = $pythonHidden }
$runnerName = if ($Engine -eq 'free') { 'free_digest.py' } else { 'run_daily.py' }
$runner = Join-Path $PSScriptRoot $runnerName
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $runner + '"') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '09:00'
$trigger.StartBoundary = ([DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd') + 'T09:00:00+08:00')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    $existingArgs = [string]$existing.Actions.Arguments
    $allowed = @((Join-Path $PSScriptRoot 'run_daily.py'), (Join-Path $PSScriptRoot 'free_digest.py'))
    if (-not ($allowed | Where-Object { $existingArgs.Contains($_) })) { throw '已有同名任务，且不是本工作流；请先检查，未覆盖。' }
}
$modeText = if ($Engine -eq 'free') { '免模型规则版，不调用GPT或Codex' } else { '模型版，使用当前用户Codex登录和额度' }
$description = '具身智能日报：北京时间每天09:00开始检索，完成后归档并桌面通知；' + $modeText
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description -Force | Out-Null
Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $PSScriptRoot '定时任务.xml') -Encoding utf8
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime,LastTaskResult
