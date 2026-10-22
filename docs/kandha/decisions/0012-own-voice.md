# 0012 · A voice can be "me": the wearer's own speech never taps

**Decision.** `SeatMap` accepts the pseudo-zone `me` for exactly one voice. The scheduler drops
speaker, new-voice and resume intents for that voice (`dropped` reason `self`); it is never seated
in a room and never saved. The voice dialog has **This is me**; the practicum demo marks Vikram's
voice this way.

**Why.** In practicum the engine hears the wearer too. Tapping "a voice without a seat is
speaking" every time the wearer speaks would be noise, and the mode default ("the other voice is
in front") cannot know which of the two voices is the wearer.
