# 0003 · Motors are driven by logic-level MOSFETs and PWM, not DRV2605L drivers

**Options compared.**

| | DRV2605L + TCA9548A multiplexer | Logic-level MOSFET + PWM |
|---|---|---|
| Tap quality | Excellent: overdrive and active braking from the driver's library, auto-calibration for ERM/LRA | Good: overdrive kick in firmware (first 15 ms at 100 %), no active braking, so an ERM coasts for ≈ 50–100 ms after a tap |
| Parts per zone | one DRV2605L breakout (fixed I²C address 0x5A) behind one mux channel; 4 breakouts + 1 mux | one SOT-23 MOSFET, one Schottky diode, two resistors |
| Cost (₹, 2026 retail) | 4 × 350–500 + 150 ≈ ₹1,550–2,150 | 4 × 15 + 4 × 5 + ≈ 10 ≈ ₹90 |
| Weight and wiring | five boards, I²C bus through the stole, 4 × (VCC, GND, SDA, SCL, EN) | one small carrier next to the ESP32, two wires per motor group |
| Latency | I²C mux select + register write ≈ 0.2 ms, then driver ramp | `ledcWrite()` ≈ instant |
| Pattern fidelity to the JSON table | the driver's own waveforms or RTP mode; levels must be mapped onto the driver | exact: the firmware plays the table's `on_ms/off_ms/level` steps directly |
| Failure modes | bus wiring faults stop every zone; EN pins needed to isolate drivers | one failed MOSFET stops one zone |
| Power | each driver draws its own quiescent current (≈ 0.5 mA × 4) | none |

**Decision.** MOSFET + PWM for the reference build: it is cheaper by an order of magnitude,
lighter, simpler to sew into a scarf, and plays the shared pattern table exactly, so the
virtual stole, the tests and the firmware all run the same step lists. The firmware adds an
overdrive kick so 120 ms taps feel crisp: a motor runs at full duty for its first 15 ms
(`MOTOR_KICK_MS`) whenever it starts from rest, timed from that start; a step or command that
takes over within those 15 ms keeps the kick until they are up, and a motor already spinning
gets none. It also raises any non-zero duty below 60/255 (`MOTOR_MIN_DUTY`) to 60, because a
coin ERM does not start below it. The app's pattern player and the virtual stole leave both
out; `tests/test_kandha_firmware_host.py` checks the firmware against them with both added.

**Rejected.** DRV2605L drivers remain the upgrade path if user tests say taps feel mushy on
the chosen motors (LRA motors with braking would be the next step). The pin map leaves the
I²C pins free.

**Would change it.** User testing showing the 120 ms tap is not distinct from the 60 ms
new-voice taps, which the driver's braking would fix.
