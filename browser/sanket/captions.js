/*
 * Sanket captions
 * ---------------
 * Pure logic, no DOM:
 *   - Vocabulary: psychology terms, gentle auto-correction and short definitions
 *   - CaptionAssembler: splits recognised text between speakers using the voice timeline
 */
(function (root) {
  'use strict';

  // ------------------------------------------------------------------ vocabulary
  // [term, plain-language definition, aliases (other spellings / how speech engines hear it)]
  const PSYCH_TERMS = [
    ['anhedonia', 'Loss of pleasure or interest in things a person used to enjoy.'],
    ['dysthymia', 'Long-lasting, low-grade depression (now called persistent depressive disorder).'],
    ['cognitive dissonance', 'Discomfort from holding two conflicting beliefs, or acting against one’s beliefs.'],
    ['schema', 'A mental framework a person uses to organise and interpret information.'],
    ['transference', 'When a client redirects feelings about someone in their life onto the therapist.'],
    ['countertransference', 'The therapist’s own emotional reactions to a client.', ['counter transference']],
    ['rumination', 'Repetitive, passive dwelling on distress and its causes.'],
    ['catastrophising', 'Expecting or imagining the worst possible outcome.', ['catastrophizing']],
    ['cognitive behavioural therapy', 'A therapy that works on the links between thoughts, feelings and behaviour (CBT).', ['cognitive behavioral therapy']],
    ['psychodynamic', 'Approaches that focus on unconscious processes and early relationships.'],
    ['attachment style', 'A pattern of relating to others shaped by early bonds: secure, anxious, avoidant or disorganised.'],
    ['dissociation', 'Feeling disconnected from one’s thoughts, body, memories or surroundings.'],
    ['depersonalisation', 'Feeling detached from oneself, as if watching from outside.', ['depersonalization']],
    ['derealisation', 'Feeling that the surroundings are unreal or dreamlike.', ['derealization']],
    ['psychosis', 'A loss of contact with reality, such as hallucinations or delusions.'],
    ['hallucination', 'Perceiving something that is not there (hearing, seeing, feeling).'],
    ['delusion', 'A fixed false belief that is not shared by others in the person’s culture.'],
    ['hypomania', 'A milder form of mania: raised mood and energy without severe impairment.'],
    ['mania', 'A period of abnormally raised or irritable mood with high energy and reduced need for sleep.'],
    ['bipolar disorder', 'A condition with episodes of depression and episodes of mania or hypomania.'],
    ['generalised anxiety disorder', 'Persistent, hard-to-control worry about many areas of life.', ['generalized anxiety disorder']],
    ['obsessive-compulsive disorder', 'Intrusive unwanted thoughts (obsessions) and repeated actions to relieve them (compulsions).', ['obsessive compulsive disorder']],
    ['post-traumatic stress disorder', 'Lasting distress after trauma: intrusive memories, avoidance and feeling on edge.', ['post traumatic stress disorder']],
    ['panic attack', 'A sudden surge of intense fear with physical symptoms such as a racing heart.'],
    ['comorbidity', 'Two or more conditions occurring in the same person at the same time.', ['co morbidity']],
    ['aetiology', 'The cause or origin of a condition.', ['etiology']],
    ['prognosis', 'The likely course and outcome of a condition.'],
    ['psychometric', 'Relating to the measurement of mental traits and abilities.'],
    ['operant conditioning', 'Learning through the consequences of behaviour: reinforcement and punishment.'],
    ['classical conditioning', 'Learning by association, as in Pavlov’s experiments.'],
    ['reinforcement', 'A consequence that makes a behaviour more likely to happen again.'],
    ['neuroplasticity', 'The brain’s ability to change and form new connections.'],
    ['neurotransmitter', 'A chemical messenger between nerve cells, such as serotonin or dopamine.'],
    ['serotonin', 'A neurotransmitter involved in mood, sleep and appetite.'],
    ['dopamine', 'A neurotransmitter involved in reward, motivation and movement.'],
    ['amygdala', 'A brain region central to detecting threat and processing emotion.'],
    ['hippocampus', 'A brain region central to forming memories.'],
    ['prefrontal cortex', 'The front of the brain, involved in planning, judgement and self-control.'],
    ['self-efficacy', 'A person’s belief in their ability to succeed at a task.', ['self efficacy']],
    ['locus of control', 'Whether a person sees events as controlled by themselves or by outside forces.'],
    ['mindfulness', 'Paying attention to the present moment, on purpose and without judgement.'],
    ['psychoeducation', 'Teaching clients and families about a condition and how to manage it.', ['psycho education']],
    ['motivational interviewing', 'A collaborative style of conversation that strengthens a person’s own motivation to change.'],
    ['active listening', 'Listening with full attention and showing it through reflections and questions.'],
    ['unconditional positive regard', 'Accepting and valuing a client without judgement (Carl Rogers).'],
    ['congruence', 'In therapy, the therapist being genuine: what they show matches what they feel.'],
    ['defence mechanism', 'An unconscious way of protecting oneself from anxiety, such as projection or repression.', ['defense mechanism']],
    ['projection', 'Attributing one’s own unwanted feelings or traits to someone else.'],
    ['repression', 'Unconsciously keeping distressing thoughts or memories out of awareness.'],
    ['sublimation', 'Channelling unacceptable impulses into socially acceptable activities.'],
    ['alexithymia', 'Difficulty identifying and describing one’s own emotions.'],
    ['somatisation', 'Psychological distress expressed through physical symptoms.', ['somatization']],
    ['flat affect', 'Little or no outward expression of emotion.'],
    ['blunted affect', 'Noticeably reduced outward expression of emotion.'],
    ['DSM-5', 'The Diagnostic and Statistical Manual of Mental Disorders, 5th edition.', ['dsm 5', 'dsm five', 'dsm v']],
    ['ICD-11', 'The International Classification of Diseases, 11th revision (WHO).', ['icd 11', 'icd eleven']],
    ['intrusive thoughts', 'Unwanted thoughts or images that pop into the mind and are hard to dismiss.'],
    ['psychotherapy', 'Treatment through talking with a trained professional.'],
    ['case formulation', 'A shared explanation of how a client’s difficulties developed and what keeps them going.'],
  ];

  const keyOf = (s) => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]/g, '');

  function levenshtein(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev = new Array(b.length + 1);
    for (let j = 0; j <= b.length; j++) prev[j] = j;
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let rowMin = i;
      for (let j = 1; j <= b.length; j++) {
        const c = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        cur.push(c);
        if (c < rowMin) rowMin = c;
      }
      if (rowMin > max) return max + 1;
      prev = cur;
    }
    return prev[b.length];
  }

  class Vocabulary {
    constructor(extra) {
      this.terms = [];
      for (const [term, def, aliases] of PSYCH_TERMS) this.add(term, def, aliases, false);
      for (const t of extra || []) this.add(t.term, t.definition || '', t.aliases || [], true);
    }

    add(term, definition, aliases, custom) {
      term = String(term || '').trim();
      if (!term) return;
      const keys = [keyOf(term)].concat((aliases || []).map(keyOf)).filter(Boolean);
      this.terms = this.terms.filter((t) => keyOf(t.term) !== keys[0]);
      this.terms.push({ term, definition: definition || '', keys, words: term.split(/\s+/).length, custom: !!custom });
    }

    remove(term) { const k = keyOf(term); this.terms = this.terms.filter((t) => keyOf(t.term) !== k); }

    customTerms() { return this.terms.filter((t) => t.custom).map((t) => ({ term: t.term, definition: t.definition })); }

    define(term) { const k = keyOf(term); const t = this.terms.find((x) => x.keys.includes(k)); return t ? t.definition : ''; }

    // Returns { text, spans: [{start, end, term}] } with likely mis-hearings corrected.
    process(text, opts) {
      const autocorrect = !opts || opts.autocorrect !== false;
      const tokens = [];
      const re = /\S+/g;
      let m;
      while ((m = re.exec(text))) tokens.push({ w: m[0], start: m.index, end: m.index + m[0].length });
      const out = [];
      const spans = [];
      let i = 0;
      while (i < tokens.length) {
        let match = null;
        for (let n = Math.min(4, tokens.length - i); n >= 1 && !match; n--) {
          const slice = tokens.slice(i, i + n);
          // keep trailing punctuation outside the term
          const lastW = slice[n - 1].w;
          const trail = (lastW.match(/[.,!?;:'")\]]+$/) || [''])[0];
          const lead = (slice[0].w.match(/^[("'\[]+/) || [''])[0];
          const raw = slice.map((s) => s.w).join(' ');
          const k = keyOf(raw);
          if (k.length < 3) continue;
          for (const t of this.terms) {
            if (t.keys.includes(k)) { match = { n, term: t.term, trail, lead, exact: true }; break; }
            if (!autocorrect || k.length < 7) continue;
            for (const tk of t.keys) {
              const maxEd = tk.length >= 12 ? 2 : 1;
              if (Math.abs(tk.length - k.length) > maxEd) continue;
              if (tk[0] !== k[0]) continue; // first letter rarely wrong; avoids odd swaps
              if (levenshtein(k, tk, maxEd) <= maxEd) { match = { n, term: t.term, trail, lead, exact: false }; break; }
            }
            if (match) break;
          }
        }
        if (match) {
          const prefix = out.length ? ' ' : '';
          const startPos = out.join(' ').length + prefix.length + match.lead.length;
          out.push(match.lead + match.term + match.trail);
          spans.push({ start: startPos, end: startPos + match.term.length, term: match.term, corrected: !match.exact });
          i += match.n;
        } else {
          out.push(tokens[i].w);
          i++;
        }
      }
      return { text: out.join(' '), spans };
    }
  }

  // ------------------------------------------------------------------ caption assembly
  // The voice engine knows WHEN the speaker changed; the speech recogniser knows WHAT was said
  // but not who said it. We note when each interim word first appeared, then give every word
  // the speaker who was talking at that moment (allowing for recogniser delay).
  class CaptionAssembler {
    constructor(opts) {
      opts = opts || {};
      this.delay = opts.delay == null ? 0.6 : opts.delay;   // recogniser lag, seconds
      this.minRun = opts.minRun || 2;                       // shortest run of words given its own line
      this.timeline = [];                                   // [{t, id}] speaker changes (audio time)
      this.reset();
    }

    reset() {
      this.wordTimes = [];  // time each word index first appeared
      this.lastCount = 0;
      this.startT = null;
    }

    speakerChange(t, id) {
      // changes can arrive late with an earlier time: keep the list sorted
      this.timeline.push({ t, id });
      this.timeline.sort((a, b) => a.t - b.t);
      if (this.timeline.length > 2000) this.timeline.splice(0, this.timeline.length - 2000);
    }

    relabel(fromId, toId) { for (const c of this.timeline) if (c.id === fromId) c.id = toId; }

    speakerAt(t) {
      let id = null;
      for (const c of this.timeline) { if (c.t <= t) id = c.id; else break; }
      return id;
    }

    _note(text, now) {
      const n = words(text).length;
      if (this.startT == null) this.startT = now;
      if (n > this.lastCount) for (let i = this.lastCount; i < n; i++) this.wordTimes[i] = now;
      this.lastCount = Math.max(this.lastCount, n);
    }

    _split(text, now) {
      const ws = words(text);
      if (!ws.length) return [];
      const known = this.wordTimes.length;
      const ids = ws.map((_, i) => {
        // map word i of this text onto the interim word times seen so far
        // the start of a phrase is stable between interim and final results, so map by position;
        // only squeeze proportionally when the final text came out shorter
        const j = !known ? -1 : ws.length >= known ? Math.min(i, known - 1) : Math.min(known - 1, Math.round((i * known) / ws.length));
        const t = j >= 0 ? this.wordTimes[j] : now;
        return this.speakerAt(t - this.delay);
      });
      return this._runs(ws, ids);
    }

    // Group words into runs of one speaker, folding blips and stray words into neighbours.
    _runs(ws, ids) {
      let runs = [];
      for (let i = 0; i < ws.length; i++) {
        if (runs.length && runs[runs.length - 1].id === ids[i]) runs[runs.length - 1].words.push(ws[i]);
        else runs.push({ id: ids[i], words: [ws[i]] });
      }
      const mergeSame = (rs) => rs.reduce((acc, x) => {
        if (acc.length && acc[acc.length - 1].id === x.id) acc[acc.length - 1].words.push(...x.words);
        else acc.push(x);
        return acc;
      }, []);
      // a short run between two runs of the same speaker is a blip: give it back
      for (let r = 1; r < runs.length - 1; r++) {
        if (runs[r].words.length <= 3 && runs[r - 1].id === runs[r + 1].id) runs[r].id = runs[r - 1].id;
      }
      runs = mergeSame(runs);
      // fold tiny runs into a neighbour so a stray word doesn't get its own colour
      let changed = true;
      while (changed && runs.length > 1) {
        changed = false;
        for (let r = 0; r < runs.length; r++) {
          if (runs[r].words.length >= this.minRun) continue;
          const into = r === 0 ? 1 : r - 1;
          if (into < r) runs[into].words.push(...runs[r].words);
          else runs[into].words.unshift(...runs[r].words);
          runs.splice(r, 1);
          changed = true;
          break;
        }
        runs = mergeSame(runs);
      }
      return runs.map((r) => ({ speakerId: r.id, text: r.words.join(' ') }));
    }

    interim(text, now) { this._note(text, now); return this._split(text, now); }

    // A final caption that comes with its own audio times (local Whisper captions): spread the
    // words evenly over [t0, t1] and give each the speaker talking at that moment. No recogniser
    // delay applies, because these times are audio times.
    timed(text, t0, t1) {
      const ws = words(text);
      this.reset();
      if (!ws.length) return [];
      const span = Math.max(0, (t1 == null ? t0 : t1) - t0);
      const ids = ws.map((_, i) => this.speakerAt(t0 + span * ((i + 0.5) / ws.length)));
      return this._runs(ws, ids).map((p) => Object.assign(p, { t: t0 }));
    }

    final(text, now) {
      if (this.startT == null) this._note(text, now);
      const pieces = this._split(text, now);
      const startT = this.startT == null ? now : this.startT;
      this.reset();
      return pieces.map((p) => Object.assign(p, { t: startT }));
    }
  }

  function words(text) { return String(text || '').trim().split(/\s+/).filter(Boolean); }

  const api = { Vocabulary, CaptionAssembler, PSYCH_TERMS, levenshtein, keyOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SanketCaptions = api;
})(typeof self !== 'undefined' ? self : typeof globalThis !== 'undefined' ? globalThis : this);
