# Kandha design

Kandha (कंधा, "shoulder") is a downloadable laptop app for deaf students who lip-read, paired
with the **Kandha Stole**, a haptic scarf that taps the shoulder on the side of whoever is
speaking. It replaces Sanket as the product and reuses Sanket's voice engine, Audial-AI's
local Whisper captions, sessions and exports. This document is the design of record; the
decision records in [decisions/](decisions/) explain each real choice. Numbers in this
document that come from a measurement say so and point at the record under
[validation/](validation/); everything else is a design target.

Built for Hackcessible India 2026 (Vikram's challenge).

## 1. The rule behind every decision

Vikram's eyes stay on faces. Anything that makes him look down at a screen costs him the lips
he is reading. So:

- information that needs no looking goes to the stole as a tap;
- the laptop screen is for captions he chooses to glance at and for review afterwards;
- the stole is quiet by default: a constant buzz was measured to be stressful in research on
  head-worn directional haptics with several talkers, so Kandha taps for changes, not states.

## 2. Architecture

```
┌──────────── Kandha window (PySide6 + QWebEngineView) ────────────┐
│  Kandha UI  browser/kandha/  (HTML/JS, CSP-safe, no inline code) │
│   • microphone → AudioWorklet → engine.js (voices, cues, tone)    │
│   • engine events → kandha-intents.js → POST /api/kandha/intents  │
│   • audio packets → /api/audio → Audial engine → Whisper captions │
│   • SSE /api/kandha/stream → virtual stole, pads, status, seats   │
└──────────────┬────────────────────────────────────────────────────┘
               │ loopback HTTP (BrowserService: sessions, voice events, exports)
┌──────────────▼──────────── Python (same Audial process) ─────────┐
│  app/kandha/service.py   KandhaService: glue, settings, queue     │
│  app/kandha/scheduler.py HapticScheduler: priorities, limits,     │
│                          modes, stale drop, pre-emption (pure)    │
│  app/kandha/seatmap.py   SeatMap: voice → zone, rooms, SeatSource │
│  app/kandha/protocol.py  v1 byte encoding/decoding, UUIDs         │
│  app/kandha/patterns.py  pattern table + PatternPlayer simulation │
│  app/kandha/virtual.py   VirtualStole: same bytes, same timing    │
│  app/kandha/bridge.py    StoleBridge: bleak, reconnect, status,   │
│                          pads, paired-device allowlist; MockStole │
└──────────────┬────────────────────────────────────────────────────┘
               │ Bluetooth LE (section 6)
          ┌────▼─────┐
          │  Kandha  │  firmware/kandha/  (Arduino-ESP32 core 3.x, ESP32-S3)
          │  Stole   │
          └──────────┘
```

Why this shape (see [decisions/0001-web-view-ui.md](decisions/0001-web-view-ui.md) and
[0002-scheduler-in-python.md](decisions/0002-scheduler-in-python.md)):

- **Reuse.** `browser/sanket/engine.js`, `tone.js` and `captions.js` are kept unchanged and
  keep their tests. Local Whisper, sessions and exports are Audial's existing code.
- **No Web Bluetooth.** QtWebEngine has none; Python `bleak` works on Windows (WinRT), macOS
  (CoreBluetooth) and Linux (BlueZ).
- **One process.** The Kandha window, the loopback service and the Bluetooth bridge run in
  the Audial process that PyInstaller already packages.
- **One scheduler.** The real stole and the virtual stole receive the same five bytes from the
  same scheduler, so what the screen shows is what the shoulders feel.

### 2.1 Processes, threads and clocks

| Where | What runs | Clock |
|---|---|---|
| Page (QtWebEngine or a Chrome tab) | AudioWorklet tap at the context's sample rate; `engine.js` (32 ms frames, 16 ms hop at 16 kHz); `kandha-intents.js`; captions UI | audio time: seconds since the first captured sample (the clock Whisper captions use) |
| Python, HTTP handler threads | `/api/kandha/*` requests; the scheduler runs inside the request that submitted the intent and on a 20 ms ticker thread for deferred commands | `time.monotonic()` for scheduling; intents also carry their audio time for the session record |
| Python, bridge thread | an asyncio loop owned by `StoleBridge`: scan, connect, writes, notifications, reconnect | `time.monotonic()` |
| Python, Audial engine | Whisper on uploaded packets (unchanged) | audio time |
| Stole | pattern engine at 1 ms resolution, touch polling at 20 ms | `millis()` |

Haptics never block captions: the scheduler and bridge are separate from the Audial engine,
every bridge call is bounded, and a failure in either only changes which device plays the tap
(the virtual stole on screen is always there).

### 2.2 Data flows

**Speaker decision → shoulder.** `engine.js` emits `speaker` 0.64–1.4 s after speech starts
(unchanged). `kandha-intents.js` applies the back-channel hold (section 7.3), then posts
`{kind:'speaker', voice, new, t, sent}` to `/api/kandha/intents`. `KandhaService` resolves the
voice to a zone through `SeatMap`, `HapticScheduler.submit()` returns the command to play now,
`KandhaService` writes it to the stole (if connected) and to the `VirtualStole`, and the HTTP
response carries the command back so the page pulses the on-screen stole immediately and files
a `haptic` event in the session timeline.

**Tone cue → collarbone.** `cue` events (`drop`, `rise`, `hesitation`, `silence`) follow the
same path with priority `cue` (or `silence`). The scheduler enforces the mode, the per-cue
switches and the rate limits.

**Pad → screen.** The stole notifies `INPUT` → `StoleBridge` decodes → `KandhaService` checks
the device is the paired one → `SeatMap.on_pad()` (assignment window) or queue toggle →
published on the SSE stream → the page lights the strip and records a `queue` or `seat`
event with its own audio time.

**Captions.** Unchanged: the page uploads 2 s WAV packets to `/api/audio`; captions return on
`/api/events` with start/end times; `CaptionAssembler.timed()` gives each word the voice
speaking at that moment.

**Review and saving.** The page builds the review from its own timeline (lines, cues, tones,
queue, haptic, seat events). Saving is gated by the consent checkbox; the page then posts the
voice events to `/api/voice-events` (as the companion does) and saves through
`/api/kandha/session/save` (which requires `consent: true`) and `/api/export?format=…`.

### 2.3 Privacy

Audio is captured in the page and uploaded only to `127.0.0.1`. Nothing is recorded; the
engine keeps short running averages of voice features in memory. No telemetry. Transcripts
are saved only after the consent checkbox. The Bluetooth link carries five-byte tap commands,
pad presses, battery and configuration, never audio or text. The companion keeps
`script-src 'self'`; `browser/kandha/` adds `style-src 'unsafe-inline'` only because voice
colours are inline custom properties, exactly as `/sanket/` did.

## 3. Modes

| Mode | Voices | Seat taps | Tone cues | Floor open | Queue |
|---|---|---|---|---|---|
| Lecture | one (engine `singleSpeaker`) | off | off | on | on |
| Seminar | up to 6 | on | optional, off by default | on | on |
| Practicum | two; the partner defaults to `F` | on | on | on | on |
| Do not disturb | as before | off | off | off | on |

Modes come from `browser/sanket/kandha-patterns.json` (`modes`), so the scheduler, the page and
the tests agree.

## 4. Screens

All screens: large type, Atkinson Hyperlegible bundled in `browser/kandha/fonts/` (OFL 1.1),
dark and light themes, visible focus on every control, WCAG 2.1 AA contrast, usable at
1280 × 720 and keyboard-reachable. Hindi text uses the system Devanagari font.

1. **Live view** (`#live`). Queue strip across the top (amber glow while waiting); the current
   caption in the speaker's colour with a tone chip when live estimates are on; the recent
   transcript; the room diagram (Vikram at the bottom, seats L/R/B/F) with the active seat
   lit; the virtual stole (outline with four zones that pulse exactly when and where the real
   stole would, plus four clickable pads); switches for mode (Lecture / Seminar / Practicum),
   speech language (English / हिन्दी) and do-not-disturb; Start/Pause, "What did I miss",
   Review and "I want to speak".
2. **Stole panel** (`#stole`). Scan and pair, forget, battery and firmware, connection state
   and last error; a test button per zone; per-zone intensity sliders; mirror left/right;
   do-not-disturb; "Learn the taps", a five-minute tutorial that plays each pattern on the
   stole (real or virtual) and says what it means, with Repeat and Next.
3. **Seat setup** (`#seats`). The room diagram with drag-and-drop voice chips (and keyboard:
   select a chip, press 1–4), saved rooms (name, save, load, delete) and "start with last
   layout".
4. **Review** (`#review`). Timeline lanes: voices, cues, tone estimates, queue moments, taps,
   seat changes; transcript with tone notes; "How accurate is this?" with the model's measured
   numbers and limits; consent checkbox; export as web page, text, VTT, SRT or JSON.
5. **Settings** (`#settings`). Name, caption size, theme; which cues are on in which mode;
   tone estimates in review (on) and live (off); microphone choice; privacy explanation; the
   room-awareness reminder.
6. **Demo mode.** A scripted seminar and a scripted practicum role-play drive captions,
   voices, room diagram and the stole through the real scheduler with no microphone. Scripted
   tone estimates are labelled "scripted".

Keyboard: `Q` queue, `S` start/pause, `M` what did I miss (last 30 s), `1`–`4` assign the
current voice to L/R/B/F, `N` new voice, `Esc` closes dialogs. Screens are tabs reachable with
the arrow keys.

## 5. The Kandha Stole (reference hardware)

A cotton or khadi stole worn over both shoulders. The electronics sit in a zipped inner channel
and come out for washing. Gender-neutral; ordinary clothing, not a medical device.

| Zone | Where | Motors | Used for |
|---|---|---|---|
| `L` | top of the left shoulder | 2 coin ERM, ~3 cm apart | speaker on the left |
| `R` | top of the right shoulder | 2 | speaker on the right |
| `B` | back of the neck | 1 | speaker behind |
| `F` | front, collarbone/sternum | 1 | tone cues; speaker in front |
| `LR` | both shoulders | L + R | squeeze: queue noted, floor open |

Inputs: four textile touch pads at the right-hand end, each with a different stitched texture
(`PAD_L` one ridge, `PAD_R` two ridges, `PAD_B` a cross, `PAD_Q` a raised dot).

### 5.1 Parts list (reference build)

Prices are approximate Indian retail prices in 2026 for one unit, not quotations.

| Part | Qty | ₹ each | ₹ | Notes |
|---|---|---|---|---|
| ESP32-S3 mini board (e.g. ESP32-S3 SuperMini or Seeed XIAO ESP32S3) | 1 | 450–900 | 450–900 | native capacitive touch, BLE 5 |
| 10 mm coin ERM vibration motor, 3 V | 6 | 40 | 240 | 2 per shoulder, 1 back, 1 front |
| Logic-level N-MOSFET, SOT-23 (AO3400 or IRLML2502) | 4 | 15 | 60 | one per zone (decision 0003) |
| Schottky flyback diode 1N5819 | 4 | 5 | 20 | across each motor group |
| Resistors: 100 Ω gate × 4, 10 kΩ pull-down × 4, 100 kΩ × 2 (battery divider), 10 kΩ × 1 | 11 | 1 | 11 | |
| 47 µF electrolytic across the motor supply | 1 | 5 | 5 | |
| TP4056 USB-C charger module with DW01 protection | 1 | 60 | 60 | |
| 3.7 V LiPo 800 mAh (slim, with protection) | 1 | 350 | 350 | 600–1000 mAh acceptable |
| Slide switch (soft power) | 1 | 15 | 15 | |
| Conductive fabric or thread for four touch pads | 1 | 200 | 200 | |
| 30 AWG silicone wire, flat ribbon | 3 m | 50/m | 150 | |
| Silicone motor pockets (cast from a small mould) | 6 | 15 | 90 | |
| Perfboard or small carrier PCB | 1 | 60 | 60 | |
| Khadi/cotton stole with zipped inner channel | 1 | 450 | 450 | |
| **Total** | | | **≈ ₹2,200–2,650** | |

Electronics weight estimate (datasheet masses): board 5 g, LiPo 800 mAh 16 g, charger 2 g,
6 motors 7 g, MOSFET board 6 g, wiring and connectors 15 g → **≈ 51 g**, under the 120 g target.
This is an estimate from datasheets, not a weighed prototype.

### 5.2 Battery estimate (duty-cycle maths)

Assumptions from datasheets and the pattern table (not measured on hardware):

- ESP32-S3 with a BLE connection at a 30 ms interval, modem sleep between events: **≈ 25 mA**
  average. Without any sleep the same board draws ≈ 80 mA.
- One coin ERM at 3 V: **≈ 75 mA**. A shoulder zone has two motors → 150 mA while on.
- Seminar mode at the budget ceiling: 6 cues/min on `F` (one motor, average pattern 450 ms on,
  at mean level ≈ 60 %) plus 10 speaker taps/min (two motors, 120 ms): motor duty =
  (6 × 0.45 × 0.6 × 75 mA + 10 × 0.12 × 150 mA) / 60 s ≈ **4.4 mA** average.
- Touch polling and the status LED: ≈ 1 mA.

Average draw ≈ 25 + 4.4 + 1 ≈ **30 mA**. An 8-hour day needs 240 mAh; with 80 % usable capacity
a **600 mAh** cell gives ≈ 16 h and an **800 mAh** cell ≈ 21 h. If modem sleep is disabled
(80 mA baseline), 8 h needs ≈ 680 mAh usable, so the 800 mAh cell still covers a college day
with little margin; 1000 mAh is the safe choice for that firmware configuration.

### 5.3 Pin map (ESP32-S3, generic DevKit or SuperMini)

| Function | GPIO | Notes |
|---|---|---|
| `PAD_L` | 1 | touch T1 |
| `PAD_R` | 2 | touch T2 |
| `PAD_B` | 3 | touch T3 |
| `PAD_Q` | 4 | touch T4 |
| `MOTOR_L` | 5 | LEDC PWM 20 kHz, 8-bit, gate of Q1 |
| `MOTOR_R` | 6 | gate of Q2 |
| `MOTOR_B` | 7 | gate of Q3 |
| `MOTOR_F` | 8 | gate of Q4 |
| `BATTERY_SENSE` | 9 | ADC1 through 100 kΩ / 100 kΩ divider |
| `CHARGING_SENSE` | 10 | TP4056 CHRG, active low, 10 kΩ pull-up |
| `STATUS_LED` | 48 | on-board LED where present |

Washing: unzip the channel, lift out the carrier with the battery, motors and pads (the pads
are sewn to a removable strip), wash the stole, dry flat, slide the carrier back.

## 6. Bluetooth protocol v1

Full details and the byte layouts are in [PROTOCOL.md](PROTOCOL.md); the authoritative UUIDs
and pattern ids are in `browser/sanket/kandha-patterns.json`.

- Service UUID `2ad2fdad-b9e2-4025-af4d-b35e6f13c100` (generated for Kandha; the retired band's
  `a7c2f3e0-…0001` is never used). Characteristics `…c101` HAPTIC (write without response),
  `…c102` PATTERNS (write), `…c103` INPUT (notify), `…c104` STATUS (read + notify),
  `…c105` CONFIG (read + write).
- Devices advertise as `KandhaStole-XXXX` (last four hex digits of the BLE address).
- Little-endian everywhere.
- **Pairing**: a user-initiated scan filtered by the service UUID or name prefix; the chosen
  address is remembered in `<data>/kandha/stole.json`; `INPUT` from any other address is
  ignored; reconnects go only to the remembered address.
- **Reconnect**: exponential backoff 1, 2, 4, 8, 16, 30, 30 … s. While disconnected captions
  keep running; haptics go to the virtual stole and the screen flashes the zone.
- **Latency budget**: engine decision → motor start ≤ 150 ms inside the app, ≤ 300 ms including
  Bluetooth. Measured with the mock device in [validation/](validation/) (the Bluetooth part is
  a budget, not a measurement, until there is hardware).

## 7. The tap language and the scheduler

The patterns are in `browser/sanket/kandha-patterns.json` and summarised in section 7.1. The
scheduler rules are pure code in `app/kandha/scheduler.py` with unit tests.

### 7.1 Patterns

| Meaning | Zone | Pattern |
|---|---|---|
| A known voice starts or takes over | that voice's seat | one firm 120 ms tap |
| A new voice | `F` | two 60 ms taps |
| Voice softened (`drop`) | `F` | one 700 ms swell |
| Voice rose (`rise`) | `F` | three 80 ms taps |
| Hesitation | `F` | five 40 ms flutters |
| Long silence / floor open | `LR` | two gentle 60 ms ticks |
| Queue noted (`PAD_Q` or `Q`) | `LR` | one 180 ms squeeze |
| Waiting a long time (default 60 s) | `LR` | one 260 ms squeeze, at most once a minute |
| Low battery (20 %) | `B` | three 300 ms pulses, once per charge |
| Voice without a seat | `F` | one 120 ms tap |

### 7.2 Scheduler rules

- **Priority**: speaker change > queue feedback > tone cue > silence. A speaker tap always
  pre-empts a cue in progress (a new HAPTIC command replaces the running pattern on the stole
  and in the virtual stole). A cue arriving during a speaker tap waits until the tap ends.
- **Stale drop**: any intent older than 1.5 s when it would play is dropped, never played late.
- **Rate limits**: at most one tone cue every 3 s and the same cue kind at most once every 8 s
  (the same cooldowns as `engine.js`). Speaker taps are not rate limited beyond the
  back-channel hold, but the same voice is not tapped twice in a row.
- **Modes**: section 3. Per-cue switches and "tone cues in Seminar" come from settings.
- **Unmapped voice**: a known voice without a seat gets one tap on `F`; a new voice gets the
  two-tap new-voice pattern on `F` and opens the six-second seat-assignment window.
- **Mirror** swaps L and R; per-zone intensity scales are applied by the device layer (real
  stole: CONFIG characteristic; virtual stole: the same arithmetic in Python).

### 7.3 Back-channel hold

The engine already waits for 0.64 s of speech before an early decision, and a short utterance
(0.4–0.64 s) is decided only after the pause that follows it. `kandha-intents.js` taps only
when the turn has lasted `min_turn_s` = 0.6 s: for a decision made while the person is still
speaking that is already true; for a decision made after a pause, the turn length is
`speech_end − turn_start`, so a 0.3 s "mm-hm" never taps. The threshold was chosen with the
LibriSpeech fixtures (decision 0004 and [validation/backchannel.json](validation/backchannel.json)).

After a long silence the first `speech-start` schedules a "voice starts" tap for the current
voice 0.6 s later; if the engine changes the speaker before then, the new voice's tap replaces
it, so there is never a double tap.

## 8. The seat map

`SeatMap` maps session-only voice ids to zones `L`, `R`, `B`, `F` or none.

- **Assigning a new voice.** The new-voice pattern opens a 6 s window; a tap on `PAD_L`,
  `PAD_R` or `PAD_B` during the window assigns that voice. Touching nothing leaves it unmapped.
- **Reassigning.** A double-tap on a pad reassigns the voice speaking now. Keys `1`–`4` and
  drag-and-drop on the room diagram do the same from the screen.
- **Saved rooms.** Layouts are saved per room name in `<data>/kandha/rooms.json` as zone →
  slot order ("the first voice goes left, the second right"), because voices are session-only.
  "Start with last layout" pre-assigns voice slots in order of appearance. No cross-session
  voice identity is attempted.
- **Practicum default**: the second voice defaults to `F`.
- **`SeatSource`**: an interface (`angles() -> {voice: degrees}`) for a future microphone array.
  `ManualSeatSource` is the only implementation; the angle-to-zone mapping is defined
  (front ±45°, right 45–135°, behind 135–225°, left 225–315°) so an array can plug in.

## 9. Risks and how they are handled

| Risk | Handling |
|---|---|
| Voice engine splits one person into two colours | browser noise suppression off while tracking (measured in Sanket), "Join voices" on screen, no tap for the same voice twice in a row |
| Cue storms stress the wearer | priorities, 3 s / 8 s rate limits, stale drop, modes with cues off by default, tap budget measured and reported |
| Bluetooth drops | captions unaffected; virtual stole and on-screen flash; backoff reconnect; paired-address allowlist |
| Flat battery | low-battery pulses once at 20 %; stole status on screen |
| Microphone differences (built-in vs USB) | the engine adapts its noise floor; microphone choice in settings; both tested with the fake-microphone harness only (real devices need user testing) |
| Tone estimates read as facts | estimates are relative to the person, named only at ≥ 0.80 after four utterances, labelled as hints, off live by default |
| Indian English / Hindi speakers | nothing validated; said in the UI and docs |
| QtWebEngine microphone permission | granted per origin with the Qt 6.8 permission API; a Chrome tab remains an alternative |

## 10. Test plan

| Layer | How | Where |
|---|---|---|
| Pattern table | JSON schema and firmware header generation round-trip | `tests/test_kandha_patterns.py`, `tests/kandha.test.js` |
| Protocol | encode/decode every characteristic, bounds, little-endian | `tests/test_kandha_protocol.py` |
| Scheduler | priorities, stale drop, rate limits, pre-emption, modes, mirror, unmapped | `tests/test_kandha_scheduler.py` |
| Seat map | window, double-tap reassign, rooms persistence, practicum default, angle → zone | `tests/test_kandha_seatmap.py` |
| Bridge | mock bleak: scan filter, pair, remembered device, reconnect backoff, ignored INPUT from strangers, STATUS, low battery | `tests/test_kandha_bridge.py` |
| Virtual stole parity | the same bytes produce the same zone timeline as the firmware simulation | `tests/test_kandha_virtual.py` |
| Intents | back-channel hold on LibriSpeech turns, resume after silence, no double taps | `tests/kandha.test.js` |
| Service and HTTP | `/api/kandha/*` ownership, SSE, consent gate, settings | `tests/test_kandha_service.py` |
| End to end | real Chromium, fake microphone A B A B, Whisper stubbed, mock stole: zones in order, latency, no cue storms, queue saved | `scripts/verify_kandha.py` |
| Tap budget | taps per minute per mode over the four-minute natural-speech fixtures | `scripts/kandha_tap_budget.py` |
| Accessibility | keyboard reach, visible focus, contrast, names, 1280 × 720 | `scripts/audit_kandha_a11y.py` |
| Firmware | compiles in CI with arduino-cli | `.github/workflows/firmware.yml` |

## 11. Out of scope for this version

Cross-session voice identity, a microphone array, on-device English↔Hindi translation in the
Kandha window (decision 0007), DRV2605L drivers (decision 0003), and any claim about Indian
English, Hindi or real seminars: those need a physical stole and user testing with deaf students.
