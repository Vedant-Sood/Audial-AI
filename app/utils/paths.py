import os
import sys
import tempfile
from pathlib import Path


def project_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def data_root():
    base = os.environ.get("ACCESSIBILITY_AI_HOME")
    if base:
        root = Path(base)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AccessibilityAI"
    else:
        root = Path.home() / ".local" / "share" / "AccessibilityAI"
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_json(path, value):
    import json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Desktop workers and the browser companion can save the same document.
    # Each writer needs its own staging file in the destination filesystem.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
