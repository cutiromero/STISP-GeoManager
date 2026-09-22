# Dot-source this file to select the configured project Python in the current shell.
$localEnvironmentFile = Join-Path $PSScriptRoot '.runtime/local-environment.json'
if (-not (Test-Path $localEnvironmentFile)) { throw 'Missing .runtime/local-environment.json; see docs/local-conda-setup.md.' }
$localEnvironment = Get-Content $localEnvironmentFile -Raw | ConvertFrom-Json
$prefix = $localEnvironment.pythonPrefix
if (-not $prefix -or -not (Test-Path (Join-Path $prefix 'python.exe'))) { throw 'The configured Conda environment has no python.exe.' }
$prefix = (Resolve-Path -LiteralPath $prefix).Path
$python = Join-Path $prefix 'python.exe'
# Rasterio registers every GDAL directory on PATH. Remove foreign GDAL directories
# from this process only, otherwise base/uboo DLLs can override the selected runtime.
$remainingPath = @($env:PATH -split ';' | Where-Object {
    $entry = $_.Trim('"')
    $entry -and -not (Test-Path (Join-Path $entry 'gdal.dll')) -and -not (Test-Path (Join-Path $entry 'libgdal.dll'))
})
$env:PATH = (@($prefix, "$prefix\Scripts", "$prefix\Library\bin") + $remainingPath) -join ';'
$env:CONDA_PREFIX = $prefix
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
$env:GDAL_DATA = Join-Path $prefix 'Library/share/gdal'
$env:PROJ_DATA = Join-Path $prefix 'Library/share/proj'
$env:PROJ_LIB = $env:PROJ_DATA
$env:GDAL_DRIVER_PATH = Join-Path $prefix 'Library/lib/gdalplugins'
