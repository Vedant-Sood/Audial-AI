# AccessibilityAI 0.4.1

A Windows desktop workspace for local captions, Indian Sign Language (ISL) phrase
playback, and optional voice emotion estimates with customizable colors.

## Windows desktop ZIP

Use the native Windows ZIP from the
[GitHub release](https://github.com/Vedant-Sood/Audial-AI/releases/tag/v0.4.1).
Release publication is gated on Windows regression, source startup, native build
and packaged-executable startup checks.
The alternative portable Python ZIP is integrity-checked but was not separately
executed on Windows. See the [validation report](docs/validation-0.3.1.json).

1. Extract the **entire Windows x64 ZIP** to a writable folder.
2. In the native ZIP, double-click **AccessibilityAI.exe**. In the alternative
   portable ZIP, use **Start AccessibilityAI.bat**. Python and native dependencies
   are included; a separate Python installation or `setup.bat` is unnecessary.
3. Open **Advanced tools → Models** and install **Whisper tiny** once for captions.
   After downloading, transcription runs locally. ISL playback uses included assets.
4. Open **Conversation**, choose Microphone or Computer / app audio, and click
   **Start listening**. **ISL with captions** is enabled by default for all audio
   sources. Nothing records automatically when the app launches.
5. In **Settings**, enable optional voice emotion estimates, choose an emotion
   color pool, and save. Stop active capture before saving desktop settings.
6. For the new model, install **WavLM voice emotion (CREMA-D)** in **Advanced
   tools → Models**. This downloads its verified ~1.3 GB encoder once and selects
   the trained classifier for the next session. It needs about 2.7 GB disk space;
   subsequent inference runs locally. The original small baseline stays available.

For a source checkout, install Python 3.11/3.12 x64, run `setup.bat --cpu`, then
`run.bat`. `run_browser.bat` opens the local browser companion. The Windows
portable ZIP and source ZIP are different packages; do not mix their launchers.

[User guide](docs/user_guide.md) · [Development](CONTRIBUTING.md) ·
[Architecture](docs/architecture.md) · [Validation](docs/validation-0.4.1.json)

## What changed

- Everyday navigation stays visible; model tools, training and diagnostics are
  grouped under **Advanced tools**.
- Readable audio-source and language choices replace technical input codes.
- **Voice & emotion** shows a text label, your chosen color, confidence and
  uncertainty. All six emotion colors and the uncertain color persist locally.
- **ISL is the fixed default for every supported input**, independently of the
  speech language. Text, clipboard, page selection, documents, subtitles and
  completed speech captions use one shared local vocabulary and playback plan.
- TXT, Markdown, CSV, HTML, DOCX, text PDFs, SRT/VTT and transcript JSON are
  supported. Included Hindi aliases match their English phrases. Scanned PDFs
  need OCR text; arbitrary image/binary files are not interpreted as speech.
- Known signs and explicit text fallbacks play in input order. Unknown words and
  symbols are retained. Long plans no longer stop at 12/30/100 signs. The same
  explicit limits apply across text inputs: 20,000 characters and 2 MB documents.
- Added ISL packs extend the bundled vocabulary for desktop and browser together.
  Silent dictionary videos can show the original signer in every native display;
  invalid media becomes readable text and subsequent signs continue.
- Audio/video file input can decode WAV, FLAC, OGG, MP3, M4A, MP4, WebM and MKV
  locally using SoundFile/PyAV. Existing caption processing is retained.
- A portable Windows packager verifies the official Python checksum and wheel
  RECORD hashes. A Windows GitHub Actions workflow builds a native executable ZIP.
- An Indian voice training command provides speaker-disjoint selection,
  calibration and held-out evaluation, plus explicit local model activation.

## Model coverage and accuracy

The new WavLM-Large ensemble reaches **80.8% overall accuracy** on 814 clips from
ten held-out CREMA-D actors, compared with **51.6%** for the original calibrated
baseline. Confidence-accepted predictions reach **88.8% accuracy at 81.9% coverage**;
remaining predictions display **uncertain**. Macro F1 is **81.2%**. The 85–90%
target across every clip remains unmet. These measurements use acted English
speech with six actor-directed labels. Indian voices and natural conversations
have not been validated. Emotion estimates remain disabled until enabled.

The bundled ISL vocabulary has **four phrases**: good evening, good night,
pleased, and thank you. Native playback and licensed vocabulary import work;
arbitrary sentence translation, full ISL grammar and detailed facial expression
are not implemented. Text fallback preserves content but is not sign translation.

See [Indian voice training](docs/indian_voice_training.md),
[model cards](docs/model_cards.md), and [limitations](docs/limitations.md).

The [voice emotion accuracy work](docs/voice_emotion_training.md) trained and
compared 97 classifiers with WavLM-Large features on the full verified corpus.
It includes separate selection, calibration and test stages, actor-level
uncertainty intervals, and verified activation of larger pretrained models.

## Verification and release

Run `python -m pytest -q`, `npm test`, and `python -m app.main --smoke-test`.
On headless Linux, use `QT_QPA_PLATFORM=offscreen`. Startup checks exercise native
UI, bundled ISL playback and silence abstention without recording devices.
Current-run results are in `docs/validation-0.4.1.json`; original benchmark and
training records are historical and are not presented as measurements of this
release or your Windows laptop.

The portable package includes Windows binaries assembled on Linux. Compatibility
checks, Windows CI, and real Windows device tests are distinct validation stages;
consult the current report for completed stages. The Windows build workflow
publishes native executable ZIPs only after its Windows checks pass.

Source packaging: `python -m scripts.package_project --output AccessibilityAI-source.zip`.
Portable packaging: `python -m scripts.package_windows_portable --output AccessibilityAI-Windows.zip --cache build-cache`.
Run portable packaging with its cache/output **outside the source checkout**.
Native executable packaging on Windows: `build_windows.bat`.

## Data and licenses

Inference is local; model/dataset downloads require Internet access. No new Indian
voice dataset or model is bundled. Raw training corpora and user recordings are
excluded from release archives. The source import was checked against all 176
uploaded manifest hashes; provenance is in `docs/source_import.json`. The original
0.2 README is preserved in `docs/archive/README-0.2.md`.

Application code retains the included MIT licenses. Models, derived signs,
evaluation speech, Python and dependency binaries retain their own licenses;
preserve [LICENSE_NOTICES.md](LICENSE_NOTICES.md) and the runtime license files.

See [ISL input behavior and vocabulary format](docs/isl.md) for the exact scope.
