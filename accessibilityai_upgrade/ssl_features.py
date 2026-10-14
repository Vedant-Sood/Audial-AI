"""Frozen speech features shared by emotion training and desktop inference.

Checkpoints are downloaded explicitly by the training command. Inference never
downloads weights or audio. Layer numbers in model metadata are one-based.
"""
from pathlib import Path
import hashlib

import numpy as np
import torch
import torchaudio

from .audio import SAMPLE_RATE, prepare

FEATURE_VERSION = "wavlm-layer-mean-std-v1"
# The original format name remains compatible with published 0.4 heads. The
# pinned encoder ID distinguishes WavLM and XLS-R; both use the same statistics.
ENCODERS = {
    "WAV2VEC2_XLSR_300M": {
        "url": "https://download.pytorch.org/torchaudio/models/wav2vec2_xlsr_300m.pth",
        "sha256": "2ad6f8ff9711c7acc72fbc6ffcdba6bc2582fba92c6b056d71de8a4ed77b6b22",
    },
    "WAVLM_BASE_PLUS": {
        "url": "https://download.pytorch.org/torchaudio/models/wavlm_base_plus.pth",
        "sha256": "136a3e720c04f2c77bf7a4dc6a3868b14d5a2c145a988114b733cb1a8428be98",
    },
    "WAVLM_LARGE": {
        "url": "https://download.pytorch.org/torchaudio/models/wavlm_large.pth",
        "sha256": "8c1e5637ae88657f1c54b60ec6b0e0277482b3a071d4be57cdc5715b7921d36e",
    },
}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pool_layers(features, layers, aggregation="mean"):
    """Combine selected layers, preserving temporal mean and deviation."""
    indices = np.asarray(layers, dtype=int) - 1
    if not len(indices) or indices.min() < 0 or indices.max() >= features.shape[-3]:
        raise ValueError("Invalid WavLM layer selection.")
    selected = np.take(features, indices, axis=-3)
    if aggregation == "mean":
        selected = selected.mean(axis=-3)
    elif aggregation != "concat":
        raise ValueError("Unsupported layer aggregation.")
    return selected.reshape((*features.shape[:-3], -1)).astype(np.float32)


class PooledEncoder:
    def __init__(self, name, checkpoint, expected_sha256, *, device="cpu", precision="float32", cpu_threads=4):
        if name not in ENCODERS:
            raise ValueError("Unsupported emotion encoder.")
        if device == "cpu":
            if not isinstance(cpu_threads, int) or cpu_threads < 1:
                raise ValueError("CPU thread count must be positive.")
            # BF16 reductions can differ with a different CPU thread count.
            # Training and inference use the same recorded setting.
            torch.set_num_threads(cpu_threads)
        if file_sha256(checkpoint) != expected_sha256:
            raise ValueError("Emotion encoder checksum differs from training metadata.")
        bundle = getattr(torchaudio.pipelines, name)
        # Construction avoids get_model(), which implicitly downloads weights.
        factory = torchaudio.models.wavlm_model if name.startswith("WAVLM_") else torchaudio.models.wav2vec2_model
        self.model = factory(**bundle._params)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        self.model.load_state_dict(state, strict=True)
        self.model.eval().requires_grad_(False).to(device)
        self.normalize = bundle._normalize_waveform
        self.device = device
        if precision not in {"float32", "bfloat16"}:
            raise ValueError("Unsupported encoder precision.")
        self.precision = precision
        if precision == "bfloat16":
            # Autocast would round these weights to BF16 on every utterance.
            # Precast linear weights once; keep normalization/position weights
            # in FP32. This preserves the extracted values and reduces CPU work.
            for layer in self.model.modules():
                if isinstance(layer, torch.nn.Linear):
                    layer.to(dtype=torch.bfloat16)
        self.layers = bundle._params["encoder_num_layers"]
        self.width = bundle._params["encoder_embed_dim"]

    def extract(self, samples, max_layer=None):
        return self.extract_with_temporal(samples,max_layer=max_layer)[0]

    def extract_with_temporal(self,samples,max_layer=None,temporal_layers=None,bins=64):
        """Return pooled statistics and optional fixed-length temporal features.

        Temporal features average the specified one-based layers and adaptively
        pool time into bins. FP16 storage is applied in both caching and runtime;
        no audio or other utterances from a speaker affect this calculation.
        """
        samples = prepare(samples, SAMPLE_RATE).astype(np.float32)
        waveform = torch.from_numpy(samples).unsqueeze(0).to(self.device)
        if self.normalize:
            waveform = torch.nn.functional.layer_norm(waveform, waveform.shape[-1:])
        # Each utterance is processed without padding, matching inference exactly.
        with torch.inference_mode(), torch.autocast(
            device_type=self.device, dtype=torch.bfloat16,
            enabled=self.precision == "bfloat16"
        ):
            frames, _ = self.model.extract_features(waveform, num_layers=max_layer)
            pooled = [torch.stack((f[0].mean(0), f[0].std(0, unbiased=False)))
                      for f in frames]
            statistics = torch.stack(pooled).float().cpu().numpy().astype(np.float32)
            temporal = None
            if temporal_layers:
                if min(temporal_layers)<1 or max(temporal_layers)>len(frames) or bins<1:
                    raise ValueError("Invalid temporal layer or bin selection.")
                sequence = torch.stack([frames[k-1][0].float() for k in temporal_layers]).mean(0)
                temporal = torch.nn.functional.adaptive_avg_pool1d(sequence.T,bins).T.half().cpu().numpy()
            return statistics,temporal
