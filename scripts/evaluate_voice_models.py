"""Compare fixed checkpoints on the recorded speaker-disjoint RAVDESS test.

Does not fit, tune, download data, or promote a checkpoint. All files must match
the committed corpus inventory. Run each model in a separate process for memory
and latency measurements. The benchmark was exposed in earlier research; this
is a reproducibility/domain-transfer check, not a fresh blind result.
"""

import argparse
import gc
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import psutil
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

LABELS = ["angry", "disgust", "fear", "happy", "neutral", "sad"]


def evaluate(inventory_path, audio_root, model_path, output):
    from app.inference.emotion import VoiceEmotion
    from accessibilityai_upgrade.audio import read_wav
    from app.models.download import digest_file

    inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    records = [
        record
        for record in inventory["clips"]
        if record["corpus"] == "RAVDESS" and record["partition"] == "test"
    ]
    if len(records) != 264 or len({r["speaker_id"] for r in records}) != 6:
        raise ValueError(
            "Use the fixed 264-clip, six-actor test protocol; do not select clips by results."
        )
    test_speakers = {r["speaker_id"] for r in records}
    other_speakers = {
        r["speaker_id"] for r in inventory["clips"] if r["partition"] != "test"
    }
    if test_speakers & other_speakers:
        raise ValueError("A test speaker is present in a development partition.")
    paths = {}
    for path in Path(audio_root).rglob("*.wav"):
        paths.setdefault(path.name, []).append(path)
    selected_paths = {}
    for record in records:
        candidates = paths.get(Path(record["file"]).name, [])
        matches = [path for path in candidates if digest_file(path) == record["sha256"]]
        if not matches:
            raise ValueError(
                "An evaluation recording is missing or differs from its fixed inventory hash."
            )
        # The mirror has canonical and label-grouped copies. Select by the fixed
        # content hash and count each inventory recording exactly once.
        selected_paths[record["file"]] = matches[0]
    model_path = Path(model_path).resolve()
    training = json.loads(
        (model_path.parent / "evaluation.json").read_text(encoding="utf-8")
    )
    # The original bundled acoustic report predates checksum metadata. Pin its
    # exact released bytes from 65f6bc0, rather than accepting arbitrary joblib.
    expected = training.get("model_sha256")
    if expected is None and training.get("feature_version") == "mfcc-mel-prosody-v1":
        expected = "30b4bf9d08f05c00f80daa6f78e224762cf3bba68a32cb05c2b8ab9cb207807c"
    if expected != digest_file(model_path):
        raise ValueError("Checkpoint differs from its evaluation provenance.")
    load_started = time.perf_counter()
    model = VoiceEmotion(model_path)
    load_seconds = time.perf_counter() - load_started
    predictions = []
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    for index, record in enumerate(records):
        audio = read_wav(selected_paths[record["file"]])
        started = time.perf_counter()
        estimate = model.predict(audio)
        seconds = time.perf_counter() - started
        probabilities = estimate.get("probabilities", {})
        if not set(probabilities).issubset(LABELS):
            raise ValueError("A checkpoint uses a different label task.")
        predicted = estimate.get("top_class") or (
            max(probabilities, key=probabilities.get) if probabilities else "uncertain"
        )
        predictions.append(
            {
                "file": record["file"],
                "speaker_id": record["speaker_id"],
                "label": record["label"],
                "prediction": predicted,
                "accepted": estimate["tone"] != "uncertain",
                "confidence": estimate.get("confidence"),
                "probabilities": probabilities,
                "latency_seconds": seconds,
            }
        )
        peak_rss = max(peak_rss, process.memory_info().rss)
        if (index + 1) % 44 == 0:
            print(
                f"Evaluated {index + 1}/{len(records)} real held-out recordings",
                flush=True,
            )
    y = [record["label"] for record in predictions]
    predicted = [record["prediction"] for record in predictions]
    accepted = np.array([record["accepted"] for record in predictions], dtype=bool)
    latencies = [record["latency_seconds"] for record in predictions]
    try:
        import resource

        peak_rss = max(
            peak_rss,
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if sys.platform == "darwin" else 1024),
        )
    except ImportError:
        peak_rss = max(peak_rss, getattr(process.memory_info(), "peak_wset", 0))
    result = {
        "protocol": "Fixed RAVDESS test from the committed multi-corpus inventory; no fitting or selection in this command",
        "test_exposure": "Previously exposed in 2026-10-14 research; repeated evaluation is not a fresh blind benchmark",
        "speakers": sorted(test_speakers),
        "clips": len(predictions),
        "model_sha256": digest_file(model_path),
        "feature_version": model.model.bundle["feature_version"],
        "inventory_sha256": digest_file(inventory_path),
        "accuracy": float(accuracy_score(y, predicted)),
        "macro_f1": float(
            f1_score(y, predicted, labels=LABELS, average="macro", zero_division=0)
        ),
        "per_class": classification_report(
            y, predicted, labels=LABELS, output_dict=True, zero_division=0
        ),
        "confusion_labels": LABELS + ["uncertain"],
        "confusion_matrix": confusion_matrix(
            y, predicted, labels=LABELS + ["uncertain"]
        ).tolist(),
        "accepted_coverage": float(accepted.mean()),
        "accepted_accuracy": float(
            accuracy_score(np.asarray(y)[accepted], np.asarray(predicted)[accepted])
        )
        if accepted.any()
        else None,
        "latency_seconds": {
            "model_object_load": load_seconds,
            "first_prediction": latencies[0],
            "p50": float(np.median(latencies)),
            "p95": float(np.percentile(latencies, 95)),
        },
        "observed_peak_rss_bytes": peak_rss,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": psutil.cpu_count(),
            "cpu_affinity_count": len(process.cpu_affinity())
            if hasattr(process, "cpu_affinity")
            else None,
            "inference_device": "cpu",
        },
        "dataset_license": "RAVDESS CC-BY-NC-SA-4.0; Livingstone and Russo (2018), doi:10.1371/journal.pone.0196391",
        "limitations": [
            "Acted English speech; Indian voices and natural conversation are not established.",
            "Corpus actor IDs are disjoint; independent human identity matching across corpora is unavailable.",
            "Predictions describe vocal expression and do not establish feelings, intent or health.",
        ],
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (output / "predictions.json").write_text(
        json.dumps(predictions, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "accuracy",
                    "macro_f1",
                    "accepted_coverage",
                    "latency_seconds",
                    "observed_peak_rss_bytes",
                ]
            }
        ),
        flush=True,
    )
    del model
    gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("docs/voice_emotion/multicorpus_inventory.json"),
    )
    parser.add_argument("--audio-root", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evaluate(args.inventory, args.audio_root, args.model, args.output)


if __name__ == "__main__":
    main()
