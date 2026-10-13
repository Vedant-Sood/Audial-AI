"""Run an isolated-sign research checkpoint on preprocessed pose features."""
import argparse
import json
import numpy as np
from app.inference.sign import LocalClassifier

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--threshold", type=float, default=.75)
    args = parser.parse_args()
    features = np.load(args.features, allow_pickle=False)
    print(json.dumps(LocalClassifier(args.checkpoint, "sign").predict(features, args.threshold), indent=2))
