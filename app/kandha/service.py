"""KandhaService: the glue between the page, the scheduler, the seat map, the queue and the stoles.

One instance lives inside BrowserService. HTTP handlers call its methods; the Bluetooth bridge
and a 20 ms ticker call back into it; every outcome is published as an event for the page's
SSE stream (`/api/kandha/stream`) and for the companion's `/api/events` poll.

Nothing here can stop captions: the Audial engine is not referenced at all.
"""
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import queue
import threading
import time

from app.kandha.bridge import SimulatedStole, StoleBridge, simulated_backend
from app.kandha.patterns import ZONE_ORDER, table as shared_table
from app.kandha.protocol import GESTURE_DOUBLE, GESTURE_LONG, GESTURE_TAP, PAD_B, PAD_L, PAD_Q, PAD_R, StoleConfig
from app.kandha.scheduler import CUES, HapticScheduler, Intent, QueueTracker, SchedulerSettings
from app.kandha.seatmap import SeatMap
from app.kandha.virtual import VirtualStole
from app.utils.paths import atomic_json, data_root

MODES = ("lecture", "seminar", "practicum")
PAD_CODES = {"L": PAD_L, "R": PAD_R, "B": PAD_B, "Q": PAD_Q}
GESTURE_CODES = {"tap": GESTURE_TAP, "double": GESTURE_DOUBLE, "long": GESTURE_LONG}
MAX_INTENTS = 50
TICK_S = 0.02
# The page numbers voices for the session and never reuses a number (New voice, joins), so a
# long session can pass 64 or any small cap; this only keeps them sane integers. Matches
# app/services/voice_view.py MAX_VOICE.
MAX_VOICE = 1_000_000
# The page and this service always run on one computer (the service listens on loopback only),
# so the page's Date.now() and time.time() read the same system clock and a batch's trip is
# time.time() at arrival minus the page's `sent`. A gap outside this range (ms) cannot be a trip
# on one clock, so it is a bad `sent`: then no trip is counted, and a bad value never drops a tap.
TRIP_RANGE_MS = (-1000.0, 600000.0)


def _default_cues():
    return {"lecture": {"drop": False, "rise": False, "hesitation": False, "silence": True},
            "seminar": {"drop": True, "rise": True, "hesitation": True, "silence": True},
            "practicum": {"drop": True, "rise": True, "hesitation": True, "silence": True}}


@dataclass
class KandhaSettings:
    mode: str = "seminar"
    dnd: bool = False
    seminar_cues: bool = False                  # the master switch for tone cues in Seminar mode
    cues_by_mode: dict = field(default_factory=_default_cues)
    mirror: bool = False
    intensity: dict = field(default_factory=lambda: {z: 100 for z in ZONE_ORDER})
    queue_reminder_s: int = 60
    use_last_layout: bool = True
    # "simulated": the prototype's built-in stole (no radio). "bluetooth": the real bleak link,
    # prepared but untested with hardware; only for people who have a stole running the firmware.
    link: str = "simulated"

    def validate(self):
        if self.mode not in MODES:
            raise ValueError("Mode must be lecture, seminar or practicum.")
        if self.link not in ("simulated", "bluetooth"):
            raise ValueError("The stole link is simulated or bluetooth.")
        for key in ("dnd", "seminar_cues", "mirror", "use_last_layout"):
            if not isinstance(getattr(self, key), bool):
                raise ValueError(f"{key} must be true or false.")
        clean = _default_cues()
        for mode, cues in clean.items():
            given = self.cues_by_mode.get(mode, {}) if isinstance(self.cues_by_mode, dict) else {}
            for cue in cues:
                value = given.get(cue, cues[cue])
                if not isinstance(value, bool):
                    raise ValueError("Cue switches must be true or false.")
                cues[cue] = value
        self.cues_by_mode = clean
        intensity = {}
        for zone in ZONE_ORDER:
            value = self.intensity.get(zone, 100) if isinstance(self.intensity, dict) else 100
            if type(value) not in (int, float) or not 0 <= value <= 100:
                raise ValueError("Zone intensity is a percentage from 0 to 100.")
            intensity[zone] = int(value)
        self.intensity = intensity
        if type(self.queue_reminder_s) is not int or not 0 <= self.queue_reminder_s <= 600:
            raise ValueError("The queue reminder is 0 (off) to 600 seconds.")
        return self

    @classmethod
    def load(cls, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__}).validate()
        except (OSError, ValueError, TypeError):
            pass
        return cls()

    def save(self, path):
        atomic_json(path, asdict(self.validate()))

    def scheduler_settings(self):
        cues = dict(self.cues_by_mode.get(self.mode, _default_cues()["seminar"]))
        return SchedulerSettings(mode=self.mode, dnd=self.dnd, cues=cues, seminar_cues=self.seminar_cues, mirror=self.mirror,
                                 intensity=dict(self.intensity))

    def stole_config(self):
        return StoleConfig.from_settings(self.intensity, mirror=self.mirror, mute=self.dnd and False)


