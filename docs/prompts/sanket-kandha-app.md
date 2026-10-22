# Prompt: Design and build Sanket 2 — a laptop app calibrated to Kandha

> **How to use this file.** Open Claude Code in the root of this repository
> (Audial-AI) and say: *"Read `docs/prompts/sanket-kandha-app.md` and carry it out."*
> Everything Claude Code needs is below or in the files it points to.

---

## 0. Your role and how to work

You are the lead engineer and product designer for **Sanket 2**, a downloadable
laptop app for deaf students that runs inside this repository's Audial-AI
desktop stack. It works with **Kandha**, a haptic stole (scarf) described in §4.
Kandha does not exist as physical hardware yet, so you will also write its
firmware and an on-screen **virtual Kandha** that behaves identically.

Work in this order and do not skip ahead:

1. **Read first.** Read every file listed in §2, run the existing test suites
   (`npm test`, `python -m pytest -q` with `QT_QPA_PLATFORM=offscreen`) and
   record the baseline. Follow `CONTRIBUTING.md`: do not create a git worktree
   unless asked, do not commit recordings or credentials, and keep dataset and
   model notices.
2. **Design document before code.** Write `docs/sanket-kandha/DESIGN.md` covering
   everything in §§3–9: architecture diagram, screens, haptic language, BLE
   protocol, seat map, data flows, risks and test plan. Add short decision
   records in `docs/sanket-kandha/decisions/` for each real choice you make
   (for example, the web view versus a native Qt UI). Then **stop and ask for
   approval** before writing implementation code. If anything in this brief is
   ambiguous or contradicts the code, list it in the design doc as an open
   question and ask; do not guess silently.
3. **Build in vertical slices** after approval, each ending with passing tests:
   (a) haptic scheduler and seat map, with unit tests; (b) virtual Kandha;
   (c) Kandha BLE bridge in Python, with a mock device; (d) desktop window and
   packaging; (e) firmware; (f) full end-to-end flow; (g) documentation.
4. **Verify honestly.** Every claim in the docs must come from a test or
   measurement you ran. Clearly separate what was simulated (virtual Kandha,
   mock BLE, stubbed ASR) from what was measured on real hardware or real speech.

---

## 1. Who this is for

**Vikram** is a deaf psychology undergraduate (Hackcessible India 2026,
Vikram's challenge, run by the University of Sheffield with the AssisTech
Foundation). He lip-reads, reads English fluently and knows ISL. In lectures,
seminars and clinical role-plays ("practicum") his problems are:

- **Finding the speaker.** When someone new starts talking, he loses the first
  words while his eyes search the room. Lip-reading only works if he is already
  looking at the right face.
- **Tone.** Captions carry the words, not how they were said. In practicum
  this matters clinically, because a client's voice dropping or rising is information.
- **Turn-taking.** He cannot hear the gap where he could speak, so he gets
  talked over.

**The design rule that decides everything:** *his eyes stay on faces.* Anything
that makes him look down — at a watch, a phone, a laptop — costs him the lips
he is reading. Information that needs no looking goes to Kandha. The screen is
for the captions he chooses to glance at, and for review afterwards.

---

## 2. What already exists (read these files)

This repository is **Audial-AI** by Vedant Sood: a Python/PySide6 desktop app
with local Whisper captions, ISL playback, emotion models, a loopback browser
companion and an MV3 browser extension. Sanket 1 was merged into it in PR #1.

| Area | Files |
|---|---|
| Sanket overview, accuracy and limits | `docs/sanket.md`, `models/sanket/evaluation.json`, `docs/model_cards.md` |
| Voice engine (VAD, speaker tracking, tone cues, tone estimates) | `browser/sanket/engine.js`, `browser/sanket/tone.js`, `models/sanket/tone_model.json` |
| Sanket 1 full app (captions, modes, review, demos) | `browser/sanket/index.html`, `app.js`, `captions.js`, `local-captions.js`, `recognizer.js`, `translator.js`, `demo.js`, `styles.css` |
| **Watch/band link — to be removed** | `browser/sanket/band.js`; the Sanket Band settings and band calls in `browser/sanket/index.html` and `browser/sanket/app.js`; "Connect Sanket Band" in `browser/index.html` and `browser/app.js`; band calls in `browser/voice-view.js` |
| Voice events in Audial | `browser/voice-session.js`, `browser/voice-view.js`, `app/services/voice_view.py`, `app/services/browser.py` (`/api/voice-events`, `/api/voice-view/settings`, `/sanket/`), `app/services/browser_bridge.py` |
| Desktop app and packaging | `app/main.py`, `app/ui/main_window.py`, `app/services/engine.py`, `packaging/AccessibilityAI.spec`, `scripts/build_windows.ps1`, `.github/workflows/` |
| Tests | `tests/sanket.test.js`, `tests/test_sanket_integration.py`, `scripts/verify_sanket.py`, `tests/browser.test.js` |
| Training (tone model) | `training/sanket/` |

