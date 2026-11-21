# Prompt: Kandha v2 — final design, mic pod, and a phone host

> **How to use this file.** Put two files in the Audial-AI repo:
> 1. This prompt, as `docs/prompts/kandha-v2.md`.
> 2. The PDF `Kandha_Final_Project_Summary.pdf` (19 Nov 2026), as
>    `docs/kandha/FINAL_SUMMARY.pdf`.
>
> Then open Claude Code in the repo root and say:
> *"Read `docs/prompts/kandha-v2.md` and carry it out."*

---

## 0. Your role and how to work

You are the lead engineer for Kandha v2. The **Final Project Summary**
(`docs/kandha/FINAL_SUMMARY.pdf`) is the source of truth for **what** Kandha
does. This prompt adds three things on top of it:
- the hardware **as actually built** (§2);
- the work needed to make the code match that summary (§4);
- a new idea: a **phone app** that can replace the laptop (§6).

When this prompt and the summary disagree, the summary wins on behaviour and
privacy. List each disagreement as an open question.

Work in this order:

1. **Read first.** Read the summary and every file in §3. Run the existing
   tests and record the baseline:
   - `npm test`
   - `python -m pytest -q` with `QT_QPA_PLATFORM=offscreen`

   The summary reports 206 Python and 38 JavaScript tests passing. Follow
   `CONTRIBUTING.md`.
2. **Design doc before code.** Write `docs/kandha/V2_DESIGN.md` covering
   §§4–8. For every real choice, add a decision record in
   `docs/kandha/decisions/`, numbered from 0013. Put ambiguities and
   contradictions under **Open questions**. Then **stop and ask for approval**.
3. **Build in the vertical slices of §9.** Each slice ends with all tests
   passing.
4. **Verify honestly.** Every number comes from a test or measurement you ran.
   Keep simulated results (mock BLE, virtual stole, synthetic audio, stubbed
   ASR) separate from results measured on the real stole, phone or speech.
   The summary says "designed in line with" the DPDP Act, never "complies
   with". Keep that wording.

**Timing.** The Stage 2 portfolio is due **30 November 2026**. Anything you
build after it must not make the portfolio's claims untrue. New work stays
"planned" in docs until it is measured.

---

## 1. The rule that decides everything

The rule is: *Vikram's eyes stay on faces.* Anything he needs without looking
goes to his shoulders as a tap. Screens, laptop or phone, are only for
captions he chooses to glance at, and for notes afterwards.

The privacy rule is: **equal access, not extra access.** Kandha gives him the
notes a hearing classmate could take. It never gives him:
- a full record of what others said;
- a profile of anyone's emotions;
- a list of who said what.

There is no mode that keeps a full transcript.

---

## 2. Hardware: as built vs the final design

A bench prototype now exists. It differs from the summary's hardware section.

| Item | Final summary says | As built (bench, Nov 2026) |
|---|---|---|
| Board | ESP32-S3 | Waveshare **ESP32-S3-Zero** (4 MB flash, 2 MB PSRAM). Onboard WS2812 RGB LED on GPIO 21, so it can be the status light (use `rgbLedWrite`, not `digitalWrite`) |
| Motor switch | AO3400 MOSFET, 100 Ω gate, 10 k pull-down | **2N2222A** NPN: GPIO → 330 Ω → base, 10 kΩ base→GND, emitter→GND, collector→motor −. 1N5819 across each motor; 47 µF across +V/GND |
| Motor pins | GPIO 5–8 | **GPIO 8, 9, 10, 11** = L, R, B, F |
| Battery sense | GPIO 9 | **GPIO 5** (100 k / 100 k divider) |
| Charge sense | — | **GPIO 6**: TP4056 CHRG, 10 k pull-up |
| Touch pads | L, R, B, F, Q | L/R/B/Q on GPIO 1–4; **F pad not wired yet** |
| Mic pod | 4 × INMP441 on two I2S buses + MPU-6050 (I2C) | Not built |
| Battery | 1,200 mAh | Not fitted yet |
| Free pins | — | **7, 12, 13, 14, 15, 16, 43, 44** (14–16 are small pads on the underside) |

**Pin budget, which you must resolve in the design doc.** These all still need
pins:
- the F pad (touch-capable: GPIO 1–14, so 7, 12, 13 or 14);
- 4 × INMP441: two I2S buses, 6 pins, or 4 if both buses can share BCLK/WS
  (prove it);
- MPU-6050 (2 pins).

That is 7–9 pins, against 8 free. Propose an assignment and check it against
the ESP32-S3 strapping-pin and USB-pin rules. If it doesn't fit, say what to
drop: for example, charge sense on GPIO 6 is optional.

Slice 0 also updates the repo to match the bench build:
- `config.h`;
- DESIGN.md §5;
- a decision record amending 0003 for the 2N2222A.

