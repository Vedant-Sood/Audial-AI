# Audial-AI 0.5.0 validation

Application/installer source: `b9143e6bf51f97f5f02c4d948cabf244408001d0`, branch
`codex/audial-desktop-upgrade`. The October 21 fixes update browser acceptance
tooling and documentation; application/runtime code is unchanged.
The official source is promoted to `main` and tagged `v0.5.0` on October 21.
The missing unpublished five-commit
archive is described in [source recovery](source_recovery-0.5.0.md); it has not
been merged.

Updated source checks on October 21 passed: 118 Python tests, 19 Node tests,
and native offscreen startup, ISL playback and silence abstention. One Windows
Credential Manager test was skipped on Linux. These checks do not replace
Windows acceptance; see the [tag workflow](https://github.com/Vedant-Sood/Audial-AI/actions/workflows/windows-release.yml)
for the new build's results. The Windows records below describe the October 19
run and retain its original source and outcomes.

## Corrected browser acceptance, October 21

[Windows run 39643199939](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39643199939)
passed both Edge Stable 155.0.4283.62 and Chromium 156.0.8078.4 at source
`92a4e29470de39590cc67ecb741f78529c6fd495`. It builds the product's isolated
native host and tests actual tab discovery, reload/navigation, restricted pages,
OS-toolbar capture grants, 440/1000-Hz PCM identity, switching, Stop, closed-tab
cleanup, extension reload, desktop disconnect/reconnect and suspend/restore.

The Edge test launches a normal browser process and attaches over local CDP.
Before discard it schedules real extension API calls, then detaches Playwright.
Authenticated loopback callbacks report the actual discarded/restored tab IDs
and states; the desktop's native bridge must independently observe both states
and remove the superseded identity. The browser must remain alive, and final
tab removal must succeed. Missing, incorrect or incomplete observations fail
the test. Required browser calls fail clearly on teardown; cleanup skips closed
targets without adding repeated Playwright errors. Twelve regression cases
cover these requirements. No acceptance assertion is waived.

Exact observations: [Edge](validation-0.5.0/windows-browser-edge-teardown-fix.json)
and [Chromium](validation-0.5.0/windows-browser-chromium-teardown-fix.json).
The original attached-debugger failure is retained below as historical evidence.
The tag workflow separately gates publication on complete native installer,
packaged-worker browser transport and installed inference acceptance.

## Actual Windows installers

[Actions run 39313088342](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39313088342)
built both native distributions on Windows Server 2022 x64 / Python 3.12.10.
Each passed regression/source startup, fresh per-user installation, shortcuts
and HKCU native registration, native first launch/automatic setup, the complete
public model catalogue, explicit gated Needs action, actual offline file and
streaming inference, an upgrade fixture, reinstall, offline native relaunch,
default uninstall data preservation, reinstall after uninstall and explicit purge.

| Installer artifact | Artifact ZIP size | Setup.exe SHA256 |
|---|---:|---|
| [CPU](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39313088342/artifacts/12217668150) | 446 MB | `e0f39cd9972f60ef32f61db793a1bfcf83c2ec2d256a0403275e87c071beb8f9` |
| [NVIDIA](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39313088342/artifacts/12218529231) | 1.92 GB | `188ae0695a71864d7947b5da7ce10cac204edb0faa9775214380153cfad6ab6d` |

Artifacts contain Setup.exe, its adjacent checksum, build/dependency/source
metadata and `acceptance-status.json`; retention is 30 days and GitHub sign-in
may be required. Both installers are **NotSigned**. Hash verification identifies
bytes and does not establish a signed publisher. The upgrade fixture uses the
same payload at a newer installer version; historical-binary upgrade remains
unverified. The NVIDIA job has no GPU and explicitly ran inference on CPU;
CUDA execution and RTX 4060 Laptop GPU behavior are untested.

Exact lifecycle/inference records: [CPU](validation-0.5.0/windows-installer-cpu-current.json),
[NVIDIA](validation-0.5.0/windows-installer-nvidia-current.json), and
[artifact ZIP digests/validation downloads](validation-0.5.0/windows-artifacts.json).
Older `windows-offline-cpu.json` and `windows-installer-nvidia.json` retain their
original 104c238 provenance and do not describe these current artifacts.

## Real offline and streaming inference

Both installed worker executables ran actual Whisper ASR, WavLM expression and
objective prosody with socket connections blocked. Both produced “Kids are
talking by the door.” and released their workers/models/capture. The file check
imports the supplied licensed 3.303-second, 48-kHz speech excerpt. The streaming
check resamples it to mono 16 kHz, feeds real-time 20-ms PCM packets through
ExternalAudio/capture/VAD, then exercises live Stop/cleanup. Neither opens a
microphone; the streaming check does not exercise browser transport.

| Installed runtime / fresh worker | First caption | First caption expression | Total |
|---|---:|---:|---:|
| CPU / file | 4.793 s | 38.560 s | 38.600 s |
| CPU / streaming | 7.352 s | 40.670 s | 40.757 s |
| NVIDIA distribution on CPU / file | 4.198 s | 36.865 s | 36.891 s |
| NVIDIA distribution on CPU / streaming | 6.500 s | 38.530 s | 38.702 s |

The expression cold start is substantial on these Windows runners. Captions
arrive independently of the slower optional estimate. These startup-inclusive
numbers are not warm inference throughput, a same-hardware before/after, or
laptop measurements. Warm repeated Windows expression latency is unmeasured.
The earlier Windows result was faster; its distinct source/host timing remains
in the historical report rather than replacing these current observations.

## Actual Chrome/Edge transport

[The full CPU worker check](validation-0.5.0/windows-browser-chromium-current.json)
passed real Chromium 156.0.8078.4 APIs across two browser windows, reload/navigation
identity, restricted pages, OS-toolbar activeTab grants, actual 440/1000-Hz
capture/source switching, Stop, closed-tab cleanup, real extension reload,
desktop disconnect/audio release, automatic fresh-token reconnect and actual
suspend/restore. Discard returned a replacement tab ID; the new ID and removal
of the superseded entry are checked. The real Developer mode setup control is
used. No managed policy is overridden.

Transport tests use generated tones and replace ASR only in that test to isolate
source identity/PCM. They do not fabricate tab discovery or establish browser-ASR
accuracy. Actual inference is checked separately above. The short workflow also
packages the product native-host module independently for faster feedback.

**Historical attached-debugger failure.** Stable 155.0.4283.62 passed
capture/switching/reload/disconnect/reconnect but crashes with process exit
`0xC0000005` on discard under Windows Server/Playwright. A separate minimal
tabs-only extension reproduces it without Audial product JS, audio, native host
or inference, with normal graphics/Windows sandbox and after an official
SHA256/Authenticode-verified Stable update. [Exact evidence](validation-0.5.0/windows-browser-edge.json)
and `scripts/diagnose_browser_discard.py` preserve the reproduction. Physical
Windows laptop behavior is unverified. In that run the CPU job failed and the
NVIDIA job passed, blocking installer publication. Independently passed
installer artifacts record the separate browser outcomes explicitly.

## Development checks and measured limits

Development host: Debian 13 x86_64, Python 3.12.14, PySide6 6.8.3,
Torch/Torchaudio 2.8.0 CPU, five available CPU cores, no GPU or physical capture
hardware. Linux regression: **106 passed, one Windows Credential Manager API
check skipped**. Windows runs all **107** Python tests, including that real API
roundtrip. Node regression: **19 passed**. Dependency checks, actionlint,
PowerShell parsing, native offscreen startup/ISL/silence and real selected WavLM
supplied-speech inference passed.

Native UI screenshots/interactions were reviewed at 1160x800 and 900x640,
including pressed/mouse/keyboard focus, persistent errors/history and smaller
window layouts. Chromium page checks at 1280x900 and 390x844 passed actual
text/document-to-ISL, denied microphone permission, persistent alerts surviving
warning expiry, duplicate suppression, readable keyboard focus and no page errors
or horizontal overflow. The permission-only check overrides ASR readiness solely
to reach the actual denial; it starts no ASR or physical microphone. Hosted
Windows acceptance opened native first-launch/offline-relaunch windows and
captured screenshots; it does not establish physical laptop/DPI/device behavior.

Same-workload settled Qt caption batches (500 rows each, layout/paint included)
improved from 2.532–23.172 s to 0.024–0.033 s. All 2500 completed captions remain
in the session while the view stays at 500 rows. Browser batches improved from
0.276–1.067 s to 0.044–0.069 s. A 180-second accelerated rendering check submitted
87000 generated captions, retaining 500 rows, 3425 DOM nodes and 53 listeners;
settled JS heap moved from 2.094 to 2.157 MB. These are Linux rendering checks,
not multi-hour physical audio, server memory or end-to-end ASR benchmarks.

Three fresh Linux desktop module imports measured 1.841–1.996 s / about 257 MB
RSS before, versus 0.777–0.859 s / about 111 MB after lazy worker imports. This
measures module import, not first paint or Windows startup.

The repeated actor-disjoint 264-clip RAVDESS comparison scored acoustic baseline
18.18% accuracy / 0.0514 macro-F1 versus released WavLM 51.14% / 0.3994. WavLM
Linux CPU median/p95 inference was 0.444/0.553 s, first prediction 6.805 s and
observed peak process RSS 2.911 GB. It is previously exposed transfer data, not a
fresh blind test or a newly trained checkpoint. Per-class metrics, confusion
matrices, train-only provenance and primary references are in
[the model report](voice_emotion-0.5.0.md). No true-feelings, Indian-conversation,
health or target-GPU accuracy claim is made.

The cloud's enforced proxy still blocks full Hugging Face/Google setup and the
Actions API; the saved environment network draft is not applied until Review/Save
and Publish. The managed cloud Chromium blocks unpacked extensions. These local
blocks remain intact; Windows results above came from authorized hosted CI.
Gated Community-1 still needs upstream terms/token, Store extension publication
and application signing are not configured, and physical microphone/camera,
CUDA/VRAM, target-laptop and historical-binary-upgrade checks remain unperformed.
No blocked or unperformed check is counted as passed.
