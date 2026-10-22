"""
Train Sanket's tone-estimate model on CREMA-D features extracted by Sanket's own engine
(training/sanket/extract_crema.mjs), using the speaker splits shipped with Audial AI
(models/emotion/splits.json: 63 train / 9 validation / 9 calibration / 10 test actors).

Two heads:
  general   – absolute features, used until Sanket has heard a person a few times
  personal  – features compared with that person's own usual voice (live: their earlier utterances)

Realism: in CREMA-D every actor speaks all six emotions equally, but in real life a person's usual
voice is mostly calm. So the personal head learns from, and is evaluated with, "usual voice"
baselines made mostly of each person's neutral sentences (plus a few others), and the live-stream
evaluation starts each person with a mostly calm warm-up, exactly as a seminar would.

Selection on validation actors, temperature on calibration actors, uncertainty threshold on
validation actors, final numbers on the 10 untouched test actors.

Usage: python training/sanket/train_tone.py <crema.jsonl> <out model.json> <out report.json>
"""
import json
import sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix

LABELS = ["angry", "disgust", "fear", "happy", "neutral", "sad"]
AROUSAL = {"angry": 1.0, "fear": 0.8, "happy": 0.8, "disgust": 0.3, "neutral": 0.0, "sad": -0.8}
MIN_UTTERANCES = 4          # personal head after this many earlier utterances from the person
TARGET_ACCEPTED = 0.75      # pick the confidence threshold that keeps accepted accuracy at this level
RNG = np.random.default_rng(7)

rows = [json.loads(l) for l in open(sys.argv[1])]
rows = [r for r in rows if r["x"] is not None]
X = np.array([[np.nan if v is None else v for v in r["x"]] for r in rows], dtype=float)
y = np.array([LABELS.index(r["emotion"]) for r in rows])
actor = np.array([r["actor"] for r in rows])
split = np.array([r["split"] for r in rows])
D = X.shape[1]

train_mean = np.nanmean(X[split == "train"], axis=0)


def fill(A):
    A = A.copy()
    idx = np.where(np.isnan(A))
    A[idx] = np.take(train_mean, idx[1])
    return A


# ---------------------------------------------------------------- speaker baselines
def stats(A):
    m = np.nanmean(A, axis=0)
    s = np.nanstd(A, axis=0, ddof=1)
    return m, s

# floor for the per-person spread: a quarter of the typical within-person spread (train actors)
within_sd = np.nanmedian(np.array([stats(X[(split == "train") & (actor == a)])[1] for a in np.unique(actor[split == "train"])]), axis=0)
FLOORS = 0.25 * within_sd


def personal(xrow, m, s):
    return (xrow - m) / np.maximum(s, FLOORS)


def personal_all(mask):
    """Normalise each actor's clips with all of that actor's clips (an ideal, fully learned baseline)."""
    out = np.full((mask.sum(), D), np.nan)
    idx = np.flatnonzero(mask)
    for a in np.unique(actor[mask]):
        sel = actor[idx] == a
        m, s = stats(X[idx[sel]])
        out[sel] = personal(X[idx[sel]], m, s)
    return out


NEU = LABELS.index("neutral")


def calm_baseline(ai, rng):
    """A realistic 'usual voice': 4–10 of the person's neutral sentences plus 0–3 others."""
    neu = ai[y[ai] == NEU]
    oth = ai[y[ai] != NEU]
    k = int(rng.integers(4, min(10, len(neu) - 1) + 1))
    j = int(rng.integers(0, 4))
    return np.concatenate([rng.choice(neu, size=k, replace=False), rng.choice(oth, size=j, replace=False)])


def personal_calm(mask, copies, rng):
    """Each person's other clips, compared with a calm usual-voice baseline (several draws)."""
    xs, raws, ys = [], [], []
    idx = np.flatnonzero(mask)
    for a in np.unique(actor[mask]):
        ai = idx[actor[idx] == a]
        for _ in range(copies):
            base = calm_baseline(ai, rng)
            rest = np.setdiff1d(ai, base)
            m, s = stats(X[base])
            xs.append(personal(X[rest], m, s)); raws.append(X[rest]); ys.append(y[rest])
    return np.vstack(xs), np.vstack(raws), np.concatenate(ys)


# ---------------------------------------------------------------- candidates
def candidates():
    for C in [0.03, 0.1, 0.3, 1.0]:
        yield f"logistic C={C}", lambda C=C: LogisticRegression(C=C, max_iter=4000)
    for h in [(64,), (128,), (96, 48)]:
        for alpha in [1e-3, 1e-2, 1e-1]:
            yield f"mlp {h} a={alpha}", lambda h=h, alpha=alpha: MLPClassifier(h, alpha=alpha, max_iter=600, early_stopping=True, random_state=0)


