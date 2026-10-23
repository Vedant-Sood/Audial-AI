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
//
// It also runs browser/kandha/kandha-intents.js after long silences (the same reader again, a
// known reader coming back, a new reader, a noise burst first) and records when the engine
// settled the turn and which seat intents were sent, and when: one tap per start, never the
// previous voice's seat first, never a voice the engine made from the noise.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";

const require = createRequire(import.meta.url);
const E = require("../browser/sanket/engine.js");
const { IntentSource } = require("../browser/kandha/kandha-intents.js");
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
const a = wav("198-209-0000"), b = wav("3436-172162-0000"), c = wav("5703-47212-0000");

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

// After a long silence: when does the engine settle the first turn, and what do the intents send?
function resume(signal) {
  let engine, start = null, settledAt = null;
  const seat = [];
  // the page passes the engine's silence setting (here the engine's default)
  const source = new IntentSource({ minTurn: rules.min_turn_s, silenceSec: E.DEFAULTS.silenceSec, wall: () => 0,
    onIntent: i => { if (start != null && ["speaker", "new_voice", "voice_resumes"].includes(i.kind)) seat.push({ kind: i.kind, voice: i.voice, sent_after_start_s: +(engine.t - start).toFixed(3) }); } });
  engine = new E.VoiceEngine({ onEvent: e => {
    if (e.type === "speech-start" && e.gap != null && e.gap >= E.DEFAULTS.silenceSec) { start = e.t; settledAt = null; }
    source.handle(e);
    // measurement only: the engine's own record of when it assigned the segment
    if (start != null && settledAt == null && engine.seg && engine.seg.assigned && engine.seg.start >= start) settledAt = engine.t;
  } });
  for (let i = 0; i < signal.length; i += 256) engine.process(signal.subarray(i, i + 256));
  return { engine_settled_after_start_s: settledAt == null ? null : +(settledAt - start).toFixed(3), seat_intents: seat };
}
const resumeCases = {};
let seed2 = 11; const noise = s => Float32Array.from({ length: Math.round(s * S) }, () => (((seed2 = (seed2 * 16807) % 2147483647) / 2147483647) * 2 - 1) * 0.1);
for (const sil of [4.5, 6]) {
  resumeCases[`A_silence${sil}_A`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(sil), a.subarray(8 * S, 13 * S), quiet(1)]));
  resumeCases[`A_B_silence${sil}_B`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(sil), b.subarray(8 * S, 14 * S), quiet(1)]));
  resumeCases[`A_B_silence${sil}_A`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(sil), a.subarray(8 * S, 14 * S), quiet(1)]));
  resumeCases[`A_silence${sil}_B_new`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(sil), b.subarray(0, 8 * S), quiet(1)]));
  resumeCases[`A_silence${sil}_C_new`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(sil), c.subarray(0, 8 * S), quiet(1)]));
  resumeCases[`A_silence${sil}_noise0.3_A`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(sil), noise(0.3), quiet(0.5), a.subarray(10 * S, 14 * S), quiet(1)]));
  // 0.3 s of quiet after the burst: the engine judges the burst in that pause and keeps one segment
  resumeCases[`A_silence${sil}_burst0.2_quiet0.3_A`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(sil), b.slice(9.1 * S, 9.3 * S), quiet(0.3), a.subarray(10 * S, 14 * S), quiet(1)]));
  // the engine makes a voice from the noise and learns it from B's speech in the same segment; it
  // gives B back at its next segment, and only then does B's seat tap
  resumeCases[`A_B_silence${sil}_noise0.5_quiet0.28_B`] = resume(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(sil), noise(0.5), quiet(0.28), b.subarray(10 * S, 14 * S), quiet(1.5)]));
}
report.resume_after_silence = {
  description: "First turn after a long silence (times from the first speech-start after it): engine_settled_after_start_s is when the engine assigned that first voice segment (in the noise cases, the noise), seat_intents what kandha-intents.js sent and when",
  cases: resumeCases,
};

// summary for the decision record
const all = Object.values(report.cases).flatMap(c => c.decisions);
const firstTaps = Object.values(resumeCases).map(c => c.seat_intents[0]).filter(Boolean);
report.summary = {
  real_turn_decisions_min_turn_so_far_s: Math.min(...report.cases.abab.decisions.map(d => d.turnSoFar)),
  decisions_under_hold: all.filter(d => d.turnSoFar < rules.min_turn_s).map(d => ({ turnSoFar: d.turnSoFar, id: d.id })),
  resume_turns_without_exactly_one_seat_intent: Object.entries(resumeCases).filter(([, c]) => c.seat_intents.length !== 1).map(([k]) => k),
  resume_first_tap_after_start_s: { min: Math.min(...firstTaps.map(t => t.sent_after_start_s)), max: Math.max(...firstTaps.map(t => t.sent_after_start_s)) },
  note: "turnSoFar is the turn length known when the engine decides; kandha-intents.js taps only when it reaches min_turn_s (or once speech continues to it).",
};
const out = process.argv[2];
if (out) { mkdirSync(dirname(out), { recursive: true }); writeFileSync(out, JSON.stringify(report, null, 1) + "\n"); }
for (const [name, c] of Object.entries(report.cases)) console.log(name, c.decisions.map(d => `${d.id}@${d.t.toFixed(2)}(turn ${d.turnSoFar}s${d.isNew ? ",new" : ""})`).join("  "));
for (const [name, c] of Object.entries(resumeCases)) console.log(name, `settled +${c.engine_settled_after_start_s}s`, c.seat_intents.map(i => `${i.kind}:${i.voice}@+${i.sent_after_start_s}s`).join("  "));
console.log("summary", JSON.stringify(report.summary));
