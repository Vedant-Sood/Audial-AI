"""Activate an emotion model that you trained with train_indian_emotion.

Only use trusted locally trained joblib models: that format can contain Python
objects. Evaluation metadata and the model hash are checked before copying.
The previous model remains on disk; --bundled selects the original baseline.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from app.utils.paths import atomic_json, data_root
from accessibilityai_upgrade.audio import FEATURE_VERSION


def activate(folder):
    folder = Path(folder).resolve()
    report = json.loads((folder / "evaluation.json").read_text(encoding="utf-8"))
    model = folder / "emotion.joblib"
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if report.get("model_sha256") != digest or report.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Model checksum or feature version differs from its training report.")
    if not report.get("split_summary") or not isinstance(report.get("test", {}).get("accuracy"), (int, float)):
        raise ValueError("A speaker-disjoint training and test report is required.")
    target = data_root() / "models" / "emotion-user" / digest / "emotion.joblib"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(model, target)
    atomic_json(data_root() / "emotion_selection.json",
                {"path": str(target), "sha256": digest, "dataset": report["dataset"],
                 "test_accuracy": report["test"]["accuracy"], "target_met": report["target_met"]})
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model", type=Path)
    group.add_argument("--bundled", action="store_true")
    args = parser.parse_args()
    if args.bundled:
        (data_root() / "emotion_selection.json").unlink(missing_ok=True)
        print("Bundled baseline selected for the next session.")
    else:
        print("Selected", activate(args.model), "for the next session.")


if __name__ == "__main__":
    main()
