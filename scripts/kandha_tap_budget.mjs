// Tap budget, part 1 (Node): run the voice engine and the intent layer over the natural-speech
// fixtures and write the intents, with audio-time stamps, for the Python scheduler to count.
//
//   node scripts/kandha_tap_budget.mjs docs/kandha/validation/tap_budget_intents.json
//
// Fixtures: the three LibriSpeech readers (tests/fixtures/sanket), each played at five gains
// (0, -2, +2, -1, +1 dB) as in tests/sanket.test.js: 1.22, 1.45 and 1.30 minutes of calm
// reading (each case's minutes are in docs/kandha/validation/tap_budget.json), and a stitched
// "seminar" of about 3.9 minutes where the three readers take turns.
// The intent layer gets the engine's silence setting, as the page passes it.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";

const require = createRequire(import.meta.url);
const E = require("../browser/sanket/engine.js");
const { IntentSource } = require("../browser/kandha/kandha-intents.js");
const table = JSON.parse(readFileSync(new URL("../browser/sanket/kandha-patterns.json", import.meta.url), "utf8"));
const model = JSON.parse(readFileSync(new URL("../models/sanket/tone_model.json", import.meta.url), "utf8"));

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
let seed = 5; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const quiet = s => Float32Array.from({ length: Math.round(s * S) }, () => (rnd() * 2 - 1) * 3e-4);
const gain = (x, db) => x.map(v => v * 10 ** (db / 20));

function run(signal, settings) {
  const source = new IntentSource({ minTurn: table.scheduler.min_turn_s, silenceSec: E.DEFAULTS.silenceSec, wall: () => engine.t });
  const cues = [];
  const engine = new E.VoiceEngine({ toneModel: model, settings, onEvent: e => { if (e.type === "cue") cues.push(e.kind); source.handle(e); } });
  for (let i = 0; i < signal.length; i += 256) engine.process(signal.subarray(i, i + 256));
  engine.flushTone();
  return { minutes: signal.length / S / 60, intents: source.intents.map(i => ({ kind: i.kind, voice: i.voice ?? null, cue: i.cue ?? null, t: +i.t.toFixed(3), created: +i.created.toFixed(3), new: !!i.new })),
    engine_cues: cues, suppressed: source.suppressed.length };
}

const readers = ["198-209-0000", "3436-172162-0000", "5703-47212-0000"].map(wav);
const cases = {};
// one reader at a time, all cues on (the engine's own cooldowns apply)
readers.forEach((x, i) => {
  const signal = concat([0, -2, 2, -1, 1].map(db => concat([gain(x, db), quiet(0.7)])));
  cases[`reader_${i + 1}_single`] = run(signal, { singleSpeaker: true, cues: { drop: true, rise: true, hesitation: true, silence: true } });
});
// a stitched three-reader seminar: 6 s turns, 0.7 s pauses, ~3.9 minutes
const turns = [];
let t = 0; const order = [0, 1, 2, 0, 2, 1, 0, 1, 2, 1, 0, 2];
for (let k = 0; t < 3.9 * 60; k++) {
  const r = readers[order[k % order.length]];
  const start = Math.round((k * 7 % Math.max(1, r.length / S - 7)) * S);
  const piece = r.subarray(start, start + 6 * S);
  turns.push(piece, quiet(0.7)); t += piece.length / S + 0.7;
}
cases.seminar_three_readers = run(concat(turns), { cues: { drop: true, rise: true, hesitation: true, silence: true } });

const out = process.argv[2];
const report = { generated_by: "scripts/kandha_tap_budget.mjs", fixtures: "LibriSpeech test clips (CC BY 4.0), tests/fixtures/sanket", min_turn_s: table.scheduler.min_turn_s, cases };
if (out) { mkdirSync(dirname(out), { recursive: true }); writeFileSync(out, JSON.stringify(report) + "\n"); }
for (const [name, c] of Object.entries(cases)) console.log(name, c.minutes.toFixed(2), "min", c.intents.length, "intents", JSON.stringify(c.intents.reduce((a, i) => (a[i.kind] = (a[i.kind] || 0) + 1, a), {})), "engine cues", c.engine_cues.length, "suppressed", c.suppressed);
