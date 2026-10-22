// Kandha voice view in the Audial-AI companion: who is speaking (a colour and an arrow per
// voice), tone cues on screen or by device vibration, tone compared with each person's usual
// voice, and a queue light. The Kandha Stole is driven from the full Kandha page (/kandha/). It draws only from the local app's event stream, so it works the
// same whether the page or the extension captured the audio.
import { displayEmotion } from "./emotion.js";

// Six voices, readable on the dark live panel and on the white transcript.
export const VOICE_COLORS = {
  panel: ["#6ab0ff", "#ff8a7a", "#45d6b9", "#c19bff", "#a7dd5a", "#ff7dc4"],
  page: ["#1a66c2", "#c2412d", "#0b8570", "#6b3fc4", "#4e7f12", "#b8306f"],
};
// One arrow per colour until a microphone array reports real directions.
export const VOICE_ARROWS = [180, 0, -90, -135, -45, 90];
export const CUE_INFO = {
  drop: {label: "Voice softened", detail: "quieter or sadder-sounding than usual", pattern: [700]},
  rise: {label: "Voice rose", detail: "louder or more intense than usual", pattern: [80, 70, 80, 70, 80]},
  hesitation: {label: "Hesitation", detail: "several short pauses", pattern: [40, 40, 40, 40, 40, 40, 40, 40, 40]},
  silence: {label: "Long silence", detail: "no one is speaking", pattern: [60, 240, 60]},
};
export const RELATIVE_TEXT = {intense: "More intense than usual", softer: "Softer, sad-sounding", usual: "Usual for them", learning: "Learning this voice"};

export const voiceName = id => (id == null ? "Someone" : `Voice ${id}`);
export const voiceSlot = id => (Math.max(1, id) - 1) % 6;

// Pure timeline over received events: attribution for captions and the transcript.
export class VoiceTimeline {
  constructor() { this.reset(); }
  reset() { this.changes = []; this.tones = []; this.cues = []; }
  add(events) {
    for (const event of events || []) {
      if (event.kind === "voice") {
        this.changes.push({t: event.t, id: event.id});
        if (this.changes.length > 1 && this.changes.at(-2).t > event.t) this.changes.sort((a, b) => a.t - b.t);
      } else if (event.kind === "tone") this.tones.push(event);
      else if (event.kind === "cue") this.cues.push(event);
    }
    for (const list of [this.changes, this.tones, this.cues]) if (list.length > 5000) list.splice(0, list.length - 5000);
  }
  voiceAt(t) {
    let id = null;
    for (const change of this.changes) { if (change.t <= t) id = change.id; else break; }
    return id;
  }
  // the voice heard longest during [start, end]
  voiceFor(start, end) {
    end = Math.max(end, start + 0.01);
    const spans = new Map();
    this.changes.forEach((change, i) => {
      const next = i + 1 < this.changes.length ? this.changes[i + 1].t : Infinity;
      const overlap = Math.min(end, next) - Math.max(start, change.t);
      if (overlap > 0) spans.set(change.id, (spans.get(change.id) || 0) + overlap);
    });
    let best = null;
    for (const [id, span] of spans) if (best === null || span > spans.get(best)) best = id;
    return best;
  }
  toneFor(start, end, voice) {
    const rank = tone => (tone.label !== "uncertain" ? 10 : 0) + ({learning: 0, usual: 1, softer: 2, intense: 2}[tone.relative] ?? 0);
    let best = null;
    for (const tone of this.tones) {
      if (tone.voice !== voice || tone.t1 < start - 0.3 || tone.t0 > end + 0.3) continue;
      if (!best || rank(tone) > rank(best)) best = tone;
    }
    return best;
  }
}

const ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

