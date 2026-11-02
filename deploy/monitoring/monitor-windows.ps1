param(
    [ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status',
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$Python = 'C:\Users\uboo\miniconda3\envs\uboo\python.exe'
)
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$scriptPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'monitor.py')).Path
$privateDir = Split-Path -Parent $configPath
$pidPath = Join-Path $privateDir 'monitor-process.json'

function Get-MonitorProcess {
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $record = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json
    if ($record.script -ne $scriptPath -or $record.config -ne $configPath) {
        throw '进程记录不属于此监测配置，未停止或替换任何进程。'
    }
    $process = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $details = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$record.pid)
    $sameStart = $process.StartTime.ToUniversalTime().Ticks -eq [long]$record.startTicks
    $sameCommand = $details.CommandLine -and
        $details.CommandLine.Contains($scriptPath) -and
        $details.CommandLine.Contains($configPath)
    if (-not ($sameStart -and $sameCommand)) {
        throw '进程记录与当前进程身份不同，未停止或替换任何进程。'
    }
    return $process
}

$current = Get-MonitorProcess
if ($Action -eq 'Status') {
    if ($current) { Write-Output ('监测进程运行中，PID ' + $current.Id) }
    else { Write-Output '监测进程未运行。' }
    exit 0
}
if ($Action -eq 'Stop') {
    if ($current) {
        Stop-Process -Id $current.Id -ErrorAction Stop
        Write-Output '已停止身份匹配的监测进程。'
    } else { Write-Output '监测进程未运行。' }
    if (Test-Path -LiteralPath $pidPath) { Remove-Item -LiteralPath $pidPath }
    exit 0
}
if ($current) {
    Write-Output ('监测已运行，未重复启动。PID ' + $current.Id)
    exit 0
}
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$arguments = @('-X', 'utf8', ('"' + $scriptPath + '"'), '--config', ('"' + $configPath + '"'))
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $privateDir 'monitor.log') `
    -RedirectStandardError (Join-Path $privateDir 'monitor-error.log')
Start-Sleep -Seconds 2
if ($process.HasExited) {
    throw '监测未能启动，请查看私有目录中的 monitor-error.log；通知尚未启用。'
}
$record = @{ pid = $process.Id; startTicks = $process.StartTime.ToUniversalTime().Ticks; script = $scriptPath; config = $configPath }
$record | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding utf8
Write-Output ('监测已隐藏启动，PID ' + $process.Id + '。电脑关机或休眠期间无法监测。')
