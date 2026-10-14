"""Develop attentive temporal emotion pooling without accessing test scores."""
import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
import torch
from sklearn.metrics import accuracy_score,f1_score
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.temporal_head import TemporalNetwork,TemporalHead,ProbabilityVoteHead,FEATURE_VERSION
from accessibilityai_upgrade.ssl_features import file_sha256
from scripts.train_ssl_emotion import load_features,write_json
from scripts.cache_temporal_emotion import TEMPORAL_VERSION


def temporal_cache(folder,manifest_path,count):
    folder=Path(folder)
    meta=json.loads((folder/"temporal.json").read_text())
    if meta["manifest_sha256"]!=file_sha256(manifest_path) or meta["completed"]!=count or meta["feature_version"]!=TEMPORAL_VERSION:
        raise ValueError("Temporal features are incomplete or differ from the manifest.")
    values=np.load(folder/"temporal.npy",mmap_mode="r")
    if list(values.shape)!=meta["shape"] or values.dtype!=np.float16:
        raise ValueError("Temporal feature shape or dtype differs.")
    return values,meta


def train(manifest_path,features_path,output,epochs=90,threads=4):
    out=Path(output)
    if (out/"selection.json").exists() or (out/"evaluation.json").exists():raise ValueError("Use a new development experiment folder.")
    out.mkdir(parents=True,exist_ok=True)
    f,y,ix,manifest,meta=load_features(manifest_path,features_path)
    temporal,tm=temporal_cache(features_path,manifest_path,len(f))
    for key in ["encoder","encoder_sha256","precision","cpu_threads"]:
        if tm[key]!=meta[key]:raise ValueError("Temporal and global encoders differ.")
    torch.set_num_threads(threads)
    tr,va=ix["train"],ix["validation"]
    classes=np.unique(y[tr]);labels={c:i for i,c in enumerate(classes)}
    ytr=torch.tensor([labels[c] for c in y[tr]]);yva=np.array([labels[c] for c in y[va]])
    raw=np.asarray(f[tr]).reshape(len(tr),-1)
    mean,scale=raw.mean(0),raw.std(0);scale[scale<1e-5]=1
    Gtr=torch.from_numpy((raw-mean)/scale);del raw
    Gva=torch.from_numpy((np.asarray(f[va]).reshape(len(va),-1)-mean)/scale)
    raw=np.asarray(temporal[tr],dtype=np.float32)
    frame_mean,frame_scale=raw.mean((0,1)),raw.std((0,1));frame_scale[frame_scale<1e-5]=1
    Ftr=torch.from_numpy((raw-frame_mean)/frame_scale);del raw
    Fva=torch.from_numpy((np.asarray(temporal[va],dtype=np.float32)-frame_mean)/frame_scale)
    groups=np.array([manifest["clips"][int(i)]["speaker_id"] for i in tr])
    speakers,group_index=np.unique(groups,return_inverse=True);group_index=torch.from_numpy(group_index)
    global_centers=torch.stack([Gtr[np.flatnonzero(groups==s)].mean(0) for s in speakers]);global_centers-=Gtr.mean(0)
    frame_centers=torch.stack([Ftr[np.flatnonzero(groups==s)].mean((0,1)) for s in speakers]);frame_centers-=Ftr.mean((0,1))
    rows,heads,best=[],[],None
    for dropout,augment,seed in [(0.4,False,42),(0.5,True,42),(0.5,True,1729)]:
        torch.manual_seed(seed);rng=np.random.default_rng(seed)
        net=TemporalNetwork(f.shape[1:],tm["bins"],128,dropout)
        opt=torch.optim.AdamW(net.parameters(),lr=0.0004,weight_decay=0.02)
        schedule=torch.optim.lr_scheduler.CosineAnnealingLR(opt,epochs)
        best_score,best_epoch,state,stale=(-1,-1),0,None,0
        started=time.monotonic()
        for epoch in range(epochs):
            net.train();order=rng.permutation(len(tr));total=0
            for start in range(0,len(tr),64):
                batch=order[start:start+64];global_values,frames=Gtr[batch],Ftr[batch]
                if augment:
                    other=torch.from_numpy(rng.integers(len(speakers),size=len(batch)))
                    strength=torch.from_numpy(rng.uniform(0,0.3,(len(batch),1)).astype(np.float32))
                    global_values=global_values+strength*(global_centers[other]-global_centers[group_index[batch]])
                    frames=frames+strength[:,:,None]*(frame_centers[other]-frame_centers[group_index[batch]])[:,None,:]
                    if rng.random()<0.5:
                        offset=int(rng.integers(tm["bins"]-8));frames[:,offset:offset+8]=0
                opt.zero_grad(set_to_none=True)
                loss=torch.nn.functional.cross_entropy(net(global_values,frames),ytr[batch],label_smoothing=0.05)
                loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),5);opt.step();total+=loss.item()*len(batch)
            schedule.step();net.eval()
            with torch.inference_mode():
                logits=torch.cat([net(Gva[i:i+64],Fva[i:i+64]) for i in range(0,len(va),64)])
            pred=logits.argmax(1).numpy()
            score=(float(accuracy_score(yva,pred)),float(f1_score(yva,pred,average="macro")))
            if score>best_score:
                best_score,best_epoch=score,epoch+1
                state={k:v.detach().numpy().copy() for k,v in net.state_dict().items()};stale=0
            else:stale+=1
            if (epoch+1)%5==0 or epoch==0:
                print(json.dumps({"seed":seed,"augmentation":augment,"epoch":epoch+1,
                    "train_loss":round(total/len(tr),4),"validation_accuracy":score[0],
                    "best_validation_accuracy":best_score[0],"seconds":round(time.monotonic()-started,1)}),flush=True)
            if epoch>=29 and stale>=20:break
        head=TemporalHead(f.shape[1:],tm["bins"],mean,scale,frame_mean,frame_scale,state,128,dropout,classes)
        row={"model":"temporal-attentive","seed":seed,"dropout":dropout,"augmentation":augment,"epoch":best_epoch,
             "validation_accuracy":best_score[0],"validation_macro_f1":best_score[1],
             "layers":list(range(1,25)),"aggregation":"concat"}
        heads.append(head);rows.append(row)
        joblib.dump({"head":head,"row":row},out/f"head-{seed}-{augment}.joblib",compress=3)
        if best is None or best_score>best[0]:best=(best_score,head,row)
        write_json(out/"development_progress.json",{"candidates":rows,"test_used_for_selection":False})
    ensemble=ProbabilityVoteHead(heads)
    Xva=np.concatenate([np.asarray(f[va]).reshape(len(va),-1),np.asarray(temporal[va],dtype=np.float32).reshape(len(va),-1)],axis=1)
    pred=ensemble.predict(Xva)
    score=(float(accuracy_score(y[va],pred)),float(f1_score(y[va],pred,average="macro")))
    row={"model":"temporal-soft-vote-3","validation_accuracy":score[0],"validation_macro_f1":score[1],
         "layers":list(range(1,25)),"aggregation":"concat","members":rows.copy()};rows.append(row)
    if score>best[0]:best=(score,ensemble,row)
    bundle={"model":best[1],"layers":list(range(1,25)),"aggregation":"concat","name":best[2]["model"],
            "feature_version":FEATURE_VERSION,"encoder":meta["encoder"],"encoder_sha256":meta["encoder_sha256"],
            "precision":meta["precision"],"cpu_threads":meta["cpu_threads"],"dataset":manifest["dataset"],
            "temporal_layers":tm["layers"],"temporal_bins":tm["bins"]}
    joblib.dump(bundle,out/"selected.joblib",compress=3)
    write_json(out/"selection.json",{"seed":42,"complete":True,"candidates":rows,"selected":best[2],
               "manifest_sha256":file_sha256(manifest_path),"test_used_for_selection":False})
    print(json.dumps({"selected":best[2]}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True);p.add_argument("--features",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--epochs",type=int,default=90)
    p.add_argument("--threads",type=int,default=4);args=p.parse_args()
    with threadpool_limits(limits=args.threads):train(args.manifest,args.features,args.output,args.epochs,args.threads)


if __name__=="__main__":main()
