# AccessibilityAI 0.2

A local desktop app and browser companion for meeting captions, Indian Sign Language (ISL) phrase playback, and measured voice features. This update integrates the recovered uploaded project, rather than requiring a separate demonstration app.

## Start on Windows

1. Install Python 3.11 or 3.12 **x64** with the Python launcher.
2. Extract the ZIP and double-click **setup.bat**. It creates `.venv`, installs dependencies and downloads local Whisper, ECAPA and MediaPipe models. Use `setup.bat --cpu` for CPU installation, or `setup.bat --no-models` to download models later from the desktop Models page.
3. Run **run.bat** for the desktop, or **run_browser.bat** for the browser companion at `http://127.0.0.1:8765`. Desktop **Open browser companion** also works and uses the port shown in its address.
4. Choose microphone, system audio, or browser **Share tab or app audio**. For meetings in a browser, select the meeting tab and enable **Share tab audio**.

Nothing starts recording on launch. The ZIP contains source and trained research weights, not a prebuilt Windows executable. Windows device capture, CUDA DLL loading and executable packaging still need local validation.

## What changed

| Capability | Behavior |
|---|---|
| Signs in light | Real upper-body and hand landmarks animate a grid of lights with two states: on and off. The default sign output uses no images or video. |
| Display over other apps | An always-on-top desktop window and Chromium Document Picture-in-Picture keep the latest caption and sign visible. |
| Browser/app audio | Browser microphone or shared audio feeds the desktop's local Whisper engine. Desktop system-audio capture uses the default output's loopback device. Support depends on the OS and browser. |
| Page and app text | The included browser extension opens selected page text in the companion. Desktop **Use clipboard** reads text copied from another app. |
| Meeting captions | Final words retain timestamps and optional session speaker labels. Pitch, recorded level and optional tone estimates are stored separately from spoken words. |
| Exports | WebVTT, SRT, JSON, CSV and text; JSON retains voice metadata. |
| Motion controls | Pause/resume, individual frames, playback speed and reduced motion. Unknown words remain readable. |
| Reliability | Final browser audio packets and queued speech are flushed on Stop; timestamp gaps remain visible; browser windows cannot stop each other's sessions. |

The four bundled ISL phrases are **good evening, good night, pleased, thank you**. Phrase lookup follows spoken order. It does not provide full sentence translation, ISL grammar, or detailed facial expression. The source-labelled poses still need review by fluent ISL users before relying on the light representation for communication.

Enable **Experimental voice-tone estimates** in desktop Settings for the newly trained CREMA-D model; save Settings before starting another session. Speaker backend defaults to **off**. Choose **ecapa** after its model is installed for experimental session speaker labels. ECAPA clustering does not identify real people or reliably separate simultaneous speech.

## Browser extension

In Chrome or Edge, open the Extensions page, enable Developer mode, choose **Load unpacked**, and select `browser-extension`. Start the local companion, select text on a page, and click the extension's **Open page text** button. Its port defaults to 8765; change it if using a desktop-created companion on another port. Without a selection it uses up to 2,000 characters of main page text. It reads a page only after that button is clicked.

## Training and measured results

The new emotion pipeline downloaded and processed **7,442 CREMA-D clips from 91 actors**. Actor-disjoint partitions separate training, model selection, probability fitting, abstention-policy fitting and final testing. Three classifiers were compared on validation actors, and an SVM was selected. Dataset URLs, pinned revision, file hashes, license, splits and results are included in `models/emotion`.

| New experiment | Held-out result | Practical limit |
|---|---|---|
| CREMA-D calibrated emotion output | 51.6% accuracy over 814 clips from 10 actors; macro-F1 0.507 | Acted English speech; no natural meeting validation. |
| CREMA-D accepted tone estimates | 71.5% accuracy on 186 accepted clips; 22.9% coverage | Remaining clips abstain. Confidence and the calibration target are not guarantees. Disabled by default. |
| Rebuilt ISL sign classifier | 16/16 supplied test clips correct; macro-F1 1.0 | Four labels and a very small clip-disjoint split; signer independence is unverified. |

No new ASR or full sign-translation model was trained. Captions use pretrained Whisper. The updated emotion model does not change caption words or assign punctuation from inferred emotion.

## Other operating systems

Use Python 3.11/3.12 in a virtual environment. Install matching `torch==2.8.0` and `torchaudio==2.8.0` for your platform, then `pip install -r requirements.txt`. Download Whisper with `python -m app.main --install-model whisper-tiny`, and run `python -m app.main --browser` or `python -m app.main`. Install ECAPA and the hand/body pose models on Models for their respective features. Linux desktop/pose capture needs the normal Qt, PortAudio, EGL/GLES system libraries.

## Verification and project records

The update passed **29 Python tests and 7 JavaScript tests**, plus real Chromium audio capture through Whisper and ECAPA, floating-panel controls, caption export, and a 390px layout check. The browser transcribed the supplied sample as “Kids are talking by the door.” See `docs/upgrade-browser-validation.json` and `docs/upgrade_notes.md`. These are cloud CPU checks, not measurements of your laptop or a multi-speaker meeting.

Run `python -m pytest -q` and `npm test` for regression checks. Training commands are in `docs/local_training.md`. Privacy and dataset reuse details are in `docs/privacy.md` and `LICENSE_NOTICES.md`.

The uploads restored 106 of 176 paths from the original delivery manifest by SHA256. Missing core modules were reconstructed, and the sign model was retrained against that implementation. `source_restoration.json` documents what was available and repaired. Original benchmark files, old experiment folders and ONNX artifacts remain historical records; current measurements are identified explicitly in the upgrade notes.
