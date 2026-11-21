# 0018 · One 5-minute caption memory; Kandha has no transcript save or export

**Status.** Proposed.

**Decision.**

The memory:
- Captions live only in an in-page `CaptionMemory`, evicted at 300 s.
- "What did I miss?" shows all 5 minutes.
- The Python event buffer keeps the same 300 s limit for Kandha sessions.

What is removed from the Kandha page and blocked for its sessions:
- the Review transcript and timeline export;
- the consent box;
- web page, text, VTT, SRT and JSON export;
- `/api/kandha/session/save`.

Review shows saved bookmarks (Q11).

**Why.** The summary says no full transcript is ever saved, and there is no mode that keeps
one. A consent tick is exactly the kind of exception the summary scrapped along with Lecture
mode.

**Rejected.**
- Keeping export behind a setting: the prompt forbids it.
- Keeping the memory in Python as well as the page: two copies to wipe.

**Open.** Q12: Audial's own windows.