def fit_select(Xtr, ytr, Xva, yva, name):
    sc = StandardScaler().fit(Xtr)
    best = None
    for label, make in candidates():
        clf = make().fit(sc.transform(Xtr), ytr)
        acc = accuracy_score(yva, clf.predict(sc.transform(Xva)))
        if best is None or acc > best[0]:
            best = (acc, label, clf)
    print(f"[{name}] selected {best[1]} — validation accuracy {best[0]:.3f}")
    return sc, best[2], best[1], best[0]


def logits(clf, sc, A):
    Z = sc.transform(A)
    if isinstance(clf, LogisticRegression):
        return clf.decision_function(Z)
    h = Z
    for i, (W, b) in enumerate(zip(clf.coefs_, clf.intercepts_)):
        h = h @ W + b
        if i < len(clf.coefs_) - 1:
            h = np.maximum(h, 0)
    return h


def softmax(z, T=1.0):
    z = z / T
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_temperature(z, yy):
    best = (1e9, 1.0)
    for T in np.exp(np.linspace(np.log(0.3), np.log(5), 120)):
        p = softmax(z, T)
        nll = -np.mean(np.log(p[np.arange(len(yy)), yy] + 1e-12))
        if nll < best[0]:
            best = (nll, T)
    return best[1]


def pick_threshold(p, yy):
    conf = p.max(axis=1)
    pred = p.argmax(axis=1)
    best = 1.0
    for t in np.linspace(0.2, 0.95, 151):
        acc = conf >= t
        if acc.sum() >= 20 and (pred[acc] == yy[acc]).mean() >= TARGET_ACCEPTED:
            best = t
            break
    return float(best)


def summary(p, yy, thr):
    pred = p.argmax(axis=1)
    conf = p.max(axis=1)
    acc = conf >= thr
    return {
        "accuracy": round(float(accuracy_score(yy, pred)), 4),
        "macro_f1": round(float(f1_score(yy, pred, average="macro")), 4),
        "accepted_accuracy": round(float((pred[acc] == yy[acc]).mean()) if acc.any() else 0, 4),
        "coverage": round(float(acc.mean()), 4),
        "confusion": confusion_matrix(yy, pred, labels=range(len(LABELS))).tolist(),
    }


def export(sc, clf, T, thr, extra=None):
    layers = []
    if isinstance(clf, LogisticRegression):
        layers.append({"W": np.round(clf.coef_, 6).tolist(), "b": np.round(clf.intercept_, 6).tolist(), "act": "none"})
    else:
        for i, (W, b) in enumerate(zip(clf.coefs_, clf.intercepts_)):
            layers.append({"W": np.round(W.T, 6).tolist(), "b": np.round(b, 6).tolist(),
                           "act": "relu" if i < len(clf.coefs_) - 1 else "none"})
    head = {"mean": np.round(sc.mean_, 6).tolist(), "scale": np.round(sc.scale_, 6).tolist(),
            "layers": layers, "temperature": round(float(T), 4), "threshold": round(thr, 4)}
    if extra:
        head.update(extra)
    return head


tr, va, ca, te = (split == s for s in ("train", "validation", "calibration", "test"))
report = {"labels": LABELS, "splits": {s: int((split == s).sum()) for s in ("train", "validation", "calibration", "test")}}

# ---------------------------------------------------------------- general head
Xf = fill(X)
sc_g, clf_g, sel_g, va_g = fit_select(Xf[tr], y[tr], Xf[va], y[va], "general")
T_g = fit_temperature(logits(clf_g, sc_g, Xf[ca]), y[ca])
thr_g = pick_threshold(softmax(logits(clf_g, sc_g, Xf[va]), T_g), y[va])
p_te_g = softmax(logits(clf_g, sc_g, Xf[te]), T_g)
report["general"] = {"selected": sel_g, "validation_accuracy": round(va_g, 4), "temperature": T_g, "threshold": thr_g,
                     "test": summary(p_te_g, y[te], thr_g)}
print("general test", {k: v for k, v in report["general"]["test"].items() if k != "confusion"})

# ---------------------------------------------------------------- personal head (+ absolute pitch & loudness kept)
RAW_KEEP = [34, 30]   # pitch_median, loud_top: who is naturally high/loud still matters a little


def pfeat(Z, Araw):
    return np.hstack([np.nan_to_num(Z, nan=0.0), fill(Araw)[:, RAW_KEEP]])


Ztr, Rtr, yp_tr = personal_calm(tr, 8, RNG)
Xp_tr = pfeat(Ztr, Rtr)
Zva, Rva, yp_va = personal_calm(va, 3, np.random.default_rng(11))
sc_p, clf_p, sel_p, va_p = fit_select(Xp_tr, yp_tr, pfeat(Zva, Rva), yp_va, "personal")
Zca, Rca, yp_ca = personal_calm(ca, 3, np.random.default_rng(12))
T_p = fit_temperature(logits(clf_p, sc_p, pfeat(Zca, Rca)), yp_ca)

