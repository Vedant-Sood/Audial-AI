"""Copy a Sanket engine source tree into browser/sanket/ as CSP-safe static files.

Historical: Sanket 1 was developed as a single-file app and synced here. Kandha now lives in
browser/kandha/ (the app) and browser/sanket/ keeps only the shared engine, tone, caption,
recogniser, translator and local-caption libraries. This script still copies those library files
(it no longer writes an index.html or a band link), for anyone retraining the engine upstream.

    python scripts/sync_sanket.py --source path/to/sanket/src

The trained tone model is kept with the other models (models/sanket/tone_model.json); copy a
retrained model there and update models/sanket/provenance.json (sha256) yourself.
"""
import argparse
import re
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "browser" / "sanket"
# load order matters: tone.js before engine.js; app.js last
SCRIPTS = ["engine/tone.js", "engine/engine.js", "captions.js", "recognizer.js", "translator.js",
           "local-captions.js"]

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Sanket · Audial-AI</title>
<meta name="description" content="Voice colours, a queue light and tone cues for deaf students, inside Audial-AI.">
<!-- Served by the Audial-AI companion: captions can come from its local Whisper model. -->
<meta name="sanket-host" content="accessibilityai">
<meta name="sanket-tone-model" content="tone-model.json">
<meta name="sanket-worklet" content="worklet.js">
<link rel="stylesheet" href="styles.css">
</head>
<body>
"""


def worklet_source(app_js):
    match = re.search(r"const WORKLET = `(.*?)`;", app_js, re.S)
    if not match:
        raise ValueError("Sanket app.js no longer defines its WORKLET source.")
    return match.group(1).strip() + "\n"


def sync(source):
    source = Path(source).resolve()
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS:
        shutil.copyfile(source / name, TARGET / Path(name).name)
    app_js = source / "app.js"
    if app_js.is_file():
        (TARGET / "worklet.js").write_text(worklet_source(app_js.read_text(encoding="utf-8")), encoding="utf-8")
    return sorted(p.name for p in TARGET.iterdir())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="Sanket src/ directory")
    print("\n".join(sync(parser.parse_args().source)))
