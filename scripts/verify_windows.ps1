param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$UpgradeInstaller,
    [string]$Output = 'windows-acceptance'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $env:CI) { throw 'Run destructive installer acceptance only in a disposable CI Windows account (CI=true).' }
$Installer = (Resolve-Path $Installer).Path
$UpgradeInstaller = (Resolve-Path $UpgradeInstaller).Path
$Output = (New-Item -ItemType Directory -Force $Output).FullName
$target = Join-Path $env:LOCALAPPDATA 'Programs\AudialAI Acceptance'
$state = Join-Path $env:LOCALAPPDATA 'AccessibilityAI'
if ((Test-Path $target) -or (Test-Path $state)) { throw 'Fresh-install acceptance requires an empty disposable account.' }
$previousRoot = $env:ACCESSIBILITY_AI_HOME
$previousQt = $env:QT_QPA_PLATFORM
Remove-Item Env:ACCESSIBILITY_AI_HOME -ErrorAction SilentlyContinue
$report = [ordered]@{ platform = [Environment]::OSVersion.VersionString; scope = 'Actual per-user installer and native runtime on a disposable Windows CI account' }
$desktopProcess = $null

function Install-Audial([string]$Setup, [string]$Label) {
    Write-Output "Installing: $Label"
    $log = Join-Path $Output "$Label-installer.log"
    $process = Start-Process $Setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/TASKS=desktopicon', "/DIR=`"$target`"", "/LOG=`"$log`"") -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "$Label installation failed: $($process.ExitCode)" }
    if (-not (Test-Path "$target\AccessibilityAI.exe") -or -not (Test-Path "$target\AccessibilityAIWorker.exe")) { throw 'Installed executables are missing' }
}
function Invoke-Worker([string[]]$Arguments, [string]$Label, [int]$TimeoutSeconds = 300) {
    Write-Output "Running installed worker: $Label"
    $process = Start-Process "$target\AccessibilityAIWorker.exe" -ArgumentList $Arguments -RedirectStandardOutput "$Output\$Label.txt" -RedirectStandardError "$Output\$Label-errors.txt" -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) { Stop-Process -Id $process.Id -Force; throw "$Label timed out" }
    if ($process.ExitCode -ne 0) { Get-Content "$Output\$Label-errors.txt"; throw "$Label failed: $($process.ExitCode)" }
}
function Launch-Desktop([string]$Label) {
    $env:QT_QPA_PLATFORM = 'windows'
    $process = Start-Process "$target\AccessibilityAI.exe" -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    do {
        Start-Sleep -Milliseconds 400
        $process.Refresh()
        if ($process.HasExited) { throw 'Native desktop exited during first launch' }
    } until ($process.MainWindowHandle -ne 0 -or [DateTime]::UtcNow -gt $deadline)
    if ($process.MainWindowHandle -eq 0) { Stop-Process $process.Id -Force; throw 'No native Windows desktop window appeared' }
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $bounds = [Windows.Forms.Screen]::PrimaryScreen.Bounds
    $image = New-Object Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [Drawing.Graphics]::FromImage($image)
    $graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size)
    $image.Save("$Output\$Label.png", [Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $image.Dispose()
    return $process
}
function Close-Desktop($Process) {
    $Process.CloseMainWindow() | Out-Null
    if (-not $Process.WaitForExit(15000)) { Stop-Process -Id $Process.Id -Force; throw 'Desktop did not close cleanly' }
    if ($Process.ExitCode -ne 0) { throw 'Desktop returned an error on close' }
}
function Uninstall-Audial([bool]$Purge, [string]$Label) {
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$Output\$Label.log`"")
    if ($Purge) { $arguments += '/PURGEUSERDATA=1' }
    $process = Start-Process "$target\unins000.exe" -ArgumentList $arguments -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw 'Uninstaller failed' }
    if (Test-Path "$target\AccessibilityAI.exe") { throw 'Uninstaller retained the executable' }
}

try {
    Install-Audial $Installer 'fresh'
    $report.fresh_install = 'PASS'
    $manifest = Get-Content "$target\native-host\native-host.json" -Raw | ConvertFrom-Json
    if ($manifest.allowed_origins[0] -ne 'chrome-extension://dojclhfndceededaacaeblikncmihnkb/') { throw 'Native bridge origin mismatch' }
    foreach ($browser in @('Google\Chrome', 'Microsoft\Edge')) {
        $key = Get-Item "HKCU:\Software\$browser\NativeMessagingHosts\org.audialai.bridge"
        if ($key.GetValue('') -ne "$target\native-host\native-host.json") { throw 'Per-user native bridge registration failed' }
    }
    if (-not (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Audial-AI\Audial-AI.lnk")) { throw 'Start menu shortcut missing' }
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (-not (Test-Path "$desktop\Audial-AI.lnk")) { throw 'Optional desktop shortcut missing' }
    $report.shortcuts_and_native_registration = 'PASS'
    $desktopProcess = Launch-Desktop 'first-launch'
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while (-not (Test-Path "$state\model-setup.json") -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 300 }
    if (-not (Test-Path "$state\model-setup.json")) { throw 'Automatic first-run model setup did not start' }
    Close-Desktop $desktopProcess
    $report.native_first_launch_and_automatic_setup = 'PASS'
    $env:QT_QPA_PLATFORM = 'offscreen'
    Invoke-Worker @('--smoke-test') 'installed-smoke'
    # The real model catalogue is downloaded by the installed executable.
    Invoke-Worker @('--setup-models') 'installed-model-setup' 1800
    $setup = Get-Content "$state\model-setup.json" -Raw | ConvertFrom-Json
    foreach ($property in $setup.models.PSObject.Properties) {
        if ($property.Name -eq 'pyannote') {
            if ($property.Value.state -ne 'needs_action') { throw 'Unauthenticated gated model status is incorrect' }
        } elseif ($property.Value.state -ne 'ready') { throw "Public asset not ready: $($property.Name)" }
    }
    $report.complete_public_catalogue = 'PASS; gated Community-1 correctly requires user acceptance and token'
    $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'
    Invoke-Worker @('--verify-inference') 'installed-offline-inference' 300
    $report.offline_caption_expression_prosody = 'PASS'
    'keep this session' | Set-Content "$state\acceptance-sentinel.txt" -Encoding utf8
    $before = (Get-FileHash "$state\acceptance-sentinel.txt").Hash
    Install-Audial $UpgradeInstaller 'upgrade'
    if ((Get-FileHash "$state\acceptance-sentinel.txt").Hash -ne $before) { throw 'Upgrade changed user data' }
    $report.upgrade_data_preservation = 'PASS (same runtime payload packaged with incremented installer version; historical binary upgrade still requires the old installer)'
    Install-Audial $Installer 'reinstall'
    if ((Get-FileHash "$state\acceptance-sentinel.txt").Hash -ne $before) { throw 'Reinstall changed user data' }
    $report.reinstall_data_preservation = 'PASS'
    $desktopProcess = Launch-Desktop 'offline-relaunch'
    Close-Desktop $desktopProcess
    $report.offline_native_relaunch = 'PASS'
    Uninstall-Audial $false 'uninstall-keep-data'
    if ((Get-FileHash "$state\acceptance-sentinel.txt").Hash -ne $before) { throw 'Default uninstall removed user data' }
    foreach ($browser in @('Google\Chrome', 'Microsoft\Edge')) {
        if (Test-Path "HKCU:\Software\$browser\NativeMessagingHosts\org.audialai.bridge") { throw 'Uninstall retained native bridge registration' }
    }
    $report.uninstall_preserves_data_by_default = 'PASS'
    Install-Audial $Installer 'restore-after-uninstall'
    if ((Get-FileHash "$state\acceptance-sentinel.txt").Hash -ne $before) { throw 'Reinstall after uninstall lost data' }
    Uninstall-Audial $true 'uninstall-explicit-purge'
    if (Test-Path $state) { throw 'Explicit uninstall purge did not remove user data' }
    $report.explicit_uninstall_purge = 'PASS'
    $report.installer_sha256 = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    $report.authenticode = (Get-AuthenticodeSignature $Installer).Status.ToString()
    if ($report.authenticode -ne 'NotSigned') { throw 'Unexpected signing status; update the reported build policy' }
} catch {
    $report.failure = $_.Exception.Message
    throw
} finally {
    $report | ConvertTo-Json -Depth 5 | Set-Content "$Output\installer-acceptance.json" -Encoding utf8
    if ($desktopProcess -and -not $desktopProcess.HasExited) { Stop-Process -Id $desktopProcess.Id -Force }
    if (Test-Path "$state\model-setup.json") { Copy-Item "$state\model-setup.json" "$Output\model-setup.json" -Force }
    if (Test-Path "$state\startup-error.log") { Copy-Item "$state\startup-error.log" "$Output\startup-error.log" -Force }
    if ($previousRoot) { $env:ACCESSIBILITY_AI_HOME = $previousRoot } else { Remove-Item Env:ACCESSIBILITY_AI_HOME -ErrorAction SilentlyContinue }
    if ($previousQt) { $env:QT_QPA_PLATFORM = $previousQt } else { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
}
