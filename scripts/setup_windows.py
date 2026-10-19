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
    from app.utils.config import Settings
    from app.models.manager import ModelManager
    settings = Settings.load()
    settings.preset = args.preset
    settings.device = "auto" if cuda else "cpu"
    settings.save()
    if not args.no_models:
        from app.models.catalogue import CatalogueInstaller
        states = CatalogueInstaller(ModelManager(), progress=print).run()
        if any(item["state"] == "failed" for item in states.values()):
            print("Dependencies installed. Some models failed; first launch opens Setup & models for Retry.")
        if any(item["state"] == "needs_action" for item in states.values()):
            print("Models marked Needs action still require their listed terms, credentials or platform prerequisite.")
    print("Ready to launch run.bat. First-run Setup & models verifies the complete catalogue.")


if __name__ == "__main__":
    main()
