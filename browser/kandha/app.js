/*
 * Kandha app: wires the microphone, the voice engine, local captions, the haptic scheduler
 * (over the loopback service), the virtual stole, the room diagram and the screens together.
 * Classic script; no inline code anywhere (the companion's CSP forbids it).
 */
(function () {
  'use strict';

  const E = window.SanketEngine;
  const C = window.SanketCaptions;
  const Recognizer = window.SanketRecognizer;
  const Translator = window.SanketTranslator;
  const LocalCaptions = window.SanketLocalCaptions || null;
  const { IntentSource } = window.KandhaIntents;
  const { StoleView, RoomView, timelineSVG, ZONE_ANGLE, ZONE_NAME } = window.KandhaViews;
  const Demo = window.KandhaDemo;

  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const metaUrl = (name) => { const m = document.querySelector(`meta[name="${name}"]`); return m ? m.content : null; };
  const IN_QT = /QtWebEngine/.test(navigator.userAgent);

  // ------------------------------------------------------------------ page settings (this device)
  const STORE = 'kandha.settings.v1';
  const DEFAULTS = {
    name: '', theme: 'system', cap: 'M', showOriginal: true, micId: '',
    sensitivity: 1, maxSpeakers: 6, silenceSec: 4, noiseFilter: false,
    autocorrect: true, customTerms: '', toneReview: true, toneLive: false,
    captionSource: 'local', speechLang: 'en', capLang: 'en', mode: 'seminar', screen: 'live',
  };
  function loadSettings() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(STORE) || '{}')); }
    catch (e) { return JSON.parse(JSON.stringify(DEFAULTS)); }
  }
  const settings = loadSettings();
  function saveSettings() { try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch (e) { /* storage unavailable */ } }

  // ------------------------------------------------------------------ constants
  const CUE_INFO = {
    drop: { label: 'Voice softened', sub: 'Quieter or sadder-sounding than usual', short: 'softened' },
    rise: { label: 'Voice rose', sub: 'Louder or more intense than usual', short: 'rose' },
    hesitation: { label: 'Hesitation', sub: 'Several short pauses', short: 'hesitation' },
    silence: { label: 'Long silence', sub: 'No one is speaking: the floor is open', short: 'silence' },
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
  const ZONE_LONG = { L: 'left shoulder', R: 'right shoulder', B: 'back of the neck', F: 'front', LR: 'both shoulders' };

  // ------------------------------------------------------------------ state
  let TONE_MODEL = null;
  let PATTERNS = null;                 // the shared table (browser/sanket/kandha-patterns.json)
  const K = { settings: null, stole: { state: 'unavailable' }, seats: {}, pending: null, rooms: [], lastRoom: null, loadedRoom: null, queue: { on: false, waited_s: 0 }, virtual: null, latency: null };
  const S = {
    running: false, demo: null, demoStart: 0,
    speakers: new Map(), current: null,
    lines: [], tones: [], changes: [], taps: [], seatChanges: [],
    queue: { on: false, since: 0, timer: null },
    lastFinalT: 0, sessionStart: Date.now(), translateNotice: false, seenSeq: [],
  };
  let uid = 0;
  let engine = null;
  let assembler = new C.CaptionAssembler({ delay: 0.6 });
  let vocab = buildVocab();
  const translator = new Translator();
  const intents = new IntentSource({ onIntent: (i) => queueIntent(i) });
  let localHost = null;
  const mic = { stream: null, ctx: null, node: null, src: null, wake: null };
  const views = {};
  let sse = null, sseState = 'closed';

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
  function clock(t) { t = Math.max(0, Math.round(t)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function speaker(id) { return id == null ? null : S.speakers.get(id) || null; }
  function colourVar(id) { const s = speaker(id); return s ? `var(--s${s.idx + 1})` : 'var(--s0)'; }
  function nameOf(id) { const s = speaker(id); return s ? s.name : 'Someone'; }
  function zoneOf(id) { return id == null ? null : K.seats[String(id)] || null; }
  function arrowAngle(id) { const z = zoneOf(id); return z && ZONE_ANGLE[z] != null ? ZONE_ANGLE[z] : 0; }
  function seatText(id) { const z = zoneOf(id); return z === 'me' ? 'you' : z ? ZONE_NAME[z] : (id == null ? '' : 'no seat yet'); }

  async function api(path, body) {
    const r = await fetch(path, body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(out.error || `Request failed (${r.status}).`), { status: r.status });
    return out;
  }

  function ensureSpeaker(id, name) {
    if (id == null) return null;
    let s = S.speakers.get(id);
    if (!s) {
      const used = new Set(Array.from(S.speakers.values()).map((x) => x.idx));
      let idx = 0;
      while (used.has(idx) && idx < 5) idx++;
      if (used.has(idx)) idx = S.speakers.size % 6;
      s = { id, idx, name: name || `Voice ${S.speakers.size + 1}` };
      S.speakers.set(id, s);
      renderVoices(); renderRooms();
    } else if (name) s.name = name;
    return s;
  }
  function badgeHTML(id, small) {
    const z = zoneOf(id);
    return `<span class="badge${small ? ' badge--sm' : ''}${z && z !== 'me' ? '' : ' is-unseated'}" style="--c:${colourVar(id)}" aria-hidden="true">${z === 'me' ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" fill="currentColor"/><path d="M4 21a8 8 0 0 1 16 0" fill="currentColor"/></svg>' : ARROW_SVG.replace('<svg', `<svg style="transform:rotate(${arrowAngle(id)}deg)"`)}</span>`;
  }
  let toastTimer = null;
  function toast(html, ms) {
    const el = $('#toast');
    el.innerHTML = html;
    el.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('is-on'), ms || 4000);
  }
  function setStatus(state, text) { $('#status').dataset.state = state; $('#statusText').textContent = text; }
  function statusLine(local) {
    const lang = settings.speechLang === 'hi' ? 'Hindi' : 'English';
    return `Listening · ${lang}${local ? ' · Whisper on this computer' : (recognizer === browserCaptions ? ' · browser captions' : ' · voices and taps only')}`;
  }

  // ------------------------------------------------------------------ screens
  const SCREENS = ['live', 'stole', 'seats', 'review', 'settings'];
  function showScreen(name) {
    if (!SCREENS.includes(name)) name = 'live';
    settings.screen = name; saveSettings();
    $('#app').dataset.screen = name;
    for (const s of SCREENS) {
      $('#' + s).hidden = s !== name;
      const tab = $(`#tab-${s}`);
      tab.setAttribute('aria-selected', String(s === name));
      tab.tabIndex = s === name ? 0 : -1;
    }
    if (name === 'review') openReview();
    if (name === 'settings') { fillSettings(); listMicrophones(); }
    if (name === 'seats') renderRooms();
    if (name === 'stole') renderStole();
  }

  // ------------------------------------------------------------------ display
  function applyDisplay() {
    const root = document.documentElement;
    if (settings.theme === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', settings.theme);
    root.setAttribute('data-capsize', settings.cap);
    $('#app').dataset.mode = settings.mode;
    $$('button[data-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === settings.mode)));
    $$('button[data-speech]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.speech === settings.speechLang)));
    const dnd = !!(K.settings && K.settings.dnd);
    $('#dndBtn').setAttribute('aria-pressed', String(dnd));
    $('#setDnd').checked = dnd;
    $('#roomHint').textContent = settings.mode === 'practicum'
      ? 'In practicum the partner is usually in front. Press 4 if the other voice lands elsewhere.'
      : 'Seats light up when that person speaks. Press 1–4 to seat the current voice left, right, behind or in front.';
  }
  function cuesActive() {
    if (!K.settings) return settings.mode === 'practicum';
    if (K.settings.dnd) return false;
    if (settings.mode === 'practicum') return true;
    if (settings.mode === 'seminar') return !!K.settings.seminar_cues;
    return false;
  }
  function cueEnabled(kind) {
    const byMode = K.settings && K.settings.cues_by_mode && K.settings.cues_by_mode[settings.mode];
    const on = byMode ? !!byMode[kind] : kind === 'silence' || settings.mode === 'practicum';
    if (kind === 'silence') return on && !(K.settings && K.settings.dnd);
    return cuesActive() && on;
  }
  function engineSettings() {
    return {
      singleSpeaker: settings.mode === 'lecture',
      maxSpeakers: settings.mode === 'practicum' ? 2 : +settings.maxSpeakers,
      sensitivity: +settings.sensitivity,
      silenceSec: +settings.silenceSec,
      cues: { drop: cueEnabled('drop'), rise: cueEnabled('rise'), hesitation: cueEnabled('hesitation'), silence: cueEnabled('silence') },
    };
  }

  // ------------------------------------------------------------------ rendering: live
  function renderNow(pieces) {
    const id = S.current;
    $('#now').style.setProperty('--c', colourVar(id));
    const badge = $('#nowBadge');
    badge.style.setProperty('--c', colourVar(id));
    badge.classList.toggle('is-unseated', id != null && (!zoneOf(id) || zoneOf(id) === 'me'));
    $('svg', badge).style.transform = `rotate(${arrowAngle(id)}deg)`;
    $('#nowName').textContent = id == null ? (S.running || S.demo ? 'Listening…' : 'No one yet') : nameOf(id);
    $('#nowSeat').textContent = seatText(id);
    if (pieces) {
      const text = $('#nowText');
      text.classList.toggle('is-idle', false);
      text.innerHTML = pieces.map((p) => `<span class="piece" style="--pc:${colourVar(p.speakerId)}">${esc(p.text)}</span>`).join(' ');
    }
    renderRoomLive();
  }
  function renderRoomLive() {
    const voices = Array.from(S.speakers.values());
    if (views.roomLive) views.roomLive.render(K.seats, voices, S.current, K.pending && K.pending.voice);
  }
  function renderRooms() {
    const voices = Array.from(S.speakers.values());
    renderRoomLive();
    if (views.roomBig) views.roomBig.render(K.seats, voices, S.current, K.pending && K.pending.voice);
    const un = voices.filter((v) => !zoneOf(v.id) || zoneOf(v.id) === 'me');
    $('#unseated').innerHTML = un.map((v) => `<li><button type="button" class="chip${views.roomBig && views.roomBig.selected === v.id ? ' is-selected' : ''}" draggable="true" data-chip="${v.id}" style="--c:${colourVar(v.id)}" aria-label="${esc(v.name)}, no seat. Select, then press 1 to 4."><i aria-hidden="true"></i>${esc(v.name)}</button></li>`).join('');
    $('#roomList').innerHTML = K.rooms.length ? K.rooms.map((r) => `<li><b>${esc(r.name)}</b><small>${esc(r.slots.map((z) => z || '–').join(' · ') || 'empty')} · ${esc(r.mode)}</small>${K.loadedRoom === r.name ? '<small>· in use</small>' : ''}<button type="button" class="btn btn--sm" data-room-load="${esc(r.name)}">Use</button><button type="button" class="btn btn--sm btn--ghost" data-room-delete="${esc(r.name)}" aria-label="Delete ${esc(r.name)}">Delete</button></li>`).join('')
      : '<li><small>No rooms saved yet. Seat the voices, name the room and save.</small></li>';
  }
  function renderVoices() {
    const ul = $('#voices');
    const list = Array.from(S.speakers.values());
    $('#voicesEmpty').hidden = list.length > 0;
    ul.innerHTML = list.map((s) => `
      <li><button class="voice${s.id === S.current ? ' is-current' : ''}" data-voice="${s.id}" style="--c:${colourVar(s.id)}" aria-label="${esc(s.name)}, ${esc(seatText(s.id) || 'no seat')}${s.id === S.current ? ', speaking' : ''}">
        ${badgeHTML(s.id, true)}
        <span class="voice__name">${esc(s.name)} <span class="voice__meta">${esc(seatText(s.id))}</span></span>
        ${s.id === S.current ? '<span class="voice__live">Speaking</span>' : `<span class="voice__meta">${countLines(s.id)} lines</span>`}
      </button></li>`).join('');
  }
  function countLines(id) { return S.lines.filter((l) => l.kind === 'speech' && l.speakerId === id).length; }

  // ------------------------------------------------------------------ rendering: stole
  function renderStole() {
    const st = K.stole || {};
    const connected = st.state === 'connected';
    const live = $('#stoleStateLive');
    live.textContent = connected ? (st.name || 'connected') : st.state === 'reconnecting' ? 'reconnecting…' : st.state === 'scanning' ? 'scanning…' : st.state === 'unavailable' ? 'virtual' : 'virtual';
    live.classList.toggle('is-on', connected);
    const status = st.status || null;
    $('#stoleState').textContent = connected ? `Connected to ${st.name || st.paired}.`
      : st.state === 'reconnecting' ? `Reconnecting to ${st.name || st.paired}… (attempt ${st.attempt || 0}${st.error ? ': ' + st.error : ''}). Captions keep going; taps show on the virtual stole.`
      : st.state === 'scanning' ? 'Scanning…'
      : st.state === 'unavailable' ? 'Bluetooth is not available in this build. The virtual stole below shows every tap.'
      : st.paired ? `Not connected to ${st.name || st.paired}. Taps show on the virtual stole.` : 'No stole paired. The virtual stole below shows every tap.';
    $('#stoleBattery').textContent = status ? `${status.battery}%${status.charging ? ' · charging' : ''}${status.low_battery ? ' · low' : ''}` : '—';
    $('#stoleFirmware').textContent = status ? status.firmware : '—';
    const lat = st.latency_ms && st.latency_ms.n ? `${st.latency_ms.last} ms (max ${st.latency_ms.max})` : '—';
    $('#stoleLatency').textContent = lat;
    $('#stolePaired').textContent = st.paired ? `${st.name || ''} ${st.paired}`.trim() : 'none';
    $('#forgetBtn').disabled = !st.paired;
    $('#scanBtn').disabled = st.state === 'unavailable' || st.state === 'scanning';
    const simulated = !!st.simulated;
    $('#linkKind').textContent = simulated ? 'simulated' : (K.settings && K.settings.link === 'bluetooth' ? 'bluetooth · untested' : 'virtual only');
    $('#linkKind').classList.toggle('is-on', connected);
    $('#simulateRow').hidden = !simulated;
    $('#prototypeNote').hidden = !simulated;
    if (K.settings) $('#setLink').value = K.settings.link || 'simulated';
    $('#setMirror').checked = !!(K.settings && K.settings.mirror);
    if (K.settings) for (const input of $$('[data-intensity]')) {
      input.value = K.settings.intensity[input.dataset.intensity];
      input.nextElementSibling.textContent = `${input.value}%`;
    }
  }
  function renderDevices(devices) {
    $('#deviceList').innerHTML = devices.length ? devices.map((d) => `<li><b>${esc(d.name || d.address)}</b><small>${esc(d.address)}${d.rssi != null ? ` · ${d.rssi} dBm` : ''}</small><button type="button" class="btn btn--sm btn--primary" data-pair="${esc(d.address)}" data-pair-name="${esc(d.name || '')}">Pair</button></li>`).join('')
      : '<li><small>No stole found. Is it switched on and within a few metres?</small></li>';
  }

  // ------------------------------------------------------------------ tone estimates
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
    const est = x.accepted ? `<span class="est">Estimate: ${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%${x.demo ? ' (scripted)' : ''}</span>` : (x.demo ? '<span class="est">scripted</span>' : '');
    return `<span class="tone-chip" title="Tone estimate: how this voice sounded compared with how this person usually sounds. A hint, not a fact about feelings."><svg viewBox="0 0 24 24" aria-hidden="true">${info.icon}</svg><span><span class="visually-hidden">Tone: </span><b>${info.label}</b></span>${est}</span>`;
  }
  function toneText(x) {
    if (!x || x.relative === 'learning' || (x.relative === 'usual' && !x.accepted)) return '';
    return `tone: ${TONE_INFO[x.relative].label.toLowerCase()}${x.accepted ? `; estimate ${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%` : ''}${x.demo ? ' (scripted)' : ''}`;
  }
  function onTone(e) {
    const x = { t0: e.t0, t1: e.t1, speakerId: e.speakerId, relative: e.relative, label: e.label, confidence: e.confidence, accepted: !!e.accepted, personal: !!e.personal, shift: e.shift, demo: !!e.demo };
    S.tones.push(x);
    if (!x.demo) recordEvent({ kind: 'tone', t0: round2(x.t0), t1: round2(x.t1), voice: x.speakerId, relative: x.relative, label: x.accepted ? x.label : 'uncertain', confidence: x.accepted ? +x.confidence.toFixed(3) : null });
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

  // ------------------------------------------------------------------ transcript lines
  function lineHTML(l, where) {
    if (l.kind === 'cue') {
      const info = CUE_INFO[l.cue];
      return `<li class="event" data-uid="${l.uid}"><svg class="cue-icon" viewBox="0 0 24 24" aria-hidden="true">${CUE_ICONS[l.cue]}</svg><b>${info.label}</b><span>${l.speakerId != null ? esc(nameOf(l.speakerId)) : ''}</span><span class="line__time">${clock(l.t)}</span></li>`;
    }
    if (l.kind === 'queue') return `<li class="event event--queue" data-uid="${l.uid}"><b>${esc(l.text)}</b><span class="line__time">${clock(l.t)}</span></li>`;
    if (l.kind === 'seat') return `<li class="event event--seat" data-uid="${l.uid}"><b>${esc(nameOf(l.speakerId))}</b><span>${l.zone === 'me' ? 'is you' : l.zone ? 'seated ' + esc(ZONE_NAME[l.zone]) : 'seat cleared'}</span><span class="line__time">${clock(l.t)}</span></li>`;
    const textHTML = l.spans && l.spans.length ? withTerms(l.text, l.spans) : esc(l.text);
    const orig = l.orig && settings.showOriginal ? `<p class="line__orig" lang="${settings.speechLang}">${esc(l.orig)}</p>` : '';
    const showTone = where === 'review' ? settings.toneReview : settings.toneLive;
    const tone = showTone ? toneChipHTML(toneForLine(l)) : '';
    return `<li class="line" data-uid="${l.uid}" style="--c:${colourVar(l.speakerId)}">
      <button class="line__who" data-line="${l.uid}" title="Fix who said this" aria-label="${esc(l.speakerId != null ? nameOf(l.speakerId) : 'Someone')}: fix who said this">${badgeHTML(l.speakerId, true)}<span>${esc(l.speakerId != null ? nameOf(l.speakerId) : 'Someone')}</span></button>
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
  function rerenderLine(l) { const el = $(`[data-uid="${l.uid}"]`, $('#history')); if (el) el.outerHTML = lineHTML(l); }
  function rerenderHistory() { $('#history').innerHTML = S.lines.map((l) => lineHTML(l)).join(''); $('#history').scrollTop = $('#history').scrollHeight; }

  // ------------------------------------------------------------------ session record (Audial session)
  const sessionEvents = [];
  let sessionTimer = 0;
  function round2(v) { return Math.round(v * 100) / 100; }
  function recordEvent(ev) {
    if (S.demo) return;
    sessionEvents.push(ev);
    if (!sessionTimer) sessionTimer = setTimeout(flushSessionEvents, 400);
  }
  async function flushSessionEvents() {
    sessionTimer = 0;
    const sid = localCaptions && localCaptions.session;
    if (!sid || !sessionEvents.length) return;
    const batch = sessionEvents.splice(0, 200);
    try { await api('/api/voice-events', { session_id: sid, events: batch }); }
    catch (e) { /* the session may have stopped; the review on this screen is unaffected */ }
    if (sessionEvents.length) sessionTimer = setTimeout(flushSessionEvents, 400);
  }

  // ------------------------------------------------------------------ live events
  function onSpeaker(id, t, isNew) {
    ensureSpeaker(id);
    const changed = S.current !== id;
    S.current = id;
    assembler.speakerChange(t, id);
    S.changes.push({ t, id });
    recordEvent({ kind: 'voice', t: round2(t), id, new: !!isNew });
    renderNow();
    if (changed) {
      const last = S.tones.filter((x) => x.speakerId === id).pop();
      renderNowTone(last && last.t1 > t - 30 ? last : null);
    }
    renderVoices();
  }
  function onCue(kind, t, speakerId) {
    if (!cueEnabled(kind)) return;
    const info = CUE_INFO[kind];
    appendLine({ uid: ++uid, kind: 'cue', cue: kind, speakerId: speakerId == null ? S.current : speakerId, t });
    recordEvent({ kind: 'cue', t: round2(t), cue: kind, voice: speakerId == null ? S.current : speakerId });
    $('#cueLabel').textContent = info.label;
    $('#cueSub').textContent = `${speakerId != null ? nameOf(speakerId) + ' · ' : ''}${info.sub}`;
  }
  function handleInterim(text) { if (!text) return; renderNow(assembler.interim(text, nowT())); }
  async function handleFinal(text, opts) {
    opts = opts || {};
    const pieces = opts.start != null ? assembler.timed(text, opts.start, opts.end) : assembler.final(text, nowT());
    for (const p of pieces) {
      const speechLang = opts.lang || settings.speechLang;
      let body = p.text, spans = [];
      if (speechLang === 'en') { const r = vocab.process(body, { autocorrect: settings.autocorrect }); body = r.text; spans = r.spans; body = body.charAt(0).toUpperCase() + body.slice(1); }
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
      if (!S.translateNotice) { S.translateNotice = true; toast(IN_QT ? 'Translation is off in this window: nothing on this computer can translate without sending text away. Captions stay in the spoken language.' : `Translation needs Chrome 138 or newer. Showing ${settings.speechLang === 'hi' ? 'Hindi' : 'English'} captions instead.`, 8000); }
      return;
    }
    const out = await translator.translate(line.text);
    if (!out) return;
    line.orig = line.text; line.text = out; line.spans = []; line.lang = settings.capLang;
    rerenderLine(line);
  }

  // ------------------------------------------------------------------ intents -> scheduler -> stole
  let pendingIntents = [], flushing = false;
  function queueIntent(intent) {
    pendingIntents.push({ kind: intent.kind, voice: intent.voice == null ? null : intent.voice, cue: intent.cue || null, t: intent.t == null ? null : round2(intent.t), new: !!intent.new, age_ms: 0, sent: Date.now(), demo: !!S.demo });
    if (!flushing) { flushing = true; queueMicrotask(flushIntents); }
  }
  async function flushIntents() {
    flushing = false;
    if (!pendingIntents.length) return;
    const batch = pendingIntents.splice(0, 50);
    try {
      const out = await api('/api/kandha/intents', { intents: batch, current: S.current });
      for (const p of out.played || []) onHaptic(p);
    } catch (e) {
      // the service is unreachable: the screen still flashes the zone the tap would have used
      for (const i of batch) if (i.kind === 'speaker' || i.kind === 'new_voice') flashZone(i.kind === 'new_voice' ? 'F' : zoneOf(i.voice) || 'F');
      setStatus($('#status').dataset.state, 'Stole service unreachable · captions continue');
    }
  }
  function flashZone(zone) { for (const v of ['stoleLive', 'stoleBig']) if (views[v]) views[v].pulse({ zones: zone, duration_ms: 160, intensity: 200 }); }
  function onHaptic(record) {
    if (record.seq != null) {
      if (S.seenSeq.includes(record.seq + ':' + record.at)) return;
      S.seenSeq.push(record.seq + ':' + record.at); if (S.seenSeq.length > 64) S.seenSeq.shift();
    }
    if (record.stopped || !record.zones) { for (const v of ['stoleLive', 'stoleBig', 'stoleLearn']) if (views[v]) views[v].clear(); return; }
    const segments = record.segments || (K.virtual && null);
    for (const v of ['stoleLive', 'stoleBig', 'stoleLearn']) if (views[v]) views[v].pulse(record);
    const pattern = PATTERNS && PATTERNS.patterns.find((p) => p.key === record.pattern);
    const t = nowT();
    S.taps.push({ t, zones: record.zones, pattern: record.pattern, duration_ms: record.duration_ms, voice: record.voice, device: record.device, intent: record.intent, app_latency_ms: record.app_latency_ms });
    if (record.intent !== 'test') {
      recordEvent({ kind: 'haptic', t: round2(t), zones: record.zones, pattern: record.pattern, voice: record.voice == null ? null : record.voice });
      $('#cueLabel').textContent = pattern ? pattern.name : record.pattern;
      $('#cueSub').textContent = `${ZONE_LONG[record.zones] || record.zones}${record.voice != null && S.speakers.has(record.voice) ? ' · ' + nameOf(record.voice) : ''} · ${record.device === 'stole' ? 'on the stole' : 'virtual stole'}${record.app_latency_ms != null ? ` · ${Math.round(record.app_latency_ms)} ms` : ''}`;
    }
    for (const row of $$('.zonerow')) {
      const z = row.dataset.zone;
      if (z === record.zones || (z !== 'LR' && record.zones.includes(z))) { row.classList.add('is-on'); setTimeout(() => row.classList.remove('is-on'), Math.min(1600, record.duration_ms || 150)); }
    }
  }

  // ------------------------------------------------------------------ server stream
  function openStream() {
    if (sse) sse.close();
    sse = new EventSource('/api/kandha/stream');
    sseState = 'connecting';
    sse.onopen = () => { sseState = 'open'; };
    sse.onerror = () => { sseState = 'error'; };
    const on = (kind, fn) => sse.addEventListener(kind, (e) => { try { fn(JSON.parse(e.data)); } catch (err) { /* malformed */ } });
    on('state', (data) => applyServerState(data));
    on('haptic', (data) => onHaptic(data));
    on('input', (data) => toast(`Stole pad <b>${esc(data.pad)}</b>: ${esc(data.gesture)}${data.device === 'virtual' ? ' (on screen)' : ''}`, 2500));
    on('queue', (data) => applyQueue(data));
    on('seat', (data) => applySeat(data));
    on('settings', (data) => { K.settings = data.settings; settings.mode = K.settings.mode; saveSettings(); applyDisplay(); renderStole(); fillSettings(); if (engine) engine.configure(engineSettings()); });
    on('stole_state', (data) => { K.stole = Object.assign({}, K.stole, data, { status: K.stole.status }); if (data.state === 'connected') K.stole.error = null; renderStole(); });
    on('stole_status', (data) => { if (data.device === 'stole') { K.stole = Object.assign({}, K.stole, { status: data }); renderStole(); } });
    on('stole_connected', (data) => { toast(`Stole connected: <b>${esc(data.name || data.address)}</b>.`); K.stole.state = 'connected'; renderStole(); });
    on('stole_error', (data) => { K.stole.error = data.error; renderStole(); });
    on('stole_scan', (data) => renderDevices(data.devices || []));
    on('session', () => {});
  }
  function applyServerState(state) {
    K.settings = state.settings; K.stole = state.stole || K.stole; K.virtual = state.virtual;
    K.seats = (state.seats && state.seats.seats) || {}; K.pending = state.seats && state.seats.pending; K.rooms = (state.seats && state.seats.rooms) || []; K.lastRoom = state.seats && state.seats.last_room; K.loadedRoom = state.seats && state.seats.loaded_room;
    K.queue = state.queue || K.queue; K.latency = state.latency_ms;
    if (K.settings.mode !== settings.mode) { settings.mode = K.settings.mode; saveSettings(); }
    applyDisplay(); renderStole(); renderVoices(); renderRooms(); renderNow(); fillSettings();
    if (K.queue.on !== S.queue.on) applyQueue({ on: K.queue.on, source: 'state', changed: true });
  }
  function applyQueue(data) {
    const on = !!data.on;
    if (data.reminder) { toast(`Still waiting to speak: ${clock(data.waited_s)}`, 3000); return; }
    const changed = on !== S.queue.on;
    S.queue.on = on;
    const strip = $('#strip');
    strip.classList.toggle('is-on', on);
    $('#queueBtn').setAttribute('aria-pressed', String(on));
    $('#queueText').textContent = on ? 'Waiting… tap to cancel' : 'I want to speak';
    $('#stripLabel').textContent = settings.name ? `${settings.name} is waiting to speak` : 'Waiting to speak';
    clearInterval(S.queue.timer);
    if (on) {
      S.queue.since = Date.now() - (data.waited_s || 0) * 1000;
      $('#stripTime').textContent = clock((Date.now() - S.queue.since) / 1000);
      S.queue.timer = setInterval(() => { $('#stripTime').textContent = clock((Date.now() - S.queue.since) / 1000); }, 500);
    }
    if (changed && data.source !== 'state') {
      const t = nowT();
      if (on) appendLine({ uid: ++uid, kind: 'queue', text: `${settings.name || 'You'} asked to speak${/pad/.test(data.source || '') ? ' (stole pad)' : ''}`, t });
      else if (S.queue.since) appendLine({ uid: ++uid, kind: 'queue', text: `Turn taken after ${Math.round((Date.now() - S.queue.since) / 1000)} s`, t });
      recordEvent({ kind: 'queue', t: round2(t), on });
    }
  }
  function applySeat(data) {
    if (data.seats) K.seats = data.seats;
    if (data.rooms) { K.rooms = data.rooms; K.loadedRoom = data.loaded_room; }
    if (data.voice != null && 'zone' in data && data.action !== 'no-window' && data.action !== 'no-current') {
      K.seats[String(data.voice)] = data.zone;
      if (data.changed !== false && data.source !== 'new-voice') {
        const t = nowT();
        S.seatChanges.push({ t, voice: data.voice, zone: data.zone });
        if (data.source && data.source !== 'room-load' && data.source !== 'mode-default') {
          appendLine({ uid: ++uid, kind: 'seat', speakerId: data.voice, zone: data.zone, t });
          recordEvent({ kind: 'seat', t: round2(t), voice: data.voice, zone: data.zone });
        }
      }
    }
    K.pending = data.pending !== undefined ? data.pending : (data.source === 'new-voice' ? { voice: data.voice } : K.pending);
    if (data.action === 'no-window') toast('No new voice is waiting for a seat. Double-tap a pad to move the person speaking now.', 3500);
    renderNow(); renderVoices(); renderRooms(); rerenderHistory();
  }

  async function toggleQueue(force) {
    const on = force === undefined ? !S.queue.on : !!force;
    if (on === S.queue.on) return;
    try { applyQueue(await api('/api/kandha/queue', { on, source: 'screen' })); }
    catch (e) { applyQueue({ on, source: 'screen', changed: true }); }
  }
  async function assignSeat(voice, zone, source) {
    if (voice == null) { toast('No one is speaking yet.'); return; }
    try { await api('/api/kandha/seats', { voice, zone, source: source || 'screen' }); }
    catch (e) { toast(esc(e.message)); }
  }
  async function setMode(mode) {
    settings.mode = mode; saveSettings(); applyDisplay();
    if (engine) engine.configure(engineSettings());
    try { await api('/api/kandha/settings', { mode }); } catch (e) { toast(esc(e.message)); }
  }
  async function updateServerSettings(changes) {
    try { const out = await api('/api/kandha/settings', changes); K.settings = out; applyDisplay(); renderStole(); if (engine) engine.configure(engineSettings()); }
    catch (e) { toast(esc(e.message)); renderStole(); }
  }

  // ------------------------------------------------------------------ microphone + engine
  async function listMicrophones() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((d) => d.kind === 'audioinput');
      const sel = $('#setMic');
      const current = settings.micId;
      sel.innerHTML = '<option value="">Default microphone</option>' + inputs.map((d, i) => `<option value="${esc(d.deviceId)}">${esc(d.label || `Microphone ${i + 1}`)}</option>`).join('');
      sel.value = inputs.some((d) => d.deviceId === current) ? current : '';
    } catch (e) { /* no device access yet */ }
  }
  async function startAudio() {
    const audio = { echoCancellation: true, noiseSuppression: !!settings.noiseFilter, autoGainControl: false, channelCount: 1 };
    if (settings.micId) audio.deviceId = { ideal: settings.micId };
    const stream = await navigator.mediaDevices.getUserMedia({ audio });
    let ctx;
    try { ctx = new AudioContext({ sampleRate: 16000 }); } catch (e) { ctx = new AudioContext(); }
    const src = ctx.createMediaStreamSource(stream);
    engine = new E.VoiceEngine({ sampleRate: ctx.sampleRate, settings: engineSettings(), onEvent: onEngineEvent, toneModel: settings.toneReview || settings.toneLive ? TONE_MODEL : null });
    const rate = ctx.sampleRate;
    const take = (x) => { if (engine) engine.process(x); if (recognizer.feed) recognizer.feed(x, rate); };
    let node = null;
    const workletUrl = metaUrl('kandha-worklet');
    if (workletUrl) {
      try { await ctx.audioWorklet.addModule(workletUrl); node = new AudioWorkletNode(ctx, 'sanket-tap'); node.port.onmessage = (e) => take(e.data); } catch (e) { node = null; }
    }
    if (!node) { node = ctx.createScriptProcessor(1024, 1, 1); node.onaudioprocess = (e) => take(e.inputBuffer.getChannelData(0).slice(0)); }
    const sink = ctx.createGain(); sink.gain.value = 0;
    src.connect(node); node.connect(sink); sink.connect(ctx.destination);
    if (ctx.state === 'suspended') await ctx.resume();
    Object.assign(mic, { stream, ctx, node, src });
    listMicrophones();
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
    intents.handle(e);
    switch (e.type) {
      case 'speaker': onSpeaker(e.id, e.t, e.isNew); break;
      case 'cue': onCue(e.kind, e.t, e.speakerId); break;
      case 'tone': onTone(e); break;
      case 'level':
        meterDb = e.db;
        if (!meterRaf) meterRaf = requestAnimationFrame(() => { meterRaf = 0; $('#meterFill').style.width = `${Math.max(0, Math.min(100, ((meterDb + 70) / 55) * 100))}%`; });
        break;
      default: break;
    }
  }

  // ------------------------------------------------------------------ captions
  const captionHandlers = {
    onInterim: (text) => handleInterim(text),
    onFinal: (text, meta) => handleFinal(text, meta && meta.start != null ? { start: meta.start, end: meta.end } : undefined),
    onStatus: (s, info) => { if (s === 'listening' && S.running) setStatus('live', statusLine(info && info.local)); },
    onError: (code, msg) => {
      toast(esc(msg), 9000);
      if (code === 'network' || code === 'unsupported' || code === 'local-missing' || code === 'local-busy') setStatus('live', 'Listening · voices and taps only');
      else if (!recognizer.active && S.running) setStatus('error', 'Captions stopped · voices and taps continue');
    },
  };
  const browserCaptions = new Recognizer(captionHandlers);
  const localCaptions = LocalCaptions ? new LocalCaptions(captionHandlers) : null;
  const noCaptions = { active: false, local: false, start: async () => { captionHandlers.onError('unsupported', 'No caption engine is available: install the Whisper model in Audial-AI (Setup & models). Voice colours and stole taps keep working.'); return false; }, stop() {}, setLanguage() {}, feed: null };
  let recognizer = noCaptions;
  function chooseCaptions() {
    if (localCaptions && localHost && localHost.asr_installed && settings.captionSource === 'local') recognizer = localCaptions;
    else if (Recognizer.supported()) recognizer = browserCaptions;
    else recognizer = localCaptions && localHost ? localCaptions : noCaptions;
    return recognizer;
  }

  async function startListening() {
    if (S.demo) stopDemo();
    hideWelcome();
    setStatus('idle', 'Starting…');
    if (settings.capLang !== settings.speechLang && !IN_QT) {
      const r = await translator.prepare(settings.speechLang, settings.capLang, (p) => setStatus('idle', `Getting translation… ${Math.round(p * 100)}%`));
      if (r !== 'ready') S.translateNotice = false;
    }
    let track = null;
    try { track = await startAudio(); }
    catch (err) {
      const blocked = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
      setStatus('error', blocked ? 'Microphone blocked' : 'No microphone');
      toast(blocked ? 'Kandha needs the microphone. Allow it for this page, then press Start.' : 'No microphone was found. Plug one in or check your sound settings, then press Start.', 9000);
      showWelcome();
      return;
    }
    resetSession();
    try { await api('/api/kandha/session/new', {}); } catch (e) { /* the service may be down; taps fall back to the screen */ }
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
    flushSessionEvents();
    recognizer.stop();
    stopAudio();
    S.running = false;
    $('#startBtn').dataset.running = 'false';
    $('#startLabel').textContent = 'Start';
    setStatus('idle', 'Paused');
    releaseWake();
  }
  async function requestWake() { try { if (navigator.wakeLock) mic.wake = await navigator.wakeLock.request('screen'); } catch (e) { /* not allowed */ } }
  function releaseWake() { try { mic.wake && mic.wake.release(); } catch (e) { /* ignore */ } mic.wake = null; }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && S.running) requestWake(); });

  // ------------------------------------------------------------------ demo
  function resetSession() {
    S.speakers.clear(); S.current = null; S.lines = []; S.changes = []; S.tones = []; S.taps = []; S.seatChanges = []; S.seenSeq = [];
    K.seats = {}; K.pending = null;
    intents.reset();
    renderNowTone(null);
    assembler = new C.CaptionAssembler({ delay: 0.6 });
    $('#history').innerHTML = '';
    $('#cueLabel').textContent = 'No taps yet';
    $('#cueSub').textContent = 'The stole shows every tap here, even with no stole connected.';
    renderVoices(); renderRooms(); renderNow();
  }
  async function playDemo(key) {
    if (S.running) stopListening();
    if (S.demo) stopDemo();
    hideWelcome();
    resetSession();
    const scene = Demo.SCENES[key];
    settings.mode = scene.mode;
    applyDisplay();
    try { await api('/api/kandha/session/new', {}); await api('/api/kandha/settings', { mode: scene.mode }); } catch (e) { /* offline: the screen still shows the demo */ }
    S.demoStart = performance.now();
    let demoOwnVoice = null;
    setStatus('demo', `Demo · ${scene.title}`);
    $('#nowHint').textContent = 'Demo: no microphone in use. Taps are scripted through the real scheduler.';
    let silenceTimer = null;
    const demo = new Demo({
      begin: (sc) => {
        sc.speakers.forEach((s) => ensureSpeaker(s.id, s.name));
        // the scripted seats stand in for pad presses; a real session asks you to seat each new voice
        setTimeout(() => { for (const [id, zone] of Object.entries(sc.room)) assignSeat(+id, zone, 'demo'); }, 400);
        // the wearer's own voice has no seat: clear whatever the mode default gave it once it appears
        demoOwnVoice = sc.own || null;
      },
      speaker: (id, isNew) => {
        clearTimeout(silenceTimer); const t = nowT(); onSpeaker(id, t, isNew);
        queueIntent({ kind: isNew ? 'new_voice' : 'speaker', voice: id, t, new: isNew });
        if (isNew && id === demoOwnVoice) setTimeout(() => assignSeat(id, 'me', 'demo'), 250);
      },
      interim: (text) => handleInterim(text),
      final: (text) => handleFinal(text, { lang: settings.capLang }),
      cue: (kind) => { onCue(kind, nowT(), S.current); queueIntent({ kind: 'cue', cue: kind, voice: S.current, t: nowT() }); },
      tone: (id, tone) => {
        const line = S.lines.filter((l) => l.kind === 'speech' && l.speakerId === id).pop();
        onTone(Object.assign({ t0: line ? line.t : nowT() - 2, t1: nowT(), speakerId: id, personal: true, demo: true, accepted: !!tone.label, label: tone.label || 'uncertain' }, tone));
      },
      queue: (on) => toggleQueue(on),
      silence: (ms) => {
        renderNow([]);
        $('#nowText').classList.add('is-idle'); $('#nowText').textContent = '…';
        silenceTimer = setTimeout(() => { onCue('silence', nowT(), null); queueIntent({ kind: 'silence', t: nowT(), voice: null }); }, Math.min(ms - 150, settings.silenceSec * 1000));
      },
      end: () => { S.demo = null; setStatus('idle', 'Demo finished'); $('#nowHint').textContent = 'Press Start to caption a real room.'; },
    });
    S.demo = demo;
    demo.play(key, { lang: settings.capLang, aloud: $('#demoAloud').checked });
  }
  function stopDemo() { if (S.demo) { S.demo.stop(); S.demo = null; } toggleQueue(false); }
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
    for (const b of $$('#voiceSeatRow [data-seat]')) b.setAttribute('aria-pressed', String((zoneOf(id) || '') === b.dataset.seat));
    $('#mergeSel').innerHTML = others.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join('');
    $('#mergeBtn').disabled = !s || !others.length;
    $('#mergeSel').disabled = !others.length;
    $('#lineMoveField').hidden = !dlgLine;
    $('#lineMoveSel').innerHTML = Array.from(S.speakers.values()).map((o) => `<option value="${o.id}"${o.id === id ? ' selected' : ''}>${esc(o.name)}</option>`).join('');
    $('#makeCurrentBtn').disabled = !s || !(S.running || S.demo);
    $('#voiceDlg').showModal();
  }
  async function mergeVoices(keepId, dropId) {
    for (const l of S.lines) if (l.speakerId === dropId) l.speakerId = keepId;
    for (const c of S.changes) if (c.id === dropId) c.id = keepId;
    for (const x of S.tones) if (x.speakerId === dropId) x.speakerId = keepId;
    assembler.relabel(dropId, keepId);
    if (engine) engine.mergeSpeakers(keepId, dropId);
    if (S.current === dropId) S.current = keepId;
    S.speakers.delete(dropId);
    try { const snap = await api('/api/kandha/merge', { keep: keepId, drop: dropId }); K.seats = snap.seats; } catch (e) { /* seats stay as they are */ }
    rerenderHistory(); renderVoices(); renderNow(); renderRooms();
  }

  // ------------------------------------------------------------------ review & saving
  function sessionLength() { const last = S.lines.length ? S.lines[S.lines.length - 1].t : 0; return Math.max(nowT(), last, S.taps.length ? S.taps[S.taps.length - 1].t : 0, 1); }
  function timelineData(literal) {
    const light = ['#1a66c2', '#c2412d', '#0b8570', '#6b3fc4', '#4e7f12', '#b8306f'];
    return {
      length: sessionLength(), clock, name: nameOf,
      colour: (id, lit) => { if (!lit) return colourVar(id); const s = speaker(id); return s ? light[s.idx] : '#4e5c6b'; },
      changes: S.changes, cues: S.lines.filter((l) => l.kind === 'cue').map((l) => ({ t: l.t, label: CUE_INFO[l.cue].label, short: CUE_INFO[l.cue].short })),
      showTone: settings.toneReview && S.tones.some((x) => x.personal),
      tones: S.tones.filter((x) => x.personal && x.relative !== 'learning').map((x) => Object.assign({ text: TONE_INFO[x.relative].label + (x.accepted ? ` · estimate ${EMOTION_NAME[x.label] || x.label} ${Math.round(x.confidence * 100)}%` : '') + (x.demo ? ' (scripted)' : '') }, x)),
      queue: S.lines.filter((l) => l.kind === 'queue' && /asked/.test(l.text)).map((l) => ({ t: l.t, text: 'Asked to speak' })),
      taps: S.taps.filter((h) => h.intent !== 'test'), seats: S.seatChanges,
    };
  }
  function openReview() {
    const speech = S.lines.filter((l) => l.kind === 'speech');
    const cues = S.lines.filter((l) => l.kind === 'cue');
    const taps = S.taps.filter((h) => h.intent !== 'test');
    $('#reviewSummary').textContent = S.lines.length || taps.length
      ? `${clock(sessionLength())} · ${S.speakers.size} voice${S.speakers.size === 1 ? '' : 's'} · ${speech.length} lines · ${cues.length} tone cue${cues.length === 1 ? '' : 's'} · ${taps.length} tap${taps.length === 1 ? '' : 's'}${S.tones.some((x) => x.demo) ? ' · demo (scripted estimates)' : ''}`
      : 'Nothing to review yet. Start listening or watch a demo first.';
    $('#timelineWrap').innerHTML = timelineSVG(timelineData(false));
    $('#reviewLegend').innerHTML = Array.from(S.speakers.values()).map((s) => `<span><i class="swatch" style="--c:${colourVar(s.id)}"></i>${esc(s.name)}${zoneOf(s.id) === 'me' ? ' · you' : zoneOf(s.id) ? ' · ' + esc(ZONE_NAME[zoneOf(s.id)]) : ''}</span>`).join('') +
      '<span><i class="swatch" style="--c:var(--signal)"></i>Asked to speak</span><span><i class="swatch" style="--c:var(--tap)"></i>Stole tap</span>';
    renderToneSummary();
    $('#reviewList').innerHTML = S.lines.map((l) => lineHTML(l, 'review')).join('');
    $('#consentBox').checked = false;
    updateSaveButtons();
  }
  function updateSaveButtons() {
    const ok = $('#consentBox').checked && (S.lines.length > 0 || S.taps.length > 0);
    for (const id of ['saveHtml', 'saveTxt', 'saveSession']) $('#' + id).disabled = !ok;
    for (const b of $$('[data-export]')) b.disabled = !ok || !localHost;
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
    box.innerHTML = `<h3>Tone estimates</h3>${rows ? `<ul>${rows}</ul>` : '<p class="fineprint">Kandha was still learning these voices. It needs to hear someone a few times before estimating their tone.</p>'}
      <p class="fineprint">${demo ? 'Demo: these estimates are scripted to show the feature. ' : ''}Compared with how each person usually sounds. A hint to look again, not a fact about feelings. <button type="button" class="linkish" data-tone-about>How accurate is this?</button></p>`;
  }
  function exportText() {
    const head = `Kandha session — ${new Date(S.sessionStart).toLocaleString()}\n\n`;
    const rows = S.lines.map((l) => {
      if (l.kind === 'speech') { const tone = settings.toneReview ? toneText(toneForLine(l)) : ''; return [l.t, `[${clock(l.t)}] ${nameOf(l.speakerId)}: ${l.text}${l.orig ? `\n          (${l.orig})` : ''}${tone ? `\n          [${tone}]` : ''}`]; }
      if (l.kind === 'cue') return [l.t, `[${clock(l.t)}] — ${CUE_INFO[l.cue].label}${l.speakerId != null ? ` (${nameOf(l.speakerId)})` : ''}`];
      if (l.kind === 'seat') return [l.t, `[${clock(l.t)}] — ${nameOf(l.speakerId)} ${l.zone === 'me' ? 'is you' : l.zone ? 'seated ' + ZONE_NAME[l.zone] : 'seat cleared'}`];
      return [l.t, `[${clock(l.t)}] — ${l.text}`];
    }).concat(S.taps.filter((h) => h.intent !== 'test').map((h) => [h.t, `[${clock(h.t)}] ~ stole: ${h.pattern} on ${ZONE_LONG[h.zones] || h.zones}`]));
    return head + rows.sort((a, b) => a[0] - b[0]).map((r) => r[1]).join('\n') + '\n';
  }
  function exportHTML() {
    const light = ['#1a66c2', '#c2412d', '#0b8570', '#6b3fc4', '#4e7f12', '#b8306f'];
    const c = (id) => { const s = speaker(id); return s ? light[s.idx] : '#4e5c6b'; };
    const rows = S.lines.map((l) => {
      if (l.kind === 'speech') { const tone = settings.toneReview ? toneText(toneForLine(l)) : ''; return `<li style="border-left:4px solid ${c(l.speakerId)}"><span class="t">${clock(l.t)}</span><b style="color:${c(l.speakerId)}">${esc(nameOf(l.speakerId))}</b><p>${esc(l.text)}</p>${l.orig ? `<p class="o">${esc(l.orig)}</p>` : ''}${tone ? `<p class="o tone">${esc(tone.charAt(0).toUpperCase() + tone.slice(1))}</p>` : ''}</li>`; }
      if (l.kind === 'cue') return `<li class="cue"><span class="t">${clock(l.t)}</span><b>${CUE_INFO[l.cue].label}</b> ${l.speakerId != null ? esc(nameOf(l.speakerId)) : ''}</li>`;
      if (l.kind === 'seat') return `<li class="cue"><span class="t">${clock(l.t)}</span><b>${esc(nameOf(l.speakerId))}</b> ${l.zone === 'me' ? 'is you' : l.zone ? 'seated ' + ZONE_NAME[l.zone] : 'seat cleared'}</li>`;
      return `<li class="cue q"><span class="t">${clock(l.t)}</span><b>${esc(l.text)}</b></li>`;
    }).join('\n');
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kandha session ${new Date(S.sessionStart).toLocaleDateString()}</title>
<style>body{font:17px/1.5 system-ui,sans-serif;color:#111820;background:#f3f5f7;margin:0;padding:24px max(16px,4vw)}h1{font-size:24px;margin:0 0 4px}p.m{color:#4e5c6b;margin:0 0 16px}.tl{overflow-x:auto;background:#fff;border:1px solid #d3dbe3;border-radius:12px;margin-bottom:16px}ol{list-style:none;padding:0;display:grid;gap:8px;max-width:860px}li{background:#fff;border-radius:10px;padding:10px 14px;border:1px solid #d3dbe3}li p{margin:4px 0 0}li .o{color:#4e5c6b;font-size:14px}.t{float:right;color:#4e5c6b;font-family:ui-monospace,monospace;font-size:13px}.cue{background:#eaeef2;border-radius:999px;padding:6px 14px}.q b{color:#9a6200}</style></head>
<body><h1>Kandha session</h1><p class="m">${esc(new Date(S.sessionStart).toLocaleString())} · ${clock(sessionLength())} · ${esc(Array.from(S.speakers.values()).map((s) => s.name + (zoneOf(s.id) ? ` (${ZONE_NAME[zoneOf(s.id)]})` : '')).join(', '))}</p>
<div class="tl">${timelineSVG(timelineData(true), { literal: true })}</div><ol>${rows}</ol><p class="m">Tone cues describe what a voice did, not what anyone felt.${settings.toneReview && S.tones.length ? ' Tone estimates compare each voice with how that person usually sounds; they were learned from acted speech (CREMA-D) and are hints, not facts about feelings.' : ''}${S.tones.some((x) => x.demo) ? ' This was a demo: the estimates are scripted.' : ''} Stole taps are listed on the timeline. Saved with the consent of everyone present.</p></body></html>`;
  }
  function saveFile(name, data, mime) {
    const url = URL.createObjectURL(data instanceof Blob ? data : new Blob([data], { type: mime }));
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(`Saved <b>${esc(name)}</b> to your downloads.`);
  }
  const stamp = () => new Date(S.sessionStart).toISOString().slice(0, 16).replace(/[T:]/g, '-');
  async function exportAudial(format) {
    await flushSessionEvents();
    try {
      const r = await fetch(`/api/export?format=${format}`);
      if (!r.ok) throw new Error('Export failed.');
      saveFile(`kandha-${stamp()}.${format}`, await r.blob());
    } catch (e) { toast(esc(e.message)); }
  }
  async function saveToSessions() {
    await flushSessionEvents();
    try {
      const out = await api('/api/kandha/session/save', { consent: $('#consentBox').checked, title: `Kandha ${settings.mode} ${new Date(S.sessionStart).toLocaleString()}` });
      toast(`Saved to Audial-AI sessions: <b>${esc(out.title)}</b> (${out.captions} captions, ${out.voice_events} events).`, 6000);
    } catch (e) { toast(esc(e.message), 6000); }
  }

  // ------------------------------------------------------------------ settings screen
  let settingsFilling = false;
  function fillSettings() {
    settingsFilling = true;
    $('#setName').value = settings.name;
    $('#setCap').value = settings.cap;
    $('#setTheme').value = settings.theme;
    $('#setNoise').checked = settings.noiseFilter;
    $('#setToneReview').checked = settings.toneReview;
    $('#setToneLive').checked = settings.toneLive;
    $('#setSens').value = settings.sensitivity;
    $('#setMax').value = String(settings.maxSpeakers);
    $('#setSilence').value = String(settings.silenceSec);
    $('#setAutocorrect').checked = settings.autocorrect;
    $('#setTerms').value = settings.customTerms;
    $('#setOrig').checked = settings.showOriginal;
    $('#setOrig').disabled = IN_QT;
    if (K.settings) {
      for (const input of $$('#cueTable input')) input.checked = !!(K.settings.cues_by_mode[input.dataset.cmode] || {})[input.dataset.cue];
      $('#setSeminarCues').checked = !!K.settings.seminar_cues;
      $('#setReminder').value = String(K.settings.queue_reminder_s);
      $('#setLastLayout').checked = !!K.settings.use_last_layout;
    }
    settingsFilling = false;
  }
  function readSettings() {
    if (settingsFilling) return;
    settings.name = $('#setName').value.trim();
    settings.cap = $('#setCap').value;
    settings.theme = $('#setTheme').value;
    settings.micId = $('#setMic').value;
    settings.noiseFilter = $('#setNoise').checked;
    const toneWas = settings.toneReview || settings.toneLive;
    settings.toneReview = $('#setToneReview').checked;
    settings.toneLive = $('#setToneLive').checked;
    if (engine && toneWas !== (settings.toneReview || settings.toneLive)) engine.setToneModel(settings.toneReview || settings.toneLive ? TONE_MODEL : null);
    if (!settings.toneLive) renderNowTone(null);
    settings.sensitivity = +$('#setSens').value;
    settings.maxSpeakers = +$('#setMax').value;
    settings.silenceSec = +$('#setSilence').value;
    settings.autocorrect = $('#setAutocorrect').checked;
    const termsChanged = settings.customTerms !== $('#setTerms').value;
    settings.customTerms = $('#setTerms').value;
    if (termsChanged) vocab = buildVocab();
    settings.showOriginal = $('#setOrig').checked;
    saveSettings();
    applyDisplay();
    if (engine) engine.configure(engineSettings());
    rerenderHistory();
    if (S.queue.on) $('#stripLabel').textContent = settings.name ? `${settings.name} is waiting to speak` : 'Waiting to speak';
  }
  function readServerSettings() {
    if (settingsFilling || !K.settings) return;
    const cues_by_mode = {};
    for (const input of $$('#cueTable input')) { (cues_by_mode[input.dataset.cmode] = cues_by_mode[input.dataset.cmode] || {})[input.dataset.cue] = input.checked; }
    updateServerSettings({ cues_by_mode, seminar_cues: $('#setSeminarCues').checked, queue_reminder_s: +$('#setReminder').value, use_last_layout: $('#setLastLayout').checked });
  }

  // ------------------------------------------------------------------ learn the taps
  const learn = { step: 0 };
  function learnSteps() { return PATTERNS ? PATTERNS.tutorial_order.map((key) => PATTERNS.patterns.find((p) => p.key === key)).filter(Boolean) : []; }
  function showLearnStep(play) {
    const steps = learnSteps();
    if (!steps.length) return;
    learn.step = Math.max(0, Math.min(steps.length - 1, learn.step));
    const p = steps[learn.step];
    $('#learnProgress').textContent = `Step ${learn.step + 1} of ${steps.length}`;
    $('#learnName').textContent = p.name;
    $('#learnMeaning').textContent = p.meaning;
    const where = p.zones === 'seat' ? 'Felt on the shoulder of the side where that person sits (this demonstration uses the left shoulder).' : `Felt at: ${ZONE_LONG[p.zones] || p.zones}.`;
    $('#learnWhere').textContent = where;
    $('#learnBack').disabled = learn.step === 0;
    $('#learnNext').textContent = learn.step === steps.length - 1 ? 'Done' : 'Next';
    if (play) playLearn(p);
  }
  async function playLearn(p) {
    try { await api('/api/kandha/test', { pattern: p.key, zone: p.zones === 'seat' ? 'L' : (p.zones === 'any' ? 'F' : undefined) }); }
    catch (e) { toast(esc(e.message)); }
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    for (const tab of $$('[role="tab"]')) {
      tab.addEventListener('click', () => showScreen(tab.dataset.screen));
      tab.addEventListener('keydown', (e) => {
        const tabs = $$('[role="tab"]'); const i = tabs.indexOf(tab);
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); const n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; n.focus(); showScreen(n.dataset.screen); }
        if (e.key === 'Home') { e.preventDefault(); tabs[0].focus(); showScreen(tabs[0].dataset.screen); }
        if (e.key === 'End') { e.preventDefault(); tabs[tabs.length - 1].focus(); showScreen(tabs[tabs.length - 1].dataset.screen); }
      });
    }
    $('#startBtn').addEventListener('click', () => (S.running ? stopListening() : startListening()));
    $('#welcomeStart').addEventListener('click', () => startListening());
    $$('[data-demo]').forEach((b) => b.addEventListener('click', () => playDemo(b.dataset.demo)));
    $('#queueBtn').addEventListener('click', () => toggleQueue());
    $('#dndBtn').addEventListener('click', () => updateServerSettings({ dnd: !(K.settings && K.settings.dnd) }));
    $('#setDnd').addEventListener('change', (e) => updateServerSettings({ dnd: e.target.checked }));
    $('#setMirror').addEventListener('change', (e) => updateServerSettings({ mirror: e.target.checked }));
    $('#newVoiceBtn').addEventListener('click', () => {
      if (engine && S.running) { engine.forceNewSpeaker(); toast('Started a new colour for the person speaking now. Press 1–4 or touch a pad to seat them.'); }
      else toast('Start listening first.');
    });
    $('#missBtn').addEventListener('click', () => {
      const t = nowT();
      const recent = S.lines.filter((l) => l.t >= t - 30);
      $('#missList').innerHTML = recent.length ? recent.map((l) => lineHTML(l)).join('') : '<li class="event">Nothing in the last 30 seconds.</li>';
      $('#missDlg').showModal();
    });
    $$('button[data-mode]').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
    $$('button[data-speech]').forEach((b) => b.addEventListener('click', async () => {
      settings.speechLang = b.dataset.speech; settings.capLang = settings.speechLang; saveSettings(); applyDisplay();
      if (S.running) { recognizer.setLanguage(settings.speechLang); setStatus('live', statusLine(recognizer.local)); toast(`Captions switch to ${settings.speechLang === 'hi' ? 'Hindi' : 'English'} the next time you press Start.`); }
    }));

    // stole screen
    $('#scanBtn').addEventListener('click', async () => {
      $('#scanBtn').disabled = true; $('#deviceList').innerHTML = '<li><small>Scanning for about six seconds…</small></li>';
      try { renderDevices((await api('/api/kandha/stole/scan', { timeout: 6 })).devices); }
      catch (e) { toast(esc(e.message)); renderDevices([]); }
      $('#scanBtn').disabled = false;
    });
    $('#deviceList').addEventListener('click', async (e) => {
      const b = e.target.closest('[data-pair]'); if (!b) return;
      b.disabled = true; b.textContent = 'Pairing…';
      try { const out = await api('/api/kandha/stole/pair', { address: b.dataset.pair, name: b.dataset.pairName }); K.stole = out.stole; renderStole(); toast(out.connected ? 'Paired and connected.' : 'Paired. Kandha keeps trying to connect in the background.'); }
      catch (err) { toast(esc(err.message)); b.disabled = false; b.textContent = 'Pair'; }
    });
    $('#simulateRow').addEventListener('click', async (e) => {
      const b = e.target.closest('[data-simulate]'); if (!b) return;
      const action = b.dataset.simulate;
      const value = action === 'press' ? { pad: b.dataset.pad, gesture: b.dataset.gesture } : action === 'battery' ? +b.dataset.value : action === 'charging' ? b.dataset.value === '1' : undefined;
      try { const out = await api('/api/kandha/stole/simulate', { action, value }); toast(`Simulated: ${esc(out.simulated)}`, 3000); }
      catch (err) { toast(esc(err.message)); }
    });
    $('#setLink').addEventListener('change', (e) => updateServerSettings({ link: e.target.value }));
    $('#forgetBtn').addEventListener('click', async () => { try { const snap = await api('/api/kandha/stole/forget', {}); K.stole = snap.stole; renderStole(); } catch (e) { toast(esc(e.message)); } });
    $$('[data-test]').forEach((b) => b.addEventListener('click', async () => { try { await api('/api/kandha/test', { zone: b.dataset.test }); } catch (e) { toast(esc(e.message)); } }));
    $('#stopTapsBtn').addEventListener('click', async () => { try { await api('/api/kandha/stop', {}); } catch (e) { toast(esc(e.message)); } });
    let intensityTimer = 0;
    for (const input of $$('[data-intensity]')) {
      input.addEventListener('input', () => { input.nextElementSibling.textContent = `${input.value}%`; });
      input.addEventListener('change', () => {
        clearTimeout(intensityTimer);
        intensityTimer = setTimeout(() => { const intensity = {}; for (const i of $$('[data-intensity]')) intensity[i.dataset.intensity] = +i.value; updateServerSettings({ intensity }); }, 150);
      });
    }
    $('#learnBtn').addEventListener('click', () => { learn.step = 0; showLearnStep(true); $('#learnDlg').showModal(); });
    $('#learnBack').addEventListener('click', () => { learn.step--; showLearnStep(true); });
    $('#learnNext').addEventListener('click', () => { if (learn.step >= learnSteps().length - 1) { $('#learnDlg').close(); return; } learn.step++; showLearnStep(true); });
    $('#learnPlay').addEventListener('click', () => { const p = learnSteps()[learn.step]; if (p) playLearn(p); });
    $('#learnDlg').addEventListener('close', () => api('/api/kandha/stop', {}).catch(() => {}));

    // seats screen
    $('#saveRoomBtn').addEventListener('click', async () => {
      const name = $('#roomName').value.trim();
      if (!name) { toast('Give the room a name first.'); $('#roomName').focus(); return; }
      try { const out = await api('/api/kandha/rooms', { action: 'save', name }); K.rooms = out.seats.rooms; K.loadedRoom = out.seats.loaded_room; renderRooms(); toast(`Saved <b>${esc(name)}</b>.`); }
      catch (e) { toast(esc(e.message)); }
    });
    $('#roomList').addEventListener('click', async (e) => {
      const load = e.target.closest('[data-room-load]'), del = e.target.closest('[data-room-delete]');
      try {
        if (load) { const out = await api('/api/kandha/rooms', { action: 'load', name: load.dataset.roomLoad }); applySeat({ seats: out.seats.seats, rooms: out.seats.rooms, loaded_room: out.seats.loaded_room, source: 'room-load' }); toast(`Using <b>${esc(load.dataset.roomLoad)}</b>.`); }
        if (del) { const out = await api('/api/kandha/rooms', { action: 'delete', name: del.dataset.roomDelete }); K.rooms = out.seats.rooms; K.loadedRoom = out.seats.loaded_room; renderRooms(); }
      } catch (err) { toast(esc(err.message)); }
    });
    $('#setLastLayout').addEventListener('change', readServerSettings);
    $('#unseated').addEventListener('click', (e) => { const b = e.target.closest('[data-chip]'); if (b && views.roomBig) { views.roomBig.select(+b.dataset.chip); renderRooms(); } });
    $('#unseated').addEventListener('dragstart', (e) => { const b = e.target.closest('[data-chip]'); if (b) { e.dataTransfer.setData('text/kandha-voice', b.dataset.chip); } });
    $('#unseated').addEventListener('keydown', (e) => {
      const b = e.target.closest('[data-chip]'); if (!b) return;
      const z = { 1: 'L', 2: 'R', 3: 'B', 4: 'F' }[e.key];
      if (z) { e.preventDefault(); assignSeat(+b.dataset.chip, z); }
    });

    // review
    $('#consentBox').addEventListener('change', updateSaveButtons);
    $('#saveHtml').addEventListener('click', () => saveFile(`kandha-${stamp()}.html`, exportHTML(), 'text/html'));
    $('#saveTxt').addEventListener('click', () => saveFile(`kandha-${stamp()}.txt`, exportText(), 'text/plain'));
    $$('[data-export]').forEach((b) => b.addEventListener('click', () => exportAudial(b.dataset.export)));
    $('#saveSession').addEventListener('click', saveToSessions);
    const openToneAbout = () => $('#toneDlg').showModal();
    $('#toneAboutBtn').addEventListener('click', openToneAbout);
    $('#toneAboutBtn2').addEventListener('click', openToneAbout);
    $('#toneSummary').addEventListener('click', (e) => { if (e.target.closest('[data-tone-about]')) openToneAbout(); });

    // settings
    for (const id of ['setName', 'setCap', 'setTheme', 'setMic', 'setNoise', 'setToneReview', 'setToneLive', 'setSens', 'setMax', 'setSilence', 'setAutocorrect', 'setTerms', 'setOrig']) $('#' + id).addEventListener('change', readSettings);
    for (const input of $$('#cueTable input')) input.addEventListener('change', readServerSettings);
    for (const id of ['setSeminarCues', 'setReminder']) $('#' + id).addEventListener('change', readServerSettings);

    // voices and lines
    $('#voices').addEventListener('click', (e) => { const b = e.target.closest('[data-voice]'); if (b) openVoice(+b.dataset.voice); });
    const lineClick = (e) => {
      const term = e.target.closest('[data-term]');
      if (term) { const d = vocab.define(term.dataset.term); toast(`<b>${esc(term.dataset.term)}</b> — ${esc(d || 'Your term.')}`, 7000); return; }
      const who = e.target.closest('[data-line]');
      if (who) { const l = S.lines.find((x) => x.uid === +who.dataset.line); if (l) openVoice(l.speakerId, l.uid); }
    };
    $('#history').addEventListener('click', lineClick);
    $('#missList').addEventListener('click', lineClick);
    $('#reviewList').addEventListener('click', lineClick);
    $('#voiceDlg').addEventListener('close', () => {
      if ($('#voiceDlg').returnValue === 'save' && dlgVoice) {
        const n = $('#voiceName').value.trim();
        if (n) { dlgVoice.name = n; rerenderHistory(); renderVoices(); renderNow(); renderRooms(); }
      }
    });
    $('#voiceSeatRow').addEventListener('click', (e) => { const b = e.target.closest('[data-seat]'); if (!b || !dlgVoice) return; assignSeat(dlgVoice.id, b.dataset.seat || null); for (const x of $$('#voiceSeatRow [data-seat]')) x.setAttribute('aria-pressed', String(x === b)); });
    $('#mergeBtn').addEventListener('click', () => { if (!dlgVoice) return; const into = +$('#mergeSel').value; const name = nameOf(into); mergeVoices(into, dlgVoice.id); $('#voiceDlg').close(); toast(`Joined into <b>${esc(name)}</b>.`); });
    $('#lineMoveBtn').addEventListener('click', () => { if (!dlgLine) return; dlgLine.speakerId = +$('#lineMoveSel').value; rerenderLine(dlgLine); renderVoices(); $('#voiceDlg').close(); });
    $('#makeCurrentBtn').addEventListener('click', () => {
      if (!dlgVoice) return;
      if (engine && S.running) engine.setCurrentSpeaker(dlgVoice.id); else onSpeaker(dlgVoice.id, nowT(), false);
      $('#voiceDlg').close();
    });

    document.addEventListener('keydown', (e) => {
      if (e.target.closest('input, textarea, select, dialog[open], [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'q') { e.preventDefault(); toggleQueue(); }
      else if (k === 's') { e.preventDefault(); $('#startBtn').click(); }
      else if (k === 'n') { e.preventDefault(); $('#newVoiceBtn').click(); }
      else if (k === 'm') { e.preventDefault(); $('#missBtn').click(); }
      else if (/^[1-4]$/.test(k)) {
        e.preventDefault();
        const z = { 1: 'L', 2: 'R', 3: 'B', 4: 'F' }[k];
        const selected = views.roomBig && views.roomBig.selected;
        assignSeat(selected != null && settings.screen === 'seats' ? selected : S.current, z, 'key');
      }
    });
  }

  // ------------------------------------------------------------------ init
  async function loadResources() {
    try { const r = await fetch(metaUrl('kandha-patterns') || 'patterns.json', { cache: 'no-store' }); if (r.ok) { PATTERNS = await r.json(); intents.minTurn = PATTERNS.scheduler.min_turn_s; } } catch (e) { /* defaults */ }
    try { const r = await fetch(metaUrl('kandha-tone-model') || 'tone-model.json', { cache: 'no-store' }); if (r.ok) TONE_MODEL = await r.json(); } catch (e) { /* estimates stay off */ }
    if (engine && TONE_MODEL && (settings.toneReview || settings.toneLive)) engine.setToneModel(TONE_MODEL);
  }
  function init() {
    views.stoleLive = new StoleView($('#stoleLive'), { onPad: (pad, gesture) => api('/api/kandha/pad', { pad, gesture }).catch((e) => toast(esc(e.message))) });
    views.stoleBig = new StoleView($('#stoleBig'), { onPad: (pad, gesture) => api('/api/kandha/pad', { pad, gesture }).catch((e) => toast(esc(e.message))) });
    views.stoleLearn = new StoleView($('#stoleLearn'), { showPads: false });
    views.roomLive = new RoomView($('#roomLive'), { interactive: false });
    views.roomBig = new RoomView($('#roomBig'), { interactive: true, onAssign: (voice, zone) => assignSeat(voice, zone, 'drag'), onSelect: () => renderRooms() });
    applyDisplay();
    renderVoices(); renderRooms(); renderStole();
    wire();
    showScreen(settings.screen || 'live');
    if (!Recognizer.supported() && !IN_QT) $('#nowHint').textContent = 'Open in Chrome or Edge for captions. The demos work here.';
    window.Kandha = {
      S, K, settings, toggleQueue, playDemo, onSpeaker, onCue, onTone, handleInterim, handleFinal, exportText, exportHTML, openReview, showScreen, assignSeat, setMode,
      ready: () => ({ ready: !!PATTERNS, screen: settings.screen, toneModel: !!TONE_MODEL, stream: sseState, host: !!localHost, qt: IN_QT, stole: K.stole && K.stole.state }),
      get toneModel() { return TONE_MODEL; }, get patterns() { return PATTERNS; }, get engine() { return engine; }, get captions() { return recognizer; }, get localHost() { return localHost; }, get intents() { return intents; },
    };
    loadResources();
    openStream();
    api('/api/kandha/state').then(applyServerState).catch(() => { setStatus('idle', 'Stole service unreachable'); });
    if (LocalCaptions && metaUrl('kandha-host') === 'accessibilityai') {
      LocalCaptions.available().then((st) => {
        localHost = st;
        if (!st) return;
        $('#aboutLine').textContent = `Kandha inside Audial-AI · Whisper model: ${st.asr_model}${st.asr_installed ? '' : ' (not installed yet: Setup & models)'} · docs/kandha/USER_GUIDE.md`;
        if (!S.running && !S.demo) $('#nowHint').textContent = st.asr_installed ? `Captions from Whisper (${st.asr_model}) on this computer.` : `Install ${st.asr_model} in Audial-AI (Setup & models) for captions; voices and taps work now.`;
        updateSaveButtons();
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