class KandhaService:
    def __init__(self, publish=None, home=None, backend=None, table=None, clock=time.monotonic, start_bridge=True, ticker=True):
        self.table = table or shared_table()
        self.clock = clock
        self.home = Path(home) if home else data_root() / "kandha"
        self.home.mkdir(parents=True, exist_ok=True)
        self.publish_outer = publish or (lambda kind, data: None)
        self.settings = KandhaSettings.load(self.home / "settings.json")
        self.lock = threading.RLock()
        self.subscribers = []
        self.stopping = threading.Event()
        self.scheduler = HapticScheduler(self._seat_lookup, self.settings.scheduler_settings(), self.table)
        self.seats = SeatMap(store_path=self.home / "rooms.json", table=self.table, mode=self.settings.mode)
        self.queue = QueueTracker(self.table)
        self.queue.reminder_s = self.settings.queue_reminder_s
        self.virtual = VirtualStole(self.table, clock=clock, on_event=self._virtual_event)
        self.virtual.write_config(self.settings.stole_config().encode())
        self.current_voice = None
        self.session_started = None
        self.played = []                  # recent dispatched taps for diagnostics
        self.latency_ms = []              # page intent raised -> dispatch
        self.bridge = None
        self.backend_given = backend
        self.start_bridge = start_bridge
        if start_bridge:
            self._start_bridge()
        self.ticker = None
        if ticker:
            self.ticker = threading.Thread(target=self._tick_loop, name="kandha-ticker", daemon=True)
            self.ticker.start()

    def _backend(self):
        if self.backend_given is not None:
            return self.backend_given
        if self.settings.link == "bluetooth":
            from app.kandha.bridge import BleakBackend
            return BleakBackend()
        return simulated_backend(self.table)

    def _start_bridge(self):
        backend = self._backend()
        store = self.home / ("stole.json" if getattr(backend, "name", "") == "bleak" else "stole-simulated.json")
        # every stole_state from this bridge says which link it is, so the page never keeps the
        # previous link's kind after a switch
        link = {"backend": getattr(backend, "name", "?"), "simulated": _simulated_in(backend) is not None}
        self.bridge = StoleBridge(lambda kind, data: self._bridge_event(kind, data, link), backend=backend, store_path=store, table=self.table)
        self.bridge.link.config = self.settings.stole_config()
        self.bridge.start()

    def _restart_bridge(self):
        if not self.start_bridge:
            return
        if self.bridge is not None:
            try:
                self.bridge.stop()
            except Exception:
                pass
            self.bridge = None
        self._start_bridge()
        self.publish("stole_state", self._stole_snapshot())

    def _stole_snapshot(self):
        if self.bridge is None:
            return {"state": "unavailable", "paired": None, "simulated": False}
        return self.bridge.snapshot() | {"simulated": self.simulated_stole is not None}

    @property
    def simulated_stole(self):
        return _simulated_in(self.bridge.backend if self.bridge is not None else None)

    def simulate(self, action, value=None):
        stole = self.simulated_stole
        if stole is None:
            raise ValueError("Simulation needs the simulated stole link (Settings).")
        if action == "press":
            if not isinstance(value, dict) or value.get("pad") not in PAD_CODES or value.get("gesture") not in GESTURE_CODES:
                raise ValueError("Pads are L, R, B, Q; gestures are tap, double, long.")
            value = (PAD_CODES[value["pad"]], GESTURE_CODES[value["gesture"]])
        elif action == "battery":
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError("Battery is 0 to 100.")
        elif action == "charging":
            value = bool(value)
        elif action != "out_of_range":
            raise ValueError("Simulations are out_of_range, battery, charging or press.")
        return stole.simulate(action, value)

    # ----------------------------------------------------------------- events
    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def publish(self, kind, data):
        payload = {**data, "kind": kind}      # the event kind always wins over a record's own fields
        with self.lock:
            subscribers = list(self.subscribers)
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass
        try:
            self.publish_outer("kandha", payload)
        except Exception:
            pass

    def _virtual_event(self, kind, data):
        if kind == "input":
            self._pad(data["pad"], data["gesture"], "virtual")
        # haptic events from the virtual stole are reported by dispatch(), which merges what it played

    def _bridge_event(self, kind, data, link=None):
        if kind == "input":
            self._pad(data["pad"], data["gesture"], "stole")
            return
        if kind == "low_battery":
            self.submit(Intent("low_battery", created=self.clock()))
        elif kind == "stole_connected":
            self.submit(Intent("connected", created=self.clock()))
        elif kind == "stole_state" and link:
            data = data | link
        self.publish(kind, data)

    # ----------------------------------------------------------------- scheduling
    def _seat_lookup(self, voice):
        return self.seats.zone_for(voice) if voice is not None else None

    def submit(self, intent):
        now = self.clock()
        with self.lock:
            commands = self.scheduler.submit(intent, now)
            played = [self.dispatch(p) for p in commands]
        return played

    def dispatch(self, played, from_page=False):
        data = played.command.encode()
        shown = self.virtual.write_haptic(data)
        device = "virtual"
        if self.bridge is not None and self.bridge.connected:
            self.bridge.write_haptic(data)
            device = "stole"
        record = played.as_dict() | {"device": device, "wall_ms": round(time.time() * 1000)}
        # What the stole plays, from the virtual stole that decoded these same bytes under the
        # same CONFIG as the real one: zones after mirror, the intensity after mute, and each
        # step with its per-zone level. The page and the session record show this, not the
        # scheduler's command, which is kept as command_zones.
        record["command_zones"] = record["zones"]
        record["segments"] = []
        if shown is not None:
            record.update(zones=shown["zones"], mask=shown["mask"], intensity=shown["intensity"],
                          duration_ms=shown["duration_ms"], segments=shown["segments"])
        if from_page:
            # the intent's whole age on this service's clock: its time on the page, the trip here
            # (see _trip_ms) and any wait in the scheduler
            latency = (self.clock() - played.intent.created) * 1000
            if math.isfinite(latency) and -1000 < latency < 60000:
                record["app_latency_ms"] = round(latency, 1)
                self.latency_ms.append(round(latency, 1))
                if len(self.latency_ms) > 500:
                    del self.latency_ms[:250]
        self.played.append(record)
        if len(self.played) > 500:
            del self.played[:250]
        self.publish("haptic", record)
        return record

    def _tick_loop(self):
        while not self.stopping.wait(TICK_S):
            try:
                self.tick()
            except Exception:
                pass

    def tick(self):
        now = self.clock()
        with self.lock:
            released = [self.dispatch(p) for p in self.scheduler.tick(now)]
            if self.queue.due(now):
                released += [self.dispatch(p) for p in self.scheduler.submit(Intent("queue_reminder", created=now), now)]
                self.publish("queue", {"on": True, "waited_s": round(self.queue.waited(now)), "reminder": True})
            # the 6 s seat window after a new voice ran out with no pad tap: say so, so every open
            # page drops its "waiting for a seat" highlight (a tap now gets "no-window" anyway)
            if self.seats.pending is not None and not self.seats.window_open(now):
                voice = self.seats.pending[0]
                self.seats.pending = None
                self.publish("seat", {"voice": voice, "source": "seat-window", "action": "window-closed", "pending": None,
                                      "seats": self.seats.snapshot(now)["seats"]})
        return released

    # ----------------------------------------------------------------- page API
    def intents(self, batch, current=None):
        """A batch of intents from the page: validate, resolve seats, schedule, dispatch."""
        if not isinstance(batch, list) or len(batch) > MAX_INTENTS:
            raise ValueError(f"Send a list of at most {MAX_INTENTS} intents.")
        if current is not None:
            self.current_voice = _voice(current)
        now = self.clock()
        arrived_ms = time.time() * 1000
        played, accepted = [], 0
        for raw in batch:
            intent = self._clean_intent(raw, now, arrived_ms)
            accepted += 1
            with self.lock:
                if intent.kind == "new_voice":
                    zone = self.seats.new_voice(intent.voice, now)
                    self.publish("seat", {"voice": intent.voice, "zone": zone, "source": "new-voice", "window_s": self.seats.window_s,
                                          "pending": self.seats.snapshot(now)["pending"]})
                if intent.kind in ("speaker", "voice_resumes", "new_voice") and intent.voice is not None:
                    self.current_voice = intent.voice
                for p in self.scheduler.submit(intent, now):
                    played.append(self.dispatch(p, from_page=True))
        return {"accepted": accepted, "played": played, "dropped": len(self.scheduler.dropped)}

    @staticmethod
    def _trip_ms(gap):
        """How long a batch took to reach this service, in ms: time.time() at arrival minus the
        page's `sent`. Both read this computer's system clock, so the gap is the trip itself; a
        clock step moves both readings together. A gap below zero (reading jitter) counts as no
        trip, and one outside TRIP_RANGE_MS is a bad `sent` and counts as none, so such a value
        never makes taps look late. Stateless: one batch never changes how the next is measured."""
        if gap is None or not TRIP_RANGE_MS[0] <= gap <= TRIP_RANGE_MS[1]:
            return 0.0
        return max(0.0, gap)

    def _clean_intent(self, raw, now, arrived_ms):
        if not isinstance(raw, dict) or raw.get("kind") not in ("speaker", "new_voice", "voice_resumes", "cue", "silence"):
            raise ValueError("Intents are speaker, new_voice, voice_resumes, cue or silence objects.")
        kind = raw["kind"]
        voice = _voice(raw.get("voice"), allow_none=kind in ("cue", "silence"))
        cue = raw.get("cue")
        if kind == "cue" and cue not in CUES:
            raise ValueError("Unknown tone cue.")
        t = raw.get("t")
        if t is not None and (type(t) not in (int, float) or not math.isfinite(t) or t < 0):
            raise ValueError("Intent times are audio seconds.")
        age = raw.get("age_ms", 0)
        if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 600000:
            raise ValueError("age_ms is how long ago the intent was raised, in milliseconds.")
        # age_ms is how old the intent was when the page sent it, on the page's own steady clock;
        # `sent` is that moment on the system clock. Adding the trip here (see _trip_ms) means an
        # intent held up on the way is dropped as stale, never played late.
        sent = _finite(raw.get("sent"))
        trip = self._trip_ms(arrived_ms - sent if sent is not None else None)
        return Intent(kind, created=now - (age + trip) / 1000.0, voice=voice, cue=cue if kind == "cue" else None,
                      t=None if t is None else round(float(t), 3), new=bool(raw.get("new")), demo=bool(raw.get("demo")))

    def set_queue(self, on, source="screen"):
        now = self.clock()
        with self.lock:
            changed = self.queue.set(on, now)
            played = []
            if changed:
                played = [self.dispatch(p) for p in self.scheduler.submit(Intent("queue_ack", created=now), now)]
        state = {"on": self.queue.on, "source": source, "waited_s": round(self.queue.waited(now)), "changed": changed}
        self.publish("queue", state)
        return state | {"played": played}

    def _pad(self, pad_name, gesture_name, device):
        pad, gesture = PAD_CODES.get(pad_name), GESTURE_CODES.get(gesture_name)
        if pad is None or gesture is None:
            return None
        self.publish("input", {"device": device, "pad": pad_name, "gesture": gesture_name})
        if pad == PAD_Q:
            if gesture == GESTURE_LONG:
                return self.update_settings({"dnd": not self.settings.dnd}, source=device)
            return self.set_queue(not self.queue.on, source=device + "-pad")
        now = self.clock()
        with self.lock:
            result = self.seats.on_pad(pad, gesture, now, self.current_voice)
        if result:
            # pending says whether a new voice still waits for a seat (null after "no-window" or an
            # assignment), so every open page shows the same
            snap = self.seats.snapshot(now)
            self.publish("seat", result | {"source": device + "-pad", "seats": snap["seats"], "pending": snap["pending"]})
        return result

    def press_pad(self, pad_name, gesture_name):
        """A pad on the on-screen stole."""
        if pad_name not in PAD_CODES or gesture_name not in GESTURE_CODES:
            raise ValueError("Pads are L, R, B, Q; gestures are tap, double, long.")
        self.virtual.press(PAD_CODES[pad_name], GESTURE_CODES[gesture_name])
        return self.seats.snapshot(self.clock())

    def assign_seat(self, voice, zone, source="screen"):
        voice = _voice(voice)
        if zone is not None and zone not in ZONE_ORDER and zone != "me":
            raise ValueError("Zones are L, R, B, F or me.")
        now = self.clock()
        with self.lock:
            changed = self.seats.assign(voice, zone, source)
        snap = self.seats.snapshot(now)
        self.publish("seat", {"voice": voice, "zone": zone, "source": source, "changed": changed, "seats": snap["seats"],
                              "pending": snap["pending"]})
        return snap

    def merge_voices(self, keep, drop):
        with self.lock:
            self.seats.merge(_voice(keep), _voice(drop))
            if self.current_voice == drop:
                self.current_voice = keep
        return self.seats.snapshot(self.clock())

    def rooms(self, action, name=None):
        with self.lock:
            if action == "save":
                result = self.seats.save_room(name)
            elif action == "load":
                result = self.seats.load_room(name)
            elif action == "delete":
                result = {"deleted": self.seats.delete_room(name)}
            elif action == "list":
                result = {"rooms": self.seats.list_rooms(), "last_room": self.seats.last_room}
            else:
                raise ValueError("Room actions are save, load, delete or list.")
        snap = self.seats.snapshot(self.clock())
        self.publish("seat", {"source": "room-" + action, "seats": snap["seats"], "rooms": snap["rooms"], "loaded_room": snap["loaded_room"]})
        return {"result": result, "seats": snap}

    def update_settings(self, changes, source="screen"):
        if not isinstance(changes, dict):
            raise ValueError("Send a settings object.")
        allowed = set(KandhaSettings.__dataclass_fields__)
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
        data = asdict(self.settings)
        data.update(changes)
        updated = KandhaSettings(**data).validate()
        link_changed = updated.link != self.settings.link
        with self.lock:
            self.settings = updated
            self.scheduler.settings = updated.scheduler_settings()
            self.seats.set_mode(updated.mode)
            self.queue.reminder_s = updated.queue_reminder_s
            config = updated.stole_config()
            self.virtual.write_config(config.encode())
            if self.bridge is not None:
                self.bridge.write_config(config)
            updated.save(self.home / "settings.json")
        if link_changed and self.backend_given is None:
            self._restart_bridge()
        self.publish("settings", {"settings": asdict(updated), "source": source})
        return asdict(updated)

    def test(self, zone=None, pattern=None, repeat=1):
        if zone is not None and zone not in ZONE_ORDER and zone != "LR":
            raise ValueError("Zones are L, R, B, F or LR.")
        if pattern is not None and pattern not in self.table.by_key:
            raise ValueError("Unknown pattern.")
        if type(repeat) is not int or not 1 <= repeat <= 5:
            raise ValueError("Repeat 1 to 5 times.")
        intent = Intent("test", created=self.clock(), zone=zone if zone != "LR" else None, pattern=pattern, repeat=repeat)
        if zone == "LR":
            intent = Intent("test", created=self.clock(), pattern=pattern or "zone_test", repeat=repeat)
            with self.lock:
                pat = self.table.by_key[intent.pattern]
                cmd = self.scheduler.command_for(pat, 3, repeat)
                from app.kandha.scheduler import Played
                played = Played(cmd, intent, pat.key, self.clock(), self.clock() + pat.duration_ms * repeat / 1000.0)
                self.scheduler.current = played
                self.scheduler.history.append(played)
                return [self.dispatch(played)]
        return self.submit(intent)

    def stop_haptics(self):
        return self.submit(Intent("stop", created=self.clock()))

    def new_session(self, page=None):
        """Start a session. page: an opaque tag of the window that asked (it is told back in the
        "session" event, so another open Kandha window knows its own session was replaced)."""
        page = page if isinstance(page, str) and 0 < len(page) <= 64 else None
        now = self.clock()
        with self.lock:
            self.scheduler.reset_session()
            self.seats.reset(keep_room=self.settings.use_last_layout)
            if self.settings.use_last_layout and self.seats.last_room and self.seats.loaded_room is None:
                try:
                    self.seats.load_room(self.seats.last_room)
                except ValueError:
                    pass
            self.queue.set(False, now)
            self.current_voice = None
            self.session_started = now
            self.latency_ms = []
        snap = self.seats.snapshot(now)
        self.publish("session", {"state": "new", "page": page, "seats": snap["seats"], "loaded_room": snap["loaded_room"]})
        self.publish("queue", {"on": False, "source": "session", "waited_s": 0, "changed": True})
        return snap

    # ----------------------------------------------------------------- stole
    def scan(self, timeout=6.0):
        if type(timeout) not in (int, float) or (type(timeout) is float and not math.isfinite(timeout)):
            raise ValueError("Scan for a number of seconds (1 to 15).")
        if self.bridge is None:
            return []
        return self.bridge.scan(float(min(max(timeout, 1.0), 15.0)))

    def pair(self, address, name=None):
        if self.bridge is None:
            raise ValueError("Bluetooth is not available in this build.")
        if not isinstance(address, str) or not 1 <= len(address) <= 64:
            raise ValueError("Choose a stole from the scan list.")
        return self.bridge.pair(address, str(name or "")[:64])

    def forget(self):
        if self.bridge is not None:
            self.bridge.forget()
        return self.snapshot()

    # ----------------------------------------------------------------- state
    def snapshot(self):
        now = self.clock()
        latencies = list(self.latency_ms)
        return {"settings": asdict(self.settings), "modes": self.table.modes, "scheduler_rules": self.table.scheduler,
                "stole": self._stole_snapshot(),
                "virtual": self.virtual.snapshot(), "seats": self.seats.snapshot(now), "current_voice": self.current_voice,
                "queue": {"on": self.queue.on, "waited_s": round(self.queue.waited(now)), "reminder_s": self.queue.reminder_s},
                "latency_ms": {"n": len(latencies), "p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95), "max": max(latencies) if latencies else None},
                "recent": self.played[-20:], "dropped": [(i.kind, reason) for i, reason in self.scheduler.dropped[-20:]]}

    def close(self):
        self.stopping.set()
        if self.ticker is not None:
            self.ticker.join(1)
        if self.bridge is not None:
            self.bridge.stop()


def _simulated_in(backend):
    """The SimulatedStole a backend serves, if it is the prototype's simulated link."""
    for stole in getattr(backend, "stoles", {}).values():
        if isinstance(stole, SimulatedStole):
            return stole
    return None


def _finite(value):
    """value as a float when it is a finite JSON number (not true or false), else None."""
    if type(value) not in (int, float):
        return None
    try:
        value = float(value)
    except OverflowError:       # a whole number too big for a float
        return None
    return value if math.isfinite(value) else None


def _voice(value, allow_none=False):
    if value is None and allow_none:
        return None
    if type(value) is not int or not 1 <= value <= MAX_VOICE:
        raise ValueError("Voices are numbers from 1 upward.")
    return value


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]
