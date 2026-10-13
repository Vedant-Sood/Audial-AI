# Dataset inventory for this update

| Dataset | Used in the update | Split and included records |
|---|---|---|
| [CREMA-D](https://github.com/CheyneyComputerScience/CREMA-D) / [pinned mirror](https://huggingface.co/datasets/cfahlgren1/crema-d/tree/b7d5beded69285eb5eb6a1c6894a5b0ad17cab92) | Downloaded all 7,442 clips from 91 actors; trained and calibrated the new optional emotion model. | 5,152 train / 738 validation / 738 calibration / 814 test. Actor-disjoint. Four calibration actors fit probabilities; five separate actors set abstention policy. License, shard hashes, splits and metrics are in models/emotion. |
| [INCLUDE, Zenodo 4010759](https://zenodo.org/records/4010759) | Restored 84 real-video feature sequences and retrained the reconstructed four-label SignGRU. Restored three replay poses; extracted a fourth from the uploaded thank-you video. | 56 train / 12 validation / 16 test. Clip-disjoint, signer independence unverified. Feature NPZ, provenance, sign manifest and replay lexicon included. CC-BY-4.0. |
| [RAVDESS, Zenodo 1188976](https://zenodo.org/records/1188976) | Supplied public speech sample used for actual Whisper/ECAPA/browser validation. Legacy prosody artifacts retained. | Raw RAVDESS audio corpus and its feature NPZ were not available in the uploads, so the original reported 1,440-clip training run was not reproduced here. CC-BY-NC-SA-4.0. |

CREMA-D targets are actor-directed emotion codes, not verified internal emotional states. Its acted English sentences do not establish meeting performance. The mirror's train shard name is not treated as an evaluation split. Separate actor partitions are created by the training script. Raw shards total about 605 MB and are excluded from the deliverable; trained weights and reproducible provenance remain included.

INCLUDE supplies isolated words/phrases, not sentence supervision for fluent ISL translation. Feature normalization is shared with camera inference; raw camera-coordinate poses are used separately for light replay. Adding vocabulary requires licensed media, attribution, correct handedness and signer review. Unknown text remains visible.

Additional candidates include RAVDESS for acted prosody, AMI/VoxConverse/LibriCSS for meeting/overlap evaluation, and IEMOCAP/MSP-Podcast for richer emotion evaluation. Access terms and domain suitability must be checked before use. No new download, training or meeting result from those candidates is claimed. Gated sentence-level ISL resources were not accessed.

datasets_manifest.json records current usage. LICENSE_NOTICES.md distinguishes the application license from dataset and derived-asset terms. Original inspection reports remain historical source records.
