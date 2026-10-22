from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from app.utils.paths import data_root


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    task: str
    source: str
    license: str
    size: str
    required: tuple
    gated: bool = False
    notes: str = ""


REGISTRY = {
    "whisper-tiny": ModelSpec(
        "whisper-tiny",
        "Whisper tiny (multilingual)",
        "ASR",
        "Systran/faster-whisper-tiny",
        "MIT",
        "~75 MB",
        ("model.bin", "config.json", "tokenizer.json"),
    ),
    "whisper-small": ModelSpec(
        "whisper-small",
        "Whisper small (multilingual)",
        "ASR",
        "Systran/faster-whisper-small",
        "MIT",
        "~480 MB",
        ("model.bin", "config.json", "tokenizer.json"),
    ),
    "whisper-medium": ModelSpec(
        "whisper-medium",
        "Whisper medium (multilingual)",
        "ASR",
        "Systran/faster-whisper-medium",
        "MIT",
        "~1.5 GB",
        ("model.bin", "config.json", "tokenizer.json"),
    ),
    "ecapa": ModelSpec(
        "ecapa",
        "SpeechBrain ECAPA-TDNN",
        "Speaker embeddings",
        "speechbrain/spkrec-ecapa-voxceleb",
        "Apache-2.0",
        "~90 MB",
        ("embedding_model.ckpt", "mean_var_norm_emb.ckpt", "hyperparams.yaml"),
        notes="Cosine similarity is not calibrated identity confidence; online clustering is experimental.",
    ),
    "pyannote": ModelSpec(
        "pyannote",
        "Community-1",
        "Diarization / overlap",
        "pyannote/speaker-diarization-community-1",
        "CC-BY-4.0",
        "~110 MB",
        (
            "config.yaml",
            "segmentation/pytorch_model.bin",
            "embedding/pytorch_model.bin",
            "plda/xvec_transform.npz",
            "plda/plda.npz",
        ),
        True,
        "Accept upstream conditions first. Full Windows builds include the local waveform runtime; no paid API or speech separation.",
    ),
    "hand-pose": ModelSpec(
        "hand-pose",
        "MediaPipe Hand Landmarker",
        "Hand tracking",
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        "Apache-2.0 (MediaPipe)",
        "~8 MB",
        ("model.task",),
    ),
    "body-pose": ModelSpec(
        "body-pose",
        "MediaPipe Pose Landmarker lite",
        "Body tracking",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        "Apache-2.0 (MediaPipe)",
        "~6 MB",
        ("model.task",),
    ),
    "emotion-wavlm": ModelSpec(
        "emotion-wavlm",
        "WavLM voice emotion (CREMA-D)",
        "Voice emotion",
        "https://download.pytorch.org/torchaudio/models/wavlm_large.pth",
        "Microsoft MIT / CREMA-D ODbL-1.0, DbCL-1.0",
        "~1.3 GB download; ~2.7 GB installed",
        ("encoder.pth", "emotion.joblib", "evaluation.json"),
        notes="Acted English benchmark. Installing selects the evaluated model for the next session; enable voice emotion in Settings.",
    ),
}


class ModelManager:
    def __init__(self, root=None):
        self.root = Path(root or data_root() / "models")
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, model_id):
        if model_id not in REGISTRY and model_id not in {"sign-local", "prosody-local"}:
            raise ValueError("Unknown model")
        return self.root / model_id

    def installed(self, model_id):
        path = self.path(model_id)
        if model_id.endswith("-local"):
            return (path / "best.pt").is_file()
        return (path / "installed.json").is_file() and all(
            (path / f).is_file() and (path / f).stat().st_size > 0
            for f in REGISTRY[model_id].required
        )

    def install(self, model_id, progress=print, accepted=False):
        """Use the same verified/resumable path for CLI and developer tools."""
        from filelock import FileLock
        from app.models.catalogue import CatalogueInstaller

        spec = REGISTRY[model_id]
        progress(f"Preparing {spec.name}; {spec.license}")
        installer = CatalogueInstaller(
            self, progress=lambda event: progress(json.dumps(event))
        )
        with FileLock(str(self.root / ".setup.lock"), timeout=0):
            destination = installer.install_model(model_id, accepted)
        progress("Installation complete")
        return destination

    def import_checkpoint(self, path, task):
        import torch
        from app.inference.sign import validate_checkpoint

        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError("Checkpoint file does not exist.")
        checkpoint = torch.load(source, map_location="cpu", weights_only=True)
        validate_checkpoint(checkpoint, task)
        dest = self.path("sign-local" if task == "sign" else "prosody-local")
        dest.mkdir(exist_ok=True)
        if source != (dest / "best.pt").resolve():
            shutil.copyfile(source, dest / "best.pt")
        return dest

    def remove(self, model_id):
        path = self.path(model_id)
        if path.exists():
            shutil.rmtree(path)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
