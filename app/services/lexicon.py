import json
from pathlib import Path
import re
import math
import unicodedata


class SignLexicon:
    """Licensed local ISL vocabulary, aliases, and an ordered playback plan.

    Dictionaries establish phrase coverage; this class does not infer ISL grammar
    or invent poses for unknown input. Both the legacy lookup API and the ordered
    native playback API share the same validated media and aliases.
    """
    def __init__(self, path):
        self.path = Path(path).resolve()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("language") != "ISL" or not isinstance(data.get("entries"), list):
            raise ValueError("Lexicon must declare Indian Sign Language and its entries.")
        self.entries = []
        for original in data["entries"]:
            entry = dict(original)
            if not entry.get("gloss") or not entry.get("source_url") or not entry.get("license"):
                raise ValueError("Each sign requires a gloss, source URL, and license.")
            if not isinstance(entry["gloss"], str) or not self.tokens(entry["gloss"]):
                raise ValueError("Each sign needs a readable gloss.")
            fps = entry.get("fps", 15)
            if not isinstance(fps, (int, float)) or not math.isfinite(fps) or not .5 <= fps <= 120:
                raise ValueError("Sign playback rate must be between 0.5 and 120 fps.")
            media = (self.path.parent / entry["path"]).resolve()
            if not media.is_relative_to(self.path.parent) or not media.is_file():
                raise ValueError("Sign media must exist inside the lexicon folder.")
            if media.suffix.lower() not in {".npy", ".mp4", ".mov", ".webm"}:
                raise ValueError("Unsupported sign media format.")
            entry["path"] = media
            self.entries.append(entry)
        self._tokens = {tuple(self.tokens(entry["gloss"])): entry for entry in self.entries}
        for entry in self.entries:
            aliases = entry.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(a, str) or not self.tokens(a) for a in aliases):
                raise ValueError("Sign aliases must be nonempty text.")
            for alias in aliases:
                key = tuple(self.tokens(alias))
                if key in self._tokens and self._tokens[key]["gloss"] != entry["gloss"]:
                    raise ValueError("An alias cannot name two different signs.")
                self._tokens[key] = entry

    @staticmethod
    def tokens(text):
        # Keep combining marks inside Indic words; Python \w omits those marks.
        words, current = [], []
        for c in unicodedata.normalize("NFC", text).casefold():
            if unicodedata.category(c)[0] in {"L", "N", "M"} or c in "'’":
                current.append(c)
            elif current:
                words.append("".join(current)); current = []
        if current:
            words.append("".join(current))
        return words

    def plan(self, text):
        """Keep known signs and explicitly labelled text fallbacks in input order.

        A fallback is readable original text, never an invented sign. Original
        spans (including punctuation and Indic combining marks) are retained.
        """
        if not isinstance(text, str) or len(text) > 20000:
            raise ValueError("Use text up to 20,000 characters.")
        spans = list(re.finditer(r"\S+", text))
        steps, index = [], 0
        longest = max((len(key) for key in self._tokens), default=1)
        while index < len(spans):
            match = None
            for count in range(min(longest, len(spans) - index), 0, -1):
                if any(not self.tokens(span.group()) for span in spans[index:index + count]):
                    continue
                original = text[spans[index].start():spans[index + count - 1].end()]
                entry = self._tokens.get(tuple(self.tokens(original)))
                if entry:
                    match = (count, original, entry)
                    break
            if match:
                count, original, entry = match
                steps.append({"kind": "sign", "text": original, "entry": entry.copy()})
                index += count
            else:
                original = spans[index].group()
                if steps and steps[-1]["kind"] == "text":
                    # Keep whitespace between successive unknown spans too.
                    steps[-1]["text"] += text[spans[index-1].end():spans[index].end()]
                else:
                    steps.append({"kind": "text", "text": original})
                index += 1
        return steps

    def lookup(self, text):
        tokens = self.tokens(text)
        known, missing, index = [], [], 0
        longest = max((len(key) for key in self._tokens), default=0)
        while index < len(tokens):
            for count in range(min(longest, len(tokens) - index), 0, -1):
                entry = self._tokens.get(tuple(tokens[index:index + count]))
                if entry:
                    known.append(entry.copy())
                    index += count
                    break
            else:
                missing.append(tokens[index])
                index += 1
        return known, missing
