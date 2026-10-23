# Kandha Stole firmware

Firmware for the Kandha Stole's ESP32-S3, implementing [protocol v1](../../docs/kandha/PROTOCOL.md).
It plays the shared tap language (`patterns.h`, generated from
`browser/sanket/kandha-patterns.json`), reads the four textile touch pads, reports the battery,
and offers a serial console for bench tests.

**Status: prototype.** This firmware compiles for the ESP32-S3 in CI
(`.github/workflows/firmware.yml`), and `tests/test_kandha_firmware_host.py` builds and runs it
on an ordinary computer against Arduino and BLE stand-ins (`tests/firmware_host/`). It has
**not yet been run on hardware**. The Kandha app does not need it: the app ships with a virtual
stole and a simulated stole, and real Bluetooth is an opt-in setting marked untested.

## Files

| File | What |
|---|---|
| `kandha.ino` | main sketch: BLE service, battery, status, serial console; the BLE callbacks only queue writes for `loop()` |
| `pattern_engine.h` | the pattern player (same steps, timing and arithmetic as `app/kandha/patterns.py`), MOSFET PWM with a 60/255 floor and a 15 ms spin-up kick from rest |
| `touch_pads.h` | pads with tap / double / long gestures (timing in `PROTOCOL.md`) |
| `config.h` | pin map, timings, firmware version |
| `patterns.h` | **generated**: run `python scripts/generate_kandha_patterns.py` after editing the JSON |

## Hardware

Pin map and parts list: [docs/kandha/DESIGN.md section 5](../../docs/kandha/DESIGN.md). In short:
pads on GPIO 1–4 (touch), motor MOSFET gates on GPIO 5–8, battery divider on GPIO 9, charger
`CHRG` on GPIO 10, status LED on GPIO 48.

## Build and flash (first time with an ESP32)

You need a computer with a USB port and the free **Arduino IDE 2** (Windows, macOS or Linux).

1. Install the Arduino IDE 2 from arduino.cc. Open it.
2. **File → Preferences → Additional boards manager URLs**, add
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json` and press OK.
3. **Tools → Board → Boards Manager**, search `esp32`, install **esp32 by Espressif Systems**
   version **3.1.x** (the Arduino-ESP32 core 3.x). This is a large download.
4. Plug the ESP32-S3 board into USB. On most boards no driver is needed; Windows may need the
   CP210x or CH340 driver from the board maker's page if no port appears.
5. **Tools → Board → esp32 → ESP32S3 Dev Module**. Leave the defaults except:
   **USB CDC On Boot: Enabled** (so the serial console works over the USB port).
6. **Tools → Port**, choose the port that appeared when you plugged the board in.
7. **File → Open**, choose `firmware/kandha/kandha.ino`. The other files open as tabs.
8. Press **Upload** (the arrow). If the upload does not start, hold the board's **BOOT** button,
   tap **RESET**, release **BOOT**, and press Upload again.
9. **Tools → Serial Monitor**, set **115200 baud**. You should see
   `Kandha Stole firmware 0.9, pattern table …` and `Advertising as Kandha-XXXX`.
   Type `help` and press Enter.

### Command line (optional)

```text
arduino-cli core install esp32:esp32@3.1.1 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli compile --fqbn esp32:esp32:esp32s3 --export-binaries firmware/kandha
arduino-cli upload  --fqbn esp32:esp32:esp32s3 -p /dev/ttyACM0 firmware/kandha
```

The firmware workflow uploads the `.bin` files with a `kandha-stole-firmware.sha256` list as the
`kandha-stole-firmware` artifact. A `kandha-v<version>` release publishes them as
`kandha-stole-firmware-<version>.zip` (with `SHA256SUMS.txt` inside and a `.sha256` beside
it); they are not in the Kandha installer. `esptool.py write_flash 0x0 kandha.ino.merged.bin`
flashes a board without the IDE.

## How it behaves

- **Motors.** A zone's duty is `level × intensity × zone scale / (255 × 255)`, as in the app.
  Any non-zero duty below 60 is raised to 60 (`MOTOR_MIN_DUTY`; a coin ERM does not start below
  it), and a motor starting from rest runs at full duty for its first 15 ms (`MOTOR_KICK_MS`),
  kept through a step or command that takes over within those 15 ms. A motor already spinning
  gets no kick. A new command takes over at once, with no stop in between.
- **The link.** The BLE callbacks only queue each write (16 at most) for `loop()`, which applies
  them in order; connects and disconnects are counted, so none is lost. A disconnect stops every
  motor. A new connection resets the duplicate-`seq` filter, so the first command after a
  reconnect always plays. If `loop()` falls behind, writes that change nothing are left out
  first, then the oldest HAPTIC, then the oldest PATTERNS upload, and the console prints
  `BLE: loop() fell behind: N writes left out with nothing lost, M lost`.
- **STATUS** is notified as soon as any flag changes and at least every 30 s.

## Bench checks with the serial console

```text
status            battery, connection, config, flags
patterns          the built-in tap language with durations
play seat_tap L   one firm tap on the left shoulder
play rise         three quick taps at the front
test              two taps on every zone in turn (an app command during it replaces the test tap)
pads              raw touch values; touch a pad and watch the number rise
cal               recalibrate the pads (keep hands away)
pad Q tap         send an INPUT as if the queue pad were tapped
mirror 1          swap left and right
```

## Pairing with Kandha

In the app's **Settings**, set **Stole link** to **Real Bluetooth (experimental)**, then on the
**Stole** screen press **Scan** and **Pair** the `Kandha-XXXX` that appears. The firmware
requests LE Secure Connections "Just Works" bonding; the app also only accepts pad input from the
address it paired with.

## Things to measure on real hardware

Nothing below has been measured yet; every number in the design document about hardware is
a datasheet estimate.

- Tap latency from the app's decision to motor start (budget: 300 ms including Bluetooth).
- Whether 120 ms taps feel distinct from the 60 ms new-voice taps on the chosen motors
  (decision 0003 names DRV2605L drivers as the fallback).
- Touch thresholds through the stitched pads (`TOUCH_THRESHOLD_RATIO` in `config.h`).
- Battery life over a college day (`docs/kandha/DESIGN.md` section 5.2).
