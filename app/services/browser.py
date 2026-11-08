"""Loopback browser companion for the existing audio engine and real ISL poses."""
from collections import deque
from dataclasses import asdict, is_dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hashlib
import json
import mimetypes
from pathlib import Path
import tempfile
import threading
import uuid
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import numpy as np

from app.audio.features import mono_resample
from app.models.manager import ModelManager
from app.services.engine import AudioEngine
from app.services.isl import ISLVocabulary, load_pose_frames
from app.services.lexicon import ISL_LANGUAGE, SignLexicon
from app.services.text_input import read_text_bytes
from app.storage.transcript import Caption, Session
from app.utils.config import PRESETS, Settings
from app.utils.paths import project_root, data_root, atomic_json
from app.services.browser_bridge import BrowserBridge
from app.utils.palette import DEFAULT_EMOTION_COLORS, validate_palette
from app.services.voice_view import MAX_EVENTS, clean_captions, clean_events
from app.kandha.service import KandhaService

# Sanket voice engine (browser/sanket/): shared library files the companion and Kandha load.
SANKET_FILES = {"tone.js", "engine.js", "captions.js", "recognizer.js", "translator.js", "local-captions.js", "worklet.js"}
# Kandha (browser/kandha/): the app, served under /kandha/ with its bundled font.
KANDHA_FILES = {"index.html", "styles.css", "app.js", "views.js", "demo.js", "kandha-intents.js"}
KANDHA_FONTS = {"AtkinsonHyperlegible-Regular.ttf", "AtkinsonHyperlegible-Bold.ttf", "AtkinsonHyperlegible-Italic.ttf",
                "AtkinsonHyperlegible-BoldItalic.ttf", "OFL.txt"}
SANKET_LANGUAGES = {"en", "hi"}
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
# Kandha's page colours voices with inline style attributes (--c custom properties); scripts stay 'self'.
CSP_SANKET = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'").replace("default-src 'self'", "default-src 'self'; font-src 'self'")


def sanket_model():
    """The tone model bytes, only if they match the SHA-256 recorded in its provenance."""
    folder = project_root() / "models" / "sanket"
    data = (folder / "tone_model.json").read_bytes()
    expected = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))["sha256"]
    if hashlib.sha256(data).hexdigest() != expected:
        raise OSError("The Sanket tone model does not match its recorded SHA-256.")
    return data


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def pose_sequence(entry):
    frames = load_pose_frames(entry)
    body_indexes = [0,11,12,13,14,15,16]
    output = []
    for index, frame in enumerate(frames):
        frame = frame.copy()
        frame[:,:2] = np.clip(frame[:,:2],0,1)
        body = np.zeros((33,4),np.float32)
        body[body_indexes] = frame[:7]
        output.append({"timeMs": index * 1000 / entry.get("fps",15), "body": body.tolist(),
                       "leftHand": frame[7:28].tolist(), "rightHand": frame[28:49].tolist()})
    return {"gloss": entry["gloss"], "frames": output, "source": entry["source_url"], "license": entry["license"]}


