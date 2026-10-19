Audial-AI 0.5.0 improves local setup, notifications, inference scheduling and real
browser integration. See validation-0.5.0.md before distribution: the exact
unpublished October 14 patch archive is still missing, and Windows acceptance
must pass for the source revision being distributed.

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
