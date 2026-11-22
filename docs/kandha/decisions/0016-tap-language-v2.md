# 0016 · Tap language v2: retired ids are never reused; crosstalk and off-the-record added

**Status.** Approved 22 Nov 2026; was proposed. The step lists are tuned in Slice 2 against the "taps can be told
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

**Decided (22 Nov 2026).**
- **Q7.** A saved bookmark is confirmed with one very light, short tick on B:
  **16 `bookmark_saved`, 30 ms @90**. It must be the lightest and shortest pattern in the
  table. Slice 2 tests that it can be told apart from every other pattern.
- **Q8** (default). "Kandha, back on" plays **15 `back_on`** (the 600 ms rise on B), so
  Vikram knows bookmarks work again.
- **Q9** (default). Do not disturb means no taps at all, including low battery and off the
  record. The screen and the status light still show both.
