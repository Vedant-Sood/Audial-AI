"""Fit a speaker-disjoint out-of-fold emotion stack, then refit its base heads.

Calibration/test actors never fit preprocessing, base heads or the meta-head.
OOF diagnostics are development estimates, not an independent accuracy claim.
The separate evaluation command freezes confidence before opening test scores.
"""
import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
import torch
from scipy.special import log_softmax
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,f1_score
from sklearn.metrics.pairwise import euclidean_distances
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler,Normalizer
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.emotion_heads import SpeakerNuisanceProjection
from accessibilityai_upgrade.fusion_stack import FEATURE_VERSION,FusionStackHead,member_input,meta_features
from accessibilityai_upgrade.kernel_head import CachedRBFHead
from accessibilityai_upgrade.layer_mix import LayerMixHead,LayerMixNetwork
from accessibilityai_upgrade.ssl_features import file_sha256,pool_layers
from accessibilityai_upgrade.train import raw_logits
from scripts.train_ssl_emotion import load_features,write_json


def acoustic_cache(manifest_path):
    p=Path(manifest_path).parent
    meta=json.loads((p/"acoustic_features.json").read_text())
    if meta["manifest_sha256"]!=file_sha256(manifest_path):raise ValueError("Acoustic feature provenance differs.")
    a=np.load(p/"acoustic_features.npy",mmap_mode="r")
    if list(a.shape)!=meta["shape"] or a.dtype!=np.float32 or meta["completed"]!=len(a):
        raise ValueError("Acoustic feature cache is incomplete.")
    return a


def fit_kernel(X,y,groups,desc):
    steps=[StandardScaler()]
    if desc.get("projection"):steps.append(SpeakerNuisanceProjection(desc["projection"]))
    if desc.get("aggregation")=="concat":steps.append(PCA(n_components=256,whiten=True,svd_solver="randomized",random_state=42))
    if desc.get("normalize"):steps.append(Normalizer())
    pre=make_pipeline(*steps)
    params={"speakernuisanceprojection__groups":groups} if desc.get("projection") else {}
    values=pre.fit_transform(X,y,**params).astype(np.float32)
    gamma=float(desc["gamma_factor"]/(values.shape[1]*values.var()))
    kernel=np.exp(-gamma*euclidean_distances(values,squared=True)).astype(np.float64)
    clf=SVC(C=desc["C"],kernel="precomputed",break_ties=True,cache_size=256).fit(kernel,y)
    return CachedRBFHead(pre,clf,values[clf.support_].copy(),gamma,len(values))


def fit_neural(X,y,groups,shape,epochs=6,seed=42,schedule_epochs=120):
    # This architecture/epoch count came from the preceding CREMA-D development
    # experiment. Every OOF fit recomputes normalization on its own train actors.
    torch.manual_seed(seed);rng=np.random.default_rng(seed)
    mean,scale=X.mean(0),X.std(0);scale[scale<1e-5]=1
    values=torch.from_numpy((X-mean)/scale)
    classes,numeric=np.unique(y,return_inverse=True);labels=torch.from_numpy(numeric)
    speakers,index=np.unique(groups,return_inverse=True);index=torch.from_numpy(index)
    centers=torch.stack([values[np.flatnonzero(groups==s)].mean(0) for s in speakers]);centers-=values.mean(0)
    net=LayerMixNetwork(shape,hidden=256,dropout=0.5)
    opt=torch.optim.AdamW(net.parameters(),lr=0.0006,weight_decay=0.03)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(opt,schedule_epochs)
    for epoch in range(epochs):
        net.train();order=rng.permutation(len(X))
        for start in range(0,len(order),128):
            batch=order[start:start+128]
            other=torch.from_numpy(rng.integers(len(centers),size=len(batch)))
            strength=torch.from_numpy(rng.uniform(0,0.5,(len(batch),1)).astype(np.float32))
            augmented=values[batch]+strength*(centers[other]-centers[index[batch]])
            opt.zero_grad(set_to_none=True)
            loss=torch.nn.functional.cross_entropy(net(augmented),labels[batch],label_smoothing=0.05)
            loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),5);opt.step()
        scheduler.step()
    state={k:v.detach().numpy().copy() for k,v in net.state_dict().items()}
    return LayerMixHead(shape,mean,scale,state,256,0.5,2,classes)


