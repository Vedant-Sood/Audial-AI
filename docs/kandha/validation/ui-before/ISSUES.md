# Kandha UI before the demo build: what glitches, overlaps or flickers

Recorded 2026-11-28 on branch `kandha-demo` (from `Kandha-Physical-Final-Software` at `4ae2b81`),
before any UI change.

How it was found:
- **`python -m scripts.check_kandha_layout --fonts both`** (new script). It runs real Chromium
  on the real page with the mock stole, at 1280 × 720, 1920 × 1080, 390 × 844 and 360 × 640.
  Each screen is checked empty and after the seminar demo plus one Hindi caption.
  - **`system`** fonts: what this container has. That includes FreeSans and Unifont, which
    contain Devanagari.
  - **`bundled`** fonts: only what Kandha ships. That's how a minimal Linux install, or Qt
    WebEngine without a Hindi font, sees the page.
  - The screenshots are in [`system/`](system/) and [`bundled/`](bundled/), and the raw
    results in [`report.json`](report.json). 51 of 64 views had at least one issue.
- **The real desktop window** (QtWebEngine 6.8.3, offscreen, 1280 × 720), in
  [`desktop-qt-1280x720/`](desktop-qt-1280x720/).
- **A DOM-churn count** during the seminar demo: nodes added and removed per element, counted
  with a MutationObserver.

| # | Problem | Screen and size | Likely cause |
|---|---|---|---|
| U1 | **Hindi renders as boxes.** Affects the brand "कंधा", the "हिन्दी" toggle, Hindi captions and the translate note | Every screen, every size, `bundled` fonts | Only Atkinson Hyperlegible is bundled. `--font-hi` names Noto Sans Devanagari, Nirmala UI and others that a minimal Linux or Qt install doesn't have |
| U2 | **"✕" close buttons render as boxes** | Every dialog (voice, What did I miss, Learn the taps, Tone), `bundled` | A text glyph used as an icon; Atkinson has no U+2715 |
| U3 | **The Do-not-disturb "◌" renders as a box** | Header, every screen, `bundled` | Text glyph U+25CC used as an icon |
| U4 | **The speaker-arrow icon sits on the "FRONT" label** (reads "FR↑NT") | Live and Seats room diagram, all sizes, browser and Qt window | The direction marker is drawn at the seat edge, right where the zone label is. It's inside the diagram SVG, so the checker's icon rule (≤ 48 px) didn't flag it; seen in the screenshots |
| U5 | **The "F" seat dot overlaps the "Seat changes" lane label** | Review timeline, every size | SVG lane labels and event marks share the left gutter |
| U6 | **The tabs don't fit; "Settings" is cut off and the page scrolls sideways** | Every screen at 360 × 640 (32 views); one tab at 390 × 844 | The tab bar doesn't wrap or scroll at phone widths |
| U7 | **The header takes about 40% of a phone screen** (tabs, mode, speech, DND and status each on their own line) | Every screen at 390 × 844 and 360 × 640 | The header layout was never designed for phones |
| U8 | **Idle caption text and hints overlap the welcome card** | Live, empty, 1280 × 720 and phone sizes | The welcome card sits over the caption panel. Mostly hidden behind it (the checker can't tell occlusion yet), but the hint text spills off-screen at 360 px |
| U9 | **The stole display (the demo's hero) is below the fold** | Live, 1280 × 720, Qt window | The right column stacks Room above Stole; the stole needs scrolling |
| U10 | **Flicker: whole sections are rebuilt on every update.** Room diagram (`#roomLive`) 891 nodes and voice list (`#voices`) 174 nodes in 20 s with 7 caption lines | Live, during speech | `renderRooms()` and `renderVoices()` rebuild by `innerHTML` on every caption, speaker and seat event; `rerenderHistory()` rebuilds the whole transcript on several events |
| U11 | **The fixed bottom bar covers content at phone sizes** ("I want to speak" alone is ~60 px tall) | Every screen, 390 × 844 and 360 × 640 | Fixed footer with a scrapped feature's big button; no content padding for it |
| U12 | **Scrapped features are still shown:** the Lecture mode tab, "I want to speak" and the queue keys, named emotion estimates, "touch a pad within six seconds" help | Live, Seats, Stole, Review, Settings | Not removed yet: Part A in V2_DESIGN, after the deadline |

Checker limits found while doing this, to fix in slice 1:
- it doesn't test occlusion, so text fully hidden behind an opaque card counts as an overlap
  (part of U8);
- the icon rule skips icons inside larger SVG diagrams (U4 was found by eye).
