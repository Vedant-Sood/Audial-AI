"""First-run model catalogue: cache assets once; never load inference here."""

from dataclasses import asdict
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request

from filelock import FileLock
from app.models.download import Asset, Downloader, DownloadCancelled, digest_file
from app.utils.paths import atomic_json, data_root, project_root
from app.utils.credentials import get_token


# Estimates are shown until upstream, revision-pinned file sizes are resolved.
ESTIMATED_BYTES = {
    "whisper-tiny": 76_000_000,
    "whisper-small": 484_000_000,
    "whisper-medium": 1_530_000_000,
    "ecapa": 90_000_000,
    "pyannote": 110_000_000,
    "hand-pose": 8_000_000,
    "body-pose": 6_000_000,
    "emotion-wavlm": 1_270_000_000,
}
LOCAL_ASSETS = ("sign-local", "emotion-baseline", "silero-vad", "system-tts")


def catalogue():
    from app.models.manager import REGISTRY

    return [
        {
            "id": spec.id,
            "name": spec.name,
            "license": spec.license,
            "estimated_download_bytes": ESTIMATED_BYTES[spec.id],
            "gated": spec.gated,
        }
        for spec in REGISTRY.values()
    ] + [
        {
            "id": "sign-local",
            "name": "Bundled isolated ISL classifier",
            "license": "See bundled provenance",
            "estimated_download_bytes": 0,
            "gated": False,
        },
        {
            "id": "emotion-baseline",
            "name": "Bundled acoustic expression baseline",
            "license": "CREMA-D ODbL-1.0 / DbCL-1.0",
            "estimated_download_bytes": 0,
            "gated": False,
        },
        {
            "id": "silero-vad",
            "name": "Silero voice activity detector",
            "license": "MIT",
            "estimated_download_bytes": 0,
            "gated": False,
        },
        {
            "id": "system-tts",
            "name": "Windows local speech voices (SAPI5)",
            "license": "Windows installed voice terms",
            "estimated_download_bytes": 0,
            "gated": False,
        },
    ]


