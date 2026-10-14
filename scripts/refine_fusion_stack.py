"""Compare an additional development-selected neural member before testing.

Reuses the original speaker-OOF predictions, trains the extra member on exactly
the same folds, and chooses inclusion using development diagnostics only.
"""
import argparse
import json
from pathlib import Path
import time

import joblib
import numpy as np
import torch
from scipy.special import log_softmax
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,f1_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from accessibilityai_upgrade.fusion_stack import FusionStackHead
from accessibilityai_upgrade.ssl_features import pool_layers,file_sha256
from accessibilityai_upgrade.train import raw_logits
from scripts.train_ssl_emotion import load_features,write_json
from scripts.train_fusion_stack import fit_neural


def refine(manifest_path,features_path,base,neural_selection,output,threads=3):
    base,out=Path(base),Path(output)
    if (base/"evaluation.json").exists() or (out/"selection.json").exists() or (out/"evaluation.json").exists():
        raise ValueError("Complete refinement before opening test scores, using a new output folder.")
    bundle=joblib.load(base/"selected.joblib")
    desc=json.loads(Path(neural_selection).read_text())["selected"]
    if desc["model"]!="layer-mix" or desc["hidden"]!=256 or not desc["actor_style_augmentation"]:
        raise ValueError("This refinement requires the development-selected 256-unit augmented neural head.")
    f,y,ix,manifest,meta=load_features(manifest_path,features_path)
    source_protocol=json.loads((base/"protocol.json").read_text())
    if source_protocol["manifest_sha256"]!=file_sha256(manifest_path):raise ValueError("Base stack uses a different dataset.")
    fit=np.r_[ix["train"],ix["validation"]]
    groups=np.array([manifest["clips"][int(i)]["speaker_id"] for i in fit])
    classes=np.unique(y[fit]);torch.set_num_threads(threads)
    folds=list(GroupKFold(n_splits=5,shuffle=True,random_state=42).split(fit,y[fit],groups))
    original=np.load(base/"oof.npy")
    oof=np.empty((len(fit),original.shape[1]+len(classes)),np.float32)
    oof[:,:-21]=original[:,:-15];oof[:,-15:]=original[:,-15:]
    out.mkdir(parents=True,exist_ok=True)
    write_json(out/"protocol.json",{"manifest_sha256":file_sha256(manifest_path),
        "base_model_sha256":file_sha256(base/"selected.joblib"),"neural_selection_sha256":file_sha256(neural_selection),
        "extra_neural_config":desc,"schedule_epochs":100,"test_scores_opened":False})
    for fold,(a,b) in enumerate(folds):
        previous=json.loads((base/f"fold-{fold}.json").read_text())
        if previous["validation_speakers"]!=np.unique(groups[b]).tolist():raise ValueError("OOF speaker assignments differ.")
        start=time.monotonic()
        Xtr=pool_layers(f[fit[a]],list(range(1,25)),"concat")
        Xva=pool_layers(f[fit[b]],list(range(1,25)),"concat")
        model=fit_neural(Xtr,y[fit[a]],groups[a],f.shape[1:],desc["epoch"],desc["seed"],100)
        if not np.array_equal(model.classes_,classes):raise ValueError("Neural class order differs.")
        oof[b,-21:-15]=log_softmax(raw_logits(model,Xva),axis=1)
        del model,Xtr,Xva
        print(json.dumps({"completed_extra_neural_fold":fold+1,"folds":5,"seconds":round(time.monotonic()-start,1)}),flush=True)
    rows,best=[],None
    # The original stack remains a candidate. Added complexity is retained only
    # when the same development diagnostic improves, before test evaluation.
    for extra,values in [(False,original),(True,oof)]:
        for c in [0.01,0.1,1]:
            predicted=np.empty(len(fit),dtype=y.dtype)
            for a,b in folds:
                model=make_pipeline(StandardScaler(),LogisticRegression(C=c,max_iter=700,random_state=42)).fit(values[a],y[fit[a]])
                predicted[b]=model.predict(values[b])
            score=(float(accuracy_score(y[fit],predicted)),float(f1_score(y[fit],predicted,average="macro")))
            row={"extra_neural_member":extra,"meta_C":c,"meta_group_cv_accuracy":score[0],"meta_group_cv_macro_f1":score[1]}
            rows.append(row)
            if best is None or score>best[0]:best=(score,extra,c)
            print(json.dumps(row),flush=True)
    if best[1]:
        model=fit_neural(pool_layers(f[fit],list(range(1,25)),"concat"),y[fit],groups,f.shape[1:],desc["epoch"],desc["seed"],100)
        member={"kind":"ssl-neural","layers":list(range(1,25)),"aggregation":"concat",
                "epochs":desc["epoch"],"seed":desc["seed"],"model":model}
        # Meta columns insert the added neural member immediately before the
        # final acoustic tail; member ordering follows those columns exactly.
        members=bundle["model"].members+[member]
        meta_model=make_pipeline(StandardScaler(),LogisticRegression(C=best[2],max_iter=700,random_state=42)).fit(oof,y[fit])
        bundle["model"]=FusionStackHead(members,meta_model,f.shape[1:])
    else:
        meta_model=make_pipeline(StandardScaler(),LogisticRegression(C=best[2],max_iter=700,random_state=42)).fit(original,y[fit])
        bundle["model"]=FusionStackHead(bundle["model"].members,meta_model,f.shape[1:])
    bundle["name"]="speaker-oof-acoustic-fusion-refined"
    joblib.dump(bundle,out/"selected.joblib",compress=3)
    np.save(out/"oof.npy",oof if best[1] else original)
    write_json(out/"selection.json",{"complete":True,"selected":{"model":bundle["name"],"extra_neural_member":best[1],"meta_C":best[2]},
        "meta_development_diagnostics":rows,"refit_training_and_validation":True,
        "manifest_sha256":file_sha256(manifest_path),"test_used_for_selection":False,
        "diagnostic_limit":"Meta CV of speaker-OOF base predictions is a development diagnostic, not a fully nested independent test."})
    print(json.dumps({"selected":bundle["name"],"extra_neural_member":best[1],"meta_C":best[2]}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ["manifest","features","base","neural-selection","output"]:p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--threads",type=int,default=3);args=p.parse_args()
    with threadpool_limits(limits=args.threads):refine(args.manifest,args.features,args.base,args.neural_selection,args.output,args.threads)


if __name__=="__main__":main()
