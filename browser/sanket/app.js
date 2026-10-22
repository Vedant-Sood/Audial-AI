/*
 * Sanket app: wires the microphone, voice engine, captions, band and interface together.
 */
(function () {
  'use strict';

  const E = window.SanketEngine;
  const C = window.SanketCaptions;
  const Recognizer = window.SanketRecognizer;
  const Translator = window.SanketTranslator;
  const Band = window.SanketBand;
  const Demo = window.SanketDemo;
  const LocalCaptions = window.SanketLocalCaptions || null;
  // Trained tone model (src/engine/tone_model.json): inlined in the one-file build, or fetched
  // from the URL in <meta name="sanket-tone-model"> when Sanket is served as separate files.
  let TONE_MODEL = window.SanketToneModel || null;
  const metaUrl = (name) => { const m = document.querySelector(`meta[name="${name}"]`); return m ? m.content : null; };
  async function loadToneModel() {
    const url = metaUrl('sanket-tone-model');
    if (TONE_MODEL || !url) return;
    try {
      const r = await fetch(url, { cache: 'no-store' });
      if (r.ok) TONE_MODEL = await r.json();
    } catch (e) { /* estimates stay off; voice colours and rule cues still work */ }
    if (engine && TONE_MODEL && (settings.toneReview || settings.toneLive)) engine.setToneModel(TONE_MODEL);
  }

  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const HOSTED = !!window.claude; // running inside the claude.ai viewer (no microphone there)

  // ------------------------------------------------------------------ settings
  const STORE = 'sanket.settings.v1';
  const DEFAULTS = {
    name: '', theme: 'system', cap: 'M', showOriginal: true,
    sensitivity: 1, maxSpeakers: 6,
    cues: { drop: true, rise: true, hesitation: true, silence: true },
    silenceSec: 4, seminarCues: false, vibrate: false,
    autocorrect: true, customTerms: '', noiseFilter: false,
    toneReview: true, toneLive: false,
    captionSource: 'local',  // 'local' (AccessibilityAI's Whisper, when Sanket runs inside it) or 'browser'
    speechLang: 'en', capLang: 'en', mode: 'seminar',
  };
  function loadSettings() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || '{}');
      return Object.assign({}, DEFAULTS, raw, { cues: Object.assign({}, DEFAULTS.cues, raw.cues || {}) });
    } catch (e) { return JSON.parse(JSON.stringify(DEFAULTS)); }
  }
  const settings = loadSettings();
  function saveSettings() { try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch (e) { /* storage unavailable */ } }

  // ------------------------------------------------------------------ constants
  const ARROWS = [180, 0, -90, -135, -45, 90];   // one direction per colour (until the puck reports real directions)
  const CUE_INFO = {
    drop: { label: 'Voice softened', sub: 'Quieter or sadder-sounding than usual', pattern: [700] },
    rise: { label: 'Voice rose', sub: 'Louder or more intense than usual', pattern: [90, 80, 90, 80, 90] },
    hesitation: { label: 'Hesitation', sub: 'Several short pauses', pattern: [40, 40, 40, 40, 40, 40, 40, 40, 40] },
    silence: { label: 'Long silence', sub: 'No one is speaking', pattern: [150, 300, 150] },
  };
  const CUE_ICONS = {
    drop: '<path d="M3 8c2.5 0 3.5 4 6 4s3.5-4 6-4 3.5 8 6 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M19 19l2-3h-4z" fill="currentColor"/>',
    rise: '<path d="M3 16c2.5 0 3.5-4 6-4s3.5 4 6 4 3.5-10 6-10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M19 3l2 3h-4z" fill="currentColor"/>',
    hesitation: '<path d="M3 12h3M9 12h2M14 12h2M19 12h2" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
    silence: '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8v4l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  };
  const TONE_INFO = {
    intense: { label: 'More intense than usual', icon: CUE_ICONS.rise },
    softer: { label: 'Softer, sad-sounding', icon: CUE_ICONS.drop },
    usual: { label: 'Usual for them', icon: '<path d="M3 12c2.5 0 3.5-3 6-3s3.5 6 6 6 3.5-3 6-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' },
  };
  const EMOTION_NAME = { angry: 'angry', disgust: 'disgusted', fear: 'fearful', happy: 'happy', neutral: 'neutral', sad: 'sad' };
  const ARROW_SVG = '<svg viewBox="0 0 24 24"><path d="M4 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // ------------------------------------------------------------------ session state
  const S = {
    running: false,
    demo: null,
    demoStart: 0,
    speakers: new Map(),     // id -> {id, name, idx}
    current: null,
    lines: [],               // {uid, kind:'speech'|'cue'|'queue', speakerId, text, orig, spans, t}
    tones: [],               // tone estimates {t0, t1, speakerId, relative, label, confidence, accepted, personal, demo}
    changes: [],             // [{t, id}] speaker timeline for review
    queue: { on: false, since: 0, timer: null },
    lastFinalT: 0,
    sessionStart: Date.now(),
    translateNotice: false,
  };
  let uid = 0;

  let engine = null;
  let assembler = new C.CaptionAssembler({ delay: 0.6 });
  let vocab = buildVocab();
  const translator = new Translator();
  const captionHandlers = {
    onInterim: (text) => handleInterim(text),
    // local captions carry their own audio times; browser captions don't
    onFinal: (text, meta) => handleFinal(text, meta && meta.start != null ? { start: meta.start, end: meta.end } : undefined),
    onStatus: (s, info) => { if (s === 'listening' && S.running) setStatus('live', statusLine(info && info.local)); },
    onError: (code, msg) => {
      toast(msg, 9000);
      if (code === 'network' || code === 'unsupported' || code === 'local-missing' || code === 'local-busy') setStatus('live', 'Listening · voices and cues only');
      else if (!recognizer.active && S.running) setStatus('error', 'Captions stopped');
    },
  };
  const browserCaptions = new Recognizer(captionHandlers);
  const localCaptions = LocalCaptions ? new LocalCaptions(captionHandlers) : null;
  let localHost = null;        // AccessibilityAI status when Sanket is served by it
  let recognizer = browserCaptions;
  function chooseCaptions() {
    recognizer = localCaptions && localHost && settings.captionSource === 'local' ? localCaptions : browserCaptions;
    return recognizer;
  }
  const band = new Band({
    onButton: () => toggleQueue(),
    onStatus: (on, name) => {
      $('#bandStatus').textContent = on ? `Connected to ${name || 'Sanket Band'}.` : 'Not connected.';
      $('#bandConnect').textContent = on ? 'Disconnect band' : 'Connect band';
      if (on && S.current != null) band.colour(colourHex(S.current));
    },
  });
  band.phoneVibrate = settings.vibrate;

  const mic = { stream: null, ctx: null, node: null, src: null, wake: null };

  // ------------------------------------------------------------------ helpers
  function buildVocab() {
    const extra = String(settings.customTerms || '').split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
      const [term, ...rest] = l.split('=');
      return { term: term.trim(), definition: rest.join('=').trim() };
    });
    return new C.Vocabulary(extra);
  }

  function nowT() {
    if (S.demo) return (performance.now() - S.demoStart) / 1000;
    return engine ? engine.t : 0;
  }
  function clock(t) {
    t = Math.max(0, Math.round(t));
    return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  function speaker(id) { return id == null ? null : S.speakers.get(id) || null; }
  function colourVar(id) { const s = speaker(id); return s ? `var(--s${s.idx + 1})` : 'var(--s0)'; }
  function colourHex(id) {
    const s = speaker(id);
    if (!s) return '#000000';
    return getComputedStyle(document.documentElement).getPropertyValue(`--s${s.idx + 1}`).trim() || '#ffffff';
  }
  function arrowAngle(id) { const s = speaker(id); return s ? ARROWS[s.idx] : 0; }
  function nameOf(id) { const s = speaker(id); return s ? s.name : 'Someone'; }

  function ensureSpeaker(id, name) {
    if (id == null) return null;
    let s = S.speakers.get(id);
    if (!s) {
      const used = new Set(Array.from(S.speakers.values()).map((x) => x.idx));
      let idx = 0;
      while (used.has(idx) && idx < 5) idx++;
      if (used.has(idx)) idx = (S.speakers.size) % 6;
      s = { id, idx, name: name || `Voice ${S.speakers.size + 1}` };
      S.speakers.set(id, s);
      renderVoices();
    } else if (name) s.name = name;
    return s;
  }

  function badgeHTML(id, small) {
    return `<span class="badge${small ? ' badge--sm' : ''}" style="--c:${colourVar(id)}" aria-hidden="true">${ARROW_SVG.replace('<svg', `<svg style="transform:rotate(${arrowAngle(id)}deg)"`)}</span>`;
  }

  let toastTimer = null;
  function toast(html, ms) {
    const el = $('#toast');
    el.innerHTML = html;
    el.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('is-on'), ms || 4000);
  }

  function setStatus(state, text) {
    $('#status').dataset.state = state;
    $('#statusText').textContent = text;
  }
  function statusLine(local) {
    const lang = settings.speechLang === 'hi' ? 'Hindi' : 'English';
    const cap = settings.capLang !== settings.speechLang ? ` → ${settings.capLang === 'hi' ? 'Hindi' : 'English'}` : '';
    return `Listening · ${lang}${cap}${local ? (recognizer === localCaptions ? ' · AccessibilityAI on this computer' : ' · on device') : ''}`;
  }

  // ------------------------------------------------------------------ theme & display
  function applyDisplay() {
    const root = document.documentElement;
    if (settings.theme === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', settings.theme);
    root.setAttribute('data-capsize', settings.cap);
    $('#app').dataset.mode = settings.mode;
    $$('button[data-mode]', $('.topbar')).forEach((b) => b.setAttribute('aria-selected', String(b.dataset.mode === settings.mode)));
    $$('button[data-speech]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.speech === settings.speechLang)));
    $$('button[data-cap]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.cap === settings.capLang)));
    renderLegend();
    const cuesOn = cuesActive();
    $('#bandHint').textContent = settings.mode === 'practicum'
      ? 'Tone cues follow the person speaking. You choose which cues are on in Settings.'
      : cuesOn ? 'Tone cues are on for seminars (Settings).' : `Tone cues are ${settings.mode === 'lecture' ? 'off in Lecture mode' : 'on in Practicum mode'}. You can change this in Settings.`;
  }

  function cuesActive() {
    if (settings.mode === 'practicum') return true;
    if (settings.mode === 'seminar') return settings.seminarCues;
    return false;
  }
  function cueEnabled(kind) { return cuesActive() && !!settings.cues[kind]; }

  function engineSettings() {
    const on = cuesActive();
    return {
      singleSpeaker: settings.mode === 'lecture',
      maxSpeakers: settings.mode === 'practicum' ? 2 : +settings.maxSpeakers,
      sensitivity: +settings.sensitivity,
      silenceSec: +settings.silenceSec,
      cues: {
        drop: on && settings.cues.drop, rise: on && settings.cues.rise,
        hesitation: on && settings.cues.hesitation, silence: on && settings.cues.silence,
      },
    };
  }

  // ------------------------------------------------------------------ rendering
  function renderNow(pieces) {
    const id = S.current;
    const now = $('#now');
    now.style.setProperty('--c', colourVar(id));
    const badge = $('#nowBadge');
    badge.style.setProperty('--c', colourVar(id));
    $('svg', badge).style.transform = `rotate(${arrowAngle(id)}deg)`;
    $('#nowName').textContent = id == null ? (S.running || S.demo ? 'Listening…' : 'No one yet') : nameOf(id);
    if (pieces) {
      const text = $('#nowText');
      text.classList.toggle('is-idle', false);
      text.innerHTML = pieces.map((p) => `<span class="piece" style="--pc:${colourVar(p.speakerId)}">${esc(p.text)}</span>`).join(' ');
    }
  }

  function renderVoices() {
    const ul = $('#voices');
    const list = Array.from(S.speakers.values());
    $('#voicesEmpty').hidden = list.length > 0;
    ul.innerHTML = list.map((s) => `
      <li><button class="voice${s.id === S.current ? ' is-current' : ''}" data-voice="${s.id}" style="--c:${colourVar(s.id)}">
        ${badgeHTML(s.id, true)}
        <span class="voice__name">${esc(s.name)}</span>
        ${s.id === S.current ? '<span class="voice__live">Speaking</span>' : `<span class="voice__meta">${countLines(s.id)} lines</span>`}
      </button></li>`).join('');
  }
  function countLines(id) { return S.lines.filter((l) => l.kind === 'speech' && l.speakerId === id).length; }

  function renderLegend() {
    $('#legend').innerHTML = Object.entries(CUE_INFO).map(([k, v]) => `
      <li data-cue="${k}" class="${cueEnabled(k) ? '' : 'is-off'}">
        <svg class="cue-icon" viewBox="0 0 24 24" aria-hidden="true">${CUE_ICONS[k]}</svg>
        <span>${v.label}</span>
        <span class="pattern" aria-hidden="true">${v.pattern.filter((_, i) => i % 2 === 0).map((ms) => `<i style="width:${Math.max(4, Math.round(ms / 12))}px"></i>`).join('')}</span>
      </li>`).join('');
  }

  // ------------------------------------------------------------------ tone estimates
  // The estimate that best describes a caption line: same person, overlapping in time.
  function toneForLine(l) {
    if (l.kind !== 'speech' || l.speakerId == null || !S.tones.length) return null;
    const i = S.lines.indexOf(l);
    let end = l.t + 8;
    for (let j = i + 1; j < S.lines.length; j++) if (S.lines[j].kind === 'speech') { end = Math.max(l.t + 1, S.lines[j].t); break; }
    const rank = (x) => (x.accepted ? 3 : x.relative === 'softer' || x.relative === 'intense' ? 2 : x.relative === 'usual' ? 1 : 0);
    let best = null;
    for (const x of S.tones) {
      if (x.speakerId !== l.speakerId || x.t1 < l.t - 0.3 || x.t0 > end) continue;
      if (!best || rank(x) > rank(best)) best = x;
    }
    return best;
  }
  function toneChipHTML(x, opts) {
    opts = opts || {};
    if (!x || x.relative === 'learning') return '';
    if (x.relative === 'usual' && !x.accepted && !opts.showUsual) return '';
    const info = TONE_INFO[x.relative];
    const est = x.accepted ? `<span class="est">Estimate: ${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%</span>` : '';
    return `<span class="tone-chip" title="Tone estimate: how this voice sounded compared with how this person usually sounds. A hint, not a fact about feelings."><svg viewBox="0 0 24 24" aria-hidden="true">${info.icon}</svg><span><span class="visually-hidden">Tone: </span><b>${info.label}</b></span>${est}</span>`;
  }
  function toneText(x) {
    if (!x || x.relative === 'learning' || (x.relative === 'usual' && !x.accepted)) return '';
    return `tone: ${TONE_INFO[x.relative].label.toLowerCase()}${x.accepted ? `; estimate ${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%` : ''}`;
  }

  function onTone(e) {
    const x = {
      t0: e.t0, t1: e.t1, speakerId: e.speakerId, relative: e.relative, label: e.label,
      confidence: e.confidence, accepted: !!e.accepted, personal: !!e.personal, shift: e.shift, demo: !!e.demo,
    };
    S.tones.push(x);
    if (!settings.toneLive) return;
    if (x.speakerId === S.current) renderNowTone(x);
    for (let i = S.lines.length - 1; i >= 0 && i >= S.lines.length - 6; i--) {
      const l = S.lines[i];
      if (l.kind === 'speech' && l.speakerId === x.speakerId && toneForLine(l) === x) rerenderLine(l);
    }
  }
  function renderNowTone(x) {
    const el = $('#nowTone');
    const html = settings.toneLive ? toneChipHTML(x, { showUsual: true }) : '';
    el.hidden = !html;
    if (html) el.innerHTML = html.replace(/^<span class="tone-chip"[^>]*>/, '').replace(/<\/span>$/, '');
  }

  function lineHTML(l, where) {
    if (l.kind === 'cue') {
      const info = CUE_INFO[l.cue];
      return `<li class="event" data-uid="${l.uid}"><svg class="cue-icon" viewBox="0 0 24 24" aria-hidden="true">${CUE_ICONS[l.cue]}</svg><b>${info.label}</b><span>${l.speakerId != null ? esc(nameOf(l.speakerId)) : ''}</span><span class="line__time">${clock(l.t)}</span></li>`;
    }
    if (l.kind === 'queue') {
      return `<li class="event event--queue" data-uid="${l.uid}"><b>${esc(l.text)}</b><span class="line__time">${clock(l.t)}</span></li>`;
    }
    const textHTML = l.spans && l.spans.length ? withTerms(l.text, l.spans) : esc(l.text);
    const orig = l.orig && settings.showOriginal ? `<p class="line__orig" lang="${settings.speechLang}">${esc(l.orig)}</p>` : '';
    const showTone = where === 'review' ? settings.toneReview : settings.toneLive;
    const tone = showTone ? toneChipHTML(toneForLine(l)) : '';
    return `<li class="line" data-uid="${l.uid}" style="--c:${colourVar(l.speakerId)}">
      <button class="line__who" data-line="${l.uid}" title="Fix who said this">${badgeHTML(l.speakerId, true)}<span>${esc(l.speakerId != null ? nameOf(l.speakerId) : 'Someone')}</span></button>
      <span class="line__time">${clock(l.t)}</span>
      <p class="line__text" lang="${l.lang || 'en'}">${textHTML}</p>${orig}${tone}</li>`;
  }

  function withTerms(text, spans) {
    let out = '', pos = 0;
    for (const sp of spans) {
      out += esc(text.slice(pos, sp.start));
      out += `<button type="button" class="term${sp.corrected ? ' is-fixed' : ''}" data-term="${esc(sp.term)}">${esc(text.slice(sp.start, sp.end))}</button>`;
      pos = sp.end;
    }
    return out + esc(text.slice(pos));
  }

  function appendLine(l) {
    S.lines.push(l);
    const ol = $('#history');
    const nearBottom = ol.scrollHeight - ol.scrollTop - ol.clientHeight < 120;
    ol.insertAdjacentHTML('beforeend', lineHTML(l));
    if (nearBottom) ol.scrollTop = ol.scrollHeight;
  }
  function rerenderLine(l) {
    const el = $(`[data-uid="${l.uid}"]`, $('#history'));
    if (el) el.outerHTML = lineHTML(l);
  }
  function rerenderHistory() {
    $('#history').innerHTML = S.lines.map(lineHTML).join('');
    $('#history').scrollTop = $('#history').scrollHeight;
  }

  // ------------------------------------------------------------------ live events
  function onSpeaker(id, t) {
    ensureSpeaker(id);
    const changed = S.current !== id;
    S.current = id;
    assembler.speakerChange(t, id);
    S.changes.push({ t, id });
    renderNow();
    if (changed) {
      const last = S.tones.filter((x) => x.speakerId === id).pop();
      renderNowTone(last && last.t1 > t - 30 ? last : null);
    }
    renderVoices();
    const face = $('#bandFace');
    face.classList.remove('is-idle');
    face.style.setProperty('--c', colourVar(id));
    if (changed) band.colour(colourHex(id));
  }

  function onCue(kind, t, speakerId) {
    if (!cueEnabled(kind)) return;
    const info = CUE_INFO[kind];
    appendLine({ uid: ++uid, kind: 'cue', cue: kind, speakerId: speakerId == null ? S.current : speakerId, t });
    $('#cueLabel').textContent = info.label;
    $('#cueSub').textContent = `${speakerId != null ? nameOf(speakerId) + ' · ' : ''}${info.sub}`;
    const face = $('#bandFace');
    face.classList.add('buzz');
    const total = info.pattern.reduce((a, b) => a + b, 0);
    setTimeout(() => face.classList.remove('buzz'), Math.min(1600, total + 100));
    const li = $(`#legend [data-cue="${kind}"]`);
    if (li) { li.classList.remove('flash'); void li.offsetWidth; li.classList.add('flash'); }
    band.cue(kind);
  }

  function handleInterim(text) {
    if (!text) return;
    const pieces = assembler.interim(text, nowT());
    renderNow(pieces);
  }

  // opts.lang: the language of `text` when it is already final (the demo supplies captions directly)
  async function handleFinal(text, opts) {
    opts = opts || {};
    const pieces = opts.start != null ? assembler.timed(text, opts.start, opts.end) : assembler.final(text, nowT());
    for (const p of pieces) {
      const speechLang = opts.lang || settings.speechLang;
      let body = p.text, spans = [];
      if (speechLang === 'en') {
        const r = vocab.process(body, { autocorrect: settings.autocorrect });
        body = r.text; spans = r.spans;
      }
      if (speechLang === 'en') body = body.charAt(0).toUpperCase() + body.slice(1);
      const line = { uid: ++uid, kind: 'speech', speakerId: p.speakerId, text: body, spans, t: p.t, lang: speechLang };
      if (p.speakerId != null) ensureSpeaker(p.speakerId);
      appendLine(line);
      if (!opts.lang && settings.capLang !== speechLang) translateLine(line);
    }
    renderVoices();
    const last = pieces[pieces.length - 1];
    if (last) renderNow([{ speakerId: last.speakerId, text: S.lines[S.lines.length - 1].text }]);
    S.lastFinalT = nowT();
  }

  async function translateLine(line) {
    if (!translator.ready) {
      if (!S.translateNotice) {
        S.translateNotice = true;
        toast(`Translation needs Chrome 138 or newer on a computer. Showing ${settings.speechLang === 'hi' ? 'Hindi' : 'English'} captions instead.`, 8000);
      }
      return;
    }
    const out = await translator.translate(line.text);
    if (!out) return;
    line.orig = line.text;
    line.text = out;
    line.spans = [];
    line.lang = settings.capLang;
    rerenderLine(line);
  }

  // ------------------------------------------------------------------ queue
  function toggleQueue(force) {
    const on = force === undefined ? !S.queue.on : !!force;
    if (on === S.queue.on) return;
    S.queue.on = on;
    const strip = $('#strip');
    strip.classList.toggle('is-on', on);
    $('#queueBtn').setAttribute('aria-pressed', String(on));
    $('#queueText').textContent = on ? 'Waiting… tap to cancel' : 'I want to speak';
    const who = settings.name ? `${settings.name} is waiting to speak` : 'Waiting to speak';
    $('#stripLabel').textContent = who;
    clearInterval(S.queue.timer);
    if (on) {
      S.queue.since = Date.now();
      $('#stripTime').textContent = '0:00';
      S.queue.timer = setInterval(() => { $('#stripTime').textContent = clock((Date.now() - S.queue.since) / 1000); }, 500);
      appendLine({ uid: ++uid, kind: 'queue', text: `${settings.name || 'You'} asked to speak`, t: nowT() });
    } else if (S.queue.since) {
      const waited = Math.round((Date.now() - S.queue.since) / 1000);
      appendLine({ uid: ++uid, kind: 'queue', text: `Turn taken after ${waited} s`, t: nowT() });
    }
  }

  // ------------------------------------------------------------------ microphone + engine
  const WORKLET = `
    class SanketTap extends AudioWorkletProcessor {
      constructor() { super(); this.buf = new Float32Array(1024); this.n = 0; }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (ch) {
          for (let i = 0; i < ch.length; i++) {
            this.buf[this.n++] = ch[i];
            if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
          }
        }
        return true;
      }
    }
    registerProcessor('sanket-tap', SanketTap);`;

  async function startAudio() {
    const stream = await navigator.mediaDevices.getUserMedia({
      // The browser's noise filter reshapes voices and makes colours less reliable, so it is off
      // unless the room is very noisy (Settings).
      audio: { echoCancellation: false, noiseSuppression: !!settings.noiseFilter, autoGainControl: false, channelCount: 1 },
    });
    let ctx;
    try { ctx = new AudioContext({ sampleRate: 16000 }); } catch (e) { ctx = new AudioContext(); }
    const src = ctx.createMediaStreamSource(stream);
    engine = new E.VoiceEngine({
      sampleRate: ctx.sampleRate, settings: engineSettings(), onEvent: onEngineEvent,
      toneModel: settings.toneReview || settings.toneLive ? TONE_MODEL : null,
    });
    const rate = ctx.sampleRate;
    const take = (x) => {
      if (engine) engine.process(x);
      if (recognizer.feed) recognizer.feed(x, rate);   // local captions get the same audio
    };
    let node = null;
    // a pages with a strict content-security policy can't load a blob: worklet, so it names a file
    for (const url of [metaUrl('sanket-worklet'), 'blob'].filter(Boolean)) {
      try {
        const src = url === 'blob' ? URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' })) : url;
        await ctx.audioWorklet.addModule(src);
        node = new AudioWorkletNode(ctx, 'sanket-tap');
        node.port.onmessage = (e) => take(e.data);
        break;
      } catch (e) { node = null; }
    }
    if (!node) {
      node = ctx.createScriptProcessor(1024, 1, 1);
      node.onaudioprocess = (e) => take(e.inputBuffer.getChannelData(0).slice(0));
    }
    const sink = ctx.createGain();
    sink.gain.value = 0;
    src.connect(node); node.connect(sink); sink.connect(ctx.destination);
    if (ctx.state === 'suspended') await ctx.resume();
    Object.assign(mic, { stream, ctx, node, src });
    return stream.getAudioTracks()[0];
  }

  function stopAudio() {
    try { mic.node && mic.node.disconnect(); } catch (e) { /* ignore */ }
    if (mic.stream) mic.stream.getTracks().forEach((t) => t.stop());
    if (mic.ctx) mic.ctx.close().catch(() => {});
    mic.stream = mic.ctx = mic.node = mic.src = null;
  }

  let meterRaf = 0, meterDb = -90;
  function onEngineEvent(e) {
    switch (e.type) {
      case 'speaker': onSpeaker(e.id, e.t); break;
      case 'cue': onCue(e.kind, e.t, e.speakerId); break;
      case 'tone': onTone(e); break;
      case 'level':
        meterDb = e.db;
        if (!meterRaf) meterRaf = requestAnimationFrame(() => {
          meterRaf = 0;
          $('#meterFill').style.width = `${Math.max(0, Math.min(100, ((meterDb + 70) / 55) * 100))}%`;
        });
        break;
      default: break;
    }
  }

  async function startListening() {
    if (S.demo) stopDemo();
    hideWelcome();
    setStatus('idle', 'Starting…');
    // translation packs download on a button press, so prepare them now
    if (settings.capLang !== settings.speechLang) {
      const r = await translator.prepare(settings.speechLang, settings.capLang, (p) => setStatus('idle', `Getting ${settings.capLang === 'hi' ? 'Hindi' : 'English'} translation… ${Math.round(p * 100)}%`));
      if (r !== 'ready') { S.translateNotice = false; }
    }
    let track = null;
    try {
      track = await startAudio();
    } catch (err) {
      const blocked = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
      setStatus('error', blocked ? 'Microphone blocked' : 'No microphone');
      toast(HOSTED
        ? 'This online preview can’t use the microphone. Download Sanket and open it in Chrome to caption a real room, or watch a demo here.'
        : blocked ? 'Sanket needs the microphone. Allow it for this page (the icon in the address bar), then press Start.'
          : 'No microphone was found. Plug one in or check your sound settings, then press Start.', 9000);
      showWelcome();
      return;
    }
    S.running = true;
    S.sessionStart = Date.now();
    $('#startBtn').dataset.running = 'true';
    $('#startLabel').textContent = 'Pause';
    setStatus('live', statusLine(false));
    renderNow();
    $('#nowHint').textContent = '';
    $('#nowText').classList.add('is-idle');
    $('#nowText').textContent = 'Listening for voices…';
    const phrases = settings.speechLang === 'en' ? vocab.terms.map((t) => t.term) : [];
    chooseCaptions();
    await recognizer.start({ lang: settings.speechLang, track, phrases });
    requestWake();
  }

  function stopListening() {
    if (engine) engine.flushTone();
    recognizer.stop();
    stopAudio();
    S.running = false;
    $('#startBtn').dataset.running = 'false';
    $('#startLabel').textContent = 'Start';
    setStatus('idle', 'Paused');
    releaseWake();
  }

  async function requestWake() {
    try { if (navigator.wakeLock) mic.wake = await navigator.wakeLock.request('screen'); } catch (e) { /* not allowed */ }
  }
  function releaseWake() { try { mic.wake && mic.wake.release(); } catch (e) { /* ignore */ } mic.wake = null; }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && S.running) requestWake(); });

  // ------------------------------------------------------------------ demo
  function resetSession() {
    S.speakers.clear(); S.current = null; S.lines = []; S.changes = []; S.tones = [];
    renderNowTone(null);
    assembler = new C.CaptionAssembler({ delay: 0.6 });
    $('#history').innerHTML = '';
    $('#cueLabel').textContent = 'No cues yet';
    $('#cueSub').textContent = 'Your band glows in the speaker’s colour.';
    $('#bandFace').classList.add('is-idle');
    renderVoices(); renderNow();
  }

  function playDemo(key) {
    if (S.running) stopListening();
    if (S.demo) stopDemo();
    hideWelcome();
    resetSession();
    const scene = Demo.SCENES[key];
    settings.mode = scene.mode;
    applyDisplay();
    S.demoStart = performance.now();
    setStatus('demo', `Demo · ${scene.title}`);
    $('#nowHint').textContent = 'Demo: no microphone in use.';
    let silenceTimer = null;
    S.demo = new Demo({
      begin: (sc) => sc.speakers.forEach((s) => ensureSpeaker(s.id, s.name)),
      speaker: (id) => { clearTimeout(silenceTimer); onSpeaker(id, nowT()); },
      interim: (text) => handleInterim(text),
      final: (text) => handleFinal(text, { lang: settings.capLang }),
      cue: (kind) => onCue(kind, nowT(), S.current),
      tone: (id, tone) => {
        const line = S.lines.filter((l) => l.kind === 'speech' && l.speakerId === id).pop();
        onTone(Object.assign({ t0: line ? line.t : nowT() - 2, t1: nowT(), speakerId: id, personal: true, demo: true,
          accepted: !!tone.label, label: tone.label || 'uncertain' }, tone));
      },
      queue: (on) => toggleQueue(on),
      silence: (ms) => {
        renderNow([]);
        $('#nowText').classList.add('is-idle');
        $('#nowText').textContent = '…';
        silenceTimer = setTimeout(() => onCue('silence', nowT(), null), Math.min(ms - 150, settings.silenceSec * 1000));
      },
      end: () => { S.demo = null; setStatus('idle', 'Demo finished'); $('#nowHint').textContent = 'Press Start to caption a real room.'; },
    });
    S.demo.play(key, { lang: settings.capLang, aloud: $('#demoAloud').checked });
  }
  function stopDemo() { if (S.demo) { S.demo.stop(); S.demo = null; } toggleQueue(false); }

  // ------------------------------------------------------------------ welcome
  function hideWelcome() { $('#welcome').hidden = true; }
  function showWelcome() { if (!S.lines.length) $('#welcome').hidden = false; }

  // ------------------------------------------------------------------ voice dialog
  let dlgVoice = null, dlgLine = null;
  function openVoice(id, lineUid) {
    const s = speaker(id);
    dlgLine = lineUid ? S.lines.find((l) => l.uid === lineUid) : null;
    dlgVoice = s;
    const others = Array.from(S.speakers.values()).filter((x) => !s || x.id !== s.id);
    $('#voiceTitle').textContent = s ? s.name : 'Unknown voice';
    $('#voiceBadge').style.setProperty('--c', colourVar(id));
    $('#voiceBadge').innerHTML = ARROW_SVG.replace('<svg', `<svg style="transform:rotate(${arrowAngle(id)}deg)"`);
    $('#voiceName').value = s ? s.name : '';
    $('#voiceName').disabled = !s;
    $('#mergeSel').innerHTML = others.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join('');
    $('#mergeBtn').disabled = !s || !others.length;
    $('#mergeSel').disabled = !others.length;
    $('#lineMoveField').hidden = !dlgLine;
    $('#lineMoveSel').innerHTML = Array.from(S.speakers.values()).map((o) => `<option value="${o.id}"${o.id === id ? ' selected' : ''}>${esc(o.name)}</option>`).join('');
    $('#makeCurrentBtn').disabled = !s || !(S.running || S.demo);
    $('#voiceDlg').showModal();
  }

  function mergeVoices(keepId, dropId) {
    for (const l of S.lines) if (l.speakerId === dropId) l.speakerId = keepId;
    for (const c of S.changes) if (c.id === dropId) c.id = keepId;
    for (const x of S.tones) if (x.speakerId === dropId) x.speakerId = keepId;
    assembler.relabel(dropId, keepId);
    if (engine) engine.mergeSpeakers(keepId, dropId);
    if (S.current === dropId) S.current = keepId;
    S.speakers.delete(dropId);
    rerenderHistory(); renderVoices(); renderNow();
  }

  // ------------------------------------------------------------------ review & saving
  function sessionLength() {
    const last = S.lines.length ? S.lines[S.lines.length - 1].t : 0;
    return Math.max(nowT(), last, 1);
  }

  function timelineSVG(literal) {
    const T = sessionLength();
    const pxPerSec = Math.max(6, Math.min(40, 900 / T));
    const tonesOn = settings.toneReview && S.tones.some((x) => x.personal);
    const W = Math.max(600, Math.ceil(T * pxPerSec) + 40), H = tonesOn ? 136 : 112, x0 = 20;
    const X = (t) => x0 + t * pxPerSec;
    const col = (id) => {
      if (!literal) return colourVar(id);
      const s = speaker(id); const light = ['#1a66c2', '#c2412d', '#0b8570', '#6b3fc4', '#4e7f12', '#b8306f'];
      return s ? light[s.idx] : '#4e5c6b';
    };
    const ink = literal ? '#4e5c6b' : 'var(--muted)';
    const blocks = [];
    const ch = S.changes.slice().sort((a, b) => a.t - b.t);
    for (let i = 0; i < ch.length; i++) {
      const t0 = ch[i].t, t1 = i + 1 < ch.length ? ch[i + 1].t : T;
      if (t1 - t0 < 0.05) continue;
      blocks.push(`<rect x="${X(t0).toFixed(1)}" y="46" width="${Math.max(2, X(t1) - X(t0)).toFixed(1)}" height="30" rx="4" fill="${col(ch[i].id)}"><title>${esc(nameOf(ch[i].id))} ${clock(t0)}–${clock(t1)}</title></rect>`);
    }
    const cues = S.lines.filter((l) => l.kind === 'cue').map((l) => `<g><path d="M${X(l.t).toFixed(1)} 40 l-6 -10 h12 z" fill="${ink}"><title>${CUE_INFO[l.cue].label} ${clock(l.t)}</title></path><text x="${X(l.t).toFixed(1)}" y="22" text-anchor="middle" font-size="11" fill="${ink}" font-family="system-ui, sans-serif">${CUE_INFO[l.cue].label}</text></g>`);
    const queue = S.lines.filter((l) => l.kind === 'queue' && /asked/.test(l.text)).map((l) => `<path d="M${X(l.t).toFixed(1)} 82 v14" stroke="${literal ? '#e39a10' : 'var(--signal)'}" stroke-width="3"><title>Asked to speak ${clock(l.t)}</title></path>`);
    // tone lane: ▲ more intense than usual, ▼ softer / sad-sounding, thin bar = usual for them
    const tones = !tonesOn ? [] : S.tones.filter((x) => x.personal && x.relative !== 'learning').map((x) => {
      const xm = X((x.t0 + x.t1) / 2), c = col(x.speakerId);
      const tip = `<title>${esc(nameOf(x.speakerId))} ${clock(x.t0)}: ${TONE_INFO[x.relative].label}${x.accepted ? ` · estimate ${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%` : ''}</title>`;
      if (x.relative === 'intense') return `<path d="M${xm.toFixed(1)} 104 l-6 10 h12 z" fill="${c}">${tip}</path>`;
      if (x.relative === 'softer') return `<path d="M${xm.toFixed(1)} 114 l-6 -10 h12 z" fill="${c}">${tip}</path>`;
      return `<rect x="${X(x.t0).toFixed(1)}" y="108" width="${Math.max(2, X(x.t1) - X(x.t0)).toFixed(1)}" height="2" fill="${c}" opacity=".6">${tip}</rect>`;
    });
    if (tonesOn) tones.unshift(`<text x="${x0}" y="100" font-size="11" fill="${ink}" font-family="system-ui, sans-serif">Tone (estimate)</text>`);
    const ticks = [];
    const step = T > 600 ? 120 : T > 120 ? 30 : 10;
    for (let t = 0; t <= T; t += step) ticks.push(`<text x="${X(t).toFixed(1)}" y="${H - 4}" text-anchor="middle" font-size="11" fill="${ink}" font-family="system-ui, sans-serif">${clock(t)}</text>`);
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Who spoke when, with tone cues"><line x1="${x0}" x2="${X(T)}" y1="61" y2="61" stroke="${literal ? '#d3dbe3' : 'var(--line)'}" stroke-width="2"/>${blocks.join('')}${queue.join('')}${cues.join('')}${tones.join('')}${ticks.join('')}</svg>`;
  }

  function openReview() {
    const speech = S.lines.filter((l) => l.kind === 'speech');
    const cues = S.lines.filter((l) => l.kind === 'cue');
    $('#reviewSummary').textContent = S.lines.length
      ? `${clock(sessionLength())} · ${S.speakers.size} voice${S.speakers.size === 1 ? '' : 's'} · ${speech.length} lines · ${cues.length} tone cue${cues.length === 1 ? '' : 's'}`
      : 'Nothing to review yet. Start listening or watch a demo first.';
    $('#timelineWrap').innerHTML = timelineSVG(false);
    $('#reviewLegend').innerHTML = Array.from(S.speakers.values()).map((s) => `<span><i class="swatch" style="--c:${colourVar(s.id)}"></i>${esc(s.name)}</span>`).join('') +
      '<span><i class="swatch" style="--c:var(--signal)"></i>Asked to speak</span>';
    renderToneSummary();
    $('#reviewList').innerHTML = S.lines.map((l) => lineHTML(l, 'review')).join('');
    $('#consentBox').checked = false;
    $('#saveHtml').disabled = $('#saveTxt').disabled = true;
    $('#reviewDlg').showModal();
  }

  function toneSummaryData() {
    const by = new Map();
    for (const x of S.tones) {
      if (!x.personal || x.relative === 'learning') continue;
      const r = by.get(x.speakerId) || { intense: 0, softer: 0, usual: 0, named: [] };
      r[x.relative]++;
      if (x.accepted) r.named.push(`${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%`);
      by.set(x.speakerId, r);
    }
    return by;
  }
  function renderToneSummary() {
    const box = $('#toneSummary');
    const by = toneSummaryData();
    const demo = S.tones.some((x) => x.demo);
    if (!settings.toneReview || (!by.size && !S.tones.length)) { box.hidden = true; return; }
    box.hidden = false;
    const rows = Array.from(by.entries()).map(([id, r]) => {
      const parts = [];
      if (r.intense) parts.push(`${r.intense}× more intense than usual`);
      if (r.softer) parts.push(`${r.softer}× softer, sad-sounding`);
      parts.push(`${r.usual}× usual`);
      return `<li style="--c:${colourVar(id)}"><span class="who">${esc(nameOf(id))}</span><span>${parts.join(' · ')}</span>${r.named.length ? `<span class="fineprint">Named: ${esc(r.named.join(', '))}</span>` : ''}</li>`;
    }).join('');
    box.innerHTML = `<h3>Tone estimates</h3>${rows ? `<ul>${rows}</ul>` : '<p class="fineprint">Sanket was still learning these voices. It needs to hear someone a few times before estimating their tone.</p>'}
      <p class="fineprint">${demo ? 'Demo: these estimates are scripted to show the feature. ' : ''}Compared with how each person usually sounds. A hint to look again, not a fact about feelings. <button type="button" class="linkish" data-tone-about>How accurate is this?</button></p>`;
  }

  function exportText() {
    const head = `Sanket session — ${new Date(S.sessionStart).toLocaleString()}\n\n`;
    return head + S.lines.map((l) => {
      if (l.kind === 'speech') {
        const tone = settings.toneReview ? toneText(toneForLine(l)) : '';
        return `[${clock(l.t)}] ${nameOf(l.speakerId)}: ${l.text}${l.orig ? `\n          (${l.orig})` : ''}${tone ? `\n          [${tone}]` : ''}`;
      }
      if (l.kind === 'cue') return `[${clock(l.t)}] — ${CUE_INFO[l.cue].label}${l.speakerId != null ? ` (${nameOf(l.speakerId)})` : ''}`;
      return `[${clock(l.t)}] — ${l.text}`;
    }).join('\n') + '\n';
  }

  function exportHTML() {
    const light = ['#1a66c2', '#c2412d', '#0b8570', '#6b3fc4', '#4e7f12', '#b8306f'];
    const c = (id) => { const s = speaker(id); return s ? light[s.idx] : '#4e5c6b'; };
    const rows = S.lines.map((l) => {
      if (l.kind === 'speech') {
        const tone = settings.toneReview ? toneText(toneForLine(l)) : '';
        return `<li style="border-left:4px solid ${c(l.speakerId)}"><span class="t">${clock(l.t)}</span><b style="color:${c(l.speakerId)}">${esc(nameOf(l.speakerId))}</b><p>${esc(l.text)}</p>${l.orig ? `<p class="o">${esc(l.orig)}</p>` : ''}${tone ? `<p class="o tone">${esc(tone.charAt(0).toUpperCase() + tone.slice(1))}</p>` : ''}</li>`;
      }
      if (l.kind === 'cue') return `<li class="cue"><span class="t">${clock(l.t)}</span><b>${CUE_INFO[l.cue].label}</b> ${l.speakerId != null ? esc(nameOf(l.speakerId)) : ''}</li>`;
      return `<li class="cue q"><span class="t">${clock(l.t)}</span><b>${esc(l.text)}</b></li>`;
    }).join('\n');
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sanket session ${new Date(S.sessionStart).toLocaleDateString()}</title>
<style>body{font:17px/1.5 system-ui,sans-serif;color:#111820;background:#f3f5f7;margin:0;padding:24px max(16px,4vw)}h1{font-size:24px;margin:0 0 4px}p.m{color:#4e5c6b;margin:0 0 16px}.tl{overflow-x:auto;background:#fff;border:1px solid #d3dbe3;border-radius:12px;margin-bottom:16px}ol{list-style:none;padding:0;display:grid;gap:8px;max-width:860px}li{background:#fff;border-radius:10px;padding:10px 14px;border:1px solid #d3dbe3}li p{margin:4px 0 0}li .o{color:#4e5c6b;font-size:14px}.t{float:right;color:#4e5c6b;font-family:ui-monospace,monospace;font-size:13px}.cue{background:#eaeef2;border-radius:999px;padding:6px 14px}.q b{color:#9a6200}</style></head>
<body><h1>Sanket session</h1><p class="m">${esc(new Date(S.sessionStart).toLocaleString())} · ${clock(sessionLength())} · ${esc(Array.from(S.speakers.values()).map((s) => s.name).join(', '))}</p>
<div class="tl">${timelineSVG(true)}</div><ol>${rows}</ol><p class="m">Tone cues describe what a voice did, not what anyone felt.${settings.toneReview && S.tones.length ? ' Tone estimates compare each voice with how that person usually sounds; they were learned from acted speech (CREMA-D) and are hints, not facts about feelings.' : ''} Saved with the consent of everyone present.</p></body></html>`;
  }

  async function saveFile(name, text, mime) {
    if (HOSTED && window.claude && window.claude.use) {
      try {
        const d = await window.claude.use('downloads');
        if (d) { await d.save({ filename: name, data: text }); toast(`Saved <b>${esc(name)}</b>.`); return; }
      } catch (e) {
        if (e && e.code === 'declined') return;
      }
      toast('Saving isn’t available in this preview. Use the downloaded app.');
      return;
    }
    const url = URL.createObjectURL(new Blob([text], { type: mime }));
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(`Saved <b>${esc(name)}</b> to your downloads.`);
  }

  async function downloadApp() {
    try {
      const d = window.claude && (await window.claude.use('downloads'));
      if (!d) { toast('Downloading isn’t available here.'); return; }
      toast('Preparing the download…');
      const list = await (await fetch('pkg/manifest.json')).json();
      const files = [];
      for (const f of list) {
        const res = await fetch(f.url);
        if (!res.ok) throw new Error('missing ' + f.url);
        files.push({ name: f.name, data: new Uint8Array(await res.arrayBuffer()) });
      }
      const zip = window.SanketZip.makeZip(files);
      await d.save({ filename: 'Sanket.zip', data: new Blob([zip], { type: 'application/zip' }) });
      toast('Unzip it and open <b>Sanket.html</b> in Google Chrome.', 8000);
    } catch (e) {
      if (e && e.code === 'declined') return;
      toast('The download didn’t start. Try again in a moment.');
    }
  }

  // ------------------------------------------------------------------ settings dialog
  function fillSettings() {
    $('#setName').value = settings.name;
    $('#setCap').value = settings.cap;
    $('#setTheme').value = settings.theme;
    $('#setOrig').checked = settings.showOriginal;
    $('#setSens').value = settings.sensitivity;
    $('#setMax').value = String(settings.maxSpeakers);
    $('#setNoise').checked = settings.noiseFilter;
    $('#setToneReview').checked = settings.toneReview;
    $('#setToneLive').checked = settings.toneLive;
    $('#captionSourceField').hidden = !localHost;
    $('#setCaptionSource').value = settings.captionSource;
    for (const k of Object.keys(CUE_INFO)) $('#cue-' + k).checked = !!settings.cues[k];
    $('#setSilence').value = String(settings.silenceSec);
    $('#setSeminarCues').checked = settings.seminarCues;
    $('#setVibrate').checked = settings.vibrate;
    $('#setVibrate').disabled = !Band.vibrationSupported();
    $('#setAutocorrect').checked = settings.autocorrect;
    $('#setTerms').value = settings.customTerms;
    $('#bandConnect').disabled = !Band.bluetoothSupported();
    $('#settingsDownloadRow').hidden = !HOSTED;
  }
  function readSettings() {
    settings.name = $('#setName').value.trim();
    settings.cap = $('#setCap').value;
    settings.theme = $('#setTheme').value;
    settings.showOriginal = $('#setOrig').checked;
    settings.sensitivity = +$('#setSens').value;
    settings.maxSpeakers = +$('#setMax').value;
    settings.noiseFilter = $('#setNoise').checked;
    const toneWas = settings.toneReview || settings.toneLive;
    settings.toneReview = $('#setToneReview').checked;
    settings.toneLive = $('#setToneLive').checked;
    if (engine && toneWas !== (settings.toneReview || settings.toneLive)) engine.setToneModel(settings.toneReview || settings.toneLive ? TONE_MODEL : null);
    if (!settings.toneLive) renderNowTone(null);
    if (localHost) {
      const src = $('#setCaptionSource').value;
      if (src !== settings.captionSource) {
        settings.captionSource = src;
        if (S.running) toast('The new caption source starts the next time you press Start.');
      }
    }
    for (const k of Object.keys(CUE_INFO)) settings.cues[k] = $('#cue-' + k).checked;
    settings.silenceSec = +$('#setSilence').value;
    settings.seminarCues = $('#setSeminarCues').checked;
    settings.vibrate = $('#setVibrate').checked;
    settings.autocorrect = $('#setAutocorrect').checked;
    const termsChanged = settings.customTerms !== $('#setTerms').value;
    settings.customTerms = $('#setTerms').value;
    if (termsChanged) vocab = buildVocab();
    band.phoneVibrate = settings.vibrate;
    saveSettings();
    applyDisplay();
    if (engine) engine.configure(engineSettings());
    rerenderHistory();
    if (S.queue.on) $('#stripLabel').textContent = settings.name ? `${settings.name} is waiting to speak` : 'Waiting to speak';
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    $('#startBtn').addEventListener('click', () => (S.running ? stopListening() : startListening()));
    $('#welcomeStart').addEventListener('click', () => startListening());
    $$('[data-demo]').forEach((b) => b.addEventListener('click', () => playDemo(b.dataset.demo)));
    $('#queueBtn').addEventListener('click', () => toggleQueue());
    $('#newVoiceBtn').addEventListener('click', () => {
      if (engine && S.running) { engine.forceNewSpeaker(); toast('Started a new colour for the person speaking now.'); }
      else toast('Start listening first.');
    });
    $('#missBtn').addEventListener('click', () => {
      const t = nowT();
      const recent = S.lines.filter((l) => l.t >= t - 30);
      $('#missList').innerHTML = recent.length ? recent.map(lineHTML).join('') : '<li class="event">Nothing in the last 30 seconds.</li>';
      $('#missDlg').showModal();
    });
    $('#reviewBtn').addEventListener('click', openReview);
    $('#consentBox').addEventListener('change', (e) => { $('#saveHtml').disabled = $('#saveTxt').disabled = !e.target.checked || !S.lines.length; });
    const stamp = () => new Date(S.sessionStart).toISOString().slice(0, 16).replace(/[T:]/g, '-');
    $('#saveHtml').addEventListener('click', () => saveFile(`sanket-${stamp()}.html`, exportHTML(), 'text/html'));
    $('#saveTxt').addEventListener('click', () => saveFile(`sanket-${stamp()}.txt`, exportText(), 'text/plain'));

    $$('button[data-mode]', $('.topbar')).forEach((b) => b.addEventListener('click', () => {
      settings.mode = b.dataset.mode; saveSettings(); applyDisplay();
      if (engine) engine.configure(engineSettings());
    }));
    $$('button[data-speech]').forEach((b) => b.addEventListener('click', async () => {
      settings.speechLang = b.dataset.speech; saveSettings(); applyDisplay();
      if (S.running) {
        recognizer.setLanguage(settings.speechLang);
        if (settings.capLang !== settings.speechLang) await translator.prepare(settings.speechLang, settings.capLang);
        setStatus('live', statusLine(recognizer.local));
      }
    }));
    $$('button[data-cap]').forEach((b) => b.addEventListener('click', async () => {
      settings.capLang = b.dataset.cap; saveSettings(); applyDisplay();
      S.translateNotice = false;
      if (settings.capLang !== settings.speechLang) {
        const r = await translator.prepare(settings.speechLang, settings.capLang, (p) => setStatus('idle', `Getting translation… ${Math.round(p * 100)}%`));
        if (r !== 'ready' && !S.demo) toast(`Translation needs Chrome 138 or newer on a computer. Captions stay in ${settings.speechLang === 'hi' ? 'Hindi' : 'English'}.`, 8000);
      }
      if (S.running) setStatus('live', statusLine(recognizer.local));
    }));

    $('#settingsBtn').addEventListener('click', () => { fillSettings(); $('#settingsDlg').showModal(); });
    $('#settingsDlg').addEventListener('close', readSettings);
    const openToneAbout = () => $('#toneDlg').showModal();
    $('#toneAboutBtn').addEventListener('click', openToneAbout);
    $('#toneSummary').addEventListener('click', (e) => { if (e.target.closest('[data-tone-about]')) openToneAbout(); });
    $('#bandConnect').addEventListener('click', async () => {
      if (band.connected) { band.disconnect(); return; }
      try { await band.connect(); } catch (e) { if (e && e.name !== 'NotFoundError') toast(esc(e.message || 'Couldn’t connect to the band.')); }
    });
    $('#bandTest').addEventListener('click', () => {
      const keep = band.phoneVibrate; band.phoneVibrate = true; band.cue('test'); band.phoneVibrate = keep;
      if (!band.connected && !Band.vibrationSupported()) toast('No band connected, and this device can’t vibrate.');
    });

    $('#voices').addEventListener('click', (e) => { const b = e.target.closest('[data-voice]'); if (b) openVoice(+b.dataset.voice); });
    const lineClick = (e) => {
      const term = e.target.closest('[data-term]');
      if (term) { const d = vocab.define(term.dataset.term); toast(`<b>${esc(term.dataset.term)}</b> — ${esc(d || 'Your term.')}`, 7000); return; }
      const who = e.target.closest('[data-line]');
      if (who) { const l = S.lines.find((x) => x.uid === +who.dataset.line); if (l) openVoice(l.speakerId, l.uid); }
    };
    $('#history').addEventListener('click', lineClick);
    $('#missList').addEventListener('click', lineClick);

    $('#voiceDlg').addEventListener('close', () => {
      if ($('#voiceDlg').returnValue === 'save' && dlgVoice) {
        const n = $('#voiceName').value.trim();
        if (n) { dlgVoice.name = n; rerenderHistory(); renderVoices(); renderNow(); }
      }
    });
    $('#mergeBtn').addEventListener('click', () => {
      if (!dlgVoice) return;
      const into = +$('#mergeSel').value;
      const name = nameOf(into);
      mergeVoices(into, dlgVoice.id);
      $('#voiceDlg').close();
      toast(`Joined into <b>${esc(name)}</b>.`);
    });
    $('#lineMoveBtn').addEventListener('click', () => {
      if (!dlgLine) return;
      dlgLine.speakerId = +$('#lineMoveSel').value;
      rerenderLine(dlgLine); renderVoices();
      $('#voiceDlg').close();
    });
    $('#makeCurrentBtn').addEventListener('click', () => {
      if (!dlgVoice) return;
      if (engine && S.running) engine.setCurrentSpeaker(dlgVoice.id);
      else onSpeaker(dlgVoice.id, nowT());
      $('#voiceDlg').close();
    });

    $('#downloadBtn').addEventListener('click', downloadApp);
    $('#settingsDownload').addEventListener('click', downloadApp);

    document.addEventListener('keydown', (e) => {
      if (e.target.closest('input, textarea, select, dialog[open]') || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'q') { e.preventDefault(); toggleQueue(); }
      else if (k === 's') { e.preventDefault(); $('#startBtn').click(); }
      else if (k === 'n') { e.preventDefault(); $('#newVoiceBtn').click(); }
      else if (k === 'm') { e.preventDefault(); $('#missBtn').click(); }
    });
  }

  function init() {
    applyDisplay();
    renderVoices();
    wire();
    if (HOSTED) $('#hostedNote').hidden = false;
    if (!Recognizer.supported()) $('#nowHint').textContent = 'Open in Chrome or Edge for captions. The demos work here.';
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (S.current != null) band.colour(colourHex(S.current)); });
    window.Sanket = { S, settings, toggleQueue, playDemo, onSpeaker, onCue, onTone, handleInterim, handleFinal, exportText, exportHTML, openReview,
      get toneModel() { return TONE_MODEL; }, get engine() { return engine; }, get captions() { return recognizer; }, get localHost() { return localHost; } };
    loadToneModel();
    // Served by AccessibilityAI? Then captions can come from its local Whisper model.
    if (LocalCaptions && metaUrl('sanket-host') === 'accessibilityai') {
      LocalCaptions.available().then((st) => {
        localHost = st;
        if (!st) return;
        const where = st.asr_installed ? `Captions from AccessibilityAI (${st.asr_model}) on this computer.` : `Install ${st.asr_model} in AccessibilityAI for private captions; until then captions use the browser.`;
        if (!S.running && !S.demo) $('#nowHint').textContent = where;
        if (!st.asr_installed && settings.captionSource === 'local') settings.captionSource = 'browser';
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
