/*
 * Sanket tone estimates
 * ---------------------
 * Turns a stretch of one person's speech (≈1–3 s of analysed frames from the voice engine)
 * into 48 acoustic features, compares them with that person's own usual voice, and runs a
 * small classifier trained on CREMA-D with the speaker splits used by Audial AI.
 *
 * The same feature code runs in training (Node, over the CREMA-D recordings) and live in the
 * browser, so the model sees exactly the numbers the app computes.
 *
 * Output is an ESTIMATE of an acted-emotion category with a confidence. Sanket only names a
 * category when it is a personal estimate (it has heard this person at least 4 times) and the
 * confidence is at least 80% — on acted test speakers those are right ~97% of the time, and on
 * natural calm reading they almost never appear (lower bars labelled calm readers "angry").
 * Otherwise the answer is "uncertain". The relative tone (more intense than usual / softer,
 * sad-sounding) is the more robust signal and is what the live cues use.
 * Shown in the session review by default, not live.
 */
(function (root) {
  'use strict';

  const FRAME_SEC = 0.016;

  const FEATURE_NAMES = [].concat(
    Array.from({ length: 12 }, (_, i) => `mfcc${i + 1}_mean`),
    Array.from({ length: 12 }, (_, i) => `mfcc${i + 1}_std`),
    Array.from({ length: 6 }, (_, i) => `mfcc${i + 1}_delta`),
    ['loud_top', 'loud_std', 'loud_range', 'loud_slope'],
    ['pitch_median', 'pitch_iqr', 'pitch_range', 'pitch_jitter', 'pitch_slope'],
    ['voiced_frac', 'onset_rate'],
    ['centroid_mean', 'centroid_std', 'tilt_mean', 'tilt_std', 'flux_mean', 'zcr_mean', 'aper_mean'],
  );

  function quantile(sorted, q) {
    if (!sorted.length) return NaN;
    const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  }
  function mean(a) { let s = 0; for (const v of a) s += v; return a.length ? s / a.length : NaN; }
  function std(a) { if (a.length < 2) return 0; const m = mean(a); let s = 0; for (const v of a) s += (v - m) * (v - m); return Math.sqrt(s / (a.length - 1)); }
  function slope(ts, ys) {
    if (ys.length < 4) return 0;
    const mt = mean(ts), my = mean(ys);
    let num = 0, den = 0;
    for (let i = 0; i < ys.length; i++) { num += (ts[i] - mt) * (ys[i] - my); den += (ts[i] - mt) * (ts[i] - mt); }
    return den > 0 ? num / den : 0;
  }

  // frames: speech frames from the voice engine ({t, db, f0, mfcc, aper, centroid, alpha, flux, zcr, onset})
  // Returns a plain array of FEATURE_NAMES.length numbers (NaN where a value can't be measured), or null.
  function features(frames) {
    if (!frames || frames.length < 25) return null;
    const n = frames.length;
    const out = [];
    for (let k = 0; k < 12; k++) out.push(mean(frames.map((f) => f.mfcc[k])));
    for (let k = 0; k < 12; k++) out.push(std(frames.map((f) => f.mfcc[k])));
    for (let k = 0; k < 6; k++) {
      const d = [];
      for (let i = 1; i < n; i++) d.push(Math.abs(frames[i].mfcc[k] - frames[i - 1].mfcc[k]));
      out.push(mean(d));
    }
    const dbs = frames.map((f) => f.db);
    const sortedDb = dbs.slice().sort((a, b) => a - b);
    const top = sortedDb.slice(Math.floor(n / 2));
    out.push(mean(top), std(dbs), quantile(sortedDb, 0.9) - quantile(sortedDb, 0.1), slope(frames.map((f) => f.t), dbs));

    const voiced = frames.filter((f) => f.f0 > 0);
    const st = voiced.map((f) => 12 * Math.log2(f.f0 / 100));
    if (st.length >= 8) {
      const s = st.slice().sort((a, b) => a - b);
      const jit = [];
      for (let i = 1; i < voiced.length; i++) if (voiced[i].t - voiced[i - 1].t < 0.04) jit.push(Math.abs(st[i] - st[i - 1]));
      out.push(quantile(s, 0.5), quantile(s, 0.75) - quantile(s, 0.25), quantile(s, 0.9) - quantile(s, 0.1),
        jit.length ? mean(jit) : NaN, slope(voiced.map((f) => f.t), st));
    } else out.push(NaN, NaN, NaN, NaN, NaN);

    out.push(voiced.length / n, frames.filter((f) => f.onset).length / (n * FRAME_SEC));
    const cents = frames.map((f) => Math.log(Math.max(f.centroid, 50)));
    const tilts = frames.map((f) => f.alpha);
    out.push(mean(cents), std(cents), mean(tilts), std(tilts), mean(frames.map((f) => f.flux)), mean(frames.map((f) => f.zcr)),
      voiced.length ? mean(voiced.map((f) => f.aper)) : NaN);
    return out;
  }

  // Each person's usual voice: running mean / spread of their utterance features.
  class SpeakerBaseline {
    constructor() { this.n = 0; this.m = null; this.s = null; this.cnt = null; }
    add(x) {
      if (!this.m) { this.m = x.map(() => 0); this.s = x.map(() => 0); this.cnt = x.map(() => 0); }
      this.n++;
      for (let i = 0; i < x.length; i++) {
        if (!Number.isFinite(x[i])) continue;
        const c = ++this.cnt[i];
        const d = x[i] - this.m[i];
        this.m[i] += d / c;
        this.s[i] += d * (x[i] - this.m[i]);
      }
    }
    // z-score against this person's usual voice; floor keeps one quiet session from exploding
    normalise(x, floors) {
      return x.map((v, i) => {
        if (!Number.isFinite(v) || !this.cnt || this.cnt[i] < 2) return NaN;
        const sd = Math.max(Math.sqrt(this.s[i] / (this.cnt[i] - 1)), floors ? floors[i] : 1e-3);
        return (v - this.m[i]) / sd;
      });
    }
  }

  function runNet(head, x) {
    // standardise, fill gaps with the training mean (0 after scaling), then the layers
    let h = x.map((v, i) => (Number.isFinite(v) ? (v - head.mean[i]) / head.scale[i] : 0));
    for (const L of head.layers) {
      const o = new Array(L.b.length);
      for (let j = 0; j < L.b.length; j++) {
        let s = L.b[j];
        const w = L.W[j];
        for (let i = 0; i < h.length; i++) s += w[i] * h[i];
        o[j] = L.act === 'relu' ? Math.max(0, s) : s;
      }
      h = o;
    }
    const T = head.temperature || 1;
    const z = h.map((v) => v / T);
    const mx = Math.max(...z);
    const e = z.map((v) => Math.exp(v - mx));
    const sum = e.reduce((a, b) => a + b, 0);
    return e.map((v) => v / sum);
  }

  const SHOW = {
    minConfidence: 0.8,      // see header; chosen on held-out acted speakers + natural calm reading
    requirePersonal: true,   // first-meeting estimates judge absolute loudness and microphone, and don't transfer
  };

  // Relative tone of an estimate (what the live cues use): thresholds as in the engine tuning.
  function relativeTone(est, shift, T) {
    T = T || { rise: 0.40, sad: 0.50 };
    if (!est || !est.personal) return 'learning';
    if (est.probs.sad >= T.sad) return 'softer';
    if (shift != null && shift >= T.rise) return 'intense';
    return 'usual';
  }

  // One tone estimator per session.
  class Estimator {
    constructor(model, opts) {
      this.model = model;
      this.show = Object.assign({}, SHOW, opts || {});
      this.baselines = new Map();
    }
    get labels() { return this.model.labels; }
    reset() { this.baselines.clear(); }
    merge(keepId, dropId) {
      const a = this.baselines.get(keepId), b = this.baselines.get(dropId);
      if (b && !a) this.baselines.set(keepId, b);
      this.baselines.delete(dropId);
    }

    // Estimate one utterance from `frames` spoken by `speakerId`.
    estimate(speakerId, frames) {
      const x = features(frames);
      if (!x) return null;
      return this.estimateFeatures(speakerId, x, frames.length * FRAME_SEC);
    }

    // Same, from an already-computed feature vector (used by tests and training checks).
    estimateFeatures(speakerId, x, seconds) {
      const M = this.model;
      let base = this.baselines.get(speakerId);
      if (!base) { base = new SpeakerBaseline(); this.baselines.set(speakerId, base); }
      const personal = base.n >= M.minUtterances;
      let probs, head;
      if (personal) {
        head = M.personal;
        // exactly as in training: unmeasurable z-scores become 0 (= this person's usual), then the
        // raw values listed in rawKeep, in that order (gaps there are filled inside runNet)
        const z = base.normalise(x, M.personal.floors).map((v) => (Number.isFinite(v) ? v : 0));
        probs = runNet(head, z.concat(M.personal.rawKeep.map((i) => x[i])));
      } else {
        head = M.general;
        probs = runNet(head, x);
      }
      base.add(x);
      let best = 0;
      for (let i = 1; i < probs.length; i++) if (probs[i] > probs[best]) best = i;
      const confidence = probs[best];
      const accepted = confidence >= Math.max(head.threshold, this.show.minConfidence) &&
        (personal || !this.show.requirePersonal);
      const arousal = probs.reduce((s, p, i) => s + p * (M.arousal[M.labels[i]] || 0), 0);
      return {
        label: accepted ? M.labels[best] : 'uncertain',
        guess: M.labels[best],
        confidence,
        accepted,
        personal,
        arousal,
        probs: Object.fromEntries(M.labels.map((l, i) => [l, probs[i]])),
        seconds: seconds || 0,
      };
    }
  }

  const api = { FEATURE_NAMES, features, SpeakerBaseline, Estimator, runNet, relativeTone, SHOW };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SanketTone = api;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