Key facts about the existing engine that you must preserve:

- **Audio time.** Audio is analysed in 32 ms frames with a 16 ms hop at 16 kHz.
  Every event carries audio time (seconds since the first captured sample), the
  same clock Whisper captions use.
- **Speaker decisions.** The engine decides who is speaking 0.64 s (clear cases)
  to 1.4 s after speech starts, and rechecks mid-speech. Voices are
  session-only slots, not identities.
- **Tone cues.** The cues are `drop` (voice softened), `rise` (voice rose),
  `hesitation` and `silence`. Once a person has been heard about 4 times,
  model-backed cues replace the loudness rules; a drop of 10 dB or more still
  counts as `drop`.
- **Tone estimates.** Estimates are always relative to the person. A category
  is named only when it is a personal estimate (at least 4 earlier utterances
  from that person) with confidence of at least 0.80; otherwise it is
  "uncertain". The training data is acted American English; nothing has been
  validated on Indian speakers. Keep this honesty in every user-facing word.

**Scrapped — do not design for these:** the wrist band or watch (all of
`band.js`, the band GATT service `a7c2f3e0-…0001`, and the band firmware
concept), the Kinara glasses lights, and the Sutradhar table pointer. Remove
the band from the UI and code paths, keeping `git` history as the record.

---

## 3. What to build: Sanket 2 for laptops

A **downloadable, offline-first laptop app**. Windows 10/11 x64 is the primary
target; macOS (Apple silicon) and Linux should run from source and be packaged
if feasible. It does four things:

1. **Captions.** Local Whisper through Audial's engine, in English or हिन्दी.
   Optional English↔Hindi translation must be on-device; if no on-device path
   exists in the desktop runtime, say so and leave translation off rather than
   sending audio or text online. The psychology vocabulary (autocorrect, with
   definitions on tap) stays.
2. **Who is speaking.** Each voice gets a colour. The arrow now points to that
   person's **seat zone** (left, right, behind, front), not a cosmetic
   direction.
3. **Kandha.** It taps the shoulder on the speaker's side, plays tone cues,
   and its queue pad lights the "I want to speak" strip.
4. **Review.** After a session: a timeline of voices, cues, tone estimates and
   queue moments; consent before saving; exports via Audial's session exports.

### Recommended architecture (confirm or challenge it in the design doc)

```
┌─────────────── Sanket 2 window (PySide6 + QWebEngineView) ───────────────┐
│  Sanket UI (HTML/JS, evolved from browser/sanket/)                       │
│   • getUserMedia mic → AudioWorklet tap → engine.js (voices, cues, tone) │
│   • audio packets → /api/audio → Audial engine → Whisper captions        │
│   • haptic intents → /api/kandha/haptic                                  │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ loopback HTTP (existing BrowserService, CSP, Host/Origin checks)
┌───────────────▼──────────────── Python (Audial process) ────────────────┐
│  BrowserService  ─ sessions, voice events, exports (existing)            │
│  KandhaBridge    ─ bleak BLE client · reconnect · battery · pad events   │
│  HapticScheduler ─ priorities, rate limits, quiet modes (pure, tested)   │
│  VirtualKandha   ─ same protocol, drives the on-screen stole             │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ BLE GATT (§5)
            ┌───▼────┐
            │ Kandha │  ESP32-S3 firmware
            └────────┘
```

Why this shape:

- **Reuse.** It keeps the tested JS engine and Audial's local Whisper,
  sessions and exports unchanged.
- **No Web Bluetooth dependency.** That is unavailable in `QWebEngine` and on
  some browsers; Python `bleak` works on Windows, macOS and Linux.
- **One process to package.** PyInstaller and Audial's installers are already
  set up.

Settle these in the design doc:

- **Where the HapticScheduler lives.** Python is recommended, so the virtual
  and real Kandha behave the same and the scheduler is unit-testable.
- **Packaging.** Whether QWebEngine's size is acceptable (`PySide6-Addons`) and
  how microphone permission is granted (`QWebEnginePage` permission API in
  Qt 6.8). Keep the browser companion and `/sanket/` route working for people
  who prefer a browser tab.
