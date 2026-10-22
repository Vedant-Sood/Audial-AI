/*
 * Sanket voice engine
 * --------------------
 * Pure JavaScript, no DOM. Runs in the browser and in Node (for tests).
 *
 * Input:  mono audio samples (any sample rate; 16 kHz is native).
 * Output: events —
 *   speech-start / speech-end   voice activity
 *   speaker                     the current voice changed (new or returning speaker)
 *   cue                         a tone cue: drop | rise | hesitation | silence
 *   speakers                    the speaker list changed (new, renamed, merged)
 *   level                       loudness meter (every 2nd frame)
 *
 * Everything is computed on the device. Nothing here records or stores audio;
 * only short running averages of voice features are kept in memory.
 */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------- constants
  const SR = 16000;          // internal sample rate
  const FRAME = 512;         // 32 ms analysis window
  const HOP = 256;           // 16 ms step
  const FRAME_SEC = HOP / SR;
  const N_MEL = 24;
  const N_MFCC = 12;         // c1..c12 (c0 = loudness, excluded from voice identity)
  const F0_MIN = 70, F0_MAX = 400;

  // ---------------------------------------------------------------- DSP helpers
  function hamming(n) {
    const w = new Float32Array(n);
    for (let i = 0; i < n; i++) w[i] = 0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (n - 1));
    return w;
  }

  // In-place iterative radix-2 FFT on (re, im).
  function fft(re, im) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        let t = re[i]; re[i] = re[j]; re[j] = t;
        t = im[i]; im[i] = im[j]; im[j] = t;
      }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = (-2 * Math.PI) / len;
      const wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        const half = len >> 1;
        for (let k = 0; k < half; k++) {
          const a = i + k, b = a + half;
          const xr = re[b] * cr - im[b] * ci;
          const xi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - xr; im[b] = im[a] - xi;
          re[a] += xr; im[a] += xi;
          const ncr = cr * wr - ci * wi;
          ci = cr * wi + ci * wr; cr = ncr;
        }
      }
    }
  }

  function hzToMel(f) { return 2595 * Math.log10(1 + f / 700); }
  function melToHz(m) { return 700 * (Math.pow(10, m / 2595) - 1); }

  function melFilterbank(nFft, sr, nMel, fLo, fHi) {
    const bins = nFft / 2 + 1;
    const mLo = hzToMel(fLo), mHi = hzToMel(fHi);
    const pts = [];
    for (let i = 0; i < nMel + 2; i++) pts.push(melToHz(mLo + ((mHi - mLo) * i) / (nMel + 1)));
    const binOf = (f) => (f * nFft) / sr;
    const filters = [];
    for (let m = 1; m <= nMel; m++) {
      const l = binOf(pts[m - 1]), c = binOf(pts[m]), r = binOf(pts[m + 1]);
      const w = new Float32Array(bins);
      for (let k = 0; k < bins; k++) {
        if (k > l && k <= c) w[k] = (k - l) / (c - l);
        else if (k > c && k < r) w[k] = (r - k) / (r - c);
      }
      filters.push(w);
    }
    return filters;
  }

  function dctMatrix(nIn, nOut) {
    // Orthonormal DCT-II rows 1..nOut (row 0 skipped: overall loudness)
    const rows = [];
    for (let k = 1; k <= nOut; k++) {
      const r = new Float32Array(nIn);
      for (let n = 0; n < nIn; n++) r[n] = Math.sqrt(2 / nIn) * Math.cos((Math.PI * k * (n + 0.5)) / nIn);
      rows.push(r);
    }
    return rows;
  }

  // YIN pitch estimate on one frame. Returns { f0, aperiodicity } (f0 = 0 when unvoiced).
  function yin(frame, sr, threshold) {
    const tauMin = Math.floor(sr / F0_MAX);
    const tauMax = Math.floor(sr / F0_MIN);
    const W = frame.length - tauMax;
    const d = new Float32Array(tauMax + 1);
    for (let tau = 1; tau <= tauMax; tau++) {
      let s = 0;
      for (let j = 0; j < W; j++) {
        const diff = frame[j] - frame[j + tau];
        s += diff * diff;
      }
      d[tau] = s;
    }
    // cumulative mean normalised difference
    const cmnd = new Float32Array(tauMax + 1);
    cmnd[0] = 1;
    let run = 0;
    for (let tau = 1; tau <= tauMax; tau++) {
      run += d[tau];
      cmnd[tau] = run > 0 ? (d[tau] * tau) / run : 1;
    }
    let best = -1;
    for (let tau = tauMin; tau <= tauMax; tau++) {
      if (cmnd[tau] < threshold) {
        while (tau + 1 <= tauMax && cmnd[tau + 1] < cmnd[tau]) tau++;
        best = tau;
        break;
      }
    }
    if (best < 0) {
      // no dip below threshold: report the global minimum as aperiodicity only
      let minV = 1;
      for (let tau = tauMin; tau <= tauMax; tau++) if (cmnd[tau] < minV) minV = cmnd[tau];
      return { f0: 0, aperiodicity: minV };
    }
    // parabolic interpolation
    let t = best;
    if (best > tauMin && best < tauMax) {
      const a = cmnd[best - 1], b = cmnd[best], c = cmnd[best + 1];
      const den = a - 2 * b + c;
      if (den !== 0) t = best + (0.5 * (a - c)) / den;
    }
    return { f0: sr / t, aperiodicity: cmnd[best] };
  }

  function median(arr) {
    const a = arr.slice().sort((x, y) => x - y);
    const n = a.length;
    if (!n) return 0;
    return n % 2 ? a[(n - 1) >> 1] : 0.5 * (a[n / 2 - 1] + a[n / 2]);
  }

  // Frame analyser: loudness, pitch, MFCC
  class FrameAnalyser {
    constructor() {
      this.win = hamming(FRAME);
      this.mel = melFilterbank(FRAME, SR, N_MEL, 80, 7600);
      this.dct = dctMatrix(N_MEL, N_MFCC);
      this.re = new Float32Array(FRAME);
      this.im = new Float32Array(FRAME);
      this.logMel = new Float32Array(N_MEL);
      this.prevMag = new Float32Array(FRAME / 2 + 1);
      // band edges (bins) for spectral tilt: 50 Hz–1 kHz vs 1–5 kHz
      const bin = (hz) => Math.round((hz * FRAME) / SR);
      this.b50 = bin(50); this.b1k = bin(1000); this.b5k = bin(5000);
    }
    analyse(frame) {
      // loudness (dBFS)
      let e = 0;
      for (let i = 0; i < FRAME; i++) e += frame[i] * frame[i];
      const db = 10 * Math.log10(e / FRAME + 1e-12);

      // spectrum with pre-emphasis + window
      const re = this.re, im = this.im;
      let prev = 0;
      for (let i = 0; i < FRAME; i++) {
        const x = frame[i] - 0.97 * prev;
        prev = frame[i];
        re[i] = x * this.win[i];
        im[i] = 0;
      }
      fft(re, im);
      const bins = FRAME / 2 + 1;
      // voice-quality and spectral shape (used by tone estimates)
      let pSum = 0, pW = 0, lo = 0, hi = 0, flux = 0, magSum = 0;
      for (let k = 1; k < bins; k++) {
        const pw = re[k] * re[k] + im[k] * im[k];
        const mag = Math.sqrt(pw);
        pSum += pw; pW += pw * (k * SR / FRAME);
        if (k >= this.b50 && k < this.b1k) lo += pw; else if (k >= this.b1k && k < this.b5k) hi += pw;
        const d = mag - this.prevMag[k];
        flux += d * d; magSum += mag * mag;
        this.prevMag[k] = mag;
      }
      const centroid = pSum > 0 ? pW / pSum : 0;
      const alpha = 10 * Math.log10((hi + 1e-12) / (lo + 1e-12));
      const fluxN = magSum > 0 ? flux / magSum : 0;
      let zc = 0;
      for (let i = 1; i < FRAME; i++) if ((frame[i] >= 0) !== (frame[i - 1] >= 0)) zc++;
      const zcr = zc / FRAME;
      for (let m = 0; m < N_MEL; m++) {
        const w = this.mel[m];
        let s = 0;
        for (let k = 0; k < bins; k++) if (w[k]) s += w[k] * (re[k] * re[k] + im[k] * im[k]);
        this.logMel[m] = Math.log(s + 1e-10);
      }
      const mfcc = new Float32Array(N_MFCC);
      for (let k = 0; k < N_MFCC; k++) {
        const row = this.dct[k];
        let s = 0;
        for (let m = 0; m < N_MEL; m++) s += row[m] * this.logMel[m];
        mfcc[k] = s;
      }
      // pitch only when there is enough energy to matter
      let f0 = 0, aper = 1;
      if (db > -65) {
        const p = yin(frame, SR, 0.15);
        f0 = p.f0; aper = p.aperiodicity;
        if (aper > 0.25) f0 = 0;
      }
      return { db, f0, mfcc, aper, centroid, alpha, flux: fluxN, zcr };
    }
  }

  // Streaming resampler to 16 kHz (box filter + linear interpolation).
  class Resampler {
    constructor(inRate) {
      this.ratio = inRate / SR;
      this.pos = 0;           // fractional read position in the filtered stream
      this.hist = [];         // filtered samples not yet consumed
      this.box = Math.max(1, Math.round(this.ratio));
      this.boxBuf = [];
      this.boxSum = 0;
    }
    push(input) {
      if (this.ratio === 1) return input;
      for (let i = 0; i < input.length; i++) {
        this.boxBuf.push(input[i]); this.boxSum += input[i];
        if (this.boxBuf.length > this.box) this.boxSum -= this.boxBuf.shift();
        this.hist.push(this.boxSum / this.boxBuf.length);
      }
      const out = [];
      while (this.pos + 1 < this.hist.length) {
        const i = Math.floor(this.pos), f = this.pos - i;
        out.push(this.hist[i] * (1 - f) + this.hist[i + 1] * f);
        this.pos += this.ratio;
      }
      const drop = Math.floor(this.pos);
      if (drop > 0) { this.hist.splice(0, drop); this.pos -= drop; }
      return Float32Array.from(out);
    }
  }

  // Sliding minimum over a time window (monotonic deque).
  class SlidingMin {
    constructor(len) { this.len = len; this.q = []; this.i = 0; }
    push(v) {
      const q = this.q;
      while (q.length && q[q.length - 1].v >= v) q.pop();
      q.push({ v, i: this.i });
      while (q[0].i <= this.i - this.len) q.shift();
      this.i++;
      return q[0].v;
    }
  }

  // ---------------------------------------------------------------- defaults
  const DEFAULTS = {
    sensitivity: 1.0,        // >1 = splits voices more readily, <1 = merges more
    maxSpeakers: 6,
    singleSpeaker: false,    // lecture mode: everything is one speaker
    silenceSec: 4,
    cues: { drop: true, rise: true, hesitation: true, silence: true },
    cueCooldownSec: 8,       // same cue type
    cueGapSec: 3,            // any two cues
  };

  // Tuned on recorded speech (see tests/calibrate*.mjs and tests/engine.test.mjs)
  const TUNING = {
    vadOnDb: 10,             // above noise floor
    vadAbsMin: -62,          // dBFS, never treat quieter as speech
    vadOnFrames: 3,
    vadHangFrames: 10,       // 160 ms bridge for short dips
    turnGapSec: 0.25,        // a pause this long starts a new voice segment
    idDims: 8,               // voice identity uses c1..c8 (more stable than all 12)
    earlyFrames: 40,         // ~0.64 s: decide early only when the answer is clear
    finalFrames: 90,         // ~1.4 s: normal decision point
    minShortFrames: 25,      // a short utterance (~0.4 s) still gets a decision
    recheckEvery: 32,        // ~0.5 s
    recheckWindow: 90,       // ~1.4 s
    threshold: 0.42,         // voice distance that means "different person" (1.4 s window)
    earlySame: 0.3,          // early decision: clearly the same voice
    earlyNew: 0.8,           // early decision: clearly a new voice
    stayBonus: 1.1,          // prefer the current speaker slightly…
    returnRatio: 0.85,       // …unless a known voice matches clearly better (a person coming back in)
    switchFactor: 1.35,      // mid-speech switch needs a clearly different voice
    pitchFarSt: 7,           // pitch gap that backs up a borderline voice-shape distance
    pitchVetoSt: 9,          // a very large pitch gap (e.g. 100 vs 170 Hz) needs only weak voice-shape support
    pitchCloseSt: 2.5,       // pitch this close supports "same person"
    pitchSlack: 1.25,        // ...and allows a voice-shape distance this much over the threshold
    baselineMinFrames: 250,  // ~4 s of a speaker's voice before tone cues
    cueWindow: 94,           // ~1.5 s
    rateWindow: 188,         // ~3 s
    confirmEvals: 3,         // condition must hold ~0.75 s (ignores sentence-end trail-offs)
    dropDb: -6, dropDbWithPitch: -3.5, dropSt: -1.5,
    dropDbStrong: -10,       // with the tone model in charge, only a much quieter voice still counts by loudness alone
    riseDb: 6, riseDbWithPitch: 3.5, riseSt: 2,
    hesitationGaps: 5, hesitationWindowSec: 8, gapMin: 0.15, gapMax: 1.2,
    // tone estimates (training/train_tone.py) and model-backed cues (training/eval_cues.mjs)
    tonePauseSec: 0.5,       // an utterance ends at a pause this long…
    toneMaxFrames: 200,      // …or after ~3.2 s of speech (CREMA-D sentences hold 1.6–3.2 s)
    toneMinFrames: 40,       // shorter stretches are carried into the next utterance
    toneHistory: 8,          // a person's recent intensity = mean of their last 8 estimates
    toneMinHistory: 4,
    toneRiseShift: 0.40,     // intensity this far above their recent usual → "voice rose"
    toneSadProb: 0.50,       // sadness probability (personal estimate) → "voice softened"
  };

  function toneLib() {
    if (root.SanketTone) return root.SanketTone;
    try { return typeof require === 'function' ? require('./tone.js') : null; } catch (e) { return null; }
  }

  // ---------------------------------------------------------------- engine
  class VoiceEngine {
    constructor(opts) {
      opts = opts || {};
      this.inRate = opts.sampleRate || SR;
      this.onEvent = opts.onEvent || function () {};
      this.onSpeechFrame = opts.onSpeechFrame || null;   // used to extract training features with this exact code
      this.settings = Object.assign({}, DEFAULTS, opts.settings || {});
      this.settings.cues = Object.assign({}, DEFAULTS.cues, (opts.settings || {}).cues || {});
      this.tuning = Object.assign({}, TUNING, opts.tuning || {});
      this.toneModel = opts.toneModel || null;
      this.reset();
    }

    reset() {
      this.resampler = new Resampler(this.inRate);
      this.analyser = new FrameAnalyser();
      this.buf = new Float32Array(FRAME * 4);
      this.bufLen = 0;
      this.frameNo = 0;
      this.t = 0;

      // voice activity
      this.noiseMin = new SlidingMin(Math.round(4 / FRAME_SEC));
      this.noise = -80;
      this.smoothDb = -100;
      this.speaking = false;
      this.aboveCount = 0;
      this.belowCount = 0;
      this.lastSpeechEnd = null;
      this.lastSpeechStart = null;
      this.everSpoke = false;
      this.silenceFired = false;

      // global feature statistics (for scaling voice distances)
      this.gN = 0;
      this.gMean = new Float64Array(N_MFCC);
      this.gM2 = new Float64Array(N_MFCC);

      // speakers
      this.speakers = [];      // {id, n, mean:Float64Array, pN, pMean, base:{...}}
      this.nextId = 1;
      this.current = null;     // speaker id
      this.seg = null;         // current voice segment {frames:[], assigned:bool, sinceCheck, strikes}
      this.lastChangeT = -1e9;

      // cues
      this.lastCueT = -1e9;
      this.lastCueByKind = {};
      this.gaps = [];          // {t, len}
      this.pendingCue = {};    // kind -> consecutive count
      this.cueTick = 0;
      this.unvoicedRun = 2;

      // tone estimates
      const lib = this.toneModel ? toneLib() : null;
      this.tone = lib ? new lib.Estimator(this.toneModel) : null;
      this.toneBuf = [];       // speech frames of the utterance in progress
      this.toneHist = new Map(); // speaker id -> recent intensity (arousal) values
    }

    // Load (or remove) the tone model. Takes effect immediately; per-person history restarts.
    setToneModel(model) {
      this.toneModel = model || null;
      const lib = this.toneModel ? toneLib() : null;
      this.tone = lib ? new lib.Estimator(this.toneModel) : null;
      this.toneBuf = [];
      this.toneHist = new Map();
    }

    // Estimate whatever speech is still buffered (call when a session stops).
    flushTone() {
      if (this.current != null) this._toneFlush(this.current, true);
      this.toneBuf = [];
    }

    configure(s) {
      if (!s) return;
      if (s.cues) this.settings.cues = Object.assign({}, this.settings.cues, s.cues);
      for (const k of Object.keys(s)) if (k !== 'cues') this.settings[k] = s[k];
      if (this.settings.singleSpeaker && this.speakers.length === 0) this._newSpeaker(this.t);
    }

    process(samples) {
      const x = this.resampler.push(samples);
      // append into buffer, analyse every HOP
      if (this.bufLen + x.length > this.buf.length) {
        const nb = new Float32Array(Math.max(this.buf.length * 2, this.bufLen + x.length));
        nb.set(this.buf.subarray(0, this.bufLen));
        this.buf = nb;
      }
      this.buf.set(x, this.bufLen);
      this.bufLen += x.length;
      let off = 0;
      while (this.bufLen - off >= FRAME) {
        this._frame(this.buf.subarray(off, off + FRAME));
        off += HOP;
      }
      if (off > 0) {
        this.buf.copyWithin(0, off, this.bufLen);
        this.bufLen -= off;
      }
    }

    // ------------------------------------------------------------ per frame
    _frame(frame) {
      const T = this.tuning;
      const t = (this.frameNo * HOP + FRAME / 2) / SR;
      this.t = t;
      this.frameNo++;
      const f = this.analyser.analyse(frame);
      f.t = t;
      if (f.f0 > 0) { f.onset = this.unvoicedRun >= 2; this.unvoicedRun = 0; } else this.unvoicedRun++;

      // smoothed loudness + noise floor
      this.smoothDb = this.smoothDb < -99 ? f.db : 0.6 * this.smoothDb + 0.4 * f.db;
      const floor = this.noiseMin.push(this.smoothDb);
      this.noise = this.noise < -79 ? floor : 0.95 * this.noise + 0.05 * floor;
      const on = this.smoothDb > Math.max(this.noise + T.vadOnDb, T.vadAbsMin);

      if (on) { this.aboveCount++; this.belowCount = 0; } else { this.belowCount++; this.aboveCount = 0; }

      if (!this.speaking && this.aboveCount >= T.vadOnFrames) {
        this.speaking = true;
        const startT = t - (T.vadOnFrames - 1) * FRAME_SEC;
        const gap = this.lastSpeechEnd == null ? null : startT - this.lastSpeechEnd;
        this.lastSpeechStart = startT;
        this.everSpoke = true;
        this.silenceFired = false;
        if (gap != null && gap >= T.gapMin && gap <= T.gapMax) {
          this.gaps.push({ t: startT, len: gap, speaker: this.current });
          this._checkHesitation(startT);
        }
        this.lastGap = gap;
        if (gap == null || gap >= T.turnGapSec || !this.seg) this._startSegment();
        this.onEvent({ type: 'speech-start', t: startT, gap });
      } else if (this.speaking && this.belowCount >= T.vadHangFrames) {
        this.speaking = false;
        this.lastSpeechEnd = t - (T.vadHangFrames - 1) * FRAME_SEC;
        this.onEvent({ type: 'speech-end', t: this.lastSpeechEnd });
      }

      if (this.speaking && on) this._speechFrame(f);

      // a short utterance followed by a pause still gets assigned to someone
      if (!this.speaking && this.seg && !this.seg.assigned && this.lastSpeechEnd != null &&
          t - this.lastSpeechEnd >= T.turnGapSec && !this.settings.singleSpeaker) {
        const n = this.seg.frames.length;
        const quickResume = this.lastGap != null && this.lastGap < 1.0 && this.current != null;
        if (n >= T.earlyFrames || (n >= T.minShortFrames && !quickResume)) this._assignSegment(this.seg, 'final');
        else {
          // too short to judge (or a burst right after a short pause): it stays with the current speaker
          this.seg.assigned = true;
        }
      }

      // an utterance ends at a pause: estimate its tone once the speaker is settled
      if (this.tone && !this.speaking && this.toneBuf.length && this.lastSpeechEnd != null &&
          t - this.lastSpeechEnd >= T.tonePauseSec && this.current != null && (!this.seg || this.seg.assigned)) {
        this._toneFlush(this.current, false);
      }

      // long silence cue
      if (!this.speaking && this.everSpoke && !this.silenceFired && this.lastSpeechEnd != null &&
          t - this.lastSpeechEnd >= this.settings.silenceSec) {
        this.silenceFired = true;
        this._cue('silence', t, { seconds: Math.round(t - this.lastSpeechEnd) });
      }

      if ((this.frameNo & 1) === 0) {
        this.onEvent({ type: 'level', t, db: f.db, noise: this.noise, speaking: this.speaking, f0: f.f0 });
      }
    }

    _startSegment() {
      this.seg = { frames: [], assigned: false, sinceCheck: 0, strikes: 0, start: this.t };
    }

    _speechFrame(f) {
      // global statistics for distance scaling
      this.gN++;
      for (let i = 0; i < N_MFCC; i++) {
        const d = f.mfcc[i] - this.gMean[i];
        this.gMean[i] += d / this.gN;
        this.gM2[i] += d * (f.mfcc[i] - this.gMean[i]);
      }
      if (this.onSpeechFrame) this.onSpeechFrame(f);
      if (!this.seg) this._startSegment();
      const seg = this.seg;
      seg.frames.push(f);
      if (seg.frames.length > 400) seg.frames.splice(0, seg.frames.length - 400);

      if (this.settings.singleSpeaker) {
        if (!this.speakers.length) this._newSpeaker(f.t);
        if (this.current == null) this._setCurrent(this.speakers[0].id, f.t, false);
        seg.assigned = true;
        this._learn(this._speaker(this.current), [f]);
      } else if (!seg.assigned) {
        const n = seg.frames.length;
        if (n >= this.tuning.finalFrames) this._assignSegment(seg, 'final');
        else if (n === this.tuning.earlyFrames) this._assignSegment(seg, 'early');
      } else {
        this._learn(this._speaker(this.current), [f]);
        seg.sinceCheck++;
        if (seg.sinceCheck >= this.tuning.recheckEvery) {
          seg.sinceCheck = 0;
          this._recheck(seg);
        }
      }

      // tone cues follow the current speaker, including the moments right after a short
      // pause while the engine is still confirming who is talking
      if (this.current != null && (seg.assigned || this.lastGap == null || this.lastGap < 1.0)) {
        this._trackBaseline(f);
        if (++this.cueTick % 16 === 0) this._evaluateCues(f.t);
      }

      if (this.tone) {
        this.toneBuf.push(f);
        if (this.toneBuf.length >= this.tuning.toneMaxFrames && this.current != null && seg.assigned) {
          this._toneFlush(this.current, true);
        }
      }
    }

    // ------------------------------------------------------------ voice identity
    _scale() {
      const s = new Float64Array(N_MFCC);
      for (let i = 0; i < N_MFCC; i++) {
        const v = this.gN > 50 ? this.gM2[i] / (this.gN - 1) : 25;
        s[i] = Math.sqrt(Math.max(v, 1e-3));
      }
      return s;
    }

    _profile(frames) {
      const m = new Float64Array(N_MFCC);
      const sts = [];
      for (const f of frames) {
        for (let i = 0; i < N_MFCC; i++) m[i] += f.mfcc[i];
        if (f.f0 > 0) sts.push(12 * Math.log2(f.f0 / 100));
      }
      for (let i = 0; i < N_MFCC; i++) m[i] /= frames.length || 1;
      return { mean: m, pMean: sts.length ? median(sts) : null, pN: sts.length, n: frames.length };
    }

    _distance(p, spk) {
      const nd = this.tuning.idDims;
      const sc = this._scale();
      let s = 0;
      for (let i = 0; i < nd; i++) {
        const d = (p.mean[i] - spk.mean[i]) / sc[i];
        s += d * d;
      }
      return Math.sqrt(s / nd);
    }

    // Pitch alone varies a lot within one person (questions, emphasis), so it only decides
    // when the gap is very large, or backs up a voice-shape distance that is already borderline.
    _pitchFar(p, spk, d) {
      if (p.pMean == null || p.pN < 15 || spk.pN < 30) return false;
      const gap = Math.abs(p.pMean - spk.pMean);
      if (d == null) d = this._distance(p, spk);
      const th = this._threshold();
      if (gap >= this.tuning.pitchVetoSt && d > th * 0.7) return true;
      return gap >= this.tuning.pitchFarSt && d > th * 0.9;
    }

    // A close pitch is extra evidence for "same person" when the voice shape is borderline.
    _pitchClose(p, spk) {
      return p.pMean != null && p.pN >= 15 && spk.pN >= 30 &&
        Math.abs(p.pMean - spk.pMean) <= this.tuning.pitchCloseSt;
    }

    _accepts(p, spk, d, limit) {
      return d <= limit || (this._pitchClose(p, spk) && d <= limit * this.tuning.pitchSlack);
    }

    _threshold() { return this.tuning.threshold / Math.max(0.3, this.settings.sensitivity); }

    _best(p, excludeId) {
      let best = null, bestD = Infinity;
      for (const s of this.speakers) {
        if (s.id === excludeId || s.n < 20) continue;
        const d = this._distance(p, s);
        if (this._pitchFar(p, s, d)) continue;
        if (d < bestD) { bestD = d; best = s; }
      }
      return { spk: best, d: bestD };
    }

    // stage: 'early' (decide only if clear), 'final' (always decide)
    _assignSegment(seg, stage) {
      const T = this.tuning;
      const th = this._threshold();
      const scale = th / T.threshold;
      const frames = seg.frames.slice(-T.finalFrames);
      const p = this._profile(frames);
      const cur = this.current != null ? this._speaker(this.current) : null;
      const room = this.speakers.length < this.settings.maxSpeakers;
      let target = null;

      if (!this.speakers.length) {
        target = this._newSpeaker(frames[0].t);
      } else if (stage === 'early') {
        const dC = cur ? this._distance(p, cur) : Infinity;
        const curOk = cur && cur.n >= 20 && !this._pitchFar(p, cur, dC);
        const dCur = curOk ? dC : Infinity;
        const b = this._best(p);
        if (curOk && dCur <= T.earlySame * scale * T.stayBonus) target = cur;
        else if (b.spk && b.d <= T.earlySame * scale) target = b.spk;
        else if (room && (!b.spk || b.d >= T.earlyNew * scale) && (!curOk || dCur >= T.earlyNew * scale)) {
          target = this._newSpeaker(frames[0].t);
        } else return; // not sure yet: wait for more speech
      } else {
        const dCur = cur ? this._distance(p, cur) : Infinity;
        const curOk = cur && cur.n >= 20 && !this._pitchFar(p, cur, dCur);
        // the stay bonus breaks near-ties only: a returning voice that matches clearly better wins
        const other = curOk ? this._best(p, cur.id) : null;
        const clearlyOther = other && other.spk && other.d <= th && other.d < dCur * T.returnRatio;
        if (curOk && !clearlyOther && this._accepts(p, cur, dCur, th * T.stayBonus)) target = cur;
        else {
          const b = this._best(p);
          if (b.spk && this._accepts(p, b.spk, b.d, th)) target = b.spk;
          else if (room) target = this._newSpeaker(frames[0].t);
          else target = b.spk || cur;
        }
      }
      if (!target) return;
      seg.assigned = true;
      this._learn(target, frames);
      if (target.id !== this.current) this._setCurrent(target.id, seg.start, target._fresh);
      target._fresh = false;
    }

    _recheck(seg) {
      const T = this.tuning;
      const cur = this._speaker(this.current);
      if (!cur) return;
      const win = seg.frames.slice(-T.recheckWindow);
      if (win.length < T.recheckWindow) return;
      const p = this._profile(win);
      const th = this._threshold();
      const dCur = this._distance(p, cur);
      if (dCur <= th * T.switchFactor && !this._pitchFar(p, cur)) { seg.strikes = 0; return; }
      seg.strikes++;
      if (seg.strikes < 2) return;
      seg.strikes = 0;
      const b = this._best(p, cur.id);
      let target;
      if (b.spk && this._accepts(p, b.spk, b.d, th)) target = b.spk;
      else if (this.speakers.length < this.settings.maxSpeakers) target = this._newSpeaker(win[0].t);
      else return;
      // the window probably straddles the change; use its middle as the change time
      const changeT = win[Math.floor(win.length / 2)].t;
      this._learn(target, win.slice(Math.floor(win.length / 2)));
      this._setCurrent(target.id, changeT, target._fresh);
      target._fresh = false;
    }

    _newSpeaker(t) {
      const s = {
        id: this.nextId++, n: 0, mean: new Float64Array(N_MFCC), pN: 0, pMean: 0, pList: [],
        base: { n: 0, db: 0, st: 0, rate: 0, rateN: 0 }, firstT: t, _fresh: true,
      };
      this.speakers.push(s);
      this.onEvent({ type: 'speakers', speakers: this.listSpeakers() });
      return s;
    }

    _speaker(id) { return this.speakers.find((s) => s.id === id) || null; }

    _learn(spk, frames) {
      if (!spk) return;
      const cap = 900;
      for (const f of frames) {
        const n = Math.min(spk.n, cap) + 1;
        for (let i = 0; i < N_MFCC; i++) spk.mean[i] += (f.mfcc[i] - spk.mean[i]) / n;
        spk.n++;
        if (f.f0 > 0) {
          spk.pList.push(12 * Math.log2(f.f0 / 100));
          spk.pN++;
        }
      }
      if (spk.pList.length > 600) spk.pList.splice(0, spk.pList.length - 600);
      if (spk.pList.length) spk.pMean = median(spk.pList);
    }

    _setCurrent(id, t, isNew) {
      const prev = this.current;
      if (this.tone && this.toneBuf.length && prev != null && prev !== id) {
        // speech before the change belongs to the previous person
        const after = this.toneBuf.filter((f) => f.t >= t);
        this.toneBuf = this.toneBuf.filter((f) => f.t < t);
        this._toneFlush(prev, true);
        this.toneBuf = after;
      }
      this.current = id;
      this.lastChangeT = t;
      this.pendingCue = {};
      this.onEvent({ type: 'speaker', id, prevId: prev, isNew: !!isNew, t });
    }

    // ------------------------------------------------------------ public controls
    forceNewSpeaker() {
      const s = this._newSpeaker(this.t);
      s._fresh = false;
      if (this.seg) {
        const recent = this.seg.frames.slice(-60);
        this._learn(s, recent);
        this.seg.assigned = true;
      }
      this._setCurrent(s.id, this.t, true);
      return s.id;
    }

    setCurrentSpeaker(id) {
      const s = this._speaker(id);
      if (!s) return;
      if (this.seg) this._learn(s, this.seg.frames.slice(-60));
      this._setCurrent(id, this.t, false);
    }

    mergeSpeakers(keepId, dropId) {
      const a = this._speaker(keepId), b = this._speaker(dropId);
      if (!a || !b || a === b) return;
      const n = a.n + b.n || 1;
      for (let i = 0; i < N_MFCC; i++) a.mean[i] = (a.mean[i] * a.n + b.mean[i] * b.n) / n;
      a.pList = a.pList.concat(b.pList).slice(-600);
      a.pMean = a.pList.length ? median(a.pList) : 0;
      a.n += b.n; a.pN += b.pN;
      if (this.tone) {
        this.tone.merge(keepId, dropId);
        const ha = this.toneHist.get(keepId) || [], hb = this.toneHist.get(dropId) || [];
        this.toneHist.set(keepId, ha.concat(hb).slice(-this.tuning.toneHistory));
        this.toneHist.delete(dropId);
      }
      this.speakers = this.speakers.filter((s) => s !== b);
      if (this.current === dropId) this._setCurrent(keepId, this.t, false);
      this.onEvent({ type: 'speakers', speakers: this.listSpeakers() });
    }

    listSpeakers() {
      return this.speakers.map((s) => ({
        id: s.id, voicedSec: +(s.n * FRAME_SEC).toFixed(1),
        pitchHz: s.pN ? Math.round(100 * Math.pow(2, s.pMean / 12)) : null,
      }));
    }

    // ------------------------------------------------------------ tone cues
    _winStats(frames) {
      // loudness: mean of the louder half (robust to gaps inside words)
      const dbs = frames.map((f) => f.db).sort((a, b) => b - a);
      const top = dbs.slice(0, Math.max(1, Math.floor(dbs.length / 2)));
      const db = top.reduce((a, b) => a + b, 0) / top.length;
      const voiced = frames.filter((f) => f.f0 > 0).map((f) => 12 * Math.log2(f.f0 / 100)).sort((a, b) => a - b);
      const st = voiced.length >= 8 ? voiced[Math.floor(voiced.length / 2)] : null;
      // speaking rate: each syllable usually has one voiced vowel, so count where voicing begins
      const onsets = frames.filter((f) => f.onset).length;
      const rate = onsets / (frames.length * FRAME_SEC);
      return { db, st, rate };
    }

    _trackBaseline(f) {
      const spk = this._speaker(this.current);
      if (!spk) return;
      spk._recent = spk._recent || [];
      spk._recent.push(f);
      if (spk._recent.length > 260) spk._recent.splice(0, spk._recent.length - 260);
      spk.base.n++;
    }

    _evaluateCues(t) {
      const T = this.tuning;
      const spk = this._speaker(this.current);
      if (!spk || !spk._recent || spk._recent.length < T.cueWindow) return;
      const w = this._winStats(spk._recent.slice(-T.cueWindow));
      const longW = this._winStats(spk._recent.slice(-T.rateWindow));
      const b = spk.base;

      if (b.n < T.baselineMinFrames || b.db === 0) {
        // warm-up: running average of window stats
        b.k = (b.k || 0) + 1;
        b.db += (w.db - b.db) / b.k;
        if (w.st != null) { b.stK = (b.stK || 0) + 1; b.st += (w.st - b.st) / b.stK; }
        b.rateN++; b.rate += (longW.rate - b.rate) / b.rateN;
        return;
      }

      const dDb = w.db - b.db;
      const dSt = w.st != null && b.stK ? w.st - b.st : 0;
      const rateRatio = b.rate > 0.5 ? longW.rate / b.rate : 1;
      const s = this.settings.cues;

      const drop = dDb <= T.dropDb || (dDb <= T.dropDbWithPitch && dSt <= T.dropSt);
      // Speaking rate is reported for the replay but does not trigger a cue: measured over a few
      // seconds it varies too much within one person to be trusted (see tests).
      const rise = dDb >= T.riseDb || (dDb >= T.riseDbWithPitch && dSt >= T.riseSt);
      const detail = { dDb: +dDb.toFixed(1), dSt: +dSt.toFixed(1), rate: +rateRatio.toFixed(2) };

      // Once Sanket has heard this person a few times and the tone model is loaded, "voice rose" and
      // "voice softened" come from the model (fewer false alarms on held-out and natural speech —
      // training/eval_cues.mjs); until then, and without the model, these loudness/pitch rules decide.
      const modelReady = this.tone && (this.toneHist.get(this.current) || []).length >= this.tone.model.minUtterances;
      this._confirm('drop', s.drop && (modelReady ? dDb <= T.dropDbStrong : drop), t, detail);
      this._confirm('rise', s.rise && rise && !drop && !modelReady, t, detail);


      // slow baseline adaptation (≈ 30 s), skipped while a change is pending
      if (!drop && !rise) {
        const a = 0.01;
        b.db += a * (w.db - b.db);
        if (w.st != null) b.st += a * (w.st - b.st);
        b.rate += a * (longW.rate - b.rate);
      }
    }

    // ------------------------------------------------------------ tone estimates
    // force: estimate even a short stretch (speaker change, session end); otherwise short
    // stretches wait to be joined with the person's next utterance
    _toneFlush(speakerId, force) {
      const T = this.tuning;
      const frames = this.toneBuf;
      if (!this.tone || !frames.length) return;
      if (frames.length < T.toneMinFrames) {
        if (force) this.toneBuf = [];
        return;
      }
      this.toneBuf = [];
      const est = this.tone.estimate(speakerId, frames);
      if (!est) return;
      const hist = this.toneHist.get(speakerId) || [];
      const usual = hist.length >= T.toneMinHistory ? hist.reduce((a, b) => a + b, 0) / hist.length : null;
      const shift = usual == null ? null : est.arousal - usual;
      hist.push(est.arousal);
      if (hist.length > T.toneHistory) hist.shift();
      this.toneHist.set(speakerId, hist);
      const t0 = frames[0].t, t1 = frames[frames.length - 1].t;
      const relative = toneLib().relativeTone(est, shift, { rise: T.toneRiseShift, sad: T.toneSadProb });
      this.onEvent(Object.assign({ type: 'tone', speakerId, t0, t1, shift, relative }, est));

      // model-backed cues, only once Sanket knows this person's usual voice
      if (!est.personal) return;
      const s = this.settings.cues;
      const now = this.t;
      const detail = { source: 'model', from: +t0.toFixed(2), to: +t1.toFixed(2) };
      if (s.drop && est.probs.sad != null && est.probs.sad >= T.toneSadProb) {
        this._cueFor(speakerId, 'drop', now, Object.assign({ sad: +est.probs.sad.toFixed(2) }, detail));
      } else if (s.rise && shift != null && shift >= T.toneRiseShift) {
        this._cueFor(speakerId, 'rise', now, Object.assign({ shift: +shift.toFixed(2) }, detail));
      }
    }

    _cueFor(speakerId, kind, t, detail) {
      const cur = this.current;
      this.current = speakerId;           // the cue is about the person who said it
      const ok = this._cue(kind, t, detail);
      this.current = cur;
      return ok;
    }

    _checkHesitation(t) {
      const T = this.tuning;
      if (this.gaps.length > 50) this.gaps.splice(0, this.gaps.length - 50);
      if (this.current == null || !this.settings.cues.hesitation) return;
      const since = Math.max(t - T.hesitationWindowSec, this.lastChangeT);
      const recent = this.gaps.filter((g) => g.t >= since && g.speaker === this.current);
      if (recent.length >= T.hesitationGaps) {
        if (this._cue('hesitation', t, { pauses: recent.length })) this.gaps = [];
      }
    }

    _confirm(kind, cond, t, detail) {
      if (!cond) { this.pendingCue[kind] = 0; return; }
      this.pendingCue[kind] = (this.pendingCue[kind] || 0) + 1;
      if (this.pendingCue[kind] >= this.tuning.confirmEvals) {
        if (this._cue(kind, t, detail)) this.pendingCue[kind] = 0;
      }
    }

    _cue(kind, t, detail) {
      if (!this.settings.cues[kind]) return false;
      const last = this.lastCueByKind[kind] == null ? -1e9 : this.lastCueByKind[kind];
      if (t - last < this.settings.cueCooldownSec) return false;
      if (t - this.lastCueT < this.settings.cueGapSec) return false;
      this.lastCueT = t;
      this.lastCueByKind[kind] = t;
      this.onEvent({ type: 'cue', kind, t, speakerId: this.current, detail: detail || {} });
      return true;
    }
  }

  const api = {
    VoiceEngine, FrameAnalyser, Resampler, fft, yin, hamming,
    SR, FRAME, HOP, FRAME_SEC, TUNING, DEFAULTS,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SanketEngine = api;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
