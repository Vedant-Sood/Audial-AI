"""Select RBF regularization and kernel width on development speakers only.

Reuse pairwise distances across candidate widths, rather than recomputing audio
or kernel products for each classifier. A separate command evaluates test audio.
"""
import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, f1_score
from sklearn.metrics.pairwise import euclidean_distances
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, Normalizer
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.kernel_head import CachedRBFHead
from accessibilityai_upgrade.emotion_heads import LayerHeadEnsemble, SpeakerNuisanceProjection
from accessibilityai_upgrade.ssl_features import FEATURE_VERSION, pool_layers, file_sha256
from scripts.train_ssl_emotion import load_features, write_json


def select(manifest_path, feature_folder, output, refit_development=False, threads=4):
    out=Path(output)
    if (out/"evaluation.json").exists() or (out/"selection.json").exists():
        raise ValueError("Use a new development experiment folder.")
    out.mkdir(parents=True,exist_ok=True)
    f,y,ix,manifest,meta=load_features(manifest_path,feature_folder)
    tr,va=ix["train"],ix["validation"]
    groups=np.array([c["speaker_id"] for c in manifest["clips"]])
    representations=[([12],"mean",0,False),([14],"mean",0,False),
                     ([12],"mean",16,False),([12],"mean",0,True),
                     ([4,8,12,16,20,24],"concat",0,False)]
    rows,winners,best=[],[],None
    for layers,agg,projection,normalize in representations:
        Xtr,Xva=(pool_layers(f[ind],layers,agg) for ind in [tr,va])
        steps=[StandardScaler()]
        if projection: steps.append(SpeakerNuisanceProjection(projection))
        if agg == "concat":steps.append(PCA(n_components=256,whiten=True,svd_solver="randomized",random_state=42))
        if normalize: steps.append(Normalizer())
        pre=make_pipeline(*steps)
        params={"speakernuisanceprojection__groups":groups[tr]} if projection else {}
        A=pre.fit_transform(Xtr,y[tr],**params).astype(np.float32)
        B=pre.transform(Xva).astype(np.float32)
        train_d=euclidean_distances(A,squared=True)
        val_d=euclidean_distances(B,A,squared=True)
        gamma_scale=1/(A.shape[1]*A.var())
        winner=None
        for factor in [0.05,0.2,0.5,1,2]:
            gamma=float(gamma_scale*factor)
            K=np.exp(-gamma*train_d).astype(np.float64)
            Kv=np.exp(-gamma*val_d).astype(np.float64)
            for c in [1,10,100]:
                started=time.monotonic()
                model=SVC(C=c,kernel="precomputed",break_ties=True,cache_size=256)
                model.fit(K,y[tr])
                pred=model.predict(Kv)
                score=(float(accuracy_score(y[va],pred)),float(f1_score(y[va],pred,average="macro")))
                row={"model":"cached-rbf", "C":c,"gamma_factor":factor,"projection":projection,
                     "normalize":normalize,"layers":layers,"aggregation":agg,
                     "validation_accuracy":score[0],"validation_macro_f1":score[1],
                     "fit_seconds":round(time.monotonic()-started,2)}
                rows.append(row)
                if winner is None or score>winner[0]:
                    head=CachedRBFHead(pre,model,A[model.support_].copy(),gamma,len(tr))
                    winner=(score,{"model":head,"layers":layers,"aggregation":agg},row)
                print(json.dumps(row),flush=True)
        winners.append(winner)
        if best is None or winner[0]>best[0]:best=winner
        joblib.dump(winner[1],out/f"representation-{len(winners)}.joblib",compress=3)
        write_json(out/"development_progress.json",{"candidates":rows,"test_used_for_selection":False})
    top=sorted(winners,key=lambda w:w[0],reverse=True)[:3]
    ensemble=LayerHeadEnsemble([w[1] for w in top],f.shape[1:])
    pred=ensemble.predict(np.asarray(f[va]).reshape(len(va),-1))
    score=(float(accuracy_score(y[va],pred)),float(f1_score(y[va],pred,average="macro")))
    row={"model":"kernel-soft-vote-3","layers":list(range(1,25)),"aggregation":"concat",
         "validation_accuracy":score[0],"validation_macro_f1":score[1],"members":[w[2] for w in top]}
    rows.append(row)
    if score>best[0]:best=(score,{"model":ensemble,"layers":row["layers"],"aggregation":"concat"},row)
    selected=best[1]
    joblib.dump({**selected,"name":best[2]["model"],"feature_version":FEATURE_VERSION,
                 "encoder":meta["encoder"],"encoder_sha256":meta["encoder_sha256"],
                 "precision":meta["precision"],"cpu_threads":meta.get("cpu_threads",4),
                 "dataset":manifest["dataset"]},out/"selected_development.joblib",compress=3)
    if refit_development:
        # Architecture, C and gamma multiplier are now fixed. Confidence is still
        # fitted on two separate actor partitions by the evaluation stage.
        fit=np.r_[tr,va]
        descriptions=best[2].get("members",[best[2]])
        members=[]
        for desc in descriptions:
            X=pool_layers(f[fit],desc["layers"],desc["aggregation"])
            steps=[StandardScaler()]
            if desc["projection"]:steps.append(SpeakerNuisanceProjection(desc["projection"]))
            if desc["aggregation"]=="concat":steps.append(PCA(n_components=256,whiten=True,svd_solver="randomized",random_state=42))
            if desc["normalize"]:steps.append(Normalizer())
            pre=make_pipeline(*steps)
            params={"speakernuisanceprojection__groups":groups[fit]} if desc["projection"] else {}
            A=pre.fit_transform(X,y[fit],**params).astype(np.float32)
            gamma=desc["gamma_factor"]/(A.shape[1]*A.var())
            model=SVC(C=desc["C"],kernel="precomputed",break_ties=True,cache_size=256)
            model.fit(np.exp(-gamma*euclidean_distances(A,squared=True)).astype(np.float64),y[fit])
            members.append({"model":CachedRBFHead(pre,model,A[model.support_].copy(),gamma,len(fit)),
                            "layers":desc["layers"],"aggregation":desc["aggregation"]})
        selected=dict(selected)
        selected["model"]=LayerHeadEnsemble(members,f.shape[1:]) if len(members)>1 else members[0]["model"]
    bundle={**selected,"name":best[2]["model"],"feature_version":FEATURE_VERSION,
            "encoder":meta["encoder"],"encoder_sha256":meta["encoder_sha256"],"precision":meta["precision"],
            "cpu_threads":meta.get("cpu_threads",4),"dataset":manifest["dataset"],
            "refit_training_and_validation":refit_development}
    joblib.dump(bundle,out/"selected.joblib",compress=3)
    write_json(out/"selection.json",{"seed":42,"complete":True,"candidates":rows,"selected":best[2],
               "refit_training_and_validation":refit_development,"manifest_sha256":file_sha256(manifest_path),
               "test_used_for_selection":False})
    print(json.dumps({"selected":best[2],"refit_training_and_validation":refit_development}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--features",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--refit-development",action="store_true")
    p.add_argument("--threads",type=int,default=4)
    args=p.parse_args()
    with threadpool_limits(limits=args.threads):
        select(args.manifest,args.features,args.output,args.refit_development,args.threads)


if __name__ == "__main__":main()
