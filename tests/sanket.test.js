// Sanket voice view inside Audial-AI: the browser tone model must reproduce its training
// results, stay quiet on natural calm speech, and the shared capture pieces must keep one clock.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { VoiceSession, compactEvent } from "../browser/voice-session.js";
import { VoiceTimeline } from "../browser/voice-view.js";

const require = createRequire(import.meta.url);
const E = require("../browser/sanket/engine.js");
const Tone = require("../browser/sanket/tone.js");
const { CaptionAssembler } = require("../browser/sanket/captions.js");
const LocalCaptions = require("../browser/sanket/local-captions.js");
const read = path => readFileSync(new URL(path, import.meta.url));
const model = JSON.parse(read("../models/sanket/tone_model.json"));
const fixture = JSON.parse(read("./fixtures/sanket/crema_test_features.json")).rows;
const filled = x => x.map(v => (v == null ? NaN : v));

function wav(name) {
  const b = read(`./fixtures/sanket/${name}.wav`);
  let o = 12;
  while (b.toString("ascii", o, o + 4) !== "data") o += 8 + b.readUInt32LE(o + 4);
  const n = b.readUInt32LE(o + 4) / 2, x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = b.readInt16LE(o + 8 + i * 2) / 32768;
  return x;
}
const concat = parts => { const out = new Float32Array(parts.reduce((a, p) => a + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
const quiet = seconds => Float32Array.from({length: Math.round(seconds * 16000)}, () => (Math.random() * 2 - 1) * 3e-4);
const gain = (x, db) => x.map(v => v * 10 ** (db / 20));
function run(signal, options = {}) {
  const events = [];
  const engine = new E.VoiceEngine({onEvent: e => { if (e.type !== "level") events.push(e); }, ...options});
  for (let i = 0; i < signal.length; i += 128) engine.process(signal.subarray(i, i + 128));
  engine.flushTone();
  return events;
}

test("browser tone inference reproduces the training report on the ten held-out actors", () => {
  let right = 0;
  for (const row of fixture) {
    const p = Tone.runNet(model.general, filled(row.x));
    if (model.labels[p.indexOf(Math.max(...p))] === row.e) right++;
  }
  assert.equal(fixture.length, 814);
  assert.ok(Math.abs(right / fixture.length - model.evaluation.general_test_accuracy) < 0.006);
});

test("after a calm warm-up, named estimates are rare, nearly always right and never overclaim", () => {
  let n = 0, ok = 0, shown = 0, shownOk = 0, stated = 0;
  for (let rep = 0; rep < 5; rep++) {
    let seed = 11 + rep; const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const actors = {};
    for (const row of fixture) (actors[row.a] ??= []).push(row);
    for (const rows of Object.values(actors)) {
      const order = rows.slice().sort(() => random() - 0.5);
      const warm = order.filter(r => r.e === "neutral").slice(0, 6).concat(order.filter(r => r.e !== "neutral").slice(0, 2));
      const estimator = new Tone.Estimator(model);
      for (const r of warm) estimator.estimateFeatures(1, filled(r.x), 2);
      for (const r of order.filter(r => !warm.includes(r))) {
        const e = estimator.estimateFeatures(1, filled(r.x), 2);
        n++; if (e.guess === r.e) ok++;
        if (e.accepted) { shown++; stated += e.confidence; if (e.guess === r.e) shownOk++; }
      }
    }
  }
  assert.ok(ok / n > 0.5, `best guess ${ok / n}`);
  assert.ok(shownOk / shown > 0.9, `named right ${shownOk / shown}`);
  assert.ok(stated / shown <= shownOk / shown + 0.03, "stated confidence must not exceed accuracy");
});

test("natural calm reading: almost no named emotions and no voice rose or softened cues", () => {
  let stretches = 0, named = 0, cues = 0, minutes = 0;
  for (const name of ["198-209-0000", "3436-172162-0000", "5703-47212-0000"]) {
    const x = wav(name);
    const signal = concat([0, -2, 2, -1, 1].map(db => gain(x, db)));
    minutes += signal.length / 16000 / 60;
    for (const e of run(signal, {toneModel: model, settings: {singleSpeaker: true}})) {
      if (e.type === "tone" && e.personal) { stretches++; if (e.accepted && e.label !== "neutral") named++; }
      if (e.type === "cue" && (e.kind === "rise" || e.kind === "drop")) cues++;
    }
  }
  assert.ok(stretches > 40, `${stretches} stretches`);
  assert.ok(named <= stretches / 20, `${named} named of ${stretches}`);
  assert.ok(cues <= minutes, `${cues} cues in ${minutes.toFixed(1)} min`);
});

test("two readers get two voices and tone estimates never straddle the change", () => {
  const a = wav("198-209-0000").subarray(0, 12 * 16000), b = wav("3436-172162-0000").subarray(0, 10 * 16000);
  const events = run(concat([quiet(0.5), a, quiet(1), b, quiet(1)]), {toneModel: model});
  const voices = new Set(events.filter(e => e.type === "speaker").map(e => e.id));
  const tones = events.filter(e => e.type === "tone");
  assert.equal(voices.size, 2);
  assert.ok(tones.length >= 4);
  assert.ok(tones.every(e => !(e.t0 < 13.3 && e.t1 > 13.7)));
  assert.ok(tones.filter(e => !e.personal).every(e => !e.accepted), "first meetings are never named");
});

test("a reader who comes back into the conversation gets their colour back", () => {
  const a = wav("198-209-0000"), b = wav("3436-172162-0000"), s = 16000;
  const signal = concat([quiet(0.6), a.subarray(0, 8 * s), quiet(0.8), b.subarray(0, 8 * s), quiet(0.8), a.subarray(8 * s, 13 * s), quiet(0.8), b.subarray(8 * s, 14 * s), quiet(1)]);
  const turns = run(signal).filter(e => e.type === "speaker").map(e => e.id);
  assert.deepEqual(turns, [1, 2, 1, 2]);
});

test("a much quieter voice still gives 'voice softened' once the model is in charge", () => {
  const b = wav("3436-172162-0000");
  const signal = concat([quiet(0.8), b.subarray(0, 16 * 16000), b.subarray(0, 4 * 16000), gain(b.subarray(4 * 16000, 12 * 16000), -12), quiet(1)]);
  const events = run(signal, {toneModel: model, settings: {singleSpeaker: true}});
  const start = 20.8;
  assert.ok(events.some(e => e.type === "cue" && e.kind === "drop" && e.t >= start && e.t < start + 6));
});

test("voice sessions hold events until the app has a session, send cues at once and finish the last estimate", async () => {
  const sent = [], timers = [];
  const session = new VoiceSession({lib: E, model, settings: {colors: true, cues: true, tone: true},
    send: async batch => { sent.push(batch); }, setTimer: fn => { timers.push(fn); return timers.length; }, clearTimer: () => {}});
  const signal = concat([quiet(0.5), wav("198-209-0000").subarray(0, 6 * 16000)]);
  for (let i = 0; i < signal.length; i += 1024) session.feed(signal.subarray(i, i + 1024), 16000);
  assert.equal(sent.length, 0, "nothing is sent before open()");
  session.open(); await session.sending;
  assert.ok(sent.flat().some(e => e.kind === "voice" && e.id === 1));
  session.push({kind: "cue", t: 3, cue: "rise", voice: 1}); await session.sending;
  assert.deepEqual(sent.at(-1), [{kind: "cue", t: 3, cue: "rise", voice: 1}]);
  await session.stop();
  const tones = sent.flat().filter(e => e.kind === "tone");
  assert.ok(tones.length >= 1);
  assert.ok(tones.every(t => (t.label === "uncertain") === (t.confidence === null)));
  const off = new VoiceSession({lib: E, settings: {}, send: async () => assert.fail("disabled sessions send nothing")});
  off.feed(signal, 16000); assert.equal(off.engine, null);
});

test("only confident estimates carry a category over the wire", () => {
  const base = {type: "tone", t0: 1, t1: 2.5, speakerId: 2, relative: "softer", label: "sad", confidence: 0.62, accepted: false};
  assert.deepEqual(compactEvent(base), {kind: "tone", t0: 1, t1: 2.5, voice: 2, relative: "softer", label: "uncertain", confidence: null});
  assert.equal(compactEvent({...base, accepted: true, confidence: 0.86}).label, "sad");
  assert.equal(compactEvent({type: "level"}), null);
});

test("the audio worklet's optional tap shares the upload clock", () => {
  let Collector; const sent = [];
  const environment = {sampleRate: 16000, Float32Array, AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => sent.push(m)}; } }, registerProcessor: (_, value) => { Collector = value; }};
  runInNewContext(readFileSync(new URL("../browser/pcm-worklet.js", import.meta.url), "utf8"), environment);
  const tapped = new Collector({processorOptions: {tap: true}});
  for (let i = 0; i < 300; i++) tapped.process([[new Float32Array(128).fill(0.1)]]);
  const taps = sent.filter(m => m.type === "tap"), packets = sent.filter(m => m.samples && m.type !== "tap");
  assert.equal(taps.length, Math.floor(300 * 128 / 1024));
  assert.ok(taps.every(m => m.samples.length === 1024 && m.sampleRate === 16000));
  assert.equal(packets[0].startSample, 0); assert.equal(packets[0].samples.length, 32000);
});

