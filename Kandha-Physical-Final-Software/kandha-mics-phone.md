# Prompt: Kandha v2 — stole microphones, a phone host, private summaries

> **How to use this file.** Save it in the Audial-AI repo as
> `docs/prompts/kandha-mics-phone.md`, open Claude Code in the repo root and say:
> *"Read `docs/prompts/kandha-mics-phone.md` and carry it out."*
> It follows the same format as `docs/prompts/sanket-kandha-app.md`.

---

## 0. Your role and how to work

You are the lead engineer for **Kandha v2**. Kandha is a haptic stole for deaf
students (see `docs/kandha/DESIGN.md`). A physical prototype now exists (§2).
v2 adds three things:

1. **Microphones** that send audio to a host over **Bluetooth**.
2. A **phone app** (Android first) that can be the host instead of the laptop.
   It transcribes speech, **auto-redacts sensitive information**, writes a
   **summary**, then **deletes** the raw material (§5).
3. The host (phone **or** laptop) keeps telling the ESP32 **what to fire and when**,
   over the existing Bluetooth protocol.

Work in this order. Do not skip ahead.

1. **Read first.** Read every file in §3. Run the existing tests
   (`npm test`, and `python -m pytest -q` with `QT_QPA_PLATFORM=offscreen`)
   and record the baseline. Follow `CONTRIBUTING.md`.
2. **Design document before code.** Write `docs/kandha/V2_DESIGN.md` covering
   §§4–8. Add a decision record in `docs/kandha/decisions/` (numbered from
   0013) for every real choice. List anything ambiguous, or anything that
   contradicts the code, as an **open question**. Then **stop and ask for
   approval** before writing implementation code.
3. **Build in vertical slices** (§9). Each slice ends with passing tests and
   no regressions in the baseline.
4. **Verify honestly.** Every number in the docs comes from a test or
   measurement you ran. Keep simulated results (mock BLE, synthetic audio,
   stubbed ASR) clearly separate from results measured on the real stole,
   the real phone, or real speech.

---

## 1. Who it is for and the rule that decides everything

Same user as v1: a deaf student who lip-reads, in lectures, seminars and
clinical role-plays ("practicum"). The v1 rule still decides everything:
**his eyes stay on faces.** The phone is for glancing at captions and for
review afterwards. It is not something he watches during class. Anything
that needs no looking goes to the stole.

v2 serves this rule in two ways:

- **Direction.** The stole's own microphones can tell left from right, so new
  speakers get their zones automatically instead of by hand. This plugs into
  `SeatSource` in the seat map (DESIGN.md §8).
- **Phone as host.** A phone in a pocket replaces carrying a laptop.
  Afterwards, the student gets a **private, redacted summary** of what was said.

---

## 2. The hardware as actually built (source of truth)

The prototype differs from DESIGN.md §5. **Slice 0 updates the repo to match
it.**

| Item | As built |
|---|---|
| Board | Waveshare **ESP32-S3-Zero** (ESP32-S3FH4R2, 4 MB flash, 2 MB PSRAM). Onboard WS2812 RGB LED on GPIO 21, so `PIN_STATUS_LED -1` |
| Motor drivers | **2N2222A** NPN (through-hole), not AO3400. Each channel: GPIO → 330 Ω → base, 10 kΩ base→GND, emitter→GND, collector→motor −, 1N5819 across the motor (cathode to +V), 47 µF across +V/GND |
| Motors | 6 × 10 mm coin ERM. L = 2, R = 2, B = 1, F = 1 |
