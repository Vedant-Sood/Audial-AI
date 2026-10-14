# Current limits

- Sign output is known-phrase ISL lookup with four included phrases. It is not full speech-to-ISL sentence translation. Light poses omit detailed facial grammar and require review by fluent signers.
- The sign classifier's 16/16 test result comes from a very small four-class clip-disjoint set. Signer independence is unverified, softmax scores are uncalibrated, and unknown signs may be assigned a known label.
- CREMA-D contains acted English speech with six actor-directed labels. The new model reaches 80.8% overall accuracy; accepted estimates reach 88.8% accuracy at 81.9% coverage. The 85–90% full-test target remains unmet, and natural meetings were not evaluated. Tone defaults to off and never changes caption words.
- Pitch is an estimate of fundamental frequency; recorded level is dBFS, not real-world sound pressure or a measure of emotion. Noise, recording gain, speakers and unvoiced sounds affect measurements.
- Whisper recognition can omit or change words and punctuation. Speaker labels are session-only clusters. The basic ECAPA path uses VAD regions and cannot reliably resolve rapid changes inside continuous speech or simultaneous speakers.
- Browser shared audio and Document Picture-in-Picture depend on OS/browser support. An extension cannot read protected browser pages. System loopback uses the default playback output. Windows device capture, CUDA and executable packaging were not tested on the user's laptop.
- Queue limits protect memory and responsiveness. Slow inference or upload can drop audio with explicit warnings and preserved gaps. Export preserves completed captions, but cannot reconstruct speech that was never processed.
- Opening the companion requires a local Python process. This is not a browser-only standalone model or a remotely hosted web service.
- Older benchmark files and experiment/ONNX artifacts are historical. Core modules were reconstructed from the available uploaded files; missing raw datasets and original implementation details are documented in `source_restoration.json`.
