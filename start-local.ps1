param([ValidateSet('Start','Backend','Frontend','Compute','Agent','Workflow','Mock','Stop')][string]$Mode = 'Start', [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$env:PYTHONUTF8 = '1'
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$env:PATH = "$runtime\node\bin;$runtime\bin\fallback;$env:PATH"
$pixi = Join-Path $project '.runtime\tools\pixi.exe'
$localEnvironmentFile = Join-Path $project '.runtime\local-environment.json'
$localEnvironment = if (Test-Path $localEnvironmentFile) { Get-Content $localEnvironmentFile -Raw | ConvertFrom-Json } else { $null }
$python = $null
if ($localEnvironment.pythonPrefix) {
    . (Join-Path $project 'activate-local.ps1')
}
function Invoke-LocalPython {
    if ($python) { & $python @args }
    else { & $pixi run --locked .pixi/envs/default/python.exe @args }
}
$logDir = Join-Path $project 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
if ($Mode -ne 'Stop') {
    if ($python -and -not (Test-Path $python)) { throw "Configured Python is missing: $python" }
    if (-not $python -and -not (Test-Path $pixi)) { throw 'Configure .runtime/local-environment.json or install the project Pixi runtime first.' }
    if (-not (Test-Path (Join-Path $project 'config/app.test.toml'))) { throw 'Create the local config/app.test.toml before starting services.' }
}
if ($Mode -eq 'Backend') {
    Set-Location (Join-Path $project 'backend')
    Invoke-LocalPython manage.py runserver 127.0.0.1:8000 --noreload --config ../config/app.test.toml
    exit $LASTEXITCODE
}
if ($Mode -eq 'Frontend') {
    Set-Location (Join-Path $project 'frontend')
    & pnpm.cmd run dev --strictPort
    exit $LASTEXITCODE
}
if ($Mode -eq 'Compute') {
    Set-Location (Join-Path $project 'backend')
    while ($true) {
        Invoke-LocalPython manage.py compute_worker --config ../config/app.test.toml
        if ($LASTEXITCODE -eq 0) { exit 0 }
        Start-Sleep -Seconds 5
    }
}
if ($Mode -eq 'Agent') {
    Set-Location (Join-Path $project 'backend')
    while ($true) {
        Invoke-LocalPython manage.py agent_worker --config ../config/app.test.toml
        if ($LASTEXITCODE -eq 0) { exit 0 }
        Start-Sleep -Seconds 5
    }
}
if ($Mode -eq 'Workflow') {
    Set-Location (Join-Path $project 'backend')
    while ($true) {
        Invoke-LocalPython manage.py workflow_worker --config ../config/app.test.toml
        if ($LASTEXITCODE -eq 0) { exit 0 }
        Start-Sleep -Seconds 5
    }
}
if ($Mode -eq 'Mock') {
    Set-Location (Join-Path $project 'backend')
    Invoke-LocalPython manage.py mock_agent_model --port 19100 --config ../config/app.test.toml
    exit $LASTEXITCODE
}
$pidFile = Join-Path $project '.runtime\local-services.json'
if ($Mode -eq 'Stop') {
    if (Test-Path $pidFile) {
        foreach ($entry in (Get-Content $pidFile -Raw | ConvertFrom-Json)) {
            $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
            if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq ([datetimeoffset]$entry.StartTime).UtcDateTime.Ticks) {
                & taskkill.exe /PID $entry.Id /T /F | Out-Null
            }
        }
        Remove-Item -LiteralPath $pidFile
    }
    Write-Host 'Local platform stopped.'
    exit 0
}
$shell = (Get-Process -Id $PID).Path
$services = @()
if (Test-Path $pidFile) { $services = @(Get-Content $pidFile -Raw | ConvertFrom-Json) }
$definitions = @(@{Name='Backend';Port=8000}, @{Name='Frontend';Port=5173}, @{Name='Compute';Port=0}, @{Name='Agent';Port=0}, @{Name='Workflow';Port=0})
if ($localEnvironment.startMock) { $definitions += @{Name='Mock';Port=19100} }
foreach ($service in $definitions) {
    if ($service.Port -and (netstat -ano -p tcp | Select-String (':'+$service.Port+'\s+\S+\s+LISTENING\s+'))) { continue }
    if ($service.Name -in @('Compute', 'Agent', 'Workflow')) {
        $live = @($services | Where-Object {
            if ($_.Name -ne $service.Name) { return $false }
            $candidate = Get-Process -Id $_.Id -ErrorAction SilentlyContinue
            return $candidate -and $candidate.StartTime.ToUniversalTime().Ticks -eq ([datetimeoffset]$_.StartTime).UtcDateTime.Ticks
        })
        if ($live.Count) { continue }
    }
    $process = Start-Process -FilePath $shell -WindowStyle Hidden -WorkingDirectory $project -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File', ('"' + $PSCommandPath + '"'), '-Mode', $service.Name) -RedirectStandardOutput (Join-Path $logDir "local-$($service.Name).out.log") -RedirectStandardError (Join-Path $logDir "local-$($service.Name).err.log") -PassThru
    $services += @{Id=$process.Id; Name=$service.Name; StartTime=$process.StartTime.ToUniversalTime().ToString('o')}
}
ConvertTo-Json -InputObject @($services) | Set-Content $pidFile -Encoding utf8
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:5173/api/health/' -TimeoutSec 3
        $page = Invoke-WebRequest 'http://127.0.0.1:5173/' -TimeoutSec 3
        if ($page.StatusCode -eq 200 -and $health) { $ready = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw "Startup failed. See $logDir\local-*.log" }
Write-Host 'Platform ready: http://127.0.0.1:5173/'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173/' }
