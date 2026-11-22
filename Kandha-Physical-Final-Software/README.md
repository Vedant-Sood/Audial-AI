# Kandha: physical and final software (v2)

Kandha v2 covers four things:
- the bench stole as actually built;
- making the app and firmware match the Final Project Summary;
- the mic pod;
- a phone host.

| File | What it is |
|---|---|
| [`docs/prompts/kandha-v2.md`](../docs/prompts/kandha-v2.md) | The v2 build prompt (current) |
| [`docs/kandha/FINAL_SUMMARY.pdf`](../docs/kandha/FINAL_SUMMARY.pdf) | Final Project Summary, 19 Nov 2026: the source of truth for behaviour and privacy |
| [`docs/kandha/V2_DESIGN.md`](../docs/kandha/V2_DESIGN.md) | The v2 design, **approved 22 Nov 2026**; answers in §9.1 |
| [`docs/kandha/decisions/`](../docs/kandha/decisions/) | Decisions 0013–0025 (approved) |
| [`PORTFOLIO_CHANGES.md`](PORTFOLIO_CHANGES.md) | **Portfolio sentences to change before 30 November** |
| [`BASELINE.md`](BASELINE.md) | Test baseline before any v2 code: npm 46/46, pytest 217 passed + 1 skipped |
| [`kandha-mics-phone.md`](kandha-mics-phone.md) | An earlier, incomplete draft of the prompt. Superseded by `kandha-v2.md` |

## Status

Done before the 30 November deadline:
- **Slice 0.** The repo matches the bench stole (ESP32-S3-Zero, 2N2222A, the new pins), and
  the firmware compiles for it.
- **No transcripts.** Kandha never saves or exports a transcript. A filesystem and network spy
  test proves nothing is written.

Everything else in V2_DESIGN (Part A, the privacy layer, the mic pod, the phone) waits until
after the deadline, on a separate branch.
