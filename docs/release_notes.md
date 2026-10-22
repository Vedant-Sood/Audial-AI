## 0.6.0: Kandha (prototype)

Kandha replaces Sanket as the product: see [kandha/RELEASE_NOTES.md](kandha/RELEASE_NOTES.md)
for what is included, what was measured (end-to-end latency, tap budget, accessibility) and what
is simulated. The Sanket wrist band is removed; `/sanket/` redirects to `/kandha/`. New Windows
artifacts: `Kandha-Setup-<version>.exe`, `Kandha-<version>-windows.zip`, with checksums, plus the
stole firmware zip on `kandha-v*` releases. The application version is 0.6.0.

## 0.5.x: Sanket voice view

- Browser capture (companion page and extension tab capture) runs Sanket's voice engine on
  the captured audio:
  - a colour and an arrow per voice;
  - tone cues on screen, by vibration, or on a Sanket Band;
  - an opt-in tone estimate relative to each person's usual voice;
  - an *I want to speak* queue light.
- Events are validated, stored with the session and included in exports. *Unattributed*
  captions are named by voice.
- The full Sanket app is served at `/sanket/` under CSP. It can caption with local Whisper in
  English or Hindi, which is a session-only language choice.
- The new browser tone model (`models/sanket/`) has a SHA-256 check and full provenance. On
  CREMA-D's held-out actors, named estimates were right 98% of the time but cover 4% of
  sentences. It is not validated on Indian or natural conversation.

Audial-AI 0.5.0 improves local setup, notifications, inference scheduling and real
browser integration. See validation-0.5.0.md before distribution: the exact
unpublished October 14 patch archive is still missing. The official source is
on `main`, tagged `v0.5.0`. CPU and NVIDIA artifacts at `b9143e6` passed actual
Windows lifecycle and file/streaming inference. Edge and Chromium browser
acceptance passed on October 21 with the corrected teardown/discard harness;
installer publication requires the current tag's Windows acceptance checks
to pass.

- Per-user CPU/NVIDIA Setup.exe builds, checksums, shortcuts, upgrade/reinstall
  and explicit uninstall data choices. Required runtimes are included.
- Automatic catalogue setup, per-model readiness/progress, verified resumable
  files, offline cache reuse and clear gated-model requirements. Windows
  Credential Manager holds optional Hugging Face access; no datasets are fetched.
- Consistent pointer/pressed/keyboard focus states, smaller-window layouts,
  nonmodal warnings, persistent actionable errors and notification history.
- Bounded incremental transcript rendering and a single asynchronous expression
  worker; captions and objective prosody continue independently of estimates.
- Manifest V3 tab discovery across windows, explicit browser-granted capture,
  native messaging, LIVE indication, source switching and resource cleanup.
- Browser acceptance guards closed targets and records teardown once. Edge
  discard/restore runs after detaching the debugger, with actual API observations
  and matching native bridge updates required before the check can pass.

The same fixed 264-clip/six-actor RAVDESS transfer test scored 18.2% accuracy /
5.1% macro-F1 for the acoustic head and 51.1% / 39.9% for the released WavLM head.
It was previously exposed in research; these are repeated evaluation results.
No new learned checkpoint is promoted, no Indian-conversation accuracy claim is
made, and the unpublished 83.7% research weights remain unavailable. Experimental
vocal-expression output does not establish feelings, intent or health.

The Qt caption batch benchmark improved from 2.53–23.17 s to 24–33 ms; the browser
benchmark from 0.276–1.067 s to 44–69 ms. Both display at most 500 rows while
session exports preserve completed captions. The sustained browser rendering
check processed 87,000 generated captions in 180 s with stable DOM/listener
counts. These Linux rendering measurements do not establish end-to-end ASR,
Windows device latency or RTX 4060 performance.

Installers are unsigned. Browser extension loading requires the browser's
supported explicit developer installation until Store publication. Gated model
acceptance, physical device permission and GPU validation remain distinct steps.
Current cold Windows CPU checks took 4.2–7.4 s to the first caption and 36.9–40.7 s
to its first expression estimate; these are startup-inclusive runner measurements,
not the warm Linux model benchmark or RTX 4060 performance. Captions do not wait
for the slower optional expression result.
