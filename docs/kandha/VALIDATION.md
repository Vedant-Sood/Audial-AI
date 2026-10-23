# Kandha validation summary

Every number here comes from a script in this repository. The checks in the table (all but the
baseline before Kandha) were last run on 2026-10-23 on the tree of the commit that last changed
this file (`git log -1 -- docs/kandha/VALIDATION.md`): the review fix run's final fix-up on top
of `dedd2df` (the run's commits `822d818`, `607d41e`, `a4937d0` and `dedd2df` follow
`2281216`). The back-channel study, the tap budget and the accessibility audit wrote records
identical to those of `dedd2df`. They ran in a Linux x86_64 cloud container
(Python 3.12.3, Node 22.22.0, Chromium 141.0.7390.37, QtWebEngine 6.8.3 / Chromium 122,
g++ 13.3). The Windows and Linux build sections further down are older records and say so. What
was simulated is marked. Nothing has been measured on a physical stole, over Bluetooth, or with
Indian English or Hindi speakers; on Windows only the CI install check below has run.

| Check | Script | Record |
|---|---|---|
| Test baseline before Kandha | `npm test`, `pytest` | [baseline.json](validation/baseline.json): npm 31/31, pytest 132 passed, 1 skipped |
| Tests now | `npm test`, `QT_QPA_PLATFORM=offscreen python -m pytest -q` | npm 58/58 (19 in `tests/kandha.test.js`); pytest 362 passed, 1 skipped (the Windows Credential Manager test). 216 of the pytest tests are in `tests/test_kandha_*.py`, and none of them was skipped: the page in real Chromium (13), the Kandha window in QtWebEngine (12) and the firmware built and run on the host with g++ (59) all ran |
| Firmware pattern header | `python scripts/generate_kandha_patterns.py --check` | `firmware/kandha/patterns.h` is up to date with the pattern table |
| Back-channel hold and the first turn after a long silence | `node scripts/kandha_backchannel_study.mjs` | [backchannel.json](validation/backchannel.json) |
| End to end in Chromium | `python -m scripts.verify_kandha` | [e2e-chromium.json](validation/e2e-chromium.json) |
| The two demos | `python -m scripts.record_kandha_demos` | [demo-taps.json](validation/demo-taps.json) |
| Tap budget | `node scripts/kandha_tap_budget.mjs` + `python -m scripts.kandha_tap_budget` | [tap_budget.json](validation/tap_budget.json) |
| Accessibility | `python -m scripts.audit_kandha_a11y` | [a11y-chromium.json](validation/a11y-chromium.json) |
| Embedded window | `python -m app.main --kandha-check` | page ready in 0.8 s in QtWebEngine 6.8.3 with the `QWebEnginePermission` API (offscreen; this container runs as root, so it needed `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu"`) |

## Back-channel hold (decision 0004)

Engine over the LibriSpeech readers (real speech): every real turn was decided with
0.624 s of turn known (early decision) or 1.424 s (final). A spliced
0.25 s interjection produced no speaker decision; a 0.45 s one was decided with 0.48 s known and
is held back by the 0.6 s rule; 0.6 s and 0.9 s interjections tap. Simulated part: the
interjections are spliced slices of the other reader, not recorded "mm-hm"s.

