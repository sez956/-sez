param([switch]$NetworkCheck)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = $null
$candidates = @()
$candidates += @(Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
$candidates += @(Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Programs\Python" -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
foreach ($candidate in $candidates) {
    if ($candidate -like '*\Microsoft\WindowsApps\python.exe') { continue }
    $candidateVersion = & $candidate -c 'import sys; print(int(sys.version_info >= (3, 10)))' 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidateVersion -eq '1') { $python = $candidate; break }
}
if (-not $python) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $discovered = & $launcher.Source -3 -c 'import sys; print(sys.executable if sys.version_info >= (3, 10) else "")' 2>$null
        if ($LASTEXITCODE -eq 0 -and $discovered -and (Test-Path -LiteralPath $discovered)) { $python = $discovered }
    }
}
if (-not $python) {
    Write-Host '未找到 Python 3.10+。请从 https://www.python.org/downloads/ 安装 Python，完成后重新双击“安装环境.cmd”。'
    Write-Host '免额度版只需要 Python，不需要安装 Codex 或配置 API Key。'
    exit 1
}
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python -m venv --without-pip (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建独立运行环境失败，请检查 Python 安装和目录权限。' }
}
& $venvPython -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
if ($LASTEXITCODE -ne 0) { throw '现有 .venv 不可用；请删除从其他设备复制的 .venv 后重试。' }
$checkArgs = @((Join-Path $PSScriptRoot 'check_environment.py'))
if ($NetworkCheck) { $checkArgs += '--network' }
& $venvPython @checkArgs
if ($LASTEXITCODE -ne 0) { throw '环境检查未通过，请查看 ENVIRONMENT.md。' }
Write-Host '环境已准备好。双击“立即汇总.cmd”运行免额度版；双击“安装定时任务.cmd”设置每天运行。'
