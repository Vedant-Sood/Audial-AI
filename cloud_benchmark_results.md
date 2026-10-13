# Measured cloud results

Recorded UTC: 2026-10-07T08:12:56.605409+00:00

These results came from the Linux CPU cloud. The target Windows laptop was not inspected or benchmarked. No cloud timing is presented as an RTX 4060 result.

Cloud: AMD EPYC 9V74 80-Core Processor; 9 logical CPUs exposed, 9.73 GiB RAM, Python 3.12.14, Torch 2.6.0+cpu. No NVIDIA/CUDA device.

| Check | Measured result | Practical limit |
|---|---|---|
| Automated tests | 41 passed, 0 failures, 3.828 seconds | Real downloaded ASR/ECAPA plus trained heads; mocks for capture |
| ISL GRU | 15/16 correct; 93.75%; macro-F1 0.9365 | Four classes, 16 test clips, signer independence unverified |
| Prosody MLP | 97/240 correct; 40.42%; macro-F1 0.3561 | Actor-disjoint acted speech; off by default |
| Whisper tiny INT8 | 3 edits / 288 words; WER 1.04%; mean RTF 0.0885 | 48 clean clips, two repeated statements; RTF excludes buffering |
| CPU checkpoint stop/resume | Bitwise-identical weights after 3 epochs | Real RAVDESS features; rotating snapshots retained 2 |
| UI | All 12 pages start/navigate; actual screenshot included | Linux UI does not verify Windows setup or devices |

## Real training

| Model | Train / val / test | Initial → selected-checkpoint train loss | Completed epochs | Best epoch | Training seconds |
|---|---|---|---|---|---|
| sign | 56 / 12 / 16 | 1.400881 → 0.030443 | 26 | 16 | 7.212 |
| prosody | PASS | — | — | — | 659.4492 |

Training times exclude video decoding/pose extraction, audio feature preparation and downloading. Those dominate the end-to-end workflow. Best checkpoints were selected by validation loss before held-out test scoring. Seeds/configs/provenance/histories/confusion matrices are preserved.

## Actual local-file integration on cloud CPU

| Component | Status | Load seconds | Inference seconds | RTF | Process RSS MiB after check |
|---|---|---|---|---|---|
| cuda | SKIP | — | — | — | — |
| whisper | PASS | 0.5304 | 0.5085 | 0.1540 | 451.3828 |
| diarization | PASS | 0.3310 | 0.1524 | — | 659.3516 |
| prosody | PASS | — | — | — | 659.4492 |
| sign_recognition | PASS | — | — | — | 661.4453 |
| webcam_and_pose | SKIP | — | — | — | — |
| microphone | SKIP | — | — | — | — |
| tts | SKIP | — | — | — | — |
| combined_pipeline | PASS | — | — | 0.1588 | 668.5586 |

RAM is cumulative current process RSS after each check, not a per-model allocation or peak. Linux uses /proc/self/status because this cloud PID namespace can make psutil inspect another process. JSON retains wall time and CPU-seconds; CPU-seconds can exceed wall time with multiple threads. Physical capture and output were disabled, so their SKIP rows have no measurement.

## Export / quantization experiment

| Model | Parameters | ONNX FP32 bytes | Dynamic INT8 bytes | Test prediction agreement |
|---|---|---|---|---|
| sign | 298,660 | 1,200,342 | 1,145,670 | 100.00% |
| prosody | PASS | — | — | — | 659.4492 |

FP32 maximum absolute logit differences: sign 0.00000477, prosody 0.00000119. Dynamic INT8 leaves unsupported operators (including much of the GRU) at FP32. Sign test remains 15/16; prosody changes from 97/240 to 98/240 on this fixed test. That one-sample change is not evidence of an improved classifier. No conversion speedup, sustained latency or target-device memory benefit is claimed.

## Outstanding measurements

DER, speaker confusion and overlap precision/recall/F1 require a separately annotated meeting corpus; this project provides a scorer but has no corpus result. Community-1 was not downloaded without gated acceptance. Speech separation, learned continuous ISL translation/generation and a trained enrolled-speaker head are absent. Windows setup/build, devices, SAPI and GPU remain local checks.

See docs/testing.md, docs/limitations.md and the full JSON for scope, skip reasons and source records.

The actual Qt background file pipeline was also verified with network connections blocked. Its public one-actor sample now produces one persistent speaker identity, including the short trailing word. Qt subprocess hardware-check launch passed on Linux. Caption hues passed 4.5:1 white-background contrast checks across 100 generated colours; this is not a full accessibility audit. Windows worker launch remains untested.
