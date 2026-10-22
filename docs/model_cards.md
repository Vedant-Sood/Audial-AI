# Current model cards

## WavLM-Large emotion ensemble, version 0.4

A frozen WavLM-Large encoder feeds three emotion heads selected from 97
development candidates: fused layers with training-only PCA and logistic
classification, a layer-12 SVM with training-speaker nuisance projection, and a
layer-14 logistic classifier. All preprocessing
and classifiers fit 63 training actors. Nine other actors select the model;
four calibrate confidence temperature; five choose its uncertainty threshold.
Positive temperature scaling preserves predicted labels.

The original ten test actors supply 814 clips. Overall accuracy is **80.8%**,
balanced accuracy **81.1%**, macro F1 **81.2%**, and confidence-accepted accuracy
**88.8%** at **81.9% coverage**. The speaker-bootstrap 95% interval for overall
accuracy is **74.9–86.1%**. The requested 85–90% full-test point estimate was not
reached. The benchmark uses actor-directed labels, acted English and twelve
sentences, with no natural-meeting or Indian-language validation.

Emitted-label precision varies by emotion: angry 95.8%, disgust 90.8%, fear
75.4%, happy 97.0%, neutral 95.2%, and sad 82.0%. The 88.8% aggregate does not
mean that every emotion class reaches 85–90% precision.

Weights, calibration, confusion matrix, class metrics, actor results and software
versions are in [models/emotion-wavlm/evaluation.json](../models/emotion-wavlm/evaluation.json).
First-run catalogue setup downloads the original 1.3 GB encoder and verifies SHA-256.
Extraction and inference share BF16 precision and the recorded four-thread CPU
setting. This is classifier transfer learning; the encoder was not fine-tuned.

An independent listener-label experiment is retained under
`models/research/emotion-listener`. It reached 74.3% majority-label agreement
and 56.1% single-label macro F1 on its test actors. Its 6.7% sadness recall makes
it unsuitable as the desktop's selected model. These results measure a different
label target and are separate from the actor-label comparison.

## Sanket browser tone model

48 utterance features, computed by Sanket's JavaScript voice engine (pitch, loudness, MFCC,
spectral shape, voicing), feed two small heads. A general MLP is kept but never named in the
interface. A person-relative MLP sees the features z-scored against that person's earlier
utterances; its "usual voice" baseline is built mostly from calm sentences. Training used the
63 Audial training actors; 9 actors selected the model, 9 calibrated its temperature, and the
10 test actors were held out.

On the test actors, the best guess is 56% over six acted classes. Named estimates (personal,
confidence ≥ 0.80) were right 98% of the time but cover 4% of sentences. Calm-versus-intense
AUC is 0.91. Model-backed "voice rose" / "voice softened" cues gave fewer false and
wrong-direction alerts than loudness/pitch rules (see `models/sanket/evaluation.json`).
On 3.8 minutes of natural calm reading, one emotion was named in 55 stretches and no
rose/softened cue fired.

The model is about 130 KB of JSON and runs in the browser; it is no substitute for the WavLM
ensemble. The benchmark is acted American English, with no Indian-language or meeting
validation. Weights, provenance and SHA-256 are in `models/sanket/`.

## CREMA-D emotion baseline

183 acoustic features feed an SVM chosen on validation actors. A logistic probability head fits margins on four independent calibration actors; five different actors select an uncertainty threshold. Ten test actors are held out. Six actor-directed classes are angry, disgust, fear, happy, neutral and sad. Calibrated overall test accuracy is 51.6%; accepted accuracy is 71.5% at 22.9% coverage. Silence, clipped audio, short/long segments and low confidence abstain. The model is disabled by default and not validated on meetings. Detailed license, data hashes, splits, software versions, confusion matrices and limitations accompany the weights in models/emotion.

## Rebuilt isolated ISL sign model

298,660-parameter bidirectional SignGRU; 48 frames of 196 shoulder-normalized pose features. Real INCLUDE features cover good evening, good night, pleased and thank you. The held-out 16-clip test set was classified correctly, but signer identities were not established. Training/validation/test partitions have 56/12/16 clips. Scores are uncalibrated, unknown signs can be misclassified, and this model is not a sentence translator. Current weights and card are models/research/sign.pt and sign.json.

## Pretrained local models

Whisper tiny/small/medium handles recognition and word timing; no new ASR fine-tuning is claimed. ECAPA embeddings produce experimental session clusters, not real identities. MediaPipe hand/body tasks supply shared pose features and light landmarks. Their source, license, revision and file hashes are recorded on explicit installation by the model manager. Optional Community-1 was not installed or evaluated.

## Historical version 0.3 status

Weights are unchanged from the uploaded baseline. No Indian voice training run
was completed in this task, and 85–90% accuracy on Indian voices is unverified.
The new training and activation commands are documented in indian_voice_training.md.
Current software tests are separate from model accuracy evaluation.


## 0.5.0 acquisition and repeat evaluation

The supported catalogue caches all three Whisper presets, ECAPA, hand/body pose,
WavLM, bundled ISL/acoustic heads, Silero VAD and Windows installed speech voices.
Community-1 remains gated until its terms and token requirements are met; the
full Windows runtime uses preloaded waveform dictionaries instead of an external
file decoder. Community-1 segmentation, embedding and PLDA assets are required;
a config file alone is not ready. Model receipts record exact upstream revisions,
checksums, licenses and preprocessing; downloading never loads all models.

The [0.5.0 repeat evaluation](voice_emotion-0.5.0.md) supplies the same-protocol
RAVDESS comparison, per-class metrics, confusion matrices and actual CPU memory/
latency. It is a previously exposed transfer test, not independent new evidence
for an Indian conversation claim. The single-owner expression worker improves
inference scheduling without changing raw class probabilities or promoting a
new trained model. Previously unpublished research heads remain unpromoted.
