# Kandha v2: test baseline (step 1)

Recorded 2026-11-21 on branch `Kandha-Physical-Final-Software`, before any v2 code was
written. The branch starts from `main` at `2a32abc`.

Environment: a Linux x86_64 cloud container with Node 22.23.5 and Python 3.12.3 (a venv set
up as `CONTRIBUTING.md` describes: CPU torch 2.8.0, then `requirements.txt` and
`requirements-dev.txt`). Qt ran with `QT_QPA_PLATFORM=offscreen`.

| Suite | Command | Result |
|---|---|---|
| Node | `npm test` | **46 passed**, 0 failed |
| Python | `QT_QPA_PLATFORM=offscreen python -m pytest -q` | **217 passed, 1 skipped**, 0 failed |

The Final Project Summary quotes 206 Python and 38 JavaScript tests. Those are the counts
`docs/kandha/VALIDATION.md` recorded on 2026-10-22; both suites have grown since then.

**Setup notes for this container.** The container's default Python is 3.13, which the project
does not support, so a 3.12 venv was used. The Qt and audio tests also needed these system
packages: `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libnss3 libxcomposite1
libxdamage1 libxrandr2 libxtst6 libasound2t64 libportaudio2`. Before `libportaudio2` was
installed, one test (`test_microphone_permission_failure_releases_stream_and_reaches_the_interface`)
failed because the PortAudio library was missing, not because of a code fault.
