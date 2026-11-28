# Kandha UI after slice 1 (2026-11-28)

`python -m scripts.check_kandha_layout --fonts both --output docs/kandha/validation/ui-after`
checked 72 views:
- 4 sizes (1280 × 720, 1920 × 1080, 390 × 844, 360 × 640);
- 5 screens empty and after the seminar demo, plus the What-did-I-miss and Audio-test dialogs;
- system fonts and bundled-fonts-only.

**Result: 0 views with overlapping text or icons, missing-glyph boxes or spill.** Before:
51 of 64 (see [`../ui-before/ISSUES.md`](../ui-before/ISSUES.md)). The accessibility audit
(`scripts.audit_kandha_a11y`) still passes in both themes.

| # | Fix |
|---|---|
| U1 | Noto Sans Devanagari (OFL 1.1) bundled, so Hindi renders with only Kandha's own fonts |
| U2, U3 | Close and do-not-disturb icons are inline SVG in the app's one icon style |
| U4 | The front label sits above its seat, clear of the "facing" arrow; 3 or more voices on a side stack in rows |
| U5 | The taps lane is tall enough for its zone letters |
| U6, U7, U11 | Phone header in three short rows (brand and status; tabs filling the width; mode, speech and DND wrapping); no sideways scroll; 44 px dock buttons |
| U8 | Long hints wrap; the checker now ignores text hidden behind an opaque card |
| U9 | The live stole display comes first in the side panel: visible at 1280 × 720 without scrolling |
| U10 | The room diagram, voice list and current caption update only when what they show changed. Before, the room diagram was rebuilt on every caption (891 DOM nodes in 20 s) |
| U12 | Lecture mode, the "I want to speak" queue and its keys, the Lecture cue column, the queue reminder, named emotion estimates, and the unverified "98% right speaker" sentence are hidden everywhere in the UI. The code stays until Part A |

Also new in this slice:
- **"Who is where?"** replaces the old Seats screen:
  - a top-down room with You in the middle;
  - one card per voice, with its colour, shape, name and how its seat was set;
  - four big side buttons;
  - This is me, rename and Join voices beside them;
  - dragging still works, as an extra.
- **The Audio test dialog:**
  - input level per channel;
  - a direction dial and zone;
  - "tap the zone I hear";
  - one sentence on what the mode can and can't do;
  - a "Simulated" badge for recorded files.

The checker itself was fixed twice while doing this: occlusion, and text clipped by its own
box.
