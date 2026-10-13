"""Stable caption revisions and timestamped exports, independent of ASR provider."""

from dataclasses import dataclass, replace
import re


@dataclass(frozen=True)
class Caption:
    id: str
    start: float
    end: float
    text: str
    speaker: str | None = None  # Supply only a speaker attributed by the ASR/meeting source.
    final: bool = True
    tone: str = "uncertain"
    tone_confidence: float | None = None

    def __post_init__(self):
        import math
        if not self.id or not math.isfinite(self.start) or not math.isfinite(self.end) or self.start < 0 or self.end <= self.start:
            raise ValueError("Caption IDs and positive finite timestamp ranges are required.")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("A caption must preserve a nonempty transcript.")
        if self.tone not in {"uncertain", "angry", "disgust", "fear", "happy", "neutral", "sad"}:
            raise ValueError("Unsupported tone estimate.")
        if self.tone_confidence is not None and (not math.isfinite(self.tone_confidence) or not 0 <= self.tone_confidence <= 1):
            raise ValueError("Confidence must be between zero and one.")


class CaptionTimeline:
    def __init__(self):
        self._captions = {}

    def update(self, caption):
        previous = self._captions.get(caption.id)
        if previous and previous.final and not caption.final:
            return previous  # Late interim events cannot replace confirmed speech.
        self._captions[caption.id] = caption
        return caption

    def attach_tone(self, caption_id, estimate, audio_start, audio_end, *, speaker=None):
        caption = self._captions[caption_id]
        # Do not assign mixed/misaligned audio to a single person's words.
        if abs(caption.start - audio_start) > 0.15 or abs(caption.end - audio_end) > 0.15 or speaker != caption.speaker:
            raise ValueError("Tone audio must match the caption's interval and attributed speaker.")
        updated = replace(caption, tone=estimate["tone"], tone_confidence=estimate.get("confidence"))
        return self.update(updated)

    def final_captions(self):
        return sorted((c for c in self._captions.values() if c.final), key=lambda c: (c.start, c.end, c.id))

    def export(self, format="vtt", *, include_tone=False):
        if format not in {"vtt", "srt"}:
            raise ValueError("Choose vtt or srt.")
        result = ["WEBVTT\n"] if format == "vtt" else []
        for index, caption in enumerate(self.final_captions(), 1):
            lines = caption.text.strip().splitlines()
            text = " ".join(line.strip() for line in lines)
            if caption.speaker:
                text = f"{caption.speaker}: {text}"
            if include_tone and caption.tone != "uncertain":
                text += f" [voice tone estimate: {caption.tone}]"
            # Prevent text from creating a new cue or being parsed as markup.
            text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
            if format == "vtt":
                text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            else:
                text = text.replace("<", "‹").replace(">", "›")
            separator = "," if format == "srt" else "."
            result.extend([str(index), f"{timestamp(caption.start, separator)} --> {timestamp(caption.end, separator)}", text, ""])
        return "\n".join(result) + "\n"


def timestamp(seconds, separator="."):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
