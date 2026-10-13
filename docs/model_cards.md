# Current model cards

## CREMA-D emotion baseline

183 acoustic features feed an SVM chosen on validation actors. A logistic probability head fits margins on four independent calibration actors; five different actors select an uncertainty threshold. Ten test actors are held out. Six actor-directed classes are angry, disgust, fear, happy, neutral and sad. Calibrated overall test accuracy is 51.6%; accepted accuracy is 71.5% at 22.9% coverage. Silence, clipped audio, short/long segments and low confidence abstain. The model is disabled by default and not validated on meetings. Detailed license, data hashes, splits, software versions, confusion matrices and limitations accompany the weights in models/emotion.

## Rebuilt isolated ISL sign model

298,660-parameter bidirectional SignGRU; 48 frames of 196 shoulder-normalized pose features. Real INCLUDE features cover good evening, good night, pleased and thank you. The held-out 16-clip test set was classified correctly, but signer identities were not established. Training/validation/test partitions have 56/12/16 clips. Scores are uncalibrated, unknown signs can be misclassified, and this model is not a sentence translator. Current weights and card are models/research/sign.pt and sign.json.

## Pretrained local models

Whisper tiny/small/medium handles recognition and word timing; no new ASR fine-tuning is claimed. ECAPA embeddings produce experimental session clusters, not real identities. MediaPipe hand/body tasks supply shared pose features and light landmarks. Their source, license, revision and file hashes are recorded on explicit installation by the model manager. Optional Community-1 was not installed or evaluated.

## Version 0.3 status

Weights are unchanged from the uploaded baseline. No Indian voice training run
was completed in this task, and 85–90% accuracy on Indian voices is unverified.
The new training and activation commands are documented in indian_voice_training.md.
Current software tests are separate from model accuracy evaluation.
