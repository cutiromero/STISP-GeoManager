param([string]$StatusPath = (Join-Path $PSScriptRoot '../.runtime/compute-wsl-install.json'))
$ErrorActionPreference = 'Stop'
# Run from an elevated Windows PowerShell. Deliberately never reboot the host.
$result = @{ state = 'running'; restartNeeded = $false; error = '' }
try {
    foreach ($feature in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $current = Get-WindowsOptionalFeature -Online -FeatureName $feature
        if ($current.State -ne 'Enabled') {
            $installed = Enable-WindowsOptionalFeature -Online -FeatureName $feature -All -NoRestart
            $result.restartNeeded = $result.restartNeeded -or $installed.RestartNeeded
        }
    }
    $result.state = if ($result.restartNeeded) { 'restart-required' } else { 'features-ready' }
} catch {
    $result.state = 'failed'
    $result.error = $_.Exception.Message
} finally {
    $result | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8
}
