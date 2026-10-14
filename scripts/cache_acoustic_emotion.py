"""Prepare deterministic MFCC/pitch features for a verified emotion manifest."""
import argparse
import json
from pathlib import Path

import numpy as np

from accessibilityai_upgrade.audio import FEATURE_VERSION,read_wav,extract_features
from accessibilityai_upgrade.ssl_features import file_sha256
from scripts.train_ssl_emotion import validate_manifest,write_json


def extract(manifest_path):
    path=Path(manifest_path)
    manifest=json.loads(path.read_text());validate_manifest(manifest)
    meta={"manifest_sha256":file_sha256(path),"feature_version":FEATURE_VERSION,
          "shape":[len(manifest["clips"]),183],"dtype":"float32","completed":0}
    report=path.parent/"acoustic_features.json";data=path.parent/"acoustic_features.npy"
    if report.exists():
        saved=json.loads(report.read_text())
        if any(saved.get(k)!=v for k,v in meta.items() if k!="completed"):
            raise ValueError("Acoustic feature cache provenance differs.")
        meta=saved;features=np.load(data,mmap_mode="r+")
        if list(features.shape)!=meta["shape"] or str(features.dtype)!=meta["dtype"]:
            raise ValueError("Acoustic cache dimensions differ.")
    else:
        features=np.lib.format.open_memmap(data,mode="w+",dtype="float32",shape=tuple(meta["shape"]))
        write_json(report,meta)
    for i in range(meta["completed"],len(manifest["clips"])):
        clip=manifest["clips"][i]
        if file_sha256(clip["path"])!=clip["sha256"]:raise ValueError("Audio changed after verification.")
        features[i],_=extract_features(read_wav(clip["path"]))
        if (i+1)%100==0 or i+1==len(features):
            features.flush();meta["completed"]=i+1;write_json(report,meta)
            print(json.dumps({"completed":i+1,"clips":len(features)}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--manifest",type=Path,required=True)
    extract(p.parse_args().manifest)


if __name__=="__main__":main()
