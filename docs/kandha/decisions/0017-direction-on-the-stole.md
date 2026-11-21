# 0017 · Direction is computed on the stole and sent as DIRECTION (protocol v2), never audio

**Status.** Proposed.

**Decision.**

The firmware does the direction maths:
- GCC-PHAT on 6 microphone pairs with ESP-DSP FFTs, 300–4,000 Hz;
- a voice-activity gate, a motor gate (during taps and for 100 ms after) and a motion gate;
- heading from the gyro.

The characteristic is `…c106` DIRECTION (notify):
`[t_ms u32][heading_cdeg u16][n u8] n×[angle_cdeg u16][confidence u8][level u8]`, n ≤ 2.
Two sources means crosstalk.

Other v2 additions:
- `…c107` MODE (write, 1 byte): bit0 off-the-record light, bit1 release for hand-off.
- `STATUS.flags` bit6 = pod present, bit7 = off the record.
- INPUT pad 5 = F.
- v1 bytes are unchanged, and a v1 host keeps working.

**Why.**
- The summary promises that Bluetooth carries no audio and no words. Angles are a few bytes.
- On-board gating knows exactly when the motors run.

**Rejected.**
- Streaming the pod's audio to the host: it breaks the published promise, and BLE bandwidth
  is marginal.
- Folding the light into CONFIG: that changes v1 bytes.

**Open.** Q10: the heading field goes beyond the prompt's "angle, confidence, level,
timestamp only".
