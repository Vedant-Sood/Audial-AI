# 0004 · The back-channel hold is 0.6 s

**Decision.** `kandha-intents.js` taps for a speaker decision only once the turn has lasted
`min_turn_s` = 0.6 s (`scheduler.min_turn_s` in `browser/sanket/kandha-patterns.json`). For a
decision made while the person is still speaking the turn is already ≥ 0.64 s (the engine's
`earlyFrames`); for a decision made after a pause, the turn is `speech_end − turn_start`.

**Measurement.** `scripts/kandha_backchannel_study.mjs` runs the engine over the LibriSpeech
fixtures and the A B A B conversation used by `scripts/verify_sanket.py`, with synthetic
back-channels (0.25 s and 0.45 s bursts of the other reader) spliced into the first reader's
turns. The result file is `docs/kandha/validation/backchannel.json`; the numbers in it were
produced by that script, not estimated:

- every real turn (5–8 s) produced its speaker decision with 0.624 s of turn known (an early
  decision at the engine's 40th speech frame) or 1.424 s (a final decision), so a 0.6 s hold
  never delays a real tap;
- the 0.25 s bursts produced no speaker decision at all (the engine keeps them with the current
  speaker: `minShortFrames` is 25 frames, 0.4 s);
- the 0.45 s bursts produced a decision after the pause with 0.48 s of turn known; the 0.6 s
  hold suppresses that tap while the on-screen colour still changes;
- 0.6 s and 0.9 s interjections are decided with 0.624 s known and do tap: by design, a
  deliberate interjection that long is a turn.

**The same hold after a long silence.** The first turn after a long silence taps once
(DESIGN.md section 7.3); a turn shorter than 0.6 s there (a cough, an "mm") taps nothing and
does not use up that tap. The study script also runs resume-after-silence cases (a new voice, a
known other voice, the same voice, and short noise before the real turn) and reports any resume
turn that did not get exactly one seat tap.

**Rejected.** 0.4 s (would let 0.45 s bursts tap); 1.0 s (would hold every early decision back
by 0.36 s for no gain, since the engine's own minimum is 0.64 s).

**Would change it.** Real seminar recordings showing frequent 0.6–1.0 s interjections that
Vikram does not want tapped; the value is one number in the JSON table.
