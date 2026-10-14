"""Develop a neural layer-mixture emotion head on speaker-disjoint partitions.

Features are frozen WavLM vectors. The development score chooses the epoch and
head; test and calibration clips do not fit preprocessing or augmentation.
"""
import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.layer_mix import LayerMixNetwork, LayerMixHead
from accessibilityai_upgrade.ssl_features import FEATURE_VERSION, file_sha256
from accessibilityai_upgrade.emotion_heads import LayerHeadEnsemble
from scripts.train_ssl_emotion import load_features, write_json


def train(manifest_path, features_path, output, epochs=120, threads=4):
    out = Path(output)
    if (out/"evaluation.json").exists() or (out/"selection.json").exists():
        raise ValueError("Use a new experiment folder; test results cannot guide training.")
    out.mkdir(parents=True, exist_ok=True)
    f, y, ix, manifest, meta = load_features(manifest_path, features_path)
    torch.set_num_threads(threads)
    train_idx, val_idx = ix["train"], ix["validation"]
    classes = np.unique(y[train_idx])
    if len(classes) != 6: raise ValueError("The native application supports six trained emotions.")
    label_index = {c:i for i,c in enumerate(classes)}
    ytr = torch.tensor([label_index[c] for c in y[train_idx]])
    yva = np.array([label_index[c] for c in y[val_idx]])
    train_raw = np.asarray(f[train_idx]).reshape(len(train_idx),-1)
    mean = train_raw.mean(0)
    scale = train_raw.std(0)
    scale[scale < 1e-5] = 1
    Xtr = torch.from_numpy((train_raw-mean)/scale)
    del train_raw
    Xva = torch.from_numpy((np.asarray(f[val_idx]).reshape(len(val_idx),-1)-mean)/scale)
    groups = np.array([manifest["clips"][int(i)]["speaker_id"] for i in train_idx])
    speakers, speaker_index = np.unique(groups, return_inverse=True)
    # Actor centers are learned on training actors only. Augmentation changes
    # voice style without ever normalizing a test voice from its other clips.
    centers = torch.stack([Xtr[np.flatnonzero(groups==s)].mean(0) for s in speakers])
    centers -= Xtr.mean(0)
    speaker_index = torch.from_numpy(speaker_index)
    rows, candidates, best = [], [], None
    settings = [(128,0.4,0.01,False,42), (256,0.5,0.03,True,42),
                (256,0.5,0.03,True,1729)]
    for hidden, dropout, decay, augment, seed in settings:
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        net = LayerMixNetwork(f.shape[1:],hidden,dropout)
        opt = torch.optim.AdamW(net.parameters(),lr=0.0006,weight_decay=decay)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt,epochs)
        best_epoch, best_score, best_state, stale = 0, (-1,-1), None, 0
        start = time.monotonic()
        for epoch in range(epochs):
            net.train()
            order = rng.permutation(len(Xtr))
            total_loss = 0
            for offset in range(0,len(order),128):
                batch = order[offset:offset+128]
                values = Xtr[batch]
                if augment:
                    own = centers[speaker_index[batch]]
                    other = centers[torch.from_numpy(rng.integers(len(centers),size=len(batch)))]
                    strength = torch.from_numpy(rng.uniform(0,0.5,(len(batch),1)).astype(np.float32))
                    values = values + strength*(other-own)
                opt.zero_grad(set_to_none=True)
                loss = torch.nn.functional.cross_entropy(net(values),ytr[batch],label_smoothing=0.05)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(),5)
                opt.step()
                total_loss += loss.item()*len(batch)
            scheduler.step()
            net.eval()
            with torch.inference_mode():
                logits = torch.cat([net(Xva[i:i+128]) for i in range(0,len(Xva),128)])
                pred = logits.argmax(1).numpy()
            score = (float(accuracy_score(yva,pred)),float(f1_score(yva,pred,average="macro")))
            if score > best_score:
                best_score, best_epoch = score, epoch+1
                best_state = {k:v.detach().numpy().copy() for k,v in net.state_dict().items()}
                stale = 0
            else: stale += 1
            if (epoch+1)%5 == 0 or epoch == 0:
                print(json.dumps({"seed":seed,"hidden":hidden,"augmentation":augment,"epoch":epoch+1,
                    "train_loss":round(total_loss/len(Xtr),4),"validation_accuracy":score[0],
                    "best_validation_accuracy":best_score[0],"seconds":round(time.monotonic()-start,1)}),flush=True)
            if stale >= 25 and epoch >= 39: break
        head = LayerMixHead(f.shape[1:],mean,scale,best_state,hidden,dropout,2,classes)
        row = {"model":"layer-mix", "hidden":hidden,"dropout":dropout,"weight_decay":decay,
               "actor_style_augmentation":augment,"seed":seed,"epoch":best_epoch,
               "validation_accuracy":best_score[0],"validation_macro_f1":best_score[1],
               "layers":list(range(1,25)),"aggregation":"concat"}
        rows.append(row)
        candidates.append({"model":head,"layers":list(range(1,25)),"aggregation":"concat"})
        if best is None or best_score > best[0]: best=(best_score,head,row)
        write_json(out/"development_progress.json",{"candidates":rows,"test_used_for_selection":False})
        joblib.dump({"head":head,"row":row},out/f"head-{hidden}-{seed}.joblib",compress=3)
    ensemble = LayerHeadEnsemble(candidates,f.shape[1:])
    pred = ensemble.predict(Xva.numpy()*scale+mean)
    score = (float(accuracy_score(y[val_idx],pred)),float(f1_score(y[val_idx],pred,average="macro")))
    row = {"model":"layer-mix-soft-vote-3","validation_accuracy":score[0],"validation_macro_f1":score[1],
           "layers":list(range(1,25)),"aggregation":"concat","members":rows.copy()}
    rows.append(row)
    if score > best[0]: best=(score,ensemble,row)
    bundle = {"model":best[1],"layers":list(range(1,25)),"aggregation":"concat","name":best[2]["model"],
              "feature_version":FEATURE_VERSION,"encoder":meta["encoder"],"encoder_sha256":meta["encoder_sha256"],
              "precision":meta["precision"],"cpu_threads":meta.get("cpu_threads",4),"dataset":manifest["dataset"]}
    joblib.dump(bundle,out/"selected.joblib",compress=3)
    write_json(out/"selection.json",{"seed":42,"complete":True,"candidates":rows,"selected":best[2],
               "manifest_sha256":file_sha256(manifest_path),"test_used_for_selection":False,
               "preprocessing":"Train-actor feature mean/std; training-only actor-style augmentation"})
    print(json.dumps({"selected":best[2]}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--features",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--epochs",type=int,default=120)
    p.add_argument("--threads",type=int,default=4)
    args=p.parse_args()
    with threadpool_limits(limits=args.threads):
        train(args.manifest,args.features,args.output,args.epochs,args.threads)


if __name__ == "__main__": main()
