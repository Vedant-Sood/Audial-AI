# Audial-AI 0.5.0 validation status

Working branch: `codex/audial-desktop-upgrade`, based on public 65f6bc0.
The exact missing unpublished handoff is recorded in [source recovery](source_recovery-0.5.0.md).

Development environment: Debian 13 x86_64, Python 3.12.14, Qt/PySide6 6.8.3,
Torch/Torchaudio 2.8.0 CPU, 5 available CPU cores, no GPU or physical capture
hardware. These results do not establish behavior on Windows or an RTX 4060.

- Python regression: 94 passed; Node regression: 19 passed.
- Real offscreen native startup, bundled ISL playback and silence abstention: passed.
- Real Chromium page checks at 1280x900 and 390x844: passed; no JavaScript errors
  or horizontal overflow. Desktop screenshots reviewed at 1160x800 and 900x640;
  final screenshots and broader keyboard/error review are still being refreshed.
- Actual WavLM encoder download (1,261,964,375 bytes), authoritative SHA256,
  selected-head activation and real supplied-speech inference: passed offline.
- Full public catalogue setup: incomplete. Hugging Face and Google model hosts
  return enforced proxy HTTP 403. Gates remain Needs action; not silently ready.
- Actual extension tab/audio capture on this cloud Chromium: blocked by managed
  `ExtensionInstallBlocklist: ["*"]`; Chromium explicitly reports unpacked loading
  disabled by administrator policy. Extension/native protocol and lifecycle
  regression tests are separate passing checks, not a real capture substitute.
- Windows installers, first launch, upgrades, uninstall, native PCM capture and
  offline ASR pipeline: awaiting actual Windows Actions acceptance.
- Signing: no certificate configured; installer acceptance requires/report NotSigned.

The same-workload settled Qt caption benchmark uses five batches of 500 rows,
with painting/layout included. Baseline batch times rise from 2.532 to 23.172 s;
updated times are 0.024–0.033 s. Updated view stays at 500 rows while all 2500
captions remain in the session. See the committed JSON for memory and timings.
Browser sustained measurements and final delivery details will be added after
those checks run. No blocked check is counted as passed.
