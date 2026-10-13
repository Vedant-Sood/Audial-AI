"""Download permitted upstream archives and verify their published checksums."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.parse
import urllib.request
import zipfile


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(destination) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive contains an unsafe member")
        z.extractall(destination)


def download_zenodo(record, filenames, destination):
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"https://zenodo.org/api/records/{record}", timeout=60) as r:
        metadata = json.load(r)
    license_id = metadata["metadata"].get("license", {}).get("id", "unknown")
    if license_id not in {"cc-by-4.0", "cc-by-nc-sa-4.0"}:
        raise PermissionError(f"Upstream license changed or is unverified: {license_id}; review before download")
    (dest / "upstream_metadata.json").write_text(json.dumps(metadata, indent=2))
    for name in filenames:
        item = next(f for f in metadata["files"] if f["key"] == name)
        target = dest / name
        if target.exists():
            print(f"Revalidating existing {name}", flush=True)
        else:
            tmp = target.with_suffix(".partial")
            print(f"Downloading {name} ({item['size'] / 1e6:.1f} MB); license {license_id}", flush=True)
            with urllib.request.urlopen(item["links"]["self"], timeout=120) as src, tmp.open("wb") as out:
                shutil.copyfileobj(src, out)
            tmp.replace(target)
        algorithm, expected = item["checksum"].split(":")
        digest = hashlib.new(algorithm)
        with target.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"Checksum mismatch for {name}; remove this archive and retry")
        safe_extract(target, dest / "extracted")
        print(f"Verified and extracted {name}", flush=True)


def hf_include_index(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    base = "https://datasets-server.huggingface.co"
    query = {"dataset": "ai4bharat/INCLUDE"}
    with urllib.request.urlopen(base + "/splits?" + urllib.parse.urlencode(query), timeout=60) as r:
        splits = json.load(r)["splits"]
    result = []
    for s in splits:
        offset = 0
        while True:
            params = {**s, "offset": offset, "length": 100}
            with urllib.request.urlopen(base + "/rows?" + urllib.parse.urlencode(params), timeout=60) as r:
                batch = json.load(r)
            result.extend({**row["row"], "split": s["split"]} for row in batch["rows"])
            offset += len(batch["rows"])
            if offset >= batch["num_rows_total"] or not batch["rows"]:
                break
    (destination / "include_hf_metadata.json").write_text(json.dumps(result, indent=2))
    print(f"Saved {len(result)} metadata rows; these are not video or pose training data.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("dataset", choices=["ravdess", "include", "include-index"])
    p.add_argument("--output", default="datasets/raw")
    p.add_argument("--archives", nargs="+", default=["Greetings_2of2.zip"])
    a = p.parse_args()
    if a.dataset == "include-index":
        hf_include_index(a.output)
    else:
        download_zenodo("1188976" if a.dataset == "ravdess" else "4010759",
            ["Audio_Speech_Actors_01-24.zip"] if a.dataset == "ravdess" else a.archives, a.output)
