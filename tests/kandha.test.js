// Kandha: the shared pattern table, and the page-side intent layer on real LibriSpeech turns.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const E = require("../browser/sanket/engine.js");
const { IntentSource, ENGINE_TIMING, FINAL_MARGIN_FRAMES, REJUDGE_WAIT_SEC } = require("../browser/kandha/kandha-intents.js");
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

// actions: [[seconds, (engine, source) => ...]] run between audio blocks, like a button press in
// the page; intentOptions as the page passes them (silenceSec: the engine's setting)
function run(signal, options = {}, actions = [], intentOptions = {}) {
  const source = new IntentSource({ minTurn: table.scheduler.min_turn_s, wall: () => 0, onIntent: i => { i.at = source.engineT; }, ...intentOptions });
  const events = [];
  const engine = new E.VoiceEngine({ onEvent: e => { events.push(e); source.handle(e); }, ...options });
  const todo = actions.slice();
  for (let i = 0; i < signal.length; i += 256) {
    while (todo.length && i / S >= todo[0][0]) todo.shift()[1](engine, source);
    engine.process(signal.subarray(i, i + 256));
  }
  return { source, events, engine };
}
const SEAT = new Set(["speaker", "new_voice", "voice_resumes"]);
// seat intents emitted from the first speech after a silence of at least `gap` seconds
function seatTapsAfterSilence(source, events, gap = 4) {
  const start = events.find(e => e.type === "speech-start" && e.gap != null && e.gap >= gap);
  assert.ok(start, "the signal has a long silence");
  return source.intents.filter(i => SEAT.has(i.kind) && i.at >= start.t).map(i => [i.kind, i.voice]);
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

// level events every second frame (32 ms), as the engine sends them
const levels = (from, to, speaking = true) => { const out = []; for (let k = 0; from + k * 0.032 <= to + 1e-9; k++) out.push({ type: "level", t: +(from + k * 0.032).toFixed(3), speaking }); return out; };

test("after a long silence the same voice starting again asks for a resume tap, once, after the engine's final say", () => {
  const source = new IntentSource({ minTurn: 0.6, wall: () => 42, silenceSec: 4 });
  const feed = (...events) => events.flatMap(e => source.handle(e));
  feed({ type: "speech-start", t: 0.5, gap: null }, { type: "level", t: 1.2 });
  assert.deepEqual(feed({ type: "speaker", id: 1, isNew: true, t: 0.5 }).map(i => i.kind), ["new_voice"]);
  feed({ type: "speech-end", t: 4.0 });
  // no silence cue at all (switched off, or swallowed by the engine's cue cooldown): the gap is enough
  feed({ type: "speech-start", t: 9.0, gap: 5.0 });
  // the engine decides at its 90th speech frame at the earliest: 9.0 + 0.032 + 89 x 0.016 = 10.456
  assert.deepEqual(feed(...levels(9.032, 10.456)), [], "not before the engine could have named another voice");
  const resumed = feed(...levels(10.488, 10.6));
  assert.deepEqual(resumed.map(i => [i.kind, i.voice, i.t]), [["voice_resumes", 1, 9.0]]);
  assert.deepEqual(feed(...levels(10.632, 12)), [], "only once");
  assert.equal(source.intents.at(-1).created, 42);
  assert.ok(FINAL_MARGIN_FRAMES >= 4 && FINAL_MARGIN_FRAMES <= 8, "a few frames past the engine's decision, not a noticeable delay");
});

test("the intents use the engine's own timing and the wearer's silence setting", () => {
  assert.deepEqual(ENGINE_TIMING, { frameSec: E.FRAME_SEC, vadOnFrames: E.TUNING.vadOnFrames, vadOnDb: E.TUNING.vadOnDb, vadAbsMin: E.TUNING.vadAbsMin,
    turnGapSec: E.TUNING.turnGapSec, finalFrames: E.TUNING.finalFrames, recheckEvery: E.TUNING.recheckEvery, recheckWindow: E.TUNING.recheckWindow,
    cueCooldownSec: E.DEFAULTS.cueCooldownSec, cueGapSec: E.DEFAULTS.cueGapSec });
  const source = new IntentSource({ silenceSec: 6 });
  assert.equal(source.silenceSec, 6);
  source.configure({ silenceSec: 8 });
  assert.equal(source.silenceSec, 8);
  // a 5 s gap is not a long silence when the wearer chose 8 s
  source.handle({ type: "speech-start", t: 0, gap: null });
  source.handle({ type: "level", t: 1 });
  source.handle({ type: "speaker", id: 1, isNew: true, t: 0 });
  source.handle({ type: "speech-end", t: 3 });
  source.handle({ type: "speech-start", t: 8, gap: 5 });
  assert.equal(source.resume, null);
  // the page's setting: the gap alone counts. The engine's own test runs one frame later than the
  // gap, so a gap one frame short of the setting is long, and two frames short is not.
  const passed = new IntentSource({ silenceSec: 5 });
  for (const e of [{ type: "speech-start", t: 0, gap: null }, { type: "speech-end", t: 3 }, { type: "speech-start", t: 7.968, gap: 4.968 }]) passed.handle(e);
  assert.equal(passed.resume, null);
  for (const e of [{ type: "speech-end", t: 9 }, { type: "speech-start", t: 13.984, gap: 4.984 }]) passed.handle(e);
  assert.deepEqual(passed.resume, { since: 13.984 });
  // a cue that agrees with it does not replace it
  for (const e of [{ type: "speech-end", t: 15 }, { type: "cue", kind: "silence", t: 20 }]) passed.handle(e);
  assert.equal(passed.silenceFrom, "page");
  // not told the setting: only the silence cue counts, and the cue shows the setting
  const unset = new IntentSource();
  assert.equal(unset.silenceSec, null);
  for (const e of [{ type: "speech-start", t: 0, gap: null }, { type: "speech-end", t: 3 }, { type: "speech-start", t: 8, gap: 5 }]) unset.handle(e);
  assert.equal(unset.resume, null, "a 5 s gap with no cue: the setting may be longer");
  unset.handle({ type: "speech-end", t: 9 });
  unset.handle({ type: "cue", kind: "silence", t: 14 });
  assert.equal(unset.silenceSec, 5);
  unset.handle({ type: "speech-start", t: 15, gap: 6 });
  assert.deepEqual(unset.resume, { since: 15 });
  unset.resume = null;
  // no cue this time: it would have come at 21, 7 s after the last, inside the engine's 8 s
  // cooldown, so the gap counts
  unset.handle({ type: "speech-end", t: 16 });
  unset.handle({ type: "speech-start", t: 21.5, gap: 5.5 });
  assert.deepEqual(unset.resume, { since: 21.5 });
  unset.resume = null;
  // a tone cue 2 s before the silence point: the engine's 3 s between any two cues held it back
  for (const e of [{ type: "speech-end", t: 23 }, { type: "cue", kind: "rise", t: 26 }, { type: "speech-start", t: 28.5, gap: 5.5 }]) unset.handle(e);
  assert.deepEqual(unset.resume, { since: 28.5 });
  unset.resume = null;
  // a silence that long with no cue and nothing to hold one back: the wearer changed the setting
  // (or switched the cue off). The gap stops counting until a cue shows the setting again.
  for (const e of [{ type: "speech-end", t: 30 }, { type: "speech-start", t: 36, gap: 6 }]) unset.handle(e);
  assert.equal(unset.resume, null);
  assert.equal(unset.silenceSec, null);
  for (const e of [{ type: "speech-end", t: 37 }, { type: "cue", kind: "silence", t: 45 }]) unset.handle(e);
  assert.equal(unset.silenceSec, 8);
  // a new session forgets a setting seen on the cue; the page's stays
  unset.reset();
  assert.equal(unset.silenceSec, null);
  source.reset();
  assert.equal(source.silenceSec, 8);
});

test("raising the silence setting mid-session does not leave the old one tapping", () => {
  const a = wav("198-209-0000");
  const seat = source => source.intents.filter(i => SEAT.has(i.kind)).map(i => [i.kind, i.voice]);
  // setting 4 s: the first 5 s pause shows it on the cue and taps. The wearer raises it to 8 s
  // during the next turn; the 5.5 s pause after that is not a long silence any more.
  const raise = (engine, source, page) => { engine.configure({ silenceSec: 8 }); if (page) source.configure({ silenceSec: 8 }); };
  // the page as it is (it does not tell the intents): the missing cue gives the change away
  const late = concat([quiet(0.6), a.subarray(0, 4 * S), quiet(5), a.subarray(4.5 * S, 9 * S), quiet(5.5), a.subarray(9.5 * S, 13.5 * S), quiet(1)]);
  const r1 = run(late, { settings: { silenceSec: 4 } }, [[12.5, (engine, source) => raise(engine, source, false)]]);
  assert.equal(r1.events.filter(e => e.type === "cue" && e.kind === "silence").length, 1);
  assert.deepEqual(seat(r1.source), [["new_voice", 1], ["voice_resumes", 1]]);
  // sooner after the cue the engine's cooldown could explain it, so the page passes the setting
  // (intents.configure next to engine.configure)
  const soon = concat([quiet(0.6), a.subarray(0, 4 * S), quiet(5), a.subarray(4.5 * S, 7 * S), quiet(5.5), a.subarray(8 * S, 12 * S), quiet(1)]);
  const r2 = run(soon, { settings: { silenceSec: 4 } }, [[12.5, (engine, source) => raise(engine, source, true)]], { silenceSec: 4 });
  assert.deepEqual(seat(r2.source), [["new_voice", 1], ["voice_resumes", 1]]);
});

test("after a long silence a different voice gets only its own tap, never the previous voice's seat first", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000");
  for (const sil of [4.5, 6]) {
    const cases = [
      // a voice never heard before: the new-voice taps only
      [[a.subarray(0, 8 * S), quiet(sil), b.subarray(0, 8 * S)], [["new_voice", 2]]],
      // a known voice comes back after B: its own seat, once (the engine's decision, sent as a resume)
      [[a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(sil), a.subarray(8 * S, 14 * S)], [["voice_resumes", 1]]],
      // the same voice goes on: the resume tap still plays
      [[a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S), quiet(sil), b.subarray(8 * S, 14 * S)], [["voice_resumes", 2]]],
      [[a.subarray(0, 8 * S), quiet(sil), a.subarray(8 * S, 13 * S)], [["voice_resumes", 1]]],
    ];
    for (const [parts, expected] of cases) {
      const { source, events } = run(concat([quiet(0.6), ...parts, quiet(2)]));
      assert.deepEqual(seatTapsAfterSilence(source, events), expected, `silence ${sil} s`);
    }
  }
});

