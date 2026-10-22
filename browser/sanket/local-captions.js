/*
 * Local captions from AccessibilityAI (Audial AI).
 * When Sanket is opened from the AccessibilityAI companion (http://127.0.0.1:<port>/sanket/),
 * captions can come from its local Whisper model instead of the browser's speech service:
 * audio never leaves the computer, and every caption arrives with start/end times, so Sanket
 * can give each word the voice that was speaking at that moment.
 *
 * Same interface as SanketRecognizer: start({lang}), stop(), setLanguage(), .active, .local,
 * plus feed(samples, sampleRate), which receives the microphone audio Sanket already captures.
 */
(function (root) {
  'use strict';

  const PACKET_SECONDS = 2;           // the companion accepts packets under 3 s
  const POLL_MS = 300;
  const MAX_PENDING_PACKETS = 3;      // bounds uploads in flight/queued
  const REQUEST_TIMEOUT_MS = 15000;

  function encodeWav(samples, rate) {
    const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
    const text = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    text(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); text(36, 'data');
    v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true);
    }
    return new Blob([buf], { type: 'audio/wav' });
  }

  class LocalCaptions {
    constructor(handlers, opts) {
      this.h = handlers || {};
      this.base = (opts && opts.base) || '';
      this.fetch = (opts && opts.fetch) || root.fetch.bind(root);
      this.active = false;
      this.starting = false;
      this.stopping = null;
      this.local = true;               // shown as "on device" in the status line
      this.lang = 'en';
      this.session = null;
      this.cursor = 0;
      this.pending = [];               // Float32Array pieces not yet sent
      this.pendingLen = 0;
      this.sentSamples = 0;
      this.rate = 16000;
      this.sending = Promise.resolve();
      this.queuedPackets = 0;
      this.generation = 0;
    }

    // Resolves to the companion's status when Sanket is served by AccessibilityAI, else null.
    static async available(base, fetchFn) {
      try {
        const f = fetchFn || root.fetch.bind(root);
        const r = await f((base || '') + '/api/status', { cache: 'no-store' });
        if (!r.ok) return null;
        const s = await r.json();
        return s && typeof s.asr_installed === 'boolean' ? s : null;
      } catch (e) { return null; }
    }

    async _json(path, data) {
      const r = await this.fetch(this.base + path, {
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        ...(data === undefined ? {} : {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
        }),
      });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) throw Object.assign(new Error(out.error || 'The local AccessibilityAI request failed.'), { status: r.status });
      return out;
    }

    async start(opts) {
      if (this.active || this.starting || this.stopping) return false;
      this.starting = true;
      opts = opts || {};
      this.lang = opts.lang === 'hi' ? 'hi' : 'en';
      const gen = ++this.generation;
      try {
        const status = await this._json('/api/status');
        if (gen !== this.generation) return false;
        if (!status.asr_installed) {
          this.h.onError && this.h.onError('local-missing', `Local captions need ${status.asr_model || 'a Whisper model'} installed in AccessibilityAI (Models page). Voice colours and tone cues keep working; or choose Browser speech service in Settings.`);
          return false;
        }
        if (status.running) {
          this.h.onError && this.h.onError('local-busy', 'AccessibilityAI is already listening in another window. Stop it there, then press Start again.');
          return false;
        }
        const r = await this._json('/api/start', { mode: 'combined', language: this.lang });
        if (gen !== this.generation) { this._json('/api/stop', { session_id: r.session_id }).catch(() => {}); return false; }
        this.session = r.session_id;
        this.cursor = r.cursor || 0;
        this.pending = []; this.pendingLen = 0; this.sentSamples = 0;
        this.drainUntil = 0;
        this.active = true;
        this.h.onStatus && this.h.onStatus('listening', { local: true });
        this._poll(gen);
        return true;
      } catch (e) {
        if (gen === this.generation) this.h.onError && this.h.onError('local-error', `Local captions couldn’t start: ${e.message}`);
        return false;
      } finally {
        if (gen === this.generation) this.starting = false;
      }
    }

    // Microphone audio from Sanket's own capture (any sample rate; the companion resamples).
    feed(samples, rate) {
      if (!this.active) return;
      this.rate = Math.round(rate || 16000);
      this.pending.push(samples.slice ? samples.slice(0) : Float32Array.from(samples));
      this.pendingLen += samples.length;
      if (this.pendingLen >= this.rate * PACKET_SECONDS) this._send();
    }

    _send() {
      if (!this.pendingLen || !this.session) return this.sending;
      const start = this.sentSamples / this.rate;
      this.sentSamples += this.pendingLen;
      if (this.queuedPackets >= MAX_PENDING_PACKETS) {
        this.pending = []; this.pendingLen = 0;
        this.h.onError && this.h.onError('local-warning', 'An audio packet was skipped because the local connection is slow. Caption timestamps preserve the gap.');
        return this.sending;
      }
      const all = new Float32Array(this.pendingLen);
      let o = 0; for (const p of this.pending) { all.set(p, o); o += p.length; }
      this.pending = []; this.pendingLen = 0;
      const session = this.session, rate = this.rate;
      this.queuedPackets++;
      // packets go in order: the companion rejects timestamps that go backwards
      this.sending = this.sending.then(async () => {
        if (session !== this.session) return;
        try {
          const r = await this.fetch(this.base + '/api/audio', {
            method: 'POST', body: encodeWav(all, rate),
            headers: { 'Content-Type': 'audio/wav', 'X-Audio-Start-Seconds': String(start), 'X-Session-ID': session },
            signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
          });
          if (!r.ok) {
            const out = await r.json().catch(() => ({}));
            throw new Error(out.error || 'Audio upload failed.');
          }
        } catch (e) {
          if (session === this.session) this.h.onError && this.h.onError('local-error', `Local captions: ${e.message}`);
        }
      }).finally(() => { this.queuedPackets--; });
      return this.sending;
    }

    async _poll(gen) {
      while (gen === this.generation) {
        try {
          const r = await this._json('/api/events?after=' + this.cursor);
          if (gen !== this.generation) break;
          this.cursor = r.cursor;
          for (const ev of r.events) {
            const d = ev.data;
            if (ev.kind === 'caption' && d && d.text) {
              this.h.onFinal && this.h.onFinal(d.text, { start: d.start, end: d.end, speaker: d.speaker, local: true });
            } else if (ev.kind === 'partial') {
              if (d) this.h.onInterim && this.h.onInterim(d);
            } else if (ev.kind === 'warning' || ev.kind === 'error') {
              this.h.onError && this.h.onError('local-warning', String(d));
            }
          }
          // keep polling after Stop until the last queued captions arrive
          if (!this.active && this.drainUntil && Date.now() > this.drainUntil) break;
        } catch (e) {
          if (gen === this.generation) this.h.onError && this.h.onError('local-error', 'AccessibilityAI is not responding. Is it still running?');
          await new Promise((res) => setTimeout(res, 2000));
        }
        await new Promise((res) => setTimeout(res, POLL_MS));
      }
    }

    stop() {
      if (this.stopping) return this.stopping;
      if (!this.active) {
        // Invalidate status/start responses that arrive after the user stops.
        if (this.starting) {
          ++this.generation;
          this.starting = false;
        }
        return Promise.resolve();
      }
      this.active = false;
      const session = this.session;
      this.stopping = (async () => {
        try {
          // Capture is already stopped, so the bounded partial packet can wait
          // for upload capacity instead of losing the final spoken words.
          await this.sending.catch(() => {});
          await this._send().catch(() => {});
          this.drainUntil = Date.now() + 15000;   // Whisper may still be finishing the last seconds
          if (session) await this._json('/api/stop', { session_id: session }).catch(() => {});
        } finally {
          this.session = null;
          this.stopping = null;
        }
      })();
      return this.stopping;
    }

    setLanguage(lang) { this.lang = lang === 'hi' ? 'hi' : 'en'; }   // takes effect at the next Start
  }

  LocalCaptions.encodeWav = encodeWav;
  if (typeof module !== 'undefined' && module.exports) module.exports = LocalCaptions;
  root.SanketLocalCaptions = LocalCaptions;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
