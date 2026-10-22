/*
 * Speech recognition wrapper (browser).
 * Uses the browser's built-in speech recognition (Chrome, Edge, Android Chrome).
 * Restarts itself when the browser ends a session, and reports clear errors.
 */
(function (root) {
  'use strict';

  const LANG_TAG = { en: 'en-IN', hi: 'hi-IN' };

  const MESSAGES = {
    'not-allowed': 'Sanket can’t use the microphone. Allow microphone access for this page (the icon in the address bar), then press Start.',
    'service-not-allowed': 'This browser blocked its speech service. Try Google Chrome or Microsoft Edge.',
    'audio-capture': 'No microphone was found. Plug one in or check your sound settings, then press Start.',
    'network': 'Captions need an internet connection in this browser. Voice colours and tone cues keep working.',
    'language-not-supported': 'This browser can’t caption the chosen language. Try Chrome or Edge.',
    'unsupported': 'This browser has no speech recognition. Open Sanket in Google Chrome or Microsoft Edge for captions. Voice colours and tone cues still work.',
  };

  class Recognizer {
    constructor(handlers) {
      this.h = handlers || {};
      this.SR = root.SpeechRecognition || root.webkitSpeechRecognition || null;
      this.active = false;
      this.rec = null;
      this.lang = 'en';
      this.track = null;
      this.local = false;
      this.phrases = [];
      this.restarts = 0;
      this.lastStart = 0;
      this.retryTimer = null;
    }

    static supported() { return !!(root.SpeechRecognition || root.webkitSpeechRecognition); }

    async start(opts) {
      opts = opts || {};
      if (!this.SR) { this._error('unsupported'); return false; }
      this.lang = opts.lang || this.lang;
      this.track = opts.track || null;
      this.phrases = opts.phrases || [];
      this.active = true;
      this.restarts = 0;
      await this._checkLocal();
      this._open();
      return true;
    }

    stop() {
      this.active = false;
      clearTimeout(this.retryTimer);
      if (this.rec) { try { this.rec.onend = null; this.rec.abort(); } catch (e) { /* already stopped */ } }
      this.rec = null;
      this._status('stopped');
    }

    setLanguage(lang) {
      this.lang = lang;
      if (this.active) { this._close(); this._checkLocal().then(() => this._open()); }
    }

    // Newer Chrome versions can recognise speech on the device itself. Use it when offered.
    async _checkLocal() {
      this.local = false;
      try {
        if (this.SR && typeof this.SR.available === 'function') {
          const st = await this.SR.available({ langs: [LANG_TAG[this.lang]], processLocally: true });
          this.local = st === 'available';
        }
      } catch (e) { this.local = false; }
    }

    _close() {
      if (this.rec) { try { this.rec.onend = null; this.rec.onerror = null; this.rec.abort(); } catch (e) { /* ignore */ } }
      this.rec = null;
    }

    _open() {
      if (!this.active) return;
      const rec = new this.SR();
      rec.lang = LANG_TAG[this.lang] || this.lang;
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      if (this.local) { try { rec.processLocally = true; } catch (e) { /* not supported */ } }
      if (this.phrases.length && root.SpeechRecognitionPhrase) {
        try { rec.phrases = this.phrases.slice(0, 200).map((p) => new root.SpeechRecognitionPhrase(p, 3)); } catch (e) { /* not supported */ }
      }

      rec.onresult = (ev) => {
        let interim = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const r = ev.results[i];
          const text = (r[0] && r[0].transcript) || '';
          if (r.isFinal) {
            if (text.trim() && this.h.onFinal) this.h.onFinal(text.trim(), r[0].confidence);
          } else interim += text;
        }
        if (this.h.onInterim) this.h.onInterim(interim.trim());
        this.restarts = 0;
      };
      rec.onerror = (ev) => {
        const code = ev.error;
        if (code === 'no-speech' || code === 'aborted') return;
        if (code === 'not-allowed' || code === 'service-not-allowed' || code === 'audio-capture' || code === 'language-not-supported') {
          this.active = false;
        }
        this._error(code);
      };
      rec.onstart = () => { this.lastStart = Date.now(); this._status('listening'); };
      rec.onend = () => {
        if (!this.active) return;
        // browsers end sessions after silence or time limits; reopen, backing off if it keeps failing
        const quick = Date.now() - this.lastStart < 1500;
        this.restarts = quick ? this.restarts + 1 : 0;
        const wait = Math.min(8000, 250 * Math.pow(2, Math.min(this.restarts, 5)));
        clearTimeout(this.retryTimer);
        this.retryTimer = setTimeout(() => this._open(), wait);
      };
      this.rec = rec;
      try {
        // Newer Chrome accepts our microphone track so both parts of Sanket hear the same audio;
        // older browsers ignore the argument and open the default microphone.
        if (this.track) rec.start(this.track); else rec.start();
      } catch (e) {
        try { rec.start(); } catch (e2) { this._error('audio-capture'); }
      }
    }

    _status(s) { if (this.h.onStatus) this.h.onStatus(s, { local: this.local }); }
    _error(code) { if (this.h.onError) this.h.onError(code, MESSAGES[code] || 'Captions stopped unexpectedly. Press Start to try again.'); }
  }

  root.SanketRecognizer = Recognizer;
})(typeof self !== 'undefined' ? self : this);
