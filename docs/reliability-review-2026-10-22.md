# Source reliability review — 22 October 2026

This review uses `87ed5e8` from `main` as its baseline. It covers the Python
application, inference and training tools, browser companion, Sanket integration,
extension transport, persistence and existing validation paths. Automated checks
scan all 133 Python source/test files for undefined names and check the syntax of
27 JavaScript modules. Manual review and changes concentrate on capture lifecycle,
bounded queues, state persistence and inputs crossing the local HTTP boundary.
This is a source reliability review, not an exhaustive security audit.

## Changes

| Trigger | Previous behavior | Updated behavior |
| --- | --- | --- |
| Two workers save the same JSON document | Both use the same temporary filename; one can overwrite the other's staging data or fail during rename. | Each writer stages a separate file on the destination filesystem, flushes it, then atomically replaces the document. Failed writes clean up staging and preserve the prior document. |
| Stop is pressed while local-caption startup is pending | A late status/start response can open capture after Stop. | Startup responses belong to a generation. Cancellation invalidates that generation and stops any session created by a late response. Concurrent starts and stops are guarded. |
| Local-caption uploads are slower than capture | Promise closures can retain an unbounded audio backlog. | At most three uploads are queued or in flight, with request timeouts. Excess packets report a gap and still advance the sample clock. Stop drains uploads before sending the final partial packet. |
| Voice events accumulate before session creation or behind a slow request | A batch can exceed the server's 200-event limit; immediate cue sends can build an unbounded promise chain. | One sender drains batches of at most 200 events from the existing bounded pending queue. Later batches can proceed after a request failure. |
| A small compressed upload claims to be WAV, or a WAV exceeds duration/channel limits | The whole file is decoded before validation. | WAV format, sample rate, channel count and frame count are checked before allocating decoded audio. Mono and stereo packets up to three seconds remain supported. |
| A browser session selects Hindi and an unrelated preference is saved | The temporary speech language can be saved as the desktop default; failed startup can also leave it changed. | The audio engine keeps a session-specific language. Status reports the active language while the saved desktop preference remains independent. Model loading and CPU fallback use that same session language. |

The Linux source workflow now runs Python tests, Node tests, headless desktop
startup and the existing real Chromium Sanket integration check. It uses the
locked CPU runtime, read-only repository permissions and pinned GitHub Actions.
Windows acceptance remains in the existing Windows workflows.

## Validation in the cloud development machine

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 140 passed; 1 skipped because the Windows Credential Manager API is unavailable on Linux |
| `npm test` | 39 passed; no skips |
| `python -m app.main --smoke-test` | Native UI, bundled ISL playback and silence abstention passed; no microphone started |
| `python -m scripts.verify_sanket --browser /usr/bin/chromium --output artifacts/reliability-review/final-sanket` | Passed in Chromium 154.0.8037.57; both voices and returning speakers detected, transcript attribution and VTT names verified, queue light and stored events verified, local captions and CSP verified; no page errors |
| Dependency compatibility | All 77 installed packages compatible |
| Ruff `F821,F822,F823` over Python source/tests | Passed |
| `node --check` over browser, extension and training JavaScript | 27 files passed |
| Actionlint 1.7.7 on `linux-source.yml` | Passed |

The concurrency, startup cancellation, batch-limit and pre-decoding regression
tests were observed failing before their respective fixes. Additional tests cover
failed publication, late session cleanup, final-packet draining, repeated Stop,
slow uploads and language changes during model loading.

Current-run XML, screenshots and browser results are generated under the ignored
`artifacts/reliability-review/` directory. Hosted CI execution is separate from
these local results.

The Chromium integration uses supplied licensed recordings through a fake
microphone and a caption stub. It establishes browser integration behavior; it
does not establish speech-recognition or emotion accuracy. Real model inference,
physical capture devices, Windows installers, Windows-native extension transport
and haptic hardware were not validated during this review. Model weights,
published accuracy claims and ISL vocabulary scope are unchanged.
