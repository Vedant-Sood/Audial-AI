# Audial-AI 0.6.0 · with Kandha

A private Windows workspace for local captions, Indian Sign Language (ISL),
objective voice measurements and optional vocal-expression estimates. Processing
uses your computer; no paid inference API is required. Microphone, camera and tab
capture start only when you choose them.

## Kandha: captions, who is speaking, and a haptic scarf

[Kandha](docs/kandha/USER_GUIDE.md) (कंधा, "shoulder") is the app for deaf students who
lip-read, built for Hackcessible India 2026 (Vikram's challenge). It captions the room in the
speaker's colour, shows where each person sits, and taps the **Kandha Stole** on the shoulder
of whoever is speaking; tone cues are felt at the collarbone and a queue pad lights an
*I want to speak* strip. It replaces Sanket as the product and reuses its voice engine.

**Prototype: no hardware needed.** The virtual stole on screen shows every tap and a simulated
stole shows pairing, battery and reconnection. Real Bluetooth and the ESP32-S3 firmware are
prepared but untested with hardware.

- Windows: `Kandha-Setup-<version>.exe` or `Kandha-<version>-windows.zip` from the
  [Windows workflow](https://github.com/Vedant-Sood/Audial-AI/actions/workflows/windows-release.yml)
  artifacts (`Kandha-Windows-x64-CPU`; the first accepted build is on
  [run 39807417445](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39807417445)) or a
  `kandha-v*` [release](https://github.com/Vedant-Sood/Audial-AI/releases); check the `.sha256`
  beside each file. Start-menu entry: **Kandha**. Unsigned, like the Audial-AI installer.
- From source: `python -m app.main --kandha` (also **Kandha** in the desktop navigation, and
  `http://127.0.0.1:<port>/kandha/` in Chrome or Edge).
- Design: [docs/kandha/DESIGN.md](docs/kandha/DESIGN.md) · protocol:
  [PROTOCOL.md](docs/kandha/PROTOCOL.md) · decisions: [decisions/](docs/kandha/decisions/) ·
  measurements: [VALIDATION.md](docs/kandha/VALIDATION.md) · firmware:
  [firmware/kandha/](firmware/kandha/README.md) · demo video script:
  [DEMO_SCRIPT.md](docs/kandha/DEMO_SCRIPT.md).

Audial-AI 0.5.0 is tagged `v0.5.0`, and its CPU and NVIDIA installers are on the
[v0.5.0 release](https://github.com/Vedant-Sood/Audial-AI/releases/tag/v0.5.0).
`main` now carries 0.6.0 (Kandha), which has no tagged release yet. Windows
installer publication runs from a version tag and requires its acceptance checks to pass.

## Windows installation

The normal distribution is a per-user **Setup.exe**, with separate **CPU** and
**NVIDIA** runtimes. The NVIDIA build includes CUDA 12.6 libraries for compatible
NVIDIA drivers and falls back to CPU when the GPU is unavailable. Use it for an
RTX 4060 Laptop GPU; actual performance on that laptop has not been established.
End users do not install Python, Git, Node or build tools.

Download `Audial-AI-0.5.0-Windows-x64-CPU-Setup.exe` (468 MB) or
`Audial-AI-0.5.0-Windows-x64-NVIDIA-Setup.exe` (2.06 GB) and the matching `.sha256`
from the [v0.5.0 release](https://github.com/Vedant-Sood/Audial-AI/releases/tag/v0.5.0),
published on October 21 after the tag's Windows acceptance checks passed. Both
runtime variants also passed installed Windows lifecycle, offline inference and
real software-fed streaming inference at source `b9143e6`; the corrected browser
suite passed Edge and Chromium on October 21. See the
[validation report](docs/validation-0.5.0.md) for its recorded observations.
Untagged builds of `main` are available as `Audial-AI-Windows-x64-*-Setup` artifacts
from [Windows Actions](https://github.com/Vedant-Sood/Audial-AI/actions/workflows/windows-release.yml)
(GitHub sign-in may be required; retention is 30 days); check that run's results
before choosing one. The older 0.4.1 ZIP release does not contain these changes.

1. Check the adjacent `.sha256` with `Get-FileHash`, then run Setup.exe.
   The installer is **unsigned**. Signing status is recorded by acceptance checks.
2. Choose the optional desktop shortcut. Start menu access and uninstall are
   included. Administrator rights are not required for the default location.
3. First launch opens **Setup & models** and starts the full model catalogue.
   Allow about 3.6 GB of downloads and 6 GB free for models and safe staging.
   Pause/retry/resume reuses verified files and partial downloads.
4. Gated Community-1 requires accepting its upstream terms and saving a read
   token through **Save access token**. Windows Credential Manager stores the
   token. Missing access or Windows speech voices remain **Needs action**.
5. Open **Conversation**, select the input and click **Start listening**; or open
   a local recording. Optional vocal-expression estimates are enabled in Settings.

Models, settings, sessions and logs use `%LOCALAPPDATA%\AccessibilityAI`, retained
for compatibility with earlier versions. Upgrades and reinstall preserve them.
Uninstall keeps data by default and asks explicitly before deleting it.

## Real browser tabs

The desktop starts a loopback companion automatically. A normal webpage cannot
enumerate unrelated browser tabs. Audial-AI uses a Manifest V3 Chrome/Edge
extension with native messaging, real tab IDs and browser-granted capture.

The installer provides a `browser-extension` folder and registers the native
bridge for your Windows account. Enable **Developer mode** on
`chrome://extensions` or `edge://extensions`, use **Load unpacked** to choose that
folder, then pin Audial-AI. No Store-signed
extension is published yet. Managed browsers may prohibit developer extensions;
manual **Share tab / app audio** remains available through the supported picker.

Open the desired regular web tab, invoke Audial-AI in its toolbar (Ctrl+Shift+Y),
and click **Capture this tab**. The LIVE badge identifies capture. To change
sources, open the other tab and invoke its toolbar action again. **Stop** releases
tracks and audio resources. The popup lists tabs across windows; the companion
can focus a chosen tab but cannot grant capture permission on your behalf.
Restricted pages explain their limitation. Microphone capture is always explicit.

Chrome for Testing 156 and Edge Stable 155.0.4283.62 passed the full Windows
transport suite, including suspend/restore. The Edge check detaches Playwright
before discarding the tab, then verifies actual browser API observations and
matching native bridge state. This avoids the browser's crash when discarding
a debugged tab. Behavior on a physical Windows laptop is unverified. On `main`,
the installer workflow's Edge capture check (CPU job) now fails on Edge 156
([run 39821972598](https://github.com/Vedant-Sood/Audial-AI/actions/runs/39821972598));
that failure is open.

## Voice view in the companion (who is speaking, tone cues, queue light)

Browser capture also runs the [voice engine](docs/sanket.md) that Kandha uses:
- **Voices:** each voice gets a colour and an arrow on the live panel and in the transcript.
- **Tone cues:** *voice rose*, *voice softened*, *hesitation* and *long silence* show on
  screen (and on the Kandha Stole in the Kandha app).
- **Queue light:** *I want to speak* (Q) lights a strip across the floating panel.
- **Tone estimates:** each voice can be compared with how that person usually sounds.

Open **Voices, queue and tone cues** in the companion. Colours are on by default; cues and tone
estimates are opt-in. Everything runs in the browser on the audio already captured: the
companion page or the extension's offscreen document. Events are stored with the session,
and exports name *Unattributed* captions by voice.

On CREMA-D's 10 test actors, the browser tone model names an emotion only when it is at
least 80% sure. That happens on 4% of sentences, and those names were right 98% of the time.
Its cues reduced false "voice rose" alerts on neutral speech from 12% to 1.5%. On natural calm
reading it named one emotion in 55 stretches and gave no false cues. The tests use acted
American English; there is no Indian-language or natural-conversation validation.

## Responsiveness and notifications

- Intentional keyboard focus replaces duplicate native dotted button outlines;
  pointer, pressed, selected and disabled states use consistent styling.
- Routine warnings appear as nonmodal pop-ups. Failures stay visible with
  recovery actions and a bounded, persistent diagnostic history.
- Device enumeration, model downloads and inference run outside the GUI thread.
  A single bounded worker owns the expression model; captions do not wait for it.
- Desktop and browser display at most 500 caption rows. Complete session exports
  retain every completed caption. Audio and expression queues have backpressure.

## Measured model and feature scope

The released WavLM classifier remains the selected model for automatic setup;
existing explicit user selections are preserved. No new learned checkpoint is
promoted. On the repeated, actor-disjoint RAVDESS transfer test (264 recordings,
6 actors), the acoustic baseline scored **18.2% accuracy / 5.1% macro-F1**;
WavLM scored **51.1% / 39.9%**. WavLM median CPU inference was **444 ms** with
**2.91 GB** observed peak process memory in this Linux environment. This test was
exposed in earlier research and is not a fresh blind benchmark. See the
[protocol, per-class results and confusion matrices](docs/voice_emotion-0.5.0.md).

Historical CREMA-D test results are 51.6% baseline versus 80.8% WavLM accuracy;
they are a different corpus and must not be combined with this comparison.
The missing unpublished October 14 archive reports an unpromoted research result
of 83.7%; its weights and source have not been recovered here. See
[source recovery](docs/source_recovery-0.5.0.md).

Estimates describe uncertain vocal expression, not feelings, intent or health.
Acted English results do not establish Indian-language or natural-conversation
accuracy. Objective pitch and recorded level remain available independently.
ISL has four bundled phrases; unknown content remains readable text. This is not
arbitrary sentence translation or a complete ISL grammar. Licensed vocabulary
imports and the original document/text/audio input features remain available.

## Development and validation

Use Python 3.11/3.12 x64 and `setup.bat --cpu` / `run.bat` on Windows. Source-only
Linux development uses `requirements-cloud.lock` with matching CPU Torch 2.8.0.

```text
python -m pytest -q
npm test
python -m app.main --smoke-test
python -m app.main --setup-models
python -m app.main --verify-inference
python -m app.main --verify-live-inference
python -m scripts.verify_sanket --browser <chromium> --output artifacts/sanket
python -m app.main --kandha-check
python -m scripts.verify_kandha --browser <chromium> --output artifacts/kandha
python -m scripts.audit_kandha_a11y --browser <chromium> --output artifacts/a11y
```

The two inference checks use real local ASR, expression and prosody with socket
connections blocked. The first imports the bundled licensed speech excerpt; the
second sends it in real-time PCM packets through the streaming capture loop.
Neither opens a physical microphone. They require model setup to be complete.
Headless Linux UI checks use `QT_QPA_PLATFORM=offscreen`.

Windows build machines also need Inno Setup 6 and the build dependencies.
`scripts/build_windows.ps1 -Runtime CPU` builds native executables, Setup.exe,
checksums and a dependency/source manifest. The Actions workflow tests fresh
install, native first launch, automatic models, offline inference, upgrade,
reinstall, uninstall/data preservation, and actual extension/native PCM capture.
Publication is gated on these checks. An upgrade fixture uses the same payload
with a newer installer revision; historical-binary upgrade remains separate.

[User guide](docs/user_guide.md) · [Troubleshooting](docs/troubleshooting.md) ·
[Architecture](docs/architecture.md) · [Model cards](docs/model_cards.md) ·
[Validation](docs/validation-0.5.0.md) · [Licenses](LICENSE_NOTICES.md)
