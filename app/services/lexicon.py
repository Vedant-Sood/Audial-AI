import json
from pathlib import Path
import math
import unicodedata
from urllib.parse import urlsplit

ISL_LANGUAGE = "ISL"
MAX_TEXT_CHARACTERS = 20000


class SignLexicon:
    """Licensed local ISL vocabulary, aliases, and an ordered playback plan.

    Dictionaries establish phrase coverage; this class does not infer ISL grammar
    or invent poses for unknown input. Both the legacy lookup API and the ordered
    native playback API share the same validated media and aliases.
    """
    def __init__(self, path):
        self.path = Path(path).resolve()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("language") != ISL_LANGUAGE or not isinstance(data.get("entries"), list):
            raise ValueError("Lexicon must declare Indian Sign Language and its entries.")
        self.entries = []
        for original in data["entries"]:
            entry = dict(original)
            if not entry.get("gloss") or not entry.get("source_url") or not entry.get("license"):
                raise ValueError("Each sign requires a gloss, source URL, and license.")
            if not isinstance(entry["source_url"], str) or not isinstance(entry["license"], str):
                raise ValueError("Sign source URLs and licenses must be text.")
            source = urlsplit(entry["source_url"])
            if source.scheme not in {"http", "https"} or not source.netloc:
                raise ValueError("Sign source URLs must use HTTP or HTTPS.")
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
        self._index()

    def _index(self):
        self._tokens = {}
        for entry in self.entries:
            aliases = entry.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(a, str) or not self.tokens(a) for a in aliases):
                raise ValueError("Sign aliases must be nonempty text.")
            for alias in [entry["gloss"], *aliases]:
                key = tuple(self.tokens(alias))
                if key in self._tokens and self._tokens[key]["gloss"] != entry["gloss"]:
                    raise ValueError("An alias cannot name two different signs.")
                self._tokens[key] = entry

    @classmethod
    def combine(cls, bundled, extra):
        """Extend the bundled vocabulary; a selected gloss replaces that gloss.

        Both inputs must already be validated lexicons. Alias collisions across
        different signs are rejected rather than changing a sign's meaning.
        """
        merged = cls.__new__(cls)
        merged.path = extra.path
        entries = {tuple(cls.tokens(e["gloss"])): e for e in bundled.entries}
        for entry in extra.entries:
            key = tuple(cls.tokens(entry["gloss"]))
            selected = entry.copy()
            if key in entries:
                selected["aliases"] = list(dict.fromkeys([*entries[key].get("aliases", []), *entry.get("aliases", [])]))
            entries[key] = selected
        merged.entries = list(entries.values())
        merged._index()
        return merged

    @staticmethod
    def word_spans(text):
        """Unicode words and original offsets, including Indic combining marks."""
        spans, start = [], None
        for index, char in enumerate(text):
            word_char = unicodedata.category(char)[0] in {"L", "N", "M"}
            apostrophe = (char in "'’" and start is not None and index + 1 < len(text)
                          and unicodedata.category(text[index + 1])[0] in {"L", "N", "M"})
            if word_char or apostrophe:
                if start is None:
                    start = index
            elif start is not None:
                spans.append((start, index, unicodedata.normalize("NFC", text[start:index]).casefold().replace("’", "'")))
                start = None
        if start is not None:
            spans.append((start, len(text), unicodedata.normalize("NFC", text[start:]).casefold().replace("’", "'")))
        return spans

    @classmethod
    def tokens(cls, text):
        return [word for _, _, word in cls.word_spans(text)]

    def plan(self, text):
        """Keep known signs and explicitly labelled text fallbacks in input order.

        A fallback is readable original text, never an invented sign. Original
        spans (including punctuation and Indic combining marks) are retained.
        """
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARACTERS:
            raise ValueError("Use text up to 20,000 characters.")
        spans = self.word_spans(text)
        steps, index, cursor = [], 0, 0
        longest = max((len(key) for key in self._tokens), default=1)
        while index < len(spans):
            match = None
            for count in range(min(longest, len(spans) - index), 0, -1):
                # A phrase may span whitespace or hyphens, never another symbol
                # or a sentence boundary. Words next to punctuation still match.
                if any(not all(c.isspace() or c in "-_" for c in text[spans[j][1]:spans[j+1][0]])
                       for j in range(index, index + count - 1)):
                    continue
                entry = self._tokens.get(tuple(s[2] for s in spans[index:index + count]))
                if entry:
                    match = (count, entry)
                    break
            if match:
                count, entry = match
                start, end = spans[index][0], spans[index + count - 1][1]
                unknown = text[cursor:start].strip()
                if unknown:
                    steps.append({"kind": "text", "text": unknown})
                while end < len(text) and unicodedata.category(text[end])[0] == "P":
                    end += 1
                steps.append({"kind": "sign", "text": text[start:end], "entry": entry.copy()})
                cursor = end
                index += count
            else:
                index += 1
        unknown = text[cursor:].strip()
        if unknown:
            steps.append({"kind": "text", "text": unknown})
        return steps

    def lookup(self, text):
        known, missing = [], []
        for step in self.plan(text):
            if step["kind"] == "sign":
                known.append(step["entry"])
            else:
                missing.extend(self.tokens(step["text"]))
        return known, missing
