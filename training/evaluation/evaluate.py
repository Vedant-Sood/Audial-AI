"""Evaluate a checkpoint against the dataset's declared held-out test split."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from app.inference.sign import LocalClassifier
from app.utils.paths import atomic_json
from training.runner import load_data, metrics


def evaluate(checkpoint, data, output=None):
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    classifier = LocalClassifier(checkpoint, state["task"])
    task = classifier.checkpoint["task"]
    x, y, split, labels, provenance = load_data(data, task)
    if labels != classifier.checkpoint["labels"]:
        raise ValueError("Dataset labels and their order must match the checkpoint.")
    mask = split == "test"
    predictions = [labels.index(classifier.predict(values)["label"]) for values in x[mask]]
    result = {"task": task, "test": metrics(y[mask], np.asarray(predictions), len(labels)),
              "labels": labels, "provenance": provenance, "experimental": True}
    if output:
        atomic_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.checkpoint, args.data, args.output), indent=2))


if __name__ == "__main__":
    main()
