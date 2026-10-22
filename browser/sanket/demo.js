/*
 * Built-in demo: plays a scripted seminar and a role-play through the real interface,
 * with no microphone needed. Useful for trying Sanket and for filming.
 * Tone estimates in the demo are scripted to illustrate the feature (step.tone); in a real
 * session they come from the voice engine.
 */
(function (root) {
  'use strict';

  const SCENES = {
    seminar: {
      title: 'Case seminar',
      mode: 'seminar',
      speakers: [{ id: 1, name: 'Dr Rao' }, { id: 2, name: 'Priya' }, { id: 3, name: 'Arjun' }],
      voices: { 1: { pitch: 0.85, rate: 0.95 }, 2: { pitch: 1.35, rate: 1.05 }, 3: { pitch: 1.0, rate: 1.1 } },
      steps: [
        { say: 1, en: 'Let’s look at the case. Meera has stopped enjoying music, her friends, even food.', hi: 'चलिए केस देखते हैं। मीरा को अब संगीत, दोस्तों, यहाँ तक कि खाने में भी आनंद नहीं आता।' },
        { say: 2, en: 'That sounds like and hedonia. I’d check the DSM 5 criteria for depression.', hi: 'यह एनहेडोनिया जैसा लगता है। मैं डिप्रेशन के लिए DSM-5 के मानदंड देखूँगी।' },
        { say: 3, en: 'But she still goes to college every day. Could it be dis thymia instead?', hi: 'लेकिन वह अब भी रोज़ कॉलेज जाती है। क्या यह डिस्थाइमिया हो सकता है?' },
        { queue: true, wait: 600 },
        { say: 2, en: 'Her sleep changed only last month, so the timeline really matters here.', hi: 'उसकी नींद पिछले महीने ही बदली है, इसलिए यहाँ समय-क्रम बहुत मायने रखता है।' },
        { say: 1, en: 'Good point. Vikram, you wanted to add something?', hi: 'अच्छा बिंदु। विक्रम, आप कुछ जोड़ना चाहते थे?' },
        { queue: false, wait: 2500 },
      ],
    },
    roleplay: {
      title: 'Role-play',
      mode: 'practicum',
      speakers: [{ id: 1, name: 'Client' }, { id: 2, name: 'Vikram' }],
      voices: { 1: { pitch: 1.3, rate: 0.95 }, 2: { pitch: 0.9, rate: 1.0 } },
      steps: [
        { say: 1, en: 'I thought I was fine. Everyone kept telling me I was fine.', hi: 'मुझे लगा मैं ठीक हूँ। सब मुझसे यही कहते रहे कि मैं ठीक हूँ।' },
        { say: 2, en: 'It sounds like that was hard to hear.', hi: 'लगता है वह सुनना आपके लिए मुश्किल था।' },
        { say: 1, en: 'But at night, when it’s quiet, I don’t feel fine at all.', hi: 'लेकिन रात को, जब सब शांत होता है, मैं बिल्कुल ठीक महसूस नहीं करती।', cueAfter: 3, cue: 'drop', volume: 0.5, tone: { relative: 'softer', label: 'sad', confidence: 0.84 } },
        { silence: 4200 },
        { say: 1, en: 'I don’t… I’m not sure… how to say it.', hi: 'मैं… मुझे नहीं पता… कैसे कहूँ।', cue: 'hesitation', cueAfter: 4, rate: 0.7, tone: { relative: 'softer' } },
        { say: 2, en: 'Take your time. I’m here.', hi: 'आराम से। मैं यहीं हूँ।' },
        { say: 1, en: 'And then my brother says I’m overreacting!', hi: 'और फिर मेरा भाई कहता है कि मैं ज़्यादा प्रतिक्रिया दे रही हूँ!', cue: 'rise', cueAfter: 4, rate: 1.2, pitch: 1.6, tone: { relative: 'intense', label: 'angry', confidence: 0.82 } },
        { wait: 2500 },
      ],
    },
  };

  class Demo {
    constructor(hooks) { this.h = hooks; this.running = false; this.timer = null; this.utter = null; }

    async play(sceneKey, opts) {
      opts = opts || {};
      const scene = SCENES[sceneKey];
      this.running = true;
      const lang = opts.lang === 'hi' ? 'hi' : 'en';
      const aloud = !!opts.aloud && root.speechSynthesis;
      this.h.begin(scene);
      for (const step of scene.steps) {
        if (!this.running) return;
        if (step.queue !== undefined) { this.h.queue(step.queue); await this._sleep(step.wait || 400); continue; }
        if (step.silence) { this.h.silence(step.silence); await this._sleep(step.silence); continue; }
        if (step.wait && !step.say) { await this._sleep(step.wait); continue; }
        if (step.say) {
          this.h.speaker(step.say);
          await this._sleep(350);
          const text = step[lang] || step.en;
          const words = text.split(/\s+/);
          const msPerWord = 330 / (step.rate || 1);
          let spoken = null;
          if (aloud) spoken = this._speak(step.en && lang === 'en' ? step.en.replace('and hedonia', 'anhedonia').replace('dis thymia', 'dysthymia').replace('DSM 5', 'D S M 5') : text, lang, scene.voices[step.say], step);
          for (let i = 1; i <= words.length; i++) {
            if (!this.running) return;
            this.h.interim(words.slice(0, i).join(' '));
            if (step.cue && i === step.cueAfter) this.h.cue(step.cue);
            await this._sleep(msPerWord);
          }
          if (spoken) await spoken;
          this.h.final(text);
          if (this.h.tone) this.h.tone(step.say, step.tone || { relative: 'usual' });
          await this._sleep(700);
        }
      }
      this.running = false;
      this.h.end();
    }

    stop() {
      this.running = false;
      clearTimeout(this.timer);
      if (root.speechSynthesis) root.speechSynthesis.cancel();
      if (this._wake) this._wake();
    }

    _sleep(ms) {
      return new Promise((res) => { this._wake = res; this.timer = setTimeout(res, ms); });
    }

    _speak(text, lang, voice, step) {
      return new Promise((res) => {
        try {
          const u = new SpeechSynthesisUtterance(text);
          u.lang = lang === 'hi' ? 'hi-IN' : 'en-IN';
          const vs = root.speechSynthesis.getVoices().filter((v) => v.lang && v.lang.toLowerCase().startsWith(lang));
          if (vs.length) u.voice = vs[0];
          u.pitch = Math.min(2, (voice && voice.pitch || 1) * (step.pitch ? step.pitch / 1.3 : 1));
          u.rate = (voice && voice.rate || 1) * (step.rate || 1);
          u.volume = step.volume || 1;
          u.onend = u.onerror = () => res();
          root.speechSynthesis.speak(u);
          setTimeout(res, 15000);
        } catch (e) { res(); }
      });
    }
  }

  Demo.SCENES = SCENES;
  root.SanketDemo = Demo;
})(typeof self !== 'undefined' ? self : this);
