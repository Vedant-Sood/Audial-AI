# Accuracy followup: licensed multi-corpus training

The released 0.4.1 voice classifier scores 80.8% on the previously published
814-clip CREMA-D test. The requested 85–90% **all-clip** target is still being
investigated. Development results below are not a claim that this target is met.
The released classifier remains available while the new experiments run.

## Data and scope

The new six-label task combines all 7,442 CREMA-D recordings with the 1,056
RAVDESS speech recordings matching the application's existing labels: angry,
disgust, fear, happy, neutral and sad. Labels describe requested acted
performances. Neither corpus establishes accuracy on natural conversations.

RAVDESS has 1,440 speech files, 24 actors and eight original labels. Calm and
surprise are outside this pre-existing application task; all 384 such recordings
are listed in [the scope manifest](voice_emotion/ravdess_scope.json), rather than
mapped to incorrect labels. Their exclusion was fixed before model development.

RAVDESS audio is CC-BY-NC-SA-4.0. Attribute Livingstone, S. R. and Russo, F. A.
(2018), [DOI 10.1371/journal.pone.0196391](https://doi.org/10.1371/journal.pone.0196391),
and [Zenodo record 1188976](https://zenodo.org/records/1188976). The downloaded
[attributed mirror](https://github.com/ZenvilleErasmus/RAVDESS-emotions-speech-audio-only)
is pinned at `29dc10e08b419f805a29c691c4dbc03da0b2b43e`; its README explicitly
identifies the audio license. Its MIT software license does not replace that
audio license. All 1,440 files were audited as PCM WAVs, canonical identifiers
were checked, and SHA-256s were recorded. Upstream Zenodo checksums could not be
retrieved in this environment; mirror hashes are not claimed to be upstream
checksum verification. No mirror scripts were executed.

CREMA-D retains ODbL-1.0/DbCL-1.0. Its author-mirror recordings were already checked
against all original Git LFS hashes. The [combined inventory](voice_emotion/multicorpus_inventory.json)
records source revisions, every supported recording, and the four duplicate
pairs. All duplicates remain within one actor and partition. Three CREMA-D pairs
have conflicting labels and remain in the benchmark. None are removed according
to prediction errors. Raw audio and feature caches are kept outside Git.

## Speaker partitions

RAVDESS actor assignments use seed 20261014, with equal male/female counts in each
partition. Six new test actors were reserved before feature extraction or model
training. CREMA-D retains the published benchmark actors, whose test results
were previously exposed during the 0.4 work.

| Role | Actors | Recordings |
|---|---:|---:|
| Initial classifier training | 75 | 5,680 |
| Classifier development | 11 | 826 |
| Final base-head refit: training plus development | 86 | 6,506 |
| Confidence temperature fitting | 6 | 416 |
| Confidence acceptance policy | 7 | 498 |
| Final test, all recordings | 16 | 1,078 |

The final test contains 814 CREMA-D and 264 RAVDESS recordings. Reports include
each corpus separately, all-clip accuracy, macro F1, confusion matrices,
accepted accuracy/coverage, and an interval that resamples whole actors.
Confidence rejection does not remove a clip from the target's denominator.

## Training methods

Frozen, checksum-verified WavLM-Large statistics are reused for CREMA-D and
extracted for RAVDESS. The speech encoder is not fine-tuned. The new emotion
heads are trained on the labeled recordings. Encoder BF16 inference uses the
recorded four CPU threads in both caching and desktop inference.

Additional development methods include regularized layer classifiers,
speaker-nuisance projection, a kernel-width/regularization comparison using
reusable RBF matrices, and trainable mixtures of speech-model layers. Neural
heads compare training-only actor-style augmentation; test identities and
other recordings from a test speaker never normalize an inference input.

The fusion stack combines three development-selected kernel heads, a neural
layer-mixture head, and an MFCC/pitch classifier. Five **speaker-grouped** folds
produce base-head predictions on actors excluded from each fit. A regularized
meta-classifier learns from those predictions and pitch/energy features.
Preprocessing is fitted separately inside each fold. Audio hashes also check
that identical recordings cannot cross folds. Final base heads are refitted on
all 86 training/development actors, keeping both confidence partitions and the
test actors separate. An additional neural member is compared before testing.

Meta-classifier cross-validation on OOF base predictions is a **development
diagnostic**, not a fully nested independent benchmark: base configurations
were selected in preceding development experiments. Only the reserved final
test can set `target_met`. The 0.4 classifier scores 71.7% on the new combined
development partition (75.7% CREMA-D; 37.5% RAVDESS). The new kernel development
model scores 77.6% (76.3% CREMA-D; 88.6% RAVDESS). RAVDESS development has two
actors, so these figures have limited precision.

A separate XLS-R-300M research path uses the official Torchaudio checkpoint,
pinned by SHA-256, and adds adaptive temporal pooling and attentive frame heads.
Its extraction is incomplete and it has no evaluated accuracy claim or
published classifier. The historical layer-statistics format name remains
compatible; encoder ID and checksum select the actual backbone explicitly.

## Reproduce the WavLM fusion run

First prepare the verified CREMA-D manifest/features using
[the original training instructions](voice_emotion_training.md). Use the same
Python/Torch/Torchaudio versions recorded in the model report. Example POSIX
paths below keep research data outside this repository.

```bash
git clone --depth 1 https://github.com/ZenvilleErasmus/RAVDESS-emotions-speech-audio-only.git ../ravdess
git -C ../ravdess checkout 29dc10e08b419f805a29c691c4dbc03da0b2b43e
python -m scripts.prepare_multicorpus --crema-manifest ../crema-data/dataset.json --crema-features ../crema-features --ravdess-root ../ravdess --output ../multi-data
python -m scripts.train_ssl_emotion extract --manifest ../multi-data/dataset.json --checkpoint ../encoder.pth --encoder WAVLM_LARGE --precision bfloat16 --output ../multi-data/features --threads 4
python -m scripts.cache_acoustic_emotion --manifest ../multi-data/dataset.json
python -m scripts.train_kernel_emotion --manifest ../multi-data/dataset.json --features ../multi-data/features --output ../multi-kernel --refit-development --threads 3
python -m scripts.train_layer_mix --manifest ../multi-data/dataset.json --features ../multi-data/features --output ../multi-neural --epochs 100 --threads 2
python -m scripts.train_fusion_stack --manifest ../multi-data/dataset.json --features ../multi-data/features --kernel-selection ../multi-kernel/selection.json --output ../multi-fusion --threads 3
python -m scripts.refine_fusion_stack --manifest ../multi-data/dataset.json --features ../multi-data/features --base ../multi-fusion --neural-selection ../multi-neural/selection.json --output ../multi-refined --threads 3
python -m scripts.train_ssl_emotion evaluate --manifest ../multi-data/dataset.json --features ../multi-data/features --checkpoint ../encoder.pth --output ../multi-refined
```

On Windows, the Python commands are identical. The preparation and selection
stages reject overwriting completed experiments. The initial fusion run can
resume interrupted OOF folds with `--resume`; each fold's actor assignments are
saved. Evaluate only after all head and member choices are fixed. Evaluating an
already evaluated output folder is rejected.

## Implementation and validation

- `ssl_features.py`: pinned encoder loading and shared global/temporal extraction.
- `kernel_head.py`: portable precomputed RBF inference using training support vectors.
- `layer_mix.py` and `temporal_head.py`: numerical neural-head state and deterministic evaluation mode.
- `fusion_stack.py`: ordered base predictions and acoustic features for the meta-head.
- `scripts/train_*emotion.py`, `train_fusion_stack.py`, `refine_fusion_stack.py`: development, grouped OOF fitting, and final refits.
- `predict.py` and `activate_emotion.py`: desktop-compatible feature assembly and verified explicit activation.

Validation currently passes 69 Python and 14 browser tests. New tests check
serialized neural logits, support-only versus full-kernel predictions,
temporal preprocessing, and exact assembly of training acoustic features in
desktop inference. The native Windows build and real-waveform verification
will be rerun when a newly evaluated classifier is promoted.
