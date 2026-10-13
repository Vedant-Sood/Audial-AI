"""Download pinned CREMA-D audio shards; preserve provenance and upstream license."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

REVISION = "b7d5beded69285eb5eb6a1c6894a5b0ad17cab92"
DATASET = "cfahlgren1/crema-d"
UPSTREAM = "https://github.com/CheyneyComputerScience/CREMA-D"


def download_one(args):
    index, directory = args
    filename = f"train-{index:05d}-of-00004.parquet"
    url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/data/{filename}"
    target = directory / filename
    if not target.exists():
        temporary = target.with_suffix(".partial")
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(target)
    digest = hashlib.sha256()
    with target.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    print(f"Downloaded {filename}: {target.stat().st_size:,} bytes", flush=True)
    return {"filename": filename, "url": url, "bytes": target.stat().st_size, "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/crema-d")
    args = parser.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(download_one, [(i, directory) for i in range(4)]))
    license_url = "https://raw.githubusercontent.com/CheyneyComputerScience/CREMA-D/master/LICENSE.txt"
    with urllib.request.urlopen(license_url, timeout=60) as response:
        license_text = response.read()
    (directory / "CREMA-D-LICENSE.txt").write_bytes(license_text)
    manifest = {"dataset": DATASET, "revision": REVISION, "upstream": UPSTREAM,
                "license": "ODbL-1.0 (database); DbCL-1.0 (individual contents)", "files": files}
    (directory / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
