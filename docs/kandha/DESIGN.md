# Kandha design

Kandha (कंधा, "shoulder") is a downloadable laptop app for deaf students who lip-read, paired
with the **Kandha Stole**, a haptic scarf that taps the shoulder on the side of whoever is
speaking. It replaces Sanket as the product and reuses Sanket's voice engine, Audial-AI's
local Whisper captions, sessions and exports. This document is the design of record; the
decision records in [decisions/](decisions/) explain each real choice. Numbers in this
document that come from a measurement say so and point at the record under
[validation/](validation/); everything else is a design target.

Built for Hackcessible India 2026 (Vikram's challenge).

> **Prototype status.** Kandha runs entirely without hardware: the virtual stole shows every
> tap and a simulated stole demonstrates pairing, battery and reconnection (decision 0011).
> The physical stole, its firmware and the Bluetooth link are designed, written and tested
> against mocks, but nothing has run on hardware. Measured results are summarised in
> [VALIDATION.md](VALIDATION.md).

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
               │ loopback HTTP (BrowserService: the session record, exports)
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
  (CoreBluetooth) and Linux (BlueZ). `bleak` is pinned in `requirements.txt`, and the Kandha
  build stops if it or its platform backend is missing (decision 0008).
- **One process.** The Kandha window, the loopback service and the Bluetooth bridge run in
  the Audial process that PyInstaller already packages.
- **One scheduler.** The real stole and the virtual stole receive the same five bytes from the
  same scheduler, so what the screen shows is what the shoulders feel: the same zones and steps
  at the same moments. Levels differ only where the motor needs it: the firmware raises any
  non-zero duty below 60/255 to 60 and gives a motor starting from rest 15 ms at full duty
  (section 7.2), and the screen draws the level before that floor and kick.

### 2.1 Processes, threads and clocks

| Where | What runs | Clock |
|---|---|---|
| Page (QtWebEngine or a Chrome tab) | AudioWorklet tap at the context's sample rate; `engine.js` (32 ms frames, 16 ms hop at 16 kHz); `kandha-intents.js`; captions UI | audio time: seconds since the first captured sample (the clock Whisper captions use) |
| Python, HTTP handler threads | `/api/kandha/*` requests; the scheduler runs inside the request that submitted the intent and on a 20 ms ticker thread for deferred commands and the end of the seat window | `time.monotonic()` for scheduling; intents carry their age on the page (section 2.2) and their audio time for the session record |
| Python, bridge thread | an asyncio loop owned by `StoleBridge`: scan, connect, writes, notifications, reconnect | `time.monotonic()` |
| Python, Audial engine | Whisper on uploaded packets (unchanged) | audio time |
| Stole | pattern engine at 1 ms resolution, touch polling at 20 ms | `millis()` |

Haptics never block captions: the scheduler and bridge are separate from the Audial engine,
every bridge call is bounded, and a failure in either only changes which device plays the tap
(the virtual stole on screen is always there).

### 2.2 Data flows

**Speaker decision → shoulder.** `engine.js` emits `speaker` 0.64–1.4 s after speech starts
(unchanged). `kandha-intents.js` applies the back-channel hold and the rule for the first turn
after a long silence (section 7.3), and the page posts the intents in batches to
`/api/kandha/intents`. Each intent is `{kind, voice, cue, t, new, demo, age_ms, sent, page}`:

- `kind` is `speaker`, `new_voice`, `voice_resumes`, `cue` or `silence`; `voice` is a session
  voice number from 1 to 1,000,000; `t` is the audio time;
- `age_ms` (0–600000) is how old the intent is when the page sends it, on the page's steady
  clock (`performance.now()`), so latency counts from the moment it was raised;
- `sent` is the page's `Date.now()` at that moment, and `page` is the window's tag (1–64
  characters, the same tag it sends to `/api/kandha/session/new`); the service uses them only
  to estimate the batch's trip (section 7.2, "How old an intent is").

`KandhaService` dates the intent `age_ms` plus that trip before its arrival, resolves the voice
to a zone through `SeatMap`, `HapticScheduler.submit()` returns the command to play now,
`KandhaService` writes it to the stole (if connected) and to the `VirtualStole`, and the HTTP
response carries the command back, as the virtual stole played it (section 7.2, mirror and
intensity), so the page pulses the on-screen stole immediately and files a `haptic` event in
the session timeline. When the service cannot be reached, the page flashes the zone of every
speaker, new-voice and voice-starts tap itself.

**Tone cue → collarbone.** `cue` events (`drop`, `rise`, `hesitation`, `silence`) follow the
same path with priority `cue` (or `silence`). The scheduler enforces the mode, the per-cue
switches and the rate limits.

**Pad → screen.** The stole notifies `INPUT` → `StoleBridge` decodes → `KandhaService` checks
the device is the paired one → `SeatMap.on_pad()` (assignment window) or queue toggle →
published on the SSE stream → the page lights the strip and records a `queue` or `seat`
event with its own audio time. The on-screen pads send the same gestures with the same timing
(PROTOCOL.md, INPUT).

**Captions.** When Audial-AI reports the Whisper model installed (the page asks again at every
Start), the page uploads 2 s WAV packets to `/api/audio`; captions return on `/api/events` with
start/end times; `CaptionAssembler.timed()` gives each word the voice speaking at that moment.
Section 2.3 covers what happens without Whisper.

**Review and saving.** The page builds the review from its own timeline (lines, cues, tones,
queue, haptic, seat events) and keeps Audial-AI's record of the session in step:

- Each session, live or demo, starts with `POST /api/kandha/session/new {page}`. It returns
  `session_id` (the saved file's name) and publishes a `session` event naming the window. The
  record swap and that event happen under one lock, so another open Kandha window learns at once
  that its record was replaced. The previous unsaved record is dropped.
- Within about 400 ms the page sends every caption line it shows (Whisper, browser captions or a demo)
  and its voice, cue, tone, queue, haptic and seat events to
  `POST /api/kandha/session/events {session_id, events, captions}`, at most 200 of each per
  batch, whatever the caption source. A caption is `{start, end, text, voice}` in audio seconds
  (text up to 4000 characters); a local Whisper line also names its engine caption
  (`whisper: {capture, start, end}`). A stale or missing id gets 409. This record stays in
  memory.
- Saving is gated by the consent checkbox: `POST /api/kandha/session/save {consent: true,
  session_id, title}` answers 403 without consent, 409 for a stale id and 400 when there is
  nothing to save, and otherwise writes `<data>/sessions/<session_id>.json`. Demos are titled
  "Kandha demo: …"; their scripted tone estimates are not stored.
- VTT, SRT and JSON come from `GET /api/export?format=…&session=<session_id>` (409 for a blank
  or stale id, 400 for an empty record), so they no longer need Whisper. Without `session`,
  `/api/export` still exports the companion's own last capture.
- The Save and export buttons stay off, with the reason under them, until there is something to
  save and consent is ticked. A window whose record was replaced turns off Save, VTT, SRT and
  JSON and says why there and in a live-region toast; its web page and text exports still work.

### 2.3 Privacy

Audio is captured in the page and uploaded only to `127.0.0.1`. Captions come from Whisper on
this computer whenever Audial-AI reports it installed; the page asks again at every Start. The
page never falls back to the browser's built-in speech recognition
(`browser/sanket/recognizer.js`) on its own:

- It is an opt-in in Settings › Privacy, off by default, whose label says the browser may send
  the audio to its maker's servers ("Let the browser's own speech service caption when Whisper is
  not installed"). It is stored per device as `browserCaptions` in the page settings.
- With it on, in a Chrome or Edge tab without Whisper, the status line says *browser captions*.
  Turning it off stops the browser's service at once, also while listening.
- Without Whisper and without the opt-in there are no captions. The status line reads
  "Listening · … · voices and taps only", the page says why and how to get the model, and voice
  colours and stole taps keep working.
- The Kandha window (QtWebEngine) has no such API, so the option is disabled there and captions
  are always local.

Nothing is recorded; the engine keeps short running averages of voice features in memory. No
telemetry. The session record the page sends to the service (section 2.2) stays in memory;
transcripts reach disk only through a consented save. The Kandha window's web view is off the
record: it keeps no cache, cookies or permission grants on disk, and its only file is the page's
own settings (`<data>/kandha/page-settings.json`: name, theme, caption size, microphone choice,
vocabulary, languages and similar, never audio or transcripts). It grants the microphone only to
the companion's exact origin (`http://127.0.0.1:<port>`), and the microphone opens only on Start.
The Bluetooth link carries five-byte tap commands, pad presses, battery and configuration, never
audio or text. The companion keeps `script-src 'self'`; `browser/kandha/` adds
`style-src 'unsafe-inline'` only because voice colours are inline custom properties, exactly as
`/sanket/` did.

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
   speech language (English / हिन्दी) and do-not-disturb; a dock with Start/Pause, "What did I
   miss", New voice, Demos and "I want to speak".
2. **Stole panel** (`#stole`). Scan and pair, forget, battery and firmware, connection state
   and last error; a test button per zone; per-zone intensity sliders; mirror left/right;
   do-not-disturb; "Learn the taps", a five-minute tutorial that plays each pattern on the
   stole (real or virtual) and says what it means, with Repeat and Next. With the simulated
   link (the default) the panel also offers *Simulate: out of range, battery 18 %, plug in,
   pad presses*.
3. **Seat setup** (`#seats`). The room diagram with drag-and-drop voice chips (and keyboard:
   select a chip, which then shows a tick and reports itself as pressed, and press 1–4; select
   it again to let go), saved rooms (name, save, load, delete) and "start with last layout".
   Keyboard focus is a separate ring, so focus and selection never look alike.
4. **Review** (`#review`). Timeline lanes: voices, cues, tone estimates, queue moments, taps,
   seat changes; transcript with tone notes; "How accurate is this?" with the model's measured
   numbers and limits; consent checkbox; Save to sessions and export as web page, text, VTT,
   SRT or JSON (section 2.2). The note under the buttons says why they are off.
5. **Settings** (`#settings`). Name, caption size, theme; which cues are on in which mode and
   when a silence counts as long; tone estimates in review (on) and live (off); microphone
   choice (remembered by its name as well as its id, because the id changes with every launch
   of the Kandha window and every new port); privacy explanation and the browser-captions
   opt-in (section 2.3); the room-awareness reminder.
6. **Demo mode.** A scripted seminar and a scripted practicum role-play drive captions,
   voices, room diagram and the stole through the real scheduler with no microphone. Scripted
   tone estimates are labelled "scripted". **Demos** in the dock opens a dialog with both
   demos at any time, also to switch or replay one (the welcome card offers them on first
   open). A demo pauses listening and clears the screen, and the dialog says what it would end;
   a demo that is switched or stopped carries nothing over into the next session.

Keyboard: `Q` queue, `S` start/pause, `M` what did I miss (last 30 s), `1`–`4` assign a voice to
L/R/B/F (the voice whose chip has keyboard focus, else the selected voice on the Seats screen,
else the voice speaking now), `N` new voice, `Esc` closes dialogs. Screens are tabs reachable
with the arrow keys. The Kandha window opens at 1280 × 760 (at least 1024 × 640).

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
  (6 × 0.45 × 0.6 × 75 mA + 10 × 0.12 × 150 mA) / 60 s = (121.5 + 180) / 60 ≈ **5.0 mA**
  average.
- Touch polling and the status LED: ≈ 1 mA.

Average draw ≈ 25 + 5.0 + 1 ≈ **31 mA**. An 8-hour day needs ≈ 250 mAh; with 80 % usable
capacity a **600 mAh** cell gives ≈ 15 h and an **800 mAh** cell ≈ 21 h. If modem sleep is
disabled (80 mA baseline, ≈ 86 mA in all), 8 h needs ≈ 690 mAh usable, more than the 640 mAh
an 800 mAh cell gives at 80 %: it lasts ≈ 7.4 h, about half an hour short of a college day.
A 1000 mAh cell (≈ 9.3 h) is the choice for that firmware configuration.

Charging (an estimate, not measured): TP4056 modules are commonly sold set to 1 A, which would
charge an 800 mAh cell in roughly 1–2 h (constant current, then a slower constant-voltage
finish). The module's programming resistor sets the current and should suit the chosen cell.

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
- Devices advertise as `Kandha-XXXX` (last four hex digits of the BLE address), the name the
  brief specifies; the simulated stole is `Kandha-SIM1`.
- Little-endian everywhere.
- **Pairing**: a user-initiated scan filtered by the service UUID or name prefix; the chosen
  address is remembered in `<data>/kandha/stole.json`; `INPUT` from any other address is
  ignored; reconnects go only to the remembered address.
- **Reconnect**: exponential backoff 1, 2, 4, 8, 16, 30, 30 … s. While disconnected captions
  keep running; haptics go to the virtual stole and the screen flashes the zone. Pressing Pair
  on the stole already connected keeps its one connection; Forget or pairing another stole
  abandons a connection attempt in progress, and reconnecting keeps working afterwards.
- **Duplicate filter**: the stole ignores a HAPTIC whose `seq` repeats the previous one within
  a connection and forgets it on every new connection, so the first command after a reconnect or
  an app restart always plays (the app's mock and simulated stoles do the same).
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

- **Priority**: speaker change and new voice (5) > voice starts again (`voice_resumes`, 4) >
  queue feedback (3) > tone cue (2) > silence (1); the stole test and stop are 9. A speaker
  tap always pre-empts a cue in progress (a new HAPTIC command replaces the running pattern on
  the stole and in the virtual stole). A cue arriving during a speaker tap waits until the tap
  ends.
- **One start, one seat tap**: a speaker or new-voice tap pre-empts a running voice-starts tap
  and drops a waiting one. A `voice_resumes` that arrives while a seat tap is playing, or while
  one is waiting that can still play, is dropped as `superseded`.
- **Stale drop**: any intent older than `stale_after_s` = 1.5 s when it would play is dropped,
  never played late (low battery, connected, test and stop never go stale). A waiting intent that will be older than that when the running pattern
  ends is dropped as soon as a newer intent would wait behind it, so it cannot keep the newer
  one out.
- **How old an intent is**: its `age_ms` on the page plus the batch's trip to the service. The
  trip comes from the batch's clock gap (the service clock at arrival minus the page's `sent`),
  compared only with the same page's last `CLOCK_SAMPLES` = 8 batches (kept for the
  `CLOCK_PAGES` = 8 pages heard from most recently; pages that send no tag share one history).
  The smallest of those gaps that another gap agrees with within `CLOCK_AGREE_MS` = 500 ms
  (the smallest gap while no two agree yet) is taken as the difference between the two clocks,
  and only delay beyond it counts. So a steady difference between the page's and the service's
  clocks never drops a tap, one odd `sent` or another page whose clock runs ahead cannot make
  this page's taps look late, and a batch held up on the way is still dropped. The first batch
  from a page has no trip measured; a page clock that falls behind mid-session can cost at most
  8 batches, one that jumps ahead none. The service clock is `time.time()` at start plus
  `time.monotonic()`, so it never steps. `app_latency_ms` in a haptic record is the intent's
  whole age when it was dispatched: page age, estimated trip and time in the scheduler.
- **Checked again on release**: a deferred intent is dropped as `mode` when its mode or
  do-not-disturb no longer allows it, and as `self` when its voice was marked "This is me" while
  it waited.
- **Rate limits**: at most one tone cue every 3 s and the same cue kind at most once every 8 s
  (the same cooldowns as `engine.js`). Speaker taps are not rate limited beyond the
  back-channel hold, but the same voice is not tapped twice in a row; `voice_resumes` is exempt
  from that rule, because after a long silence the voice tapped last may be the one starting
  again.
- **Modes**: section 3. Per-cue switches and "tone cues in Seminar" come from settings.
- **Unmapped voice**: a known voice without a seat gets one tap on `F`; a new voice gets the
  two-tap new-voice pattern on `F` and opens the six-second seat-assignment window.
- **Mirror and intensity**: mirror swaps L and R; per-zone intensity scales are applied by the
  device layer (real stole: CONFIG characteristic; virtual stole: the same arithmetic in
  Python). The haptic record the page draws, the Review lane and the saved session use what the
  virtual stole played from those same bytes: `zones`, `mask`, `intensity` and `duration_ms`
  after mirror and mute, `segments` `[{zone, start_ms, end_ms, level}]` with each zone's scale
  applied, and the scheduler's own zones as `command_zones`. The firmware then raises any
  non-zero duty below 60/255 to 60 (a coin ERM does not start below it) and runs a motor that
  starts from rest at full duty for its first 15 ms (PROTOCOL.md); the screen shows the level
  before that floor and kick.

### 7.3 Back-channel hold

The engine already waits for 0.64 s of speech before an early decision, and a short utterance
(0.4–0.64 s) is decided only after the pause that follows it. `kandha-intents.js` taps only
when the turn has lasted `min_turn_s` = 0.6 s: for a decision made while the person is still
speaking that is already true; for a decision made after a pause, the turn length is
`speech_end − turn_start`, so a 0.3 s "mm-hm" never taps. The threshold was chosen with the
LibriSpeech fixtures (decision 0004 and [validation/backchannel.json](validation/backchannel.json)).

**After a long silence the next real turn taps once.** The engine reports a speaker only when
it changes, so without this rule the same voice speaking again after a pause would get nothing.

- *When a silence is long.* When the engine's silence cue fires, or when the gap before a
  `speech-start` (plus one 16 ms engine frame) reaches the wearer's "A silence counts as long
  after" setting (3, 4, 5, 6, 8 or 10 s; default 4). The page passes that setting to
  `kandha-intents.js` at load, on every change and again after every engine silence cue, so the
  intents always use the page's value. The cue is rate-limited by the engine (8 s between cues
  of one kind, 3 s between any two) and can be switched off, so it is not the only trigger.
  (Without a page value, as in the Node studies, the setting is measured from the first silence
  cue and forgotten again when a later silence that long brings no cue and the cue limits do not
  explain why.)
