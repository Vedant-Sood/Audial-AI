param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [string]$Output = 'windows-kandha-acceptance'
)
# Installs Kandha-Setup-<version>.exe on the disposable CI account (after verify_windows.ps1 has
# uninstalled Audial-AI), checks Kandha.exe and the Start-menu entry, loads the Kandha page in the
# packaged QtWebEngine with the console worker (--kandha-check), then uninstalls with data purge.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $env:CI) { throw 'Run destructive installer acceptance only in a disposable CI Windows account (CI=true).' }
$Installer = (Resolve-Path $Installer).Path
$Output = (New-Item -ItemType Directory -Force $Output).FullName
$target = Join-Path $env:LOCALAPPDATA 'Programs\AudialAI Kandha Acceptance'
$state = Join-Path $env:LOCALAPPDATA 'AccessibilityAI'
if ((Test-Path $target) -or (Test-Path $state)) { throw 'Kandha acceptance requires an empty disposable account.' }
Remove-Item Env:ACCESSIBILITY_AI_HOME -ErrorAction SilentlyContinue
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QTWEBENGINE_CHROMIUM_FLAGS = '--disable-gpu --no-sandbox'
$report = [ordered]@{ platform = [Environment]::OSVersion.VersionString; scope = 'Actual Kandha per-user installer and packaged QtWebEngine page on a disposable Windows CI account; no microphone, no Bluetooth hardware' }
try {
    $log = Join-Path $Output 'kandha-installer.log'
    $process = Start-Process $Installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/TASKS=desktopicon', "/DIR=`"$target`"", "/LOG=`"$log`"") -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Kandha installation failed: $($process.ExitCode)" }
    foreach ($exe in @('Kandha.exe', 'AccessibilityAI.exe', 'AccessibilityAIWorker.exe')) {
        if (-not (Test-Path "$target\$exe")) { throw "Installed executable missing: $exe" }
    }
    if (-not (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Kandha\Kandha.lnk")) { throw 'Start menu entry "Kandha" missing' }
    if (-not (Test-Path "$target\_internal\firmware\kandha\kandha.ino")) { throw 'Firmware sources missing from the payload' }
    if (-not (Test-Path "$target\_internal\browser\kandha\fonts\AtkinsonHyperlegible-Regular.ttf")) { throw 'Bundled font missing' }
    if (-not (Test-Path "$target\_internal\models\sanket\tone_model.json")) { throw 'Tone model missing' }
    $report.install_and_shortcuts = 'PASS'
    $check = Start-Process "$target\AccessibilityAIWorker.exe" -ArgumentList @('--kandha-check') -RedirectStandardOutput "$Output\kandha-check.txt" -RedirectStandardError "$Output\kandha-check-errors.txt" -PassThru
    if (-not $check.WaitForExit(180000)) { Stop-Process -Id $check.Id -Force; throw 'Packaged Kandha page check timed out' }
    $line = Get-Content "$Output\kandha-check.txt" | Where-Object { $_ -like '{*"ok"*' } | Select-Object -Last 1
    if (-not $line) { Get-Content "$Output\kandha-check-errors.txt"; throw 'No readiness line from --kandha-check' }
    $result = $line | ConvertFrom-Json
    if (-not $result.ok) { throw "Packaged Kandha page did not become ready: $line" }
    $report.packaged_page_ready = $result
    $report.bluetooth_backend_import = (& "$target\AccessibilityAIWorker.exe" --list-devices 2>$null; 'see kandha-check; bleak is imported lazily on the Bluetooth link only')
} finally {
    if (Test-Path "$target\unins000.exe") {
        $uninstall = Start-Process "$target\unins000.exe" -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/PURGEUSERDATA=1', "/LOG=`"$Output\kandha-uninstall.log`"") -PassThru -Wait
        $report.uninstall = if ($uninstall.ExitCode -eq 0 -and -not (Test-Path "$target\Kandha.exe")) { 'PASS' } else { "exit $($uninstall.ExitCode)" }
    }
    $report | ConvertTo-Json -Depth 6 | Set-Content "$Output\kandha-acceptance.json" -Encoding utf8
}
Get-Content "$Output\kandha-acceptance.json"
