"""Install the desktop/browser dependencies and explicitly requested local models."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", action="store_true", help="Install CPU Torch wheels")
    parser.add_argument("--no-models", action="store_true", help="Install dependencies; download models later on Models")
    parser.add_argument("--preset", choices=["FAST", "BALANCED", "ACCURATE"], default="FAST")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.architecture()[0] != "64bit":
        parser.error("setup.bat requires Windows x64; see README.md for Linux/macOS commands.")
    if sys.version_info[:2] not in {(3, 11), (3, 12)}:
        parser.error("Use Python 3.11 or 3.12 x64.")
    root = Path(__file__).resolve().parents[1]
    cuda = not args.cpu and shutil.which("nvidia-smi") is not None
    def pip(*options):
        subprocess.run([sys.executable, "-m", "pip", *options], cwd=root, check=True)
    pip("install", "--upgrade", "pip")
    pip("install", "torch==2.8.0", "torchaudio==2.8.0", "--index-url",
        "https://download.pytorch.org/whl/" + ("cu126" if cuda else "cpu"))
    pip("install", "-r", str(root / "requirements.txt"))
    from app.utils.cuda_runtime import configure_cuda_dlls
    configure_cuda_dlls()
    import torch
    if cuda and not torch.cuda.is_available():
        raise RuntimeError("PyTorch could not use the NVIDIA driver. Update it, or run setup.bat --cpu.")
    from app.utils.config import Settings, PRESETS
    from app.models.manager import ModelManager
    settings = Settings.load()
    settings.preset = args.preset
    settings.device = "auto" if cuda else "cpu"
    settings.save()
    manager = ModelManager()
    if not args.no_models:
        for model in [PRESETS[args.preset]["asr"], "ecapa", "hand-pose", "body-pose"]:
            if not manager.installed(model):
                manager.install(model)
    sign = root / "models" / "research" / "sign.pt"
    if sign.exists():
        manager.import_checkpoint(sign, "sign")
    print("Setup complete. Run run.bat for the desktop or run_browser.bat for your browser.")


if __name__ == "__main__":
    main()
