"""Read local text/subtitles for sign lookup without interpreting markup as code."""
import json
from pathlib import Path
import re

MAX_BYTES = 2 * 1024 * 1024


def read_text(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Choose a text file smaller than 2 MB.")
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
        captions = data.get("captions") if isinstance(data, dict) else data
        if not isinstance(captions, list) or any(not isinstance(c, dict) or not isinstance(c.get("text"), str) for c in captions):
            raise ValueError("Use a transcript JSON with a captions list and text in each caption.")
        return "\n".join(c["text"] for c in captions)
    if suffix in {".srt", ".vtt"}:
        lines, skip_block = [], False
        for line in text.splitlines():
            value = line.strip()
            if not value:
                skip_block = False
                continue
            if value.startswith(("NOTE", "STYLE", "REGION")):
                skip_block = True
            if skip_block or "-->" in value or value.isdigit() or value.startswith("WEBVTT"):
                continue
            # Subtitle formatting is display text, never rich HTML.
            lines.append(re.sub(r"<[^>]*>", "", value))
        return "\n".join(lines)
    if suffix not in {".txt", ".md"}:
        raise ValueError("Choose TXT, Markdown, SRT, VTT, or transcript JSON.")
    return text
