# Kandha v2 design

**Status: approved 22 Nov 2026.** The answers to the open questions are in
[§9.1](#91-answers-22-nov-2026). Before the 30 November portfolio deadline, only two things
ship: Slice 0, and the removal of transcript saving and export (§5.1, decision 0018). Both are
built. Everything else is planned and waits until after the deadline, on a separate branch.

This document covers §§4–8 of [the v2 prompt](../prompts/kandha-v2.md). The
[Final Project Summary](FINAL_SUMMARY.pdf) (19 Nov 2026) is the source of truth for behaviour
and privacy. Where this document, the prompt and the summary disagree, the disagreement is
listed under [Open questions](#9-open-questions) rather than settled here. Decisions 0013–0025
in [decisions/](decisions/) record each real choice.

Words used for status, as in the summary:
- **Built**: in the repo and passing tests.
- **Planned**: designed here, not built.
- **Measured**: a number from a test or measurement, with the record named.
- **Estimate**: from datasheets or arithmetic.

Until something is measured, the docs and the portfolio call it planned. The portfolio is due
30 November 2026.

## 0. Baseline and what was read

**Read.**
- The whole summary.
- DESIGN, PROTOCOL, VALIDATION and USER_GUIDE.
- Decisions 0001–0012.
- `app/kandha/` (scheduler, seat map, protocol, service, bridge).
- The Kandha page (`app.js`, `kandha-intents.js`).
- `kandha-patterns.json`.
- The firmware (`kandha.ino`, `config.h`, `touch_pads.h`, `pattern_engine.h`, README).

`engine.js` was read only for overlap handling: it has none.

**Test baseline.**
- `npm test`: 46 of 46 passed.
- `pytest`: see [`Kandha-Physical-Final-Software/BASELINE.md`](../../Kandha-Physical-Final-Software/BASELINE.md).

The summary's "206 Python and 38 JavaScript" tests are the count recorded in VALIDATION.md on
22 Oct 2026. The JavaScript suite has grown since then, so 46 is not a regression.

## 1. Where the code differs from the summary today

| # | Summary (final design) | Code today | Where |
|---|---|---|---|
| D1 | Modes: Seminar, Practicum, Do not disturb | `lecture` mode with `single_speaker` | `kandha-patterns.json` `modes`; `service.py` `MODES`, `_default_cues` |
| D2 | New voices are seated from the pod's direction | "Two taps at the front" `new_voice` pattern (id 2) and a 6 s pad window | `seatmap.py` `new_voice`, `on_pad`; `scheduler.py`; pattern id 2; `seat_assign_window_s` |
| D3 | A single press of L/R/B/F reassigns the voice speaking now | Tap assigns the *new* voice in the window, double-tap reassigns the current voice, long press clears it | `seatmap.py` `on_pad`; PROTOCOL "What the app does" |
| D4 | Five pads: L, R, B, F, Q | Four pads; `PAD_Q = 4`; a v1 host rejects any other pad value (and ignores it, see §5.4) | `protocol.py` `PAD_NAMES`; `touch_pads.h` |
| D5 | Q only bookmarks; no queue | `QueueTracker`, `queue_ack` (7), `queue_reminder` (8), "I want to speak", Q key, Q long press toggles do-not-disturb | `scheduler.py`, `service.py` `set_queue`, `app.js` |
| D6 | Crosstalk pattern on both shoulders | None. `engine.js` has no overlap detection. Audial's `Caption.overlap` (diarization) arrives with 2 s packets, too late for a tap | — |
| D7 | Off-the-record pattern on the back of the neck | None | — |
| D8 | No full transcript is ever saved; captions wiped after 5 minutes | The Review screen keeps the whole session in the page. With a consent tick it saves the session (`/api/kandha/session/save`) and exports web page, text, VTT, SRT and JSON | `app.js` `exportText`, `exportHTML`, `exportAudial`; `browser.py` `session/save` |
| D9 | "What did I miss?" reads the 5-minute memory | Shows the last 30 s | `app.js` `#missBtn` |
| D10 | Do not disturb: "No taps; captions and bookmarks continue" | DND keeps queue taps | `kandha-patterns.json` `dnd.queue: true` |
| D11 | Status light shows captioning, changes colour off the record | Single-colour LED on GPIO 48 with `digitalWrite` | `kandha.ino` |
| D12 | Hardware table: MOSFETs on GPIO 5–8, battery on 9 | Same as the summary, but the bench build differs (§2) | `config.h`, DESIGN §5 |

## 2. Hardware as built, and the pin budget (Slice 0)

### 2.1 Bench build

The bench build has:
- a Waveshare ESP32-S3-Zero;
- an onboard WS2812 on GPIO 21, driven with `rgbLedWrite`;
- four 2N2222A channels, one per zone, with motors on GPIO 8, 9, 10 and 11 (L, R, B, F);
- battery sense on GPIO 5 (ADC1, so it still works while BLE is on);
- charge sense on GPIO 6;
- pads L, R, B and Q on GPIO 1–4.

Two notes on the transistors (decision [0013](decisions/0013-npn-motor-switch.md)):

- **Base drive.** The 330 Ω resistor gives ≈ 7.8 mA of base current. A shoulder zone is two
  motors in parallel on one transistor, ≈ 150 mA (estimate), so the forced gain is ≈ 19. That
  saturates a 2N2222A, but with V<sub>CE(sat)</sub> ≈ 0.3–0.4 V instead of a MOSFET's ≈ 0.02 V,
  so the motors run a little weaker.
- **PWM at 20 kHz.** The 10 kΩ base pull-down turns the transistor off slowly, so low PWM
  duties may not switch cleanly. `MOTOR_MIN_DUTY` (60) and the 15 ms kick may need retuning.

All of this is to be measured in Slice 2: collector voltage under load, and whether a 120 ms
tap still feels distinct.

### 2.2 Pin budget

Still needed: the F pad, four INMP441 microphones and an MPU-6050.

The free pins are 7, 12, 13, 14, 15, 16, 43 and 44. Pins 14–16 are underside pads.

ESP32-S3 rules that apply:
- Strapping pins are 0, 3, 45 and 46.
- GPIO 3 is already PAD_B. It is a strapping pin only when the JTAG eFuse is set, which is
  not the default. That is acceptable, but it is noted in `config.h`.
- USB uses 19 and 20.
- Flash and PSRAM use 26–32.
- 43 and 44 are UART0. The ROM prints its boot log on 43.

**Proposal (decision [0014](decisions/0014-pin-budget-shared-i2s-clock.md)): 7 pins, with one
spare. Charge sense stays.**

| Function | GPIO | Why there |
|---|---|---|
| `PAD_F` | **7** | Touch-capable (T7) and on the top edge |
| I2S BCLK (shared) | **12** | Top edge; the fastest signal (3.07 MHz at 48 kHz × 64) gets the shortest wire |
| I2S WS (shared) | **13** | Top edge |
| I2S0 DIN (mics 1+2, L/R) | **14** | Input only; underside pad is fine for a data line |
| I2S1 DIN (mics 3+4, L/R) | **15** | Input only; underside |
| MPU-6050 SDA | **44** | UART0 RX. The firmware uses USB CDC for `Serial`, so UART0 is free |
| MPU-6050 SCL | **43** | UART0 TX. The boot log toggles it once at reset; an I²C slave ignores that because there is no valid START+address. The GY-521 board already has 4.7 kΩ pull-ups |
| spare | 16 | — |

**Shared BCLK/WS is required, not just a way to save pins.** GCC-PHAT compares arrival times
*between* microphones. The two pairs live on different I2S peripherals, and with two
independent masters their frames would start at unrelated moments. The cross-pair delay would
then be meaningless, even though the largest true delay is only ≈ 117 µs (5.6 samples).

The plan:
- I2S0 runs as master and drives BCLK and WS.
- I2S1 runs as slave and takes BCLK and WS from the same pins through the GPIO matrix.
- Both start from one `i2s_channel_enable` sequence, with I2S1 enabled first so it waits for
  the clock.

**Proof (Slice 4, bench).** Play a click from a speaker at 0° and at 90°. Check that:
- the cross-pair delay is stable to ±1 sample over 1,000 clicks;
- the delay matches the geometry.

If that fails, the fallback uses 2 more pins: two masters, with the clock skew calibrated at
boot from a shared click. That would need 16 *and* dropping charge sense (GPIO 6), and is
recorded as the alternative.

### 2.3 Files Slice 0 changes

- `config.h`: new pins; `PIN_STATUS_LED 21` with an `RGB` flag.
- `kandha.ino`: `rgbLedWrite`.
- `DESIGN.md` §5: parts, pin map and wiring.
- The firmware README.
- Decision 0013 amends 0003. 0003 stays as written, with a note pointing at 0013.

No protocol change is needed. The tests already cover the pattern table and firmware header
generation, and CI compiles the firmware. The CI board target changes from `esp32s3` to the
same FQBN with the S3-Zero options (4 MB flash, QSPI PSRAM).

## 3. Part A: the code matches the final design (Slice 2)

### 3.1 Automatic seat map, pads as overrides

Decision [0015](decisions/0015-seat-map-bearings.md).

**Bearings, not just zones.** `SeatMap` keeps a **bearing** for each voice, in a world frame,
in degrees. It does not store only a zone, because the map has to rotate when Vikram turns
(the summary's "left stays left"). Zones are worked out when a tap is played:
`angle_to_zone(bearing − heading)`. `angle_to_zone` and its ±45° / 45–135° / 135–225° /
225–315° bounds stay exactly as they are.

**`SeatSource` gets an event interface.** `ManualSeatSource` stays.

```text
class SeatSource(Protocol):
    def angles(self) -> dict            # unchanged: {voice: degrees, torso frame}
    def observe(self, t) -> Observation | None
        # (t, sources: [(angle, confidence, level)], heading)
```

- **`MicArraySeatSource`** consumes DIRECTION notifications (§4.3).
- **`SimulatedSeatSource`** is the default until the pod exists. It is scripted per voice in
  the demo and in tests, and can be told to give low confidence, two sources, or a turn of the
  body.

**Joining a turn to a direction.** The host has the voice and the turn start from the engine,
and a stream of angles with stole timestamps. A turn gets the **median angle of the frames
inside the turn** whose confidence is ≥ `dir_min_conf` (0.5, to be tuned in Slice 4). It needs
at least `dir_min_frames` (3) such frames.

Stole time is mapped to host time with a running minimum of `arrival − t_stole`. That is good
enough at turn scale (≥ 0.6 s); bench-measuring it is part of Slice 4.

**Rules.**

| Situation | What happens | Tap |
|---|---|---|
| New voice, direction known | Seat ← that bearing | One firm tap on that side (summary step 4) |
| Known voice, direction agrees | Nothing changes | Tap on its saved side |
| Known voice, direction confidently different for 2 turns in a row | Seat moves ("when the pod notices someone has moved") | Tap on the new side |
| Direction unclear (low confidence, motion-gated, no pod) | Remembered seat used | Tap on the remembered side |
| New voice, direction unclear | **Open question Q3**. Proposed: no seat tap; the caption still appears | — |
| Two confident sources at once | Crosstalk (§3.3) | Crosstalk pattern |
| Pad L/R/B/F pressed while a voice is speaking | That voice ← that zone's centre bearing at the current heading | Next turn taps there |
| Pad pressed while nobody is speaking | Ignored | **Open question Q4**: confirm with a tap? |
| "This is me" voice | Never seated, never tapped (decision 0012, unchanged) | — |

**Removed:**
- `SeatMap.pending` and the 6 s window (`seat_assign_window_s`);
- the `assign-new` action;
- the `new_voice` intent and pattern;
- `no-window`.

**Pad gestures.** A **tap** is the override. **Double** and **long** have no meaning in the
summary. Proposed: double acts the same as tap, and long does nothing. That leaves Q's long
press (today it toggles DND) as **open question Q5**.

**Saved rooms** (decision 0006) still store zones in slot order. They pre-seat voices only
when the pod gives no direction. Practicum's "partner in front" default becomes the same kind
of fallback: when the pod has a direction, the pod wins.

### 3.2 Q pad: bookmark only

A tap on Q (or the `B` key; `Q` is freed) makes a bookmark. It takes the caption memory from
`now − bookmark_window_s` to now, redacts it (§6) and stores it encrypted (§5.3).

`bookmark_window_s` is proposed at 30 s, the same span "What did I miss?" shows today. That
is **open question Q6**.

Removed:
- `QueueTracker`;
- `queue_ack`;
- `queue_reminder`;
- the queue strip;
- "I want to speak";
- `queue_reminder_s`.

A confirming tap is the summary's own open item, **Q7**. The design reserves a pattern id for
it but does not play it until it is decided.

### 3.3 Tap language and scheduler

Decision [0016](decisions/0016-tap-language-v2.md).

**Ids are never reused.** Ids 2 (`new_voice`), 7 (`queue_ack`) and 8 (`queue_reminder`) are
**retired**, not reused. A v1 firmware still on a stole would otherwise play the old meaning
of a new id. The generator keeps retired ids as reserved and rejects them.

| id | key | zone | steps (proposal; tuned in Slice 2 against the "taps can be told apart" gate) |
|---|---|---|---|
| 13 | `crosstalk` | LR | 3 × (100 ms @230, rest 60): both shoulders together, fast and even, unlike the two gentle silence ticks |
| 14 | `off_record` | B | one 600 ms fade 255 → 60 (6 steps), unlike low battery's three separate pulses |
| 15 | `back_on` | B | one 600 ms rise 60 → 255. Played when "Kandha, back on" is heard (Q8) |
| 16 | `bookmark_saved` | B | one 30 ms tick @90: the lightest, shortest pattern in the table (Q7) |

**Scheduler.**
- Priority order: `speaker` = `crosstalk` > `privacy` (off_record, back_on) > `cue` >
  `silence`. `queue` is removed.
- Kept unchanged, with their tests:
  - speaker taps beat cues;
  - one cue per 3 s, the same cue once per 8 s;
  - stale after 1.5 s;
  - never the same voice twice in a row;
  - never "me";
  - the 0.6 s minimum turn (the back-channel hold in `kandha-intents.js`).
- **Crosstalk.** A crosstalk intent clears `last_tapped_voice`, so "then taps whoever keeps
  talking" works. Whoever keeps talking is tapped once the pod reports a single source again
  for ≥ 0.6 s. Crosstalk is itself rate-limited to once per 3 s, so a long overlap doesn't buzz
  constantly.
- **Do not disturb** plays no taps at all, which drops the queue exception. Whether DND also
  silences `low_battery` and `off_record` is **Q9**.

**Modes.** `lecture` is removed from the JSON, `MODES`, `_default_cues`, the page, the demo
script and the tutorial, along with `single_speaker`. Saved settings with `mode: "lecture"`
load as `seminar`.

**Crosstalk without a pod.** Nothing in the current software can detect overlap in time to
tap. Until the pod exists, crosstalk comes only from the simulated source. This goes in the
docs as "planned".

### 3.4 Tutorial, user guide and tests

- `tutorial_order` becomes `seat_tap, crosstalk, drop, rise, hesitation, silence, off_record,
  low_battery`.
- USER_GUIDE, DEMO_SCRIPT and the tests for D1–D10 are rewritten.
- The old tests for the queue, the window and lecture mode are **deleted along with the
  behaviour**, not skipped. New tests replace them.

## 4. Part B: the mic pod (Slice 4)

### 4.1 Hardware

Built as in the summary:
- a 40 mm rigid board;
- INMP441 at the corners, with L/R select so each data line carries one pair;
- an MPU-6050;
- a grommet housing and a foam windscreen.

Wiring follows §2.2.

### 4.2 Firmware direction pipeline

Decision [0017](decisions/0017-direction-on-the-stole.md).

1. I2S at 48 kHz, 32-bit slots, 24-bit samples. Frames of 1,024 samples (21.3 ms), with a
   50 % hop.
2. Band-pass 300–4,000 Hz in the frequency domain: zero the bins outside the band before PHAT
   weighting.
3. GCC-PHAT on the 6 microphone pairs, using ESP-DSP `dsps_fft2r_fc32` with 4× zero-padded
   interpolation around the peak. Least-squares fit of the bearing from the 6 delays.
   Confidence is the peak-to-sidelobe ratio, mapped to 0–255.
4. A second peak with ≥ 0.7 of the first peak's height, ≥ 60° away, is reported as a second
   source. This is how crosstalk is detected.
5. Gates. No DIRECTION is sent while a gate is active, so a gated frame is simply absent:
   - **Voice-activity gate**: frame energy above a running noise floor.
   - **Motor gate**: `PatternEngine::playing()`, plus 100 ms after the last step.
   - **Motion gate**: gyro magnitude above `MOTION_GATE_DPS` (30 °/s, to be tuned), or the
     accelerometer variance above a walking threshold.
6. Heading: gyro z integrated while still, with bias re-estimated whenever the stole is still
   for ≥ 2 s. The MPU-6050 has no magnetometer, so heading drifts. Drift is corrected
   implicitly: each confident observation re-anchors the voice it belongs to. Bench-measuring
   the drift (°/min) is a Slice 4 item.

**Latency target.** Turn start → direction known ≤ 300 ms (3 confident frames plus a BLE
interval). To be measured.

### 4.3 Protocol v2: DIRECTION

The new characteristic is `…c106` DIRECTION (notify). Its payload is little-endian, 7 + 4n
bytes, with n = 0–2:

```text
[t_ms u32][heading_cdeg u16][n u8] then n × [angle_cdeg u16][confidence u8][level u8]
```

- **`t_ms`**: the stole's `millis()` at the end of the frame.
- **`angle`**: centi-degrees, clockwise from straight ahead, torso frame, 0–35,999.
- **`level`**: dBFS + 128.
- **`n = 0`**: "listening, no confident source". Sent at most every 500 ms so the host can
  tell a silent pod from a lost one.

**Heading is one more field than the prompt's list** (angle, confidence, level, timestamp).
It is a motion reading, not audio or words. Without it the host can't rotate the seat map,
because the seat map lives on the host. This is **open question Q10**. The alternative is for
the stole to report world-frame angles only and keep the heading to itself. Then pad overrides
and taps after a turn would still need the heading, so it would come back in another
characteristic.

**Backward compatibility.**
- The HAPTIC, PATTERNS, INPUT, STATUS and CONFIG bytes are unchanged.
- A v1 host never subscribes to `…c106`.
- `STATUS.fw_major` ≥ 1 marks a v2 stole.
- `STATUS.flags` bit 6 is "mic pod present", and bit 7 is "off the record" (the stole's light).
  Bits 6–7 were unused in v1.
- INPUT gains pad 5 = F. A v1 host already ignores unknown pads. `PadInput.decode` raises,
  and `StoleBridge._on_input` catches the error, which a test will pin down.
- CONFIG stays 7 bytes. The off-the-record light is switched by a **new** characteristic
  `…c107` MODE (write, 1 byte: bit0 off-the-record). This avoids changing CONFIG's layout.

### 4.4 What gets measured (Phase 2 gate)

The method for each item is in `docs/kandha/validation/pod-protocol.md`, to be written in
Slice 4.

| Item | Method |
|---|---|
| Zone accuracy, quiet room | A loudspeaker playing consented or LibriSpeech speech at 8 bearings × 3 distances (1, 2, 3 m). Report % correct zone, per zone, with B separately |
| Zone accuracy, noise and overlap | The same, with café noise at 0 and 10 dB SNR, and two speakers at once. Report crosstalk detection rate and wrong-zone rate |
| Self-noise while walking | Wearer walks and turns in a quiet room. Report false DIRECTION frames per minute with gating on and off |
| Turn start → direction known | Speaker onset (from the loudspeaker's own trigger) → first confident notification at the host. p50/p95 |
| Current | USB power meter on the battery line: idle connected, pod running, the Seminar tap load. Hours on the measured 1,200 mAh cell, against the summary's ≈ 95 mA / ≈ 10 h estimate |

## 5. Privacy layer (Slice 3)

Decision [0018](decisions/0018-caption-memory-and-no-transcripts.md).

### 5.1 Caption memory

**One memory, in the page.** `CaptionMemory` is a ring of
`{t, text, voice, zone, tone…}` lines.
- Lines older than 300 s are evicted on a 1 s timer, and on every read.
- "What did I miss?" shows the whole 5 minutes (D9).
- The Review screen loses its transcript, timeline export, consent box and all export
  buttons. Review shows **only the saved bookmarks** (Q11 asks what else, if anything).

**Python side.**
- `BrowserService.events` (a `deque(maxlen=400)`) currently keeps captions for
  `/api/events`. For the Kandha session it gets the same 300 s age limit.
- `/api/kandha/session/save` and `/api/export` are refused while the Kandha page owns the
  session.
- Audial's own windows are not changed (Q12).

**What off the record does.** It empties the memory, any recap, and the Python event buffer
for the session.

### 5.2 Off the record

Decision [0019](decisions/0019-off-the-record-detection.md).

**Detection** runs on the **caption text** that is already produced, so no new audio path is
needed:
- a fuzzy match for "Kandha, off the record" and "Kandha, back on";
- the wake word is in Whisper's `initial_prompt`, and the matcher accepts known
  mis-hearings (`kanda`, `kandaa`, `condor`, `ganda`…), taken from the measurement below;
- Hindi equivalents are **Q13**.

**Latency** is one caption packet (≈ 2–3 s). The 5-minute wipe makes that harmless, because
the words spoken just before the phrase are wiped too.

**Effects** (all in the summary):
- wipe the memory;
- block bookmarks until "back on" or the end of the session;
- captions continue;
- MODE write sets the light's colour;
- the `off_record` pattern plays.

**Measurement.** Run the phrase at 5 SNRs (clean, 20, 10, 5, 0 dB) × several voices × the
real Whisper model, and report detection and false-trigger rates and every miss.

- **Synthetic first.** TTS voices plus noise, labelled simulated.
- **Consented recordings next.** Indian English and Hindi speakers. The recordings are never
  committed; only the counts are.

### 5.3 Saved notes

Decision [0020](decisions/0020-notes-encrypted-at-rest.md).

- Each bookmark becomes one record: `{saved_at (minute precision), mode, text_redacted}`.
  There is no voice, zone, tone or speaker label (D8).
- The records are stored as `notes.jsonl.enc`, with AES-256-GCM per record (`cryptography`,
  which must be added to the requirements).
- The data key is held by the OS keystore: Windows DPAPI, the macOS Keychain, or Linux Secret
  Service via `keyring`. On Android it is the Android Keystore.
- If no keystore is available, bookmarks are **refused** with a message. They are never
  stored in plain text.
- Notes can be viewed and deleted in Review. "Delete all" removes the file and the key.

**Practicum.** The bookmark path is disabled (the Q pad shows "not saved in Practicum").
Nothing else in Kandha writes files: settings and room slot orders contain no words. The test
in §7 proves it.

## 6. Redaction (shared spec)

Decision [0021](decisions/0021-redaction-spec.md).

**One specification:**
- `spec/redaction/README.md` for the rules;
- `spec/redaction/fixtures.jsonl` for the cases;
- `spec/redaction/data/` for shared word lists.

**Two implementations:** `app/kandha/redact.py`, and Kotlin `redact/` in the Android app.
Both run the same fixtures in CI.

**Deterministic first.** A rules + checksum + gazetteer pipeline that both languages can
implement identically. There is no ML NER model in the first version, because the same model
would have to run identically in Python and Kotlin, and offline. An ONNX NER model is the
planned upgrade if the measured name recall is too low.

| Category | Rule | Placeholder |
|---|---|---|
| Phone | `(\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}`, plus landlines with STD code | `[number]` |
| Aadhaar | 12 digits (spaced 4-4-4 allowed), first digit 2–9, Verhoeff valid. A failed checksum is still redacted as `[number]`, because over-redacting is the cheaper error | `[number]` |
| PAN | `[A-Z]{5}\d{4}[A-Z]`, case-insensitive after ASR | `[id]` |
| Card | 13–19 digits, Luhn valid | `[number]` |
| Bank account / IFSC | 9–18 digits near "account"/"a/c"; `[A-Z]{4}0[A-Z0-9]{6}` | `[number]` / `[id]` |
| PIN code | 6 digits, first 1–9, near an address word or a city name | `[number]` |
| Date of birth | Any date within 6 words of "born", "DOB", "birthday", "age"; any spoken date with a year 1940–2015 | `[date]` |
| Email | Standard pattern, plus spoken "at … dot com" | `[email]` |
| Address | House/flat number + street words (road, marg, nagar, lane, sector…) | `[address]` |
| **Spelled-out numbers** | Runs of ≥ 4 digit words ("nine eight two…") are normalised first, because ASR often writes numbers as words | as above |
| Names | (a) the voice names Vikram typed in the app (always); (b) an Indian + international given/family name gazetteer with a licence recorded in `LICENSE_NOTICES.md`; (c) honorific + capitalised word (Dr, Mr, Ms, Prof, -ji, Shri, Smt); (d) "my name is / I'm / call me X". The **allow-list** (course terms, places of study) wins over the gazetteer, never over (a) | `[name]` |
| Speaker labels | Never written: the bookmark is built from text only. Lines like `Voice 2:` or `Priya:` are stripped as a second line of defence | — |
| Tone data | Never written; the record has no tone field | — |
| Clinical details | **Q14**. Proposed: redact a clinical term only when it is tied to a person ("my client/she/he/my brother … has/was diagnosed with/takes …"). Course terms on their own (anhedonia, DSM-5) are kept, since they are the lesson | `[clinical detail]` |

**Reporting.**
- Precision and recall per category on the fixture suite.
- A separate **held-out** set that is never used for tuning: synthetic sentences plus
  ASR-style noise. A consented real set is used if one becomes available; its texts are never
  committed.
- Every known miss is listed in VALIDATION.

**Tuning rule.** Recall ≥ 0.98 on numbers and IDs, and ≥ 0.95 on names. Precision is
reported, and over-redaction is accepted.

## 7. Privacy guarantees and how tests prove them

| Guarantee | Test |
|---|---|
| No audio and no unredacted text on disk, in logs or on the network | A pytest fixture patches `open`, `Path.write_*`, `os.replace`, `socket.connect` and the logging handlers. It records everything and fails on any write outside the notes file and settings. It also fails on any non-loopback connect. A Playwright run of the Kandha page in Chromium does the same with request interception and a `localStorage`/IndexedDB check. Canary strings planted in the captions must never appear in any recorded write |
| Memory and recap empty 300 s after speech, and at once after off the record | Fake clock: lines at t, read at t + 299 (present) and t + 301 (gone). Off the record at any time → zero lines, zero recap |
| Practicum leaves no file behind | Run a scripted practicum, then diff the `<data>/kandha` tree before and after. Only `settings.json` may change, and not its content apart from `mode` |
| Notes encrypted at rest | Bytes on disk contain none of the canaries. AES-GCM tags verify. With the key removed, nothing can be read |
| BLE carries only taps, pads, battery/status, config, direction | (a) Mock bridge: every write and notify is checked against a schema per characteristic, by length and layout. (b) Real hardware, Slice 6: nRF Sniffer capture of a session, parsed and checked the same way |

## 8. Part C: the phone as host (Slice 5)

Decisions [0022](decisions/0022-android-host.md),
[0023](decisions/0023-phone-asr-and-mics.md),
[0024](decisions/0024-one-host-at-a-time.md) and
[0025](decisions/0025-recap.md).

### 8.1 Shape

- **Kotlin app**:
  - BLE central (protocol v1 + v2);
  - scheduler, seat map, redaction and notes, all ported to Kotlin;
  - Android Keystore;
  - a foreground service, so it keeps listening with the screen off.
- **UI and voice engine.** The Kandha page runs in a **WebView** with `engine.js` and
  `kandha-intents.js` **unchanged**. The JS bridge replaces the loopback HTTP API, so the
  voice engine is not reimplemented. WebView AudioWorklet support on the target devices is a
  Slice 5 check.
- **One scheduler** (decision 0002). The Kotlin scheduler and seat map must reproduce
  **golden vectors** exported from `app/kandha/scheduler.py` and `seatmap.py`: sequences of
  intents and observations with times, and the exact HAPTIC bytes and drop reasons. Python CI
  regenerates the vectors and fails if they change without a version bump. Kotlin CI must pass
  them.

### 8.2 Captions on the phone

**ASR.** whisper.cpp with a multilingual Whisper model (base or small, picked by measurement)
and the same psychology vocabulary as `initial_prompt`. Android's
`createOnDeviceSpeechRecognizer` (API 31+) is the fallback for phones too slow for
whisper.cpp. Both run on the device only.

**Audio** is kept in memory in an `AudioRecord` ring buffer. It is never written to disk and
never uses MediaRecorder.

**Microphones.** All three of the prompt's options are compared on consented Indian English
and Hindi speech, by WER and by end-to-end caption delay:
1. the phone's own microphone;
2. a Bluetooth headset or lapel mic on the phone (HFP/mSBC, 16 kHz mono);
3. a wired or USB-C wireless lapel mic.

**No audio on the stole link.** Decision 0023 rejects streaming pod audio over BLE. It would
break "Bluetooth carries no audio", it needs a bonded encrypted link, and BLE throughput at
16 kHz × 16 bit is marginal.

**Q15.** Option 2 means a *Bluetooth* microphone carries audio to the phone. The summary's
sentence "Bluetooth carries no audio or words" refers to the stole, but a reader may take it
literally.

### 8.3 "Summarise, then delete"

**Recap.** "What did I miss?" on the phone gives a **recap** of the 5-minute memory:
- **extractive**: the top sentences by TF-IDF and position, ≤ 5 sentences;
- **redacted** with the shared spec (no speaker labels);
- held only in memory and wiped with that memory;
- never saved.

A small on-device LLM is the planned upgrade if a phone can run one acceptably. That will be
measured, not assumed.

Bookmarks, Practicum and off the record work exactly as on the laptop.

### 8.4 One host at a time

- The stole already accepts one central at a time: it stops advertising while connected
  (`kandha.ino` `onDisconnect` restarts it).
- **Hand-off**:
  1. The active host's "Hand over" button writes MODE bit1 "release". The stole plays
     `connected` and disconnects.
  2. The stole advertises with a 10 s **hand-off window**. During it, the releasing host does
     not reconnect.
  3. The other host connects as usual.
- If a host simply vanishes (laptop lid closed), normal reconnect rules apply and whichever
  host reconnects first wins. A "preferred host" setting is **Q16**.

### 8.5 Measurement on the phone

- Tap latency (engine decision → motor start) on a real phone and stole. Budget ≤ 300 ms
  worst case.
- Battery drain per hour on the phone.
- WER per microphone option.
- Recap usefulness, a later user-test item.

## 9. Open questions

The prompt says these must be asked, not guessed. Q1–Q2 are about the hardware, Q3–Q9 about
behaviour, Q10 about the protocol, Q11–Q14 about privacy, and Q15–Q17 about the phone.

1. **Q1. Shared I2S clocks.** Are you happy to commit to the shared-clock design and prove it
   on the bench before buying the pod board? The fallback costs GPIO 16 plus charge sense.
2. **Q2. 2N2222A base resistor.** Keep 330 Ω (≈ 7.8 mA base) or drop to 220 Ω (≈ 12 mA) for a
   harder saturation on the 150 mA shoulder zones? That is within the S3's 40 mA per-pin
   limit. Decide after the Slice 2 measurement.
3. **Q3. New voice with no clear direction.** No tap (Kandha "never guesses"), or the old
   `seat_unmapped` single tap on F? F is now a real seat, so that tap would mean "someone in
   front".
4. **Q4.** Should a pad pressed while nobody is speaking give any feedback?
5. **Q5. Gestures.** Double and long press have no meaning in the summary. Today a long press
   on Q toggles DND. Keep it, or remove it?
6. **Q6.** How much does one bookmark keep? Proposed: the last 30 s.
7. **Q7** (the summary's own open item). Does saving a bookmark give a confirming tap?
8. **Q8.** Does "Kandha, back on" play a pattern? The summary only says bookmarks resume.
9. **Q9.** In Do not disturb ("no taps"), are low battery and off the record also silent?
10. **Q10.** Can DIRECTION carry a heading field (motion data, not audio or words), or must
    rotation work another way?
11. **Q11. Review screen.** The summary says named emotion estimates appear "only in Review",
    but also that captions are wiped after 5 minutes, bookmarks carry no tone data, and there
    is no profile of anyone's emotions. What does Review show after a session? Proposed:
    bookmarks only, with tone estimates live-only and off by default. The portfolio sentence
    would need to change.
12. **Q12.** The rules apply to the Kandha window. Do Audial's own caption window and its
    transcript save and export also change, or stay as a separate product?
13. **Q13.** A Hindi phrase for off the record and back on?
14. **Q14. Clinical details.** Is "redact only when tied to a person" acceptable, given that
    psychology course terms are the lesson?
15. **Q15.** Bluetooth microphones on the phone versus the sentence "Bluetooth carries no
    audio or words": reword to "the stole's Bluetooth link", or don't support Bluetooth mics?
16. **Q16.** Should there be a preferred host when both the phone and the laptop are around?
17. **Q17. Timing.** Slices 2–3 change behaviour the portfolio describes as *designed*.
    Should anything land before 30 November, or does all v2 work wait until after
    submission? The portfolio already describes the final behaviour, so building it makes the
    claims truer, not less true.

### 9.1 Answers (22 Nov 2026)

| # | Answer | Recorded in |
|---|---|---|
| Q1 | Default: commit to the shared clock, and prove it on the bench before ordering the pod board | 0014 |
| Q2 | Default: keep 330 Ω until the Slice 2 measurement decides | 0013 |
| Q3 | **No tap.** The caption shows **"?"** as its direction arrow until the pod is confident or a pad is pressed | 0015 |
| Q4 | Default: a pad with nobody speaking does nothing | 0015 |
| Q5 | Default: double = tap; long press does nothing (Q's long press no longer toggles DND) | 0015 |
| Q6 | **30 s** per bookmark | §3.2 |
| Q7 | **Yes**: one very light, short tick on B, new id **16 `bookmark_saved`** (30 ms @90), distinct from every other pattern | 0016 |
| Q8 | Default: "back on" plays **15 `back_on`** | 0016 |
| Q9 | Default: Do not disturb means no taps at all; the screen and the light still show state | 0016 |
| Q10 | **Yes**: DIRECTION carries heading. Wording: "angle, confidence, level, heading, timestamp" | 0017 |
| Q11 | **Review shows redacted bookmarks only. Named emotion estimates are removed entirely** | 0018 |
| Q12 | Default: Audial's own windows are unchanged | 0018 |
| Q13 | Default: English phrases only until a Hindi phrase is measured | 0019 |
| Q14 | **Clinical details are redacted only when tied to a person**; course terms stay | 0021 |
| Q15 | **"The stole's Bluetooth link carries no audio or words."** Bluetooth mics on the phone come later, off by default | 0023 |
| Q16 | Default: no preferred host; the first to connect wins | 0024 |
| Q17 | **Before 30 Nov:** Slice 0 and removing transcript saving and every export. **Everything else after**, on a separate branch | this section |

## 10. Slices

| Slice | Contents | Needs hardware? |
|---|---|---|
| 0 | As-built sync, the pin budget. **Done 22 Nov**: compiles for the S3-Zero | No (the docs and the firmware compile) |
| 1 | This document and decisions 0013–0025. **Approved 22 Nov** | No |
| 2 | Part A in the app and firmware, F pad, new patterns; tap distinguishability on the bench stole | The bench stole for the feel tests only |
| 3 | Privacy layer, redaction spec and fixtures, spy tests | No |
| 4 | Mic pod bench board, DIRECTION, automatic seat map from real angles, Phase 2 measurements | Yes |
| 5 | Android host, golden vectors, phone measurements | An Android phone |
| 6 | End to end on real hardware against the summary's gates | Yes |
| 7 | Docs, VALIDATION (measured vs estimated), the list of portfolio sentences to change | No |
