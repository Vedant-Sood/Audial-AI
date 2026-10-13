"""WER and frame-grid overlap-aware DER with global optimal speaker mapping."""
import re
import numpy as np
from scipy.optimize import linear_sum_assignment


def wer(reference, hypothesis):
    a = re.findall(r"\w+", reference.lower())
    b = re.findall(r"\w+", hypothesis.lower())
    previous = list(range(len(b) + 1))
    for i, actual in enumerate(a, 1):
        current = [i]
        for j, predicted in enumerate(b, 1):
            current.append(min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (actual != predicted)))
        previous = current
    return {"wer": previous[-1] / max(1, len(a)), "edits": previous[-1], "reference_words": len(a)}


def diarization_metrics(reference, hypothesis, duration, step=0.01):
    """Turns: {start,end,speaker}. 10-ms approximate DER; no collar, overlap scored."""
    times = np.arange(step / 2, duration, step)
    rlabels = sorted({r["speaker"] for r in reference})
    hlabels = sorted({h["speaker"] for h in hypothesis})
    def mask(turns, labels):
        values = np.zeros((len(times), len(labels)), bool)
        for t in turns:
            values[(times >= t["start"]) & (times < t["end"]), labels.index(t["speaker"])] = True
        return values
    r, h = mask(reference, rlabels), mask(hypothesis, hlabels)
    cost = -(r.astype(int).T @ h.astype(int))
    ri, hi = linear_sum_assignment(cost) if len(rlabels) and len(hlabels) else ([], [])
    matched = np.zeros(len(times), int)
    mapping = {}
    for a, b in zip(ri, hi):
        matched += r[:, a] & h[:, b]
        mapping[hlabels[b]] = rlabels[a]
    rn, hn = r.sum(1), h.sum(1)
    miss = np.maximum(rn - hn, 0).sum()
    false = np.maximum(hn - rn, 0).sum()
    confusion = (np.minimum(rn, hn) - matched).sum()
    denominator = max(1, rn.sum())
    ro, ho = rn > 1, hn > 1
    tp, fp, fn = (ro & ho).sum(), (~ro & ho).sum(), (ro & ~ho).sum()
    return {"der": float((miss + false + confusion) / denominator), "speaker_confusion": float(confusion / denominator),
        "miss_rate": float(miss / denominator), "false_alarm_rate": float(false / denominator),
        "overlap_precision": float(tp / max(1, tp + fp)), "overlap_recall": float(tp / max(1, tp + fn)),
        "overlap_f1": float(2 * tp / max(1, 2 * tp + fp + fn)), "speaker_mapping": mapping,
        "method": "Frame-grid DER; step=10 ms; no collar; overlap included", "step_seconds": step}
