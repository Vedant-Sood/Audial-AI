# 0029 · Phone → laptop caption audio: local network only, encrypted, in memory, and off by default

**Status.** Proposed, 28 Nov 2026 (demo build). **Needs the owner's decision on wording.**

**Decision.**
- "Phone mic" mode streams the phone's microphone to the laptop's Whisper:
  - over local HTTPS only (0030);
  - in short chunks, as the desktop page already sends to `/api/audio`;
  - held only in memory, never written or logged.
- The mode is **off by default**, and stays off until the owner approves the wording below.

**Conflict.** The portfolio says "Audio never recorded and never leaves the laptop". This
mode sends audio from the phone to the laptop over Wi-Fi, so that sentence would be untrue
whenever it's on.

**Proposed wording, for approval:** "Audio is never recorded and never leaves your own
devices: it stays on the laptop, or travels encrypted from your phone to your laptop over
your own Wi-Fi."

Until that is approved, the demo uses the laptop's microphone for captions. The phone
contributes levels only (0028), which keeps the current sentence true.
