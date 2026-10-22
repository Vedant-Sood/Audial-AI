"""Sanket voice view: validated voice/cue/tone events from the in-browser voice engine.

Browser capture (companion page or extension offscreen document) runs Sanket's voice engine on
the same PCM it uploads, and reports compact events in audio time (seconds since the first
captured sample, the clock captions use). This module validates them, keeps them with the
session, and answers "which voice was speaking during this caption?" for exports.

Voices are session-only colour slots ("Voice 1", "Voice 2"...), not identities. Tone fields are
estimates of how a voice sounded compared with that person's usual voice, never a reading of
feelings; categories are named only when Sanket was at least 80% sure.
"""
import math

from app.utils.palette import DEFAULT_EMOTION_COLORS

KINDS = {"voice", "cue", "tone", "queue"}
CUES = {"drop", "rise", "hesitation", "silence"}
RELATIVE = {"learning", "usual", "intense", "softer"}
LABELS = set(DEFAULT_EMOTION_COLORS)  # six acted categories plus "uncertain"
MAX_BATCH = 200
MAX_EVENTS = 20000
MAX_SECONDS = 24 * 3600
UNATTRIBUTED = {"Unknown", "Unattributed"}

CUE_TEXT = {"drop": "Voice softened", "rise": "Voice rose", "hesitation": "Hesitation", "silence": "Long silence"}
RELATIVE_TEXT = {"intense": "more intense than usual", "softer": "softer, sad-sounding", "usual": "usual for them"}


def _time(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_SECONDS:
        raise ValueError(f"Voice event {name} must be a time in seconds.")
    return round(float(value), 3)


def _voice(value, allow_none=False):
    if value is None and allow_none:
        return None
    if type(value) is not int or not 1 <= value <= 64:
        raise ValueError("Voice events need a voice number from 1 to 64.")
    return value


def clean_events(events):
    """Validate one batch. Unknown fields are dropped; anything malformed rejects the batch."""
    if not isinstance(events, list) or len(events) > MAX_BATCH:
        raise ValueError(f"Send a list of at most {MAX_BATCH} voice events.")
    clean = []
    for event in events:
        if not isinstance(event, dict) or event.get("kind") not in KINDS:
            raise ValueError("Voice events must be voice, cue, tone or queue objects.")
        kind = event["kind"]
        if kind == "voice":
            clean.append({"kind": kind, "t": _time(event.get("t"), "t"), "id": _voice(event.get("id")),
                          "new": bool(event.get("new"))})
        elif kind == "cue":
            if event.get("cue") not in CUES:
                raise ValueError("Unknown tone cue.")
            clean.append({"kind": kind, "t": _time(event.get("t"), "t"), "cue": event["cue"],
                          "voice": _voice(event.get("voice"), allow_none=True)})
        elif kind == "tone":
            t0, t1 = _time(event.get("t0"), "t0"), _time(event.get("t1"), "t1")
            if t1 < t0 or event.get("relative") not in RELATIVE or event.get("label") not in LABELS:
                raise ValueError("Tone events need an ordered span, a relative tone and a known label.")
            confidence = event.get("confidence")
            if event["label"] == "uncertain":
                confidence = None
            elif type(confidence) not in (int, float) or not 0.8 <= confidence <= 1:
                raise ValueError("Named tone estimates need a confidence of at least 0.8.")
            clean.append({"kind": kind, "t0": t0, "t1": t1, "voice": _voice(event.get("voice")),
                          "relative": event["relative"], "label": event["label"],
                          "confidence": None if confidence is None else round(float(confidence), 3)})
        else:
            clean.append({"kind": kind, "t": _time(event.get("t"), "t"), "on": bool(event.get("on"))})
    return clean


class VoiceTrack:
    """Read-only view over stored events for attributing captions."""

    def __init__(self, events):
        self.changes = sorted((e["t"], e["id"]) for e in events if e["kind"] == "voice")
        self.tones = [e for e in events if e["kind"] == "tone"]
        self.cues = [e for e in events if e["kind"] == "cue"]

    def __bool__(self):
        return bool(self.changes)

    def voice_for(self, start, end):
        """The voice heard longest during [start, end], or None."""
        if not self.changes:
            return None
        end = max(end, start + 0.01)
        spans = {}
        for index, (t, voice) in enumerate(self.changes):
            t_next = self.changes[index + 1][0] if index + 1 < len(self.changes) else math.inf
            overlap = min(end, t_next) - max(start, t)
            if overlap > 0:
                spans[voice] = spans.get(voice, 0) + overlap
        return max(spans, key=spans.get) if spans else None

    def tone_for(self, start, end, voice):
        """The most informative tone estimate for this voice overlapping the caption."""
        rank = {"learning": 0, "usual": 1, "softer": 2, "intense": 2}
        best = None
        for tone in self.tones:
            if tone["voice"] != voice or tone["t1"] < start - 0.3 or tone["t0"] > end + 0.3:
                continue
            score = (tone["label"] != "uncertain", rank[tone["relative"]])
            if best is None or score > best[0]:
                best = (score, tone)
        return best[1] if best else None

    def annotate(self, caption):
        voice = self.voice_for(caption.start, caption.end)
        if voice is None:
            return None
        result = {"voice": f"Voice {voice}"}
        tone = self.tone_for(caption.start, caption.end, voice)
        if tone and tone["relative"] != "learning":
            result["tone"] = {k: tone[k] for k in ("relative", "label", "confidence")}
        return result


def describe_tone(tone):
    if not tone or tone.get("relative") not in RELATIVE_TEXT:
        return ""
    text = "tone: " + RELATIVE_TEXT[tone["relative"]]
    if tone.get("label") not in (None, "uncertain"):
        text += f"; estimate {tone['label']} {round(tone['confidence'] * 100)}%"
    return text
