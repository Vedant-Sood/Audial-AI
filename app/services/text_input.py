"""Extract local document text for the common ISL pathway; never run markup.

PDFs must contain text. Scanned images need OCR text from another tool. All
adapters enforce the same size/character limit and fail instead of truncating.
"""
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from app.services.lexicon import MAX_TEXT_CHARACTERS

MAX_BYTES = 2 * 1024 * 1024
SUPPORTED_SUFFIXES = {".txt", ".md", ".srt", ".vtt", ".json", ".html", ".htm", ".csv", ".docx", ".pdf"}


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if not self.hidden and tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    @classmethod
    def text(cls, markup):
        parser = cls()
        parser.feed(markup)
        return "".join(parser.parts).strip()


def subtitle_text(text):
    """Extract cue bodies; numbers spoken in captions are not cue identifiers."""
    captions = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        if not lines or lines[0].strip().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is not None:
            caption = PlainHTML.text("\n".join(lines[timing + 1:]))
            if caption:
                captions.append(caption)
    return "\n".join(captions)


def read_text_bytes(filename, contents):
    """Shared desktop/browser document adapter, with explicit unsupported input."""
    if len(contents) > MAX_BYTES:
        raise ValueError("Choose a document smaller than 2 MB.")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Choose TXT, MD, CSV, HTML, DOCX, text PDF, SRT, VTT, or transcript JSON.")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(contents)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_BYTES:
                    raise ValueError("The extracted Word document is larger than 2 MB.")
                markup = archive.read(info)
                if b"<!DOCTYPE" in markup:
                    raise ValueError("Unsupported Word XML declarations.")
                root = ET.fromstring(markup)
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = []
            for paragraph in root.iter(namespace + "p"):
                parts = []
                for node in paragraph.iter():
                    if node.tag == namespace + "t":
                        parts.append(node.text or "")
                    elif node.tag in {namespace + "br", namespace + "tab"}:
                        parts.append("\n" if node.tag.endswith("br") else "\t")
                paragraphs.append("".join(parts))
            text = "\n".join(paragraphs)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
            raise ValueError("Could not read this Word document.") from error
    elif suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(BytesIO(contents))
            if reader.is_encrypted:
                raise ValueError("Open an unencrypted PDF or paste its text.")
            if len(reader.pages) > 100:
                raise ValueError("Choose a PDF extract of at most 100 pages.")
            parts, length = [], 0
            for page in reader.pages:
                value = page.extract_text() or ""
                length += len(value) + 1
                if length > MAX_TEXT_CHARACTERS:
                    raise ValueError("Use a document extract up to 20,000 characters.")
                parts.append(value)
            text = "\n".join(parts)
        except PdfReadError as error:
            raise ValueError("Could not read this PDF. Try pasting its text.") from error
        if not text.strip():
            raise ValueError("This PDF has no extractable text. Paste OCR text from the scanned document.")
    else:
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeError as error:
            raise ValueError("Save text files as UTF-8, or paste the text directly.") from error
        if suffix == ".json":
            data = json.loads(text)
            captions = data.get("captions") if isinstance(data, dict) else data
            if not isinstance(captions, list) or any(not isinstance(c, dict) or not isinstance(c.get("text"), str) for c in captions):
                raise ValueError("Use a transcript JSON with a captions list and text in each caption.")
            text = "\n".join(c["text"] for c in captions)
        elif suffix in {".srt", ".vtt"}:
            text = subtitle_text(text)
        elif suffix in {".html", ".htm"}:
            text = PlainHTML.text(text)
    if len(text) > MAX_TEXT_CHARACTERS:
        raise ValueError("Use a document extract up to 20,000 characters.")
    if not text.strip():
        raise ValueError("The document contains no readable text.")
    return text


def read_text(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Choose a document smaller than 2 MB.")
    return read_text_bytes(path.name, path.read_bytes())
