# Audial-AI 0.5.0 validation status

Working branch: `codex/audial-desktop-upgrade`, based on public 65f6bc0.
The exact missing unpublished handoff is recorded in [source recovery](source_recovery-0.5.0.md).

Development environment: Debian 13 x86_64, Python 3.12.14, Qt/PySide6 6.8.3,
Torch/Torchaudio 2.8.0 CPU, 5 available CPU cores, no GPU or physical capture
hardware. These results do not establish behavior on Windows or an RTX 4060.

- Linux Python regression: 106 passed, one Windows Credential Manager API test
  skipped; Node regression: 19 passed. Windows CI ran all 107 Python tests on
  both runtime variants, including the real Credential Manager API check.
- Real offscreen native startup, bundled ISL playback and silence abstention: passed.
- Real Chromium page checks at 1280x900 and 390x844: passed; no JavaScript errors
  or horizontal overflow. Desktop screenshots reviewed at 1160x800 and 900x640;
  mouse/keyboard focus, smaller-window controls and persistent-error/history screenshots reviewed. Conversation stacks its panels at smaller widths.
- Actual WavLM encoder download (1,261,964,375 bytes), authoritative SHA256,
  selected-head activation and real supplied-speech inference: passed offline.
- Full public catalogue setup: passed using the installed Windows executables
  for both runtime variants. This cloud's Hugging Face and Google model hosts
  return enforced proxy HTTP 403, so the same full download is blocked locally.
  Gates remain Needs action; not silently ready.
- Actual extension tab/audio capture on this cloud Chromium: blocked by managed
  `ExtensionInstallBlocklist: ["*"]`; Chromium explicitly reports unpacked loading
  disabled by administrator policy. Extension/native protocol and lifecycle
  regression tests are separate passing checks, not a real capture substitute.
- Windows CPU and NVIDIA Setup.exe compilation succeeded in
  [Actions run 39247313393](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39247313393),
  producing 467,814,008-byte and 2,059,306,411-byte unsigned installers. Installed
  acceptance failed; those builds are not published as accepted artifacts.
  That run did not establish installed lifecycle or native PCM capture.
- The subsequent [CPU run 39252467405](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39252467405/job/118059403371)
  passed 103 Windows tests, actual fresh install, shortcuts/native registration,
  native first launch/automatic setup and the installed startup smoke check.
  Full setup failed while reading Google's repeated checksum headers; WavLM and
  bundled assets installed successfully. The resolver now reads every hash header
  and retains the authoritative MD5 rather than losing it behind the CRC32C field.
- [CPU job 118067771068](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39254818531/job/118067771068)
  then passed 107 Windows tests and the full installed acceptance: fresh install,
  shortcuts/native registration, native first launch, complete public catalogue,
  gated Needs action, actual offline captions/expression/prosody, upgrade fixture,
  reinstall, default data preservation and explicit purge. With sockets blocked,
  the supplied speech produced “Kids are talking by the door.” First caption:
  2.354 s; expression: 5.249 s; total: 5.269 s, with workers released.
  [Exact result](validation-0.5.0/windows-offline-cpu.json). This is hosted Windows
  imported-file inference, not live capture or an RTX 4060 measurement.
- [NVIDIA job 118067771671](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39254818531/job/118067771671)
  also passed the entire installed lifecycle and offline inference, then uploaded
  the [accepted NVIDIA installer artifact](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39254818531/artifacts/12190252072)
  (1.92 GB artifact ZIP, 30-day retention). Its artifact ZIP SHA256 is
  `830fd56c93eae62cef515b4e611f2a8957f38a3f0df0ea944c7e1ff790143da2`;
  the individual installer SHA256 is inside the artifact. The hosted runner has
  no NVIDIA GPU: this validates the CUDA-runtime distribution's CPU fallback,
  not CUDA execution or target-laptop performance.
- The short Windows browser workflow has passed the entire real transport suite
  in [Chromium 156](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39310991766/job/118260199188):
  two-window discovery, reload/navigation identity, restricted pages, 440/1000-Hz
  capture/source switching, Stop, closed-tab cleanup, extension reload, desktop
  disconnect/audio release, fresh-token reconnection and suspension/restoration.
  [Exact result](validation-0.5.0/windows-browser-chromium.json). Discard replaces
  the real tab ID; both its new identity and removal of the old entry are checked.
  Chrome's supported Developer mode UI must be enabled for unpacked reloads.
  Edge 155 has passed the other transport checks. Current Stable 155.0.4283.62
  still crashes with process exit 0xC0000005 during discard. A separate minimal
  tabs-only extension reproduces the crash without any Audial product JS, audio,
  native host or inference, including with normal graphics and Windows sandbox
  settings. This is an external browser/automation environment blocker, not a
  passed suspended-tab check. Physical-laptop behavior is unverified.
  [Reproduction evidence](validation-0.5.0/windows-browser-edge.json).
  The fast workflow packages
  the product native host independently; the release workflow checks the complete
  desktop worker. Generated tones establish transport/source identity, not ASR.
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
Edge suspended-tab acceptance remains blocked as described above. Acceptance retains
partial progress, model setup state and worker errors, and publishes failure
excerpts when authenticated Actions logs cannot be reached from this environment.
No blocked check is counted as passed.

Installer artifacts require successful regression and installed lifecycle plus
offline/streaming inference. Their `acceptance-status.json` includes the separate
browser outcomes. A failed browser check remains a failed job and prevents a
tagged release; it does not discard an independently validated installer.

The installed check also runs `--verify-live-inference`: the supplied recording
is software-fed in real-time 20-ms PCM blocks through the actual capture loop,
VAD, ASR, asynchronous expression/prosody and Stop/cleanup, with sockets blocked.
This additional streaming check has been implemented; a Windows pass is not
claimed until the next installer acceptance run completes. It is separate from
physical microphone capture and the browser transport acceptance above.

Moving the sign classifier import into its owning workers avoids importing
PyTorch during desktop module import. Three fresh processes measured 1.841–1.996 s
and about 257 MB RSS before, versus 0.777–0.859 s and about 111 MB after on this
same Linux CPU host. This measures module import, not first paint, total Windows
launch time or inference. Exact samples are in `startup-import.json`.
