# Local Windows results — not run

The supplied Dell/RTX 4060 specifications are deployment targets. The laptop has not been inspected from this cloud. No local performance, memory, microphone, webcam or SAPI result is available yet.

Run **Diagnostics → Run local validation** after setup/model installation. Reports appear under `%LOCALAPPDATA%\AccessibilityAI`. To replace these project-root placeholders, run from the project root:

```text
.venv\Scripts\python.exe -m scripts.local_validation --output .
```

The command explicitly opens webcam 0, captures two seconds of microphone audio in memory, requests local TTS and tests installed models on the included public samples. Missing components receive SKIP or FAIL reasons. Actual Windows-generated reports have measured times and hardware data; this placeholder contains none.
