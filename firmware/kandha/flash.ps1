# Kandha Stole: build and flash the firmware onto the Waveshare ESP32-S3-Zero, then open the
# serial console. Windows PowerShell 5.1 or PowerShell 7. Run it through flash.bat, or:
#   powershell -ExecutionPolicy Bypass -File firmware\kandha\flash.ps1 [-Port COM5] [-MonitorOnly] [-NoMonitor]
#
# What it does:
#   1. finds arduino-cli on PATH, or downloads the pinned 1.2.2 release into firmware\kandha\.tools
#      (checksum verified against the release's published SHA-256);
#   2. installs the Arduino-ESP32 core 3.1.1 if it is missing (a large one-time download);
#   3. compiles for the S3-Zero (4 MB flash, QSPI PSRAM, USB CDC serial);
#   4. finds the board's USB port (Espressif USB id 303A), or asks you to pick one;
#   5. uploads, then opens the serial console at 115200 baud.
# In the console type   identify   to find which GPIO drives which motor.
param(
  [string]$Port = "",
  [switch]$MonitorOnly,
  [switch]$NoMonitor
)
# Not "Stop": in Windows PowerShell 5.1 that turns any stderr line from arduino-cli into a
# fatal error. Each native step checks $LASTEXITCODE instead; cmdlets use -ErrorAction Stop.
$ErrorActionPreference = "Continue"
$Sketch = $PSScriptRoot
$Fqbn = "esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=4M,PSRAM=enabled"
$CoreUrl = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
$CoreVersion = "3.1.1"
$CliVersion = "1.2.2"
$CliSha256 = "bdd3ed88a361af8539e51a1cc0bf831b269be155ddfdd90cb96a900ce78723b7"   # arduino-cli_1.2.2_Windows_64bit.zip

# arduino-cli waits only 60 s for a download to start; the ESP32 core files are large.
if (-not $env:ARDUINO_NETWORK_CONNECTION_TIMEOUT) { $env:ARDUINO_NETWORK_CONNECTION_TIMEOUT = "300s" }
function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

# ------------------------------------------------------------------ 1. arduino-cli
$Cli = (Get-Command arduino-cli -ErrorAction SilentlyContinue).Source
if (-not $Cli) {
  $Tools = Join-Path $Sketch ".tools"
  $Cli = Join-Path $Tools "arduino-cli.exe"
  if (-not (Test-Path $Cli)) {
    Step "Downloading arduino-cli $CliVersion"
    New-Item -ItemType Directory -Force -Path $Tools | Out-Null
    $Zip = Join-Path $Tools "arduino-cli.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -ErrorAction Stop -UseBasicParsing -Uri "https://github.com/arduino/arduino-cli/releases/download/v$CliVersion/arduino-cli_${CliVersion}_Windows_64bit.zip" -OutFile $Zip
    $Hash = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLower()
    if ($Hash -ne $CliSha256) { Remove-Item $Zip; throw "arduino-cli download failed its checksum ($Hash). Not using it." }
    Expand-Archive -ErrorAction Stop -Force -Path $Zip -DestinationPath $Tools
    Remove-Item $Zip
  }
}
Write-Host "arduino-cli: $Cli"

if (-not $MonitorOnly) {
  # ---------------------------------------------------------------- 2. the ESP32 core
  $Installed = & $Cli core list --additional-urls $CoreUrl | Select-String -Pattern "^esp32:esp32\s+$([regex]::Escape($CoreVersion))\b"
  if (-not $Installed) {
    Step "Installing the Arduino-ESP32 core $CoreVersion (one time, several hundred MB)"
    & $Cli core update-index --additional-urls $CoreUrl
    if ($LASTEXITCODE) { throw "Could not download the board index. Check the internet connection." }
    & $Cli core install "esp32:esp32@$CoreVersion" --additional-urls $CoreUrl
    if ($LASTEXITCODE) { throw "Could not install the ESP32 core." }
  }

  # ---------------------------------------------------------------- 3. compile
  Step "Compiling the Kandha firmware for the ESP32-S3-Zero"
  & $Cli compile --fqbn $Fqbn --additional-urls $CoreUrl $Sketch
  if ($LASTEXITCODE) { throw "Compile failed (see above)." }
}

# ------------------------------------------------------------------ 4. the port
if (-not $Port) {
  Step "Looking for the board"
  $Ports = @()
  try { $Ports = ((& $Cli board list --format json | Out-String) | ConvertFrom-Json).detected_ports | Where-Object { $_.port.protocol -eq "serial" } } catch { }
  $Espressif = @($Ports | Where-Object { "$($_.port.properties.vid)" -match "303a" })
  if ($Espressif.Count -eq 1) { $Port = $Espressif[0].port.address }
  elseif (@($Ports).Count -eq 1) { $Port = @($Ports)[0].port.address }
  else {
    Write-Host "Serial ports found:"
    foreach ($p in $Ports) { Write-Host ("  {0}  {1}" -f $p.port.address, $(if ("$($p.port.properties.vid)" -match "303a") { "(ESP32-S3)" } else { "" })) }
    if (-not @($Ports).Count) {
      Write-Host "  none. Plug the board in with a USB DATA cable (some cables only charge)."
      Write-Host "  If it still does not appear: hold BOOT, tap RESET (or plug in while holding BOOT), release BOOT, run this again."
    }
    $Port = Read-Host "Type the port to use (e.g. COM5)"
  }
}
if (-not $Port) { throw "No port chosen." }
Write-Host "Port: $Port"

# ------------------------------------------------------------------ 5. upload and monitor
if (-not $MonitorOnly) {
  Step "Uploading to $Port"
  & $Cli upload --fqbn $Fqbn -p $Port $Sketch
  if ($LASTEXITCODE) {
    Write-Host "Upload failed. Put the board in download mode and try again:" -ForegroundColor Yellow
    Write-Host "  hold BOOT, tap RESET (or replug the USB while holding BOOT), release BOOT, then run this again."
    Write-Host "  The port number can change in download mode; after the upload press RESET once."
    exit 1
  }
  Write-Host "Flashed. Waiting for the board to restart..."
  Start-Sleep -Seconds 3
}
if ($NoMonitor) { exit 0 }
Step "Serial console on $Port (115200 baud). Type help, or identify to find the motors. Ctrl+C to quit."
# Pressing RESET (or replugging) restarts the board's USB too, so the COM port vanishes for a
# moment and the monitor exits. Wait for it to come back and reconnect; Ctrl+C quits for good.
while ($true) {
  & $Cli monitor -p $Port --config baudrate=115200
  Write-Host ""
  Write-Host "-- Board disconnected (RESET pressed?). Reconnecting when it is back... Ctrl+C to quit." -ForegroundColor Yellow
  Start-Sleep -Seconds 1
  while (-not ([System.IO.Ports.SerialPort]::GetPortNames() -contains $Port)) { Start-Sleep -Milliseconds 500 }
  Start-Sleep -Milliseconds 500
  Write-Host "-- Back on $Port. Type status to see the board's state." -ForegroundColor Cyan
}
