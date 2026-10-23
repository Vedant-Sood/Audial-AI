# Kandha 0.6.0 (prototype)

Kandha is a downloadable laptop app for deaf students who lip-read, paired with the Kandha
Stole, a haptic scarf. It replaces Sanket as the product inside Audial-AI and reuses Sanket's
voice engine, Audial-AI's local Whisper captions, sessions and exports.

**This is a prototype: no hardware is required or expected.** The virtual stole on screen shows
every tap; a simulated stole shows pairing, battery and reconnection; real Bluetooth is an
opt-in setting marked untested.

## What is in this release

- Live captions (English or हिन्दी, local Whisper) in the speaker's colour, with the
  psychology vocabulary and definitions. The Kandha window offers **Get the caption model**
  until Whisper is installed. A browser tab never falls back to the browser's own speech
  service unless you turn that on in Settings › Privacy (off by default).
- Who is speaking and where they sit: a room diagram, seat taps on the stole, pads and keys
  to seat voices, saved rooms, a "this is me" voice.
- The tap language: one firm tap on the speaker's side, two taps at the front for a new voice,
  tone cues at the collarbone, shoulder squeezes for the queue and for an open floor, a
  low-battery warning at the neck. One shared pattern table drives the app, the virtual stole,
  the tests and the firmware.
- A pure haptic scheduler: priorities, rate limits (3 s / 8 s), stale-drop at 1.5 s,
  pre-emption, Lecture / Seminar / Practicum / Do-not-disturb modes.
- Review with timeline lanes, tone notes, "How accurate is this?", a consent gate, saving and
  exports for live sessions and demos, whatever gave the captions; in the Kandha window exports
  go to your Downloads folder.
- Learn the taps (five-minute tutorial), per-zone intensity, mirror left/right.
- Two demos (seminar, practicum) through the real scheduler, from **Demos** in the dock, for
  filming.
- Downloads on a `kandha-v<version>` release: `Kandha-Setup-<version>.exe` (installs
  `Kandha.exe`; a `Kandha-Setup-<version>-NVIDIA.exe` when that runtime is built),
  `Kandha-<version>-windows.zip` and `kandha-stole-firmware-<version>.zip`, each with a
  `.sha256` beside it, plus `SHA256SUMS.txt` for all of them. There is no Linux or macOS
  download; from source, run `python -m app.main --kandha`.
- ESP32-S3 firmware for a future stole, with a flashing guide: compiled for the ESP32-S3 in CI
  and built and run on the host by the tests against the app's pattern player, not run on
  hardware. The firmware binary is the separate firmware download, not part of the installer.

## Measured (see docs/kandha/VALIDATION.md)

- In-app tap latency in the end-to-end check: p50 4.3 ms, p95 6.5 ms (budget 150 ms).
- Tap budget on the natural-speech fixtures: Seminar default 0 cue taps per minute; with cues
  on, 1.0 per minute; Practicum 1.0 per minute (target ≤ 6).
- Accessibility audit: every control reachable by keyboard with visible focus, no contrast
  failure, no overflow at 1280 × 720, both themes.
- Tests: pytest 206 passed, npm 38 passed (baseline before Kandha: 132 and 31).
- Windows CI: `Kandha-Setup-0.6.0.exe` built, installed on a disposable Windows account, the
  packaged page ready in 0.8 s, uninstalled cleanly (run 39807417445, both runtimes).

## Not measured

Nothing has been run on a physical stole or with Bluetooth hardware; Indian English and Hindi
speakers, real seminars and the tap language with deaf students are untested. The installer is
unsigned.
