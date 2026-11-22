# Portfolio sentences to change before 30 November 2026

These follow from the approved v2 answers (22 Nov 2026) and the code as it now stands on
branch `Kandha-Physical-Final-Software`. The quotes are taken from the **Final Project
Summary** (`docs/kandha/FINAL_SUMMARY.pdf`), with its page numbers. Find the same sentences
in the portfolio PDF; its pages may differ.

Rules kept throughout: "designed in line with" the DPDP Act, never "complies with", and no
unmeasured numbers.

## A. Must change (the sentence is now wrong, or was approved to change)

| # | Summary page | Current text | Change to | Why |
|---|---|---|---|---|
| A1 | 4, Design concept | "Audio never leaves the laptop. Bluetooth carries only 5-byte tap commands, pad presses, battery level and direction angles, never audio and never words." | "Audio never leaves the laptop. The stole's Bluetooth link carries only 5-byte tap commands, pad presses, battery level and direction readings (angle, confidence, level, heading, timestamp), never audio and never words." | Q15 (the claim is about the stole's link) and Q10 (heading added) |
| A2 | 8, "What happens to what people say", row *Audio* | "Never recorded and never leaves the laptop. Bluetooth carries no audio or words." | "Never recorded and never leaves the laptop. The stole's Bluetooth link carries no audio or words." | Q15 |
| A3 | 8, Captions and vocabulary / Tone cues | "Named emotion estimates appear only in Review, off by default, and only at 80% confidence or more after at least four utterances from that person." | Delete. Optionally replace with: "Kandha never names an emotion." | Q11: named emotions removed entirely |
| A4 | 2, judges' table, row *Emotion cues may mislead* | "Live cues describe what a voice did, never what someone feels; named emotions only on request" | "Cues describe what a voice did, never what someone feels; Kandha never names an emotion" | Q11 |
| A5 | 14, Measured results, row *Named emotion estimates* | "Right 98% when named; named on 4% of sentences" | Delete the row | Q11; the summary's own open item also says no raw data file was found for it |
| A6 | 15, Measured results, row *Automated tests and builds* | "206 Python and 38 JavaScript tests pass" | Either keep 206/38 as the measured October figures, or write "220 Python and 48 JavaScript tests pass (Linux, 22 Nov 2026)" | The new counts were measured on Linux only. "Windows installer built and installed in CI" was not re-run for them, so don't attach it to the new numbers until CI has run on this branch |

## B. Now true, so keep it (and it can be stated with evidence)

| # | Summary page | Text | Evidence |
|---|---|---|---|
| B1 | 9, row *Live captions* | "No full transcript is ever saved." | The Kandha page has no save and no export; `/api/export` refuses Kandha sessions; the desktop window no longer collects Kandha captions. Proven by a filesystem and network spy test (`docs/kandha/VALIDATION.md`, 22 Nov) |
| B2 | 8, Privacy | "There are no exceptions, so there is no mode that keeps a full transcript." | Same. The consent-box exception that existed in the app is gone |

## C. Still not built: keep it described as *designed*, not working

These sentences are fine **only** while the software-stack table on page 12 keeps
"Privacy layer: … Designed" and "Automatic seat map, pad overrides, Q-pad bookmarks:
Designed". Don't change those two rows to "Built".

| # | Summary page | Text | Status in code |
|---|---|---|---|
| C1 | 9, row *Live captions* | "Held in memory only and wiped automatically after five minutes." | In memory only: true. The 5-minute wipe: **not built** (planned) |
| C2 | 9, rows *Bookmarks*, *Redaction*, *Saved notes* | Q-pad bookmarks, redaction, encrypted notes | **Not built** (planned) |
| C3 | 9, *Anyone can go off the record by speaking* | The whole "Kandha, off the record" list | **Not built** (planned) |
| C4 | 9 and 17, Lecture mode scrapped; 17–18, Q pad only bookmarks, queue scrapped | Lecture mode and "I want to speak" | **Still in the app** until Part A (after the deadline). The summary already says "The app and firmware also still follow the old behaviour", so keep a sentence like that in the portfolio |

## D. Optional: the bench stole now exists

The summary says (page 1): "Hardware | Fully designed and costed; firmware written and
compiling; no physical stole built for Stage 2". If the portfolio should mention the bench
build, suggested wording:

> "A bench prototype of the haptics has been wired (Waveshare ESP32-S3-Zero, six coin motors
> switched by 2N2222A transistors); no measurement has been made on it yet."

If you add that, also update the hardware connections table (page 11). The bench pins are:
- motors on GPIO 8–11;
- battery sense on GPIO 5;
- charge sense on GPIO 6;
- the status light is the board's RGB LED on GPIO 21;
- motor switches are 2N2222A transistors, not AO3400 MOSFETs.

Otherwise leave the table describing the reference design. Don't claim any bench measurement:
none has been made.
