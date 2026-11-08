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
 *   {kind:'voice_resumes', voice, t}        the voice speaking takes the first real turn after a long silence
 *   {kind:'cue', cue,      voice, t}        drop | rise | hesitation
 *   {kind:'silence',       t}               long silence: the floor is open
 *
 * The back-channel hold (decision 0004): a speaker decision taps only once the turn has lasted
 * minTurn seconds. If the turn ended before that ("mm-hm"), nothing is sent; the screen still
 * shows the colour, because the page draws from engine events, not from intents.
 *
 * After a long silence the next real turn taps once. A silence is long when the engine's silence
 * cue fires, or when the speech-start gap reaches the wearer's "a silence counts as long after"
 * setting. The page passes that setting (constructor or configure()); until it does, it is
 * measured from the engine's own silence cue, and forgotten again when a later silence that long
 * brings no cue and the engine's cue limits (8 s per kind, 3 s between any two) do not explain
 * why: the setting has changed, or the cue was switched off.
 * The engine reports a speaker only when it changes, so for the same voice nothing else would
 * tap: the resume fills that gap. It waits until the engine has had its final say on the turn
 * (its 90th speech frame, or the pause that ends a shorter turn), so a different voice only ever
 * gets its own tap. A turn shorter than minTurn (a cough, an "mm") does not use it up. When the
 * speech comes back so soon after such a burst that the engine keeps one segment, the engine has
 * already judged it; the resume then waits for the engine's first chance to correct itself
 * (its mid-turn recheck) or the pause that ends the turn. If the voice it kept is one it made
 * from a burst after the silence, it learns that voice from the speech that follows and cannot
 * reject it there, so the tap waits for its decision on the next segment, or REJUDGE_WAIT_SEC of
 * quiet. A known voice the engine decides in the first turn is sent as voice_resumes too, so the
 * scheduler taps it even when it was the last voice tapped before the silence (for example after
 * the wearer's own voice, never tapped).
 *
 * Only the New voice control (engine.forceNewSpeaker) makes a new-voice decision stamped with
 * the present moment; the engine's own new voices carry the start of speech already heard. So a
 * new-voice event that is not in the past is a press, and taps at once, even in a pause. Other
 * page controls ("this person is speaking now", Join voices) and the engine's own first
 * Lecture-mode decision follow the back-channel rule as before.
 */
(function (root) {
  'use strict';

  const DEFAULT_RULES = { min_turn_s: 0.6 };
  // The engine's timing (browser/sanket/engine.js TUNING, FRAME_SEC); read from the engine when
  // it is loaded, so these decisions line up with its own.
  const ENGINE_TIMING = { frameSec: 0.016, vadOnFrames: 3, vadOnDb: 10, vadAbsMin: -62, turnGapSec: 0.25, finalFrames: 90, recheckEvery: 32, recheckWindow: 90, cueCooldownSec: 8, cueGapSec: 3 };
  // The resume waits this many speech frames past the engine's final decision: the count below
  // is rebuilt from level events (every second frame) and ran at most 3 frames ahead of the
  // engine's over the LibriSpeech fixtures, also chopped, softened and with added noise.
  const FINAL_MARGIN_FRAMES = 6;
  // A voice the engine made from a short burst after the silence, kept for the speech that went
  // on in the same segment, waits for the engine's next decision; after this much quiet it taps.
  const REJUDGE_WAIT_SEC = 1.0;

  function engineTiming() {
    const out = Object.assign({}, ENGINE_TIMING);
    const E = root.SanketEngine;
    if (E && E.TUNING) {
      for (const k of ['vadOnFrames', 'vadOnDb', 'vadAbsMin', 'turnGapSec', 'finalFrames', 'recheckEvery', 'recheckWindow']) if (typeof E.TUNING[k] === 'number') out[k] = E.TUNING[k];
      if (typeof E.FRAME_SEC === 'number') out.frameSec = E.FRAME_SEC;
      for (const k of ['cueCooldownSec', 'cueGapSec']) if (E.DEFAULTS && typeof E.DEFAULTS[k] === 'number') out[k] = E.DEFAULTS[k];
    }
    return out;
  }

  // The engine's first chance to switch voices in a segment it judged at n0 speech frames: it
  // rechecks every recheckEvery frames once the segment holds recheckWindow frames, and switches
  // on the second miss in a row. The count here may run a few frames ahead of the engine's, so
  // take the latest switch point over that range.
  function firstSwitchFrames(n0, T) {
    let latest = 0;
    for (let n = Math.max(1, n0 - FINAL_MARGIN_FRAMES); n <= n0; n++) {
      latest = Math.max(latest, n + T.recheckEvery * (Math.max(1, Math.ceil((T.recheckWindow - n) / T.recheckEvery)) + 1));
    }
    return latest;
  }

  class IntentSource {
    constructor(opts) {
      opts = opts || {};
      this.minTurn = opts.minTurn != null ? opts.minTurn : DEFAULT_RULES.min_turn_s;
      this.onIntent = opts.onIntent || function () {};
      this.wall = opts.wall || (() => (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000);
      this.timing = engineTiming();
      // the engine's silenceSec (the wearer's "a silence counts as long after"): passed by the page,
      // or measured from the engine's silence cue. Unknown until then: only the cue counts.
      this.silenceSec = null;
      this.silenceFrom = null;   // 'page' | 'cue'
      this.configure(opts);
      this.reset();
    }

    // The page passes the engine's settings so "a long silence" means the same to both.
    configure(opts) {
      if (opts && opts.silenceSec != null && +opts.silenceSec > 0) { this.silenceSec = +opts.silenceSec; this.silenceFrom = 'page'; }
    }

    reset() {
      // a setting measured from the cue may have changed by the next session; the page's stays
      if (this.silenceFrom !== 'page') { this.silenceSec = null; this.silenceFrom = null; }
      this.lastCueT = null;      // the engine's cue limits, mirrored from its cue events
      this.lastCueByKind = {};
      this.engineT = 0;          // latest audio time seen on any event
      this.speaking = false;
      this.lastSpeechStart = null;
      this.lastSpeechEnd = null;
      this.current = null;       // the engine's current voice
      this.hold = null;          // {voice, isNew, t, due} a speaker decision waiting for the turn to reach minTurn
      // {since, born (new voices decided after it and held back), wait ({voice, t}: see judge)}
      // after a long silence: the next real turn taps the voice speaking
      this.resume = null;
      // the engine's voice segment, rebuilt from its events: {start, frames, decided, tapped,
      // newVoice (a new voice decided for it but held back), lead (its speech before its first
      // short pause), cont ({n0, start}: speech went on in it after the engine judged it in a pause)}
      this.seg = null;
      this.firstFrame = null;    // audio time of the first speech frame after the latest speech-start
      this.lastLevelT = null;
      this.smoothDb = null;      // the engine's smoothed loudness, approximated from level events
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
      const prevT = this.engineT;
      if (e.t != null && e.t > this.engineT) this.engineT = e.t;
      switch (e.type) {
        case 'speech-start': {
          const T = this.timing;
          this.speaking = true;
          this.lastSpeechStart = e.t;
          this.firstFrame = e.t + (T.vadOnFrames - 1) * T.frameSec;
          // a long silence opens the floor. The gap counts as well as the cue, which the engine
          // rate-limits and the wearer can switch off.
          const long = this.silenceFired || this.longGap(e);
          if (!this.resume && long) this.resume = { since: e.t };
          this.silenceFired = false;
          // the engine starts a new voice segment after a pause of turnGapSec (or at the first speech)
          if (!this.seg || e.gap == null || e.gap >= T.turnGapSec) this.seg = { start: e.t, frames: 0, decided: false };
          else {
            // the segment goes on: how long its first stretch of speech was (a burst, or a turn)
            if (this.seg.lead == null && this.lastSpeechEnd != null) this.seg.lead = this.lastSpeechEnd - this.seg.start;
            // the same frame-later test: the engine judged the segment in the pause just gone
            if (e.gap + T.frameSec >= T.turnGapSec - 1e-6) this.continueSegment(e.t);
          }
          break;
        }
        case 'speech-end':
          this.speaking = false;
          this.lastSpeechEnd = e.t;
          // a decision still on hold whose turn ended short is a back-channel
          if (this.hold && e.t - this.hold.t < this.minTurn) {
            this.suppressed.push(Object.assign({ reason: 'back-channel', turn: +(e.t - this.hold.t).toFixed(3) }, this.hold));
            if (this.seg) this.seg.newVoice = this.hold.isNew ? this.hold.voice : null;
            this.heldBack(this.hold.voice, this.hold.isNew);
            this.hold = null;
          }
          break;
        case 'speaker': {
          this.current = e.id;
          // only the New voice control makes a new voice stamped with the present moment (see the header)
          const pressed = !!e.isNew && e.t != null && e.t >= prevT;
          if (this.seg) this.seg.decided = true;   // this turn has its decision: no resume for it
          const turn = this.turnLength(e.t);
          const intent = this.speakerIntent(e.id, !!e.isNew, e.t);
          if (pressed || turn >= this.minTurn) { this.hold = null; this.resume = null; this.emitSeat(intent); }
          else if (this.speaking && (this.lastSpeechEnd == null || this.lastSpeechEnd < e.t || this.lastSpeechStart >= e.t)) {
            this.hold = { voice: e.id, isNew: !!e.isNew, t: e.t, due: e.t + this.minTurn };
          } else {
            // a back-channel: no tap, and after a silence the next real turn still gets its tap
            this.hold = null;
            if (this.seg) this.seg.newVoice = e.isNew ? e.id : null;
            this.heldBack(e.id, !!e.isNew);
            this.suppressed.push(Object.assign({ reason: 'back-channel', turn: +turn.toFixed(3) }, intent));
          }
          break;
        }
        case 'cue':
          if (e.t != null) { this.lastCueT = e.t; if (e.kind) this.lastCueByKind[e.kind] = e.t; }
          if (e.kind === 'silence') {
            // the cue fires on the first frame the engine's silence setting is reached: learn it,
            // unless it only confirms the setting the page passed
            if (!this.speaking && this.lastSpeechEnd != null && e.t > this.lastSpeechEnd) {
              const seen = e.t - this.lastSpeechEnd;
              if (this.silenceFrom !== 'page' || Math.abs(seen - this.silenceSec) > this.timing.frameSec + 1e-6) { this.silenceSec = seen; this.silenceFrom = 'cue'; }
            }
            this.silenceFired = true;
            this.emit({ kind: 'silence', t: e.t, voice: null });
          }
          else if (e.kind === 'drop' || e.kind === 'rise' || e.kind === 'hesitation') this.emit({ kind: 'cue', cue: e.kind, voice: e.speakerId == null ? null : e.speakerId, t: e.t });
          break;
        case 'level':
          this.countFrames(e);
          break;
        default:
          break;
      }
      this.settle();
      return this.intents.slice(before);
    }

    // Whether the gap before this speech-start is a long silence by the setting, when no silence
    // cue said so. The engine's own silence test runs on the frame before speech is confirmed,
    // one frame further on than the gap.
    longGap(e) {
      const T = this.timing, S = this.silenceSec;
      if (e.gap == null || S == null || e.gap + T.frameSec < S - 1e-6) return false;
      if (this.silenceFrom === 'page') return true;
      // measured from the cue: its absence is explained only by the engine's cue limits
      const at = e.t - e.gap + S, kind = this.lastCueByKind.silence;
      if ((kind != null && at - kind < T.cueCooldownSec - 1e-6) || (this.lastCueT != null && at - this.lastCueT < T.cueGapSec - 1e-6)) return true;
      // otherwise the setting has changed (or the cue was switched off): only the cue counts again
      this.silenceSec = null;
      this.silenceFrom = null;
      return false;
    }

    // A new voice whose decision did not tap: after a silence, its first real turn is announced as new.
    heldBack(voice, isNew) {
      if (isNew && this.resume) (this.resume.born = this.resume.born || []).push(voice);
    }

    // A known voice in the first real turn after a long silence is a resume (see the header).
    speakerIntent(voice, isNew, t) {
      const kind = isNew ? 'new_voice' : (this.resume ? 'voice_resumes' : 'speaker');
      return { kind, voice, t, new: isNew };
    }

    emitSeat(intent) {
      if (this.seg) this.seg.tapped = true;
      return this.emit(intent);
    }

    // Speech came back within turnGapSec, but only after the engine's pause check: the engine has
    // judged the segment on the burst before the pause (a decision, or "it stays with the current
    // voice") and the speech goes on in it. After a long silence a short burst is not the turn:
    // the turn goes on, and the resume now waits for the engine's first chance to switch voices.
    continueSegment(t) {
      const seg = this.seg;
      if (!this.resume || seg.start < this.resume.since || seg.tapped) return;
      // the level event that would have judged the burst came too late
      if (!seg.decided && this.lastSpeechEnd != null && this.lastSpeechEnd >= (seg.cont ? seg.cont.start : seg.start)) this.judge(this.lastSpeechEnd);
      if (seg.tapped || !seg.decided) return;
      // the engine's recheck clock starts at its first judgement and does not restart
      seg.cont = { n0: seg.cont ? seg.cont.n0 : seg.frames, start: t };
      seg.decided = false;
    }

    // The engine's speech-frame count for the current segment, rebuilt from its level events
    // (one every second frame): a frame counts while speaking and above the engine's voice floor.
    countFrames(e) {
      const T = this.timing;
      if (e.db != null) this.smoothDb = this.smoothDb == null ? e.db : 0.36 * this.smoothDb + 0.64 * e.db;
      const speaking = e.speaking != null ? !!e.speaking : this.speaking;
      if (this.seg && speaking && this.firstFrame != null && e.t != null) {
        const from = Math.max(this.lastLevelT == null ? -Infinity : this.lastLevelT, this.firstFrame - T.frameSec);
        const n = Math.max(0, Math.round((e.t - from) / T.frameSec));
        const floor = Math.max((e.noise != null ? e.noise : -Infinity) + T.vadOnDb, T.vadAbsMin);
        // hand-made events without a loudness count every speaking frame
        if (e.db == null || (e.db > floor && this.smoothDb > floor)) this.seg.frames += n;
      }
      if (e.t != null) this.lastLevelT = e.t;
    }

    // Holds and resumes are released by the engine clock, not by wall timers.
    settle() {
      if (this.hold && this.engineT >= this.hold.due) {
        const h = this.hold; this.hold = null;
        if (this.speaking && this.current === h.voice) { this.emitSeat(this.speakerIntent(h.voice, h.isNew, h.t)); this.resume = null; }
      }
      this.settleResume();
    }

    // The resume taps once the engine has had its final say on the turn and kept the voice: its
    // 90th speech frame while the person talks on (in a segment it already judged in a pause, its
    // first chance to switch), or the pause that ends a shorter turn.
    settleResume() {
      const r = this.resume, seg = this.seg, T = this.timing;
      if (!r || !seg) return;
      if (!seg.decided && seg.start >= r.since) {
        if (this.speaking) {
          const need = seg.cont ? firstSwitchFrames(seg.cont.n0, T) : T.finalFrames;
          if (seg.frames >= need + FINAL_MARGIN_FRAMES) this.judge(this.engineT);
        } else if (this.lastSpeechEnd != null && this.lastSpeechEnd >= (seg.cont ? seg.cont.start : seg.start) && this.engineT - this.lastSpeechEnd >= T.turnGapSec) {
          this.judge(this.lastSpeechEnd);
        }
      }
      // waiting on a voice made from the burst (see judge): the speech stopped before the engine's
      // next decision, so the decision it has stands
      const w = this.resume && this.resume.wait;
      if (w && this.seg.decided && !this.speaking && this.lastSpeechEnd != null && this.engineT - this.lastSpeechEnd >= REJUDGE_WAIT_SEC) {
        this.resume.wait = null;
        if (this.current === w.voice) { this.resume = null; this.emitSeat({ kind: 'new_voice', voice: w.voice, t: w.t, new: true }); }
      }
    }

    // The engine has had its say on the turn that ends at `end`: tap the voice it kept, unless
    // the turn was too short to be one.
    judge(end) {
      const seg = this.seg, r = this.resume, from = seg.cont ? seg.cont.start : seg.start;
      seg.decided = true;
      const turn = end - from;
      if (turn < this.minTurn || this.current == null) {
        // a cough or an "mm" after the silence: no tap, and the next real turn still gets one
        this.suppressed.push({ reason: 'short-after-silence', kind: 'voice_resumes', voice: this.current, t: from, turn: +turn.toFixed(3) });
        return;
      }
      // a new voice whose own decision was held back as a back-channel is still announced as new
      const isNew = (seg.newVoice != null && seg.newVoice === this.current) || (r.born != null && r.born.includes(this.current));
      // but when the segment began with a burst, the engine judged it (or decided early) mostly on
      // that burst, and from then on learns the voice from the speech that follows: its rechecks
      // cannot reject a voice it made from a burst. Wait for its decision on the next segment (a
      // different voice then taps through the speaker event instead).
      if (isNew && (seg.cont || (seg.lead != null && seg.lead < this.minTurn))) { if (!r.wait) r.wait = { voice: this.current, t: from }; return; }
      const t = r.wait && r.wait.voice === this.current ? r.wait.t : from;
      this.resume = null;
      this.emitSeat({ kind: isNew ? 'new_voice' : 'voice_resumes', voice: this.current, t, new: isNew });
    }

    // The engine says who is speaking; the page can also force it (New voice button, "this person is speaking now").
    setCurrent(id) { this.current = id; }
  }

  const api = { IntentSource, DEFAULT_RULES, ENGINE_TIMING, FINAL_MARGIN_FRAMES, REJUDGE_WAIT_SEC };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.KandhaIntents = api;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
