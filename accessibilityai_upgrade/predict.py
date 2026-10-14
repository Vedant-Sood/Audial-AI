"""Inference with explicit abstention; only load the bundled trusted model file."""

import argparse
import json
from pathlib import Path

import joblib
from scipy.special import softmax

from .audio import FEATURE_VERSION, extract_features, read_wav, prosody
from .train import raw_logits


class EmotionModel:
    def __init__(self, model_path):
        self.directory = Path(model_path).resolve().parent
        self.bundle = joblib.load(model_path)
        self.encoder = None
        if self.bundle["feature_version"] not in {FEATURE_VERSION, "wavlm-layer-mean-std-v1"}:
            raise ValueError("Model and acoustic feature versions differ.")

    def predict_samples(self, samples):
        if self.bundle["feature_version"] == FEATURE_VERSION:
            vector, details = extract_features(samples)
        else:
            details = prosody(samples)
            details.pop("_pitch_features")
        if details["rms_dbfs"] < -55 or details["active_fraction"] < 0.05:
            return {"tone": "uncertain", "reason": "insufficient_audio", "confidence": None,
                    "probabilities": {}, "prosody": details}
        if self.bundle["feature_version"] != FEATURE_VERSION:
            from .ssl_features import PooledEncoder, pool_layers
            if self.encoder is None:
                if self.bundle.get("encoder_file") != "encoder.pth":
                    raise ValueError("Emotion encoder must use the verified local filename.")
                self.encoder = PooledEncoder(
                    self.bundle["encoder"], self.directory / "encoder.pth",
                    self.bundle["encoder_sha256"], precision=self.bundle["precision"],
                    cpu_threads=self.bundle.get("cpu_threads", 4)
                )
            features = self.encoder.extract(samples, max_layer=max(self.bundle["layers"]))
            vector = pool_layers(features, self.bundle["layers"], self.bundle.get("aggregation", "mean"))
        if len(vector) != self.bundle["feature_count"]:
            raise ValueError("Model feature count differs.")
        logits = raw_logits(self.bundle["model"], vector[None, :])
        probabilities = self.bundle["calibrator"].predict_proba(logits)[0] if "calibrator" in self.bundle else softmax(logits / self.bundle["temperature"], axis=1)[0]
        confidence = float(probabilities.max())
        accepted = confidence >= self.bundle["threshold"]
        if details["clipped_fraction"] > 0.05:
            accepted = False
        return {"tone": self.bundle["classes"][int(probabilities.argmax())] if accepted else "uncertain",
                "reason": None if accepted else "clipped_audio" if details["clipped_fraction"] > 0.05 else "low_confidence",
                "confidence": round(confidence, 4),
                "probabilities": {k: round(float(v), 4) for k, v in zip(self.bundle["classes"], probabilities)},
                "prosody": details}

    def predict_wav(self, path):
        return self.predict_samples(read_wav(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", default="models/emotion.joblib")
    args = parser.parse_args()
    print(json.dumps(EmotionModel(args.model).predict_wav(args.audio), indent=2))


if __name__ == "__main__":
    main()
