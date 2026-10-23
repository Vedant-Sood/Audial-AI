# Current verification

Run `python -m pytest -q`, `npm test`, and `python -m app.main --smoke-test`.
The current release report is [0.5.0 validation](validation-0.5.0.md). Browser endpoint tests
need local socket access; headless Linux uses `QT_QPA_PLATFORM=offscreen`.
These checks do not record microphones or cameras.

The [Linux source workflow](../.github/workflows/linux-source.yml) runs these
checks and the Chromium Sanket integration test on pushes to `main` and
`codex/**`, and on pull requests to `main`. It installs the pinned CPU runtime
from `requirements-cloud.lock`; the root Node tests need no npm dependencies.
See the [22 October source reliability review](reliability-review-2026-10-22.md)
for the capture, queue and persistence regressions added in that pass.

After complete model setup, run `python -m app.main --verify-inference` for
imported-file ASR/expression/prosody and `--verify-live-inference` for the same
models through the streaming capture loop. Both block socket connections. The
streaming check sends the supplied licensed recording in real-time 20-ms PCM
blocks; it validates VAD, asynchronous captions/expression, objective prosody,
and Stop/resource release. It does not validate a physical capture device or
the browser transport.

`python -m scripts.verify_browser --browser <executable> --native-host <worker.exe>
--output <directory>` separately exercises real Chromium/Edge extension APIs,
the OS toolbar capture grant, native PCM, source identity/switching, reload,
suspension/restoration, disconnect/reconnect and cleanup. Generated tones verify
the actual selected source; this transport-only check deliberately replaces ASR.
The fast browser workflow packages the product native host independently. The
full release workflow runs it against the complete desktop worker executable.
Managed extension restrictions remain enforced; a policy block is not a pass.

The original uploaded benchmark, trained weights and historical experiment records
remain in the repository for provenance. They do not establish a new Indian voice
accuracy result. Windows device capture, target-machine speed, and signer assessment
require testing on the target machine.

Kandha: `tests/kandha.test.js` (pattern table, intents on LibriSpeech turns, the on-screen
pads' gesture timing) and `tests/test_kandha_*.py` (pattern table and firmware header, protocol
bytes, scheduler rules, seat map and rooms, virtual-stole parity, bridge with mock bleak,
service and HTTP routes, SSE, the session record and consent gate, packaging). Three of them
need more than Python: `tests/test_kandha_firmware_host.py` builds and runs the firmware's C++
on the host and is skipped without a C++ compiler (and on Windows);
`tests/test_kandha_page.py` drives the page in real Chromium with the mock stole and is skipped
without Playwright or Chromium (`KANDHA_CHROMIUM` names the browser; the Linux source workflow
runs pytest before it installs Chromium, so this test skips there); and
`tests/test_kandha_window.py` opens the Kandha window in QtWebEngine subprocesses.
`python -m app.main --kandha-check` loads the page in QtWebEngine headlessly.
`python -m scripts.verify_kandha` is the Chromium end-to-end check with the mock stole (it also
checks that a different voice after a 5 s silence gets only its own tap);
`python -m scripts.record_kandha_demos` records the two demos' taps, checks each whole sequence
against the one `demo.js` scripts and that the taps the demo video script narrates (all of the
seminar's, the practicum's three tone cues) come in order;
`scripts/kandha_backchannel_study.mjs` measures the back-channel hold and the seat intents for
the first turn after a long silence; `scripts/kandha_tap_budget.{mjs,py}` measure taps per minute;
`scripts/audit_kandha_a11y.py` audits keyboard, focus, names and contrast. Records and the
latest counts: [kandha/VALIDATION.md](kandha/VALIDATION.md).
The Windows workflow installs `Kandha-Setup-<version>.exe` on the CI account and loads the
packaged page (`scripts/verify_kandha_windows.ps1`).

`tests/sanket.test.js`, `tests/test_sanket_integration.py` and `python -m scripts.verify_sanket`
cover the voice engine and the companion voice view (see [sanket.md](sanket.md)). The browser check uses a fake microphone
and a stub in place of Whisper, so it verifies timing, voices, cues, exports and CSP, not ASR
or emotion accuracy.

`tests/test_isl_inputs.py` covers the fixed ISL default, old-settings migration,
shared pack selection, mixed scripts/symbols, genuine video byte ranges, all
document adapters, input limits, long plans, and recovery from invalid pose media.
Browser tests exercise text/pose ordering, pause, manual motion and local video
references. Native startup/video checks use the bundled source-labelled assets;
they do not establish signer-reviewed sentence translation accuracy.

The Windows workflow preserves failed-check output in standard artifacts,
summaries and bounded error annotations. Validation uses read-only repository
permissions. Native releases require Windows tests and executable startup to pass.
