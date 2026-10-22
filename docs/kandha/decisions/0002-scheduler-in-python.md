# 0002 · The HapticScheduler lives in Python; intents are generated in the page

**Decision.** Two layers:

1. `browser/kandha/kandha-intents.js` turns engine events into *intents* (`speaker`,
   `new_voice`, `cue`, `silence`, `voice_resumes`). It is the only place that knows engine
   timing, so it owns the back-channel hold and the "voice resumes after silence" timer.
2. `app/kandha/scheduler.py` (`HapticScheduler`) owns priorities, stale dropping, rate limits,
   modes, pre-emption, mirror and the seat lookup, and emits the five-byte HAPTIC commands.
   It is pure: time is passed in, no threads, no I/O.

**Why.** The real stole is driven from Python (`bleak`), so the last decision before the motor
must be in Python or the virtual stole and the real one could disagree. Pure Python is easy to
unit-test with pytest, and the same scheduler runs the tap-budget measurement offline. Keeping
the intent layer in JavaScript avoids shipping engine internals (segment start, speech-end
times) over HTTP and lets `npm test` cover it with the LibriSpeech fixtures.

**Latency.** Page → loopback HTTP → scheduler → bridge write is measured with the mock device;
the budget is ≤ 150 ms in-app. The loopback round trip is a few milliseconds on the test
machine (see `docs/kandha/validation/`).

**Rejected.** Scheduler in JavaScript with Python as a dumb pipe: the virtual stole would be a
second implementation and the Python tests would test nothing real. Scheduler in both: two
implementations drift.

**Would change it.** A Python port of the engine (0001) would move the intent layer to Python.
