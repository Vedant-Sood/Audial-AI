// Measures Sanket's live tone cues against CREMA-D emotion labels, in simulated sessions:
// each session plays 8 earlier clips from the same speaker (so Sanket learns their usual voice —
// mostly calm, as in real life: 6 neutral sentences and 2 others), then one target clip.
// Did "voice rose" / "voice softened" fire during the target?
//
// A second check uses natural (non-acted) calm reading from tests/fixtures/sanket: model cues must not fire
// there more often than the original rules do.
//
// Compares: (1) the original loudness/pitch rules, (2) model-assisted cues from the tone model,
// (3) both combined. Model thresholds are tuned on VALIDATION speakers, results reported on TEST.
//
// Usage: node training/sanket/eval_cues.mjs <wav dir> <splits.json> <tone_model.json> <out report.json>
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const E = require('../../browser/sanket/engine.js');
const Tone = require('../../browser/sanket/tone.js');

const [wavDir, splitsPath, modelPath, outPath] = process.argv.slice(2);
const splits = JSON.parse(fs.readFileSync(splitsPath, 'utf8'));
const model = JSON.parse(fs.readFileSync(modelPath, 'utf8'));
const EMO = { ANG: 'angry', DIS: 'disgust', FEA: 'fear', HAP: 'happy', NEU: 'neutral', SAD: 'sad' };
const HIGH = new Set(['angry', 'happy', 'fear']);

let seed = 12345;
const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const pick = (arr) => arr[Math.floor(rand() * arr.length)];

function readWav(file) {
  const b = fs.readFileSync(file);
  let o = 12, data = null;
  while (o + 8 <= b.length) {
    const id = b.toString('ascii', o, o + 4), len = b.readUInt32LE(o + 4);
    if (id === 'data') { data = b.subarray(o + 8, o + 8 + len); break; }
    o += 8 + len + (len & 1);
  }
  const x = new Float32Array(data.length >> 1);
  for (let i = 0; i < x.length; i++) x[i] = data.readInt16LE(i * 2) / 32768;
  return x;
}
const cache = new Map();
const wav = (f) => { if (!cache.has(f)) cache.set(f, readWav(path.join(wavDir, f))); return cache.get(f); };
const gap = (s) => { const g = new Float32Array(Math.round(s * 16000)); for (let i = 0; i < g.length; i++) g[i] = (Math.random() * 2 - 1) * 0.0003; return g; };

function session(files) {
  const parts = [gap(0.5)], spans = [];
  let t = 0.5;
  for (const f of files) {
    const x = wav(f); parts.push(x); spans.push([t, t + x.length / 16000]); t += x.length / 16000;
    const g = gap(0.7); parts.push(g); t += 0.7;
  }
  const n = parts.reduce((a, p) => a + p.length, 0), sig = new Float32Array(n);
  let o = 0; for (const p of parts) { sig.set(p, o); o += p.length; }
  return { sig, spans };
}

// run the live engine; collect rule cues and per-clip frames for the tone model
function run(files) {
  const { sig, spans } = session(files);
  const cues = [], frames = [];
  const eng = new E.VoiceEngine({
    settings: { singleSpeaker: true, cues: { drop: true, rise: true, hesitation: false, silence: false } },
    onEvent: (e) => { if (e.type === 'cue') cues.push(e); },
    onSpeechFrame: (f) => frames.push(f),
    tuning: process.env.TUNE ? JSON.parse(process.env.TUNE) : undefined,
  });
  for (let i = 0; i < sig.length; i += 128) eng.process(sig.subarray(i, i + 128));
  // tone estimates per clip, in order (as the live app does at the end of each utterance)
  const est = new Tone.Estimator(model);
  const estimates = spans.map(([a, b]) => est.estimate(1, frames.filter((f) => f.t >= a && f.t <= b + 0.2)));
  return { cues, spans, estimates };
}

