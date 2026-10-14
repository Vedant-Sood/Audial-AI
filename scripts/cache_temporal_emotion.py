"""Cache temporal and global speech features in one frozen-encoder pass.

Resumes only with matching audio/encoder hashes and precision. Existing pooled
features are verified rather than overwritten when adding the temporal cache.
The test partition is processed as inputs only; no classifier scores are made.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.audio import read_wav
from accessibilityai_upgrade.ssl_features import PooledEncoder,ENCODERS,FEATURE_VERSION,file_sha256
from scripts.train_ssl_emotion import validate_manifest,write_json

TEMPORAL_VERSION="ssl-temporal-bins-v1"


def extract(manifest_path,checkpoint,name,output,precision="bfloat16",threads=4,layers=(12,14),bins=64):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(Path(manifest_path).read_text());validate_manifest(manifest)
    encoder=PooledEncoder(name,checkpoint,ENCODERS[name]["sha256"],precision=precision,cpu_threads=threads)
    common={"manifest_sha256":file_sha256(manifest_path),"encoder":name,
            "encoder_sha256":ENCODERS[name]["sha256"],"precision":precision,"cpu_threads":threads}
    pooled_meta={**common,"feature_version":FEATURE_VERSION,"shape":[len(manifest["clips"]),encoder.layers,2,encoder.width],
                 "dtype":"float32","completed":0}
    temporal_meta={**common,"feature_version":TEMPORAL_VERSION,"shape":[len(manifest["clips"]),bins,encoder.width],
                   "dtype":"float16","layers":list(layers),"bins":bins,"completed":0,
                   "aggregation":"Mean of selected layer frames; adaptive temporal average pooling"}
    def open_cache(filename,metadata):
        path=out/(filename+".json")
        if path.exists():
            saved=json.loads(path.read_text())
            if any(saved.get(k)!=v for k,v in metadata.items() if k!="completed"):
                raise ValueError(f"{filename} cache provenance differs.")
            array=np.load(out/(filename+".npy"),mmap_mode="r+")
            if list(array.shape)!=metadata["shape"] or str(array.dtype)!=metadata["dtype"]:
                raise ValueError("Cache shape or dtype differs.")
            return array,saved
        array=np.lib.format.open_memmap(out/(filename+".npy"),mode="w+",dtype=metadata["dtype"],shape=tuple(metadata["shape"]))
        write_json(path,metadata)
        return array,metadata
    global_array,pooled_meta=open_cache("features",pooled_meta)
    temporal_array,temporal_meta=open_cache("temporal",temporal_meta)
    first=min(pooled_meta["completed"],temporal_meta["completed"])
    started=time.monotonic()
    for i in range(first,len(manifest["clips"])):
        clip=manifest["clips"][i]
        if file_sha256(clip["path"])!=clip["sha256"]:raise ValueError("Audio changed after verification.")
        pooled,temporal=encoder.extract_with_temporal(read_wav(clip["path"]),temporal_layers=list(layers),bins=bins)
        if i<pooled_meta["completed"]:
            if not np.array_equal(pooled,global_array[i]):raise ValueError("Existing pooled features differ from this encoder run.")
        else:global_array[i]=pooled
        if i<temporal_meta["completed"]:
            if not np.array_equal(temporal,temporal_array[i]):raise ValueError("Existing temporal features differ from this run.")
        else:temporal_array[i]=temporal
        if (i+1)%50==0 or i+1==len(manifest["clips"]):
            global_array.flush();temporal_array.flush()
            pooled_meta["completed"]=max(pooled_meta["completed"],i+1)
            temporal_meta["completed"]=max(temporal_meta["completed"],i+1)
            write_json(out/"features.json",pooled_meta);write_json(out/"temporal.json",temporal_meta)
            rate=(i+1-first)/max(time.monotonic()-started,1e-9)
            print(json.dumps({"completed":i+1,"clips":len(manifest["clips"]),"clips_per_second":round(rate,2),
                  "estimated_remaining_minutes":round((len(manifest["clips"])-i-1)/rate/60,1)}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path,required=True)
    p.add_argument("--encoder",choices=list(ENCODERS),required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--threads",type=int,default=4)
    p.add_argument("--precision",choices=["float32","bfloat16"],default="bfloat16")
    args=p.parse_args()
    with threadpool_limits(limits=args.threads):
        extract(args.manifest,args.checkpoint,args.encoder,args.output,args.precision,args.threads)


if __name__=="__main__":main()
