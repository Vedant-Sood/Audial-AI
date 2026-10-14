"""Train WavLM emotion classifiers without using test speakers for selection.

Stages separate expensive feature extraction, development selection, and the
single final test evaluation. Raw audio and feature caches stay outside Git.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import joblib
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.linear_model import LogisticRegression
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, f1_score, log_loss
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits
import torch
import torchaudio
import sklearn

from accessibilityai_upgrade.audio import read_wav
from accessibilityai_upgrade.ssl_features import (
    FEATURE_VERSION, PooledEncoder, file_sha256, pool_layers, ENCODERS,
)
from accessibilityai_upgrade.train import EMOTIONS, metrics, raw_logits
from accessibilityai_upgrade.emotion_heads import LayerHeadEnsemble, SpeakerNuisanceProjection, NumericMLPHead


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def prepare_cremad(audio_folder, pointer_folder, split_file, output):
    """Verify mirror WAVs against upstream Git LFS content hashes."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    original = json.loads(Path(split_file).read_text(encoding="utf-8"))
    splits = {name: {"speakers": info["speakers"]} for name, info in original.items()}
    calibration = splits.pop("calibration")
    splits["calibration_fit"] = {"speakers": calibration["speakers"][:4]}
    splits["calibration_policy"] = {"speakers": calibration["speakers"][4:]}
    speaker_partition = {}
    for partition, info in splits.items():
        for speaker in info["speakers"]:
            if speaker in speaker_partition:
                raise ValueError("Speaker leakage in split manifest.")
            speaker_partition[speaker] = partition
    clips, hashes = [], {}
    for path in sorted(Path(audio_folder).glob("*.wav")):
        parts = path.stem.split("_")
        speaker, emotion = parts[0], EMOTIONS[parts[2]]
        pointer = (Path(pointer_folder) / path.name).read_text(encoding="ascii")
        expected = next(line.split(":", 1)[1] for line in pointer.splitlines()
                        if line.startswith("oid sha256:"))
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"Audio differs from upstream hash: {path.name}")
        partition = speaker_partition[speaker]
        if actual in hashes and hashes[actual] != partition:
            raise ValueError(f"Identical audio crosses dataset partitions: {path.name}")
        hashes[actual] = partition
        clips.append({"path": str(path.resolve()), "file": path.name,
                      "label": emotion, "speaker_id": speaker,
                      "partition": partition, "sha256": actual})
    if len(clips) != 7442 or len(speaker_partition) != 91:
        raise ValueError("Expected the complete 7,442-clip, 91-actor CREMA-D corpus.")
    for partition in splits:
        subset = [c for c in clips if c["partition"] == partition]
        if set(c["label"] for c in subset) != set(EMOTIONS.values()):
            raise ValueError(f"Missing emotion in {partition}.")
        splits[partition]["clips"] = len(subset)
    manifest = {"dataset": "CREMA-D", "source_url":
                "https://github.com/CheyneyComputerScience/CREMA-D",
                "download_url": "https://gitlab.com/cs-cooper-lab/crema-d-mirror",
                "license": "ODbL-1.0 / DbCL-1.0", "language": "en",
                "labels": sorted(EMOTIONS.values()), "splits": splits,
                "label_source": "Actor-directed emotion, not crowd-perceived emotion",
                "clips": clips}
    write_json(output / "dataset.json", manifest)
    print(json.dumps({"verified_clips": len(clips), "splits": splits}), flush=True)