test("the resume tap follows the silence itself, not the rate-limited, switchable silence cue", () => {
  const a = wav("198-209-0000");
  const silenceCues = events => events.filter(e => e.type === "cue" && e.kind === "silence").length;
  const resumes = source => source.intents.filter(i => i.kind === "voice_resumes").map(i => i.voice);
  const noCue = silenceSec => ({ settings: { silenceSec, cues: { drop: true, rise: true, hesitation: true, silence: false } } });
  // two long silences 6.5 s apart: the engine's 8 s cooldown swallows the second silence cue;
  // the first cue shows the setting even when the page has not passed it
  const twice = (sil, gap) => concat([quiet(0.6), a.subarray(0, 8 * S), quiet(sil), a.subarray(8 * S, 8 * S + gap * S), quiet(sil), a.subarray(10 * S, 13 * S), quiet(1)]);
  for (const silenceSec of [3, 4]) {
    const { source, events } = run(twice(silenceSec + 0.5, 2), { settings: { silenceSec } });
    assert.equal(silenceCues(events), 1);
    assert.deepEqual(resumes(source), [1, 1], `setting ${silenceSec} s`);
  }
  // "Long silence" unticked in Settings: no floor-open tick, the voice still taps when it starts again
  for (const silenceSec of [3, 4]) {
    const { source, events } = run(twice(silenceSec + 0.5, 2), noCue(silenceSec), [], { silenceSec });
    assert.equal(silenceCues(events), 0);
    assert.deepEqual(resumes(source), [1, 1], `setting ${silenceSec} s, cue off`);
  }
  // pauses shorter than the wearer's setting are not long silences, with the cue on or off
  for (const [settings, intentOptions] of [[{ silenceSec: 8 }, {}], [{ silenceSec: 8 }, { silenceSec: 8 }], [noCue(8).settings, { silenceSec: 8 }]]) {
    for (const pause of [4.5, 7]) {
      const { source, events } = run(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(pause), a.subarray(8 * S, 13 * S), quiet(1)]), { settings }, [], intentOptions);
      assert.equal(silenceCues(events), 0);
      assert.deepEqual(source.intents.filter(i => SEAT.has(i.kind)).map(i => i.kind), ["new_voice"], `setting 8 s, pause ${pause} s`);
    }
  }
});

