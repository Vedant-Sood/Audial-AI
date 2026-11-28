# 0027 · Audio source modes; every multichannel capture and the direction maths run in desktop Python

**Status.** Proposed, 28 Nov 2026 (demo build).

**Decision.**
- **Modes:** Mono (the default), Stereo, 4-sided, Distributed devices, Phone mic, Bluetooth
  headset (off by default) and Recorded/simulated. Each has a test panel.
- **The page keeps one mono stream** for the voice engine and captions, exactly as today.
- **Direction is separate:** a desktop-Python capture through sounddevice/PortAudio, with 2
  or 4 channels, opened alongside. One module, `app/kandha/direction.py`, does it:
  - GCC-PHAT on every microphone pair;
  - 300–4,000 Hz band-pass;
  - nothing measured during a tap and for 100 ms after;
  - a per-turn median.
- It feeds a `DirectionSeatSource` through `SeatSource`. Taps still go only through
  `scheduler.py` (0002), and pads still override.
- **Fake-stereo detector:** if the two channels correlate almost perfectly, the mode says
  "this mic is really mono" and falls back to Mono.
- **The pod reuses the algorithm, not the code** (C++ on the ESP32, V2_DESIGN §4.2). Both
  must pass the same synthetic-room test vectors.

**Why.**
- Browsers don't reliably give more than 2 channels, and page audio processing can mix
  channels.
- One Python implementation serves stereo, 4-sided and recorded files the same way, and is
  unit-testable on synthetic rooms.

**Limits stated in the app:**
- Stereo tells left from right, not front from back.
- 4-sided needs a 4-channel interface or array.
- Recorded mode is simulated.

**Rejected.** GCC-PHAT in the page's AudioWorklet: it would be a second implementation, and
it's capped at 2 channels.
