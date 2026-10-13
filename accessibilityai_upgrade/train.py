"""Speaker-disjoint selection, calibration, and untouched test evaluation."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pyarrow.parquet as pq
import scipy
from scipy.optimize import minimize_scalar
from scipy.special import softmax
import sklearn
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from .audio import FEATURE_VERSION, extract_features, read_wav

EMOTIONS = {"ANG": "angry", "DIS": "disgust", "FEA": "fear", "HAP": "happy", "NEU": "neutral", "SAD": "sad"}


def load_features(directory, output):
    manifest = json.loads((directory / "provenance.json").read_text())
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    cache = output / "features.npz"
    if cache.exists():
        with np.load(cache, allow_pickle=False) as saved:
            if str(saved["version"]) == FEATURE_VERSION and str(saved["fingerprint"]) == fingerprint:
                return saved["X"], saved["y"], saved["speakers"], saved["files"], manifest
    vectors, labels, speakers, files = [], [], [], []
    for shard in sorted(directory.glob("*.parquet")):
        parquet = pq.ParquetFile(shard)
        for batch in parquet.iter_batches(batch_size=64):
            for row in batch.to_pylist():
                name = str(row["source_file"])
                code = row["emotion_code"]
                if code not in EMOTIONS:
                    raise ValueError(f"Unknown emotion code in {name}: {code}")
                samples = read_wav(row["audio"]["bytes"])
                vector, _ = extract_features(samples)
                vectors.append(vector)
                labels.append(EMOTIONS[code])
                speakers.append(str(row["actor_id"]))
                files.append(name)
                if len(vectors) % 500 == 0:
                    print(f"Extracted {len(vectors)} clips", flush=True)
    X, y, groups, names = np.array(vectors), np.array(labels), np.array(speakers), np.array(files)
    if len(names) != len(set(names)) or len(X) != 7442 or len(set(groups)) != 91:
        raise ValueError("Unexpected CREMA-D counts or duplicate recordings.")
    np.savez_compressed(cache, X=X, y=y, speakers=groups, files=names, version=FEATURE_VERSION, fingerprint=fingerprint)
    return X, y, groups, names, manifest


def raw_logits(model, X):
    if hasattr(model, "decision_function"):
        return model.decision_function(X)
    return np.log(np.maximum(model.predict_proba(X), 1e-8))


def metrics(y, probabilities, classes, threshold):
    predicted = classes[probabilities.argmax(axis=1)]
    accepted = probabilities.max(axis=1) >= threshold
    result = {"clips": len(y), "accuracy": float(accuracy_score(y, predicted)),
              "balanced_accuracy": float(balanced_accuracy_score(y, predicted)),
              "macro_f1": float(f1_score(y, predicted, average="macro")),
              "log_loss": float(log_loss(y, probabilities, labels=classes)),
              "coverage": float(accepted.mean()), "accepted_clips": int(accepted.sum()),
              "accepted_accuracy": float(accuracy_score(y[accepted], predicted[accepted])) if accepted.any() else None,
              "confusion_matrix": confusion_matrix(y, predicted, labels=classes).tolist(),
              "classification_report": classification_report(y, predicted, labels=classes, output_dict=True, zero_division=0)}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/crema-d")
    parser.add_argument("--output", default="models")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    X, y, speakers, files, provenance = load_features(Path(args.data), output)
    rng = np.random.default_rng(args.seed)
    unique = np.array(sorted(set(speakers)))
    rng.shuffle(unique)
    split_groups = {"train": unique[:63], "validation": unique[63:72], "calibration": unique[72:81], "test": unique[81:]}
    splits = {name: np.flatnonzero(np.isin(speakers, groups)) for name, groups in split_groups.items()}
    for name, indices in splits.items():
        if set(y[indices]) != set(EMOTIONS.values()):
            raise ValueError(f"Missing class in {name}")
    for first, g1 in split_groups.items():
        for second, g2 in split_groups.items():
            if first != second and set(g1) & set(g2):
                raise ValueError("Speaker leakage")
    train, validation, calibration, test = (splits[k] for k in ["train", "validation", "calibration", "test"])
    candidates = {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=3000, random_state=args.seed)),
        "svm": make_pipeline(StandardScaler(), SVC(C=3.0, gamma="scale", decision_function_shape="ovr", random_state=args.seed)),
        "extra_trees": ExtraTreesClassifier(n_estimators=400, min_samples_leaf=3, max_features=0.7, n_jobs=2, random_state=args.seed),
    }
    evaluations, best_score, best_name, best_model = {}, -1, None, None
    for name, model in candidates.items():
        started = time.monotonic()
        model.fit(X[train], y[train])
        prediction = model.predict(X[validation])
        score = float(f1_score(y[validation], prediction, average="macro"))
        evaluations[name] = {"validation_macro_f1": score,
                             "validation_accuracy": float(accuracy_score(y[validation], prediction)),
                             "fit_seconds": round(time.monotonic() - started, 2)}
        print(name, json.dumps(evaluations[name]), flush=True)
        if score > best_score:
            best_score, best_name, best_model = score, name, model
    classes = best_model.classes_
    # SVM OVR outputs include vote ranks, so temperature scaling hides useful
    # margin differences. Fit a probability head on pairwise margins instead.
    if best_name == "svm":
        best_model.set_params(svc__decision_function_shape="ovo")
    probability_fit = np.flatnonzero(np.isin(speakers, split_groups["calibration"][:4]))
    policy = np.flatnonzero(np.isin(speakers, split_groups["calibration"][4:]))
    calibrator = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=3000, random_state=args.seed))
    calibrator.fit(raw_logits(best_model, X[probability_fit]), y[probability_fit])
    if calibrator.classes_.tolist() != classes.tolist():
        raise ValueError("Probability calibration requires every training class.")
    probabilities = calibrator.predict_proba(raw_logits(best_model, X[policy]))
    confidence = probabilities.max(axis=1)
    correct = classes[probabilities.argmax(axis=1)] == y[policy]
    threshold = 1.01  # No qualifying confidence range: always abstain.
    qualifying = []
    for value in np.arange(0.35, 0.96, 0.01):
        mask = confidence >= value
        if mask.sum() < 30:
            continue
        if correct[mask].mean() >= 0.75:
            qualifying.append((int(mask.sum()), float(value)))
    if qualifying:
        threshold = max(qualifying, key=lambda item: (item[0], -item[1]))[1]
    bundle = {"model": best_model, "calibrator": calibrator, "classes": classes.tolist(), "temperature": 1.0,
              "threshold": threshold, "feature_version": FEATURE_VERSION, "feature_count": X.shape[1],
              "scope": "Acted English audio baseline; not validated for meetings or inner emotional states."}
    joblib.dump(bundle, output / "emotion.joblib", compress=3)
    test_probabilities = calibrator.predict_proba(raw_logits(best_model, X[test]))
    test_metrics = metrics(y[test], test_probabilities, classes, threshold)
    calibration_metrics = metrics(y[policy], probabilities, classes, threshold)
    manifest = {name: {"speakers": groups.tolist(), "clips": len(splits[name]),
                       "class_counts": dict(Counter(y[splits[name]].tolist())),
                       "files": files[splits[name]].tolist()} for name, groups in split_groups.items()}
    (output / "splits.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (output / "CREMA-D-LICENSE.txt").write_bytes((Path(args.data) / "CREMA-D-LICENSE.txt").read_bytes())
    report = {"trained_at_utc": datetime.now(timezone.utc).isoformat(), "seed": args.seed,
              "dataset": "CREMA-D", "clips": len(X), "speakers": len(unique), "labels": classes.tolist(),
              "target_labels": "Actor-directed emotion code; not crowd-voted perceived emotion.",
              "feature_version": FEATURE_VERSION, "feature_count": X.shape[1],
              "versions": {"numpy": np.__version__, "scipy": scipy.__version__, "scikit_learn": sklearn.__version__},
              "selection": evaluations, "selected_model": best_name,
              "temperature": None, "abstention_threshold": threshold,
              "probability_method": "Multinomial logistic calibration on margins; four held-out fit actors and five separate policy actors.",
              "calibration_groups": {"probability_fit": split_groups["calibration"][:4].tolist(),
                                     "abstention_policy": split_groups["calibration"][4:].tolist()},
              "threshold_policy": "Largest calibration coverage with >=75% empirical accuracy and >=30 accepted clips; not a guarantee.",
              "calibration": calibration_metrics, "test": test_metrics,
              "uncalibrated_classifier_test_accuracy": float(accuracy_score(y[test], best_model.predict(X[test]))),
              "majority_test_accuracy": float(max(Counter(y[test]).values()) / len(test)),
              "split_summary": {k: {"speakers": len(v["speakers"]), "clips": v["clips"]} for k, v in manifest.items()},
              "limitations": ["Acted speech, twelve English sentences, six classes; no natural meeting validation.",
                              "Pitch and recorded loudness depend on speaker, microphone, language, noise, and health.",
                              "Abstention threshold is estimated on held-out actors; test coverage and accuracy must be reviewed.",
                              "No transcription, punctuation, speaker diarization, or sign-language translation model was trained."]}
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print("TEST", json.dumps(test_metrics), flush=True)


if __name__ == "__main__":
    main()