---

## 3. Read these first

- `docs/kandha/FINAL_SUMMARY.pdf`. All of it, especially:
  - "How it works"
  - "Privacy and the law"
  - "Technical feasibility"
  - "Final changes and open items"
- `docs/kandha/DESIGN.md`, `PROTOCOL.md`, `VALIDATION.md`, `USER_GUIDE.md`
- `docs/kandha/decisions/`: all of them
- `app/kandha/*.py`, `browser/kandha/`, `browser/sanket/engine.js`
- `browser/sanket/kandha-patterns.json`: the single source of pattern truth
- `firmware/kandha/*`, `docs/prompts/sanket-kandha-app.md`

---

## 4. Part A — make the code match the final design

The summary says plainly: *"The app and firmware also still follow the old
behaviour."* Fix that first. It needs no new hardware.

1. **Automatic seat map.**
   - Remove the old new-voice flow (the "two taps at the front, touch a pad
     within 6 s" step).
   - New voices are seated from the mic pod's direction, through a
     `MicArraySeatSource` implementing the existing `SeatSource`.
   - Until the pod exists, use a simulated source.
   - Keep the zone mapping: front ±45°, right 45–135°, behind 135–225°,
     left 225–315°.
2. **Pads are overrides.**
   - Pressing L, R, B or **F** while someone speaks reassigns that voice to
     that side. Their next turn taps the new side.
   - Add the F pad to the protocol, `kandha-patterns.json`, the firmware and
     the app.
3. **Q pad = bookmark only.**
   - Remove the queue ("I want to speak") and its tap patterns.
   - Whether a saved bookmark gives a confirming tap is an **open item**:
     ask, don't guess.
4. **Tap language and scheduler per the summary.**
   - Add the crosstalk pattern: two voices at once go to both shoulders, and
     Kandha never guesses.
   - Add the off-the-record pattern.
   - Remove the "two short taps = new voice" and "squeeze = I want to speak"
     patterns.
   - Keep the scheduler rules:
     - speaker taps beat tone cues;
     - at most one tone cue per 3 s, and the same cue at most once per 8 s;
     - drop any tap older than 1.5 s;
     - no turn shorter than 0.6 s is tapped;
     - never tap the same voice twice in a row;
     - "This is me" is never tapped.
5. **Modes.** Seminar, Practicum, Do not disturb. Remove Lecture mode and its
   professor-consent exception completely.
6. **Privacy layer** (summary: "Designed"; build it):
   - **Captions** live in memory only and wipe automatically after **5
     minutes**. "What did I miss?" reads from that memory.
   - **Bookmarks.** A Q press keeps what was just said. Before saving,
     redaction removes names, numbers, speaker labels and tone data
     automatically. There is no review step and no unredacted copy.
   - **Saved notes** are encrypted at rest.
   - **Practicum** saves nothing, ever.
   - **"Kandha, off the record"**, said by anyone, does all of this:
     - wipes the last 5 minutes for everyone;
     - blocks bookmarks until "Kandha, back on" or the session ends;
     - keeps live captions showing;
     - changes the status light's colour;
     - plays the off-the-record pattern.

     Measure detection in noise and report the misses.
7. Update the Learn-the-taps tutorial, USER_GUIDE and the tests to match.

---

## 5. Part B — the mic pod

Build it as the summary specifies:
- a rigid 40 mm board at the front of the stole;
- 4 × INMP441 at the corners;
- an MPU-6050 motion sensor;
- a foam windscreen and silicone-grommet mounting.

**On the ESP32**, direction is worked out on the board:
- GCC-PHAT using Espressif's ESP-DSP FFTs;
- a 300–4,000 Hz band-pass;
- motor gating: ignore frames during a tap and for 100 ms after;
- motion gating: pause direction updates while turning or walking.
- When the torso turns, rotate the seat map using the MPU-6050 so left stays
  left.

**New BLE characteristic: DIRECTION.**
- It notifies angle, confidence, level and timestamp only.
- It carries **no audio and no words**, because the summary promises
  Bluetooth never carries either.
- Add it to `PROTOCOL.md` as a backward-compatible v2. v1 bytes stay
  unchanged, and a v1 host must still work.

**Measure the following and report them per the summary's Phase 2 gate:**
- zone accuracy in a quiet room;
- zone accuracy with noise and with overlap;
- self-noise while walking;
- the time from a turn starting to its direction being known;
- current draw. The summary estimates about 95 mA with the pod and about
  10 h on 1,200 mAh; those are datasheet figures, so measure them.

---

## 6. Part C — new idea: a phone that can replace the laptop

**The owner's idea, in his words:** "external microphones linked to the phone
by Bluetooth; the phone transcribes and summarises, then deletes the summary,
and auto-redacts sensitive information; the ESP32 is told what to fire and
when by the phone or the laptop over Bluetooth."

**Reconcile it with the summary like this.** Propose this in the design doc
and confirm it in the open questions:

- **Phone or laptop as host.** An Android app (Kotlin first; Flutter only if
  a decision record argues for it) does the laptop's job: captions, voice
  engine, seat map, scheduler, BLE protocol v1 + v2.
  - Only **one host controls the stole at a time**. Design the hand-off.
  - Keep "one scheduler" (decision 0002): if the phone runs its own scheduler
    and seat map, prove they match with golden test vectors generated from
    `app/kandha/scheduler.py`.
  - Same latency budget: tap ≤ 300 ms worst case. Measure it on the phone.
- **Microphones for captions.**
  - The stole's link stays audio-free, so caption audio must reach the host
    another way. Compare, with measured word error rate on consented Indian
    English and Hindi speech:
    1. the phone's own mic;
    2. a Bluetooth headset or lapel mic paired **to the phone** (usually one
       mic at a time, 8–16 kHz);
    3. a wired or USB-C wireless lapel mic.
  - Streaming audio from the pod over the stole's BLE link would break a
    published promise. Do it only if a decision record argues for it, the
    portfolio's privacy text changes to match, and the link is encrypted and
    bonded.
- **"Summarise, then delete the summary"** maps onto the summary's privacy
  design:
  - The phone makes a short **"What did I miss?" recap** from the 5-minute
    caption memory.
  - The recap is **redacted** and is **wiped with that memory**. It is never
    saved.
  - The only things kept are Q-pad bookmarks, redacted and encrypted, exactly
    as on the laptop.
  - Practicum keeps nothing.
  - "Off the record" works the same.
- **On the device only.** Transcription (for example whisper.cpp, or
  Android's on-device recognizer), recap (a small on-device model, or an
  extractive recap if the phone can't run one acceptably) and redaction all
  run on the phone. No cloud by default. Audio is never written to disk.

---

## 7. Redaction spec (shared by laptop and phone)

The summary requires automatic removal of **names, numbers, speaker labels
and tone data**, with no review step. Implement it as one specification with
a shared fixture suite. Both the Python and the Kotlin implementations must
pass it.

- **Names:** person names (NER), with a configurable allow-list for course
  terms that look like names.
- **Numbers:**
  - Indian phone numbers (+91 and 10-digit mobiles);
  - Aadhaar (12 digits, Verhoeff check);
  - PAN (`AAAAA9999A`);
  - bank accounts, IFSC codes, card numbers (Luhn check);
  - PIN codes and dates of birth;
  - emails and addresses.
- **Speaker labels and tone data:** stripped from every saved bookmark and
  every recap.
- **Clinical details:** treat them as sensitive, since practicum role-plays
  contain client stories.
- **Report** precision and recall per category, and list the known misses.
  Remember that removing too much costs Vikram a word, while removing too
  little costs someone else their privacy. Tune for that.

---

## 8. Privacy guarantees you must prove in tests

- No audio and no unredacted text ever reaches disk, logs or the network.
  Use a filesystem and network spy in CI.
- The caption memory and the recap are empty 5 minutes after speech, and
  immediately after "off the record".
- Practicum leaves no file behind.
- Saved notes are encrypted at rest.
- The stole's BLE traffic contains only:
  - tap commands;
  - pad presses;
  - battery and status;
  - config;
  - direction angles.

  Capture and check it.

---

## 9. Vertical slices

0. **As-built sync** (§2), including the pin budget.
1. **Design doc + decision records.** Then stop for approval.
2. **Part A:** final behaviour in the laptop app and firmware, plus the F pad,
   on the existing bench stole.
3. **Privacy layer** on the laptop (§4.6, §7, §8).
4. **Mic pod**, first as a bench board, then DIRECTION over BLE, then the
   automatic seat map from real angles.
5. **Android host** (§6), reusing the redaction spec and the scheduler golden
   vectors.
6. **End to end on real hardware.** Report what you measure against the
   summary's gates:
   - taps distinguishable;
   - right zone in a quiet room;
   - ≥ 8 h of battery;
   - < 120 g;
   - survives washing.
7. **Docs.** Update USER_GUIDE, VALIDATION (measured vs estimated), the
   firmware README and the wiring guide. Also list the exact portfolio
   sentences that need changing, if any.

## 10. Do not

- Add any mode or setting that keeps a full transcript.
- Change v1 bytes, or remove the virtual or mock stole.
- Put audio or words on the stole's Bluetooth link without the decision
  record in §6.
- Upload anything by default, store audio, or commit recordings or real
  transcripts.
- Claim a number you didn't measure. The summary already flags two rows (98%
  right-speaker; named emotion) whose raw data wasn't found. Don't repeat
  them as measured.
- Guess when unclear. Ask instead.