**The first turn after a long silence** (16 cases: silences of 4.5 s and 6 s, then the same
reader, a known reader coming back, a new reader, or noise or a short burst before the real
turn; the intent layer given the engine's 4 s silence setting, as the page passes it): every
case sent exactly one seat intent, and never the previous voice's. A new voice was sent at the
engine's early decision, 0.656 s after speech started; a known other voice coming back at the
engine's final decision, 1.456 s; the same voice again at the engine's final say plus the
margin, 1.552–1.568 s; after noise or a 0.2 s burst, 2.368–3.536 s. Simulated part: the
silences, noise and bursts are spliced, not recorded.

## End to end (Chromium, fake microphone, Whisper stubbed, mock stole)

The clip: reader A, reader B, A, B with short pauses, then 5 s of silence and A again, then
5 s of silence and a third reader, C (LibriSpeech, 54 s). The run below was repeated once with
the same taps in the same order.

- Speaker taps the stole received, in order: new_voice on F (A), new_voice on F (B), seat_tap
  on L (A back), seat_tap on R (B back), seat_tap on B (A after the silence), new_voice on F
  (C after the silence). A saved room seats A left and B right.
- A pad double-tap 22 s in, during A's second turn and after its left tap, reseated A
  (voice 1) to "behind"; B kept its right seat. Final seats: voice 1 behind, voice 2 right,
  voice 3 none.
- **After a long silence a different voice gets only its own tap** (review finding C0). After
  B's last turn and 5 s of silence the stole played the silence ticks and then exactly one seat
  tap for A, on A's own seat (behind), sent as `voice_resumes`. After the next 5 s of silence it
  played the silence ticks and exactly one front double tap for C, a new voice. B's seat was
  never tapped first, and nothing came between the silence ticks and those taps. The same check,
  run against the intent layer and scheduler of `2281216` (before the fix), fails: there the
  stole tapped R (B's seat) and then B for A's return, and B (A's seat) and then F for C.
- In-app latency from the page's intent to the stole write (n=9): p50 2.5 ms, p95 4.6 ms,
  max 4.6 ms, against a 150 ms budget (the repeat: p50 2.3 ms, p95 3.6 ms). The mock stole's
  write round trip was at most 0.11 ms. **Simulated:** Bluetooth is not involved, so the 300 ms
  end-to-end budget remains a budget.
- Cue storms: at most 1 cue-like tap in any 1.5 s window.
- Queue: the strip followed the `Q` key and the stole's queue pad. The session record held
  6 voice, 3 cue, 14 tone, 4 queue, 13 haptic and 1 seat events. A consented "Save to
  sessions" wrote exactly this session: 27 captions, each keeping the stub's word confidence,
  and 41 events. When another window then started a session, Save, VTT, SRT and JSON turned off,
  the note and a polite live-region toast said why, and an export with a blank session id was
  refused (409).
- **Simulated:** captions are time spans from a stub, not words; the microphone is a WAV file.

## The two demos (Chromium, mock stole)

Both built-in demos played through the page, the service's scheduler and the paired mock stole.
The stole received, in order (two runs, the same order, times within 0.07 s):

- Seminar (37.6 s): new_voice F three times (Dr Rao, Priya, Arjun), queue_ack LR, seat_tap L
  (Priya), seat_tap F (Dr Rao), queue_ack LR (the queue clears), silence LR, seat_tap R (Arjun).
- Practicum (31.9 s): new_voice F (the client), new_voice F (Vikram, whom the demo marks "This
  is me" just after, as a wearer would), seat_tap F (the client), drop F, silence LR, seat_tap F
  (the client), hesitation F, rise F.

These are the sequences `browser/kandha/demo.js` scripts; `record_kandha_demos` fails when they
change. [DEMO_SCRIPT.md](DEMO_SCRIPT.md) narrates all of the seminar's taps but only the
practicum's three tone cues (drop, hesitation, rise), and the recorder also fails when those
stop coming in that order. The practicum's two new voices, the client's seat taps and the
silence ticks come from `demo.js`, not from the video script. The page's own tap list matched
the stole's in both. **Simulated:** the demos are scripted (no microphone, scripted tone
estimates) and the stole is the mock.

## Tap budget (natural-speech fixtures, real scheduler)

Taps per minute, (all taps, taps excluding speaker changes):

| Fixture | Lecture | Seminar (default) | Seminar, cues on | Practicum | Do not disturb |
|---|---|---|---|---|---|
| reader 1 single (1.22 min) | 0.0 (0.0) | 0.82 (0.0) | 0.82 (0.0) | 0.82 (0.0) | 0.0 (0.0) |
| reader 2 single (1.45 min) | 0.0 (0.0) | 0.69 (0.0) | 1.38 (0.69) | 1.38 (0.69) | 0.0 (0.0) |
| reader 3 single (1.3 min) | 0.0 (0.0) | 0.77 (0.0) | 1.54 (0.77) | 1.54 (0.77) | 0.0 (0.0) |
| seminar three readers (3.91 min) | 0.0 (0.0) | 10.23 (0.0) | 11.26 (1.02) | 11.26 (1.02) | 0.0 (0.0) |

Target: at most 6 per minute in Seminar excluding speaker changes. Worst measured:
0.0 per minute (cues are off by default in Seminar; with cues on,
1.02 per minute). The stitched three-reader seminar changes speaker every 6.7 s
by construction, hence 10.23 speaker taps per minute there. The 2026-10-23 re-run gave the
intent layer the engine's silence setting, as the page does; the intents and the table came out
identical to the first run, because these fixtures have only 0.7 s pauses and so never reach
the long-silence rules. **Simulated:** the seminar is stitched from single readers; nobody
interrupts anybody.

## Accessibility (Chromium, both themes)

Result: PASS. Every focusable control on every screen was reached by Tab with a visible
focus indicator; no text failed WCAG 2.1 AA contrast; no horizontal overflow at 1280 × 720;
arrow keys move between screens; Escape closes dialogs. Controls per screen (the same in the
dark and the light theme): live 20, stole 31, seats 19, review 16, settings 43.
Not done: a screen-reader walkthrough with a user.

## Windows installer (GitHub Actions, windows-2022 runners)

An earlier record, not re-run in this pass: the fixes since then need a new run of the Windows
workflow. Run [39807417445](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39807417445) on commit
`305b77c` passed on both runtimes (CPU and NVIDIA): the Windows regression suite including the
Kandha tests, `python -m app.main --kandha-check` from source (page ready in 0.8 s), the
Audial-AI and Kandha installer builds, Chrome for Testing and Edge transport, the installed
Audial-AI lifecycle, and the installed Kandha acceptance (`scripts/verify_kandha_windows.ps1`):
`Kandha-Setup-0.6.0.exe` installed on a disposable account, `Kandha.exe` and the Start-menu entry
"Kandha" present, firmware sources, bundled font and tone model in the payload, the packaged
QtWebEngine page ready in 0.8 s with the `QWebEnginePermission` API, uninstall with purge. The
artifacts `Kandha-Windows-x64-CPU` (1.38 GB) and `Kandha-Windows-x64-NVIDIA` (5.26 GB) hold
`Kandha-Setup-0.6.0.exe`, `Kandha-0.6.0-windows.zip`, their `.sha256` files and the acceptance
report. An earlier run on `7bb5b52` failed only because the page check then gave up after 40 s on
a cold runner; the window now waits 150 s and reports why it gave up. **Not covered:** a
microphone, Bluetooth hardware, and a human looking at the window.

## Linux portable build (this container, 2026-10-22)

An earlier record, not rebuilt in this pass. `python -m PyInstaller packaging/AccessibilityAI.spec`
produced `dist/AccessibilityAI` (2.3 GB: `AccessibilityAI`, `AccessibilityAIWorker`, `Kandha`,
QtWebEngine, bleak 0.22.3 (the requirements now pin 3.0.2), firmware, fonts, models, docs);
`./AccessibilityAIWorker --kandha-check` from that folder reported the page ready.
`scripts/package_kandha_portable.py` wrote `Kandha-0.6.0-linux.tar.gz` (940 MB, SHA-256
`500a46af2cc036e66d2310d1459c97684243537b358330008135d44ebe632717`). The archive was built and
checked here only; it is not published anywhere.

## Still needs real-world testing

A physical stole (tap feel, pad thresholds, battery, Bluetooth latency), Windows installer
acceptance of the current tree (runs in CI on the Windows workflow), Indian English and Hindi
speakers, real seminars, and user testing of the tap language with deaf students.
