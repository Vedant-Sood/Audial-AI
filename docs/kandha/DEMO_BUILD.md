# Kandha demo build: plan

Branch `kandha-demo`, made from `Kandha-Physical-Final-Software` at `4ae2b81`. Brief:
[the demo-build prompt, 28 Nov 2026] on top of V2_DESIGN and decisions 0013–0025. Goal: a
home-filmed demo video of Kandha working end to end on the laptop, the phone(s), and the
bench or virtual stole.

**Status: plan. Waiting on the open questions; the defaults apply if they're not answered.**
Everything this branch adds is labelled **demo / test** until measured. Nothing here changes a
portfolio sentence (`Kandha-Physical-Final-Software/PORTFOLIO_CHANGES.md`).

## Baseline (2026-11-28, Linux container, Python 3.12.3, Node 22)

`npm test` 48/48 · `pytest` 225 passed, 1 skipped. The UI problems were reproduced first:
12 issues (U1–U12) in [validation/ui-before/ISSUES.md](validation/ui-before/ISSUES.md), with
screenshots from the browser at four sizes and from the Qt desktop window.

## Slices (demo-critical first; each ends with all tests passing)

**1. UI fixes.**
- Bundle Noto Sans Devanagari (OFL) next to Atkinson (U1).
- Replace text-glyph icons with inline SVG from one icon set (U2, U3).
- Room diagram: labels in a reserved band; the speaker marker goes inside the seat, never on
  the label (U4); review lanes get their own label gutter (U5).
- Phone header: tabs become a scrolling segmented bar; mode, speech and DND move into one
  compact row; no sideways scroll (U6, U7, U11).
- Keyed, incremental updates instead of `innerHTML` rebuilds; meters and dials throttled to
  one update per animation frame (U10).
- Hide the scrapped features everywhere in the UI, per the Q2 default (U12).
- The new **"Who is where?"** speaker view (§5.2 of the brief): a top-down room with You in
  the centre, voice cards, four big side buttons, stacked lists per side, detected vs
  overridden direction, and Join voices / This is me on each card.
- The live stole display stays as it is. It can be shown large and is never below the fold
  at 1280 × 720 (U9).
- The checker learns occlusion and icons inside diagrams, runs in CI, and saves the
  after-screenshots to `validation/ui-after/`.

**2. Audio source modes and the test panel.**
- Mono stays the default.
- **Direction runs in desktop Python, not in the page:** one GCC-PHAT module
  (`app/kandha/direction.py`, 300–4,000 Hz, motor gate, per-turn median) feeds a
  `DirectionSeatSource` through `SeatSource`.
- Order: Recorded/simulated, Stereo (with the fake-stereo detector), then 4-sided.
- A synthetic room generator writes 1-, 2- and 4-channel WAVs with voices at known angles.
- An end-to-end test: 4-channel file → direction → seat map → scheduler → the exact HAPTIC
  bytes on the mock stole.
- A test panel for each mode: level meters, direction dial, zone, "tap the zone I hear", and
  one sentence on what the mode can't do.

**3. Phone site.**
- The desktop app serves `/phone/` over **local HTTPS**, using a locally generated CA and a
  server certificate for the laptop's LAN address.
- Pairing uses a one-time code in a QR. Connected phones are listed, each with a Disconnect
  button.
- Transport is fetch + SSE only, no WebSockets. Safari is known to be strict with
  WebSockets over self-signed certificates; to verify on the iPhone.
- The page is portrait-first at 390 × 844 and 360 × 640, with targets of at least 44 pt. It
  shows big captions, the live stole display, L/R/B/F/Q buttons, the mode, the side it
  represents, and mic on/off with a meter.
- **Distributed mode sends levels only:** each phone sends a loudness number a few times a
  second, never audio. The loudest side wins, with hysteresis.
- **Phone mic** (audio phone → laptop) is a separate mode, **off by default**, because of the
  portfolio's "audio never leaves the laptop" (decision 0029).
- No browser speech recognition. Nothing is stored on the phone (tested).
- Android driving the stole over Web Bluetooth is optional and left out by default (Q7).

**4. Desktop executables.**
- **Linux:** an AppImage with an icon and a `.desktop` entry; it opens with a double click.
- **Windows:** the existing PyInstaller + Inno Setup flow already builds `Kandha.exe` with no
  console (`AccessibilityAI.spec`) and the Kandha installer. Check the shortcuts, the
  uninstaller, the first-run model download screen and plain-word errors, then fill gaps.
- Size lever: Kandha's captions use CTranslate2, not torch. A Kandha-only bundle without
  torch could be far smaller; to measure.
- Verified by installing on a clean CI runner or VM, recording exactly what ran.

**5. Demo / recording mode, and `DEMO_VIDEO_PLAN.md`.** A clean 1920 × 1080 view with large
captions, a visible marker on every tap, and a "Simulated" label on anything simulated. Then
the shot list, setup, audio mode per shot, lines to say, and the shots that must carry the
label. `DEMO_SCRIPT.md` updated to match.

**6. Docs.** USER_GUIDE (audio modes, phone pairing, the speaker view), VALIDATION (measured
vs simulated, per mode), and any affected portfolio sentence listed.

## Decisions (proposed)

| # | Decision |
|---|---|
| [0026](decisions/0026-phone-as-website.md) | The phone is a website served by the desktop app for now; defers 0022 |
| [0027](decisions/0027-audio-source-modes.md) | Audio source modes; all multichannel capture and direction run in desktop Python |
| [0028](decisions/0028-distributed-devices.md) | Distributed devices: level only, no clock sync, levels not audio |
| [0029](decisions/0029-phone-mic-path.md) | Phone → laptop audio: off by default; conflicts with "audio never leaves the laptop" |
| [0030](decisions/0030-local-https-pairing.md) | Local HTTPS with a generated CA, and one-time-code QR pairing |
| [0031](decisions/0031-linux-appimage.md) | Linux packaging is an AppImage |

## Risks

- **Two days to the portfolio deadline.** Default: this branch doesn't feed the portfolio.
- **iPhone certificate trust.** Installing a profile is a one-time chore; it may need trying
  on the phone itself.
- **Bundle size.** torch, Qt WebEngine and the 1.6 GB turbo model.
- **The laptop's stereo mic is unproven.** The three-clip check is still to be run.
