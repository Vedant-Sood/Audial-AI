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


def activate(folder, download_encoder=False):
    folder = Path(folder).resolve()
    report = json.loads((folder / "evaluation.json").read_text(encoding="utf-8"))
    model = folder / "emotion.joblib"
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    version = report.get("feature_version")
    if report.get("model_sha256") != digest or version not in {FEATURE_VERSION, "wavlm-layer-mean-std-v1", "ssl-global-temporal-v1", "ssl-acoustic-stack-v1"}:
        raise ValueError("Model checksum or feature version differs from its training report.")
    if not report.get("split_summary") or not isinstance(report.get("test", {}).get("accuracy"), (int, float)):
        raise ValueError("A speaker-disjoint training and test report is required.")
    target = data_root() / "models" / "emotion-user" / digest / "emotion.joblib"
    target.parent.mkdir(parents=True, exist_ok=True)
    if version != FEATURE_VERSION:
        from accessibilityai_upgrade.ssl_features import ENCODERS, file_sha256
        encoder_name, encoder_sha = report["encoder"], report["encoder_sha256"]
        encoder = folder / "encoder.pth"
        destination = target.parent / "encoder.pth"
        if encoder.exists():
            if file_sha256(encoder) != encoder_sha:
                raise ValueError("Encoder checksum differs from its training report.")
            if not destination.exists():
                shutil.copyfile(encoder, destination)
        elif not destination.exists() and download_encoder:
            from urllib.request import urlopen
            temporary = destination.with_suffix(".download")
            try:
                with urlopen(ENCODERS[encoder_name]["url"], timeout=60) as source, temporary.open("wb") as stream:
                    shutil.copyfileobj(source, stream, length=1024*1024)
                if file_sha256(temporary) != encoder_sha:
                    raise ValueError("Downloaded encoder failed checksum verification.")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        if not destination.exists() or file_sha256(destination) != encoder_sha:
            raise ValueError("Verified encoder is missing. Use --download-encoder or include encoder.pth.")
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
    parser.add_argument("--download-encoder", action="store_true",
                        help="Download the pretrained encoder if this verified model needs it.")
    args = parser.parse_args()
    if args.bundled:
        (data_root() / "emotion_selection.json").unlink(missing_ok=True)
        print("Bundled baseline selected for the next session.")
    else:
        print("Selected", activate(args.model, args.download_encoder), "for the next session.")


if __name__ == "__main__":
    main()
