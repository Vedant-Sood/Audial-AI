# AccessibilityAI 0.2 upgrade record

This update reconstructs missing core modules from the available uploaded project and integrates its actual PySide6 UI, model manager, audio pipeline, ISL assets and training data.

## Changes

- Desktop and browser sign views render actual hand/body landmarks as binary lights. All four included ISL phrases have raw replay poses; the thank-you pose was extracted from the provided video using MediaPipe tasks.
- An always-on-top desktop window and Chromium floating panel share the active sign and latest caption. Motion controls support pause/resume, stepping, speed and reduced motion.
- Explicit microphone, shared browser/tab/app audio and system-loopback sources feed the same local caption engine. Browser Stop flushes its short last packet; the backend drains already captured speech, including capture during model preparation.
- The Chrome/Edge extension passes selected page text to the local companion. Use clipboard supports copied text from other apps. Both retain unknown words and avoid creating artificial ASR transcript entries.
- Captions retain timestamped words, optional session speakers and separate voice metadata. WebVTT/SRT join the existing JSON/CSV/text exports. Completed caption events are retained when transient UI updates fill the event queue.
- Browser requests are local, checked for Host/Origin and assigned a window-specific session ID. Reordered packets are rejected and missing audio preserves timeline gaps.
- A newly trained CREMA-D model is bundled with actor-disjoint splits, calibrated probabilities and an uncertainty threshold. It defaults to off. Inferred emotion never rewrites recognized words.
- Windows setup/launch scripts and the package specification were repaired. Browser launch waits for the server and respects a custom port. The ZIP excludes raw corpora, feature caches, intermediate epoch checkpoints, environments and build output. Selected weights and latest resumable checkpoints remain included.

## Measured verification

29 Python regression tests and 7 Node tests pass. They cover the original app pages/models/configuration, queued-speech shutdown, audio timestamps, loopback failure reporting, binary/visible lights, source vocabulary, floating/manual frames, clipboard text, subtitle/metadata exports, silence abstention, local HTTP controls and final worklet packet flushing.

Chromium captured the supplied public speech recording through its actual getUserMedia/AudioWorklet path, uploaded PCM to the local engine and obtained “Kids are talking by the door.” The same run produced Speaker 1, finite pitch/recorded-level measurements and an uncertain tone estimate. JSON and WebVTT exported the recognized words. Floating controls returned the panel to its origin page, the layout fit 390px without horizontal overflow, and no browser runtime errors occurred. The fake browser audio device supplied the real recording; recognized words came from Whisper, not a scripted transcript.

The small rebuilt sign model correctly classified all 16 supplied test clips; signer independence remains unknown. The emotion model used 7,442 CREMA-D clips; calibrated test accuracy was 51.6% overall, with 71.5% accuracy on 22.9% of clips passing its confidence policy. Models remain experimental. Full evaluation details are in models/emotion/evaluation.json and training/experiments/sign_lights_upgrade/results.json.

## Scope of evidence

Checks ran on Linux CPU and headless Chromium, including a PySide6 offscreen smoke check of all 12 pages and three shared light canvases. They do not establish Windows microphone/loopback behavior, CUDA acceleration, a working Windows executable, sustained meeting latency, speaker-change/overlap accuracy, or natural-meeting emotion recognition.

The new sign network's architecture was reconstructed because its original implementation was missing. It was retrained from scratch. Older sign/prosody experiment folders, research ONNX files and original cloud/local benchmark JSON are historical uploads, with different implementations and measurement contexts. The new bundled sign.pt belongs to sign_lights_upgrade; no regenerated ONNX model or original RAVDESS training result is claimed.

106 of 176 original manifest paths were recoverable by SHA256. source_restoration.json lists that initial state and the files repaired afterward. Some legacy raw-data, tests, packaging and research artifacts remain absent. The shipped core application is validated against the tests and examples above.
