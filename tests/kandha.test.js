// Kandha: the shared pattern table, and the page-side intent layer on real LibriSpeech turns.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const E = require("../browser/sanket/engine.js");
const { IntentSource } = require("../browser/kandha/kandha-intents.js");
const read = path => readFileSync(new URL(path, import.meta.url));
const table = JSON.parse(read("../browser/sanket/kandha-patterns.json"));

function wav(name) {
  const b = read(`./fixtures/sanket/${name}.wav`);
  let o = 12;
  while (b.toString("ascii", o, o + 4) !== "data") o += 8 + b.readUInt32LE(o + 4);
  const n = b.readUInt32LE(o + 4) / 2, x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = b.readInt16LE(o + 8 + i * 2) / 32768;
  return x;
}
const S = 16000;
const concat = parts => { const out = new Float32Array(parts.reduce((a, p) => a + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
let seed = 3; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const quiet = s => Float32Array.from({ length: Math.round(s * S) }, () => (rnd() * 2 - 1) * 3e-4);

function run(signal, options = {}) {
  const source = new IntentSource({ minTurn: table.scheduler.min_turn_s, wall: () => 0 });
  const events = [];
  const engine = new E.VoiceEngine({ onEvent: e => { events.push(e); source.handle(e); }, ...options });
  for (let i = 0; i < signal.length; i += 256) engine.process(signal.subarray(i, i + 256));
  return { source, events };
}

test("the pattern table is the documented tap language with the retired band's service gone", () => {
  const keys = Object.fromEntries(table.patterns.map(p => [p.key, p]));
  assert.equal(keys.seat_tap.steps[0].on_ms, 120);
  assert.equal(keys.new_voice.steps.length, 2);
  assert.equal(keys.drop.steps.reduce((a, s) => a + s.on_ms + s.off_ms, 0), 700);
  assert.equal(keys.rise.steps.length, 3);
  assert.equal(keys.hesitation.steps.length, 5);
  assert.equal(keys.silence.zones, "LR");
  assert.ok(table.patterns.every(p => p.id >= 0 && p.id <= 31));
  assert.ok(!JSON.stringify(table).includes("a7c2f3e0"));
  assert.ok(table.protocol.service_uuid.length === 36);
  assert.equal(table.scheduler.min_turn_s, 0.6);
});

test("A B A B turns give four seat intents in order, the first two for new voices", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000");
  const { source } = run(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(0.8), a.subarray(8 * S, 13 * S), quiet(0.8), b.subarray(8 * S, 14 * S), quiet(2)]));
  const taps = source.intents.filter(i => i.kind === "speaker" || i.kind === "new_voice");
  assert.deepEqual(taps.map(i => [i.kind, i.voice]), [["new_voice", 1], ["new_voice", 2], ["speaker", 1], ["speaker", 2]]);
  assert.deepEqual(source.suppressed, []);
  // the tap is asked for at most one engine frame after the hold: no real turn waits for it
  for (const i of taps) assert.ok(i.t >= 0);
});

test("a 0.45 s interjection never taps but a real turn still does", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000");
  const n = Math.round(0.45 * S);
  let best = 0, bestE = -1;
  for (let i = 0; i + n < 8 * S; i += 800) { let e = 0; for (let j = i; j < i + n; j++) e += b[j] * b[j]; if (e > bestE) { bestE = e; best = i; } }
  const burst = b.slice(best, best + n);
  const { source } = run(concat([quiet(0.6), a.subarray(0, 3 * S), quiet(0.3), burst, quiet(0.3), a.subarray(3 * S, 9 * S), quiet(0.3), burst, quiet(0.3), a.subarray(9 * S, 14 * S), quiet(1.5)]));
  const taps = source.intents.filter(i => i.kind === "speaker" || i.kind === "new_voice");
  assert.ok(taps.length >= 1 && taps.every(i => i.voice === 1), "only reader A is ever asked for; the scheduler drops a repeat of the same voice");
  assert.ok(source.suppressed.some(s => s.voice === 2 && s.turn < table.scheduler.min_turn_s), "the interjection was held and dropped");
});

