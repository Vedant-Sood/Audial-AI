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

See `docs/architecture.md` for the code map and `docs/indian_voice_training.md` for
model training, provenance and activation. Every distributed dataset/model or
native dependency must retain its notices. Do not put credential values or user
recordings into release scripts, documentation or archives.