test("a short noise after a long silence does not use up the tap for the real resumption", () => {
  const a = wav("198-209-0000");
  let r = 11; const noise = s => Float32Array.from({ length: Math.round(s * S) }, () => (((r = (r * 16807) % 2147483647) / 2147483647) * 2 - 1) * 0.1);
  for (const burst of [noise(0.3), noise(0.5), a.slice(9 * S, 9.3 * S)]) {
    const { source, events } = run(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(5), burst, quiet(0.5), a.subarray(10 * S, 14 * S), quiet(1)]));
    const real = events.filter(e => e.type === "speech-start" && e.gap != null && e.gap >= 0.4).at(-1);
    const taps = source.intents.filter(i => SEAT.has(i.kind) && i.t > 13);
    assert.deepEqual(taps.map(i => [i.kind, i.voice]), [["voice_resumes", 1]], "one tap, for the real turn");
    assert.ok(taps[0].t >= real.t - 1e-9, "dated at the real turn, not the noise");
    assert.ok(source.suppressed.some(s => s.turn < table.scheduler.min_turn_s), "the noise itself did not tap");
  }
});

test("speech back so soon after a short burst that the engine keeps one segment still gets its one tap", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000");
  let r = 5; const noise = s => Float32Array.from({ length: Math.round(s * S) }, () => (((r = (r * 16807) % 2147483647) / 2147483647) * 2 - 1) * 0.1);
  // 0.3 s of quiet after the burst: the engine's gap is 0.240 s, just under its 0.25 s segment gap,
  // so it judges the burst in the pause and the real turn goes on in the same segment
  // the noise case: the engine makes a voice from the noise and keeps it for A's speech, so that
  // tap waits for the engine's next decision; A stops instead, and it comes after REJUDGE_WAIT_SEC
  const cases = [[b.slice(9.1 * S, 9.3 * S), "voice_resumes", 1, false], [a.slice(9.1 * S, 9.45 * S), "voice_resumes", 1, false], [noise(0.45), "new_voice", 2, true]];
  for (const [burst, kind, voice, waits] of cases) {
    const { source, events, engine } = run(concat([quiet(0.6), a.subarray(0, 8 * S), quiet(6), burst, quiet(0.3), a.subarray(10 * S, 13.5 * S), quiet(1.5)]));
    const real = events.find(e => e.type === "speech-start" && e.t > 15 && e.gap < E.TUNING.turnGapSec);
    assert.ok(real && real.gap + E.FRAME_SEC >= E.TUNING.turnGapSec, "the speech came back one frame after the engine's pause check");
    const taps = source.intents.filter(i => SEAT.has(i.kind) && i.t > 14);
    assert.deepEqual(taps.map(i => [i.kind, i.voice]), [[kind, voice]], "one tap, for the voice the engine kept");
    assert.equal(engine.current, voice);
    assert.ok(taps[0].t >= real.t - 1e-9, "dated at the real turn");
    const end = events.filter(e => e.type === "speech-end").at(-1).t;
    if (waits) assert.ok(taps[0].at >= end + REJUDGE_WAIT_SEC && taps[0].at < end + REJUDGE_WAIT_SEC + 0.05, "sent once the quiet shows no next decision is coming");
    else assert.ok(taps[0].at < real.t + 2.5, "sent during the turn");
  }
});

