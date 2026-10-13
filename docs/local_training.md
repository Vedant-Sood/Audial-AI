# Training and evaluation

Run commands from the project root in its installed Python environment. Stop live capture before using the desktop training page or training on the same GPU. Use a new output directory for a new experiment. The bundled model's scikit-learn version is pinned to 1.8.0 for serialization compatibility.

## Emotion recognition

```sh
python -m accessibilityai_upgrade.download --output datasets/raw/crema-d
python -m accessibilityai_upgrade.train --data datasets/raw/crema-d --output models/emotion_new
python -m accessibilityai_upgrade.predict assets/evaluation_sample.wav --model models/emotion/emotion.joblib
```

The downloader pins the Hugging Face CREMA-D mirror revision and records every shard's SHA256. Four parquet shards contain all 7,442 clips; their mirror split name is not used as an evaluation split. Training creates deterministic actor-disjoint splits: 63 training actors, 9 validation actors, 9 calibration actors and 10 test actors. Four calibration actors fit probabilities and five separate actors choose an abstention threshold. Test actors are used only for final evaluation. MFCC, mel, spectral, pitch and energy features total 183 values.

The bundled labels are actor-directed emotion codes, not crowd-voted perception, verified internal emotions, or diagnoses. The confidence threshold obtained 75% accuracy on 68 policy clips, but accepted accuracy was 71.5% on the final test set. Keep natural-meeting tone experimental. Include neutral, uncertainty, noisy speech, accents and microphone variation in future evaluation rather than treating pitch as an emotion label.

Raw data and `features.npz` caches are excluded from the distribution. `emotion.joblib`, `evaluation.json`, `splits.json`, `provenance.json` and the upstream license are included. Load only your bundled/trusted joblib file: joblib deserialization executes Python objects.

## Isolated ISL recognition

```sh
python -m training.sign_recognition.train --config training/configs/sign_lights_upgrade.yaml
python -m training.sign_recognition.evaluate --checkpoint models/research/sign.pt --data datasets/sign.npz --output sign_test.json
python -m training.sign_recognition.inference --checkpoint models/research/sign.pt --features assets/sign_evaluation.npy
```

The included real-data feature set contains 84 INCLUDE clips, with 56 training, 12 validation and 16 test clips. Each sequence has 48 frames × 196 features, normalized with `mp_tasks_49x4_shoulder_v1`. It has four labels and no verified signer grouping. The newly reconstructed 298,660-parameter bidirectional GRU is trained from scratch in `training/experiments/sign_lights_upgrade`; `models/research/sign.pt` is its selected validation checkpoint. Older sign experiment files and ONNX exports describe the original implementation and are not updated model exports.

Use an ISL-labelled, licensed video manifest and the shared MediaPipe extractor to expand the vocabulary. Acquire signer annotations and separate signers across partitions before reporting generalization. A larger isolated-sign classifier alone cannot perform sentence translation.

Pose playback uses **raw camera coordinates** `[frames,49,4]`, with x/y in normalized image coordinates and a visibility value. Training features are shoulder-normalized and cannot be substituted directly for replay files. Each lexicon entry must have its gloss, path inside the lexicon folder, frame rate, source URL and license. Keep the handedness/orientation of source videos; review the result with fluent ISL users.

## Optional original research paths

RAVDESS preprocessing remains available in `training.prosody.preprocess`; its raw audio and feature NPZ were not present in the visible uploads. The new default optional tone model uses CREMA-D instead. An enrolled-speaker MLP can train through `training.diarization.train` on declared 192-dimensional ECAPA feature datasets; no new enrolled-speaker classifier was trained here. Existing documentation and experiments referring to missing raw datasets do not establish new measurements.

The shared PyTorch trainer requires real-data source/license metadata, finite features, matching labels/schema and nonempty train/val/test partitions. When `group_disjoint=true`, it rejects group leakage. Resume with `--resume PATH/latest.pt`. Desktop Pause and Stop write control JSON and take effect after an epoch with a saved checkpoint.

For ASR and diarization evaluation, use `scripts.evaluate_speech` with a manifest containing audio paths, reference text and optional reference turns. Its 10-ms turn scorer is limited and is not a substitute for a full standard meeting evaluation. Test timestamp alignment, speaker switching, overlap, background noise, punctuation, latency and transcript completeness on representative meetings before making quality claims.
