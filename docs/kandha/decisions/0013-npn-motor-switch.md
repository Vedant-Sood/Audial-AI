# 0013 · The bench stole uses an ESP32-S3-Zero and 2N2222A NPN motor switches (amends 0003)

**Status.** Approved 22 Nov 2026; was proposed (V2_DESIGN §2). Describes the bench build of November 2026.

**Decision.** The reference build follows the bench prototype:
- a Waveshare ESP32-S3-Zero (4 MB flash, 2 MB PSRAM), with its WS2812 on GPIO 21 as the
  status light, driven with `rgbLedWrite`;
- one 2N2222A per zone, on GPIO 8–11 = L, R, B, F. Each channel: GPIO → 330 Ω → base,
  10 kΩ base→GND, emitter→GND, collector→motor −. A 1N5819 across each motor, and 47 µF
  across +V/GND.

PWM stays at 20 kHz, 8-bit, with the 15 ms kick.

**Why.** It is what was built, from parts to hand. Through-hole parts are easier to
hand-solder than SOT-23 MOSFETs.

**Costs, compared with 0003's MOSFET.**
- V<sub>CE(sat)</sub> is ≈ 0.3–0.4 V at ≈ 150 mA (estimate) instead of ≈ 0.02 V, so the
  motors run a little weaker. The transistor also dissipates ≈ 50 mW while on.
- The base draws ≈ 7.8 mA from the GPIO.
- Turn-off is slower through the 10 kΩ pull-down. At 20 kHz, very low duties may not switch
  cleanly.

**To measure (Slice 2).**
- Collector voltage under load on L and R (two motors each).
- The lowest duty that starts a motor, which sets `MOTOR_MIN_DUTY`.
- Whether the 120 ms tap is still distinct.

**Would change it.**
- A zone that doesn't saturate (V<sub>CE</sub> > 0.5 V): drop the base resistor to 220 Ω
  (open question Q2) or go back to AO3400s.
- Taps too mushy to tell apart: DRV2605L, as in 0003.

**Decided (22 Nov 2026).** Approved. Q2 (330 Ω or 220 Ω base resistor) is settled after the
Slice 2 measurement. Until then, 330 Ω as built. Slice 0 brought `config.h`, DESIGN §5 and the
firmware README in line with the bench build, and the firmware compiles for the S3-Zero.