test("a voice the engine made from a burst after the silence gets no tap before the engine gives the speaker back", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000");
  let r = 9; const noise = s => Float32Array.from({ length: Math.round(s * S) }, () => (((r = (r * 16807) % 2147483647) / 2147483647) * 2 - 1) * 0.1);
  // A, B, a long silence, 0.5 s of noise and 0.28 s of quiet (one segment again), then B goes on.
  // The engine makes voice 3 from the noise, learns it from B's speech, and names B again only at
  // its next segment: B's seat taps once, voice 3 never does. The same with two bursts, the
  // second running into B's speech (0.26 s: the engine's gap is under its pause check).
  const pre = [quiet(0.6), a.subarray(0, 8 * S), quiet(0.8), b.subarray(0, 8 * S)];
  for (const [sil, n, bursts] of [[4.5, 1, () => [noise(0.5), quiet(0.28)]], [6, 1, () => [noise(0.5), quiet(0.3)]], [4.5, 2, () => [noise(0.5), quiet(0.5), noise(0.5), quiet(0.26)]]]) {
    const { source, events } = run(concat([...pre, quiet(sil), ...bursts(), b.subarray(10 * S, 14 * S), quiet(1.5)]));
    assert.ok(events.some(e => e.type === "speaker" && e.id === 3 && e.isNew), "the engine made a voice from the noise");
    assert.deepEqual(seatTapsAfterSilence(source, events), [["voice_resumes", 2]], `silence ${sil} s, ${n} burst(s)`);
  }
});

