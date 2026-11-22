#!/usr/bin/env bash
# Kandha Stole: build and flash the firmware onto the Waveshare ESP32-S3-Zero, then open the
# serial console. macOS and Linux.
#   firmware/kandha/flash.sh                 build, flash, open the console
#   firmware/kandha/flash.sh /dev/ttyACM0    use this port
#   firmware/kandha/flash.sh --monitor       only open the console
#   firmware/kandha/flash.sh --no-monitor    build and flash only
# In the console type   identify   to find which GPIO drives which motor.
set -euo pipefail

SKETCH="$(cd "$(dirname "$0")" && pwd)"
FQBN="esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=4M,PSRAM=enabled"
CORE_URL="https://espressif.github.io/arduino-esp32/package_esp32_index.json"
CORE_VERSION="3.1.1"
CLI_VERSION="1.2.2"
PORT="" MONITOR_ONLY=0 NO_MONITOR=0
for arg in "$@"; do
  case "$arg" in
    --monitor) MONITOR_ONLY=1 ;;
    --no-monitor) NO_MONITOR=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) PORT="$arg" ;;
  esac
done
step() { printf '\n== %s\n' "$1"; }

# ------------------------------------------------------------------ 1. arduino-cli
CLI="$(command -v arduino-cli || true)"
if [ -z "$CLI" ]; then
  TOOLS="$SKETCH/.tools"
  CLI="$TOOLS/arduino-cli"
  if [ ! -x "$CLI" ]; then
    case "$(uname -s)-$(uname -m)" in
      Linux-x86_64) ASSET="Linux_64bit.tar.gz"; SHA="a5ad085d1b02fd4010df18b1bbf20453276efe6c6e2ac323baa0cac4e96a85b4" ;;
      Darwin-arm64) ASSET="macOS_ARM64.tar.gz"; SHA="bf7a6ee89b63ee95f708c20bcb60fdb81037da1319269187ee100528f5ad1bd1" ;;
      Darwin-x86_64) ASSET="macOS_64bit.tar.gz"; SHA="fb3c019eb01fcaba46e12c0dfd00386f9bdb44a83f83a3d810a3bc303cc3e5dd" ;;
      *) echo "No pinned arduino-cli for $(uname -s) $(uname -m). Install arduino-cli 1.x yourself and run this again."; exit 1 ;;
    esac
    step "Downloading arduino-cli $CLI_VERSION"
    mkdir -p "$TOOLS"
    curl -fsSL -o "$TOOLS/cli.tar.gz" "https://github.com/arduino/arduino-cli/releases/download/v$CLI_VERSION/arduino-cli_${CLI_VERSION}_$ASSET"
    GOT="$( (command -v sha256sum >/dev/null && sha256sum "$TOOLS/cli.tar.gz" || shasum -a 256 "$TOOLS/cli.tar.gz") | cut -d' ' -f1)"
    if [ "$GOT" != "$SHA" ]; then echo "arduino-cli download failed its checksum ($GOT). Not using it."; exit 1; fi
    tar -xzf "$TOOLS/cli.tar.gz" -C "$TOOLS" arduino-cli
    rm "$TOOLS/cli.tar.gz"
  fi
fi
echo "arduino-cli: $CLI"

if [ "$MONITOR_ONLY" = 0 ]; then
  # ---------------------------------------------------------------- 2. the ESP32 core
  if ! "$CLI" core list --additional-urls "$CORE_URL" 2>/dev/null | grep -Eq "^esp32:esp32[[:space:]]+$CORE_VERSION([[:space:]]|$)"; then
    step "Installing the Arduino-ESP32 core $CORE_VERSION (one time, several hundred MB)"
    "$CLI" core update-index --additional-urls "$CORE_URL"
    "$CLI" core install "esp32:esp32@$CORE_VERSION" --additional-urls "$CORE_URL"
  fi
  # ---------------------------------------------------------------- 3. compile
  step "Compiling the Kandha firmware for the ESP32-S3-Zero"
  "$CLI" compile --fqbn "$FQBN" --additional-urls "$CORE_URL" "$SKETCH"
fi

# ------------------------------------------------------------------ 4. the port
if [ -z "$PORT" ]; then
  step "Looking for the board"
  # Espressif's USB vendor id is 303a; fall back to the usual native-USB device names.
  PORT="$("$CLI" board list 2>/dev/null | awk 'NR>1 && /303[aA]|ESP32/ {print $1; exit}')"
  if [ -z "$PORT" ]; then
    for candidate in /dev/cu.usbmodem* /dev/ttyACM*; do [ -e "$candidate" ] && { PORT="$candidate"; break; }; done
  fi
  if [ -z "$PORT" ]; then
    "$CLI" board list || true
    echo "No ESP32-S3 found. Use a USB DATA cable. If it still does not appear: hold BOOT, tap RESET"
    echo "(or plug in while holding BOOT), release BOOT, run this again."
    read -r -p "Type the port to use (e.g. /dev/ttyACM0 or /dev/cu.usbmodem1101): " PORT
  fi
fi
[ -n "$PORT" ] || { echo "No port chosen."; exit 1; }
echo "Port: $PORT"
if [ "$(uname -s)" = Linux ] && [ ! -w "$PORT" ]; then
  GROUP="$(stat -c %G "$PORT" 2>/dev/null || echo dialout)"   # uucp on Arch, dialout on Debian/Ubuntu
  echo "No permission to write $PORT. Run:  sudo usermod -aG $GROUP \$USER   then log out and back in."
  exit 1
fi

# ------------------------------------------------------------------ 5. upload and monitor
if [ "$MONITOR_ONLY" = 0 ]; then
  step "Uploading to $PORT"
  if ! "$CLI" upload --fqbn "$FQBN" -p "$PORT" "$SKETCH"; then
    echo "Upload failed. Put the board in download mode: hold BOOT, tap RESET (or replug while"
    echo "holding BOOT), release BOOT, then run this again. After the upload press RESET once."
    exit 1
  fi
  echo "Flashed. Waiting for the board to restart..."
  sleep 3
fi
[ "$NO_MONITOR" = 1 ] && exit 0
step "Serial console on $PORT (115200 baud). Type help, or identify to find the motors. Ctrl+C to quit."
exec "$CLI" monitor -p "$PORT" --config baudrate=115200