- **Startup.** Add `python -m app.main --sanket`, plus a "Sanket" entry in the
  desktop navigation that opens the window.
- **Microphones.** The laptop's built-in mic and a USB conference mic both
  work. Keep browser noise suppression **off** while voices are tracked
  (measured: it splits one person into two colours); leave echo cancellation
  on.

---

## 4. Kandha (theoretical hardware) — calibrate everything to this

A cotton or khadi stole worn over both shoulders, with a zipped inner channel
for electronics so it can be removed for washing. It is gender-neutral and
looks like everyday clothing, not a medical device.

| Zone ID | Where | Actuators | Used for |
|---|---|---|---|
| `L` | Left shoulder, on top | 2 coin ERMs ~3 cm apart | Speaker on the left |
| `R` | Right shoulder, on top | 2 coin ERMs | Speaker on the right |
| `B` | Back of neck | 1 coin ERM | Speaker behind |
| `F` | Front, at the collarbone or sternum | 1 coin ERM | Tone cues; speaker in front |
| `LR` | Both shoulders together | — (L+R) | Squeeze: queue acknowledged, floor open |

**Inputs** are four textile touch pads at the right-hand end of the stole, each
with a different stitched texture so they can be found without looking:
`PAD_L`, `PAD_R`, `PAD_B` and `PAD_Q` (queue).

**Reference build** (put a bill of materials with ₹ prices in the design doc):

- **Controller: ESP32-S3 mini board.** It has native capacitive touch. Note
  the ESP32-C3 has no touch peripheral; if you choose it, add a TTP223 or
  MPR121.
- **Haptic driver: DRV2605L.** Its I²C address (0x5A) is fixed, so use a
  TCA9548A I²C multiplexer for one driver per zone. Alternatively, drive the
  ERMs with logic-level MOSFETs and PWM and implement the waveforms in
  firmware. Compare the two in a decision record.
- **Power and connection:** a slim 3.7 V LiPo (about 600–1000 mAh), a TP4056
  USB-C charger and a soft power switch.
- **Wiring:** flat, flexible wiring or conductive thread; motors in small
  silicone pockets.
- **Constraints:** the whole thing must be washable after removal, weigh under
  about 120 g of electronics, and last a full college day (8 h) at typical cue
  rates. Estimate this in the design doc from duty-cycle maths.

---

## 5. Kandha BLE protocol v1 (define precisely, then implement)

- **New 128-bit service UUID.** Generate one; never reuse the scrapped band's.
- **Name:** devices advertise as `Kandha-XXXX`. All multi-byte values are
  little-endian.

| Characteristic | Props | Payload |
|---|---|---|
| `HAPTIC` | write w/o response | `[seq u8][zones u8 bitmask L=1,R=2,B=4,F=8][pattern u8][intensity u8 0–255][repeat u8]` |
| `PATTERNS` | write | Optional custom pattern upload: `[id][n][(on_ms u16, off_ms u16, level u8)×n]`; ids 0–31 reserved for built-ins |
| `INPUT` | notify | `[pad u8: 1=L 2=R 3=B 4=Q][gesture u8: 1=tap 2=double 3=long]` |
| `STATUS` | read + notify | `[battery % u8][charging u8][fw_major u8][fw_minor u8][flags u8]` |
| `CONFIG` | read + write | Per-zone intensity scale, global mute, handedness swap (mirror L/R), test mode |

Also specify:

- **Bridge behaviour:** reconnect with backoff, and what the UI shows when
  disconnected (captions continue; haptics fall back to the virtual Kandha
  and an on-screen flash).
- **Latency budget.** From the engine's speaker decision to motor start:
  ≤ 150 ms locally, ≤ 300 ms worst case including BLE. Measure it with the
  mock and report it.
- **Pairing and security.** A user-initiated scan and pair, and remembering
  the device. Do not accept `INPUT` from unknown devices.

---

## 6. The haptic language (Kandha's vocabulary)

It must be learnable in five minutes and **quiet by default**. Vikram must
never get a constant buzz; that was a measured problem in prior research on
head-worn directional haptics with several talkers.