- *Which tap.* If the engine names a speaker in that first turn (early, at its 40th speech
  frame, about 0.64 s; or finally, at its 90th, about 1.44 s), that decision is the only tap: a
  new voice gets the new-voice pattern on `F`, and a known voice is sent as `voice_resumes`, so
  the scheduler taps it even if it was the last voice tapped. If the engine keeps the same voice
  (it sends no event), the `voice_resumes` tap waits for the engine's final say: 96 counted
  speech frames (its 90 plus a 6-frame margin, `FINAL_MARGIN_FRAMES`, about 1.5 s into the
  turn), or, for a shorter turn, the pause of 0.25 s that ends it. Either way a different voice
  never gets the previous voice's seat first.
- *Short sounds.* A turn shorter than `min_turn_s` = 0.6 s after the silence (a cough, a chair,
  an "mm") taps nothing and does not use up the tap; it is recorded as suppressed with the
  reason `short-after-silence`. When speech returns so soon after such a burst that the engine
  keeps one segment, the tap waits for the engine's first chance to correct itself (its mid-turn
  recheck) plus the margin, or for the pause that ends the turn. If the voice the engine kept is
  one it made from that burst, the tap waits for its decision on the next segment, or for
  `REJUDGE_WAIT_SEC` = 1.0 s of quiet.
