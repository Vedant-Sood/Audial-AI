"""Compare additional emotion heads using development speakers only.

This stage never evaluates the test partition. Outputs remain experiments until
the separate evaluation command is run after model and calibration are fixed.
"""
import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.emotion_heads import LayerHeadEnsemble, SpeakerNuisanceProjection
from accessibilityai_upgrade.ssl_features import FEATURE_VERSION, pool_layers, file_sha256
from scripts.train_ssl_emotion import load_features, write_json


def select(manifest_path, feature_folder, output):
    output = Path(output)
    if (output / "evaluation.json").exists() or (output / "selection.json").exists():
        raise ValueError("Use a new folder for an independent development experiment.")
    output.mkdir(parents=True, exist_ok=True)
    f, y, ix, manifest, meta = load_features(manifest_path, feature_folder)
    tr, va = ix["train"], ix["validation"]
    groups = np.array([c["speaker_id"] for c in manifest["clips"]])
    rows, winners, best = [], [], None
    layer_sets = [([12], "mean"), ([14], "mean"),
                  ([8, 12, 16], "concat"), ([12, 14, 16], "concat"),
                  ([4, 8, 12, 16, 20, 24], "concat")]
    for layers, aggregation in layer_sets:
        # Materialize only training and development clips for classifier work.
        Xtr, Xva = (pool_layers(f[indices], layers, aggregation) for indices in [tr, va])
        models = [(f"logistic-C{c}", make_pipeline(StandardScaler(),
                  LogisticRegression(C=c, max_iter=700, random_state=42)))
                  for c in [0.0003, 0.001, 0.003, 0.01]]
        if aggregation == "mean":
            models += [("lda-shrinkage", make_pipeline(StandardScaler(),
                        LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")))]
            models += [(f"projection-{k}-svm", make_pipeline(StandardScaler(),
                        SpeakerNuisanceProjection(k), SVC(C=10, gamma="scale", break_ties=True)))
                       for k in [8, 24]]
        else:
            for n in [128, 512]:
                for whiten in [False, True]:
                    models.append((f"pca-{n}-whiten-{whiten}-logistic", make_pipeline(
                        StandardScaler(), PCA(n_components=n, whiten=whiten,
                            svd_solver="randomized", random_state=42),
                        LogisticRegression(C=0.03 if whiten else 0.001, max_iter=700, random_state=42))))
        winner = None
        for name, model in models:
            start = time.monotonic()
            params = {"speakernuisanceprojection__groups": groups[tr]} if "speakernuisanceprojection" in model.named_steps else {}
            model.fit(Xtr, y[tr], **params)
            pred = model.predict(Xva)
            row = {"model": name, "layers": layers, "aggregation": aggregation,
                   "validation_accuracy": float(accuracy_score(y[va], pred)),
                   "validation_macro_f1": float(f1_score(y[va], pred, average="macro")),
                   "fit_seconds": round(time.monotonic()-start, 2)}
            rows.append(row)
            score = (row["validation_accuracy"], row["validation_macro_f1"])
            member = {"model": model, "layers": layers, "aggregation": aggregation}
            if winner is None or score > winner[0]: winner = (score, member, row)
            if best is None or score > best[0]: best = (score, model, layers, aggregation, row)
            print(json.dumps(row), flush=True)
        winners.append(winner)
    members = [m[1] for m in sorted(winners, key=lambda m: m[0], reverse=True)[:3]]
    ensemble = LayerHeadEnsemble(members, f.shape[1:])
    Xva = np.asarray(f[va]).reshape(len(va), -1)
    pred = ensemble.predict(Xva)
    row = {"model": "refined-soft-vote-3", "layers": list(range(1, 25)), "aggregation": "concat",
           "validation_accuracy": float(accuracy_score(y[va], pred)),
           "validation_macro_f1": float(f1_score(y[va], pred, average="macro"))}
    rows.append(row)
    score = (row["validation_accuracy"], row["validation_macro_f1"])
    if score > best[0]: best = (score, ensemble, row["layers"], "concat", row)
    bundle = {"model": best[1], "layers": best[2], "aggregation": best[3], "name": best[4]["model"],
              "feature_version": FEATURE_VERSION, "encoder": meta["encoder"],
              "encoder_sha256": meta["encoder_sha256"], "precision": meta["precision"],
              "cpu_threads": meta.get("cpu_threads", 4), "dataset": manifest["dataset"]}
    joblib.dump(bundle, output / "selected.joblib", compress=3)
    write_json(output / "selection.json", {"seed":42, "complete":True, "candidates":rows,
               "selected":best[4], "manifest_sha256":file_sha256(manifest_path), "test_used_for_selection":False})
    print(json.dumps({"selected":best[4]}), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--features", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    with threadpool_limits(limits=4):
        select(args.manifest, args.features, args.output)


if __name__ == "__main__": main()
