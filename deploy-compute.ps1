param([switch]$WithRuntime, [string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$pixi = Join-Path $project '.runtime/tools/pixi.exe'
$env:PYTHONUTF8 = '1'
$env:WSL_UTF8 = '1'

function Invoke-Backend([string[]]$Arguments) {
    Push-Location (Join-Path $project 'backend')
    try {
        & $pixi run --frozen .pixi/envs/default/python.exe manage.py @Arguments --config ../config/app.test.toml
        if ($LASTEXITCODE -ne 0) { throw 'Backend deployment command failed.' }
    } finally { Pop-Location }
}

if ($WithRuntime) {
    # This script intentionally does not restart Windows or enable OS features.
    & wsl.exe --version
    if ($LASTEXITCODE -ne 0) {
        $bootstrap = Join-Path $project 'deploy/bootstrap-compute-wsl.ps1'
        Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File', ('"' + $bootstrap + '"'))
        $bootstrapState = Get-Content -LiteralPath (Join-Path $project '.runtime/compute-wsl-bootstrap.json') -Raw | ConvertFrom-Json
        if ($bootstrapState.state -ne 'installed') { throw $bootstrapState.error }
    }
    $distributions = (& wsl.exe --list --quiet 2>$null) -replace "`0", ''
    if ($LASTEXITCODE -ne 0) {
        # An installed WSL with no distributions returns a nonzero exit code.
        & wsl.exe --status
        if ($LASTEXITCODE -ne 0) { throw 'WSL is unavailable. Finish component setup and any requested Windows restart first.' }
        $distributions = @()
    }
    if (-not ($distributions | Where-Object { $_.Trim() -eq $Distribution })) {
        & wsl.exe --install --distribution $Distribution --web-download --no-launch
        if ($LASTEXITCODE -ne 0) { throw 'WSL distribution installation failed.' }
    }
    $linuxProject = '/mnt/' + $project.Substring(0,1).ToLower() + $project.Substring(2).Replace('\','/')
    & wsl.exe --distribution $Distribution --user root -- bash ($linuxProject + '/deploy/compute/install-linux.sh')
    if ($LASTEXITCODE -ne 0) { throw 'Docker setup inside WSL failed.' }
    & wsl.exe --distribution $Distribution --user root -- docker build --tag geomanager-compute:1 ($linuxProject + '/deploy/compute')
    if ($LASTEXITCODE -ne 0) { throw 'Compute runtime image build failed.' }
    Invoke-Backend -Arguments @('configure_compute_runtime','--wsl',$Distribution)
}

& (Join-Path $project 'start-local.ps1') -Mode Stop
Invoke-Backend -Arguments @('migrate','--noinput')
Invoke-Backend -Arguments @('seed_compute')
& (Join-Path $project 'start-local.ps1') -NoBrowser
if ($LASTEXITCODE -ne 0) { throw 'Local services failed to start.' }
Write-Host 'Application: http://127.0.0.1:5173/compute'
Write-Host 'Algorithms: http://127.0.0.1:5173/admin/compute'
Write-Host 'Publish each algorithm only after a successful isolated trial and result review.'