- *Page controls tap at once.* New voice (`N`) stamps its decision with the present moment,
  while the engine's own decisions are dated in the past, so a new-voice event that is not in
  the past is a press: it plays the front double tap and opens the 6 s seat window at once, even
  in a pause. "This person is speaking now", Join voices and the engine's first Lecture-mode
  decision follow the back-channel hold as before.

`scripts/kandha_backchannel_study.mjs` runs these cases over the LibriSpeech fixtures (a new
voice, a known other voice, the same voice, and short noise before the real turn) and checks
that each resume turn gets exactly one seat tap; its record is
[validation/backchannel.json](validation/backchannel.json).

## 8. The seat map

`SeatMap` maps session-only voice ids to zones `L`, `R`, `B`, `F` or none.

- **Assigning a new voice.** The new-voice pattern opens a 6 s window; a tap on `PAD_L`,
  `PAD_R` or `PAD_B` during the window assigns that voice. Touching nothing leaves it unmapped.
  When the window runs out unused, the service publishes a `seat` event with
  `action: 'window-closed'` and `pending: null` (and no `zone`), so every open page drops its
  "drop here" highlight; the page also clears it on its own timer when the window ends. Pad seat
  events and screen assignments carry `pending`: `null` once nobody waits, otherwise
  `{voice, until_s}`.
