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
from app.storage.transcript import Session
from app.utils.config import PRESETS, Settings
from app.utils.paths import project_root, data_root, atomic_json
from app.services.browser_bridge import BrowserBridge
from app.utils.palette import DEFAULT_EMOTION_COLORS, validate_palette
from app.services.voice_view import clean_events

# Sanket (browser/sanket/): static app files the companion may serve, and its tone model.
SANKET_FILES = {"index.html", "styles.css", "app.js", "tone.js", "engine.js", "captions.js", "recognizer.js",
                "translator.js", "band.js", "local-captions.js", "demo.js", "worklet.js"}
SANKET_LANGUAGES = {"en", "hi"}
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
# Sanket's page colours voices with inline style attributes (--c custom properties); scripts stay 'self'.
CSP_SANKET = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")


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
    def __init__(self, engine=None, settings=None, port=0, vocabulary=None):
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
        self.server = None
        self.thread = None
        self.unsubscribe = self.engine.subscribe(self.on_event)
        self.bridge = BrowserBridge(self)
        self.bridge_token = secrets.token_urlsafe(32)
        self.bridge_stopped = threading.Event()
        self._bridge_thread = None
        self.saved_language = None

    def on_event(self, kind, data):
        if kind not in {"caption","partial","status","warning","error","prosody","performance","isl_settings","isl_vocabulary","emotion","caption_voice","voice","voice_settings"}:
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
                self.send_header("Content-Security-Policy", CSP_SANKET if self.path.startswith("/sanket/") else CSP)
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

            def do_GET(self):
                if not self.allowed():return
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                try:
                    if parsed.path == "/api/tabs":
                        self.respond(200, service.bridge.snapshot())
                    elif parsed.path == "/api/status":
                        selected = PRESETS[service.settings.preset]["asr"]
                        self.respond(200,{"running":service.engine.running,"source":service.engine.source,
                            "asr_model":selected,"asr_installed":service.engine.manager.installed(selected),
                            "language":service.settings.language,"sign_language":ISL_LANGUAGE,
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
                        with service.lock, tempfile.TemporaryDirectory() as directory:
                            target = Path(directory)/("transcript."+kind)
                            service.session.export(target,kind)
                            self.respond(200,target.read_bytes(),"text/vtt; charset=utf-8" if kind=="vtt" else "application/octet-stream","transcript."+kind)
                    elif parsed.path == "/sanket":
                        self.send_response(308); self.send_header("Location", "/sanket/"); self.send_header("Content-Length", "0"); self.end_headers()
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
                except (ValueError,OSError) as error:
                    self.respond(400,{"error":str(error)})

            def do_POST(self):
                if not self.allowed():return
                try:
                    size = int(self.headers.get("Content-Length","0"))
                    if not 0 <= size <= 4*1024*1024:raise ValueError("Request is too large.")
                    body = self.rfile.read(size)
                    if len(body)!=size:raise ValueError("Incomplete request.")
                    parsed = urlsplit(self.path)
                    if parsed.path == "/api/bridge":
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
                            # A page may choose this session's speech language (Sanket's English/हिन्दी);
                            # the saved desktop preference is restored when the session stops.
                            if language is not None and language != service.settings.language:
                                service.saved_language = service.settings.language
                                service.settings.language = language
                            service.engine.start(mode,source="browser")
                            service.session = Session(title="Browser meeting")
                            service.session_id = uuid.uuid4().hex
                            self.respond(200,{"started":True,"cursor":cursor,"session_id":service.session_id})
                    elif self.path == "/api/audio":
                        if self.headers.get("Content-Type","").split(";")[0]!="audio/wav":raise ValueError("Send audio/wav.")
                        import soundfile as sf
                        audio,rate = sf.read(BytesIO(body),dtype="float32")
                        if not 8000 <= rate <= 192000 or len(audio)>rate*3 or len(audio)==0:
                            raise ValueError("Use nonempty audio packets under three seconds, at 8–192 kHz.")
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
                                if service.saved_language is not None:
                                    service.settings.language, service.saved_language = service.saved_language, None
                            else:service.engine.pause(bool(options.get("paused")))
                        self.respond(200,{"ok":True})
                    else:self.respond(404,{"error":"Not found."})
                except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:
                    self.respond(400,{"error":str(error)})

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
