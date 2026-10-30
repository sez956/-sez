param(
    [ValidateSet('success','failed')][string]$Result = 'success',
    [string]$ReportPath = '',
    [string]$StatusPath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $ReportPath) { $ReportPath = Join-Path $PSScriptRoot '最新日报.html' }
if (-not $StatusPath) { $StatusPath = Join-Path $PSScriptRoot '运行状态.json' }
$message = if ($Result -eq 'success') { '今日成果汇总已生成，点击打开日报。' } else { '本次检索未完成，点击查看运行状态；定时任务会自动重试。' }
$openPath = if ($Result -eq 'success') { $ReportPath } else { $StatusPath }
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $launch = [System.Security.SecurityElement]::Escape(([System.Uri]::new($openPath)).AbsoluteUri)
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast activationType='protocol' launch='$launch'><visual><binding template='ToastGeneric'><text>具身智能成果日报</text><text>$message</text></binding></visual></toast>")
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.Windows.PowerShell').Show($toast)
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = New-Object System.Windows.Forms.NotifyIcon
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Visible = $true
    $icon.BalloonTipTitle = '具身智能成果日报'
    $icon.BalloonTipText = $message + ' 文件位于：' + $PSScriptRoot
    $icon.add_BalloonTipClicked({ Start-Process -FilePath $openPath })
    $icon.ShowBalloonTip(10000)
    $end = [DateTime]::Now.AddSeconds(12)
    while ([DateTime]::Now -lt $end) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 100 }
    $icon.Dispose()
}
