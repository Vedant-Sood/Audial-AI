# Indian voice emotion training and evaluation

The 85–90% target remains unverified. This release adds a training path; it does
not claim a new trained Indian voice model. No suitable licensed, multi-speaker
Indian emotion corpus is present in the upload. Model download hosts in this
cloud also require the saved network settings to be applied.

## Dataset requirements

Use genuine emotion-labeled Indian recordings with reuse permission, known
speaker IDs and language metadata. Keep a stable speaker ID across recordings,
sources and augmentations. Indian ASR/TTS audio without emotion labels cannot
supply emotion supervision. Do not infer speaker IDs from filenames if the
provider has not established them.

The six supported labels are angry, disgust, fear, happy, neutral and sad. Use
mono/stereo WAV segments between 0.4 and 30 seconds. The loader resamples to
16 kHz, rejects silent/clipped audio and exact duplicate content, and records
SHA256 hashes. At least 15 speakers and all classes in each partition are needed.
More speakers, recording conditions and naturally occurring speech are needed
for a convincing generalization claim.

Place a JSON manifest beside its recordings:

```json
{
  "name": "Your licensed Indian emotion corpus",
  "source_url": "https://the-dataset-provider.example/corpus",
  "license": "Document the actual reuse license",
  "clips": [
    {"path": "audio/clip.wav", "speaker_id": "stable-speaker-id",
     "label": "happy", "language": "hi", "country": "IN"}
  ]
}
```

This illustrates the schema; it is not a ready-to-train dataset.

## Train and inspect results

From a configured source checkout:

```text
python -m scripts.train_indian_emotion --manifest datasets/my-corpus/manifest.json --output models/indian-run-001
```

The pipeline uses acoustic features shared with inference and compares logistic,
SVM and tree classifiers. Five partitions separate training, validation model
selection, probability fitting, abstention-policy fitting, and final testing.
No speaker crosses those partitions. Splits lacking class coverage fail explicitly.
Use a new output folder for each experiment; an existing model is not overwritten.

`evaluation.json` contains full-test accuracy, macro F1, confusion matrix,
per-class metrics, accepted accuracy/coverage, selected model, and speaker splits.
`provenance.json` retains dataset license, language/country metadata and clip
hashes. `target_met` describes that run's full-test point estimate against 85%;
it is not a guarantee for unseen languages, natural conversations or microphones.
Rejected clips must not be removed when reporting full-test accuracy.

## Activate a trusted result

Only activate a model you trained or otherwise trust: joblib models can contain
Python objects. The activation command verifies its recorded checksum and feature
version, copies it into local application storage, and selects it for the next
session without replacing the bundled baseline:

```text
python -m scripts.activate_emotion --model models/indian-run-001
```

Enable voice emotion estimates in app Settings. To return to the baseline:

```text
python -m scripts.activate_emotion --bundled
```

## Sources inspected during this task

- [Hindi speech research](https://github.com/ankuPRK/Emotion-Recognition-in-Hindi-Speech)
  describes a borrowed two-speaker subset of IITKGP-SEHSC. Its reported
  speaker-specific accuracy cannot establish performance on unseen Indian speakers.
  The inspected README does not supply a reusable corpus release/license.
- [Vaani speech corpus](https://github.com/ghostiee-11/vaani-speech-corpus) describes
  two voices, one per language, and YouTube-sourced audio without Creative Commons
  licensing. It cannot provide the independent-speaker partitions required here.

Neither source was downloaded for training or relabeled as an achieved benchmark.
A licensed, speaker-annotated corpus is the remaining training prerequisite.