class CatalogueInstaller:
    def __init__(self, manager=None, progress=None, cancel=None):
        from app.models.manager import ModelManager

        self.manager = manager or ModelManager()
        self.progress = progress or (lambda event: None)
        self.cancel = cancel
        self.status_path = data_root() / "model-setup.json"
        self.states = {}

    def emit(self, model, state, **values):
        event = {"model": model, "state": state, **values}
        self.states[model] = event
        self.progress(event)
        if state not in {"downloading", "verified", "resolving"}:
            atomic_json(self.status_path, {"schema_version": 1, "models": self.states})

    def run(self, accepted=False):
        with FileLock(str(self.manager.root / ".setup.lock"), timeout=0):
            self.states = {
                entry["id"]: {"model": entry["id"], "state": "pending"}
                for entry in catalogue()
            }
            atomic_json(self.status_path, {"schema_version": 1, "models": self.states})
            for entry in catalogue():
                model = entry["id"]
                if self.cancel is not None and self.cancel.is_set():
                    self.emit(
                        model,
                        "paused",
                        message="Resume continues verified downloads and partial files.",
                    )
                    break
                try:
                    self.install_model(model, accepted)
                    self.emit(model, "ready")
                except DownloadCancelled as error:
                    self.emit(model, "paused", message=str(error))
                    break
                except (PermissionError, NotImplementedError) as error:
                    self.emit(model, "needs_action", message=str(error))
                except Exception as error:
                    # One unavailable destination must not prevent independent assets.
                    self.emit(model, "failed", message=str(error))
        return self.states

    def install_model(self, model, accepted=False):
        from app.models.manager import REGISTRY

        if model in LOCAL_ASSETS:
            return self.install_local(model)
        spec = REGISTRY[model]
        destination = self.manager.path(model)
        backup = self.manager.root / (model + ".previous")
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        receipt = destination / "installed.json"
        if self.manager.installed(model) and receipt.is_file():
            try:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            hashes = saved.get("sha256", {})
            if hashes and all(
                (destination / name).resolve().is_relative_to(destination.resolve())
                and (destination / name).is_file()
                and digest_file(destination / name) == expected
                for name, expected in hashes.items()
            ):
                self.activate_default(model, destination)
                return destination
        if spec.gated:
            if not accepted or not get_token():
                raise PermissionError(
                    "Accept Community-1 terms at https://huggingface.co/pyannote/speaker-diarization-community-1, save a read token in Setup, then Resume. Other models continue automatically."
                )
            if (
                importlib.util.find_spec("pyannote") is None
                or importlib.util.find_spec("pyannote.audio") is None
            ):
                raise NotImplementedError(
                    "The optional Community-1 runtime is not included in this build. Install the full Windows distribution; setup has not marked diarization ready."
                )
        self.emit(model, "resolving")
        staging = self.manager.root / (model + ".installing")
        staging.mkdir(exist_ok=True)
        assets = self.resolve_assets(spec)
        completed_bytes = 0
        total_bytes = sum(asset.size or 0 for asset in assets)

        def model_progress(event):
            self.emit(
                model,
                **{
                    **event,
                    "downloaded": completed_bytes + event.get("downloaded", 0),
                    "total": total_bytes or None,
                },
            )

        downloader = Downloader(
            staging,
            self.cancel,
            model_progress,
            token=get_token() if spec.gated else None,
        )
        plan_path = staging / "asset-plan.json"
        try:
            prior_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior_plan = []
        prior_assets = {a["filename"]: a for a in prior_plan}
        for asset in assets:
            prior = prior_assets.get(asset.filename)
            if prior and prior != asdict(asset):
                (staging / asset.filename).with_name(
                    Path(asset.filename).name + ".part"
                ).unlink(missing_ok=True)
        atomic_json(plan_path, [asdict(a) for a in assets])
        required = set(spec.required)
        if model == "emotion-wavlm":
            required = {"encoder.pth"}
        if not required.issubset({a.filename for a in assets}):
            raise ValueError(
                "Upstream model revision is missing required runtime files."
            )
        for asset in assets:
            prior = destination / asset.filename
            target = staging / asset.filename
            if (
                not target.exists()
                and prior.is_file()
                and downloader.valid(prior, asset)
            ):
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(prior, target)
                except OSError:
                    shutil.copyfile(prior, target)
            downloader.fetch(asset)
            completed_bytes += target.stat().st_size
        if model == "emotion-wavlm":
            bundled = project_root() / "models" / "emotion-wavlm"
            report = json.loads(
                (bundled / "evaluation.json").read_text(encoding="utf-8")
            )
            if digest_file(bundled / "emotion.joblib") != report["model_sha256"]:
                raise ValueError(
                    "Bundled classifier differs from its evaluated checksum."
                )
            for name in ["emotion.joblib", "evaluation.json"]:
                shutil.copyfile(bundled / name, staging / name)
        plan_path.unlink(missing_ok=True)
        hashes = {
            str(p.relative_to(staging)): digest_file(p)
            for p in staging.rglob("*")
            if p.is_file()
            and p.name != "installed.json"
            and not p.name.endswith(".part")
        }
        atomic_json(
            staging / "installed.json",
            {
                **asdict(spec),
                "schema_version": 2,
                "assets": [asdict(asset) for asset in assets],
                "sha256": hashes,
                "preprocessing": {
                    "sample_rate": 16000,
                    "audio": "mono float32",
                    "download_is_not_model_loading": True,
                },
            },
        )
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.rename(backup)
        try:
            staging.rename(destination)
        except OSError:
            if backup.exists() and not destination.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        self.activate_default(model, destination)
        return destination

    def activate_default(self, model, destination):
        if (
            model == "emotion-wavlm"
            and not (data_root() / "emotion_selection.json").exists()
        ):
            from scripts.activate_emotion import activate

            activate(destination)

    def resolve_assets(self, spec):
        if spec.id == "emotion-wavlm":
            from accessibilityai_upgrade.ssl_features import ENCODERS

            with urllib.request.urlopen(
                urllib.request.Request(spec.source, method="HEAD"), timeout=30
            ) as response:
                size = int(response.headers["Content-Length"])
            return [
                Asset(
                    spec.source,
                    "encoder.pth",
                    ENCODERS["WAVLM_LARGE"]["sha256"],
                    size=size,
                )
            ]
        if spec.source.startswith("https://"):
            with urllib.request.urlopen(
                urllib.request.Request(spec.source, method="HEAD"), timeout=30
            ) as response:
                # Google may send CRC32C and MD5 in separate header fields.
                # HTTPMessage.get() returns only the first, losing MD5.
                values = (
                    response.headers.get_all("x-goog-hash", [])
                    if hasattr(response.headers, "get_all")
                    else [response.headers.get("x-goog-hash", "")]
                )
                checksums = dict(
                    value.strip().split("=", 1)
                    for value in ",".join(values).split(",")
                    if "=" in value
                )
                if "md5" not in checksums:
                    raise ValueError(
                        "The model server did not provide its authoritative object checksum."
                    )
                checksum = base64.b64decode(checksums["md5"]).hex()
                generation = response.headers["x-goog-generation"]
                size = int(response.headers["Content-Length"])
            return [
                Asset(
                    spec.source + "?generation=" + generation,
                    "model.task",
                    checksum,
                    "md5",
                    size,
                    generation,
                )
            ]
        from huggingface_hub import HfApi, hf_hub_url

        info = HfApi().model_info(
            spec.source,
            files_metadata=True,
            token=get_token() if spec.gated else False,
            timeout=30,
        )
        assets = []
        # Runtime formats only: never download training datasets or duplicate framework weights.
        allowed = {
            ".bin",
            ".json",
            ".txt",
            ".yaml",
            ".yml",
            ".ckpt",
            ".safetensors",
            ".pt",
            ".npz",
        }
        for sibling in info.siblings:
            name = sibling.rfilename
            if Path(name).suffix.lower() not in allowed or name.startswith(
                (".gitattributes", "onnx/")
            ):
                continue
            lfs = sibling.lfs
            digest = lfs.sha256 if lfs else sibling.blob_id
            size = lfs.size if lfs else sibling.size
            if digest is None or size is None:
                raise ValueError(
                    "Upstream file metadata lacks the checksum or size required for verification."
                )
            assets.append(
                Asset(
                    hf_hub_url(spec.source, name, revision=info.sha),
                    name,
                    digest,
                    "sha256" if lfs else "git-sha1",
                    size,
                    info.sha,
                )
            )
        return assets

    def install_local(self, model):
        if model == "sign-local":
            source = self.manager.path(model) / "best.pt"
            if not source.exists():
                source = (
                    self.manager.import_checkpoint(
                        project_root() / "models" / "research" / "sign.pt", "sign"
                    )
                    / "best.pt"
                )
            self.local_receipt(
                model,
                [source],
                "Trusted local isolated-sign checkpoint; normalized MediaPipe pose sequence",
            )
            return source.parent
        if model == "system-tts":
            if sys.platform != "win32":
                raise NotImplementedError(
                    "Windows SAPI5 voices are verified on Windows; no cloud voice service is used."
                )
            import pyttsx3

            engine = pyttsx3.init("sapi5")
            try:
                if not engine.getProperty("voices"):
                    raise PermissionError(
                        "Install a local speech voice in Windows Settings → Time & language → Speech, then Resume."
                    )
            finally:
                engine.stop()
            self.local_receipt(
                model, [], "Windows SAPI5; installed voices are owned by Windows"
            )
            return None
        if model == "silero-vad":
            import faster_whisper

            directory = Path(faster_whisper.__file__).parent / "assets"
            files = list(directory.glob("silero*.onnx"))
            if not files:
                raise FileNotFoundError(
                    "The packaged Silero VAD asset is missing; reinstall Audial-AI."
                )
            self.local_receipt(model, files, "faster-whisper wheel; mono 16-kHz PCM")
            return directory
        if model == "emotion-baseline":
            directory = project_root() / "models" / "emotion"
            if not (directory / "emotion.joblib").is_file():
                raise FileNotFoundError(
                    "The bundled acoustic classifier is missing; reinstall Audial-AI."
                )
            if (
                digest_file(directory / "emotion.joblib")
                != "30b4bf9d08f05c00f80daa6f78e224762cf3bba68a32cb05c2b8ab9cb207807c"
            ):
                raise ValueError(
                    "Bundled acoustic classifier differs from its released checksum."
                )
            self.local_receipt(
                model,
                [directory / "emotion.joblib", directory / "evaluation.json"],
                "mfcc-mel-prosody-v1; mono 16-kHz PCM",
            )
            return directory

    def local_receipt(self, model, files, preprocessing):
        from app import __version__

        entry = next(item for item in catalogue() if item["id"] == model)
        atomic_json(
            self.manager.root / "receipts" / (model + ".json"),
            {
                **entry,
                "app_version": __version__,
                "preprocessing": preprocessing,
                "assets": [
                    {
                        "filename": str(p),
                        "sha256": digest_file(p),
                        "bytes": p.stat().st_size,
                    }
                    for p in files
                ],
            },
        )