function sessionsFor(splitName, perActor) {
  const byActor = {};
  for (const f of splits[splitName].files) {
    if (!fs.existsSync(path.join(wavDir, f))) continue;
    const a = f.split('_')[0];
    (byActor[a] = byActor[a] || []).push(f);
  }
  const out = [];
  for (const [a, fs_] of Object.entries(byActor)) {
    for (let k = 0; k < perActor; k++) {
      const target = pick(fs_);
      const neu = fs_.filter((f) => f.includes('_NEU_') && f !== target), oth = fs_.filter((f) => !f.includes('_NEU_') && f !== target);
      const warm = [];
      while (warm.length < 6) { const w = pick(neu); if (!warm.includes(w)) warm.push(w); }
      while (warm.length < 8) { const w = pick(oth); if (!warm.includes(w)) warm.push(w); }
      warm.sort(() => rand() - 0.5);
      out.push({ actor: a, files: warm.concat([target]), emotion: EMO[target.split('_')[2]] });
    }
  }
  return out;
}

function collect(splitName, perActor) {
  const rows = [];
  for (const s of sessionsFor(splitName, perActor)) {
    const r = run(s.files);
    const [a, b] = r.spans[r.spans.length - 1];
    const inTarget = (c) => c.t >= a && c.t <= b + 0.6;
    const prev = r.estimates.slice(0, -1).filter(Boolean);
    const baseArousal = prev.length ? prev.reduce((t, e) => t + e.arousal, 0) / prev.length : 0;
    const est = r.estimates[r.estimates.length - 1];
    rows.push({
      emotion: s.emotion,
      ruleRise: r.cues.some((c) => c.kind === 'rise' && inTarget(c)),
      ruleDrop: r.cues.some((c) => c.kind === 'drop' && inTarget(c)),
      arousal: est ? est.arousal : null,
      dArousal: est ? est.arousal - baseArousal : null,
      pSad: est ? est.probs.sad : null,
      personal: est ? est.personal : false,
    });
  }
  return rows;
}

// natural calm reading (LibriSpeech, tests/fixtures/sanket), each recording played 5 times at slightly
// different levels so Sanket learns the voice; every estimated stretch is a "should stay quiet" case
function naturalRows() {
  const dir = path.join(path.dirname(new URL(import.meta.url).pathname), '../../tests/fixtures/sanket');
  const rows = [];
  for (const name of ['198-209-0000', '3436-172162-0000', '5703-47212-0000']) {
    const x = readWav(path.join(dir, name + '.wav'));
    const parts = [0, -2, 2, -1, 1].map((g) => x.map((v) => v * Math.pow(10, g / 20)));
    const sig = new Float32Array(parts.reduce((a, p) => a + p.length, 0));
    let o = 0; for (const p of parts) { sig.set(p, o); o += p.length; }
    const ev = [];
    const eng = new E.VoiceEngine({ toneModel: model, settings: { singleSpeaker: true }, onEvent: (e) => ev.push(e) });
    for (let i = 0; i < sig.length; i += 128) eng.process(sig.subarray(i, i + 128));
    eng.flushTone();
    const minutes = sig.length / 16000 / 60;
    const rule = new E.VoiceEngine({ settings: { singleSpeaker: true }, onEvent: (e) => ev.push(Object.assign({ rule: true }, e)) });
    for (let i = 0; i < sig.length; i += 128) rule.process(sig.subarray(i, i + 128));
    for (const e of ev) if (e.type === 'tone' && e.personal) rows.push({ emotion: 'natural', dArousal: e.shift, pSad: e.probs.sad, minutes });
    rows.ruleCues = (rows.ruleCues || 0) + ev.filter((e) => e.rule && e.type === 'cue' && (e.kind === 'rise' || e.kind === 'drop')).length;
    rows.minutes = (rows.minutes || 0) + minutes;
  }
  return rows;
}

const rate = (rows, emo, key) => { const r = rows.filter((x) => emo.includes(x.emotion)); return r.length ? r.filter((x) => x[key]).length / r.length : 0; };

// Model scores for each cue. Rise: intensity above this person's recent usual.
// Softened: either sadness probability or intensity below their usual (picked on validation).
const SCORES = {
  rise: { arousal_shift: (x) => x.dArousal },
  drop: { sad_prob: (x) => x.pSad, arousal_drop: (x) => (x.dArousal == null ? null : -x.dArousal) },
};
const TARGET = { rise: [...HIGH], drop: ['sad'] };
const WRONG = { rise: ['sad'], drop: [...HIGH] };
const RULE = { rise: 'ruleRise', drop: 'ruleDrop' };

