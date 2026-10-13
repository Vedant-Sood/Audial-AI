"""One local Indian Sign Language vocabulary for every input and display.

This service selects verified local media and plans their playback. It is a
dictionary adapter, not a sentence translation model. Input language never
changes the output sign language. A selected pack extends the bundled signs.
"""
import json
from functools import lru_cache
from pathlib import Path
import threading

import numpy as np

from app.services.lexicon import ISL_LANGUAGE, MAX_TEXT_CHARACTERS, SignLexicon
from app.utils.paths import atomic_json, data_root, project_root


@lru_cache(maxsize=64)
def _pose_frames(path, modified, size):
    if size > 20 * 1024 * 1024:
        raise ValueError("A sign pose file must be smaller than 20 MB.")
    frames = np.load(path, allow_pickle=False)
    if (frames.ndim != 3 or frames.shape[1:] != (49, 4) or not 1 <= len(frames) <= 1500
            or not np.issubdtype(frames.dtype, np.number) or not np.isfinite(frames).all()):
        raise ValueError("Sign replay needs finite raw camera coordinates [frames,49,4].")
    frames = frames.astype(np.float32, copy=True)
    frames[:, :, :2] = np.clip(frames[:, :, :2], 0, 1)
    frames.setflags(write=False)
    return frames


def load_pose_frames(entry):
    """Validate once per file revision; both displays use identical coordinates."""
    path = entry["path"]
    stat = path.stat()
    frames = _pose_frames(str(path), stat.st_mtime_ns, stat.st_size)
    if (len(frames) - 1) * 1000 / entry.get("fps", 15) > 60000:
        raise ValueError("One sign pose sequence must fit within one minute.")
    return frames


class ISLVocabulary:
    language = ISL_LANGUAGE
    max_characters = MAX_TEXT_CHARACTERS

    def __init__(self, bundled=None, selection=None):
        self.bundled = Path(bundled or project_root() / "assets/isl_lexicon/lexicon.json")
        self.selection = Path(selection or data_root() / "lexicon_selection.json")
        self.warning = ""
        self._signature = None
        self._lexicon = None
        self._lock = threading.RLock()

    def load(self):
        """Refresh selection changes from either UI without re-parsing each caption."""
        with self._lock:
            selected, warning = None, ""
            try:
                if self.selection.exists():
                    data = json.loads(self.selection.read_text(encoding="utf-8"))
                    selected = Path(data["path"]).expanduser().resolve()
                elif (data_root() / "lexicon/lexicon.json").exists():
                    selected = data_root() / "lexicon/lexicon.json"
                signature = (self.bundled.stat().st_mtime_ns, str(selected),
                             selected.stat().st_mtime_ns if selected else None)
            except (OSError, ValueError, TypeError, KeyError) as error:
                warning = "The added ISL vocabulary is unavailable; using bundled signs. " + str(error)
                selected = None
                signature = (self.bundled.stat().st_mtime_ns, None, warning)
            if signature != self._signature:
                lexicon = SignLexicon(self.bundled)
                if selected and selected.resolve() != self.bundled.resolve():
                    try:
                        lexicon = SignLexicon.combine(lexicon, SignLexicon(selected))
                    except (OSError, ValueError, TypeError, KeyError) as error:
                        warning = "The added ISL vocabulary is invalid; using bundled signs. " + str(error)
                self._lexicon = lexicon
                self._signature = signature
                self.warning = warning
            return self._lexicon

    def select(self, path):
        """Validate before persisting; never replace a working pack with a bad one."""
        with self._lock:
            path = Path(path).resolve()
            SignLexicon.combine(SignLexicon(self.bundled), SignLexicon(path))
            atomic_json(self.selection, {"language": ISL_LANGUAGE, "path": str(path)})
            self._signature = None
            return self.load()

    def use_bundled(self):
        return self.select(self.bundled)

    def plan(self, text):
        return self.load().plan(text)

    def summary(self):
        lexicon = self.load()
        return {"language": ISL_LANGUAGE, "entries": len(lexicon.entries),
                "glosses": [e["gloss"] for e in lexicon.entries],
                "max_characters": MAX_TEXT_CHARACTERS, "warning": self.warning,
                "translation_mode": "local vocabulary with text fallback"}
