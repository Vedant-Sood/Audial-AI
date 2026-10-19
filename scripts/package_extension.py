"""Build a loadable Chrome/Edge extension from the shared audio sources."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def extension_id(manifest):
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    return "".join(chr(ord("a") + int(character, 16)) for character in digest)


def build(output):
    root = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    if output == root / "browser-extension" or output.is_relative_to(
        root / "browser-extension"
    ):
        raise ValueError(
            "Choose a generated output directory outside the extension source."
        )
    output.mkdir(parents=True, exist_ok=True)
    for source in (root / "browser-extension").iterdir():
        if source.is_file():
            shutil.copyfile(source, output / source.name)
    for name in ["capture.js", "pcm-worklet.js"]:
        shutil.copyfile(root / "browser" / name, output / name)
    manifest = json.loads((output / "manifest.json").read_text())
    result = {
        "id": extension_id(manifest),
        "version": manifest["version"],
        "path": str(output),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/browser-extension")
    )
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    result = build(args.output)
    if args.zip:
        args.zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(args.output.iterdir()):
                if path.is_file():
                    archive.write(path, path.name)
        result["zip_sha256"] = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
