# 0018 · One 5-minute caption memory; Kandha has no transcript save or export

**Status.** Approved 22 Nov 2026; was proposed.

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

**Decided (22 Nov 2026).**
- **Q11.** Review shows **redacted bookmarks only**. Named emotion estimates are **removed
  entirely**, not just from Review.
- **Q12** (default). Audial's own windows and the companion page are unchanged.
- **Q17.** Removing transcript saving and every export ships **before 30 November**. The
  5-minute memory, bookmarks and the Review change wait until after.

**Built (22 Nov 2026), before the portfolio deadline:**
- The Kandha page has no consent box, no save and no export: web page, text, VTT, SRT and
  JSON are all gone.
- `/api/kandha/session/save` is gone.
- The page starts captioning with `origin: "kandha"`, which makes the session private. A
  private `Session` refuses `save()` and `export()`, and `/api/export` answers 403.
- The shared engine keeps caption text out of the desktop window's event queue. Before this
  change, the desktop window collected Kandha's captions and offered to save them when it
  closed.

Tests: `test_kandha_session_cannot_be_saved_or_exported_and_writes_nothing` (a filesystem and
network spy with a canary caption), a control test showing that spy sees an ordinary save,
`test_kandha_captions_never_reach_the_desktop_window_queue`, and two page checks in
`tests/kandha.test.js`. With the private flag switched off on purpose, the first and third
fail.
