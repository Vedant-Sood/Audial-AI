// Back-channel hold study (decision 0004): how long has a turn lasted when the engine decides
// who is speaking, and what happens to short interjections?
//
//   node scripts/kandha_backchannel_study.mjs docs/kandha/validation/backchannel.json
//
// Runs browser/sanket/engine.js over the LibriSpeech fixtures used by scripts/verify_sanket.py
// (two readers, A B A B) and over the same conversation with synthetic back-channels of 0.25 s
// and 0.45 s from the other reader spliced into the first reader's turns. Records, for every
// speaker decision, the length of the turn at decision time (the number kandha-intents.js
// compares with min_turn_s).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";

const require = createRequire(import.meta.url);
const E = require("../browser/sanket/engine.js");
const rules = JSON.parse(readFileSync(new URL("../browser/sanket/kandha-patterns.json", import.meta.url), "utf8")).scheduler;

function wav(name) {
  const b = readFileSync(new URL(`../tests/fixtures/sanket/${name}.wav`, import.meta.url));
  let o = 12;
  while (b.toString("ascii", o, o + 4) !== "data") o += 8 + b.readUInt32LE(o + 4);
  const n = b.readUInt32LE(o + 4) / 2, x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = b.readInt16LE(o + 8 + i * 2) / 32768;
  return x;
}
const S = 16000;
const concat = parts => { const out = new Float32Array(parts.reduce((a, p) => a + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const quiet = s => Float32Array.from({ length: Math.round(s * S) }, () => (rnd() * 2 - 1) * 3e-4);
const a = wav("198-209-0000"), b = wav("3436-172162-0000");

// A loud, voiced slice of reader B to use as an interjection ("mm-hm")
function burst(seconds) {
  const n = Math.round(seconds * S);
  // pick the loudest window of B's first 8 s
  let best = 0, bestE = -1;
  for (let i = 0; i + n < 8 * S; i += 800) { let e = 0; for (let j = i; j < i + n; j++) e += b[j] * b[j]; if (e > bestE) { bestE = e; best = i; } }
  const x = b.slice(best, best + n);
  const fade = Math.round(0.01 * S);
  for (let i = 0; i < fade; i++) { x[i] *= i / fade; x[n - 1 - i] *= i / fade; }
  return x;
}

function analyse(signal) {
  const events = [];
  let speaking = false, lastEnd = null;
  const engine = new E.VoiceEngine({ onEvent: e => {
    if (e.type === "speech-start") speaking = true;
    if (e.type === "speech-end") { speaking = false; lastEnd = e.t; }
    if (e.type === "speaker") events.push({ t: e.t, decidedAt: engine.t, id: e.id, isNew: e.isNew,
      // turn length known at decision time: still speaking -> now - start; after a pause -> end - start
      turnSoFar: +(((speaking || lastEnd == null || lastEnd < e.t) ? engine.t : lastEnd) - e.t).toFixed(3) });
  } });
  for (let i = 0; i < signal.length; i += 256) engine.process(signal.subarray(i, i + 256));
  return events;
}

const conversation = [quiet(0.6), a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(0.8), a.subarray(8 * S, 13 * S), quiet(0.8), b.subarray(8 * S, 14 * S), quiet(2)];
const report = { generated_by: "scripts/kandha_backchannel_study.mjs", engine: { earlyFrames: E.TUNING.earlyFrames, finalFrames: E.TUNING.finalFrames, minShortFrames: E.TUNING.minShortFrames, turnGapSec: E.TUNING.turnGapSec, frameSec: E.FRAME_SEC }, min_turn_s: rules.min_turn_s, cases: {} };

report.cases.abab = { description: "Two LibriSpeech readers, A B A B (the verify_sanket conversation)", decisions: analyse(concat(conversation)) };

for (const seconds of [0.25, 0.45, 0.6, 0.9]) {
  // reader A talks for 8 s; the other reader interjects twice, inside A's turn, with 0.3 s of pause either side
  const bc = burst(seconds);
  const signal = concat([quiet(0.6), a.subarray(0, 3 * S), quiet(0.3), bc, quiet(0.3), a.subarray(3 * S, 9 * S), quiet(0.3), bc, quiet(0.3), a.subarray(9 * S, 14 * S), quiet(1.5)]);
  const decisions = analyse(signal);
  const bursts = [3.6 + 0.3, 3.6 + 0.3 + seconds + 0.3 + 6 + 0.3 + 0.3];  // approximate start times of the two bursts
  report.cases[`backchannel_${seconds}s`] = {
    description: `Reader A with two ${seconds} s interjections by reader B`,
    burst_starts_s: bursts.map(t => +t.toFixed(2)),
    decisions,
    taps_with_hold: decisions.filter(d => d.turnSoFar >= rules.min_turn_s).length,
    decisions_total: decisions.length,
  };
}

// summary for the decision record
const all = Object.values(report.cases).flatMap(c => c.decisions);
report.summary = {
  real_turn_decisions_min_turn_so_far_s: Math.min(...report.cases.abab.decisions.map(d => d.turnSoFar)),
  decisions_under_hold: all.filter(d => d.turnSoFar < rules.min_turn_s).map(d => ({ turnSoFar: d.turnSoFar, id: d.id })),
  note: "turnSoFar is the turn length known when the engine decides; kandha-intents.js taps only when it reaches min_turn_s (or once speech continues to it).",
};
const out = process.argv[2];
if (out) { mkdirSync(dirname(out), { recursive: true }); writeFileSync(out, JSON.stringify(report, null, 1) + "\n"); }
for (const [name, c] of Object.entries(report.cases)) console.log(name, c.decisions.map(d => `${d.id}@${d.t.toFixed(2)}(turn ${d.turnSoFar}s${d.isNew ? ",new" : ""})`).join("  "));
console.log("summary", JSON.stringify(report.summary));