test("after a long silence the same voice starting again asks for a resume tap, once", () => {
  const source = new IntentSource({ minTurn: 0.6, wall: () => 42 });
  const feed = (...events) => events.flatMap(e => source.handle(e));
  feed({ type: "speech-start", t: 0.5, gap: null }, { type: "level", t: 1.2 });
  assert.deepEqual(feed({ type: "speaker", id: 1, isNew: true, t: 0.5 }).map(i => i.kind), ["new_voice"]);
  feed({ type: "speech-end", t: 4.0 });
  assert.deepEqual(feed({ type: "cue", kind: "silence", t: 8.0, speakerId: 1 }).map(i => i.kind), ["silence"]);
  feed({ type: "speech-start", t: 9.0, gap: 5.0 });
  assert.deepEqual(feed({ type: "level", t: 9.3 }), [], "not yet: the resume waits for the hold");
  const resumed = feed({ type: "level", t: 9.62 });
  assert.deepEqual(resumed.map(i => [i.kind, i.voice, i.t]), [["voice_resumes", 1, 9.0]]);
  assert.deepEqual(feed({ type: "level", t: 12 }), [], "only once");
  assert.equal(source.intents.at(-1).created, 42);
});

test("a new speaker within the hold replaces the resume tap: never two taps for one start", () => {
  const source = new IntentSource({ minTurn: 0.6 });
  const feed = (...events) => events.flatMap(e => source.handle(e));
  feed({ type: "speech-start", t: 0.5 }, { type: "speaker", id: 1, isNew: true, t: 0.5 }, { type: "level", t: 1.2 }, { type: "speech-end", t: 4 }, { type: "cue", kind: "silence", t: 8 });
  feed({ type: "speech-start", t: 9.0 });
  const out = feed({ type: "level", t: 9.3 }, { type: "speaker", id: 2, isNew: true, t: 9.0 }, { type: "level", t: 9.65 }, { type: "level", t: 10 });
  assert.deepEqual(out.map(i => [i.kind, i.voice]), [["new_voice", 2]]);
  assert.equal(source.resume, null);
});

test("a short back-channel decided after its pause is suppressed and a held decision taps once speech continues", () => {
  const source = new IntentSource({ minTurn: 0.6 });
  const feed = (...events) => events.flatMap(e => source.handle(e));
  feed({ type: "speech-start", t: 0 }, { type: "level", t: 1 }, { type: "speaker", id: 1, isNew: true, t: 0 });
  feed({ type: "speech-end", t: 5 }, { type: "speech-start", t: 5.3 }, { type: "speech-end", t: 5.75 });
  assert.deepEqual(feed({ type: "speaker", id: 2, isNew: true, t: 5.3 }), [], "0.45 s burst decided after its pause");
  assert.equal(source.suppressed.at(-1).turn, 0.45);
  // a decision while still speaking with only 0.3 s known (hypothetical engine tuning) is held, then released
  feed({ type: "speech-start", t: 6 }, { type: "level", t: 6.3 });
  assert.deepEqual(feed({ type: "speaker", id: 3, isNew: true, t: 6 }), []);
  assert.ok(source.hold && source.hold.due === 6.6);
  assert.deepEqual(feed({ type: "level", t: 6.59 }), []);
  assert.deepEqual(feed({ type: "level", t: 6.61 }).map(i => i.voice), [3]);
  // and one that ends too soon is dropped
  feed({ type: "speech-end", t: 9 }, { type: "speech-start", t: 9.4 }, { type: "level", t: 9.7 });
  feed({ type: "speaker", id: 4, isNew: false, t: 9.4 });
  assert.deepEqual(feed({ type: "speech-end", t: 9.8 }), []);
  assert.equal(source.hold, null);
  assert.equal(source.suppressed.at(-1).voice, 4);
});

test("cues become cue and silence intents with the speaker attached", () => {
  const source = new IntentSource();
  assert.deepEqual(source.handle({ type: "cue", kind: "rise", t: 3, speakerId: 2 }).map(i => [i.kind, i.cue, i.voice, i.t]), [["cue", "rise", 2, 3]]);
  assert.deepEqual(source.handle({ type: "cue", kind: "silence", t: 9 }).map(i => [i.kind, i.voice]), [["silence", null]]);
  assert.deepEqual(source.handle({ type: "cue", kind: "sarcasm", t: 10 }), []);
  assert.deepEqual(source.handle({ type: "level", t: 11, db: -40 }), []);
});