# threshold chosen on validation actors in the realistic streaming condition (below)


def stream_probs(mask, repeats):
    """Probabilities exactly as live: a mostly calm warm-up (not scored), then the person's other
    utterances in random order; the usual-voice baseline keeps growing with everything they say.
    General head for a person's first utterances, personal after."""
    idx = np.flatnonzero(mask)
    P, Y, PERS = [], [], []
    for _ in range(repeats):
        for a in np.unique(actor[mask]):
            ai0 = idx[actor[idx] == a]
            warm = RNG.permutation(calm_baseline(ai0, RNG))
            ai = np.concatenate([warm, RNG.permutation(np.setdiff1d(ai0, warm))])
            for j, i in enumerate(ai):
                if j < len(warm):
                    continue
                if j >= MIN_UTTERANCES:
                    m, s = stats(X[ai[:j]])
                    z = personal(X[i], m, s)[None, :]
                    P.append(softmax(logits(clf_p, sc_p, pfeat(z, X[i][None, :])), T_p)[0]); PERS.append(True)
                else:
                    P.append(softmax(logits(clf_g, sc_g, fill(X[i][None, :])), T_g)[0]); PERS.append(False)
                Y.append(y[i])
    return np.array(P), np.array(Y), np.array(PERS)


Pv, Yv, PERSv = stream_probs(va, 5)
thr_p = pick_threshold(Pv[PERSv], Yv[PERSv])
Zte, Rte, yp_te = personal_calm(te, 3, np.random.default_rng(13))
p_te_p_ideal = softmax(logits(clf_p, sc_p, pfeat(Zte, Rte)), T_p)
Pt, Yt, PERSt = stream_probs(te, 10)
report["personal"] = {"selected": sel_p, "validation_accuracy": round(va_p, 4), "temperature": T_p, "threshold": thr_p,
                      "test_calm_baseline": summary(p_te_p_ideal, yp_te, thr_p),
                      "test_live_stream_after_4": summary(Pt[PERSt], Yt[PERSt], thr_p)}
live_thr = np.where(PERSt, thr_p, thr_g)
pred = Pt.argmax(1); conf = Pt.max(1); accd = conf >= live_thr
report["live_overall"] = {"accuracy": round(float((pred == Yt).mean()), 4),
                          "accepted_accuracy": round(float((pred[accd] == Yt[accd]).mean()), 4),
                          "coverage": round(float(accd.mean()), 4),
                          "note": "10 shuffled orders per test actor, each after a mostly calm warm-up (not scored)"}
for k in ("test_calm_baseline", "test_live_stream_after_4"):
    print("personal", k, {kk: vv for kk, vv in report["personal"][k].items() if kk != "confusion"})
print("live overall", report["live_overall"])

# arousal (calm ↔ intense) as a by-product: does the weighted score separate the groups?
aw = np.array([AROUSAL[l] for l in LABELS])
score = Pt @ aw
hi = np.isin(Yt, [LABELS.index(l) for l in ("angry", "happy", "fear")])
lo = np.isin(Yt, [LABELS.index(l) for l in ("sad", "neutral")])
from sklearn.metrics import roc_auc_score
report["arousal_auc_high_vs_low"] = round(float(roc_auc_score(np.r_[np.ones(hi.sum()), np.zeros(lo.sum())], np.r_[score[hi], score[lo]])), 4)
print("arousal AUC (angry/happy/fear vs sad/neutral):", report["arousal_auc_high_vs_low"])

model = {
    "version": 2,
    "source": "Trained by Sanket on CREMA-D (ODbL-1.0 / DbCL-1.0) with Audial AI's speaker splits (MIT).",
    "labels": LABELS, "arousal": AROUSAL, "minUtterances": MIN_UTTERANCES,
    "general": export(sc_g, clf_g, T_g, thr_g),
    "personal": export(sc_p, clf_p, T_p, thr_p, {"floors": np.round(FLOORS, 6).tolist(), "rawKeep": RAW_KEEP}),
    "evaluation": {"general_test_accuracy": report["general"]["test"]["accuracy"],
                   "live_accuracy": report["live_overall"]["accuracy"],
                   "live_accepted_accuracy": report["live_overall"]["accepted_accuracy"],
                   "live_coverage": report["live_overall"]["coverage"],
                   "test_actors": 10, "test_clips": int(te.sum())},
}
json.dump(model, open(sys.argv[2], "w"), separators=(",", ":"))
json.dump(report, open(sys.argv[3], "w"), indent=1)
print("wrote", sys.argv[2])