function mark(rows, cue, mode, scoreName, th) {
  const f = SCORES[cue][scoreName];
  for (const x of rows) {
    const s = f(x), m = s != null && s >= th, r = x[RULE[cue]];
    x._on = mode === 'model' ? m : mode === 'rule_and_model' ? r && m : r || m;
  }
}
const stats = (rows, cue) => ({
  hit: rate(rows, TARGET[cue], '_on'), fa: rate(rows, ['neutral'], '_on'), wrong: rate(rows, WRONG[cue], '_on'),
});

// Pick, on validation speakers, the variant with the best (hits − false alarms − wrong-direction)
// that does not raise the false-alarm rate above the original rule's.
function tuneCue(val, cue, nat) {
  for (const x of val) x._on = x[RULE[cue]];
  const ruleS = stats(val, cue);
  for (const x of nat) x.ruleRise = x.ruleDrop = false;   // rule cues on natural speech are counted separately
  const natLimit = Math.max(1, nat.ruleCues || 0);       // no more false cues on calm reading than the rules give (min 1)
  let best = { mode: 'rule', score: ruleS.hit - ruleS.fa - ruleS.wrong, val: ruleS };
  for (const mode of ['model', 'rule_and_model', 'rule_or_model']) {
    for (const scoreName of Object.keys(SCORES[cue])) {
      for (let th = -0.5; th <= 1.0; th += 0.01) {
        mark(val, cue, mode, scoreName, th);
        const st = stats(val, cue);
        if (st.fa > ruleS.fa + 1e-9) continue;
        if (mode !== 'rule_and_model') { mark(nat, cue, 'model', scoreName, th); if (nat.filter((x) => x._on).length > natLimit) continue; }
        const score = st.hit - st.fa - st.wrong;
        if (score > best.score + 1e-9) best = { mode, scoreName, th: +th.toFixed(2), score, val: st };
      }
    }
  }
  return best;
}
function applyCue(rows, cue, choice) {
  if (choice.mode === 'rule') for (const x of rows) x._on = x[RULE[cue]];
  else mark(rows, cue, choice.mode, choice.scoreName, choice.th);
  return stats(rows, cue);
}
const r3 = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, +v.toFixed(3)]));

const cachePath = outPath.replace(/\.json$/, '') + (process.env.TUNE ? '_tuned' : '') + '_rows.json';
let val, test;
if (fs.existsSync(cachePath)) ({ val, test } = JSON.parse(fs.readFileSync(cachePath, 'utf8')));
else {
  console.log('validation sessions…'); val = collect('validation', 40);
  console.log('test sessions…'); test = collect('test', 40);
  fs.writeFileSync(cachePath, JSON.stringify({ val, test }));
}

const nat = naturalRows();
console.log(`natural calm reading: ${nat.length} estimated stretches over ${nat.minutes.toFixed(1)} min; rule cues there: ${nat.ruleCues}`);
const report = { sessions: { validation: val.length, test: test.length, natural_stretches: nat.length, natural_minutes: +nat.minutes.toFixed(1) }, natural_rule_cues: nat.ruleCues, cues: {} };
for (const cue of ['rise', 'drop']) {
  const choice = tuneCue(val, cue, nat);
  const before = applyCue(test, cue, { mode: 'rule' });
  const after = applyCue(test, cue, choice);
  let natCues = 0;
  if (choice.mode !== 'rule') { mark(nat, cue, 'model', choice.scoreName, choice.th); natCues = nat.filter((x) => x._on).length; }
  report.cues[cue] = { choice: { mode: choice.mode, score: choice.scoreName, threshold: choice.th }, test_before: r3(before), test_after: r3(after),
    natural_model_cues: choice.mode === 'rule_and_model' ? 'only with a rule cue' : natCues };
}
console.log(JSON.stringify(report, null, 1));
fs.writeFileSync(outPath, JSON.stringify(report, null, 1));