def train(manifest_path,feature_folder,kernel_selection,output,threads=3,resume=False):
    out=Path(output)
    if (out/"evaluation.json").exists() or (out/"selection.json").exists():raise ValueError("This experiment already completed; use a new folder.")
    out.mkdir(parents=True,exist_ok=True)
    f,y,ix,manifest,meta=load_features(manifest_path,feature_folder)
    acoustic=acoustic_cache(manifest_path)
    if len(acoustic)!=len(f):raise ValueError("Acoustic and speech feature counts differ.")
    fit=np.r_[ix["train"],ix["validation"]]
    groups=np.array([manifest["clips"][int(i)]["speaker_id"] for i in fit])
    classes=np.unique(y[fit]);torch.set_num_threads(threads)
    selected=json.loads(Path(kernel_selection).read_text())["selected"]
    descriptions=selected.get("members",[selected])
    prototypes=[{"kind":"ssl-kernel",**d} for d in descriptions]
    prototypes.append({"kind":"ssl-neural","layers":list(range(1,25)),"aggregation":"concat","epochs":6,"seed":42})
    prototypes.append({"kind":"acoustic","layers":[],"aggregation":"mean","projection":0,"normalize":False,"C":10,"gamma_factor":0.2})
    protocol={"manifest_sha256":file_sha256(manifest_path),"kernel_selection_sha256":file_sha256(kernel_selection),
              "seed":42,"folds":5,"prototypes":prototypes,"fit_partitions":["train","validation"],
              "calibration_and_test_used":False}
    path=out/"protocol.json"
    if path.exists():
        if not resume or json.loads(path.read_text())!=protocol:raise ValueError("Resume protocol differs.")
        oof=np.load(out/"oof.npy",mmap_mode="r+")
        progress=json.loads((out/"oof_progress.json").read_text())
    else:
        write_json(path,protocol)
        oof=np.lib.format.open_memmap(out/"oof.npy",mode="w+",dtype="float32",shape=(len(fit),len(prototypes)*len(classes)+15))
        oof[:]=np.nan
        progress={"completed_folds":[]}
        write_json(out/"oof_progress.json",progress)
    folds=list(GroupKFold(n_splits=5,shuffle=True,random_state=42).split(fit,y[fit],groups))
    for fold,(a,b) in enumerate(folds):
        if fold in progress["completed_folds"]:continue
        started=time.monotonic();tr,va=fit[a],fit[b]
        if set(groups[a])&set(groups[b]):raise ValueError("OOF speaker leakage.")
        if {manifest["clips"][int(i)]["sha256"] for i in tr}&{manifest["clips"][int(i)]["sha256"] for i in va}:
            raise ValueError("OOF identical-audio leakage.")
        logits=[]
        for desc in prototypes:
            Xtr=member_input(desc,f[tr],acoustic[tr]);Xva=member_input(desc,f[va],acoustic[va])
            model=fit_neural(Xtr,y[tr],groups[a],f.shape[1:]) if desc["kind"]=="ssl-neural" else fit_kernel(Xtr,y[tr],groups[a],desc)
            if not np.array_equal(model.classes_,classes):raise ValueError("OOF class order differs.")
            logits.append(log_softmax(raw_logits(model,Xva),axis=1))
            del model,Xtr,Xva
        oof[b]=np.concatenate([*logits,acoustic[va,-15:]],axis=1)
        oof.flush();progress["completed_folds"].append(fold)
        write_json(out/"oof_progress.json",progress)
        write_json(out/f"fold-{fold}.json",{"train_speakers":np.unique(groups[a]).tolist(),"validation_speakers":np.unique(groups[b]).tolist()})
        print(json.dumps({"completed_fold":fold+1,"folds":5,"validation_speakers":len(np.unique(groups[b])),"seconds":round(time.monotonic()-started,1)}),flush=True)
    if not np.all(np.isfinite(oof)):raise ValueError("OOF predictions are incomplete or non-finite.")
    rows,best=[],None
    for c in [0.01,0.1,1]:
        predicted=np.empty(len(fit),dtype=y.dtype)
        for a,b in folds:
            model=make_pipeline(StandardScaler(),LogisticRegression(C=c,max_iter=700,random_state=42)).fit(oof[a],y[fit[a]])
            predicted[b]=model.predict(oof[b])
        score=(float(accuracy_score(y[fit],predicted)),float(f1_score(y[fit],predicted,average="macro")))
        row={"C":c,"meta_group_cv_accuracy":score[0],"meta_group_cv_macro_f1":score[1]};rows.append(row)
        if best is None or score>best[0]:best=(score,c)
        print(json.dumps(row),flush=True)
    meta_model=make_pipeline(StandardScaler(),LogisticRegression(C=best[1],max_iter=700,random_state=42)).fit(oof,y[fit])
    members=[]
    for number,desc in enumerate(prototypes):
        X=member_input(desc,f[fit],acoustic[fit])
        model=fit_neural(X,y[fit],groups,f.shape[1:]) if desc["kind"]=="ssl-neural" else fit_kernel(X,y[fit],groups,desc)
        member={**desc,"model":model};members.append(member)
        print(json.dumps({"refitted_base":number+1,"bases":len(prototypes),"actors":len(np.unique(groups))}),flush=True)
    head=FusionStackHead(members,meta_model,f.shape[1:])
    bundle={"model":head,"name":"speaker-oof-acoustic-fusion","feature_version":FEATURE_VERSION,
            "encoder":meta["encoder"],"encoder_sha256":meta["encoder_sha256"],"precision":meta["precision"],
            "cpu_threads":meta["cpu_threads"],"dataset":manifest["dataset"],"layers":list(range(1,25)),
            "aggregation":"concat","refit_training_and_validation":True,"acoustic_count":183}
    joblib.dump(bundle,out/"selected.joblib",compress=3)
    write_json(out/"selection.json",{"complete":True,"selected":{"model":bundle["name"],"meta_C":best[1]},
               "meta_development_diagnostics":rows,"protocol":protocol,"manifest_sha256":file_sha256(manifest_path),
               "diagnostic_limit":"Meta CV uses speaker-OOF base predictions but is not a fully nested independent test.",
               "test_used_for_selection":False,"refit_training_and_validation":True})
    print(json.dumps({"selected":bundle["name"],"meta_C":best[1],"model_bytes":(out/"selected.joblib").stat().st_size}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True);p.add_argument("--features",type=Path,required=True)
    p.add_argument("--kernel-selection",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--threads",type=int,default=3);p.add_argument("--resume",action="store_true");args=p.parse_args()
    with threadpool_limits(limits=args.threads):train(args.manifest,args.features,args.kernel_selection,args.output,args.threads,args.resume)


if __name__=="__main__":main()
