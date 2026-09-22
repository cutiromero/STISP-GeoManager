param([string]$StatusPath = (Join-Path $PSScriptRoot '../.runtime/compute-wsl-bootstrap.json'))
$ErrorActionPreference = 'Stop'
$result = @{ state = 'running'; features = @(); exitCode = $null; error = '' }
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StatusPath -Encoding utf8
try {
    foreach ($feature in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $current = Get-WindowsOptionalFeature -Online -FeatureName $feature
        $result.features += @{ name = $feature; state = $current.State.ToString() }
        if ($current.State -ne 'Enabled') { throw "$feature is not enabled after restart." }
    }
    $installer = Start-Process -FilePath "$env:SystemRoot\System32\wsl.exe" -ArgumentList @('--install', '--no-distribution') -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput ($StatusPath + '.stdout.log') -RedirectStandardError ($StatusPath + '.stderr.log')
    $result.exitCode = $installer.ExitCode
    if ($installer.ExitCode -ne 0) { throw 'WSL application installation failed; inspect bootstrap logs.' }
    $result.state = 'installed'
} catch {
    $result.state = 'failed'
    $result.error = $_.Exception.Message
} finally {
    $result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StatusPath -Encoding utf8
}
