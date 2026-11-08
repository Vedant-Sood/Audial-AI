param(
    [ValidateSet('CPU', 'NVIDIA')][string]$Runtime = 'CPU',
    [string]$Version = '',
    [string]$PayloadDir = '',
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
# Builds Kandha-Setup-<version>.exe and Kandha-<version>-windows.zip from the Audial-AI payload.
# Run scripts/build_windows.ps1 first (it builds the PyInstaller folder, which contains Kandha.exe),
# or pass -PayloadDir to reuse one.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if (-not $Version) {
        $Version = python -c 'from app import __version__; print(__version__)'
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read application version' }
    }
    if (-not (Test-Path $InnoCompiler)) { throw 'Inno Setup 6 compiler is required on the build machine.' }
    if (-not $PayloadDir) { $PayloadDir = Join-Path $root 'dist\AccessibilityAI' }
    $PayloadDir = (Resolve-Path $PayloadDir).Path
    if (-not (Test-Path (Join-Path $PayloadDir 'Kandha.exe'))) { throw 'Kandha.exe is missing from the payload; run scripts/build_windows.ps1 first.' }
    # Never package a Kandha whose Bluetooth link cannot work: bleak, its WinRT backend and their metadata must be inside.
    python packaging/kandha_bluetooth.py --payload $PayloadDir --os windows
    if ($LASTEXITCODE -ne 0) { throw 'The Kandha payload is missing bleak or its WinRT backend; install requirements.txt and rebuild.' }
    # The Start-menu guide entry opens this HTML copy (stock Windows has no program for .md files).
    if (-not (Test-Path (Join-Path $PayloadDir '_internal\docs\kandha\USER_GUIDE.html'))) { throw 'USER_GUIDE.html is missing from the payload; rebuild with packaging/AccessibilityAI.spec.' }
    & $InnoCompiler "/DAppVersion=$Version" "/DRuntime=$Runtime" "/DPayloadDir=$PayloadDir" packaging/kandha-installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Kandha installer compilation failed' }
    $installer = Join-Path $root "dist\installers\Kandha-Setup-$Version.exe"
    $hash = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($installer))" | Set-Content "$installer.sha256" -Encoding ascii
    python scripts/package_kandha_portable.py --payload $PayloadDir --output dist/installers --os windows
    if ($LASTEXITCODE -ne 0) { throw 'Portable Kandha packaging failed' }
    Get-ChildItem dist/installers -Filter 'Kandha-*'
} finally {
    Pop-Location
}
