/*
 * Kandha views: the virtual stole, the room diagram and the review timeline.
 * ---------------------------------------------------------------------------
 * DOM rendering only; no app state and no network. Loaded as a classic script (UMD) so Node can
 * require the pure helpers (zoneAngle, stoleSegmentsToFrames) in tests.
 */
(function (root) {
  'use strict';

  const SVG = 'http://www.w3.org/2000/svg';
  const ZONE_ANGLE = { F: -90, R: 0, B: 90, L: 180 };   // arrow rotation (the arrow points right at 0)
  const ZONE_NAME = { L: 'left', R: 'right', B: 'behind', F: 'in front' };
  const PADS = ['L', 'R', 'B', 'Q'];

  function el(tag, attrs, parent) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    if (parent) parent.appendChild(node);
    return node;
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  // ------------------------------------------------------------------ virtual stole
  // A stole seen from the front: both shoulders, the neck behind, the front panel at the collarbone,
  // and the four pads at the right-hand end. Zones light exactly when the scheduler says they do.
  class StoleView {
    constructor(container, opts) {
      opts = opts || {};
      this.onPad = opts.onPad || null;
      this.showPads = opts.showPads !== false;
      this.container = container;
      this.zones = {};
      this.timers = new Map();
      this.frames = [];
      this.raf = 0;
      this.build();
    }

    build() {
      const svg = el('svg', { viewBox: '0 0 300 300', role: 'img', 'aria-label': 'Virtual Kandha Stole: shoulders, neck and front zones' });
      const title = el('title', {}, svg); title.textContent = 'Virtual Kandha Stole';
      // head outline (dashed) so the zones read as a worn scarf
      el('circle', { cx: 150, cy: 52, r: 34, class: 'stole__head' }, svg);
      // the cloth: a loop over both shoulders with two ends hanging down
      el('path', { class: 'stole__cloth', d: 'M62 118 C 80 86, 118 76, 150 92 C 182 76, 220 86, 238 118 L 238 150 C 232 190, 226 226, 224 268 L 196 268 C 198 228, 202 196, 206 160 C 184 150, 160 140, 150 134 C 140 140, 116 150, 94 160 C 98 196, 102 228, 104 268 L 76 268 C 74 226, 68 190, 62 150 Z' }, svg);
      // zones: back of neck (B) sits behind the head, shoulders L/R on top, front F at the sternum
      this.zones.B = el('rect', { x: 118, y: 88, width: 64, height: 22, rx: 10, class: 'stole__zone', 'data-zone': 'B' }, svg);
      el('circle', { cx: 150, cy: 99, r: 4, class: 'stole__motor' }, svg);
      this.zones.L = el('rect', { x: 66, y: 112, width: 70, height: 30, rx: 12, class: 'stole__zone', 'data-zone': 'L' }, svg);
      el('circle', { cx: 86, cy: 127, r: 4, class: 'stole__motor' }, svg);
      el('circle', { cx: 116, cy: 127, r: 4, class: 'stole__motor' }, svg);
      this.zones.R = el('rect', { x: 164, y: 112, width: 70, height: 30, rx: 12, class: 'stole__zone', 'data-zone': 'R' }, svg);
      el('circle', { cx: 184, cy: 127, r: 4, class: 'stole__motor' }, svg);
      el('circle', { cx: 214, cy: 127, r: 4, class: 'stole__motor' }, svg);
      this.zones.F = el('rect', { x: 128, y: 150, width: 44, height: 44, rx: 22, class: 'stole__zone', 'data-zone': 'F' }, svg);
      el('circle', { cx: 150, cy: 172, r: 4, class: 'stole__motor' }, svg);
      const labels = [['L', 101, 160], ['R', 199, 160], ['B', 150, 82], ['F', 150, 208]];
      for (const [z, x, y] of labels) { const t = el('text', { x, y, 'text-anchor': 'middle', class: 'stole__label' }, svg); t.textContent = z; }
      // the wearer's left is on the viewer's right: label the sides as the wearer feels them
      const left = el('text', { x: 30, y: 128, 'text-anchor': 'middle', class: 'stole__label' }, svg); left.textContent = 'left';
      const right = el('text', { x: 270, y: 128, 'text-anchor': 'middle', class: 'stole__label' }, svg); right.textContent = 'right';
      this.pads = {};
      if (this.showPads) {
        PADS.forEach((pad, i) => {
          const y = 196 + i * 18;
          const g = el('g', { class: 'stole__padgroup' }, svg);
          const r = el('rect', { x: 204, y, width: 16, height: 14, rx: 3, class: 'stole__pad', 'data-pad': pad, tabindex: 0, role: 'button', 'aria-label': `Stole pad ${pad}: click to tap, double-click for double tap, hold for long press` }, g);
          const t = el('text', { x: 212, y: y + 11, 'text-anchor': 'middle', class: 'stole__padlabel' }, g); t.textContent = pad;
          this.pads[pad] = r;
          this.wirePad(r, pad);
        });
      }
      this.container.innerHTML = '';
      this.container.appendChild(svg);
      this.svg = svg;
    }

    wirePad(node, pad) {
      if (!this.onPad) return;
      let down = 0, longTimer = 0, fired = false, clickTimer = 0;
      const start = () => { down = performance.now(); fired = false; node.classList.add('is-active'); longTimer = setTimeout(() => { fired = true; this.onPad(pad, 'long'); node.classList.remove('is-active'); }, 700); };
      const end = () => {
        clearTimeout(longTimer); node.classList.remove('is-active');
        if (fired || !down) { down = 0; return; }
        down = 0;
        if (clickTimer) { clearTimeout(clickTimer); clickTimer = 0; this.onPad(pad, 'double'); return; }
        clickTimer = setTimeout(() => { clickTimer = 0; this.onPad(pad, 'tap'); }, 280);
      };
      node.addEventListener('pointerdown', (e) => { e.preventDefault(); start(); });
      node.addEventListener('pointerup', end);
      node.addEventListener('pointerleave', () => { clearTimeout(longTimer); node.classList.remove('is-active'); down = 0; });
      node.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!e.repeat) start(); }
      });
      node.addEventListener('keyup', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); end(); } });
    }

    // segments: [{zone, start_ms, end_ms, level}] relative to now: each step as the stole plays
    // it (zones after mirror, the zone's intensity scale in the level), from the service's record
    pulse(record) {
      const segments = record && record.segments;
      const now = performance.now();
      if (segments && segments.length) {
        // a new command replaces whatever was playing, on the stole and here
        this.frames = [];
        for (const s of segments) this.frames.push({ zone: s.zone, from: now + s.start_ms, until: now + s.end_ms, level: s.level });
      } else if (record && record.zones) {
        // no step detail (the page's own fallback flash when the service is unreachable)
        const until = now + (record.duration_ms || 150);
        for (const z of record.zones) this.frames.push({ zone: z, from: now, until, level: record.intensity != null ? record.intensity : 200 });
      }
      this.container.classList.remove('is-flash'); void this.container.offsetWidth; this.container.classList.add('is-flash');
      if (!this.raf) this.tick();
    }

    tick() {
      const now = performance.now();
      const on = {};
      this.frames = this.frames.filter((f) => f.until > now);
      for (const f of this.frames) if (f.from <= now) on[f.zone] = Math.max(on[f.zone] || 0, f.level);
      for (const [z, node] of Object.entries(this.zones)) {
        const level = on[z] || 0;
        node.classList.toggle('is-on', level > 0);
        node.classList.toggle('is-soft', level > 0 && level < 140);
      }
      this.raf = this.frames.length ? requestAnimationFrame(() => this.tick()) : 0;
      if (!this.frames.length) this.raf = 0;
    }

    clear() { this.frames = []; for (const node of Object.values(this.zones)) node.classList.remove('is-on', 'is-soft'); }
  }

  // ------------------------------------------------------------------ room diagram
  // Top-down: the wearer at the centre facing up. F ahead, B behind, L left, R right.
  class RoomView {
    constructor(container, opts) {
      opts = opts || {};
      this.container = container;
      this.onAssign = opts.onAssign || null;    // (voiceId, zone|null)
      this.onSelect = opts.onSelect || null;    // (voiceId)
      this.interactive = !!opts.interactive;
      this.selected = null;
      this.build();
    }

    build() {
      const svg = el('svg', { viewBox: '0 0 300 300', role: 'img', 'aria-label': 'Room: you in the middle, seats to the left, right, behind and in front' });
      const title = el('title', {}, svg); title.textContent = 'Room diagram';
      el('rect', { x: 8, y: 8, width: 284, height: 284, rx: 18, class: 'room__floor' }, svg);
      this.seats = {};
      const spots = { F: [150, 62], R: [238, 150], B: [150, 238], L: [62, 150] };
      this.spots = spots;
      for (const [z, [x, y]] of Object.entries(spots)) {
        const g = el('g', { 'data-zone': z }, svg);
        this.seats[z] = el('circle', { cx: x, cy: y, r: 36, class: 'room__seat', 'data-zone': z }, g);
        const t = el('text', { x, y: y + 52, 'text-anchor': 'middle', class: 'room__seatlabel' }, g);
        t.textContent = { F: 'front', R: 'right', B: 'behind', L: 'left' }[z];
        if (this.interactive) {
          g.addEventListener('dragover', (e) => { e.preventDefault(); this.seats[z].classList.add('is-over'); });
          g.addEventListener('dragleave', () => this.seats[z].classList.remove('is-over'));
          g.addEventListener('drop', (e) => { e.preventDefault(); this.seats[z].classList.remove('is-over'); const id = +e.dataTransfer.getData('text/kandha-voice'); if (id && this.onAssign) this.onAssign(id, z); });
          g.addEventListener('click', () => { if (this.selected != null && this.onAssign) this.onAssign(this.selected, z); });
        }
      }
      el('path', { d: 'M150 118 L150 104 M142 112 L150 104 L158 112', class: 'room__facing' }, svg);
      el('circle', { cx: 150, cy: 150, r: 26, class: 'room__you' }, svg);
      const you = el('text', { x: 150, y: 155, 'text-anchor': 'middle', class: 'room__youlabel' }, svg); you.textContent = 'you';
      this.chipLayer = el('g', {}, svg);
      this.container.innerHTML = '';
      this.container.appendChild(svg);
      this.svg = svg;
    }

    // seats: {voiceId: zone|null}; voices: [{id, name, idx}]; current: voiceId; pending: voiceId waiting for a pad
    render(seats, voices, current, pending) {
      // a re-render keeps the keyboard on the voice it was on
      const active = document.activeElement;
      const focused = active && this.chipLayer.contains(active) ? active.getAttribute('data-voice') : null;
      for (const node of Object.values(this.seats)) { node.classList.remove('is-lit'); node.style.removeProperty('--c'); }
      this.chipLayer.innerHTML = '';
      const byZone = {};
      for (const v of voices) {
        const z = seats[v.id];
        if (!z || !this.spots[z]) continue;
        (byZone[z] = byZone[z] || []).push(v);
      }
      for (const [z, list] of Object.entries(byZone)) {
        const [cx, cy] = this.spots[z];
        list.forEach((v, i) => {
          const n = list.length, dx = (i - (n - 1) / 2) * 30;
          const g = el('g', { class: 'room__chip' + (v.id === current ? ' is-current' : '') + (v.id === this.selected ? ' is-selected' : ''), 'data-voice': v.id, tabindex: this.interactive ? 0 : -1, role: this.interactive ? 'button' : null, 'aria-label': `${v.name}, seated ${ZONE_NAME[z]}` }, this.chipLayer);
          g.style.setProperty('--c', `var(--s${v.idx + 1})`);
          el('circle', { cx: cx + dx, cy, r: 15 }, g);
          const t = el('text', { x: cx + dx, y: cy + 5, 'text-anchor': 'middle' }, g); t.textContent = v.name.slice(0, 2);
          if (v.id === current) this.seats[z].classList.add('is-lit'), this.seats[z].style.setProperty('--c', `var(--s${v.idx + 1})`);
          if (this.interactive) this.wireChip(g, v.id);
        });
      }
      if (pending != null && seats[pending] == null) for (const node of Object.values(this.seats)) node.classList.add('is-over');
      else for (const node of Object.values(this.seats)) node.classList.remove('is-over');
      const again = focused != null ? this.chipLayer.querySelector(`[data-voice="${focused}"]`) : null;
      if (again) again.focus({ preventScroll: true });
    }

    wireChip(g, id) {
      g.setAttribute('draggable', 'true');
      g.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/kandha-voice', String(id)); e.dataTransfer.effectAllowed = 'move'; });
      g.addEventListener('click', (e) => { e.stopPropagation(); this.select(id); });
      // the key belongs to this chip: stop it here, so the page's own 1-4 shortcut does not also
      // seat the person speaking now
      g.addEventListener('keydown', (e) => {
        const z = { 1: 'L', 2: 'R', 3: 'B', 4: 'F' }[e.key];
        if (z && this.onAssign) { e.preventDefault(); e.stopPropagation(); this.onAssign(id, z); }
        else if ((e.key === 'Delete' || e.key === 'Backspace') && this.onAssign) { e.preventDefault(); e.stopPropagation(); this.onAssign(id, null); }
        else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); this.select(id); }
      });
      // SVG <g draggable> is not reliable everywhere: pointer drag as a fallback
      let dragging = false;
      g.addEventListener('pointerdown', (e) => { dragging = true; g.setPointerCapture(e.pointerId); });
      g.addEventListener('pointerup', (e) => {
        if (!dragging) return; dragging = false;
        const hit = document.elementFromPoint(e.clientX, e.clientY);
        const zone = hit && hit.closest && hit.closest('[data-zone]') ? hit.closest('[data-zone]').getAttribute('data-zone') : null;
        if (zone && this.onAssign) this.onAssign(id, zone);
      });
    }

    select(id) { this.selected = this.selected === id ? null : id; if (this.onSelect) this.onSelect(this.selected); }
  }

  // ------------------------------------------------------------------ review timeline
  // lanes: voices (blocks), cues (triangles), tone estimates, queue moments, taps, seat changes
  function timelineSVG(data, opts) {
    opts = opts || {};
    const T = Math.max(1, data.length);
    const pxPerSec = Math.max(6, Math.min(40, 900 / T));
    const x0 = 20, W = Math.max(600, Math.ceil(T * pxPerSec) + 40);
    const lanes = [['voices', 44], ['cues', 24], ['tone', data.showTone ? 22 : 0], ['queue', 16], ['taps', 22], ['seats', data.seats && data.seats.length ? 18 : 0]].filter((l) => l[1] > 0);
    let y = 18; const laneY = {};
    for (const [name, h] of lanes) { laneY[name] = y; y += h + 6; }
    const H = y + 16;
    const X = (t) => x0 + t * pxPerSec;
    const col = (id) => data.colour(id, !!opts.literal);
    const ink = opts.literal ? '#4e5c6b' : 'var(--muted)';
    const signal = opts.literal ? '#b4780a' : 'var(--signal)';
    const tap = opts.literal ? '#b4780a' : 'var(--tap)';
    const font = 'font-family="system-ui, sans-serif" font-size="11"';
    const parts = [];
    const label = (name, text) => parts.push(`<text x="${x0}" y="${laneY[name] - 4}" ${font} fill="${ink}">${esc(text)}</text>`);
    label('voices', 'Who spoke');
    const ch = data.changes.slice().sort((a, b) => a.t - b.t);
    for (let i = 0; i < ch.length; i++) {
      const t0 = ch[i].t, t1 = i + 1 < ch.length ? ch[i + 1].t : T;
      if (t1 - t0 < 0.05) continue;
      parts.push(`<rect x="${X(t0).toFixed(1)}" y="${laneY.voices + 6}" width="${Math.max(2, X(t1) - X(t0)).toFixed(1)}" height="30" rx="4" fill="${col(ch[i].id)}"><title>${esc(data.name(ch[i].id))} ${data.clock(t0)}–${data.clock(t1)}</title></rect>`);
    }
    label('cues', 'Tone cues');
    for (const c of data.cues) parts.push(`<g><path d="M${X(c.t).toFixed(1)} ${laneY.cues + 18} l-6 -10 h12 z" fill="${ink}"><title>${esc(c.label)} ${data.clock(c.t)}</title></path><text x="${X(c.t).toFixed(1)}" y="${laneY.cues + 4}" text-anchor="middle" ${font} fill="${ink}">${esc(c.short || c.label)}</text></g>`);
    if (laneY.tone != null) {
      label('tone', 'Tone (estimate)');
      for (const x of data.tones) {
        const xm = X((x.t0 + x.t1) / 2), c = col(x.speakerId), yb = laneY.tone + 4;
        const tip = `<title>${esc(data.name(x.speakerId))} ${data.clock(x.t0)}: ${esc(x.text)}</title>`;
        if (x.relative === 'intense') parts.push(`<path d="M${xm.toFixed(1)} ${yb} l-6 10 h12 z" fill="${c}">${tip}</path>`);
        else if (x.relative === 'softer') parts.push(`<path d="M${xm.toFixed(1)} ${yb + 10} l-6 -10 h12 z" fill="${c}">${tip}</path>`);
        else parts.push(`<rect x="${X(x.t0).toFixed(1)}" y="${yb + 4}" width="${Math.max(2, X(x.t1) - X(x.t0)).toFixed(1)}" height="2" fill="${c}" opacity=".6">${tip}</rect>`);
      }
    }
    label('queue', 'Asked to speak');
    for (const q of data.queue) parts.push(`<path d="M${X(q.t).toFixed(1)} ${laneY.queue} v14" stroke="${signal}" stroke-width="3"><title>${esc(q.text)} ${data.clock(q.t)}</title></path>`);
    label('taps', 'Stole taps');
    for (const h of data.taps) {
      const w = Math.max(3, (h.duration_ms || 120) / 1000 * pxPerSec);
      parts.push(`<rect x="${X(h.t).toFixed(1)}" y="${laneY.taps + 2}" width="${w.toFixed(1)}" height="14" rx="2" fill="${tap}"><title>${esc(h.zones)} ${esc(h.pattern)} ${data.clock(h.t)}</title></rect><text x="${X(h.t).toFixed(1)}" y="${laneY.taps + 24}" ${font} fill="${ink}" text-anchor="middle">${esc(h.zones)}</text>`);
    }
    if (laneY.seats != null) {
      label('seats', 'Seat changes');
      for (const s of data.seats) parts.push(`<circle cx="${X(s.t).toFixed(1)}" cy="${laneY.seats + 8}" r="5" fill="${col(s.voice)}"><title>${esc(data.name(s.voice))} → ${esc(s.zone || 'no seat')} ${data.clock(s.t)}</title></circle>`);
    }
    const step = T > 600 ? 120 : T > 120 ? 30 : 10;
    for (let t = 0; t <= T; t += step) parts.push(`<text x="${X(t).toFixed(1)}" y="${H - 4}" text-anchor="middle" ${font} fill="${ink}">${data.clock(t)}</text>`);
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Who spoke when, with cues, tone estimates, queue moments, taps and seat changes"><line x1="${x0}" x2="${X(T)}" y1="${laneY.voices + 21}" y2="${laneY.voices + 21}" stroke="${opts.literal ? '#d3dbe3' : 'var(--line)'}" stroke-width="2"/>${parts.join('')}</svg>`;
  }

  const api = { StoleView, RoomView, timelineSVG, ZONE_ANGLE, ZONE_NAME };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.KandhaViews = api;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
