import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import soundfile as sf
from app.audio.features import mfcc_features
from app.utils.paths import atomic_json

LABELS = ["neutral (acted)", "calm (acted)", "happy (acted)", "sad (acted)", "angry (acted)", "fearful (acted)", "disgust (acted)", "surprised (acted)"]


def preprocess(root, output):
    paths = sorted(Path(root).rglob("*.wav"))
    features, targets, splits, groups, files, hashes = [], [], [], [], [], []
    for path in paths:
        codes = path.stem.split("-")
        if len(codes) != 7 or codes[:2] != ["03", "01"]:
            continue
        actor, label = int(codes[-1]), int(codes[2]) - 1
        audio, rate = sf.read(path, dtype="float32")
        features.append(mfcc_features(audio, rate))
        targets.append(label)
        # Actor disjoint: 1-16 training, 17-20 validation, 21-24 test.
        splits.append("train" if actor <= 16 else "val" if actor <= 20 else "test")
        groups.append(str(actor))
        files.append(str(path.relative_to(root)))
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    if not features:
        raise ValueError("No RAVDESS audio-only speech files found")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, X=np.asarray(features), y=np.asarray(targets), split=np.asarray(splits), labels=np.asarray(LABELS), groups=np.asarray(groups))
    atomic_json(output.with_suffix(".json"), {"real_data": True, "source_url": "https://zenodo.org/records/1188976",
        "name": "RAVDESS audio speech", "license": "CC-BY-NC-SA-4.0", "group_disjoint": True,
        "feature_schema": "mfcc40_mean_std_v1", "files": files, "sha256": hashes,
        "split_policy": "actors 1–16 train / 17–20 val / 21–24 test; acted categories, not mental-state inference"})
    print(json.dumps({"samples": len(features), "splits": {s: splits.count(s) for s in set(splits)}}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    preprocess(Path(a.input), a.output)