- **Reassigning.** A double-tap on a pad reassigns the voice speaking now. Keys `1`–`4` and
  drag-and-drop on the room diagram do the same from the screen (section 4 for which voice a
  key moves).
- **Joining voices.** Join voices (`merge(keep, drop)`) closes a seat window still open for the
  dropped voice, so a pad tap cannot bring it back or save it in a room. When the kept voice had
  no seat it takes the dropped voice's seat (recorded as a `merge` change). Joining a voice to
  itself changes nothing.
- **Saved rooms.** Layouts are saved per room name in `<data>/kandha/rooms.json` as a list of
  zones in order of appearance ("the first voice goes left, the second right"), because voices
  are session-only. "Start with last layout" pre-assigns voice slots in order of appearance. No
  cross-session voice identity is attempted.
- **Practicum default**: with no room loaded, the second voice to appear defaults to `F`; the
  first (often the wearer, who can mark it "This is me") stays unmapped.
- **"This is me"**: one voice can be the wearer's own; it is never tapped and never saved
  (decision 0012).
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
| QtWebEngine microphone permission | granted with the Qt 6.8 permission API to the companion's exact origin only (same scheme, host and port), up front when the window opens so the page can name the microphones; the microphone opens only on Start, and the view never navigates elsewhere; a Chrome tab remains an alternative |
| Captions leaving the computer | no automatic fallback to the browser's speech service: it is an opt-in, off by default, with the risk stated in its label (section 2.3) |

