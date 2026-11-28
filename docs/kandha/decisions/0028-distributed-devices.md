# 0028 · Distributed devices: the loudest device's side, from levels only, never audio or time delay

**Status.** Proposed, 28 Nov 2026 (demo build).

**Decision.**
- The laptop and one or two phones on the same Wi-Fi are each given a side when they join.
- Each device sends only a **loudness level** (dB, a few times a second), never audio.
- During a turn, the side whose device is loudest (relative to its own noise floor, with
  hysteresis) is that voice's direction. It goes through `SeatSource` like any other source.
- On screen: "Distributed: uses loudness only; the devices' clocks are not synchronised."

**Why.**
- It's the at-home way to show several directions without new hardware.
- Phone clocks over Wi-Fi drift by milliseconds, far more than the sub-millisecond delays
  GCC-PHAT needs, so time delay is unusable. Level is robust and cheap.
- **Sending levels only means no audio leaves any phone**, so this mode doesn't touch the
  "audio never leaves the laptop" promise.

**Limits.**
- Coarse: the result is "nearest device", not an angle.
- Fooled by a device in a pocket or a person standing between devices.
- Measured accuracy will be reported only for setups actually tried.
