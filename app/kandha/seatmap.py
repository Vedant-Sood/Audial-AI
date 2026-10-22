"""SeatMap: which shoulder each session-only voice belongs to, saved rooms, and SeatSource.

Voices are the engine's session-only slots ("Voice 1", "Voice 2"); the map links them to the
zones L, R, B, F. Pads, keys and drag-and-drop all end in `assign()`. Saved rooms store the zone
for the first, second, third voice to appear (decision 0006), never who those people are.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Protocol

from app.kandha.patterns import table as shared_table
from app.kandha.protocol import GESTURE_DOUBLE, GESTURE_LONG, GESTURE_TAP, PAD_B, PAD_L, PAD_Q, PAD_R
from app.utils.paths import atomic_json, data_root

ZONES = ("L", "R", "B", "F")
PAD_ZONE = {PAD_L: "L", PAD_R: "R", PAD_B: "B"}
# nominal bearing of each zone from the wearer, degrees clockwise from straight ahead
ZONE_ANGLE = {"F": 0.0, "R": 90.0, "B": 180.0, "L": 270.0}


def angle_to_zone(degrees):
    """Bearing (clockwise from ahead) -> zone: front +-45, right 45-135, behind 135-225, left 225-315."""
    a = float(degrees) % 360.0
    if a < 45 or a >= 315:
        return "F"
    if a < 135:
        return "R"
    if a < 225:
        return "B"
    return "L"


class SeatSource(Protocol):
    """A future direction-of-arrival source (a microphone array): one bearing per voice."""

    def angles(self) -> dict:
        """{voice id: degrees clockwise from straight ahead}; omit voices it cannot place."""


class ManualSeatSource:
    """The only SeatSource today: bearings derived from the manual seat map."""

    def __init__(self, seat_map):
        self.seat_map = seat_map

    def angles(self):
        return {voice: ZONE_ANGLE[zone] for voice, zone in self.seat_map.voices().items() if zone}


@dataclass
class Room:
    name: str
    slots: list
    mode: str = "seminar"
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def as_dict(self):
        return {"name": self.name, "slots": list(self.slots), "mode": self.mode, "updated": self.updated}


class SeatMap:
    def __init__(self, store_path=None, table=None, mode="seminar"):
        self.table = table or shared_table()
        self.window_s = float(self.table.scheduler["seat_assign_window_s"])
        self.store_path = Path(store_path) if store_path else data_root() / "kandha" / "rooms.json"
        self.mode = mode
        self.seats = {}             # voice id -> zone or None
        self.order = []             # voice ids in order of appearance
        self.pending = None         # (voice, deadline) assignment window after a new voice
        self.rooms = {}
        self.last_room = None
        self.loaded_room = None     # the Room whose slots pre-assign voices this session
        self.changes = []           # (voice, zone, source) this session
        self._load_store()

    # ------------------------------------------------------------------ voices and zones
    def zone_for(self, voice):
        return self.seats.get(voice)

    def voices(self):
        return dict(self.seats)

    def assign(self, voice, zone, source="screen"):
        if type(voice) is not int or voice < 1:
            raise ValueError("Voices are positive integers.")
        if zone is not None and zone not in ZONES:
            raise ValueError("Zones are L, R, B or F.")
        if voice not in self.order:
            self.order.append(voice)
        changed = self.seats.get(voice) != zone
        self.seats[voice] = zone
        if changed:
            self.changes.append((voice, zone, source))
        if self.pending and self.pending[0] == voice:
            self.pending = None
        return changed

    def clear(self, voice, source="screen"):
        return self.assign(voice, None, source) if voice in self.seats else False

    def new_voice(self, voice, now):
        """A voice appeared: pre-assign from the loaded room or the mode default, open the pad window."""
        if voice not in self.order:
            self.order.append(voice)
        index = self.order.index(voice)
        zone = None
        if self.loaded_room and index < len(self.loaded_room.slots):
            zone = self.loaded_room.slots[index]
            zone = zone if zone in ZONES else None
        if zone is None:
            zone = self.default_for_mode(index)
        self.seats.setdefault(voice, None)
        if zone is not None and self.seats[voice] is None:
            self.seats[voice] = zone
            self.changes.append((voice, zone, "room" if self.loaded_room else "mode-default"))
        self.pending = (voice, now + self.window_s)
        return self.seats[voice]

    def default_for_mode(self, index):
        rules = self.table.mode(self.mode)
        default = rules.get("default_partner_zone")
        # practicum: the partner is usually in front; the wearer's own voice (if it appears) stays unmapped
        return default if default and index == 1 else None

    def window_open(self, now):
        return self.pending is not None and now <= self.pending[1]

    def on_pad(self, pad, gesture, now, current_voice=None):
        """A stole pad gesture. Returns {'action', 'voice', 'zone'} or None when nothing applies."""
        if pad == PAD_Q:
            return None  # queue pads are the service's business
        zone = PAD_ZONE.get(pad)
        if zone is None:
            return None
        if gesture == GESTURE_TAP:
            if self.window_open(now):
                voice = self.pending[0]
                self.assign(voice, zone, "pad")
                return {"action": "assign-new", "voice": voice, "zone": zone}
            self.pending = None
            return {"action": "no-window", "voice": None, "zone": zone}
        if gesture == GESTURE_DOUBLE:
            if current_voice is None:
                return {"action": "no-current", "voice": None, "zone": zone}
            self.assign(current_voice, zone, "pad")
            return {"action": "reassign-current", "voice": current_voice, "zone": zone}
        if gesture == GESTURE_LONG:
            if current_voice is None:
                return {"action": "no-current", "voice": None, "zone": zone}
            self.clear(current_voice, "pad")
            return {"action": "clear-current", "voice": current_voice, "zone": None}
        return None

    def merge(self, keep, drop):
        """Two colours turned out to be one person: keep the first voice's seat unless it has none."""
        if drop in self.seats:
            if self.seats.get(keep) is None and self.seats[drop] is not None:
                self.seats[keep] = self.seats[drop]
            del self.seats[drop]
        if drop in self.order:
            self.order.remove(drop)
        if keep not in self.order:
            self.order.append(keep)

    def reset(self, keep_room=True):
        self.seats = {}
        self.order = []
        self.pending = None
        self.changes = []
        if not keep_room:
            self.loaded_room = None

    def set_mode(self, mode):
        self.table.mode(mode)
        self.mode = mode

    # ------------------------------------------------------------------ rooms
    def _load_store(self):
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for item in data.get("rooms", []):
            try:
                room = Room(str(item["name"])[:80], [z if z in ZONES else None for z in list(item.get("slots", []))[:8]],
                            str(item.get("mode", "seminar")), str(item.get("updated", "")))
            except (KeyError, TypeError):
                continue
            if room.name:
                self.rooms[room.name] = room
        last = data.get("last_room")
        self.last_room = last if last in self.rooms else None

    def _save_store(self):
        atomic_json(self.store_path, {"version": 1, "rooms": [r.as_dict() for r in self.rooms.values()], "last_room": self.last_room})

    def list_rooms(self):
        return [r.as_dict() for r in sorted(self.rooms.values(), key=lambda r: r.updated, reverse=True)]

    def save_room(self, name):
        name = str(name or "").strip()[:80]
        if not name:
            raise ValueError("Give the room a name.")
        slots = [self.seats.get(v) for v in self.order]
        while slots and slots[-1] is None:
            slots.pop()
        room = Room(name, slots, self.mode)
        self.rooms[name] = room
        self.last_room = name
        self.loaded_room = room
        self._save_store()
        return room.as_dict()

    def load_room(self, name):
        if name not in self.rooms:
            raise ValueError("No saved room with that name.")
        room = self.rooms[name]
        self.loaded_room = room
        self.last_room = name
        # voices already heard this session take the room's slots in order of appearance
        for index, voice in enumerate(self.order):
            if index < len(room.slots) and room.slots[index] in ZONES:
                self.assign(voice, room.slots[index], "room")
        self._save_store()
        return room.as_dict()

    def delete_room(self, name):
        if name in self.rooms:
            del self.rooms[name]
            if self.last_room == name:
                self.last_room = None
            if self.loaded_room and self.loaded_room.name == name:
                self.loaded_room = None
            self._save_store()
            return True
        return False

    def snapshot(self, now=None):
        return {"seats": {str(v): z for v, z in self.seats.items()}, "order": list(self.order),
                "pending": {"voice": self.pending[0], "until_s": round(self.pending[1] - now, 2)} if (self.pending and now is not None and now <= self.pending[1]) else None,
                "rooms": self.list_rooms(), "last_room": self.last_room,
                "loaded_room": self.loaded_room.name if self.loaded_room else None, "mode": self.mode}
