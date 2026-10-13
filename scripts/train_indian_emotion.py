"""Train a local emotion model from licensed, labeled Indian voice recordings.

Use --manifest dataset.json --output models/indian-emotion. Five speaker-disjoint
partitions keep model selection, calibration, policy selection and testing apart.
No data is downloaded implicitly and the bundled model is never overwritten.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from accessibilityai_upgrade.audio import FEATURE_VERSION, extract_features, read_wav
from accessibilityai_upgrade.train import raw_logits, metrics

LABELS = {"angry", "disgust", "fear", "happy", "neutral", "sad"}


def load_dataset(path):
    """Validate provenance and duplicate recordings before any model fitting."""
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not all(isinstance(manifest.get(k), str) and manifest[k].strip()
               for k in ("name", "source_url", "license")):
        raise ValueError("Document the dataset name, source_url and license.")
    records = manifest.get("clips")
    if not isinstance(records, list) or not records:
        raise ValueError("Supply labeled clips, not an empty dataset.")
    features, labels, speakers, details, hashes = [], [], [], [], set()
    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("label") not in LABELS:
            raise ValueError(f"Clip {index}: use one of {sorted(LABELS)}.")
        if record.get("country") != "IN" or not record.get("speaker_id") or not record.get("language"):
            raise ValueError(f"Clip {index}: document country IN, language, and a stable speaker_id.")
        media = (path.parent / record["path"]).resolve()
        if not media.is_relative_to(path.parent) or not media.is_file():
            raise ValueError("All recordings must exist beneath the manifest folder.")
        digest = hashlib.sha256(media.read_bytes()).hexdigest()
        if digest in hashes:
            raise ValueError("Duplicate recording content; remove duplicates before splitting.")
        hashes.add(digest)
        samples = read_wav(media)
        if not 6400 <= len(samples) <= 480000:
            raise ValueError(f"Clip {index}: use segments between 0.4 and 30 seconds.")
        vector, quality = extract_features(samples)
        if quality["rms_dbfs"] < -55 or quality["active_fraction"] < .05 or quality["clipped_fraction"] > .05:
            raise ValueError(f"Clip {index}: silent or clipped audio cannot train an emotion label.")
        features.append(vector); labels.append(record["label"])
        speakers.append(str(record["speaker_id"]))
        details.append({**record, "sha256": digest})
        if (index + 1) % 100 == 0:
            print(f"Extracted {index+1}/{len(records)} recordings", flush=True)
    return np.asarray(features), np.asarray(labels), np.asarray(speakers), details, manifest


def speaker_splits(speakers, labels, seed=42):
    unique = np.array(sorted(set(speakers)))
    if len(unique) < 15:
        raise ValueError("At least 15 speakers are needed for five separate evaluation partitions.")
    unique = np.random.default_rng(seed).permutation(unique)
    size = max(2, len(unique) // 10)
    groups = dict(zip(("validation", "calibration_fit", "calibration_policy", "test"),
                      [unique[i * size:(i + 1) * size] for i in range(4)]))
    groups["train"] = unique[4 * size:]
    splits = {name: np.flatnonzero(np.isin(speakers, ids)) for name, ids in groups.items()}
    classes = set(labels)
    if classes != LABELS:
        raise ValueError("All six supported emotion classes are required.")
    for name, indices in splits.items():
        if set(labels[indices]) != classes:
            raise ValueError(f"{name} lacks an emotion class. Add speaker coverage; do not move test clips into training.")
    return groups, splits


def train(manifest_path, output, seed=42, target=.85):
    X, y, speakers, records, provenance = load_dataset(manifest_path)
    groups, split = speaker_splits(speakers, y, seed)
    output = Path(output)
    if (output / "emotion.joblib").exists():
        raise ValueError("Use a new output directory; an existing trained model will not be replaced.")
    output.mkdir(parents=True, exist_ok=True)
    candidates = {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=2000, class_weight="balanced")),
        "svm_c10": make_pipeline(StandardScaler(), SVC(C=10, gamma="scale", class_weight="balanced")),
        "svm_c30": make_pipeline(StandardScaler(), SVC(C=30, gamma="scale", class_weight="balanced")),
        "trees": ExtraTreesClassifier(n_estimators=400, class_weight="balanced", random_state=seed, n_jobs=4),
    }
    from sklearn.metrics import f1_score
    selection = {}
    for name, model in candidates.items():
        model.fit(X[split["train"]], y[split["train"]])
        score = float(f1_score(y[split["validation"]], model.predict(X[split["validation"]]), average="macro"))
        selection[name] = score
        print(f"{name}: validation macro F1 {score:.3f}", flush=True)
    name = max(selection, key=selection.get)
    model = candidates[name]; classes = model.classes_
    calibration = split["calibration_fit"]
    calibrator = LogisticRegression(C=1, max_iter=2000)
    calibrator.fit(raw_logits(model, X[calibration]), y[calibration])
    if not np.array_equal(calibrator.classes_, classes):
        raise ValueError("Calibration class order differs from the trained model.")
    policy = split["calibration_policy"]
    probabilities = calibrator.predict_proba(raw_logits(model, X[policy]))
    # Abstention never establishes overall target accuracy. Report both accuracy
    # and accepted coverage so rejecting most clips cannot mask a weak model.
    threshold = 1.0
    for cutoff in np.arange(.35, .96, .025):
        accepted = probabilities.max(axis=1) >= cutoff
        if accepted.sum() >= 30 and (classes[probabilities[accepted].argmax(axis=1)] == y[policy][accepted]).mean() >= target:
            threshold = float(cutoff); break
    test = split["test"]
    test_result = metrics(y[test], calibrator.predict_proba(raw_logits(model, X[test])), classes, threshold)
    result = {"trained_at_utc": datetime.now(timezone.utc).isoformat(), "dataset": provenance["name"],
              "seed": seed, "feature_version": FEATURE_VERSION, "selected_model": name,
              "validation_selection": selection, "scikit_learn": sklearn.__version__,
              "target_accuracy": target, "target_met": test_result["accuracy"] >= target,
              "test": test_result, "threshold": threshold,
              "split_summary": {k: {"speakers": ids.tolist(), "clips": len(split[k]),
                                    "labels": dict(Counter(y[split[k]]))} for k, ids in groups.items()},
              "limitations": ["Results apply only to represented Indian speakers, languages and recording conditions.",
                              "Acted emotion labels do not establish a person's emotional state."]}
    bundle = {"model": model, "calibrator": calibrator, "classes": classes.tolist(),
              "feature_version": FEATURE_VERSION, "feature_count": X.shape[1], "threshold": threshold,
              "temperature": 1., "dataset": provenance["name"]}
    joblib.dump(bundle, output / "emotion.joblib", compress=3)
    result["model_sha256"] = hashlib.sha256((output / "emotion.joblib").read_bytes()).hexdigest()
    for filename, data in [("evaluation.json", result), ("provenance.json", {**provenance, "clips": records})]:
        (output / filename).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = train(args.manifest, args.output, args.seed)
    print(json.dumps({"test": result["test"], "target_met": result["target_met"]}, indent=2))


if __name__ == "__main__":
    main()
