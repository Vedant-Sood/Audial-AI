# Kandha v2 — test baseline (step 1)

Recorded 2026-11-19 on branch `Kandha-Physical-Final-Software` at `2a32abc` (same as `main`),
in a Linux cloud container: Node 22.23.5, Python 3.13.18. The project supports Python
3.11/3.12 (`CONTRIBUTING.md`), and this container does not have the project's Python
dependencies installed (no `scipy`, `torch` or `PySide6`).

| Suite | Command | Result |
|---|---|---|
| Node | `npm test` | **46 / 46 passed**, 0 failed |
| Python, full | `QT_QPA_PLATFORM=offscreen python -m pytest -q` | **Not run to completion.** Stops when collecting `tests/test_asr.py` (`No module named 'scipy'`) |
| Python, Kandha without extra packages | `pytest tests/test_kandha_{bridge,patterns,protocol,scheduler,seatmap,virtual}.py` | **57 / 57 passed** |
| Python, Kandha needing extra packages | `tests/test_kandha_service.py` (needs `scipy`), `tests/test_kandha_window.py` (needs `PySide6`) | **Not run** (collection errors) |

So this is a partial baseline. A full Python baseline needs a Python 3.11/3.12 environment
set up as `CONTRIBUTING.md` describes (CPU torch 2.8.0, then `requirements.txt`).

## Files read for step 1

`CONTRIBUTING.md`, `docs/kandha/DESIGN.md`, `docs/kandha/PROTOCOL.md`,
`firmware/kandha/config.h`, decisions 0003 (motor driver) and 0011 (prototype without hardware).
The prompt's §3 says which files to read, but §3 is missing from the prompt (see `README.md`),
so this list is my own choice.

## What differs between the as-built stole (prompt §2) and the repo

| Item | Repo today | As built |
|---|---|---|
| Board | generic ESP32-S3 DevKit / SuperMini (`config.h`, DESIGN §5.1, §5.3) | Waveshare ESP32-S3-Zero |
| Status LED | `PIN_STATUS_LED 48` | WS2812 on GPIO 21, so `PIN_STATUS_LED -1` |
| Motor driver | AO3400 / IRLML2502 MOSFET, 100 Ω gate, 4 drivers, one per zone (decision 0003) | 2N2222A NPN, 330 Ω base, 10 kΩ base→GND, 1N5819 per motor, 47 µF |
| Motors | 6 × coin ERM, L 2, R 2, B 1, F 1 | same |

Questions to settle before Slice 0 changes these:

1. **How many transistors?** Does the build use one 2N2222A per zone (4) or one per motor (6)?
   "1N5819 across the motor" could mean either.
2. **Can a 2N2222A drive a zone?** A shoulder zone draws ≈ 150 mA (DESIGN §5.2). With
   3.3 V GPIO through 330 Ω, the base current is ≈ 8 mA, which is enough to saturate it at
   that load (forced β ≈ 19). But the transistor drops ≈ 0.2–0.3 V, so the motor gets
   slightly less voltage than with a MOSFET. Measure this on the stole rather than assume it.
3. **Do the pins still fit?** Are GPIO 1–10 still the pad, motor and sense pins on the
   S3-Zero? That board breaks out fewer pins than a DevKit.