export class VoiceView {
  constructor(get, {vibrate = () => {}, palette = () => null, now = () => Date.now()} = {}) {
    this.$ = get; this.vibrate = vibrate; this.palette = palette; this.now = now;
    this.timeline = new VoiceTimeline();
    this.settings = {colors: true, cues: false, tone: false};
    this.current = null; this.queue = {on: false, since: 0, timer: 0};
    this.$("voice-badge").innerHTML = ARROW;
  }
  reset() {
    this.timeline.reset(); this.current = null;
    this.$("voice-name").textContent = "Listening for voices…";
    this.$("voice-cue").textContent = "";
    this.renderBadge(null); this.renderTone(null);
  }
  configure(settings) {
    this.settings = {...this.settings, ...settings};
    this.$("voice-now").hidden = !(this.settings.colors || this.settings.cues || this.settings.tone);
    this.$("voice-tone-row").hidden = !this.settings.tone;
    for (const key of ["colors", "cues", "tone"]) {
      const box = this.$("voice-" + key);
      if (box) box.checked = Boolean(this.settings[key]);
    }
    if (!this.settings.colors) this.renderBadge(null);
  }
  colour(id, where = "panel") { return id == null ? null : VOICE_COLORS[where][voiceSlot(id)]; }
  renderBadge(id) {
    const badge = this.$("voice-badge");
    const colour = this.settings.colors ? this.colour(id) : null;
    badge.style.setProperty("--voice", colour || "#8aa3ad");
    badge.querySelector("svg").style.transform = `rotate(${id == null ? 0 : VOICE_ARROWS[voiceSlot(id)]}deg)`;
    badge.dataset.voice = id == null ? "" : String(id);
  }
  // A batch of events from the local app's stream.
  apply(events) {
    this.timeline.add(events);
    for (const event of events) {
      if (event.kind === "voice") {
        this.current = event.id;
        if (this.settings.colors) {
          this.renderBadge(event.id);
          this.$("voice-name").textContent = voiceName(event.id) + (event.new ? " · new voice" : "");
        }
      } else if (event.kind === "cue" && this.settings.cues) this.cue(event);
      else if (event.kind === "tone" && this.settings.tone && event.voice === this.current) this.renderTone(event);
    }
  }
  cue(event) {
    const info = CUE_INFO[event.cue];
    if (!info) return;
    this.$("voice-cue").textContent = `${info.label} · ${event.voice ? voiceName(event.voice) + " · " : ""}${info.detail}`;
    const row = this.$("voice-now");
    row.classList.remove("is-cue"); void row.offsetWidth; row.classList.add("is-cue");
    this.vibrate(info.pattern);
  }
  renderTone(tone) {
    const out = this.$("voice-tone-out");
    if (!tone || tone.relative === "learning") {
      out.textContent = tone ? RELATIVE_TEXT.learning : "—";
      out.removeAttribute("style"); out.removeAttribute("aria-label");
      return;
    }
    const colors = this.palette();
    if (tone.label !== "uncertain" && colors) {
      // named estimates use the user's vocal-expression colours, label always visible
      displayEmotion(out, {tone: tone.label}, colors);
      out.textContent = `${RELATIVE_TEXT[tone.relative]} · ${tone.label} ${Math.round(tone.confidence * 100)}%`;
    } else {
      out.removeAttribute("style");
      out.textContent = RELATIVE_TEXT[tone.relative];
    }
  }
  // Transcript decoration: colour + voice name (when diarization left it unattributed) + tone.
  decorate(item, caption) {
    if (!this.settings.colors && !this.settings.tone) return;
    const voice = this.timeline.voiceFor(caption.start, caption.end);
    if (voice == null) return;
    const doc = item.ownerDocument;
    if (this.settings.colors) {
      item.classList.add("has-voice");
      item.style.setProperty("--voice", this.colour(voice, "page"));
      const tag = doc.createElement("span");
      tag.className = "voice-tag"; tag.textContent = voiceName(voice);
      item.firstElementChild?.prepend(tag, doc.createTextNode(" · "));
    }
    const tone = this.settings.tone ? this.timeline.toneFor(caption.start, caption.end, voice) : null;
    if (tone && tone.relative !== "learning" && (tone.relative !== "usual" || tone.label !== "uncertain")) {
      const chip = doc.createElement("span");
      chip.className = "tone-chip";
      chip.textContent = RELATIVE_TEXT[tone.relative] + (tone.label !== "uncertain" ? ` · estimate: ${tone.label} ${Math.round(tone.confidence * 100)}%` : "");
      chip.title = "Compared with how this person usually sounds. A hint, not a fact about feelings.";
      item.append(chip);
    }
  }
  // Queue light: "I want to speak" lights a strip across the top of the live panel.
  setQueue(on) {
    on = Boolean(on);
    if (on === this.queue.on) return false;
    this.queue.on = on;
    clearInterval(this.queue.timer);
    const strip = this.$("queue-strip"), button = this.$("queue-button");
    strip.hidden = !on; button.setAttribute("aria-pressed", String(on));
    button.textContent = on ? "Waiting… tap to cancel" : "I want to speak";
    if (on) {
      this.queue.since = this.now();
      const tick = () => {
        const s = Math.round((this.now() - this.queue.since) / 1000);
        this.$("queue-time").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      };
      tick(); this.queue.timer = setInterval(tick, 500);
    }
    return true;
  }
}
