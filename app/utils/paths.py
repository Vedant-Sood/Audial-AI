import os
import sys
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    fd = os.open(str(tmp), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(path)
