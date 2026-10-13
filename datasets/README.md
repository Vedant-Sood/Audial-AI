# Bundled real feature data

- `sign.npz` and `sign.json`: 84 real INCLUDE videos, four ISL classes, 56 train / 12 val / 16 test. 48 frames, 196 features; byte-deduplicated source clips. Signer independence is not established. `sign_manifest.csv` contains source paths and explicit partitions. CC-BY-4.0 attribution applies.
- `prosody.npz` and `prosody.json`: 1,440 real RAVDESS audio speech clips, 80 MFCC features, actor-disjoint 960 / 240 / 240. CC-BY-NC-SA-4.0 attribution, noncommercial and ShareAlike conditions apply.

The feature sidecars preserve real-data declarations, original hashes, source URLs, schema and split policy. NPZ files load with `allow_pickle=False`. Training rejects missing source/license metadata and non-ISL sign data. These are derived public dataset samples, not fabricated training examples.

Full raw archives are not included. `scripts/download_datasets.py` downloads chosen original archives and checks published checksums. See the root `datasets_manifest.json`, `LICENSE_NOTICES.md` and `docs/local_training.md` for research/access/reproduction details.