class BrowserService:
    def __init__(self, engine=None, settings=None, port=0, vocabulary=None, kandha_backend=None, kandha_bridge=True):
        self.settings = settings or Settings.load()
        self.engine = engine or AudioEngine(self.settings, queue_events=False)
        self.owns_engine = engine is None
        self.vocabulary = vocabulary or ISLVocabulary()
        self.sign_media = {}
        self.port = port
        self.session = Session(title="Browser meeting")
        self.events = deque(maxlen=400)
        self.lock = threading.RLock()
        self.control_lock = threading.RLock()
        self.session_id = None
        self.id = 0
        # The Kandha page's own session record (captions it showed and its events), apart from
        # the Whisper capture above: it is what "Save to sessions" and the Kandha exports write.
        self.kandha_session = None
        # (record caption, engine caption, whole?) for Kandha lines that came from local Whisper
        self.kandha_links = []
        # held while a new Kandha session replaces the record and announces it (start_kandha_session)
        self.kandha_start_lock = threading.Lock()
        # Kandha: haptic scheduling, seat map, queue, the virtual stole and the Bluetooth bridge.
        # Captions never depend on it; a failure here is reported, not raised. It is built after
        # the event feed exists, because its bridge thread can publish (a remembered stole
        # reconnecting) before this constructor returns.
        self.kandha = KandhaService(publish=self.on_event, backend=kandha_backend, start_bridge=kandha_bridge)
        self.server = None
        self.thread = None
        self.unsubscribe = self.engine.subscribe(self.on_event)
        self.bridge = BrowserBridge(self)
        self.bridge_token = secrets.token_urlsafe(32)
        self.bridge_stopped = threading.Event()

    def on_event(self, kind, data):
        if kind not in {"caption","partial","status","warning","error","prosody","performance","isl_settings","isl_vocabulary","emotion","caption_voice","voice","voice_settings","kandha"}:
            return
        with self.lock:
            if kind == "caption":
                self.session.add(replace(data, voice=dict(data.voice)))
            elif kind == "caption_voice":
                for caption in reversed(self.session.captions[-40:]):
                    if (caption.start, caption.end, caption.speaker) == (data["start"], data["end"], data["speaker"]):
                        caption.voice = {**caption.voice, "tone": data["estimate"]["tone"], "tone_confidence": data["estimate"].get("confidence")}
                        break
            self.id += 1
            self.events.append({"id": self.id,"kind": kind,"data": data})

    def voice_settings(self):
        return {"colors": self.settings.voice_colors, "cues": self.settings.voice_cues,
                "tone": self.settings.voice_tone, "model": (project_root() / "models" / "sanket" / "tone_model.json").is_file()}

    def add_voice_events(self, session_id, events):
        """Store a batch from the capture that owns `session_id`, then republish it to pages."""
        clean = clean_events(events)
        with self.lock:
            if session_id is None or session_id != self.session_id:
                raise PermissionError("These voice events belong to a stopped or different capture session.")
            stored = self.session.add_voice_events(clean)
        if clean:
            self.on_event("voice", {"events": clean})
        return {"stored": stored}

    # ------------------------------------------------------------- the Kandha page's session record
    def new_kandha_session(self):
        """Start the record for a new Kandha session (live or demo); the unsaved previous one is dropped."""
        with self.lock:
            self.kandha_session = Session(title="Kandha session")
            self.kandha_links = []
            return self.kandha_session.id

    def start_kandha_session(self, page=None):
        """A new session on a Kandha page (live or demo): a new record, then the "session" event
        that names the asking window. Both happen under one lock, so when two windows start at
        once the events go out in the order the records were replaced: the window holding the
        current record hears its own event last, and only the other window marks itself replaced.
        Its own lock (not self.lock), since the Kandha service takes its lock before ours."""
        with self.kandha_start_lock:
            session_id = self.new_kandha_session()
            return self.kandha.new_session(page) | {"session_id": session_id}

    def kandha_record(self, session_id, require_content=False):
        """The current Kandha record, only for the page session that started it. Hold self.lock."""
        record = self.kandha_session
        if record is None or not isinstance(session_id, str) or session_id != record.id:
            raise PermissionError("This is not the current Kandha session. Start listening or watch a demo, then save it.")
        if require_content and not record.captions and not record.voice_events:
            raise ValueError("Nothing to save yet: this session has no captions, voices, cues or taps.")
        return record

    def kandha_saved_record(self, session_id):
        """The record a consented save or export writes. Hold self.lock.

        A line from local Whisper takes the engine caption's details as they are now (a tone
        estimate can arrive after the page sent the line): word confidence and overlap always,
        and the speaker similarity and voice measurements only when it shows the whole caption,
        since a piece the page gave another voice is not that voice's tone."""
        record = self.kandha_record(session_id, require_content=True)
        for caption, source, whole in self.kandha_links:
            caption.word_confidence, caption.overlap = source.word_confidence, source.overlap
            if whole:
                caption.speaker_similarity, caption.voice = source.speaker_similarity, dict(source.voice)
        return record

    def add_kandha_record(self, session_id, events=None, captions=None):
        """Captions the Kandha page showed and its voice, cue, tone, queue, haptic and seat events.

        Stored whatever the caption source (Whisper, the browser's captions or a demo), so the
        saved session is the one on screen. Kept in memory until a consented save."""
        clean = clean_events([] if events is None else events)
        lines = clean_captions([] if captions is None else captions)
        with self.lock:
            record = self.kandha_record(session_id)
            stored = record.add_voice_events(clean)
            added = 0
            for line in lines[:max(0, MAX_EVENTS - len(record.captions))]:
                speaker = f"Voice {line['voice']}" if line["voice"] is not None else "Unattributed"
                caption = Caption(line["start"], line["end"], line["text"], speaker)
                record.add(caption)
                added += 1
                link = line["whisper"]
                # only the capture still held here; an engine caption is matched by its exact times
                if link and link["capture"] == self.session_id:
                    source = next((c for c in reversed(self.session.captions[-400:]) if (c.start, c.end) == (link["start"], link["end"])), None)
                    if source is not None:
                        whole = abs(caption.start - source.start) <= 0.01 and abs(caption.end - source.end) <= 0.01
                        self.kandha_links.append((caption, source, whole))
        return {"stored": stored, "captions": added}

    def sign_plan(self, text):
        """Return every ordered step; each distinct pose is encoded only once.

        Video URLs are opaque identifiers for validated vocabulary media, never
        caller-supplied paths. Desktop and browser use the same selected pack.
        """
        plan = self.vocabulary.plan(text)
        steps, sequences, indexes, missing = [], [], {}, []
        for step in plan:
            if step["kind"] == "text":
                steps.append(step.copy())
                missing.extend(SignLexicon.tokens(step["text"]))
                continue
            entry = step["entry"]
            item = {"text": step["text"], "gloss": entry["gloss"], "source": entry["source_url"],
                    "license": entry["license"], "attribution": entry.get("attribution", "")}
            if entry["path"].suffix.lower() == ".npy":
                identity = (str(entry["path"]), entry.get("fps", 15), entry["gloss"])
                if identity not in indexes:
                    try:
                        sequence = pose_sequence(entry)
                    except (OSError, ValueError, TypeError) as error:
                        steps.append({"kind": "text", "text": step["text"], "reason": "The loaded sign media could not be read: " + str(error)})
                        missing.extend(SignLexicon.tokens(step["text"]))
                        continue
                    indexes[identity] = len(sequences)
                    sequences.append(sequence)
                item.update(kind="pose", sequence_index=indexes[identity])
            else:
                stat = entry["path"].stat()
                identity = f"{entry['path']}:{stat.st_size}:{stat.st_mtime_ns}"
                media_id = hashlib.sha256(identity.encode()).hexdigest()
                with self.lock:
                    self.sign_media[media_id] = entry["path"]
                item.update(kind="video", url="/api/sign-media/" + media_id, fps=entry.get("fps", 15))
            steps.append(item)
        return {"language": ISL_LANGUAGE, "text": text, "steps": steps, "sequences": sequences,
                "missing": missing, "vocabulary": self.vocabulary.summary(),
                "note": "Local vocabulary in input order with explicit text fallback; this is not fluent ISL sentence translation."}

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        service = self
        browser = project_root() / "browser"
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(15)

            def respond(self, code, data, content_type="application/json; charset=utf-8", filename=None):
                if not isinstance(data,bytes):
                    data = json.dumps(data,default=json_default,allow_nan=False).encode()
                self.send_response(code)
                self.send_header("Content-Type",content_type)
                self.send_header("Content-Length",str(len(data)))
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Security-Policy", CSP_SANKET if self.path.startswith(("/sanket/", "/kandha/")) else CSP)
                if filename:
                    self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(data)

            def allowed(self):
                hosts = {f"127.0.0.1:{service.server.server_port}",f"localhost:{service.server.server_port}"}
                origin = self.headers.get("Origin")
                if self.headers.get("Host") not in hosts or (origin and origin not in {"http://"+host for host in hosts}):
                    self.respond(403,{"error":"Use the local companion origin."})
                    return False
                return True

            def serve_sign_media(self, media_id):
                with service.lock:
                    path = service.sign_media.get(media_id)
                if path is None:
                    self.respond(404, {"error": "No such vocabulary clip."})
                    return
                size = path.stat().st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get("Range")
                if requested:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                    if not match or not any(match.groups()):
                        raise ValueError("Use a single byte range.")
                    first, last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                    else:
                        start = max(0, size - int(last))
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                self.send_response(status)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "video/mp4")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                with path.open("rb") as clip:
                    clip.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = clip.read(min(remaining, 256 * 1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def serve_stream(self):
                """Server-sent events: haptic commands, pad presses, stole status, seats, queue, settings."""
                subscription = service.kandha.subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", CSP_SANKET)
                self.end_headers()
                try:
                    self.wfile.write(b"retry: 1000\n\n")
                    self.wfile.write(b"event: state\ndata: " + json.dumps(service.kandha.snapshot(), default=json_default).encode() + b"\n\n")
                    self.wfile.flush()
                    while not service.kandha.stopping.is_set() and service.server is not None:
                        try:
                            item = subscription.get(timeout=10)
                        except Exception:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            continue
                        kind = str(item.get("kind", "event"))
                        self.wfile.write(f"event: {kind}\ndata: ".encode() + json.dumps(item, default=json_default).encode() + b"\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                    pass
                finally:
                    service.kandha.unsubscribe(subscription)
                    self.close_connection = True

            def do_GET(self):
                if not self.allowed():return
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                try:
                    if parsed.path == "/api/kandha/stream":
                        self.serve_stream()
                    elif parsed.path == "/api/kandha/state":
                        self.respond(200, service.kandha.snapshot())
                    elif parsed.path == "/api/kandha/rooms":
                        self.respond(200, service.kandha.rooms("list"))
                    elif parsed.path in {"/sanket", "/sanket/", "/sanket/index.html", "/kandha"}:
                        self.send_response(308); self.send_header("Location", "/kandha/"); self.send_header("Content-Length", "0"); self.end_headers()
                    elif parsed.path == "/kandha/tone-model.json":
                        self.respond(200, sanket_model())
                    elif parsed.path in {"/kandha/icon.svg", "/favicon.ico"}:
                        self.respond(200, (project_root()/"assets"/"icon.svg").read_bytes(), "image/svg+xml")
                    elif parsed.path == "/kandha/patterns.json":
                        self.respond(200, (browser/"sanket"/"kandha-patterns.json").read_bytes())
                    elif parsed.path.startswith("/kandha/fonts/"):
                        filename = parsed.path.removeprefix("/kandha/fonts/")
                        if filename not in KANDHA_FONTS:
                            self.respond(404,{"error":"Not found."});return
                        type_ = "font/ttf" if filename.endswith(".ttf") else "text/plain; charset=utf-8"
                        self.respond(200,(browser/"kandha"/"fonts"/filename).read_bytes(),type_)
                    elif parsed.path.startswith("/kandha/"):
                        filename = parsed.path.removeprefix("/kandha/") or "index.html"
                        if filename not in KANDHA_FILES:
                            self.respond(404,{"error":"Not found."});return
                        type_ = "text/html" if filename.endswith(".html") else "text/css" if filename.endswith(".css") else "text/javascript"
                        self.respond(200,(browser/"kandha"/filename).read_bytes(),type_+"; charset=utf-8")
                    elif parsed.path == "/api/tabs":
                        self.respond(200, service.bridge.snapshot())
                    elif parsed.path == "/api/status":
                        selected = PRESETS[service.settings.preset]["asr"]
                        self.respond(200,{"running":service.engine.running,"source":service.engine.source,
                            "asr_model":selected,"asr_installed":service.engine.manager.installed(selected),
                            "language":service.engine.language if service.engine.running else service.settings.language,"sign_language":ISL_LANGUAGE,
                            "auto_sign":service.settings.auto_sign,"vocabulary":service.vocabulary.summary(),
                            "emotion_enabled":service.settings.prosody_classifier,"voice_view":service.voice_settings(),
                            "cursor":service.id})
                    elif parsed.path == "/api/palette":
                        self.respond(200, {"colors": service.settings.emotion_colors,
                                           "defaults": DEFAULT_EMOTION_COLORS})
                    elif parsed.path == "/api/events":
                        cursor = int(query.get("after",["0"])[0])
                        with service.lock:
                            events = [event for event in service.events if event["id"] > cursor]
                            gap = bool(service.events and cursor and cursor < service.events[0]["id"]-1)
                            self.respond(200,{"events":events,"cursor":service.id,"gap":gap})
                    elif parsed.path == "/api/signs":
                        self.respond(200, service.sign_plan(query.get("text", [""])[0]))
                    elif parsed.path.startswith("/api/sign-media/"):
                        self.serve_sign_media(parsed.path.removeprefix("/api/sign-media/"))
                    elif parsed.path == "/api/isl":
                        self.respond(200, {**service.vocabulary.summary(), "auto_sign": service.settings.auto_sign})
                    elif parsed.path == "/api/export":
                        kind = query.get("format",["vtt"])[0]
                        if kind not in {"vtt","srt","json","txt","csv"}:raise ValueError("Unsupported export format.")
                        # ?session=<id>: the Kandha page's own session record, never an older capture.
                        # A blank ?session= (the page lost its id) is refused, not the companion's export.
                        wanted = parse_qs(parsed.query, keep_blank_values=True).get("session", [None])[0]
                        with service.lock, tempfile.TemporaryDirectory() as directory:
                            try:
                                exported = service.session if wanted is None else service.kandha_saved_record(wanted)
                            except PermissionError as error:
                                self.respond(409, {"error": str(error)}); return
                            target = Path(directory)/("transcript."+kind)
                            exported.export(target,kind)
                            self.respond(200,target.read_bytes(),"text/vtt; charset=utf-8" if kind=="vtt" else "application/octet-stream","transcript."+kind)
                    elif parsed.path == "/sanket/tone-model.json":
                        self.respond(200, sanket_model())
                    elif parsed.path.startswith("/sanket/"):
                        filename = parsed.path.removeprefix("/sanket/") or "index.html"
                        if filename not in SANKET_FILES:
                            self.respond(404,{"error":"Not found."});return
                        type_ = "text/html" if filename.endswith(".html") else "text/css" if filename.endswith(".css") else "text/javascript"
                        self.respond(200,(browser/"sanket"/filename).read_bytes(),type_+"; charset=utf-8")
                    else:
                        allowed = {"index.html","app.js","styles.css","light-box.js","capture.js","pcm-worklet.js","emotion.js","isl-playback.js","transcript.js","notifications.js","voice-session.js","voice-view.js"}
                        filename = parsed.path.lstrip("/") or "index.html"
                        if filename not in allowed:
                            self.respond(404,{"error":"Not found."});return
                        type_ = "text/html" if filename.endswith(".html") else "text/css" if filename.endswith(".css") else "text/javascript"
                        self.respond(200,(browser/filename).read_bytes(),type_+"; charset=utf-8")
                except (ValueError,OSError,ArithmeticError) as error:
                    self.respond(400,{"error":str(error)})

            def do_POST(self):
                if not self.allowed():return
                try:
                    size = int(self.headers.get("Content-Length","0"))
                    if not 0 <= size <= 4*1024*1024:raise ValueError("Request is too large.")
                    body = self.rfile.read(size)
                    if len(body)!=size:raise ValueError("Incomplete request.")
                    parsed = urlsplit(self.path)
                    if parsed.path.startswith("/api/kandha/"):
                        self.kandha_post(parsed.path.removeprefix("/api/kandha/"), json.loads(body or b"{}"))
                    elif parsed.path == "/api/bridge":
                        if not secrets.compare_digest(self.headers.get("X-Audial-Bridge", ""), service.bridge_token):
                            self.respond(403, {"error": "Use the installed Audial-AI browser bridge."})
                            return
                        self.respond(200, service.bridge.handle(json.loads(body or b"{}")))
                    elif parsed.path == "/api/voice-events":
                        options = json.loads(body or b"{}")
                        if not isinstance(options, dict):
                            raise ValueError("Send a JSON object with session_id and events.")
                        try:
                            self.respond(200, service.add_voice_events(options.get("session_id"), options.get("events")))
                        except PermissionError as error:
                            self.respond(409, {"error": str(error)})
                    elif parsed.path == "/api/voice-view/settings":
                        options = json.loads(body or b"{}")
                        if not isinstance(options, dict) or not all(isinstance(options.get(k), bool) for k in ("colors", "cues", "tone")):
                            raise ValueError("Send colors, cues and tone as true or false.")
                        with service.control_lock:
                            service.settings.voice_colors, service.settings.voice_cues, service.settings.voice_tone = options["colors"], options["cues"], options["tone"]
                            service.settings.save()
                        service.on_event("voice_settings", service.voice_settings())
                        self.respond(200, service.voice_settings())
                    elif parsed.path == "/api/browser-command":
                        options = json.loads(body or b"{}")
                        self.respond(200, service.bridge.queue_command(options["profile"], int(options["tab_id"])))
                    elif parsed.path == "/api/signs":
                        options = json.loads(body or b"{}")
                        if not isinstance(options, dict):
                            raise ValueError("Send a JSON object with text.")
                        self.respond(200, service.sign_plan(options.get("text")))
                    elif parsed.path == "/api/document":
                        filename = parse_qs(parsed.query).get("filename", [""])[0]
                        self.respond(200, service.sign_plan(read_text_bytes(filename, body)))
                    elif parsed.path == "/api/isl/settings":
                        options = json.loads(body or b"{}")
                        if not isinstance(options, dict) or not isinstance(options.get("auto_sign"), bool) or options.get("language", ISL_LANGUAGE) != ISL_LANGUAGE:
                            raise ValueError("Use ISL and a boolean auto_sign preference.")
                        with service.control_lock:
                            service.settings.auto_sign = options["auto_sign"]
                            service.settings.save()
                        service.engine.emit("isl_settings", {"language": ISL_LANGUAGE, "auto_sign": service.settings.auto_sign})
                        self.respond(200, {"language": ISL_LANGUAGE, "auto_sign": service.settings.auto_sign})
                    elif self.path == "/api/palette":
                        options = json.loads(body or b"{}")
                        if not isinstance(options, dict):
                            raise ValueError("Send a JSON object.")
                        colors = validate_palette(options.get("colors"))
                        with service.control_lock:
                            service.settings.emotion_colors = colors.copy()
                            service.settings.save()
                        self.respond(200, {"colors": colors})
                    elif self.path == "/api/start":
                        options = json.loads(body or b"{}")
                        if not isinstance(options,dict):raise ValueError("Send a JSON object.")
                        mode = options.get("mode","combined")
                        language = options.get("language")
                        if language is not None and language not in SANKET_LANGUAGES:
                            raise ValueError("Caption language must be en or hi.")
                        with service.control_lock, service.lock:
                            if service.engine.running:
                                self.respond(409,{"error":"Stop the current audio session before starting browser capture."});return
                            cursor = service.id
                            service.engine.start(mode,source="browser",language=language)
                            service.session = Session(title="Browser meeting")
                            service.session_id = uuid.uuid4().hex
                            self.respond(200,{"started":True,"cursor":cursor,"session_id":service.session_id})
                    elif self.path == "/api/audio":
                        if self.headers.get("Content-Type","").split(";")[0]!="audio/wav":raise ValueError("Send audio/wav.")
                        import soundfile as sf
                        # Check metadata before allocating decoded samples. A small
                        # compressed file can otherwise expand far beyond the limit.
                        with sf.SoundFile(BytesIO(body)) as packet:
                            rate = packet.samplerate
                            if (packet.format not in {"WAV", "WAVEX"} or packet.channels not in {1, 2}
                                    or not 8000 <= rate <= 192000 or not 0 < packet.frames <= rate * 3):
                                raise ValueError("Use nonempty mono or stereo WAV packets up to three seconds, at 8–192 kHz.")
                            audio = packet.read(dtype="float32")
                        start = float(self.headers["X-Audio-Start-Seconds"])
                        with service.control_lock:
                            if (not service.engine.running or service.engine.source!="browser" or service.engine.capture is None
                                    or service.engine.stop_requested.is_set() or self.headers.get("X-Session-ID")!=service.session_id):
                                self.respond(409,{"error":"This browser audio session has stopped."});return
                            service.engine.capture.feed(mono_resample(audio,rate),start)
                        self.respond(200,{"queued":True})
                    elif self.path in {"/api/stop","/api/pause"}:
                        options = json.loads(body or b"{}")
                        if not isinstance(options,dict):raise ValueError("Send a JSON object.")
                        with service.control_lock:
                            if service.engine.source!="browser" or options.get("session_id")!=service.session_id or service.session_id is None:
                                self.respond(409,{"error":"This session is controlled by another window."});return
                            if self.path=="/api/stop":
                                service.engine.stop()
                            else:service.engine.pause(bool(options.get("paused")))
                        self.respond(200,{"ok":True})
                    else:self.respond(404,{"error":"Not found."})
                # ArithmeticError: int()/float() of an infinite or huge JSON number (1e999, Infinity)
                except (ValueError,TypeError,KeyError,OSError,RuntimeError,ArithmeticError) as error:
                    self.respond(400,{"error":str(error)})

            def kandha_post(self, action, options):
                if not isinstance(options, dict):
                    raise ValueError("Send a JSON object.")
                k = service.kandha
                if action == "intents":
                    self.respond(200, k.intents(options.get("intents"), options.get("current")))
                elif action == "queue":
                    self.respond(200, k.set_queue(bool(options.get("on")), str(options.get("source", "screen"))[:20]))
                elif action == "settings":
                    self.respond(200, k.update_settings(options.get("settings", options)))
                elif action == "seats":
                    self.respond(200, k.assign_seat(options.get("voice"), options.get("zone"), str(options.get("source", "screen"))[:20]))
                elif action == "merge":
                    self.respond(200, k.merge_voices(options.get("keep"), options.get("drop")))
                elif action == "rooms":
                    self.respond(200, k.rooms(options.get("action"), options.get("name")))
                elif action == "test":
                    self.respond(200, {"played": k.test(options.get("zone"), options.get("pattern"), options.get("repeat", 1))})
                elif action == "stop":
                    self.respond(200, {"played": k.stop_haptics()})
                elif action == "pad":
                    self.respond(200, k.press_pad(options.get("pad"), options.get("gesture", "tap")))
                elif action == "stole/scan":
                    self.respond(200, {"devices": k.scan(options.get("timeout", 6))})
                elif action == "stole/pair":
                    self.respond(200, {"connected": k.pair(options.get("address"), options.get("name")), "stole": k.snapshot()["stole"]})
                elif action == "stole/forget":
                    self.respond(200, k.forget())
                elif action == "stole/simulate":
                    self.respond(200, k.simulate(options.get("action"), options.get("value")))
                elif action == "session/new":
                    # a new session on the page (live or demo) gets a new record; session_id names it
                    self.respond(200, service.start_kandha_session(options.get("page")))
                elif action == "session/events":
                    try:
                        self.respond(200, service.add_kandha_record(options.get("session_id"), options.get("events"), options.get("captions")))
                    except PermissionError as error:
                        self.respond(409, {"error": str(error)})
                elif action == "session/save":
                    if options.get("consent") is not True:
                        self.respond(403, {"error": "Saving needs everyone's consent: tick the consent box first."}); return
                    with service.lock:
                        try:
                            record = service.kandha_saved_record(options.get("session_id"))
                        except PermissionError as error:
                            self.respond(409, {"error": str(error)}); return
                        title = str(options.get("title") or record.title)[:120]
                        record.title = title
                        path = record.save()
                        counts = len(record.captions), len(record.voice_events)
                    self.respond(200, {"saved": path.name, "title": title, "captions": counts[0], "voice_events": counts[1]})
                else:
                    self.respond(404, {"error": "Not found."})

            def log_message(self,*args):pass

        self.server = ThreadingHTTPServer(("127.0.0.1",self.port),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        discovery = data_root() / "browser-bridge.json"
        atomic_json(discovery, {"url": self.url, "token": self.bridge_token})
        discovery.chmod(0o600)
        self.bridge_stopped.clear()
        def watch_bridge():
            while not self.bridge_stopped.wait(1):
                self.bridge.expire()
        self._bridge_thread = threading.Thread(target=watch_bridge, daemon=True, name="bridge-watch")
        self._bridge_thread.start()
        return self.url

    def stop(self):
        self.bridge_stopped.set()
        if self._bridge_thread is not None and self._bridge_thread.is_alive():
            self._bridge_thread.join(timeout=3)
        if self.bridge.owner:
            self.bridge.stop(self.bridge.owner["profile"], self.bridge.owner["session_id"])
        if self.owns_engine:self.engine.stop()
        if self.server:
            discovery = data_root() / "browser-bridge.json"
            try:
                saved = json.loads(discovery.read_text(encoding="utf-8"))
                if saved.get("token") == self.bridge_token:
                    discovery.unlink()
            except (OSError, ValueError):
                pass
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.unsubscribe()


def main(port=8765, open_browser=False):
    import time
    service = BrowserService(port=port)
    print("AccessibilityAI browser companion: "+service.start(),flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(service.url)
    try:
        while True:time.sleep(.2)
    except KeyboardInterrupt:
        service.stop()


if __name__ == "__main__":main()