def extract(manifest_path, checkpoint, encoder_name, output, threads, device, precision="float32"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(threads)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    digest = file_sha256(checkpoint)
    if digest != ENCODERS[encoder_name]["sha256"]:
        raise ValueError("Checkpoint differs from the registered pretrained encoder.")
    encoder = PooledEncoder(encoder_name, checkpoint, digest, device=device, precision=precision, cpu_threads=threads)
    fingerprint = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    metadata = {"feature_version": FEATURE_VERSION, "manifest_sha256": fingerprint,
                "encoder": encoder_name, "encoder_sha256": digest, "precision": precision, "cpu_threads": threads,
                "shape": [len(manifest["clips"]), encoder.layers, 2, encoder.width],
                "dtype": "float32", "completed": 0}
    progress_path, features_path = output / "features.json", output / "features.npy"
    if progress_path.exists():
        saved = json.loads(progress_path.read_text(encoding="utf-8"))
        # The initial run used the documented four-thread default before this
        # setting was explicitly serialized. Reject other legacy assumptions.
        saved.setdefault("cpu_threads", 4)
        if any(saved[k] != v for k, v in metadata.items() if k != "completed"):
            raise ValueError("Feature cache provenance differs; choose a new folder.")
        metadata = saved
        features = np.load(features_path, mmap_mode="r+")
    else:
        features = np.lib.format.open_memmap(features_path, mode="w+", dtype="float32",
                                            shape=tuple(metadata["shape"]))
        write_json(progress_path, metadata)
    started, initial = time.monotonic(), metadata["completed"]
    for index in range(initial, len(manifest["clips"])):
        clip = manifest["clips"][index]
        if file_sha256(clip["path"]) != clip["sha256"]:
            raise ValueError("Audio changed after dataset verification.")
        features[index] = encoder.extract(read_wav(clip["path"]))
        if (index + 1) % 50 == 0 or index + 1 == len(manifest["clips"]):
            features.flush()
            metadata["completed"] = index + 1
            write_json(progress_path, metadata)
            rate = (index + 1 - initial) / max(time.monotonic() - started, 1e-9)
            print(json.dumps({"completed": index + 1, "clips": len(features),
                              "clips_per_second": round(rate, 2),
                              "estimated_remaining_minutes": round((len(features)-index-1)/rate/60, 1)}), flush=True)


def load_features(manifest_path, feature_folder):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    validate_manifest(manifest)
    folder = Path(feature_folder)
    meta = json.loads((folder / "features.json").read_text(encoding="utf-8"))
    if meta["feature_version"] != FEATURE_VERSION or meta["manifest_sha256"] != file_sha256(manifest_path):
        raise ValueError("Feature provenance differs.")
    if meta["completed"] != len(manifest["clips"]):
        raise ValueError("Feature extraction is incomplete.")
    features = np.load(folder / "features.npy", mmap_mode="r")
    if list(features.shape) != meta["shape"] or features.dtype != np.float32:
        raise ValueError("Feature array shape or dtype differs from its manifest.")
    y = np.array([clip["label"] for clip in manifest["clips"]])
    indices = {k: np.array([i for i, c in enumerate(manifest["clips"]) if c["partition"] == k])
               for k in manifest["splits"]}
    return features, y, indices, manifest, meta


def validate_manifest(manifest):
    """Reject speaker/content leakage even when a manifest was edited by hand."""
    partitions = {"train", "validation", "calibration_fit", "calibration_policy", "test"}
    if set(manifest["splits"]) != partitions:
        raise ValueError("Five independent speaker partitions are required.")
    group_by_speaker, group_by_hash, files = {}, {}, set()
    for name, info in manifest["splits"].items():
        for speaker in info["speakers"]:
            if speaker in group_by_speaker:
                raise ValueError("Speaker leakage across partitions.")
            group_by_speaker[speaker] = name
    for clip in manifest["clips"]:
        partition, speaker = clip["partition"], clip["speaker_id"]
        if group_by_speaker.get(speaker) != partition:
            raise ValueError("Clip speaker differs from its assigned partition.")
        if clip["file"] in files:
            raise ValueError("Duplicate recording identifiers.")
        files.add(clip["file"])
        digest = clip["sha256"]
        if digest in group_by_hash and group_by_hash[digest] != partition:
            raise ValueError("Identical audio crosses partitions.")
        group_by_hash[digest] = partition
    for name in partitions:
        clips = [c for c in manifest["clips"] if c["partition"] == name]
        if set(c["label"] for c in clips) != set(EMOTIONS.values()):
            raise ValueError("Every partition must contain all six emotions.")
        if len(clips) != manifest["splits"][name]["clips"]:
            raise ValueError("Partition clip count differs from its manifest.")


def select(manifest_path, features_path, output, seed, workers=3, resume=False):
    output = Path(output)
    if (output / "selected.joblib").exists() and not resume:
        raise ValueError("Selection already exists; choose a new output directory.")
    if resume and (output / "evaluation.json").exists():
        raise ValueError("Cannot resume selection after the test was evaluated.")
    output.mkdir(parents=True, exist_ok=True)
    features, y, splits, manifest, metadata = load_features(manifest_path, features_path)
    train, validation = splits["train"], splits["validation"]
    # These choices are fixed before evaluation. Test and calibration labels are
    # not supplied to any estimator or model-selection score.
    count = features.shape[1]
    layer_sets = [([k], "mean") for k in range(4, count + 1, 2)]
    layer_sets += [(list(range(4, min(count, 8)+1)), "mean"),
                   (list(range(max(1, count-4), count+1)), "mean"),
                   (list(range(4, count+1, 4)), "concat")]
    evaluations, best, members = [], None, []
    if resume:
        previous = json.loads((output / "selection.json").read_text(encoding="utf-8"))
        if previous.get("complete"):
            raise ValueError("Selection already completed; choose a new experiment.")
        selected = joblib.load(output / "selected.joblib")
        if previous["seed"] != seed or selected["encoder_sha256"] != metadata["encoder_sha256"]:
            raise ValueError("Selection resume settings differ from the original run.")
        if previous.get("manifest_sha256", metadata["manifest_sha256"]) != metadata["manifest_sha256"]:
            raise ValueError("Dataset manifest changed after the original selection.")
        evaluations = previous["candidates"]
        summary = previous["selected"]
        best = ((summary["validation_accuracy"],summary["validation_macro_f1"]),
                selected["model"],selected["layers"],selected["name"],selected["aggregation"])

    def record(model, layers, aggregation, result):
        nonlocal best
        evaluations.append(result)
        print(json.dumps(result), flush=True)
        score = (result["validation_accuracy"], result["validation_macro_f1"])
        if best is None or score > best[0]:
            best = (score, model, layers, result["model"], aggregation)
            joblib.dump({"model": model, "layers": layers, "name": result["model"],
                         "aggregation": aggregation, "feature_version": FEATURE_VERSION,
                         "encoder": metadata["encoder"], "encoder_sha256": metadata["encoder_sha256"],
                         "precision": metadata["precision"], "cpu_threads": metadata.get("cpu_threads", 4),
                         "dataset": manifest["dataset"]},
                        output / "selected.joblib", compress=3)
        write_json(output / "selection.json", {"seed": seed, "candidates": evaluations,
                   "fit_workers": workers, "blas_threads_per_worker": 1,
                   "manifest_sha256": metadata["manifest_sha256"], "complete":False,
                   "selected": {"model": best[3], "layers": best[2], "aggregation": best[4],
                                "validation_accuracy": best[0][0], "validation_macro_f1": best[0][1]},
                   "test_used_for_selection": False})

    for layers, aggregation in layer_sets:
        X = pool_layers(features, layers, aggregation)
        def preprocessing():
            steps = [StandardScaler()]
            if aggregation == "concat":
                steps.append(PCA(n_components=min(256, len(train)-1, X.shape[1]),
                                 whiten=True, svd_solver="randomized", random_state=seed))
            return steps
        candidates = [(f"logistic-C{c}", make_pipeline(*preprocessing(),
                       LogisticRegression(C=c, max_iter=1200, random_state=seed))) for c in [0.01, 0.1, 1.0]]
        candidates += [(f"svm-C{c}", make_pipeline(*preprocessing(),
                        SVC(C=c, gamma="scale", decision_function_shape="ovr", break_ties=True, random_state=seed)))
                       for c in [1.0, 3.0, 10.0]]
        if aggregation == "mean" and (layers in [[8], [12], [16]] or len(layers)>1):
            candidates += [(f"speaker-projection-{n}-svm-C3", make_pipeline(
                StandardScaler(), SpeakerNuisanceProjection(n),
                SVC(C=3.0, gamma="scale", break_ties=True, random_state=seed)))
                for n in [4, 16]]
        if len(layers) > 1 and aggregation == "mean":
            # Internal early-stopping clips belong only to training actors.
            # The external, speaker-disjoint validation split selects the head.
            candidates += [("mlp-256", make_pipeline(StandardScaler(), NumericMLPHead(seed=seed)))]
        member = None
        def fit_candidate(candidate):
            name, model = candidate
            started = time.monotonic()
            fit_params = {}
            if "speakernuisanceprojection" in model.named_steps:
                speakers = np.array([c["speaker_id"] for c in manifest["clips"]])
                fit_params["speakernuisanceprojection__groups"] = speakers[train]
            model.fit(X[train], y[train], **fit_params)
            predicted = model.predict(X[validation])
            result = {"model": name, "layers": layers, "aggregation": aggregation,
                      "validation_accuracy": float(accuracy_score(y[validation], predicted)),
                      "validation_macro_f1": float(f1_score(y[validation], predicted, average="macro")),
                      "fit_seconds": round(time.monotonic()-started, 2)}
            return model, result

        prior = [r for r in evaluations if r["layers"] == layers and r["aggregation"] == aggregation]
        if prior and {r["model"] for r in prior} == {name for name, _ in candidates}:
            winning = max(prior, key=lambda r:(r["validation_accuracy"],r["validation_macro_f1"]))
            estimator = dict(candidates)[winning["model"]]
            members.append(((winning["validation_accuracy"],winning["validation_macro_f1"]),
                            {"model":estimator,"layers":layers,"aggregation":aggregation,"needs_fit":True}))
            continue
        # Independent fits release the GIL in NumPy/libsvm. Limit BLAS to one
        # thread per fit, and preserve candidate order for deterministic ties.
        with ThreadPoolExecutor(max_workers=workers) as executor:
            fitted = list(executor.map(fit_candidate, candidates))
        for model, result in fitted:
            score = (result["validation_accuracy"], result["validation_macro_f1"])
            if member is None or score > member[0]:
                member = (score, {"model": model, "layers": layers, "aggregation": aggregation})
            record(model, layers, aggregation, result)
        members.append(member)
    # A fixed three-member voting option compares different representations.
    # Its uniform weights and membership use validation only, never test scores.
    top = [m[1] for m in sorted(members, key=lambda m: m[0], reverse=True)[:3]]
    for member in top:
        if member.pop("needs_fit",False):
            X_member=pool_layers(features,member["layers"],member["aggregation"])
            fit_params={}
            if "speakernuisanceprojection" in member["model"].named_steps:
                fit_params["speakernuisanceprojection__groups"]=np.array([c["speaker_id"] for c in manifest["clips"]])[train]
            member["model"].fit(X_member[train],y[train],**fit_params)
    ensemble = LayerHeadEnsemble(top, features.shape[1:])
    layers = list(range(1, count+1))
    X = pool_layers(features[validation], layers, "concat")
    predicted = ensemble.predict(X)
    result = {"model": "three-layer-head-ensemble", "layers": layers, "aggregation": "concat",
              "validation_accuracy": float(accuracy_score(y[validation], predicted)),
              "validation_macro_f1": float(f1_score(y[validation], predicted, average="macro")),
              "members": [{"layers": m["layers"], "aggregation": m["aggregation"]} for m in top]}
    record(ensemble, layers, "concat", result)
    finished=json.loads((output / "selection.json").read_text(encoding="utf-8"))
    finished["complete"]=True
    write_json(output / "selection.json",finished)


def cluster_interval(y, predicted, speakers, seed=1729, repeats=5000):
    """Bootstrap entire speakers, preserving dependence among their clips."""
    unique = np.unique(speakers)
    counts = np.array([(np.sum((y == predicted) & (speakers == s)), np.sum(speakers == s)) for s in unique])
    draws = np.random.default_rng(seed).integers(len(unique), size=(repeats, len(unique)))
    resampled = counts[draws].sum(axis=1)
    return np.quantile(resampled[:, 0] / resampled[:, 1], [0.025, 0.975]).tolist()


def evaluate(manifest_path, features_path, output, checkpoint, target=0.85):
    output = Path(output)
    if (output / "evaluation.json").exists():
        raise ValueError("Final test was already evaluated; do not tune against it.")
    features, y, splits, manifest, metadata = load_features(manifest_path, features_path)
    bundle = joblib.load(output / "selected.joblib")
    if file_sha256(checkpoint) != metadata["encoder_sha256"]:
        raise ValueError("Encoder checkpoint differs from extracted features.")
    X = pool_layers(features, bundle["layers"], bundle.get("aggregation", "mean"))
    if bundle["feature_version"] == "ssl-global-temporal-v1":
        from scripts.train_temporal_emotion import temporal_cache
        temporal,tm = temporal_cache(features_path,manifest_path,len(features))
        if tm["layers"] != bundle["temporal_layers"] or tm["bins"] != bundle["temporal_bins"]:
            raise ValueError("Temporal feature settings differ from the selected model.")
        X = np.concatenate([X,np.asarray(temporal,dtype=np.float32).reshape(len(features),-1)],axis=1)
    elif bundle["feature_version"] == "ssl-acoustic-stack-v1":
        from scripts.train_fusion_stack import acoustic_cache
        acoustic = acoustic_cache(manifest_path)
        if acoustic.shape != (len(features),bundle["acoustic_count"]):
            raise ValueError("Acoustic feature dimensions differ from the selected model.")
        X = np.concatenate([X,acoustic],axis=1)
    classes = bundle["model"].classes_
    fit, policy, test = (splits[k] for k in ["calibration_fit", "calibration_policy", "test"])
    # Positive temperature scaling calibrates confidence without changing labels.
    logits = raw_logits(bundle["model"], X[fit])
    objective = lambda log_temperature: log_loss(y[fit], softmax(logits / np.exp(log_temperature), axis=1), labels=classes)
    temperature = float(np.exp(minimize_scalar(objective, bounds=(-3, 5), method="bounded").x))
    policy_probabilities = softmax(raw_logits(bundle["model"], X[policy]) / temperature, axis=1)
    confidence = policy_probabilities.max(axis=1)
    correct = classes[policy_probabilities.argmax(axis=1)] == y[policy]
    threshold = 1.01
    for value in np.arange(0.30, 1.0, 0.01):
        mask = confidence >= value
        if mask.sum() >= 30 and correct[mask].mean() >= target:
            threshold = float(value)
            break
    scope = ("Acted English six-label speech from CREMA-D and RAVDESS."
             if manifest.get("source_corpora") else "Acted English CREMA-D speech.")
    bundle.update({"classes": classes.tolist(), "temperature": temperature, "threshold": threshold,
                   "feature_count": X.shape[1], "encoder_file": "encoder.pth",
                   "scope": scope + " No natural conversation validation."})
    joblib.dump(bundle, output / "emotion.joblib", compress=3)
    # The selected head and all confidence settings are now fixed.
    probabilities = softmax(raw_logits(bundle["model"], X[test]) / temperature, axis=1)
    result = metrics(y[test], probabilities, classes, threshold)
    speakers = np.array([c["speaker_id"] for c in manifest["clips"]])[test]
    predicted = classes[probabilities.argmax(axis=1)]
    accepted = probabilities.max(axis=1) >= threshold
    result["displayed_label_accuracy"] = float(np.mean((predicted == y[test]) & accepted))
    result["speaker_bootstrap_95_interval"] = cluster_interval(y[test], predicted, speakers)
    result["per_speaker_accuracy"] = {s: float(accuracy_score(y[test][speakers == s], predicted[speakers == s])) for s in np.unique(speakers)}
    corpus = np.array([manifest["clips"][int(i)].get("corpus",manifest["dataset"]) for i in test])
    result["per_corpus"] = {}
    for name in np.unique(corpus):
        mask = corpus == name
        details = metrics(y[test][mask],probabilities[mask],classes,threshold)
        details["speaker_bootstrap_95_interval"] = cluster_interval(y[test][mask],predicted[mask],speakers[mask])
        details["speakers"] = np.unique(speakers[mask]).tolist()
        result["per_corpus"][str(name)] = details
    report = {"trained_at_utc": datetime.now(timezone.utc).isoformat(),
              "dataset": manifest["dataset"], "language": manifest["language"],
              "label_source": manifest["label_source"], "labels": classes.tolist(),
              "feature_version": bundle["feature_version"], "encoder": metadata["encoder"],
              "encoder_sha256": metadata["encoder_sha256"], "precision": metadata["precision"],
              "cpu_threads": metadata.get("cpu_threads", 4),
              "model_sha256": file_sha256(output / "emotion.joblib"),
              "feature_count": X.shape[1], "layers": bundle["layers"], "aggregation": bundle["aggregation"],
              "calibration_method": "Positive scalar temperature; preserves argmax labels",
              "temperature": temperature, "abstention_threshold": threshold,
              "target_accuracy": target, "target_met": result["accuracy"] >= target,
              "target_basis": "All test clips, including clips rejected by the confidence policy",
              "selection": json.loads((output / "selection.json").read_text(encoding="utf-8")),
              "fit_partitions": ["train","validation"] if bundle.get("refit_training_and_validation") else ["train"],
              "test_status": manifest.get("test_status",{"CREMA-D":"Previously published baseline test actors"}),
              "source_corpora": manifest.get("source_corpora",[]),
              "calibration_policy": metrics(y[policy], policy_probabilities, classes, threshold),
              "test": result, "split_summary": manifest["splits"],
              "manifest_sha256": file_sha256(manifest_path),
              "versions": {"python": platform.python_version(), "torch": torch.__version__,
                           "torchaudio": torchaudio.__version__, "numpy": np.__version__,
                           "scikit_learn": sklearn.__version__, "platform": platform.platform()},
              "limitations": [scope + " Not Indian or natural meeting validation.",
                              "CREMA-D test actors are the previously published benchmark, reused for comparison only.",
                              "Confidence acceptance accuracy is reported separately and is not the requested full-test accuracy.",
                              "Ten test actors limit precision; a point estimate is not a population guarantee."]}
    write_json(output / "evaluation.json", report)
    write_json(output / "test_predictions.json", [{"file": manifest["clips"][int(i)]["file"],
               "speaker": manifest["clips"][int(i)]["speaker_id"], "true": str(y[i]),
               "predicted": str(predicted[j]), "confidence": float(probabilities[j].max())}
               for j, i in enumerate(test)])
    print(json.dumps({"test": result, "target_met": report["target_met"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "extract", "select", "evaluate"])
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--pointers", type=Path)
    parser.add_argument("--splits", type=Path, default=Path("models/emotion/splits.json"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--encoder", choices=list(ENCODERS), default="WAVLM_BASE_PLUS")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--workers", type=int, default=3, help="Independent classifier fits (1–4).")
    parser.add_argument("--resume-selection", action="store_true", help="Continue an interrupted development-only comparison.")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--precision", choices=["float32", "bfloat16"], default="float32")
    args = parser.parse_args()
    if args.workers not in range(1, 5) or args.threads < 1:
        parser.error("Use 1–4 classifier workers and a positive thread count.")
    required = {
        "prepare": ["audio", "pointers"],
        "extract": ["manifest", "checkpoint"],
        "select": ["manifest", "features"],
        "evaluate": ["manifest", "features", "checkpoint"],
    }
    missing = [f"--{name}" for name in required[args.stage] if getattr(args, name) is None]
    if missing:
        parser.error("Required for this stage: " + ", ".join(missing))
    with threadpool_limits(limits=1 if args.stage == "select" else args.threads):
        run_stage(args)


def run_stage(args):
    if args.stage == "prepare":
        prepare_cremad(args.audio, args.pointers, args.splits, args.output)
    elif args.stage == "extract":
        extract(args.manifest, args.checkpoint, args.encoder, args.output, args.threads, args.device, args.precision)
    elif args.stage == "select":
        select(args.manifest, args.features, args.output, args.seed, args.workers, args.resume_selection)
    else:
        evaluate(args.manifest, args.features, args.output, args.checkpoint)


if __name__ == "__main__":
    main()