| Meaning | Zone | Pattern (starting point; tune in user tests) |
|---|---|---|
| A known voice starts or takes over | that voice's seat zone | One firm 120 ms tap |
| A **new** voice appears | `F` then a short pulse wherever it is | Two short taps on `F` |
| Voice softened (`drop`) | `F` | One slow 700 ms swell |
| Voice rose (`rise`) | `F` | Three quick 80 ms taps |
| Hesitation | `F` | A soft flutter (5×40 ms) |
| Long silence / floor open | `LR` | Two gentle ticks on both shoulders |
| Queue acknowledged (`PAD_Q`) | `LR` | One short squeeze |
| Waiting too long (configurable, e.g. 60 s) | `LR` | One reminder squeeze, at most once a minute |
| Low battery (20%) | `B` | Three slow pulses, once |

**Scheduler rules** (implement them in `HapticScheduler` with unit tests):

- **Priority:** speaker change > queue feedback > tone cue > silence.
  Never queue up stale haptics: drop a cue older than 1.5 s.
- **Limits:** at most one tone cue per 3 s, and the same cue type no more
  than once per 8 s (match `engine.js` cooldowns). A speaker tap always
  wins and pre-empts a cue in progress.
- **Short turns:** do not tap for very short turns (back-channel "mm-hm"
  under about 0.6 s). Choose the threshold with the existing engine tests
  and LibriSpeech fixtures, and document it.
- **Modes:**
  - **Lecture:** one speaker; seat taps off; only queue feedback and
    silence.
  - **Seminar:** seat taps on; tone cues optional (off by default).
  - **Practicum:** two voices; tone cues on.
  - **Do not disturb:** only queue feedback.
- **Unmapped voice:** if a voice has no seat zone, tap `F` once.
- **Handedness and zones:** a mirror setting swaps L and R. Each zone has
  its own intensity.

---

## 7. Seat map (how voices become shoulders)

The voice engine knows *who* (a voice slot), not *where*. Kandha needs where.
The seat map links them:

- **Assign by touch.** When a new voice appears (two taps on `F`), Vikram
  touches `PAD_L`, `PAD_R` or `PAD_B` within about 6 s to assign that voice's
  seat. Touching nothing leaves it unmapped. A double-tap on a pad reassigns
  the **currently speaking** voice.
- **Assign on screen.** Each voice chip in the UI can be dragged onto a
  top-down room diagram showing Vikram and seats. Arrows on screen follow the
  seat map.
- **Persistence.** Save the map per named room ("Seminar room 2.14",
  "Practicum lab") and offer it again at the start of the next session.
  Re-identifying returning people across sessions is **out of scope**: voices
  are session-only, so the stored map is a starting layout and is not tied to
  identities.
- **Future:** a direction-of-arrival source (a USB mic array) could fill the
  map automatically. Define the interface (`SeatSource` producing an angle per
  voice) but do not build it now.
- **Practicum:** the partner is usually in front. Default to `F` for the
  other voice and still allow changes.

---

## 8. Screens and interaction (laptop)

The UI uses large type, high contrast, dark and light themes and the
Atkinson Hyperlegible font (bundled locally; no web fonts at runtime). Every
action is keyboard-reachable, with visible focus. The UI follows WCAG 2.1 AA
and works at 1280×720.

1. **Live view.**
   - Top strip: queue state, glowing amber when Vikram is waiting.
   - The current caption in the speaker's colour.
   - A transcript of recent lines.
   - A compact **room diagram** (Vikram plus seats) that lights the active
     voice's seat.
   - A **virtual Kandha**: a stole silhouette whose zones pulse exactly as
     the real one would. Also used for demos, training and when no device is
     connected.
   - Mode switch: Lecture, Seminar or Practicum.
   - Speech language: English or हिन्दी.
2. **Kandha panel.** Scan, pair, battery and firmware status, per-zone test
   buttons, intensity sliders, mirror L/R, do-not-disturb, and a five-minute
   **learn the taps** tutorial that plays each pattern with its meaning.
3. **Seat setup.** The room diagram with drag-and-drop voices, saved rooms,
   and a "start with last layout" option.
4. **Review.**
   - A timeline with voice lanes, cues, tone-estimate lane and queue moments.
   - The transcript with tone notes.
   - "How accurate is this?" explaining the model's numbers and limits.
   - A consent checkbox before any save.
   - Export as web page, text, VTT, SRT or JSON through Audial's session
     exports.
5. **Settings.**
   - Name (shown on the queue strip).
   - Caption size and theme.
   - Which cues and modes are on.
   - Tone estimates in review (on) and live (off by default).
   - Microphone choice.
   - Privacy explanation.
6. **Demo mode.** A scripted seminar and a practicum role-play that drive the
   captions, voices, room diagram and virtual Kandha with no microphone, for
   filming the competition video. Label scripted estimates as scripted.

