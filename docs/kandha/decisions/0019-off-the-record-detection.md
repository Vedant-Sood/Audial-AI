# 0019 · "Kandha, off the record" is detected in the caption text

**Status.** Proposed. Detection is measured in noise before it is described as working.

**Decision.**
- Fuzzy-match the phrase, and "Kandha, back on", in finished caption text.
- "Kandha" is in Whisper's `initial_prompt`, and the matcher accepts the mis-hearings found
  in measurement.
- Effects follow the summary: wipe, block bookmarks, captions continue, the light's colour
  changes (MODE), and the `off_record` pattern plays.

**Why.**
- No second audio pipeline and no extra model.
- It works the same on the laptop and the phone.
- Caption latency (≈ 2–3 s) is harmless, because the wipe covers the preceding 5 minutes.

**Rejected.** A keyword-spotting model, which would be one more model to ship, license and
validate. It is still the fallback if the measured miss rate is poor.

**Measurement.** 5 SNRs × voices with the real Whisper model. Synthetic (TTS) first, labelled
simulated; then consented speakers, with recordings never committed. Report detection, false
triggers and every miss.

**Open.** Q13: Hindi phrases.
