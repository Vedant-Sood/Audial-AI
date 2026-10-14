from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
from app.utils.paths import atomic_json, data_root, project_root


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
    "whisper-tiny": ModelSpec("whisper-tiny", "Whisper tiny (multilingual)", "ASR", "Systran/faster-whisper-tiny", "MIT", "~75 MB", ("model.bin", "config.json", "tokenizer.json")),
    "whisper-small": ModelSpec("whisper-small", "Whisper small (multilingual)", "ASR", "Systran/faster-whisper-small", "MIT", "~480 MB", ("model.bin", "config.json", "tokenizer.json")),
    "whisper-medium": ModelSpec("whisper-medium", "Whisper medium (multilingual)", "ASR", "Systran/faster-whisper-medium", "MIT", "~1.5 GB", ("model.bin", "config.json", "tokenizer.json")),
    "ecapa": ModelSpec("ecapa", "SpeechBrain ECAPA-TDNN", "Speaker embeddings", "speechbrain/spkrec-ecapa-voxceleb", "Apache-2.0", "~90 MB", ("embedding_model.ckpt", "mean_var_norm_emb.ckpt", "hyperparams.yaml"), notes="Cosine similarity is not calibrated identity confidence; online clustering is experimental."),
    "pyannote": ModelSpec("pyannote", "Community-1", "Diarization / overlap", "pyannote/speaker-diarization-community-1", "CC-BY-4.0", "See model card", ("config.yaml",), True, "Accept upstream conditions first; requires requirements-overlap.txt. No speech separation."),
    "hand-pose": ModelSpec("hand-pose", "MediaPipe Hand Landmarker", "Hand tracking", "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task", "Apache-2.0 (MediaPipe)", "~8 MB", ("model.task",)),
    "body-pose": ModelSpec("body-pose", "MediaPipe Pose Landmarker lite", "Body tracking", "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task", "Apache-2.0 (MediaPipe)", "~6 MB", ("model.task",)),
    "emotion-wavlm": ModelSpec("emotion-wavlm", "WavLM voice emotion (CREMA-D)", "Voice emotion",
        "https://download.pytorch.org/torchaudio/models/wavlm_large.pth", "Microsoft MIT / CREMA-D ODbL-1.0, DbCL-1.0",
        "~1.2 GB download; ~2.4 GB installed", ("encoder.pth", "emotion.joblib", "evaluation.json"),
        notes="Acted English benchmark. Installing selects the evaluated model for the next session; enable voice emotion in Settings."),
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
        return (path / "installed.json").is_file() and all((path / f).is_file() and (path / f).stat().st_size > 0 for f in REGISTRY[model_id].required)

    def install(self, model_id, progress=print, accepted=False):
        """Call in an explicit download subprocess, never in inference workers."""
        spec = REGISTRY[model_id]
        if spec.gated and not accepted:
            raise PermissionError("Accept the upstream model conditions, then set HF_TOKEN locally and select Accepted conditions.")
        staging = self.root / (model_id + ".installing")
        staging.mkdir(exist_ok=True)
        progress(f"Downloading {spec.name} from {spec.source}; {spec.license}")
        if model_id == "emotion-wavlm":
            from accessibilityai_upgrade.ssl_features import ENCODERS
            bundled = project_root() / "models" / "emotion-wavlm"
            report = json.loads((bundled / "evaluation.json").read_text(encoding="utf-8"))
            if file_hash(bundled / "emotion.joblib") != report["model_sha256"]:
                raise ValueError("Bundled emotion classifier differs from its evaluation report.")
            if report["encoder_sha256"] != ENCODERS["WAVLM_LARGE"]["sha256"]:
                raise ValueError("Emotion encoder differs from the registered pretrained checkpoint.")
            for name in ["emotion.joblib", "evaluation.json"]:
                shutil.copyfile(bundled / name, staging / name)
        revision = None
        if spec.source.startswith("https://"):
            target = staging / spec.required[0]
            with urllib.request.urlopen(spec.source, timeout=60) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            if model_id == "emotion-wavlm" and file_hash(target) != report["encoder_sha256"]:
                raise ValueError("Downloaded emotion encoder failed checksum verification.")
        else:
            from huggingface_hub import HfApi, snapshot_download
            info = HfApi().model_info(spec.source)
            revision = info.sha
            snapshot_download(spec.source, revision=revision, local_dir=str(staging),
                              ignore_patterns=["*.onnx", "*.tflite", "*.h5", "*.msgpack"], max_workers=2)
        for f in spec.required:
            if not (staging / f).is_file() or (staging / f).stat().st_size == 0:
                raise ValueError(f"Incomplete download: {f}")
        hashes = {str(f.relative_to(staging)): file_hash(f) for f in staging.rglob("*") if f.is_file() and ".cache" not in f.parts}
        atomic_json(staging / "installed.json", {**asdict(spec), "revision": revision, "sha256": hashes})
        dest = self.path(model_id)
        if dest.exists():
            shutil.rmtree(dest)
        staging.replace(dest)
        if model_id == "emotion-wavlm":
            from scripts.activate_emotion import activate
            activate(dest)
        progress("Installation complete")
        return dest

    def import_checkpoint(self, path, task):
        import torch
        from app.inference.sign import validate_checkpoint
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        validate_checkpoint(checkpoint, task)
        dest = self.path("sign-local" if task == "sign" else "prosody-local")
        dest.mkdir(exist_ok=True)
        shutil.copyfile(path, dest / "best.pt")
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
