param([string]$Output = 'windows-browser-current/edge-runtime.json')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $env:CI) { throw 'Browser updates are restricted to disposable CI runners.' }
$destination = (New-Item -ItemType Directory -Force (Split-Path $Output -Parent)).FullName
$browser = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
$before = if (Test-Path $browser) { (Get-Item $browser).VersionInfo.ProductVersion } else { '0.0.0.0' }
# Microsoft's published enterprise update feed supplies the stable version,
# HTTPS installer and expected SHA256. No unofficial binary mirror is used.
$products = Invoke-RestMethod 'https://edgeupdates.microsoft.com/api/products?view=enterprise' -TimeoutSec 60
$stable = $products | Where-Object Product -eq 'Stable'
$release = $stable.Releases | Where-Object { $_.Platform -eq 'Windows' -and $_.Architecture -eq 'x64' } | Sort-Object { [version]$_.ProductVersion } -Descending | Select-Object -First 1
if (-not $release) { throw 'Microsoft did not publish an x64 Windows stable release.' }
$artifact = $release.Artifacts | Where-Object ArtifactName -eq 'msi' | Select-Object -First 1
if (-not $artifact -or $artifact.HashAlgorithm -ne 'SHA256') { throw 'A SHA256-verified official Edge MSI is required.' }
$report = [ordered]@{ source = 'https://edgeupdates.microsoft.com/api/products?view=enterprise'; channel = 'Stable'; before = $before; requested = $release.ProductVersion }
if ([version]$before -lt [version]$release.ProductVersion) {
    $uri = [uri]$artifact.Location
    if ($uri.Scheme -ne 'https' -or -not $uri.DnsSafeHost.EndsWith('.microsoft.com')) { throw 'Unexpected official Edge installer destination.' }
    $installer = Join-Path $env:RUNNER_TEMP 'Audial-EdgeStable-x64.msi'
    Invoke-WebRequest $uri -OutFile $installer -TimeoutSec 180
    if ((Get-FileHash $installer -Algorithm SHA256).Hash -ne $artifact.Hash) { throw 'Edge installer SHA256 mismatch.' }
    $signature = Get-AuthenticodeSignature $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Edge installer is not validly signed by Microsoft.' }
    $process = Start-Process msiexec.exe -ArgumentList @('/i', "`"$installer`"", '/qn', '/norestart', '/L*v', "`"$destination\edge-install.log`"") -PassThru -Wait
    if ($process.ExitCode -notin @(0, 3010)) { throw "Edge stable update failed: $($process.ExitCode)" }
    $report.installer_sha256 = $artifact.Hash.ToLowerInvariant()
}
$after = (Get-Item $browser).VersionInfo.ProductVersion
if ([version]$after -lt [version]$release.ProductVersion) { throw 'The actual installed Edge did not update to current stable.' }
$report.after = $after
$report | ConvertTo-Json | Set-Content $Output -Encoding utf8
$message = $report | ConvertTo-Json -Compress
Write-Output ('::notice title=Microsoft Edge Stable runtime::' + $message)
