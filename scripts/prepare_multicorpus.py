"""Add licensed RAVDESS speech to the six-label CREMA-D emotion task.

Actor splits are fixed before any RAVDESS model development. The two unsupported
labels, calm and surprise, are listed explicitly rather than mapped incorrectly.
The mirror's code license does not replace the corpus's CC BY-NC-SA audio terms.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess

import numpy as np

from accessibilityai_upgrade.ssl_features import file_sha256, FEATURE_VERSION
from scripts.train_ssl_emotion import validate_manifest, write_json


LABELS = {1: "neutral", 3: "happy", 4: "sad", 5: "angry", 6: "fear", 7: "disgust"}


def prepare(crema_manifest, crema_features, ravdess_root, output, seed=20261014):
    output = Path(output)
    if (output / "dataset.json").exists():
        raise ValueError("The precommitted actor assignments must not be overwritten.")
    manifest = json.loads(Path(crema_manifest).read_text())
    validate_manifest(manifest)
    ravdess_root = Path(ravdess_root)
    files = sorted((ravdess_root / "Audio_Speech_Actors_01-24").rglob("*.wav"))
    if len(files) != 1440:
        raise ValueError("Expected the complete 1,440-file RAVDESS speech release.")
    rng = np.random.default_rng(seed)
    assignments = defaultdict(list)
    for gender in [range(1, 25, 2), range(2, 25, 2)]:
        actors = rng.permutation(list(gender))
        for partition, selected in zip(
            ["train", "validation", "calibration_fit", "calibration_policy", "test"],
            [actors[:6], actors[6:7], actors[7:8], actors[8:9], actors[9:]],
        ):
            assignments[partition] += [f"ravdess-{actor:02d}" for actor in selected]
    actor_split = {actor: partition for partition, actors in assignments.items() for actor in actors}
    out = json.loads(json.dumps(manifest))
    out.update({"dataset": "CREMA-D + RAVDESS (six shared labels)",
                "license": "CREMA-D: ODbL-1.0 / DbCL-1.0; RAVDESS audio: CC-BY-NC-SA-4.0",
                "language": "en", "split_seed_ravdess":seed,
                "test_status": {"CREMA-D":"Previously published test; exposed in the 0.4 benchmark",
                                "RAVDESS":"Fresh actors reserved before training or feature extraction"},
                "source_corpora": [
                    {"name":"CREMA-D", "source_url":manifest["source_url"], "download_url":manifest["download_url"],
                     "license":manifest["license"], "inventory_sha256":file_sha256(crema_manifest)},
                    {"name":"RAVDESS", "source_url":"https://zenodo.org/records/1188976",
                     "paper_doi":"10.1371/journal.pone.0196391", "license":"CC-BY-NC-SA-4.0",
                     "download_url":"https://github.com/ZenvilleErasmus/RAVDESS-emotions-speech-audio-only",
                     "download_revision":subprocess.check_output(["git", "-C", str(ravdess_root), "rev-parse", "HEAD"],text=True).strip(),
                     "upstream_checksums_available":False, "mirror_readme_license":"README.txt",
                     "task_coverage":"Six existing app labels; calm (02) and surprise (08) are unsupported"}]})
    for clip in out["clips"]:
        clip["corpus"] = "CREMA-D"
    counts, excluded = Counter(), []
    for path in files:
        modality, channel, emotion, intensity, statement, repetition, actor = map(int, path.stem.split("-"))
        if modality != 3 or channel != 1 or actor not in range(1, 25):
            raise ValueError(f"Invalid RAVDESS speech identifier: {path.name}")
        digest = file_sha256(path)
        if emotion not in LABELS:
            excluded.append({"file":path.name, "sha256":digest,
                             "original_label":"calm" if emotion == 2 else "surprise",
                             "reason":"Unsupported in the pre-existing six-label application task"})
            continue
        speaker = f"ravdess-{actor:02d}"
        partition = actor_split[speaker]
        out["clips"].append({"path":str(path.resolve()), "file":"RAVDESS/"+path.name,
                             "label":LABELS[emotion], "speaker_id":speaker,
                             "partition":partition, "sha256":digest, "corpus":"RAVDESS"})
        counts[partition] += 1
    if len(excluded) != 384 or sum(counts.values()) != 1056:
        raise ValueError("Unexpected shared-label counts.")
    for part, actors in assignments.items():
        out["splits"][part]["speakers"] += actors
        out["splits"][part]["clips"] += counts[part]
    validate_manifest(out)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "dataset.json", out)
    write_json(output / "ravdess_scope.json", {"total_speech_files":1440, "shared_label_files":1056,
               "excluded":excluded, "seed":seed, "actor_splits":dict(assignments),
               "split_counts":dict(counts), "source":out["source_corpora"][1]})
    # Reuse the byte-identical CREMA-D features, never recompute test inputs with
    # a different encoder precision. New extraction starts after this prefix.
    old_meta = json.loads((Path(crema_features)/"features.json").read_text())
    old = np.load(Path(crema_features)/"features.npy", mmap_mode="r")
    if old_meta["completed"] != len(manifest["clips"]) or old_meta["manifest_sha256"] != file_sha256(crema_manifest):
        raise ValueError("CREMA-D feature provenance differs.")
    shape = [len(out["clips"]), *old.shape[1:]]
    folder = output / "features"
    folder.mkdir()
    features = np.lib.format.open_memmap(folder/"features.npy", mode="w+", dtype="float32", shape=tuple(shape))
    for start in range(0, len(old), 128):
        end = min(start+128, len(old))
        features[start:end] = old[start:end]
    features.flush()
    old_meta.update({"shape":shape, "manifest_sha256":file_sha256(output/"dataset.json")})
    write_json(folder/"features.json", old_meta)
    print(json.dumps({"splits":out["splits"], "ravdess_actor_splits":dict(assignments),
                      "unsupported_label_clips":len(excluded), "feature_prefix_reused":len(old)}),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--crema-manifest",type=Path,required=True)
    p.add_argument("--crema-features",type=Path,required=True)
    p.add_argument("--ravdess-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    prepare(args.crema_manifest,args.crema_features,args.ravdess_root,args.output)


if __name__ == "__main__": main()