**Keyboard shortcuts:** `Q` toggles queue, `S` start/pause, `M` "what did I
miss" (last 30 s), and `1`–`4` assign the current voice to L/R/B/F.

---

## 9. Packaging and distribution

**Windows:** extend the existing PyInstaller spec and installer flow
(`packaging/`, `scripts/build_windows.ps1`, `.github/workflows/`) with:

- the Sanket window;
- QtWebEngine resources;
- `bleak` and its WinRT backend;
- the Kandha firmware binary and flashing instructions (or a separate
  download).

The Start menu entry is "Sanket". The app must work fully offline after model
setup.

**macOS and Linux:** document running from source. Package them only if it
doesn't destabilise the Windows build.

**Firmware:** an Arduino-ESP32 (core 3.x) or ESP-IDF sketch in
`firmware/kandha/`, plus:

- a pin map;
- the pattern table generated from the same JSON as the app's haptic
  language (single source of truth: `browser/sanket/kandha-patterns.json`,
  or similar);
- a serial test console;
- a CI job that at least compiles it.

---

## 10. Quality bar and tests

- **Keep green.** Every existing test must still pass. Add `npm test` and
  `pytest` coverage for the scheduler, seat map, BLE protocol encoding and
  decoding, bridge reconnect (mock `bleak`), pad gestures, virtual Kandha
  parity with the real protocol, and mode rules.
- **End-to-end.** Extend `scripts/verify_sanket.py`, or add
  `scripts/verify_kandha.py`. Use real Chromium or QtWebEngine with a fake
  microphone playing the LibriSpeech fixtures in turns (A B A B), stubbed
  Whisper and the mock Kandha. Assert:
  - that the correct zones fire in order;
  - the latency is within budget;
  - no cue storms (no more than about 1 haptic per 1.5 s outside speaker
    changes);
  - that queue taps light the strip and are stored with the session.
- **Haptic budget report.** Over the 4-minute natural-speech fixtures, how
  many taps per minute does Vikram feel in each mode? Target ≤ 6/min in
  Seminar excluding speaker changes. Report the measured number.
- **Accessibility audit.** Keyboard, focus, contrast and screen-reader labels
  for every new screen.
- **Docs.** Update `docs/sanket.md`, and add `docs/sanket-kandha/USER_GUIDE.md`
  (wearing, charging, learning the taps, washing), `docs/architecture.md`,
  `README.md`, `LICENSE_NOTICES.md` and release notes. Every number must be
  traceable to a test or measurement; mark what is simulated.

---

## 11. Non-negotiables

- **Privacy.** Audio never leaves the computer. No telemetry.
  Recordings are never stored. Transcripts are saved only with consent.
- **Tone is a hint, not a fact.** Estimates describe how a voice sounded
  relative to that person, learned from acted speech. Never present them as
  feelings, diagnoses or truth, and never name a category under 80% confidence
  or before the person has been heard about 4 times.
- **Never break the core.** Captions continue when Kandha is
  disconnected, the battery is flat or the BLE stack fails.
- **Room awareness.** Remind the user that the people in the room should
  know live captions are on. Saving a practicum transcript with real clients
  needs supervisor and ethics approval.
- **Licences.** Keep existing licences and notices; add notices for any new
  dependency (`bleak` is MIT; check QtWebEngine/Chromium licensing in the
  packaged build).

---

## 12. Deliverables checklist

- [ ] `docs/sanket-kandha/DESIGN.md` and decision records, **approved before
      coding**.
- [ ] Sanket 2 window (`--sanket`) with the live view, Kandha panel, seat
      setup, review, settings and demo mode.
- [ ] The band removed from the UI and code; Kandha in its place.
- [ ] `KandhaBridge` (bleak), `HapticScheduler`, `VirtualKandha`, and the
      seat-map persistence.
- [ ] `firmware/kandha/` that compiles, with pin map and BOM.
- [ ] A single pattern table shared by the app and the firmware.
- [ ] Tests and end-to-end verification with the measured latency and haptic
      budget.
- [ ] A Windows installer including Sanket 2 (CI), plus from-source
      instructions for macOS and Linux.
- [ ] Updated docs and notices, and a 90-second demo script for the
      competition video using demo mode and the virtual Kandha.

When finished, summarise:

- what was built;
- what was measured versus simulated;
- what still needs real hardware or real users to validate: a physical
  Kandha, Indian English and Hindi speakers, real seminars, and user testing
  of the haptic language with deaf students.
