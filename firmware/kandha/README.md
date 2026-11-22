# Kandha Stole firmware

Firmware for the Kandha Stole's ESP32-S3, implementing [protocol v1](../../docs/kandha/PROTOCOL.md).
It plays the shared tap language (`patterns.h`, generated from
`browser/sanket/kandha-patterns.json`), reads the four textile touch pads, reports the battery,
and offers a serial console for bench tests.

**Status: prototype.** This firmware compiles in CI (`.github/workflows/firmware.yml`) and has
**not yet been run on hardware**. The Kandha app does not need it: the app ships with a virtual
stole and a simulated stole, and real Bluetooth is an opt-in setting marked untested.

## Files

| File | What |
|---|---|
| `kandha.ino` | main sketch: BLE service, battery, status, serial console |
| `pattern_engine.h` | the pattern player (same steps and arithmetic as `app/kandha/patterns.py`), transistor PWM with a spin-up kick |
| `touch_pads.h` | pads with tap / double / long gestures |
| `motor_map.h` | which GPIO drives which motor zone, saved in flash, and the `identify` wizard that finds out |
| `config.h` | pin map, timings, firmware version |
| `flash.bat` / `flash.ps1` | Windows: build, flash and open the serial console in one go |
| `flash.sh` | macOS / Linux: the same |
| `patterns.h` | **generated**: run `python scripts/generate_kandha_patterns.py` after editing the JSON |

## Hardware

Pin map and parts list: [docs/kandha/DESIGN.md section 5](../../docs/kandha/DESIGN.md). The
bench stole is a **Waveshare ESP32-S3-Zero**. In short: pads on GPIO 1–4 (touch), battery
divider on GPIO 5, charger `CHRG` on GPIO 6, motor transistors (2N2222A, through 330 Ω) on
GPIO 8–11 (default order L, R, B, F; see **Find the motors** below if yours differ), and the onboard WS2812 RGB status light on GPIO 21. GPIO 7 and 12–16,
43 and 44 are reserved for the F pad and the v2 mic pod. Status light: blue flash while
advertising, green blink when connected, solid green while a pattern plays, magenta blink while
finding the motors.

## Quick start: flash with one command

Plug the ESP32-S3-Zero in with a USB **data** cable, then from the repository folder:

- **Windows:** double-click `firmware\kandha\flash.bat`, or run it in a terminal.
- **macOS / Linux:** `bash firmware/kandha/flash.sh`

The script:
1. downloads `arduino-cli` 1.2.2 if you don't have it (checksum-verified, kept in
   `firmware/kandha/.tools/`);
2. installs the ESP32 core 3.1.1 the first time (a large download);
3. compiles for the S3-Zero;
4. finds the board's port, uploads, and opens the serial console at 115200 baud.

Options:
- choose the port with `flash.bat -Port COM5` or `flash.sh /dev/ttyACM0`;
- only reopen the console with `flash.bat -MonitorOnly` or `flash.sh --monitor`.

If the upload fails, put the board in download mode and run the script again: hold **BOOT**,
tap **RESET** (or plug in while holding **BOOT**), then release **BOOT**. After the upload,
press **RESET** once.

## Find the motors (`identify`)

The four motor transistors are on GPIO 8, 9, 10 and 11, but the wires may not run L, R, B, F
in that order. The board can't sense where a motor sits on your body, so it asks you.

1. Flash, and open the serial console (the flash script opens it for you).
2. Put the stole on, or hold the motors where you can feel them.
3. Type `identify` and press Enter. The status light blinks magenta.
4. One GPIO buzzes at a time (about 12 times, then it waits). Say where you feel it: type `L`,
   `R`, `B` or `F` and press Enter. Or tap the stole's **L**, **R** or **B** pad; tap **Q**
   for **F**, because the F pad isn't wired yet.
   - L and R each have **two** motors, so you feel two buzzes at once there. B and F have one.
   - Other answers: `again` buzzes it again, `none` means you felt nothing, `back` goes to the
     previous pin, `cancel` stops without changing anything.
