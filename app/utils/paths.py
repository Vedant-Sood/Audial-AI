import os
import sys
import tempfile
import time
from pathlib import Path

# Windows refuses to replace a file while another writer is replacing it (or an antivirus scanner or
# the search indexer has it open): "Access is denied" (WinError 5) or a sharing violation (WinError 32).
# That clears within milliseconds, so publishing is retried a few times. Elsewhere a PermissionError
# is a real one and is raised at once.
REPLACE_RETRY_DELAYS_S = (0.005, 0.01, 0.02, 0.04, 0.08, 0.1, 0.15, 0.2)     # about 0.6 s in all
TRANSIENT_WINERRORS = {5, 32}


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
        _publish(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _publish(tmp, path):
    """Atomically move the staged file over `path`, riding out Windows' brief replace refusals."""
    for delay in REPLACE_RETRY_DELAYS_S:
        try:
            tmp.replace(path)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in TRANSIENT_WINERRORS:
                raise
            time.sleep(delay)
    tmp.replace(path)          # last attempt: its error reaches the caller