## 10. Test plan

| Layer | How | Where |
|---|---|---|
| Pattern table | JSON schema and firmware header generation round-trip | `tests/test_kandha_patterns.py`, `tests/kandha.test.js` |
| Protocol | encode/decode every characteristic, bounds, little-endian | `tests/test_kandha_protocol.py` |
| Scheduler | priorities (`voice_resumes` below a speaker change), one seat tap per start, stale drop, rate limits, pre-emption, modes, mirror, unmapped, intents checked again on release | `tests/test_kandha_scheduler.py` |
| Seat map | window, double-tap reassign, join voices, rooms persistence, practicum default, angle → zone | `tests/test_kandha_seatmap.py` |
| Bridge | mock bleak: scan filter, pair, one connection on re-pair, reconnect after Forget, remembered device, reconnect backoff, ignored INPUT from strangers, STATUS, low battery, the mock stole's seq filter forgotten on a new connection | `tests/test_kandha_bridge.py` |
| Virtual stole parity | the same bytes produce the same zone timeline on the virtual stole and the mock stole (both run the Python `PatternPlayer`) | `tests/test_kandha_virtual.py` |
| Firmware on the host | `pattern_engine.h`, `touch_pads.h` and the whole `kandha.ino` built with the host C++ compiler against Arduino and BLE stand-ins (`tests/firmware_host/`): every built-in pattern, played once and twice, and CONFIG scaling, mirror, mute, a command replacing another, stop and late `loop()` ticks equal `PatternPlayer` millisecond by millisecond, with the 60/255 floor and the 15 ms kick on top; pad gestures (tap, double, long, debounce); the BLE-to-`loop()` mailbox and its backlog; the seq filter forgotten on each connection; STATUS on every flag change; a ThreadSanitizer run. Skipped without a C++ compiler and on Windows | `tests/test_kandha_firmware_host.py` |
| Intents | back-channel hold on LibriSpeech turns, the first turn after a long silence (one tap, short sounds, the page's silence setting), page controls, no double taps; the on-screen pads' gesture timing | `tests/kandha.test.js` |
| Service and HTTP | `/api/kandha/*` ownership, SSE, consent gate, settings, the session record (`session/new`, `session/events`, `session/save`, export by session id), the stale rule with page clocks ahead, behind or stepping, the seat window closing | `tests/test_kandha_service.py` |
| Page in Chromium | real `BrowserService` with the mock stole, Chromium's fake microphone: seat chips and keys, the voice dialog, the seat highlight, the queue after a reload, browser captions only as an opt-in, Demos and the session clock, the silence setting reaching the intents, the unreachable-service flash and status, the page tag on intents, the pads' gestures, the microphone remembered by name. Skipped without Playwright or Chromium | `tests/test_kandha_page.py` |
| Kandha window | QtWebEngine in a subprocess: the microphone only for the exact companion origin, exports saved to Downloads with unique names (also when the window closes right after one), the caption-model bar, opening from Audial-AI, quitting with Kandha open, the microphone across a relaunch, an explicit `--port` | `tests/test_kandha_window.py` |
| Packaging | `bleak` pinned and collected with its backend, the portable Windows wheel set, the HTML user guide, a `.sha256` beside every release asset | `tests/test_kandha_packaging.py` |
| End to end | real Chromium, fake microphone A B A B, Whisper stubbed, mock stole: zones in order, latency, no cue storms, queue saved, a consented save of this session | `scripts/verify_kandha.py` |
| Tap budget | taps per minute per mode over the natural-speech fixtures | `scripts/kandha_tap_budget.py` |
| Accessibility | keyboard reach, visible focus, contrast, names, 1280 × 720 | `scripts/audit_kandha_a11y.py` |
| Firmware build | compiles for the ESP32-S3 in CI with arduino-cli (core 3.1.1) | `.github/workflows/firmware.yml` |

## 11. Out of scope for this version

Cross-session voice identity, a microphone array, on-device English↔Hindi translation in the
Kandha window (decision 0007), DRV2605L drivers (decision 0003), and any claim about Indian
English, Hindi or real seminars: those need a physical stole and user testing with deaf students.
