/*
 * Kandha intents: engine events -> what the stole should be asked to do.
 * ----------------------------------------------------------------------
 * Pure JavaScript, no DOM, no timers: everything is driven by the engine's own audio clock, so
 * the same code runs live in the page and over recorded fixtures in Node (tests/kandha.test.js,
 * scripts/kandha_tap_budget.mjs).
 *
 * Input:  events from browser/sanket/engine.js (speaker, speech-start, speech-end, cue, level)
 * Output: intents for app/kandha/scheduler.py:
 *   {kind:'speaker',       voice, t}        a known voice starts or takes over (after the hold)
 *   {kind:'new_voice',     voice, t}        a voice never heard before (two taps at the front)
 *   {kind:'voice_resumes', voice, t}        the same voice starts again after a long silence
 *   {kind:'cue', cue,      voice, t}        drop | rise | hesitation
 *   {kind:'silence',       t}               long silence: the floor is open
 *
 * The back-channel hold (decision 0004): a speaker decision taps only once the turn has lasted
 * minTurn seconds. If the turn ended before that ("mm-hm"), nothing is sent; the screen still
 * shows the colour, because the page draws from engine events, not from intents.
 */
(function (root) {
  'use strict';

  const DEFAULT_RULES = { min_turn_s: 0.6 };

  class IntentSource {
    constructor(opts) {
      opts = opts || {};
      this.minTurn = opts.minTurn != null ? opts.minTurn : DEFAULT_RULES.min_turn_s;
      this.onIntent = opts.onIntent || function () {};
      this.wall = opts.wall || (() => (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000);
      this.reset();
    }

    reset() {
      this.engineT = 0;          // latest audio time seen on any event
      this.speaking = false;
      this.lastSpeechStart = null;
      this.lastSpeechEnd = null;
      this.current = null;       // the engine's current voice
      this.hold = null;          // {voice, isNew, t, due} a speaker decision waiting for the turn to reach minTurn
      this.resume = null;        // {voice, due} a "voice starts again" tap waiting after a long silence
      this.silenceFired = false; // a silence cue happened since the last speech
      this.intents = [];         // everything emitted (the measurement scripts read this)
      this.suppressed = [];      // back-channels that did not tap
    }

    // Turn length known now: still speaking -> now - start; after a pause -> end - start.
    turnLength(t) {
      const end = (this.speaking || this.lastSpeechEnd == null || this.lastSpeechEnd < t) ? this.engineT : this.lastSpeechEnd;
      return Math.max(0, end - t);
    }

    emit(intent) {
      intent.created = this.wall();
      this.intents.push(intent);
      this.onIntent(intent);
      return intent;
    }

    // Feed one engine event. Returns the intents emitted for it (usually none or one).
    handle(e) {
      const before = this.intents.length;
      if (e.t != null && e.t > this.engineT) this.engineT = e.t;
      switch (e.type) {
        case 'speech-start':
          this.speaking = true;
          this.lastSpeechStart = e.t;
          if (this.silenceFired && this.current != null) this.resume = { voice: this.current, due: e.t + this.minTurn };
          this.silenceFired = false;
          break;
        case 'speech-end':
          this.speaking = false;
          this.lastSpeechEnd = e.t;
          // a decision still on hold whose turn ended short is a back-channel
          if (this.hold && e.t - this.hold.t < this.minTurn) { this.suppressed.push(Object.assign({ reason: 'back-channel', turn: +(e.t - this.hold.t).toFixed(3) }, this.hold)); this.hold = null; }
          if (this.resume && e.t < this.resume.due) this.resume = null;
          break;
        case 'speaker': {
          this.current = e.id;
          this.resume = null;          // a decision supersedes "the same voice continues"
          const turn = this.turnLength(e.t);
          const intent = { kind: e.isNew ? 'new_voice' : 'speaker', voice: e.id, t: e.t, new: !!e.isNew };
          if (turn >= this.minTurn) { this.hold = null; this.emit(intent); }
          else if (this.speaking && (this.lastSpeechEnd == null || this.lastSpeechEnd < e.t || this.lastSpeechStart >= e.t)) {
            this.hold = { voice: e.id, isNew: !!e.isNew, t: e.t, due: e.t + this.minTurn };
          } else {
            this.hold = null;
            this.suppressed.push(Object.assign({ reason: 'back-channel', turn: +turn.toFixed(3) }, intent));
          }
          break;
        }
        case 'cue':
          if (e.kind === 'silence') { this.silenceFired = true; this.emit({ kind: 'silence', t: e.t, voice: null }); }
          else if (e.kind === 'drop' || e.kind === 'rise' || e.kind === 'hesitation') this.emit({ kind: 'cue', cue: e.kind, voice: e.speakerId == null ? null : e.speakerId, t: e.t });
          break;
        default:
          break;
      }
      this.settle();
      return this.intents.slice(before);
    }

    // Holds and resumes are released by the engine clock, not by wall timers.
    settle() {
      if (this.hold && this.engineT >= this.hold.due) {
        const h = this.hold; this.hold = null;
        if (this.speaking && this.current === h.voice) this.emit({ kind: h.isNew ? 'new_voice' : 'speaker', voice: h.voice, t: h.t, new: h.isNew });
      }
      if (this.resume && this.engineT >= this.resume.due) {
        const r = this.resume; this.resume = null;
        if (this.speaking && this.current === r.voice) this.emit({ kind: 'voice_resumes', voice: r.voice, t: this.lastSpeechStart == null ? r.due - this.minTurn : this.lastSpeechStart });
      }
    }

    // The engine says who is speaking; the page can also force it (New voice button, "this person is speaking now").
    setCurrent(id) { this.current = id; }
  }

  const api = { IntentSource, DEFAULT_RULES };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.KandhaIntents = api;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
