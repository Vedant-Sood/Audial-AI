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

test("voice events stay bounded behind a slow request and use accepted batch sizes", async () => {
  const sent = [];
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const session = new VoiceSession({lib: E, settings: {cues: true}, maxQueue: 500,
    send: async batch => { sent.push(batch); if (sent.length === 1) await blocked; }});
  session.open();
  session.push({kind: "cue", t: 0, cue: "rise", voice: 1});
  await Promise.resolve();
  for (let i = 1; i <= 1000; i++) session.push({kind: "cue", t: i, cue: "rise", voice: 1});
  assert.equal(sent.length, 1, "only one request may be in flight");
  assert.equal(session.queue.length, 500, "pending events stay in the bounded queue");
  release();
  await session.stop();
  assert.ok(sent.every(batch => batch.length <= 200), "the companion accepts at most 200 events per request");
  assert.deepEqual(sent.flat().map(event => event.t), [0, ...Array.from({length: 500}, (_, i) => i + 501)]);
});

test("voice events buffered before session creation are split without losing their order", async () => {
  const sent = [];
  const session = new VoiceSession({lib: E, send: async batch => sent.push(batch)});
  for (let i = 0; i < 450; i++) session.push({kind: "voice", t: i, id: 1});
  session.open();
  await session.stop();
  assert.deepEqual(sent.map(batch => batch.length), [200, 200, 50]);
  assert.deepEqual(sent.flat().map(event => event.t), Array.from({length: 450}, (_, i) => i));
});

test("a failed voice event request does not prevent later batches", async () => {
  const sent = [], errors = [];
  const session = new VoiceSession({lib: E, onError: error => errors.push(error.message),
    send: async batch => { sent.push(batch); if (sent.length === 1) throw new Error("disconnected"); }});
  for (let i = 0; i < 201; i++) session.push({kind: "voice", t: i, id: 1});
  session.open();
  await session.stop();
  assert.deepEqual(errors, ["disconnected"]);
  assert.deepEqual(sent.map(batch => batch.length), [200, 1]);
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

const localReply = body => ({ok: true, status: 200, json: async () => body});
const nextTurn = () => new Promise(resolve => setImmediate(resolve));

test("stopping local captions while status is pending cancels startup", async () => {
  let release;
  const calls = [];
  const local = new LocalCaptions({}, {fetch: url => {
    calls.push(url);
    return new Promise(resolve => { release = resolve; });
  }});
  const starting = local.start();
  await local.stop();
  release(localReply({asr_installed: true, running: false}));
  await nextTurn();
  assert.deepEqual(calls, ["/api/status"], "a cancelled start must never open a capture session");
  assert.equal(await starting, false);
  assert.equal(local.active, false);
});

test("stopping local captions during session creation releases only that late session", async () => {
  let release;
  const calls = [];
  const local = new LocalCaptions({}, {fetch: async (url, options) => {
    calls.push([url, options]);
    if (url === "/api/status") return localReply({asr_installed: true, running: false});
    if (url === "/api/start") return new Promise(resolve => { release = resolve; });
    return localReply({ok: true});
  }});
  const starting = local.start();
  await nextTurn();
  await local.stop();
  release(localReply({session_id: "cancelled-session"}));
  assert.equal(await starting, false);
  await nextTurn();
  assert.deepEqual(JSON.parse(calls.find(([url]) => url === "/api/stop")[1].body), {session_id: "cancelled-session"});
  assert.equal(local.active, false);
  assert.equal(local.session, null);
});

test("repeated local-caption stops keep the final-caption polling generation", async () => {
  const local = new LocalCaptions({}, {fetch: async url => localReply(url === "/api/status"
    ? {asr_installed: true, running: false} : {session_id: "draining", cursor: 0})});
  local._poll = async () => {};
  await local.start();
  const generation = local.generation;
  const stopping = local.stop();
  assert.equal(local.stop(), stopping, "concurrent stops share the same cleanup");
  await stopping;
  await local.stop();
  assert.equal(local.generation, generation, "final captions can still arrive after stop");
});

test("stopping local captions drains a full upload queue before sending the final partial packet", async () => {
  const starts = [];
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const local = new LocalCaptions({onError: (_, message) => assert.fail(message)}, {fetch: async (url, options) => {
    if (url === "/api/status") return localReply({asr_installed: true, running: false});
    if (url === "/api/start") return localReply({session_id: "final-packet", cursor: 0});
    if (url === "/api/audio") {
      starts.push(Number(options.headers["X-Audio-Start-Seconds"]));
      if (starts.length === 1) await blocked;
    }
    return localReply({ok: true});
  }});
  local._poll = async () => {};
  await local.start();
  for (let i = 0; i < 7; i++) local.feed(new Float32Array(16000), 16000);
  const stopping = local.stop();
  assert.equal(await local.start(), false, "restart waits for the previous session cleanup");
  release();
  await stopping;
  assert.deepEqual(starts, [0, 2, 4, 6]);
});

test("local captions reject duplicate starts and bound slow audio uploads without compressing time", async () => {
  const calls = [], errors = [];
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const local = new LocalCaptions({onError: (code, message) => errors.push([code, message])}, {fetch: async (url, options) => {
    calls.push([url, options]);
    if (url === "/api/status") return localReply({asr_installed: true, running: false});
    if (url === "/api/start") return localReply({session_id: "bounded", cursor: 0});
    if (url === "/api/audio" && calls.filter(([path]) => path === url).length === 1) await blocked;
    return localReply({ok: true});
  }});
  local._poll = async () => {};
  assert.equal(await local.start(), true);
  assert.equal(await local.start(), false);
  for (let i = 0; i < 8; i++) local.feed(new Float32Array(32000), 16000);
  await nextTurn();
  assert.equal(calls.filter(([url]) => url === "/api/audio").length, 1);
  assert.equal(errors.length, 5, "excess packets report their gaps instead of accumulating audio");
  release();
  await local.sending;
  local.feed(new Float32Array(32000), 16000);
  await local.stop();
  assert.deepEqual(calls.filter(([url]) => url === "/api/audio").map(([, options]) => Number(options.headers["X-Audio-Start-Seconds"])), [0, 2, 4, 16]);
  assert.ok(calls.every(([, options]) => options?.signal), "requests have bounded timeouts");
  assert.equal(local.session, null);
});