test("captions are attributed to the voice heard longest and tone notes follow the same person", () => {
  const timeline = new VoiceTimeline();
  timeline.add([{kind: "voice", t: 0, id: 1}, {kind: "voice", t: 4, id: 2},
    {kind: "tone", t0: 4.2, t1: 6, voice: 2, relative: "usual", label: "uncertain", confidence: null},
    {kind: "tone", t0: 4.1, t1: 7, voice: 2, relative: "intense", label: "angry", confidence: 0.9}]);
  assert.equal(timeline.voiceFor(3.5, 7), 2);
  assert.equal(timeline.voiceFor(1, 4.5), 1);
  assert.equal(timeline.toneFor(4, 7, 2).label, "angry");
  assert.equal(timeline.toneFor(0, 3, 1), null);
});

test("timed local captions give each word the voice speaking at that moment", () => {
  const assembler = new CaptionAssembler();
  assembler.speakerChange(0, 1); assembler.speakerChange(2, 2);
  const pieces = assembler.timed("one two three four five six seven eight", 0, 4);
  assert.deepEqual(pieces.map(p => [p.speakerId, p.text]), [[1, "one two three four"], [2, "five six seven eight"]]);
});

test("local captions send ordered, timestamped packets and deliver timed captions", async () => {
  const calls = [], captions = [];
  let polled = false;
  const reply = (status, body) => ({ok: status < 300, status, json: async () => body});
  const fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (url === "/api/status") return reply(200, {asr_installed: true, asr_model: "whisper-tiny", running: false});
    if (url === "/api/start") return reply(200, {session_id: "s1", cursor: 5});
    if (url === "/api/audio") return reply(200, {queued: true});
    if (url === "/api/stop") return reply(200, {ok: true});
    if (url.startsWith("/api/events")) {
      if (polled) return reply(200, {events: [], cursor: 6});
      polled = true;
      return reply(200, {cursor: 6, events: [{kind: "caption", data: {text: "Hello there", start: 0.5, end: 1.4, speaker: "Unattributed"}}]});
    }
    return reply(404, {error: "no"});
  };
  const local = new LocalCaptions({onFinal: (text, meta) => captions.push([text, meta.start, meta.end]), onError: (code, message) => assert.fail(message)}, {fetch});
  assert.equal(await local.start({lang: "hi"}), true);
  assert.equal(JSON.parse(calls.find(c => c.url === "/api/start").options.body).language, "hi");
  for (let i = 0; i < 5; i++) local.feed(new Float32Array(16000), 16000);
  await local.stop(); local.generation++;
  const starts = calls.filter(c => c.url === "/api/audio").map(c => Number(c.options.headers["X-Audio-Start-Seconds"]));
  assert.deepEqual(starts, [0, 2, 4]);
  assert.ok(calls.filter(c => c.url === "/api/audio").every(c => c.options.headers["X-Session-ID"] === "s1"));
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.deepEqual(captions, [["Hello there", 0.5, 1.4]]);
});
