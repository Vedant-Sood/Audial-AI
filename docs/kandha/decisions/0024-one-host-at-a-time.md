# 0024 · One host at a time: the stole takes one central, and hand-off is an explicit release

**Status.** Proposed.

**Decision.**
- The stole keeps accepting a single central.
- "Hand over" writes MODE bit1. The stole plays `connected` and disconnects, then advertises.
  The releasing host stays away for 10 s.
- When a host disappears, normal reconnect applies, and the first host to reconnect wins.

**Why.** It needs no new pairing model (decision 0005), and the stole can never get commands
from two schedulers at once.

**Rejected.** Multi-central with arbitration on the stole: two schedulers' taps would
interleave.

**Open.** Q16: preferred host.
