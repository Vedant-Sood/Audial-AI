"""Copy the Sanket voice-cue app into browser/sanket/ as CSP-safe static files.

Sanket (built for Hackcessible India 2026, Vikram's challenge) is developed as a
single-file app. The companion's Content-Security-Policy forbids inline scripts, so this script
copies its sources as separate same-origin files and writes an index.html that loads them.

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
           "band.js", "local-captions.js", "demo.js", "app.js"]

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
    for name in SCRIPTS + ["styles.css"]:
        shutil.copyfile(source / name, TARGET / Path(name).name)
    body = (source / "body.html").read_text(encoding="utf-8")
    # the dialog width was the only inline style; it moves to the stylesheet
    body = body.replace(' style="width:min(980px, calc(100vw - 32px))"', ' class="dlg--wide"')
    if re.search(r"<script(?![^>]*\bsrc=)", body, re.I):
        raise ValueError("body.html must not contain inline scripts.")
    tags = "\n".join(f'<script src="{Path(name).name}"></script>' for name in SCRIPTS)
    (TARGET / "index.html").write_text(HEAD + body + "\n" + tags + "\n</body>\n</html>\n", encoding="utf-8")
    (TARGET / "worklet.js").write_text(worklet_source((source / "app.js").read_text(encoding="utf-8")), encoding="utf-8")
    css = TARGET / "styles.css"
    text = css.read_text(encoding="utf-8")
    if ".dlg--wide" not in text:
        css.write_text(text + "\n#reviewDlg.dlg--wide { width: min(980px, calc(100vw - 32px)); }\n", encoding="utf-8")
    return sorted(p.name for p in TARGET.iterdir())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="Sanket src/ directory")
    print("\n".join(sync(parser.parse_args().source)))
