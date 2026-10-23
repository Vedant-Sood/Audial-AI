# Local installation

For normal Windows use, download a validated CPU or NVIDIA Setup.exe and its
SHA256 from the [Windows Actions workflow](https://github.com/Vedant-Sood/Audial-AI/actions/workflows/windows-release.yml)
or a published release. The installer includes Python, Qt, inference libraries,
Start menu access and uninstall; a separate developer toolchain is unnecessary.
See [current validation](validation-0.5.0.md) for actual platform acceptance.

The default install is per user at `%LOCALAPPDATA%\Programs\AudialAI`, without
administrator rights. Model/settings/session data remain in
`%LOCALAPPDATA%\AccessibilityAI` for upgrade compatibility. An existing
`ACCESSIBILITY_AI_HOME` override remains supported. Upgrades/reinstall preserve
user data. Uninstall keeps it by default; explicit deletion applies to the
standard per-user data folder and removes the saved model credential. Custom
external data paths remain under their owner's control.

First launch starts the complete supported model catalogue in the background.
Use **Setup & models** for progress, pause, retry/resume and gated prerequisites.
About 3.6 GB downloads and 6 GB free for models/staging are estimates; installer
runtime storage is additional, especially for NVIDIA. Cached assets are verified
and reused offline. No training dataset is part of setup. Models load only for
active features. Windows SAPI5 uses installed speech voices; missing voices show
Needs action and direct you to Windows speech settings.

The NVIDIA build contains matching Torch/Torchaudio 2.8.0 CUDA 12.6 runtime DLLs.
A compatible NVIDIA driver is still required. Settings selects Automatic, CPU or
NVIDIA GPU; unavailable acceleration produces a visible CPU fallback. The CPU
build needs no CUDA. No current cloud check proves RTX 4060 Laptop GPU latency.

The installer registers the native messaging host in HKCU for Chrome and Edge.
It does not bypass browser permissions or install an extension silently. Enable
**Developer mode** on the browser's extension page, use **Load unpacked** to select
its `browser-extension` folder, pin it, open the desired tab and invoke the toolbar
action before capture. Developer mode must stay enabled for unpacked extension
reloads. Browser or administrator restrictions still apply.
Enterprise policy may forbid developer extensions; the supported manual source
picker remains available. A Store-signed extension is not published yet.

## Source development and builds

Use Python 3.11/3.12 x64 and `setup.bat --cpu`, then `run.bat`. Source setup creates
`.venv`, installs compatible dependencies and prepares the catalogue unless
`--no-models` is explicitly chosen. First desktop launch also starts catalogue
verification. Source developers wanting Community-1 install
`requirements-overlap.txt`; full native builds include that runtime. Gated model
terms and a local read token are separate user prerequisites.

`run_browser.bat` starts the loopback companion on 8765. The desktop's companion
uses a dynamic loopback port, obtained automatically by its native bridge.
`python -m app.main --kandha` (and `Kandha.exe`) also uses a free port unless
`--port` is given; an explicit `--port`, 8765 included, is always honoured. Source
extension generation uses `python -m scripts.package_extension`; normal installer
users receive that generated folder already.

On a Windows build machine with Inno Setup 6, install `requirements-build.txt`,
then run `build_windows.bat -Runtime CPU` or
`scripts/build_windows.ps1 -Runtime NVIDIA` in the matching runtime environment.
Actions creates an isolated venv and runs regression, native packaging, actual
installer lifecycle and offline inference checks. Build metadata records source,
Python, dependency resolution and compiler versions; adjacent SHA256 files
identify installer bytes. This does not promise byte-identical timestamps across
machines. No signing certificate is configured.
