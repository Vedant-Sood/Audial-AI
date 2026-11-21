# 0016 · Tap language v2: retired ids are never reused; crosstalk and off-the-record added

**Status.** Proposed. The step lists are tuned in Slice 2 against the "taps can be told
apart" gate.

**Decision.**

Retired:
- Ids 2 `new_voice`, 7 `queue_ack` and 8 `queue_reminder` are retired, and the generator
  rejects them.
- `lecture` mode, the `queue` priority, `QueueTracker` and `seat_assign_window_s` are removed.

New:
- 13 `crosstalk`: LR, 3 × 100 ms @230.
- 14 `off_record`: B, 600 ms fade down.
- 15 `back_on` is reserved (Q8).
- 16 `bookmark_saved` is reserved (Q7).

Priority: speaker = crosstalk > privacy > cue > silence.

Do not disturb plays no taps (Q9 for low battery and off the record).

**Why.**
- **No reused ids.** A stole still on v1 firmware would play an old meaning for a reused id.
  New ids fail safe: an unknown built-in id plays nothing.
- **Crosstalk** must not feel like the two gentle LR silence ticks, so it is faster and firmer.
- **Off the record** must not feel like low battery's three separate pulses on the same zone,
  so it is one continuous fade.

**Rejected.** Reusing 2, 7 and 8 for the new meanings.
