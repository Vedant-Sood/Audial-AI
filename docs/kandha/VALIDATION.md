# Kandha validation summary

Every number here comes from a script in this repository, run on 2026-10-22 in a Linux x86_64
cloud container (Python 3.12.3, Node 22, Chromium 141.0.7390.37, QtWebEngine 6.8.3 /
Chromium 122). What was simulated is marked. Nothing has been measured on a physical stole,
over Bluetooth, on Windows, or with Indian English or Hindi speakers.

| Check | Script | Record |
|---|---|---|
| Test baseline before Kandha | `npm test`, `pytest` | [baseline.json](validation/baseline.json): npm 31/31, pytest 132 passed, 1 skipped |
| Tests after Kandha | `npm test`, `pytest` | npm 38/38, pytest 206 passed, 1 skipped |
| Back-channel hold | `node scripts/kandha_backchannel_study.mjs` | [backchannel.json](validation/backchannel.json) |
| End to end in Chromium | `python -m scripts.verify_kandha` | [e2e-chromium.json](validation/e2e-chromium.json) |
| Tap budget | `node scripts/kandha_tap_budget.mjs` + `python -m scripts.kandha_tap_budget` | [tap_budget.json](validation/tap_budget.json) |
| Accessibility | `python -m scripts.audit_kandha_a11y` | [a11y-chromium.json](validation/a11y-chromium.json) |
| Embedded window | `python -m app.main --kandha-check` | page ready in QtWebEngine 6.8.3 with the `QWebEnginePermission` API (offscreen) |

## Bench stole: first results (reported by the builder, 2026-11-22)

These are the first observations made on the physical bench stole (Waveshare ESP32-S3-Zero,
2N2222A switches, firmware 0.11), as reported by the person who built it. Nothing below has
been measured with instruments yet.

- **Motor map from `identify`:** L = GPIO 10, R = GPIO 8, B = GPIO 11, F = GPIO 9. So the
  wiring does not follow the default L, R, B, F = 8, 9, 10, 11 order.
- **Front motor (GPIO 9) does not buzz.** The fault is not yet found. `hold 9` and the checks
  in the firmware README are the next step.
- **Real Bluetooth link:** not working yet; the app could not find the stole. Fault-finding
  is in progress.

## No transcript is saved or exported (decision 0018), 2026-11-22

Run in a Linux x86_64 cloud container with Python 3.12.3 and Node 22.23.5.
**Result: npm 48 of 48 passed; pytest 220 passed, 1 skipped.**

What the tests check:

- **The full Kandha session path, under a spy.** `test_kandha_session_cannot_be_saved_or_exported_and_writes_nothing`
  - Patches `open`, `os.open`, `os.replace`, `os.rename` and `socket.connect`.
  - Runs a full Kandha captioning session with a canary caption and voice events.
  - Tries `/api/kandha/session/save` (gone: 404) and `/api/export` in all five formats (403).
  - Calls `Session.save()` and `Session.export()` directly; both raise `PrivateSessionError`.
  - Result: the only files written were Kandha's own settings, rooms and stole files. The
    canary appeared in no file under the data folder, no temporary file and no log line. No
    connection left loopback.
- **The spy works.** `test_the_spy_catches_a_transcript_write`: the same spy records an
  ordinary Audial session save.
- **The desktop window gets no captions.**
  `test_kandha_captions_never_reach_the_desktop_window_queue`: during a Kandha session the
  shared engine queues only status, warning, error and performance events, so the desktop
  window can no longer collect Kandha's captions and offer to save them.
- **Sabotage check.** With the private flag switched off on purpose, the two tests above
  fail. With it restored, they pass.
- **The page has no save path.** In `tests/kandha.test.js`, the Kandha page contains no
  export, save, download or consent code, and its only browser storage is its settings.
- **Chromium smoke check.**
  - What was checked: the page loaded with no script errors, the seminar demo ran, and Review
    showed the session with no consent box, no save button and no export button.
  - This is a one-off script, not in the repo.
  - `scripts.verify_kandha` fails at "timed captions and two voices" in this container. It
    fails the same way on the code from before this change, so the cause is the environment,
    not this change. It has not been re-run elsewhere yet.

Not built yet (planned after 30 November):
- the 5-minute caption memory;
- Q-pad bookmarks;
- the Review change to "bookmarks only".

Until then, the Review screen still shows the current session on screen, in memory only.

## Back-channel hold (decision 0004)

Engine over the LibriSpeech readers (real speech): every real turn was decided with
0.624 s of turn known (early decision) or 1.424 s (final). A spliced
0.25 s interjection produced no speaker decision; a 0.45 s one was decided with 0.48 s known and
is held back by the 0.6 s rule; 0.6 s and 0.9 s interjections tap. Simulated part: the
interjections are spliced slices of the other reader, not recorded "mm-hm"s.

## End to end (Chromium, fake microphone, Whisper stubbed, mock stole)

- Speaker taps the stole received, in order: new_voice on F, new_voice on F, seat_tap on L, seat_tap on R.
  The two new voices tap the front first; the returning readers tap their seats (the second
  reader was reseated to "behind" by a pad double-tap mid-session, which the check verifies).
- In-app latency from the page's intent to the stole write (n=5): p50 4.3 ms, p95 6.5 ms,
  max 6.5 ms, against a 150 ms budget. The mock stole's write round trip was at most
  0.09 ms. **Simulated:** Bluetooth is not involved, so the 300 ms end-to-end
  budget remains a budget.
- Cue storms: at most 1 cue-like tap in any 1.5 s window.
- Queue: the strip followed the `Q` key and the stole's queue pad; the session stored
  4 queue events, 4 voice events, 9 taps and 1 seat change.
- **Simulated:** captions are time spans from a stub, not words; the microphone is a WAV file.

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
by construction, hence 10.23 speaker taps per minute there. **Simulated:** the seminar is
stitched from single readers; nobody interrupts anybody.

## Accessibility (Chromium, both themes)

Result: PASS. Every focusable control on every screen was reached by Tab with a visible
focus indicator; no text failed WCAG 2.1 AA contrast; no horizontal overflow at 1280 × 720;
arrow keys move between screens; Escape closes dialogs. Controls per screen (dark):
live 19, stole 30, seats 18, review 15, settings 41.
Not done: a screen-reader walkthrough with a user.

## Windows installer (GitHub Actions, windows-2022 runners)

Run [39807417445](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39807417445) on commit
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

## Linux portable build (this container)

`python -m PyInstaller packaging/AccessibilityAI.spec` produced `dist/AccessibilityAI` (2.3 GB:
`AccessibilityAI`, `AccessibilityAIWorker`, `Kandha`, QtWebEngine, bleak, firmware, fonts, models,
docs); `./AccessibilityAIWorker --kandha-check` from that folder reported the page ready.
`scripts/package_kandha_portable.py` wrote `Kandha-0.6.0-linux.tar.gz` (940 MB, SHA-256
`500a46af2cc036e66d2310d1459c97684243537b358330008135d44ebe632717`). The archive was built and
checked here only; it is not published anywhere yet.

## Still needs real-world testing

A physical stole (tap feel, pad thresholds, battery, Bluetooth latency), Windows installer
acceptance (runs in CI on the Windows workflow), Indian English and Hindi speakers, real
seminars, and user testing of the tap language with deaf students.