5. After four answers it shows the map, for example `L = GPIO 10, R = GPIO 8, B = GPIO 11,
   F = GPIO 9`. Type `save`. It refuses to save if a zone is missing or was given twice; type
   `redo` instead.
6. It saves the map in the chip's flash, then taps L, R, B and F once each and says which one
   you should feel. If one is wrong, run `identify` again.

The map is kept through power-off **and** reflashing, so you only do this once per stole.

Related commands:
- `motors` shows the saved map;
- `motors 10 8 11 9` sets it by hand (the GPIOs for L R B F, in that order);
- `motors reset` goes back to the default 8, 9, 10, 11.

If exactly one pin buzzes nothing (you answered `none`) and the other three are known, the
wizard works out that pin's zone, but tells you to check that motor's transistor, diode and
wires. A motor that never buzzes is a wiring fault, not a mapping problem.

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
   **USB CDC On Boot: Enabled** (so the serial console works over the USB port),
   **Flash Size: 4MB** and **PSRAM: QSPI PSRAM** (the S3-Zero's ESP32-S3FH4R2).
6. **Tools → Port**, choose the port that appeared when you plugged the board in.
7. **File → Open**, choose `firmware/kandha/kandha.ino`. The other files open as tabs.
8. Press **Upload** (the arrow). If the upload does not start, hold the board's **BOOT** button,
   tap **RESET**, release **BOOT**, and press Upload again.
9. **Tools → Serial Monitor**, set **115200 baud**. You should see
   `Kandha Stole firmware 0.11, pattern table …`, `Advertising as KandhaStole-XXXX` and the
   motor map. Set the monitor's line ending to **Newline**, type `help` and press Enter, then
   `identify` (see **Find the motors**).

### Command line by hand (optional)

```text
arduino-cli core install esp32:esp32@3.1.1 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli compile --fqbn esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=4M,PSRAM=enabled --export-binaries firmware/kandha
arduino-cli upload  --fqbn esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=4M,PSRAM=enabled -p /dev/ttyACM0 firmware/kandha
arduino-cli monitor -p /dev/ttyACM0 --config baudrate=115200
```

The CI workflow produces `kandha-stole-firmware.zip` with the `.bin` files and a `.sha256` file;
`esptool.py write_flash 0x0 kandha.ino.merged.bin` flashes a board without the IDE.

## Bench checks with the serial console

```text
status            battery, connection, config, flags
patterns          the built-in tap language with durations
play seat_tap L   one firm tap on the left shoulder
play rise         three quick taps at the front
test              two taps on every zone in turn, saying which one you should feel
identify          find which GPIO drives which motor, and save it
motors            show the saved motor map
hold 9            keep GPIO 9's motor on (up to 60 s) to measure that channel
hold off          switch it off
pads              raw touch values; touch a pad and watch the number rise
cal               recalibrate the pads (keep hands away)
pad Q tap         send an INPUT as if the queue pad were tapped
mirror 1          swap left and right
```

## Pairing with Kandha

In the app's **Settings**, set **Stole link** to **Real Bluetooth (experimental)**, then on the
**Stole** screen press **Scan** and **Pair** the `KandhaStole-XXXX` that appears. The firmware
requests LE Secure Connections "Just Works" bonding; the app also only accepts pad input from the
address it paired with.

## Things to measure on real hardware

Nothing below has been measured yet; every number in the design document about hardware is
a datasheet estimate.

- Tap latency from the app's decision to motor start (budget: 300 ms including Bluetooth).
- Whether 120 ms taps feel distinct from the 60 ms new-voice taps on the chosen motors
  (decision 0003 names DRV2605L drivers as the fallback).
- The 2N2222A's collector-emitter voltage with two motors on (L, R), and the lowest PWM duty
  that starts a motor (`MOTOR_MIN_DUTY`), decision 0013.
- Touch thresholds through the stitched pads (`TOUCH_THRESHOLD_RATIO` in `config.h`).
- Battery life over a college day (`docs/kandha/DESIGN.md` section 5.2).
