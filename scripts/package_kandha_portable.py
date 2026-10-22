"""Package the PyInstaller folder as a portable Kandha archive with a SHA-256 file beside it.

    python scripts/package_kandha_portable.py --payload dist/AccessibilityAI --output dist/installers

Windows: Kandha-<version>-windows.zip (contains Kandha.exe). Linux: Kandha-<version>-linux.tar.gz
(contains a `Kandha` launcher). macOS: Kandha-<version>-macos.zip. A README-KANDHA.txt and the
checksums are written next to the archive. Packaging never implies a test on the user's hardware.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

README = """Kandha {version} ({os_name} portable build)

Kandha captions the room, shows who is speaking and where they sit, and taps the
Kandha Stole on the speaker's side. This prototype needs no hardware: the virtual
stole on screen shows every tap and a simulated stole demonstrates pairing.

Start: {start}
First run opens Audial-AI's Setup & models to download the Whisper caption model
(about 3.6 GB for the full catalogue; the FAST preset needs only whisper-tiny).
After that everything runs offline. Audio never leaves this computer.

Let people in the room know live captions are on. Saving a practicum transcript
with a real client needs supervisor and ethics approval.

Docs: _internal/docs/kandha/USER_GUIDE.md (or docs/kandha in the source tree).
Firmware for a future physical stole: _internal/firmware/kandha (untested on hardware).
This build is unsigned. Check the .sha256 file before running it.
"""


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(payload, output, os_name=None):
    from app import __version__
    payload = Path(payload).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os_name = os_name or {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    start = {"windows": "double-click Kandha.exe", "macos": "open Kandha", "linux": "./Kandha (or ./AccessibilityAI --kandha)"}[os_name]
    readme = payload / "README-KANDHA.txt"
    readme.write_text(README.format(version=__version__, os_name=os_name, start=start), encoding="utf-8")
    base = f"Kandha-{__version__}-{os_name}"
    folder = f"Kandha-{__version__}"
    if os_name == "linux":
        archive = output / (base + ".tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(payload, arcname=folder)
    else:
        archive = output / (base + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(payload.rglob("*")):
                if path.is_file():
                    zf.write(path, f"{folder}/{path.relative_to(payload).as_posix()}")
    digest = sha256(archive)
    (output / (archive.name + ".sha256")).write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    info = {"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest, "version": __version__, "os": os_name,
            "executed_on_target": False}
    (output / (base + ".json")).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(info), flush=True)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--payload", type=Path, required=True, help="the PyInstaller COLLECT folder")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--os", dest="os_name", choices=["windows", "linux", "macos"])
    args = parser.parse_args()
    build(args.payload, args.output, args.os_name)


if __name__ == "__main__":
    main()
