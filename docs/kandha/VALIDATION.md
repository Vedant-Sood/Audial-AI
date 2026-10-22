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

## Still needs real-world testing

A physical stole (tap feel, pad thresholds, battery, Bluetooth latency), Windows installer
acceptance (runs in CI on the Windows workflow), Indian English and Hindi speakers, real
seminars, and user testing of the tap language with deaf students.
