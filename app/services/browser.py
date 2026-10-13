"""Loopback browser companion for the existing audio engine and real ISL poses."""
from collections import deque
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import uuid
from urllib.parse import parse_qs, urlsplit

import numpy as np

from app.audio.features import mono_resample
from app.models.manager import ModelManager
from app.services.engine import AudioEngine
from app.services.lexicon import SignLexicon
from app.storage.transcript import Session
from app.utils.config import PRESETS, Settings
from app.utils.paths import project_root
from app.utils.palette import DEFAULT_EMOTION_COLORS, validate_palette


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def pose_sequence(entry):
    frames = np.load(entry["path"], allow_pickle=False)
    if frames.ndim != 3 or frames.shape[1:] != (49,4) or len(frames) > 1500 or not np.isfinite(frames).all():
        raise ValueError("Invalid raw ISL pose sequence.")
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
    def __init__(self, engine=None, settings=None, port=0):
        self.settings = settings or Settings.load()
        self.engine = engine or AudioEngine(self.settings)
        self.owns_engine = engine is None
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

    def on_event(self, kind, data):
        if kind not in {"caption","partial","status","warning","error","prosody","performance"}:
            return
        with self.lock:
            if kind == "caption":
                self.session.add(data)
            self.id += 1
            self.events.append({"id": self.id,"kind": kind,"data": data})

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
                self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
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

            def do_GET(self):
                if not self.allowed():return
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                try:
                    if parsed.path == "/api/status":
                        selected = PRESETS[service.settings.preset]["asr"]
                        self.respond(200,{"running":service.engine.running,"source":service.engine.source,
                            "asr_model":selected,"asr_installed":service.engine.manager.installed(selected),
                            "language":service.settings.language,"sign_language":"ISL",
                            "emotion_enabled":service.settings.prosody_classifier,"cursor":service.id})
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
                        text = query.get("text",[""])[0][:2000]
                        lexicon = SignLexicon(project_root()/"assets/isl_lexicon/lexicon.json")
                        known,missing = lexicon.lookup(text)
                        sequences = [pose_sequence(entry) for entry in known[:12] if entry["path"].suffix==".npy"]
                        self.respond(200,{"language":"ISL","sequences":sequences,"missing":missing,
                            "note":"Known phrase lookup in spoken order; detailed facial cues are absent."})
                    elif parsed.path == "/api/export":
                        kind = query.get("format",["vtt"])[0]
                        if kind not in {"vtt","srt","json","txt","csv"}:raise ValueError("Unsupported export format.")
                        with service.lock, tempfile.TemporaryDirectory() as directory:
                            target = Path(directory)/("transcript."+kind)
                            service.session.export(target,kind)
                            self.respond(200,target.read_bytes(),"text/vtt; charset=utf-8" if kind=="vtt" else "application/octet-stream","transcript."+kind)
                    else:
                        allowed = {"index.html","app.js","styles.css","light-box.js","capture.js","pcm-worklet.js","emotion.js"}
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
                    if self.path == "/api/palette":
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
                        with service.control_lock, service.lock:
                            if service.engine.running:
                                self.respond(409,{"error":"Stop the current audio session before starting browser capture."});return
                            cursor = service.id
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
                            if self.path=="/api/stop":service.engine.stop()
                            else:service.engine.pause(bool(options.get("paused")))
                        self.respond(200,{"ok":True})
                    else:self.respond(404,{"error":"Not found."})
                except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:
                    self.respond(400,{"error":str(error)})

            def log_message(self,*args):pass

        self.server = ThreadingHTTPServer(("127.0.0.1",self.port),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        if self.owns_engine:
            threading.Thread(target=self.drain,daemon=True).start()
        return self.url

    def drain(self):
        import queue
        while self.server is not None:
            try:self.engine.events.get(timeout=.2)
            except queue.Empty:pass

    def stop(self):
        if self.owns_engine:self.engine.stop()
        if self.server:
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
