"""Assemble a Windows x64 desktop ZIP using official Python and Windows wheels.

This can assemble files on Linux; Windows execution is a separate required
validation step. TLS, the pinned Python SHA512, pip artifact verification and
wheel RECORD hashes remain enabled. All downloaded dependency licenses remain
in their dist-info directories. No microphone or network inference starts here.
"""
import argparse
import base64
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

PYTHON_URL = "https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg"
# Published x-ms-meta-sha512 of the official CPython package, retrieved over TLS.
PYTHON_SHA512 = "u9pNz2iKlCEbYtUJaKkbOPMF0LjR7NkCafdKhvigpPzrt8oWKgdTpHaR6z3wyWQAm9PYGUxv0Zr66NX9AeHMDw=="
# pip reads dependency markers for the machine it runs on, not for Windows. These packages are
# fetched without their dependencies; requirements-portable.txt lists their Windows ones itself.
NO_DEPS = {"bleak"}


def requirement_name(line):
    """The normalised project name a requirement line names, or None for comments and options."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line.split("#", 1)[0])
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


def portable_requirements(root):
    """(resolved, no_deps): requirements-portable.txt with its -r includes expanded, NO_DEPS lines kept apart."""
    resolved, no_deps = [], []

    def read(path):
        for line in path.read_text(encoding="utf-8").splitlines():
            include = re.match(r"\s*(?:-r|--requirement)(?:\s+|=)(\S+)", line)
            if include:
                read(path.parent / include.group(1))
            elif requirement_name(line) in NO_DEPS:
                no_deps.append(line.split("#", 1)[0].strip())
            else:
                resolved.append(line)

    read(Path(root) / "requirements-portable.txt")
    return resolved, no_deps


def pip_downloads(wheels, cache, listing, no_deps):
    """The pip commands that fetch the Windows x64 CPython 3.12 wheel set on any host."""
    download = [sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                "--platform", "win_amd64", "--python-version", "312", "--implementation", "cp",
                "--abi", "cp312", "--abi", "abi3", "--dest", str(wheels),
                "--cache-dir", str(Path(cache) / "pip")]
    commands = [download + ["--extra-index-url", "https://download.pytorch.org/whl/cpu", "-r", str(listing)]]
    if no_deps:
        commands.append(download + ["--no-deps"] + no_deps)
    return commands


def safe_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unsafe archive path: " + name)
    return path


def install_wheel(wheel, runtime):
    site = runtime / "Lib" / "site-packages"
    with zipfile.ZipFile(wheel) as archive:
        # Vendored packages can include their own RECORD files; only the wheel's
        # top-level dist-info describes the complete installation payload.
        records = [n for n in archive.namelist() if n.endswith(".dist-info/RECORD")
                   and len(PurePosixPath(n).parts) == 2]
        if len(records) != 1:
            raise ValueError("Missing wheel RECORD: " + wheel.name)
        for name, digest, size in csv.reader(StringIO(archive.read(records[0]).decode())):
            safe_path(name)
            if not digest:
                continue
            algorithm, expected = digest.split("=", 1)
            contents = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.new(algorithm, contents).digest()).rstrip(b"=").decode()
            if actual != expected or (size and len(contents) != int(size)):
                raise ValueError("Wheel integrity failure: " + name)
        for item in archive.infolist():
            if item.is_dir():
                continue
            path = safe_path(item.filename)
            parts = path.parts
            if len(parts) > 2 and parts[0].endswith(".data"):
                roots = {"purelib": site, "platlib": site, "scripts": runtime / "Scripts",
                         "data": runtime, "headers": runtime / "Include"}
                if parts[1] not in roots:
                    raise ValueError("Unsupported wheel scheme: " + parts[1])
                target = roots[parts[1]].joinpath(*parts[2:])
            else:
                target = site.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))


def build(output, cache):
    root = Path(__file__).resolve().parents[1]
    cache = Path(cache).resolve(); cache.mkdir(parents=True, exist_ok=True)
    package = cache / "python.3.12.10.nupkg"
    if not package.exists():
        print("Downloading official Windows Python 3.12.10", flush=True)
        with urllib.request.urlopen(PYTHON_URL, timeout=60) as response, package.open("wb") as target:
            shutil.copyfileobj(response, target)
    digest = base64.b64encode(hashlib.sha512(package.read_bytes()).digest()).decode()
    if digest != PYTHON_SHA512:
        raise ValueError("Official Python checksum differs; refusing the artifact.")
    fingerprint = hashlib.sha256((root / "requirements-portable.txt").read_bytes()
                                 + (root / "requirements.txt").read_bytes()).hexdigest()[:12]
    wheels = cache / ("windows-wheels-" + fingerprint); wheels.mkdir(exist_ok=True)
    print("Resolving Windows CPU wheels", flush=True)
    resolved, no_deps = portable_requirements(root)
    listing = cache / ("portable-requirements-" + fingerprint + ".txt")
    listing.write_text("\n".join(resolved) + "\n", encoding="utf-8")
    for command in pip_downloads(wheels, cache, listing, no_deps):
        subprocess.run(command, check=True)
    staging = cache / "AccessibilityAI-Windows"
    if staging.exists():
        shutil.rmtree(staging)
    runtime = staging / "runtime"; runtime.mkdir(parents=True)
    with zipfile.ZipFile(package) as archive:
        for item in archive.infolist():
            path = safe_path(item.filename)
            if path.parts[0] == "tools" and len(path.parts) > 1 and not item.is_dir():
                target = runtime.joinpath(*path.parts[1:]); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    for wheel in sorted(wheels.glob("*.whl")):
        print("Verifying and installing " + wheel.name, flush=True)
        install_wheel(wheel, runtime)
    source = staging / "app-source"; source.mkdir()
    excluded = {".git", ".venv", ".venvs", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist", "raw", "tensorboard", "artifacts", "ci-state"}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not p.is_symlink() and not any(part in excluded for part in rel.parts) and p.suffix not in {".pyc", ".zip", ".log"} and not p.name.startswith(".env"):
            dest = source / rel; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dest)
    (staging / "Start AccessibilityAI.bat").write_text(
        '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
        'start "" "%~dp0runtime\\pythonw.exe" -E "%~dp0app-source\\launcher.py" %*\r\n', encoding="ascii")
    (staging / "Diagnose startup.bat").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\n'
        '"%~dp0runtime\\python.exe" -E "%~dp0app-source\\launcher.py" %*\r\npause\r\n', encoding="ascii")
    (staging / "README-WINDOWS.txt").write_text(
        "Audial-AI - Windows 10/11 x64 (legacy portable developer package)\n\n"
        "Extract the entire ZIP to a writable folder and double-click Start AccessibilityAI.bat.\n"
        "Python and native Windows dependencies are included; setup.bat is unnecessary.\n"
        "ISL playback and the bundled experimental emotion model are local.\n"
        "First launch opens Setup & models to prepare the complete supported catalogue.\n"
        "Downloads need Internet access. Speech processing then runs locally.\n"
        "Choose Settings to enable emotion estimates and assign colors.\n"
        "Use Diagnose startup.bat if the application does not launch.\n"
        "Read app-source/README.md and docs/user_guide.md for coverage and measured limitations.\n"
        "The included model has not met 85-90% accuracy on Indian voices.\n"
        "This archive is assembled with Windows binaries; validation results accompany the release.\n",
        encoding="utf-8")
    from app import __version__
    inventory = {"version": __version__, "platform": "Windows x64", "python_url": PYTHON_URL,
                 "python_sha512": PYTHON_SHA512, "windows_execution_verified": False,
                 "wheels": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels.glob("*.whl")}}
    (staging / "runtime_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    print("Compressing portable desktop", flush=True)
    temporary = output.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in staging.rglob("*"):
            if p.is_file():
                archive.write(p, "AccessibilityAI-Windows/" + p.relative_to(staging).as_posix())
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip():
            raise ValueError("ZIP integrity check failed.")
    temporary.replace(output)
    print(json.dumps({"path": str(output), "bytes": output.stat().st_size,
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    args = parser.parse_args()
    build(args.output, args.cache)


if __name__ == "__main__":
    main()
