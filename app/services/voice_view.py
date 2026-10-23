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
import re

from app.utils.palette import DEFAULT_EMOTION_COLORS

KINDS = {"voice", "cue", "tone", "queue", "haptic", "seat"}
CUES = {"drop", "rise", "hesitation", "silence"}
ZONES = {"L", "R", "B", "F"}
PATTERN_KEY = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
RELATIVE = {"learning", "usual", "intense", "softer"}
LABELS = set(DEFAULT_EMOTION_COLORS)  # six acted categories plus "uncertain"
MAX_BATCH = 200
MAX_EVENTS = 20000
MAX_SECONDS = 24 * 3600
# Voice numbers are session-local and never reused (each New voice takes the next one), so a
# long session can pass any small cap; this bound only keeps them sane integers. Matches
# app/kandha/service.py MAX_VOICE.
MAX_VOICE = 1_000_000
MAX_CAPTION_TEXT = 4000
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
    if type(value) is not int or not 1 <= value <= MAX_VOICE:
        raise ValueError("Voice events need a voice number of 1 or more.")
    return value


def _whisper_link(value):
    """{capture, start, end}: the local Whisper caption a line came from, its times kept exact."""
    if value is None:
        return None
    if (not isinstance(value, dict) or not isinstance(value.get("capture"), str) or not 0 < len(value["capture"]) <= 64
            or any(type(value.get(k)) not in (int, float) or not math.isfinite(value[k]) or not 0 <= value[k] <= MAX_SECONDS
                   for k in ("start", "end"))):
        raise ValueError("A caption's whisper link is {capture, start, end}.")
    return {"capture": value["capture"], "start": float(value["start"]), "end": float(value["end"])}


def clean_captions(captions):
    """Validate caption lines the Kandha page showed, for its own session record.

    Each is {start, end, text, voice}: audio seconds, the words as shown, and the voice number
    (or null). A line from local Whisper may add whisper: {capture, start, end}, naming the
    engine caption it came from. Anything malformed rejects the batch."""
    if not isinstance(captions, list) or len(captions) > MAX_BATCH:
        raise ValueError(f"Send a list of at most {MAX_BATCH} captions.")
    clean = []
    for caption in captions:
        if not isinstance(caption, dict):
            raise ValueError("Captions are objects with start, end, text and voice.")
        start, end = _time(caption.get("start"), "start"), _time(caption.get("end"), "end")
        text = caption.get("text")
        if end < start or not isinstance(text, str) or not text.strip() or len(text) > MAX_CAPTION_TEXT:
            raise ValueError("Captions need ordered times and some text.")
        clean.append({"start": start, "end": end, "text": text.strip(), "voice": _voice(caption.get("voice"), allow_none=True),
                      "whisper": _whisper_link(caption.get("whisper"))})
    return clean


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
        elif kind == "haptic":
            zones = event.get("zones")
            pattern = event.get("pattern")
            if not isinstance(zones, str) or not 0 <= len(zones) <= 4 or set(zones) - ZONES or not isinstance(pattern, str) or not PATTERN_KEY.match(pattern):
                raise ValueError("Haptic events need zones from L, R, B, F and a pattern key.")
            clean.append({"kind": kind, "t": _time(event.get("t"), "t"), "zones": zones, "pattern": pattern,
                          "voice": _voice(event.get("voice"), allow_none=True)})
        elif kind == "seat":
            zone = event.get("zone")
            if zone is not None and zone not in ZONES and zone != "me":
                raise ValueError("Seat events need a zone of L, R, B, F, me or null.")
            clean.append({"kind": kind, "t": _time(event.get("t"), "t"), "voice": _voice(event.get("voice")), "zone": zone})
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
