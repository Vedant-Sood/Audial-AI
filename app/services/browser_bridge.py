"""Authenticated extension broker: real tab metadata and owned PCM sessions."""

import base64
from collections import deque
import threading
import time
import uuid

import numpy as np
from app.audio.features import mono_resample
from app.storage.transcript import Session
from app.utils.config import PRESETS


class BrowserBridge:
    def __init__(self, service, clock=time.monotonic):
        self.service = service
        self.clock = clock
        self.lock = threading.RLock()
        self.profiles = {}
        self.commands = {}
        self.owner = None

    def snapshot(self):
        self.expire()
        with self.lock:
            return {
                "profiles": [
                    {
                        "id": name,
                        "browser": info["browser"],
                        "tabs": info["tabs"],
                        "connected": self.clock() - info["seen"] < 15,
                    }
                    for name, info in self.profiles.items()
                ],
                "capture": {k: v for k, v in self.owner.items() if k != "session_id"}
                if self.owner
                else None,
            }

    def expire(self):
        with self.lock:
            if self.owner:
                profile = self.profiles.get(self.owner["profile"])
                if not self.service.engine.running:
                    self.owner = None
                elif profile is None or self.clock() - profile["seen"] > 15:
                    self.stop(self.owner["profile"], self.owner["session_id"])
                    self.service.engine.emit(
                        "warning",
                        "Browser extension disconnected. Capture stopped; reconnect the extension to continue.",
                    )
            for name, info in list(self.profiles.items()):
                if self.clock() - info["seen"] > 60:
                    self.profiles.pop(name)
                    self.commands.pop(name, None)

    def queue_command(self, profile, tab_id):
        with self.lock:
            info = self.profiles.get(profile)
            if info is None or self.clock() - info["seen"] > 15:
                raise ValueError(
                    "The browser extension is disconnected. Open its toolbar button to reconnect."
                )
            if not any(tab["id"] == tab_id for tab in info["tabs"]):
                raise ValueError("This tab has closed. Refresh the browser list.")
            self.commands.setdefault(profile, deque(maxlen=8)).append(
                {"type": "focus-tab", "tab_id": tab_id}
            )
        return {
            "queued": True,
            "message": "Switching to the tab. Click Audial-AI in that tab's browser toolbar to grant capture permission.",
        }

    def handle(self, data):
        if not isinstance(data, dict):
            raise ValueError("Send a bridge message object.")
        profile = data.get("profile")
        if not isinstance(profile, str) or not 1 <= len(profile) <= 64:
            raise ValueError("A stable browser profile ID is required.")
        kind = data.get("type")
        with self.lock:
            if profile not in self.profiles:
                if len(self.profiles) >= 16:
                    raise ValueError("Too many connected browser profiles.")
                self.profiles[profile] = {
                    "browser": "Chromium",
                    "tabs": [],
                    "seen": self.clock(),
                }
            info = self.profiles[profile]
            info["seen"] = self.clock()
            if kind == "tabs":
                tabs = data.get("tabs")
                if not isinstance(tabs, list) or len(tabs) > 500:
                    raise ValueError("Send at most 500 browser tabs.")
                clean = []
                seen = set()
                for tab in tabs:
                    if (
                        not isinstance(tab, dict)
                        or type(tab.get("id")) is not int
                        or tab["id"] in seen
                    ):
                        raise ValueError("Tab identifiers must be unique integers.")
                    seen.add(tab["id"])
                    clean.append(
                        {
                            "id": tab["id"],
                            "window_id": int(tab.get("window_id", 0)),
                            "title": str(tab.get("title", "Untitled tab"))[:300],
                            "supported": bool(tab.get("supported")),
                            "reason": str(tab.get("reason", ""))[:300],
                            "audible": bool(tab.get("audible")),
                            "discarded": bool(tab.get("discarded")),
                        }
                    )
                info["tabs"] = clean
                info["browser"] = str(data.get("browser", "Chromium"))[:80]
                if self.owner and self.owner["profile"] == profile:
                    captured = next(
                        (tab for tab in clean if tab["id"] == self.owner["tab_id"]),
                        None,
                    )
                    if (
                        captured is None
                        or not captured["supported"]
                        or captured["discarded"]
                    ):
                        self.stop(profile, self.owner["session_id"])
                    else:
                        self.owner["title"] = captured["title"]
                return {"updated": True}
            if kind == "poll":
                commands = list(self.commands.pop(profile, ()))
                return {
                    "commands": commands,
                    "capture": dict(self.owner) if self.owner else None,
                    "engine_running": self.service.engine.running,
                    "needs_tabs": not bool(info["tabs"]),
                }
            if kind == "start":
                tab_id = data.get("tab_id")
                tab = next((tab for tab in info["tabs"] if tab["id"] == tab_id), None)
                if tab is None or not tab["supported"]:
                    raise ValueError(
                        "Choose a supported, live browser tab and invoke Audial-AI from its toolbar."
                    )
                if self.owner or self.service.engine.running:
                    raise ValueError(
                        "Stop the current capture before switching source."
                    )
                with self.service.control_lock:
                    if not self.service.engine.manager.installed(
                        PRESETS[self.service.settings.preset]["asr"]
                    ):
                        raise ValueError(
                            "Finish automatic model setup before starting browser captions."
                        )
                    self.service.engine.start("combined", source="browser")
                    self.service.session = Session(title=tab["title"])
                    self.service.session_id = uuid.uuid4().hex
                    self.owner = {
                        "profile": profile,
                        "tab_id": tab_id,
                        "title": tab["title"],
                        "session_id": self.service.session_id,
                    }
                    return dict(self.owner)
            if kind == "stop":
                self.stop(profile, data.get("session_id"))
                return {"stopped": True}
            if kind == "audio":
                if (
                    not self.owner
                    or self.owner["profile"] != profile
                    or self.owner["session_id"] != data.get("session_id")
                ):
                    raise ValueError(
                        "This audio packet belongs to a stopped or different capture session."
                    )
                encoded, rate = data.get("pcm"), data.get("sample_rate")
                if (
                    not isinstance(encoded, str)
                    or len(encoded) > 2_400_000
                    or type(rate) is not int
                    or not 8000 <= rate <= 192000
                ):
                    raise ValueError("Use bounded mono PCM packets at 8–192 kHz.")
                raw = base64.b64decode(encoded, validate=True)
                if not raw or len(raw) % 2 or len(raw) > rate * 6:
                    raise ValueError(
                        "Use nonempty PCM16 packets of at most three seconds."
                    )
                audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
                with self.service.control_lock:
                    capture = self.service.engine.capture
                    if capture is None or self.service.engine.stop_requested.is_set():
                        raise ValueError(
                            "Capture stopped while preparing the audio packet."
                        )
                    capture.feed(
                        mono_resample(audio, rate), float(data["start_seconds"])
                    )
                return {"queued": True}
            raise ValueError("Unsupported bridge command.")

    def stop(self, profile, session_id):
        if (
            self.owner
            and self.owner["profile"] == profile
            and self.owner["session_id"] == session_id
        ):
            self.service.engine.stop()
            self.owner = None
