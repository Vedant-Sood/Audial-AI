# Development

Use the existing checkout. Each cloud task is already isolated; do not create a
Git worktree unless explicitly requested. Source code, uploaded research weights,
and runtime state are separate; keep user recordings and caches out of Git.

Python 3.11/3.12 and Node 20+ are supported. On Linux, create a virtual environment,
install CPU `torch==2.8.0` and `torchaudio==2.8.0` from the official CPU wheel index,
then install `requirements.txt`. `requirements-cloud.lock` records the tested
Linux dependency snapshot. Windows uses `setup.bat --cpu` or the portable bundle.
Qt is pinned for portable compatibility.

```text
python -m pytest -q
npm test
python -m app.main --smoke-test
```

Use `QT_QPA_PLATFORM=offscreen` for headless checks. Browser endpoint tests require
local socket access. `npm test` directly registers all Node test cases and retains
the test runner's exit status. New test reports belong in a current-run validation
record; preserve the imported historical model measurements separately.

The Windows workflow runs source tests and startup checks before building with
PyInstaller, then checks the packaged console worker. Tagged builds publish the
native ZIP only after checks pass. Live device capture and target-machine latency
remain separate Windows tests.

Kandha's tap language lives in `browser/sanket/kandha-patterns.json`; after editing it run
`python scripts/generate_kandha_patterns.py` so `firmware/kandha/patterns.h` matches (a test
checks). `python -m app.main --kandha-check` loads the Kandha page headlessly; see
`docs/kandha/VALIDATION.md` for the Chromium end-to-end, tap-budget and accessibility scripts.
`tests/test_kandha_firmware_host.py` builds the firmware with the host C++ compiler (`g++` or
`clang++`; `CXX` overrides) and `tests/test_kandha_page.py` needs Playwright with Chromium
(`KANDHA_CHROMIUM` overrides the path); both skip when those are missing, so install them to
run the whole suite. A firmware change that uses a new Arduino or BLE call needs a matching
stand-in in `tests/firmware_host/`. Keep `requirements-portable.txt`'s `winrt-*` lines in step
with the `bleak` pin in `requirements.txt` (`tests/test_kandha_packaging.py` checks).

See `docs/architecture.md` for the code map and `docs/indian_voice_training.md` for
model training, provenance and activation. Every distributed dataset/model or
native dependency must retain its notices. Do not put credential values or user
recordings into release scripts, documentation or archives.
