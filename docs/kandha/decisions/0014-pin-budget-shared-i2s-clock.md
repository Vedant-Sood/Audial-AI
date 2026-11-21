# 0014 · Pin budget: both I2S buses share one BCLK/WS; the MPU-6050 uses UART0's pins

**Status.** Proposed. The shared clock must be proved on the bench (Slice 4).

**Decision.**

| Function | GPIO |
|---|---|
| F pad | 7 (T7) |
| BCLK, shared | 12 |
| WS, shared | 13 |
| I2S0 DIN | 14 |
| I2S1 DIN | 15 |
| SDA | 44 |
| SCL | 43 |
| Spare | 16 |

Charge sense stays on GPIO 6. I2S0 is master. I2S1 is slave on the same BCLK/WS pins,
through the GPIO matrix.

**Why.**
- **Sync.** GCC-PHAT needs sample-synchronous capture *across* the two pairs. The largest
  real delay across the 40 mm board is ≈ 117 µs (5.6 samples at 48 kHz). Two independent
  masters would add an unknown frame offset, so a shared clock is the only design where
  cross-pair delays mean anything.
- **Pins.** Sharing the clock saves two pins.
- **Pin rules.** None of the chosen pins is a strapping pin (0, 3, 45, 46), a USB pin
  (19, 20) or a flash/PSRAM pin.
- **43/44.** These are free because `Serial` runs over USB CDC. The ROM boot log on 43
  forms no valid I²C START+address, so the MPU-6050 ignores it.

**Proof required.** On the bench, the cross-pair delay of a click at fixed bearings must be
stable to ±1 sample over 1,000 clicks and match the geometry.

**Rejected.**
- Two I2S masters (6 pins). They need a boot-time skew calibration, and use pin 16 plus GPIO 6.
- PDM microphones. They would use the S3's 4-line PDM RX, but the summary specifies INMP441.
- TDM. The INMP441 doesn't support it.

**Would change it.** A failed sync test → the two-master fallback, dropping charge sense.
