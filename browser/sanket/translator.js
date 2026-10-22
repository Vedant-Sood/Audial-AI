/*
 * Caption translation English <-> Hindi using the browser's built-in translator
 * (Chrome 138+ on computers; runs on the device once its language pack is downloaded).
 */
(function (root) {
  'use strict';

  class CaptionTranslator {
    constructor() { this.t = null; this.pair = null; this.cache = new Map(); }

    static async availability(src, tgt) {
      if (src === tgt) return 'same';
      if (!('Translator' in root)) return 'unavailable';
      try { return await root.Translator.availability({ sourceLanguage: src, targetLanguage: tgt }); }
      catch (e) { return 'unavailable'; }
    }

    // Call from a button press: downloading a language pack needs a user gesture.
    async prepare(src, tgt, onProgress) {
      if (src === tgt) { this.t = null; this.pair = null; return 'same'; }
      const key = src + '>' + tgt;
      if (this.pair === key && this.t) return 'ready';
      const av = await CaptionTranslator.availability(src, tgt);
      if (av === 'unavailable') { this.t = null; this.pair = null; return 'unavailable'; }
      try {
        this.t = await root.Translator.create({
          sourceLanguage: src, targetLanguage: tgt,
          monitor(m) { m.addEventListener('downloadprogress', (e) => onProgress && onProgress(e.loaded)); },
        });
        this.pair = key;
        this.cache.clear();
        return 'ready';
      } catch (e) {
        this.t = null; this.pair = null;
        return 'failed';
      }
    }

    get ready() { return !!this.t; }

    async translate(text) {
      if (!this.t || !text) return null;
      if (this.cache.has(text)) return this.cache.get(text);
      try {
        const out = await this.t.translate(text);
        this.cache.set(text, out);
        if (this.cache.size > 300) this.cache.delete(this.cache.keys().next().value);
        return out;
      } catch (e) { return null; }
    }
  }

  root.SanketTranslator = CaptionTranslator;
})(typeof self !== 'undefined' ? self : this);
