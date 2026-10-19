"""Create a source/research ZIP; exclude raw corpora, caches and runtime/build trees."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from app import __version__


def package(output):
    root = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    excluded = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".venvs", ".git", "build", "dist", "raw", "tensorboard", "artifacts", "ci-state"}
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()
        and not any(part in excluded for part in p.relative_to(root).parts)
        and p.suffix not in {".pyc", ".tmp", ".zip", ".log"} and not p.name.startswith(".env")
        and not p.match("epoch_*.pt")
        and p.name not in {"delivery_manifest.json", "features.npz", "features.npy", "encoder.pth", "selected.joblib"} and p.resolve() != output]
    manifest = {"project": "Audial-AI", "version": __version__, "kind": "source and research checkpoints",
        "contains_prebuilt_windows_executable": False, "excluded": sorted(excluded), "files": {}}
    manifest["excluded_patterns"] = ["epoch_*.pt", "features.npz", "features.npy", "encoder.pth", "selected.joblib"]
    for p in files:
        manifest["files"][p.relative_to(root).as_posix()] = {
            "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    manifest_json = json.dumps(manifest, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in files:
            archive.write(p, f"AccessibilityAI/{p.relative_to(root).as_posix()}")
        archive.writestr("AccessibilityAI/delivery_manifest.json", manifest_json)
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP integrity failure: {bad}")
        for name, item in manifest["files"].items():
            actual = hashlib.sha256(archive.read("AccessibilityAI/" + name)).hexdigest()
            if actual != item["sha256"]:
                raise ValueError(f"Packaged hash mismatch: {name}")
    print(json.dumps({"path": str(output), "files": len(files) + 1, "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "integrity": "PASS"}), flush=True)
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", default=str(Path(__file__).resolve().parents[2] / "AccessibilityAI.zip"))
    package(p.parse_args().output)
