from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import colorsys
import csv
import json
from pathlib import Path
import uuid
import math
from html import escape
from app.utils.paths import atomic_json, data_root
from app.services.voice_view import CUE_TEXT, MAX_EVENTS, UNATTRIBUTED, VoiceTrack, describe_tone


def speaker_color(index):
    h = (index * 0.61803398875 + 0.57) % 1
    # Dark hues preserve text contrast against the white caption surface.
    r, g, b = colorsys.hsv_to_rgb(h, 0.66, 0.43)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


@dataclass
class Caption:
    start: float
    end: float
    text: str
    speaker: str = "Unknown"
    word_confidence: float | None = None
    speaker_similarity: float | None = None
    overlap: bool | None = None
    voice: dict = field(default_factory=dict)

    def __post_init__(self):
        if not math.isfinite(self.start) or not math.isfinite(self.end) or self.start < 0 or self.end < self.start:
            raise ValueError("Caption timestamps must be finite and ordered.")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Caption text is required.")


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    title: str = "Untitled session"
    captions: list = field(default_factory=list)
    speakers: dict = field(default_factory=dict)
    # Sanket voice view: validated browser voice/cue/tone events (app/services/voice_view.py)
    voice_events: list = field(default_factory=list)

    def add(self, caption):
        self.captions.append(caption)
        if caption.speaker not in self.speakers:
            self.speakers[caption.speaker] = {"name": caption.speaker, "color": speaker_color(len(self.speakers))}

    def add_voice_events(self, events):
        room = MAX_EVENTS - len(self.voice_events)
        self.voice_events.extend(events[:max(0, room)])
        return min(len(events), max(0, room))

    def _display_speaker(self, caption, track):
        """The diarized name, or the voice-view slot when diarization left the caption unattributed."""
        name = self.speakers[caption.speaker]["name"]
        if track and caption.speaker in UNATTRIBUTED and not caption.overlap:
            voice = track.voice_for(caption.start, caption.end)
            if voice is not None:
                return f"Voice {voice}"
        return name

    def rename(self, speaker, name):
        if speaker not in self.speakers or not name.strip():
            raise ValueError("Choose an existing speaker and a nonempty name")
        self.speakers[speaker]["name"] = name.strip()[:100]

    def to_dict(self):
        data = {"schema_version": 2, "id": self.id, "created": self.created,
                "title": self.title, "speakers": self.speakers,
                "captions": [asdict(c) for c in self.captions]}
        if self.voice_events:
            track = VoiceTrack(self.voice_events)
            for row, caption in zip(data["captions"], self.captions):
                note = track.annotate(caption)
                if note:
                    row["voice_view"] = note
            data["voice_view"] = {
                "source": "Sanket voice engine in the browser (session-only voices; tone is an estimate, not a feeling)",
                "events": self.voice_events}
        return data

    def save(self, path=None):
        path = Path(path or data_root() / "sessions" / f"{self.id}.json")
        atomic_json(path, self.to_dict())
        return path

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        captions = [Caption(**{k: v for k, v in c.items() if k != "voice_view"}) for c in data["captions"]]
        return cls(id=data["id"], created=data["created"], title=data["title"], captions=captions,
                   speakers=data["speakers"], voice_events=list(data.get("voice_view", {}).get("events", [])))

    def export(self, path, kind):
        path = Path(path)
        if kind == "json":
            atomic_json(path, self.to_dict())
        elif kind == "txt":
            text = [self.title, self.created, ""]
            track = VoiceTrack(self.voice_events)
            rows = []
            for c in self.captions:
                name = self._display_speaker(c, track)
                line = f"[{c.start:08.2f} – {c.end:08.2f}] {name}: {c.text}" + (" [overlap]" if c.overlap else "")
                note = track.annotate(c) if track else None
                if note and note.get("tone"):
                    line += f" [{describe_tone(note['tone'])}]"
                rows.append((c.start, line))
            for cue in track.cues:
                who = f" (Voice {cue['voice']})" if cue["voice"] else ""
                rows.append((cue["t"], f"[{cue['t']:08.2f}] — {CUE_TEXT[cue['cue']]}{who}"))
            text.extend(line for _, line in sorted(rows, key=lambda row: row[0]))
            path.write_text("\n".join(text), encoding="utf-8")
        elif kind == "csv":
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                fields = list(Caption.__dataclass_fields__) + ["speaker_name"]
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for c in self.captions:
                    row = asdict(c)
                    row["speaker_name"] = self.speakers[c.speaker]["name"]
                    # Spreadsheet exports cannot execute transcript text as formulae.
                    for k, v in row.items():
                        if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")):
                            row[k] = "'" + v
                    writer.writerow(row)
        elif kind in {"srt", "vtt"}:
            rows = ["WEBVTT\n"] if kind == "vtt" else []
            def timestamp(seconds):
                milliseconds = round(seconds * 1000)
                hours, milliseconds = divmod(milliseconds, 3600000)
                minutes, milliseconds = divmod(milliseconds, 60000)
                seconds, milliseconds = divmod(milliseconds, 1000)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}{',' if kind == 'srt' else '.'}{milliseconds:03d}"
            track = VoiceTrack(self.voice_events)
            for index, caption in enumerate(sorted(self.captions, key=lambda c: c.start), 1):
                name = self._display_speaker(caption, track)
                text = " ".join(f"{name}: {caption.text}".split())
                text = escape(text) if kind == "vtt" else text.replace("<", "‹").replace(">", "›")
                end = max(caption.end, caption.start + 0.001)
                rows.extend([str(index), f"{timestamp(caption.start)} --> {timestamp(end)}", text, ""])
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        else:
            raise ValueError("Export must be txt, csv, json, srt, or vtt")
