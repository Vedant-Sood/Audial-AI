from pathlib import Path
import numpy as np
import torch

from app.video.pose import POSE_SCHEMA
from training.networks import make_model


def resample_sequence(values, length=48):
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 196 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Sign input must be a finite [frames,196] sequence.")
    if not isinstance(length, int) or not 1 <= length <= 1000:
        raise ValueError("Invalid sequence length.")
    source = np.arange(len(values))
    target = np.linspace(0, len(values) - 1, length)
    return np.stack([np.interp(target, source, values[:, i]) for i in range(196)], axis=1).astype(np.float32)


def validate_checkpoint(checkpoint, task):
    if not isinstance(checkpoint, dict) or checkpoint.get("task") != task or not checkpoint.get("labels") or not checkpoint.get("model"):
        raise ValueError("Checkpoint task, labels, and model weights are required.")
    if task == "sign" and (checkpoint.get("language") != "ISL" or checkpoint.get("pose_schema") != POSE_SCHEMA):
        raise ValueError("This model requires the declared Indian Sign Language pose schema.")
    if task == "prosody" and checkpoint.get("feature_schema") != "mfcc40_mean_std_v1":
        raise ValueError("Prosody feature schema does not match.")
    return checkpoint


class LocalClassifier:
    def __init__(self, checkpoint_path, task="sign"):
        self.checkpoint = validate_checkpoint(torch.load(Path(checkpoint_path), map_location="cpu", weights_only=True), task)
        self.task = task
        self.labels = self.checkpoint["labels"]
        self.config = self.checkpoint.get("model_config", {})
        self.model = make_model(task, self.config, len(self.labels))
        self.model.load_state_dict(self.checkpoint["model"])
        self.model.eval()
        self.mean = np.asarray(self.checkpoint.get("mean", 0), dtype=np.float32)
        self.std = np.maximum(np.asarray(self.checkpoint.get("std", 1), dtype=np.float32), 1e-6)

    def predict(self, features, threshold=0.75):
        values = np.asarray(features, dtype=np.float32)
        if not np.isfinite(values).all():
            raise ValueError("Non-finite inference features.")
        if self.task == "sign":
            values = resample_sequence(values, int(self.config.get("sequence_length", 48)))
        expected = 196 if self.task == "sign" else 80 if self.task == "prosody" else 192
        if values.shape[-1] != expected or values.ndim != (2 if self.task == "sign" else 1):
            raise ValueError("Inference feature shape mismatch.")
        values = (values - self.mean) / self.std
        with torch.inference_mode():
            scores = torch.softmax(self.model(torch.from_numpy(values)[None]) / max(float(self.checkpoint.get("temperature", 1)), 1e-6), dim=1)[0]
        index = int(scores.argmax())
        return {"label": self.labels[index], "score": float(scores[index]),
                "accepted": bool(float(scores[index]) >= threshold), "calibrated": False}
