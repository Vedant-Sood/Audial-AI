param(
    [ValidateSet('CPU', 'NVIDIA')][string]$Runtime = 'CPU',
    [string]$Version = '',
    [string]$PayloadDir = '',
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
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
    if (-not $PayloadDir) {
        python -m scripts.package_extension --output build/browser-extension
        if ($LASTEXITCODE -ne 0) { throw 'Extension packaging failed' }
        $commit = git rev-parse HEAD
        $packages = @(python -m pip freeze)
        $build = [ordered]@{
            app_version = $Version; runtime = $Runtime; source_commit = $commit
            python = (python --version); dependencies = $packages
            inno_setup = (Get-Item $InnoCompiler).VersionInfo.FileVersion
            signing = 'Unsigned; no signing certificate configured'
        }
        New-Item -ItemType Directory -Force build | Out-Null
        $build | ConvertTo-Json -Depth 5 | Set-Content build/build-info.json -Encoding utf8
        python -m PyInstaller packaging/AccessibilityAI.spec --noconfirm --clean
        if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
        $PayloadDir = Join-Path $root 'dist\AccessibilityAI'
        Copy-Item README.md, LICENSE, LICENSE_UPLOADED, LICENSE_NOTICES.md -Destination $PayloadDir
        Copy-Item docs -Destination (Join-Path $PayloadDir 'docs') -Recurse -Force
        Copy-Item build/build-info.json -Destination $PayloadDir
        Copy-Item build/browser-extension -Destination (Join-Path $PayloadDir 'browser-extension') -Recurse -Force
    }
    $PayloadDir = (Resolve-Path $PayloadDir).Path
    & $InnoCompiler "/DAppVersion=$Version" "/DRuntime=$Runtime" "/DPayloadDir=$PayloadDir" packaging/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
    $installer = Join-Path $root "dist\installers\Audial-AI-$Version-Windows-x64-$Runtime-Setup.exe"
    $hash = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($installer))" | Set-Content "$installer.sha256" -Encoding ascii
    Get-Item $installer
} finally {
    Pop-Location
}
