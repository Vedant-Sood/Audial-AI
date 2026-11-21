# 0015 · The seat map stores bearings, fills itself from a SeatSource, and pads override

**Status.** Proposed. Replaces the new-voice window of 0006 and DESIGN §8.

**Decision.**

How seats are filled:
- `SeatMap` keeps a world-frame bearing per voice. Zones are worked out at tap time:
  `angle_to_zone(bearing − heading)`. The bounds are unchanged.
- A new voice is seated from the median of the confident direction frames within its turn
  (≥ 3 frames, confidence ≥ 0.5; to be tuned).
- A known voice moves only after two consecutive confident turns at a different zone.
- Unclear direction → the remembered seat.

The sources:
- `MicArraySeatSource` reads DIRECTION frames.
- `SimulatedSeatSource` is the default until the pod exists.
- `ManualSeatSource` remains.

Pads:
- A single press of L, R, B or F reassigns the voice speaking now to that zone's centre
  bearing.
- The 6 s window, the `new_voice` intent and pattern, and `assign-new` are removed.

**Why.**
- These rules are the summary's "How it works", unchanged.
- Bearings, rather than zones, are what make rotation by the motion sensor possible.
- Two turns before moving a seat stops one reflection from moving a person.

**Rejected.**
- Storing zones only: the map can't rotate.
- Moving a seat on one disagreeing turn: one noisy frame would move a person.

**Open.** Q3 (new voice, no direction), Q4 (pad with nobody speaking), Q5 (double and long
gestures).
