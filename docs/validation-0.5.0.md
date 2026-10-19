# Audial-AI 0.5.0 validation status

Working branch: `codex/audial-desktop-upgrade`, based on public 65f6bc0.
The exact missing unpublished handoff is recorded in [source recovery](source_recovery-0.5.0.md).

Development environment: Debian 13 x86_64, Python 3.12.14, Qt/PySide6 6.8.3,
Torch/Torchaudio 2.8.0 CPU, 5 available CPU cores, no GPU or physical capture
hardware. These results do not establish behavior on Windows or an RTX 4060.

- Linux Python regression: 102 passed, one Windows Credential Manager API test
  skipped; Node regression: 19 passed. The preceding Windows CI revision ran
  all 101 tests then present successfully on both runtime variants.
- Real offscreen native startup, bundled ISL playback and silence abstention: passed.
- Real Chromium page checks at 1280x900 and 390x844: passed; no JavaScript errors
  or horizontal overflow. Desktop screenshots reviewed at 1160x800 and 900x640;
  mouse/keyboard focus, smaller-window controls and persistent-error/history screenshots reviewed. Conversation stacks its panels at smaller widths.
- Actual WavLM encoder download (1,261,964,375 bytes), authoritative SHA256,
  selected-head activation and real supplied-speech inference: passed offline.
- Full public catalogue setup: incomplete. Hugging Face and Google model hosts
  return enforced proxy HTTP 403. Gates remain Needs action; not silently ready.
- Actual extension tab/audio capture on this cloud Chromium: blocked by managed
  `ExtensionInstallBlocklist: ["*"]`; Chromium explicitly reports unpacked loading
  disabled by administrator policy. Extension/native protocol and lifecycle
  regression tests are separate passing checks, not a real capture substitute.
- Windows CPU and NVIDIA Setup.exe compilation succeeded in
  [Actions run 39247313393](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39247313393),
  producing 467,814,008-byte and 2,059,306,411-byte unsigned installers. Installed
  acceptance failed; those builds are not published as accepted artifacts.
  First launch, upgrades, uninstall, native PCM capture and the offline ASR
  pipeline still require passing acceptance.
- Signing: no certificate configured; installer acceptance requires/report NotSigned.

The same-workload settled Qt caption benchmark uses five batches of 500 rows,
with painting/layout included. Baseline batch times rise from 2.532 to 23.172 s;
updated times are 0.024–0.033 s. Updated view stays at 500 rows while all 2500
captions remain in the session. See the committed JSON for memory and timings.
The browser same-workload batch comparison includes DOM/layout/paint: baseline
0.276–1.067 s versus 0.044–0.069 s after. During a 180-second accelerated rendering
check, 87,000 generated captions were submitted. The view stayed at 500 rows,
3425 DOM nodes and 53 listeners; retained JS heap moved from 2.094 to 2.157 MB
across sustained samples. These are rendering measurements, not capture/ASR or a
multi-hour physical audio test. Exact data are in browser-performance.json.

Actual Chromium text/document-to-ISL, browser-denied microphone permission,
persistent errors surviving warning expiry, duplicate suppression, desktop/mobile
layout and visible keyboard focus passed. The permission-only test overrides ASR
readiness to reach the actual denial; it starts no ASR or physical microphone.

CI attempts are linked on the branch. Initial runner failures (unavailable
Windows Python patch, then global pipx/filelock contamination) were diagnosed;
Windows builds now use available Python 3.12.10 in an isolated venv. Actual
installer/native capture acceptance is still pending. Acceptance now retains
partial progress, model setup state and worker errors, and publishes failure
excerpts when authenticated Actions logs cannot be reached from this environment.
No blocked check is counted as passed.
