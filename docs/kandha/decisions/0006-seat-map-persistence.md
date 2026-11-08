# 0006 · Saved rooms store zone slot order, never voice identities

**Decision.** A saved room is `{name, slots: ["L", "R", "B", "F", ...], mode, updated}`: the
zone for the first voice to appear, the second, and so on (`null` for a voice without a seat).
Loading a room pre-assigns voice slots in order of appearance; anything can still be changed by
pad, key or drag. In Practicum with no room loaded, `SeatMap.default_for_mode()` seats the
*second* voice to appear in front (`F`) and leaves the first unmapped, because the wearer often
speaks first (and can mark that voice "This is me", decision 0012). A practicum room saved after
that has slots `[null, "F"]`.

**Why.** Voices are session-only clusters, not people (`docs/sanket.md`). Storing anything that
looked like "Priya sits on the left" would promise cross-session recognition that the engine
cannot give and would be a privacy claim. Slot order captures what is useful about a room: the
usual geometry.

**Rejected.** Storing voice embeddings per room for re-identification: out of scope, and the
engine's MFCC means are not reliable identities.

**Future.** `SeatSource` (an angle per voice) is defined so a microphone array can fill the map;
`angle_to_zone()` is in `app/kandha/seatmap.py` with tests.