test("New voice pressed in a pause taps at once, so the seat window opens", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000");
  let forced = null;
  // reader A, then a pause; the wearer presses N 0.6 s into it (after the engine's speech-end)
  const { source, events } = run(concat([quiet(0.6), a.subarray(0, 5 * S), quiet(1.2), b.subarray(0, 4 * S), quiet(1)]), {},
    [[6.2, engine => { assert.equal(engine.speaking, false); forced = { id: engine.forceNewSpeaker(), t: engine.t }; }]]);
  assert.ok(events.some(e => e.type === "speech-end" && e.t < forced.t));
  const tap = source.intents.find(i => i.voice === forced.id);
  assert.ok(tap && tap.kind === "new_voice" && tap.at === forced.t, "the new-voice intent is sent at the press");
  assert.ok(!source.suppressed.some(s => s.voice === forced.id), "a press is not a back-channel");
  // an engine decision about speech already heard is still held to the back-channel rule
  const s2 = new IntentSource({ minTurn: 0.6 });
  for (const e of [{ type: "speech-start", t: 0 }, { type: "level", t: 1 }, { type: "speaker", id: 1, isNew: true, t: 0 }, { type: "speech-end", t: 5 },
    { type: "speech-start", t: 5.3 }, { type: "speech-end", t: 5.75 }, { type: "level", t: 5.8, speaking: false }]) s2.handle(e);
  assert.deepEqual(s2.handle({ type: "speaker", id: 2, isNew: true, t: 5.3 }), []);
  assert.deepEqual(s2.handle({ type: "speaker", id: 3, isNew: true, t: 5.8 }).map(i => [i.kind, i.voice]), [["new_voice", 3]], "stamped now: a press");
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
