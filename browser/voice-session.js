// Sanket voice analysis wherever Audial-AI has the audio: the companion page (shared tab /
// microphone) and the extension's offscreen tab capture both feed PCM here.
//
// It runs Sanket's voice engine (browser/sanket/engine.js, loaded as a classic script so the
// same file also runs under Node for tests and training) and sends small batches of events to
// the local app, which stores them with the session and republishes them to every open page:
//   {kind:"voice", t, id, new}                       who is speaking changed (audio time, s)
//   {kind:"cue",   t, cue, voice}                    drop | rise | hesitation | silence
//   {kind:"tone",  t0, t1, voice, relative, label, confidence}
// Audio times count from the first sample of the capture, the same clock as caption times.

export const CUE_KINDS = ["drop", "rise", "hesitation", "silence"];
const MAX_BATCH = 200; // matches the companion's validated event limit

const round = (value, digits = 2) => Math.round(value * 10 ** digits) / 10 ** digits;

// Engine event → wire event (or null). Tone categories are sent only when Sanket is confident
// enough to name them; everything else is "uncertain".
export function compactEvent(event) {
  if (!event) return null;
  if (event.type === "speaker") return {kind: "voice", t: round(event.t), id: event.id, new: Boolean(event.isNew)};
  if (event.type === "cue" && CUE_KINDS.includes(event.kind)) {
    return {kind: "cue", t: round(event.t), cue: event.kind, voice: event.speakerId ?? null};
  }
  if (event.type === "tone") {
    return {kind: "tone", t0: round(event.t0), t1: round(event.t1), voice: event.speakerId,
      relative: event.relative, label: event.accepted ? event.label : "uncertain",
      confidence: event.accepted ? round(event.confidence, 3) : null};
  }
  return null;
}

export function engineSettings(settings = {}) {
  const cues = Boolean(settings.cues);
  return {singleSpeaker: false, maxSpeakers: 6,
    cues: {drop: cues, rise: cues, hesitation: cues, silence: cues}};
}

export class VoiceSession {
  constructor({send, settings = {}, model = null, lib = globalThis.SanketEngine, flushMs = 400,
    maxQueue = 500, onError = () => {}, setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = id => clearTimeout(id)} = {}) {
    if (!lib?.VoiceEngine) throw new Error("Sanket's voice engine is not loaded.");
    this.lib = lib; this.send = send; this.settings = {...settings}; this.model = model;
    this.flushMs = flushMs; this.maxQueue = maxQueue; this.onError = onError;
    this.setTimer = setTimer; this.clearTimer = clearTimer;
    this.engine = null; this.queue = []; this.timer = 0; this.sending = Promise.resolve(); this.ready = false; this.flushing = false;
  }
  get enabled() { return Boolean(this.settings.colors || this.settings.cues || this.settings.tone); }
  get t() { return this.engine ? this.engine.t : 0; }

  // Engine starts on the first audio block, at that block's sample rate.
  feed(samples, sampleRate) {
    if (!this.enabled) return;
    if (!this.engine) {
      this.engine = new this.lib.VoiceEngine({sampleRate, settings: engineSettings(this.settings),
        toneModel: this.settings.tone ? this.model : null, onEvent: event => this.push(compactEvent(event))});
    }
    this.engine.process(samples);
  }
  configure(settings) {
    this.settings = {...this.settings, ...settings};
    if (!this.engine) return;
    this.engine.configure(engineSettings(this.settings));
    this.engine.setToneModel(this.settings.tone ? this.model : null);
  }
  setModel(model) {
    this.model = model;
    if (this.engine && this.settings.tone) this.engine.setToneModel(model);
  }
  push(event) {
    if (!event) return;
    if (this.queue.length >= this.maxQueue) this.queue.shift();
    this.queue.push(event);
    // cues are worth sending at once; the rest can ride in the next batch
    if (event.kind === "cue" && this.ready) this.flush();
    else if (!this.timer && this.ready) this.timer = this.setTimer(() => {this.timer = 0; this.flush();}, this.flushMs);
  }
  // Events wait until the local app has a session to file them under.
  open() { this.ready = true; if (this.queue.length) this.flush(); }
  flush() {
    if (this.timer) {this.clearTimer(this.timer); this.timer = 0;}
    if (!this.queue.length || !this.ready || this.flushing) return this.sending;
    this.flushing = true;
    // Keep unsent events in the bounded queue, rather than retaining a new
    // promise closure for every cue while the connection is slow.
    this.sending = Promise.resolve().then(async () => {
      try {
        while (this.ready && this.queue.length) {
          const batch = this.queue.splice(0, MAX_BATCH);
          try { await this.send(batch); }
          catch (error) { this.onError(error); }
        }
      } finally { this.flushing = false; }
    });
    return this.sending;
  }
  // Estimate whatever was still being said, then deliver everything.
  async stop() {
    if (this.engine) this.engine.flushTone();
    this.ready = true;
    await this.flush();
    this.engine = null;
  }
}
