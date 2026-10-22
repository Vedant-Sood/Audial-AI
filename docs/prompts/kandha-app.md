# Build Kandha: a laptop app for deaf students, paired with the Kandha Stole

You are Claude Code, working in the root of the **Audial-AI** repository
(github.com/Vedant-Sood/Audial-AI). Your job is to **design and fully build
Kandha**: a downloadable laptop app that works with the **Kandha Stole**, a
haptic scarf. The stole does not exist physically yet, so you will also write
its firmware and an on-screen virtual stole that behaves identically.

Work autonomously from start to finish. Ask me only if you are truly blocked,
for example by a missing credential or a decision that cannot be undone.
Otherwise make the most reasonable choice, record it as a decision record, and
keep going. The finished result must be a **downloadable installer file**
(see §11).

---

## 1. Who it is for

**Vikram** is a deaf psychology undergraduate (Hackcessible India 2026,
Vikram's challenge). He lip-reads, reads English fluently and knows ISL. In
lectures, seminars and clinical role-plays ("practicum") he struggles with
three things:

- **Finding the speaker.** When someone new starts talking, he loses the first
  words while his eyes search the room. Lip-reading only works if he is already
  looking at the right face.
- **Hearing tone.** Captions carry the words, not how they were said. In
  practicum, a client's voice dropping or rising is clinical information.
- **Getting a turn.** He can't hear the gap where he could speak, so he gets
  talked over.

**The rule behind every decision: his eyes stay on faces.** Anything that
makes him look down at a screen costs him the lips he is reading. Information
that needs no looking goes to the stole as a tap. The laptop screen is for
captions he chooses to glance at, and for review afterwards.

**The idea behind the stole:** deaf people commonly get each other's
attention with a tap on the shoulder. The stole taps the shoulder on the side
where the speaker is sitting.

---

## 2. What already exists — read these first

Audial-AI (by Vedant Sood) is a Python 3.11/3.12 + PySide6 desktop app. It
already has:

- **Local captions:** offline Whisper captions, an engine with bounded worker
  threads, and session storage and exports (VTT, SRT, TXT, JSON, CSV).
- **Browser side:** a loopback browser companion (`app/services/browser.py`,
  strict CSP, Host/Origin checks) and an MV3 browser extension.
- **Other features:** ISL playback, emotion models, and Windows packaging
  (PyInstaller + installer + GitHub Actions).

The previous app, **Sanket**, was merged into it. Kandha replaces Sanket as
the product and reuses its engine.

Read these before writing anything:

| Area | Files |
|---|---|
| Contribution rules | `CONTRIBUTING.md`, `README.md`, `docs/architecture.md`, `docs/testing.md` |
| Sanket overview, accuracy and limits | `docs/sanket.md`, `models/sanket/evaluation.json`, `models/sanket/provenance.json`, `docs/model_cards.md` |
| Voice engine (voice activity, speaker tracking, tone cues, tone estimates) | `browser/sanket/engine.js`, `browser/sanket/tone.js`, `models/sanket/tone_model.json` |
| Sanket app to evolve (captions, vocabulary, local captions, modes, review, demos) | `browser/sanket/index.html`, `app.js`, `captions.js`, `local-captions.js`, `recognizer.js`, `translator.js`, `demo.js`, `styles.css`, `worklet.js` |
| Voice events in Audial | `browser/voice-session.js`, `browser/voice-view.js`, `app/services/voice_view.py`, `app/services/browser.py` (`/api/voice-events`, `/api/voice-view/settings`, `/sanket/`), `app/services/browser_bridge.py`, `app/storage/transcript.py` |
| Desktop app and packaging | `app/main.py`, `app/ui/main_window.py`, `app/services/engine.py`, `packaging/AccessibilityAI.spec`, `scripts/build_windows.ps1`, `scripts/package_windows_portable.py`, `.github/workflows/` |
| Tests | `tests/sanket.test.js`, `tests/test_sanket_integration.py`, `scripts/verify_sanket.py`, `tests/browser.test.js`, `package.json` |

Facts about the existing engine you must keep:

- **Audio time.** Audio is analysed in 32 ms frames with a 16 ms hop at
  16 kHz. Every event carries audio time (seconds since the first captured
  sample), the same clock Whisper captions use.
- **Speaker decisions.** The engine decides who is speaking 0.64–1.4 s after
  speech starts, and rechecks during speech. Voices are session-only slots
  ("Voice 1", "Voice 2"), not identities.
- **Tone cues.** The cues are `drop` (voice softened), `rise` (voice rose),
  `hesitation` and `silence`. Once a person has been heard about four times,
  model-backed cues replace the loudness rules; a drop of 10 dB or more still
  counts as `drop`.
- **Tone estimates.** These are always relative to the person. A category is
  named only for a personal estimate (at least 4 earlier utterances from that
  person) with confidence ≥ 0.80; otherwise it is "uncertain". The training
  data is acted American English; nothing has been validated on Indian
  speakers. Keep this honesty in every user-facing word.

**Retired — do not build:** the Sanket wrist band or watch (`browser/sanket/band.js`,
its Bluetooth service `a7c2f3e0-…0001`, the "Connect Sanket Band" buttons and
settings), glasses-mounted lights, and any table-top pointer. Remove the band
from the UI and code. Git history keeps the record.

Before starting, run `npm test` and `python -m pytest -q` (with
`QT_QPA_PLATFORM=offscreen`) and record the baseline. Follow `CONTRIBUTING.md`:
- don't create git worktrees;
- never commit recordings or credentials;
- keep every dataset and model notice.

---

## 3. What Kandha does

Kandha is an **offline-first, downloadable laptop app**. Windows 10/11 x64 is
the main target; macOS (Apple silicon) and Linux must run from source. It:

1. **Captions** speech with Audial's local Whisper, in English or हिन्दी.
   - English↔Hindi translation only if it can run on the device; otherwise
     leave it off and say why. Never send audio or text online.
   - Keep the psychology vocabulary: autocorrected terms, with definitions on
     click.
2. **Shows who is speaking.** Each voice gets a colour, and its arrow points
   to that person's **seat zone**: left, right, behind or front.
3. **Drives the Kandha Stole.**
   - The shoulder on the speaker's side gets a tap.
   - Tone cues are felt at the collarbone.
   - The stole's queue pad lights an "I want to speak" strip on the screen.
4. **Reviews sessions** afterwards:
   - a timeline of voices, cues, tone estimates and queue moments;
   - consent required before saving;
   - export through Audial's session exports.

### Architecture (use this unless you find a concrete problem; record any change as a decision)

```
┌──────────── Kandha window (PySide6 + QWebEngineView) ────────────┐
│  Kandha UI (HTML/JS, evolved from browser/sanket/, CSP-safe)      │
│   • microphone → AudioWorklet → engine.js (voices, cues, tone)    │
│   • audio packets → /api/audio → Audial engine → Whisper captions │
│   • haptic intents → /api/kandha/haptic                           │
└──────────────┬────────────────────────────────────────────────────┘
               │ loopback HTTP (BrowserService: sessions, voice events, exports)
┌──────────────▼──────────── Python (same Audial process) ─────────┐
│  HapticScheduler ─ priorities, rate limits, modes (pure, tested)  │
│  StoleBridge     ─ bleak BLE client, reconnect, battery, pads     │
│  VirtualStole    ─ same protocol, drives the on-screen stole      │
│  SeatMap         ─ voice → zone, saved rooms                      │
└──────────────┬────────────────────────────────────────────────────┘
               │ Bluetooth LE (§5)
          ┌────▼─────┐
          │  Kandha  │  ESP32-S3 firmware (firmware/kandha/)
          │  Stole   │
          └──────────┘
```

Why this shape:

- **Reuse.** It keeps the tested JavaScript engine, local Whisper, sessions
  and exports.
- **No Web Bluetooth needed.** QWebEngine doesn't support it, while Python
  `bleak` works on Windows, macOS and Linux.
- **One process.** That keeps packaging simple.

Also:

- **Microphone permission.** Grant it with the Qt 6.8 `QWebEnginePage`
  permission API.
- **Startup and navigation.** Start with `python -m app.main --kandha` and add
  a "Kandha" entry to the desktop navigation. The browser companion's
  `/sanket/` route can redirect to a browser version of Kandha for people who
  prefer a tab.
- **Noise suppression.** Turn browser noise suppression **off** while voices
  are being tracked; it was measured to split one person into two colours.
  Leave echo cancellation on. Both the laptop's built-in microphone and a USB
  conference microphone must work.

---

## 4. The Kandha Stole (theoretical hardware — design everything around it)

The stole is a cotton or khadi scarf worn over both shoulders. The electronics
sit in a zipped inner channel and come out for washing. It must be
gender-neutral and look like ordinary clothing, not a medical device.

| Zone | Where | Motors | Used for |
|---|---|---|---|
| `L` | Top of the left shoulder | 2 coin vibration motors, about 3 cm apart | Speaker on the left |
| `R` | Top of the right shoulder | 2 | Speaker on the right |
| `B` | Back of the neck | 1 | Speaker behind |
| `F` | Front, at the collarbone or sternum | 1 | Tone cues; speaker in front |
| `LR` | Both shoulders together | (L + R) | A "squeeze": queue acknowledged, or floor open |

**Inputs:** four fabric touch pads at the right-hand end, each with a
different stitched texture so they can be found without looking: `PAD_L`,
`PAD_R`, `PAD_B` and `PAD_Q` (queue).

**Reference build.** Include a parts list with prices in ₹.

- **Controller: ESP32-S3 mini board.** It has capacitive touch built in; the
  ESP32-C3 does not, so if you use a C3, add a TTP223 or MPR121.
- **Motor drivers.** The DRV2605L haptic driver gives crisp taps, but its I²C
  address (0x5A) is fixed. Either use a TCA9548A multiplexer for one driver
  per zone, or drive the motors with logic-level MOSFETs and PWM and generate
  the waveforms in firmware. Compare the two in a decision record and pick
  one.
- **Power:** a slim 3.7 V LiPo (600–1000 mAh), a TP4056 USB-C charger and a
  soft power switch. Use flat, flexible wiring or conductive thread, and put
  the motors in small silicone pockets.
- **Targets:**
  - under about 120 g of electronics;
  - a full 8-hour college day on one charge at typical cue rates (show the
    duty-cycle calculation);
  - washable once the electronics are removed.

---

## 5. Kandha Stole Bluetooth protocol v1 (define exactly, then implement)

- **Service UUID:** generate a new 128-bit UUID. Never reuse the retired
  band's.
- **Name:** devices advertise as `KandhaStole-XXXX`.
- **Byte order:** multi-byte values are little-endian.

| Characteristic | Properties | Payload |
|---|---|---|
| `HAPTIC` | write without response | `[seq u8][zones u8 bitmask L=1 R=2 B=4 F=8][pattern u8][intensity u8 0–255][repeat u8]` |
| `PATTERNS` | write | Custom pattern upload `[id][n][(on_ms u16, off_ms u16, level u8) × n]`; ids 0–31 are reserved for built-ins |
| `INPUT` | notify | `[pad u8: 1=L 2=R 3=B 4=Q][gesture u8: 1=tap 2=double 3=long]` |
| `STATUS` | read + notify | `[battery % u8][charging u8][fw_major u8][fw_minor u8][flags u8]` |
| `CONFIG` | read + write | Per-zone intensity scale, global mute, mirror L/R, test mode |

Also specify and implement:

- **Reconnecting:** reconnect with backoff. While disconnected, captions keep
  working, and haptics fall back to the virtual stole and an on-screen flash.
- **Pairing:** user-initiated scan and pair, with the paired device
  remembered. Ignore `INPUT` from unknown devices.
- **Latency budget:** from the engine's speaker decision to the motor
  starting, ≤ 150 ms inside the app and ≤ 300 ms worst case including
  Bluetooth. Measure this with the mock device and report it.

---

## 6. The tap language

It must be learnable in five minutes and **quiet by default**. Vikram must
never feel a constant buzz: research on head-worn directional haptics found
it stressful when several people talk.

| Meaning | Zone | Pattern (starting point) |
|---|---|---|
| A known voice starts or takes over | That voice's seat zone | One firm 120 ms tap |
| A **new** voice appears | `F` | Two short taps |
| Voice softened (`drop`) | `F` | One slow 700 ms swell |
| Voice rose (`rise`) | `F` | Three quick 80 ms taps |
| Hesitation | `F` | Soft flutter (5 × 40 ms) |
| Long silence / floor open | `LR` | Two gentle ticks on both shoulders |
| Queue acknowledged (`PAD_Q`) | `LR` | One short squeeze |
| Waiting a long time (configurable, default 60 s) | `LR` | One reminder squeeze, at most once a minute |
| Low battery (20%) | `B` | Three slow pulses, once |

**Pattern table.** Keep a **single pattern table** in
`browser/sanket/kandha-patterns.json` (or similar). The app, the virtual
stole, the tests and the firmware build are all generated from it.

**HapticScheduler rules** (pure code with unit tests):

- **Priority:** speaker change > queue feedback > tone cue > silence. Drop any
  cue older than 1.5 s instead of playing it late.
- **Rate limits:** at most one tone cue every 3 s, and the same cue type at
  most once every 8 s (match `engine.js`). A speaker tap always pre-empts a
  cue in progress.
- **Back-channel filter:** no tap for very short turns such as "mm-hm".
  Choose the threshold (around 0.6 s) using the existing engine tests and
  LibriSpeech fixtures, and document it.
- **Modes:**
  - **Lecture:** one speaker; seat taps off; only queue feedback and silence.
  - **Seminar:** seat taps on; tone cues optional, off by default.
  - **Practicum:** two voices; tone cues on.
  - **Do not disturb:** only queue feedback.
- **Unmapped voice:** if a voice has no seat yet, tap `F` once.
- **Personal settings:** a mirror setting swaps left and right, and each zone
  has its own intensity.

---

## 7. The seat map (how voices become shoulders)

The voice engine knows *who* is speaking (a voice slot), not *where* they
sit. The seat map links the two:

- **Assigning a new voice.** When a new voice appears (two taps on `F`),
  Vikram touches `PAD_L`, `PAD_R` or `PAD_B` within about 6 s to set its seat.
  If he touches nothing, the voice stays unmapped.
- **Reassigning.** A double-tap on a pad reassigns the voice that is speaking
  right now.
- **On screen.** Voice chips can be dragged onto a top-down room diagram
  showing Vikram and the seats. On-screen arrows follow the seat map.
- **Saved rooms.** Save layouts per room ("Seminar room 2.14", "Practicum
  lab") and offer them at the next session. Voices are session-only, so a
  saved layout is a starting point, not tied to people; don't attempt
  cross-session voice identity.
- **Practicum default:** the partner is usually in front, so default the
  other voice to `F`.
- **Future direction sensing:** define a `SeatSource` interface (an angle per
  voice) for a future microphone array, but don't build the array.

---

## 8. Screens

**Visual style:**
- large type and high contrast;
- dark and light themes;
- the Atkinson Hyperlegible font, bundled locally (no web fonts at runtime).

**Accessibility:** everything is keyboard-reachable with visible focus, meets
WCAG 2.1 AA, and works at 1280 × 720.

1. **Live view.**
   - **Queue strip:** across the top; glows amber while Vikram waits.
   - **Captions:** the current caption in the speaker's colour, plus a
     transcript of recent lines.
   - **Room diagram:** shows the speaker's seat lighting up.
   - **Virtual stole:** a stole outline whose zones pulse exactly when and
     where the real stole would. Used for demos, training and when no stole
     is connected.
   - **Switches:** mode (Lecture / Seminar / Practicum) and speech language
     (English / हिन्दी).
2. **Stole panel.**
   - Scan and pair; battery and firmware status.
   - A test button per zone, intensity sliders, mirror left/right and do not
     disturb.
   - A five-minute **"Learn the taps"** tutorial that plays each pattern and
     says what it means.
3. **Seat setup.** The room diagram with drag-and-drop voices, saved rooms,
   and "start with last layout".
4. **Review.**
   - A timeline with lanes for voices, cues, tone estimates and queue
     moments, and the transcript with tone notes.
   - **"How accurate is this?"**, with the model's real numbers and limits.
   - A consent checkbox before saving; export as web page, text, VTT, SRT or
     JSON.
5. **Settings.**
   - Your name (shown on the queue strip), caption size and theme.
   - Which cues are on in which modes.
   - Tone estimates in review (on by default) and live (off by default).
   - Microphone choice and the privacy explanation.
6. **Demo mode.** A scripted seminar and a scripted practicum role-play that
   drive the captions, voices, room diagram and virtual stole with no
   microphone, for filming the competition video. Label scripted estimates as
   scripted.

**Keyboard:**
- `Q`: queue on/off
- `S`: start/pause
- `M`: "what did I miss" (last 30 s)
- `1`–`4`: assign the current voice to L / R / B / F

---

## 9. Firmware

Write the firmware in `firmware/kandha/` using Arduino-ESP32 core 3.x or
ESP-IDF. It needs:

- a pin map and the parts list;
- the pattern table generated from the shared JSON;
- the §5 Bluetooth service;
- touch pads with tap, double and long-press gestures;
- battery reporting;
- a serial test console.

Add a CI job that compiles it. Write flashing instructions for someone who
has never used an ESP32.

---

## 10. Tests and verification

- **Existing tests:** all must still pass.
- **New unit tests:** `npm test` and `pytest` coverage for the scheduler,
  seat map, protocol encoding and decoding, bridge reconnects (mock `bleak`),
  pad gestures, virtual-stole parity with the real protocol, and mode rules.
- **End to end:** extend `scripts/verify_sanket.py` or add
  `scripts/verify_kandha.py`. Use a real Chromium or QtWebEngine with a fake
  microphone playing the LibriSpeech fixtures as turns (A B A B), Whisper
  stubbed, and the mock stole. Assert that:
  - the correct zones fire in the correct order;
  - latency is within budget;
  - there are no cue storms (outside speaker changes, at most about one tap
    every 1.5 s);
  - queue presses light the strip and are saved with the session.
- **Tap budget:** over the four-minute natural-speech fixtures, measure taps
  per minute in each mode. The target is ≤ 6 per minute in Seminar mode,
  excluding speaker changes. Report the number.
- **Accessibility audit:** keyboard, focus, contrast and screen-reader labels
  on every screen.
- **Honesty:** every number in the docs must come from a test or measurement
  you ran, with simulated parts clearly marked as simulated.

---

## 11. The downloadable file (the main deliverable)

Produce an installer someone can download and run.

- **Windows (primary).** Extend the existing PyInstaller spec, installer
  scripts and GitHub Actions to produce **`Kandha-Setup-<version>.exe`** and a
  portable **`Kandha-<version>-windows.zip`**.
  - Contents: the Kandha window, QtWebEngine resources, `bleak` with its WinRT
    backend, the tone model, and the stole firmware binary with flashing
    instructions.
  - It adds a Start-menu entry called "Kandha" and works fully offline after
    the one-time Whisper model setup that Audial already does.
- **If you are not running on Windows,** build the Windows installer through
  the GitHub Actions workflow and tell me where to download the artifact.
  Also build and test a portable build for the OS you are on (for example
  `Kandha-<version>-linux.tar.gz` or a macOS `.app` zip), if it doesn't
  destabilise the Windows build.
- **Release flow:** tagging `kandha-v<version>` publishes the installer as a
  GitHub release asset, following the repository's existing release gating.
- **Checksums:** publish SHA-256 checksums next to every file.

---

## 12. Non-negotiables

- **Privacy:** audio never leaves the computer. No telemetry. Recordings are
  never stored, and transcripts are saved only with consent.
- **Tone is a hint, not a fact.** Estimates describe how a voice sounded
  compared with that person's usual voice, learned from acted speech. Never
  present them as feelings, diagnoses or truth. Never name a category below
  80% confidence or before a person has been heard about four times.
- **Captions never stop because of the stole.** A disconnected stole, a flat
  battery or a Bluetooth failure must not affect captions.
- **Room awareness:** remind the user that people in the room should know live
  captions are on. Saving practicum transcripts with real clients needs
  supervisor and ethics approval.
- **Licences:** keep every existing licence and notice, and add notices for
  new dependencies (`bleak` is MIT; check QtWebEngine/Chromium terms for the
  packaged build).

---

## 13. Order of work

1. Read §2's files and record the test baseline.
2. Write `docs/kandha/DESIGN.md` and decision records in
   `docs/kandha/decisions/`. The design doc covers the architecture diagram,
   screens, tap language, protocol, seat map, data flows, risks and test plan.
   Continue straight on; don't wait for approval unless a decision can't be
   undone.
3. Build in vertical slices, each ending with passing tests and a commit:
   1. pattern table, HapticScheduler and SeatMap;
   2. virtual stole;
   3. StoleBridge with a mock device;
   4. Kandha window and UI, with the band removed;
   5. firmware;
   6. end-to-end verification;
   7. installers and CI.
4. Write the docs:
   - update `docs/sanket.md` to point to Kandha;
   - add `docs/kandha/USER_GUIDE.md` (wearing, charging, learning the taps,
     washing);
   - update `docs/architecture.md`, `README.md`, `LICENSE_NOTICES.md` and the
     release notes;
   - add a 90-second demo script for the competition video using demo mode
     and the virtual stole.
5. Push a branch and open a pull request against `main`.

**Finish with a summary** covering:
- what was built;
- where to download the installer;
- what was measured and what was simulated;
- what still needs real-world testing: a physical stole, Indian English and
  Hindi speakers, real seminars, and user testing of the tap language with
  deaf students.
