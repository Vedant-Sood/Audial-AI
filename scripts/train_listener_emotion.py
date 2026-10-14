"""Independent audio-listener benchmark; never replace actor labels silently."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.emotion_heads import ListenerHead
from accessibilityai_upgrade.ssl_features import FEATURE_VERSION, pool_layers, file_sha256
from accessibilityai_upgrade.train import raw_logits
from scripts.train_ssl_emotion import load_features, write_json, cluster_interval

CLASSES = ["angry", "disgust", "fear", "happy", "neutral", "sad"]
CODES = dict(zip("ADFHNS", CLASSES))


def listener_targets(votes_path, clips):
    with Path(votes_path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_file = {}
    for row in rows:
        name = Path(row["FileName"]).stem
        if name in by_file:
            raise ValueError("Duplicate listener annotation identifiers.")
        labels = row["VoiceVote"].split(":")
        if not labels or any(code not in CODES for code in labels):
            raise ValueError("Missing or unknown audio-only listener votes.")
        by_file[name] = {CODES[code] for code in labels}
    target = np.array([[int(label in by_file[Path(c["file"]).stem]) for label in CLASSES] for c in clips])
    if len(by_file) != len(clips) or np.any(target.sum(1) == 0):
        raise ValueError("Listener ratings must cover every original recording.")
    return target


def agreement(targets, predicted_indices):
    return float(targets[np.arange(len(targets)), predicted_indices].mean())


def select(manifest_path, features_path, votes_path, output, focus="wide"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "selected.joblib").exists():
        raise ValueError("Listener selection already exists; choose a new folder.")
    features, _, splits, manifest, metadata = load_features(manifest_path, features_path)
    targets = listener_targets(votes_path, manifest["clips"])
    train, validation = splits["train"], splits["validation"]
    results, best = [], None
    representations = [[8], [12], [16], [20], list(range(4,9))]
    regularization = [0.01, 0.1]
    if focus == "late":
        representations = [[18], [20], [22], [24], list(range(20,25))]
        regularization = [0.001, 0.003, 0.01, 0.03]
    for layers in representations:
        X = pool_layers(features, layers)
        candidates = [(f"listener-logistic-C{c}", make_pipeline(StandardScaler(), ListenerHead(C=c))) for c in regularization]
        if len(layers)>1:
            candidates.append(("listener-neural-256", make_pipeline(StandardScaler(), ListenerHead(neural=True))))
        def fit(candidate):
            name, model = candidate
            model.fit(X[train], targets[train])
            indices = raw_logits(model, X[validation]).argmax(1)
            unambiguous = targets[validation].sum(1) == 1
            result = {"model": name, "layers": layers,
                      "validation_majority_agreement": agreement(targets[validation], indices),
                      "validation_single_label_accuracy": float(accuracy_score(targets[validation][unambiguous].argmax(1), indices[unambiguous])),
                      "validation_single_label_macro_f1": float(f1_score(targets[validation][unambiguous].argmax(1), indices[unambiguous], average="macro"))}
            return model, result
        with ThreadPoolExecutor(max_workers=2) as executor:
            fitted = list(executor.map(fit, candidates))
        for model, result in fitted:
            results.append(result)
            print(json.dumps(result), flush=True)
            score = (result["validation_majority_agreement"], result["validation_single_label_macro_f1"])
            if best is None or score > best:
                best = score
                joblib.dump({"model": model, "layers": layers, "name": result["model"],
                    "aggregation": "mean", "feature_version": FEATURE_VERSION,
                    "encoder": metadata["encoder"], "encoder_sha256": metadata["encoder_sha256"],
                    "precision": metadata["precision"], "cpu_threads": metadata.get("cpu_threads",4),
                    "dataset": "CREMA-D audio-listener ratings", "listener_votes_sha256": file_sha256(votes_path)},
                    output / "selected.joblib", compress=3)
            write_json(output / "selection.json", {"candidates": results, "focus":focus, "test_used_for_selection": False})


def evaluate(manifest_path, features_path, votes_path, output):
    output = Path(output)
    if (output / "evaluation.json").exists():
        raise ValueError("Listener test already evaluated; do not tune against it.")
    features, actor_labels, splits, manifest, metadata = load_features(manifest_path, features_path)
    bundle = joblib.load(output / "selected.joblib")
    if bundle["listener_votes_sha256"] != file_sha256(votes_path):
        raise ValueError("Listener annotations changed after selection.")
    targets = listener_targets(votes_path, manifest["clips"])
    X = pool_layers(features, bundle["layers"])
    fit, policy, test = (splits[k] for k in ["calibration_fit", "calibration_policy", "test"])
    soft_targets = targets[fit] / targets[fit].sum(axis=1, keepdims=True)
    logits = raw_logits(bundle["model"], X[fit])
    objective = lambda value: -float(np.mean(np.sum(soft_targets * np.log(np.maximum(softmax(logits / np.exp(value), axis=1),1e-12)),axis=1)))
    temperature = float(np.exp(minimize_scalar(objective,bounds=(-3,5),method="bounded").x))
    policy_probs = softmax(raw_logits(bundle["model"], X[policy]) / temperature,axis=1)
    correct = targets[policy][np.arange(len(policy)),policy_probs.argmax(1)].astype(bool)
    threshold = 1.01
    for t in np.arange(0.30,1.0,0.01):
        accepted = policy_probs.max(1) >= t
        if accepted.sum() >= 30 and correct[accepted].mean() >= .85:
            threshold = float(t); break
    bundle.update({"classes": CLASSES, "temperature": temperature, "threshold": threshold,
                   "feature_count": X.shape[1], "encoder_file": "encoder.pth",
                   "scope": "Audio-only listener majority labels on acted English CREMA-D."})
    joblib.dump(bundle, output / "emotion.joblib", compress=3)
    probabilities = softmax(raw_logits(bundle["model"], X[test])/temperature,axis=1)
    indices = probabilities.argmax(1)
    correct = targets[test][np.arange(len(test)),indices].astype(bool)
    accepted = probabilities.max(1) >= threshold
    single = targets[test].sum(1) == 1
    speakers = np.array([c["speaker_id"] for c in manifest["clips"]])[test]
    result = {"clips": len(test), "majority_label_agreement": float(correct.mean()),
              "accuracy": float(correct.mean()), "single_label_clips": int(single.sum()),
              "tied_label_clips": int((~single).sum()),
              "single_label_accuracy": float(accuracy_score(targets[test][single].argmax(1),indices[single])),
              "single_label_macro_f1": float(f1_score(targets[test][single].argmax(1),indices[single],average="macro")),
              "single_label_confusion_matrix": confusion_matrix(targets[test][single].argmax(1),indices[single],labels=list(range(6))).tolist(),
              "single_label_classification_report": classification_report(targets[test][single].argmax(1),indices[single],labels=list(range(6)),target_names=CLASSES,output_dict=True,zero_division=0),
              "coverage": float(accepted.mean()), "accepted_clips": int(accepted.sum()),
              "accepted_majority_agreement": float(correct[accepted].mean()) if accepted.any() else None,
              "displayed_label_agreement": float(np.mean(correct & accepted)),
              "majority_neutral_baseline": float(targets[test][:,CLASSES.index('neutral')].mean()),
              "speaker_bootstrap_95_interval": cluster_interval(np.ones(len(test)),correct.astype(int),speakers),
              "actor_directed_accuracy_different_target": float(np.mean(np.array(CLASSES)[indices]==actor_labels[test]))}
    report = {"trained_at_utc": datetime.now(timezone.utc).isoformat(), "dataset":bundle["dataset"],
              "label_source": "VoiceVote from independent audio-only human ratings, including tied majorities",
              "target_basis": "Top-one prediction is one of the majority audio-listener labels on every test clip. This differs from actor-directed classification.",
              "feature_version": FEATURE_VERSION, "encoder":bundle["encoder"], "encoder_sha256":bundle["encoder_sha256"],
              "precision":bundle["precision"], "cpu_threads":bundle["cpu_threads"],
              "layers":bundle["layers"], "aggregation":"mean", "labels":CLASSES,
              "model_sha256":file_sha256(output/'emotion.joblib'), "listener_votes_sha256":bundle["listener_votes_sha256"],
              "split_summary":manifest["splits"], "target_accuracy":.85, "target_met":result["majority_label_agreement"]>=.85,
              "temperature":temperature,"abstention_threshold":threshold,"test":result,
              "selection":json.loads((output/'selection.json').read_text()),
              "limitations":["Listener agreement is a separate target from actor-directed labels; do not compare its percentage directly with the historical 51.6% baseline.",
                  "About half the source recordings are perceived as neutral; inspect minority-class recall and macro F1.",
                  "Acted English speech and a small set of sentences; no natural conversation or Indian language validation."]}
    write_json(output/'evaluation.json',report)
    print(json.dumps(result),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['select','evaluate'])
    parser.add_argument('--focus',choices=['wide','late'],default='wide',help='Development representations; never tune after opening the test report.')
    for key in ['manifest','features','votes','output']:
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    with threadpool_limits(limits=1):
        if args.stage=='select':
            select(args.manifest,args.features,args.votes,args.output,args.focus)
        else:
            evaluate(args.manifest,args.features,args.votes,args.output)


if __name__=='__main__':
    main()
