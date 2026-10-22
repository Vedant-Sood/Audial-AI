"""The Kandha tap language: the shared pattern table and a simulation of the stole's player.

`PatternTable` loads browser/sanket/kandha-patterns.json. `PatternPlayer` mirrors the firmware's
pattern engine (firmware/kandha/pattern_engine.h): the same steps, the same replacement rule,
the same intensity arithmetic. The virtual stole and the parity tests use it.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from app.utils.paths import project_root

ZONE_ORDER = ("L", "R", "B", "F")
PRIORITIES = ("speaker", "queue", "cue", "silence", "system")


def table_path():
    return project_root() / "browser" / "sanket" / "kandha-patterns.json"


@dataclass(frozen=True)
class Step:
    on_ms: int
    off_ms: int
    level: int

    def __post_init__(self):
        if not (0 <= self.on_ms <= 65535 and 0 <= self.off_ms <= 65535 and 0 <= self.level <= 255):
            raise ValueError("Pattern steps need on_ms/off_ms in 0-65535 and a level in 0-255.")


@dataclass(frozen=True)
class Pattern:
    id: int
    key: str
    name: str
    meaning: str
    zones: str           # "seat", "any", "none" or a zone combination such as "F" or "LR"
    priority: str
    intensity: int
    repeat: int
    steps: tuple

    @property
    def duration_ms(self):
        return self.repeat * sum(s.on_ms + s.off_ms for s in self.steps)

    @property
    def fixed_mask(self):
        """The zone mask for patterns with fixed zones, else 0."""
        return 0 if self.zones in {"seat", "any", "none"} else zone_mask(self.zones)


class PatternTable:
    def __init__(self, data):
        if data.get("version") != 1:
            raise ValueError("Unsupported Kandha pattern table version.")
        self.data = data
        self.protocol = data["protocol"]
        self.zone_bits = {k: int(v["bit"]) for k, v in data["zones"].items()}
        self.zone_names = {k: v["name"] for k, v in data["zones"].items()}
        self.pads = {k: int(v) for k, v in data["pads"].items()}
        self.gestures = {k: int(v) for k, v in data["gestures"].items()}
        self.scheduler = data["scheduler"]
        self.modes = data["modes"]
        self.tutorial_order = list(data["tutorial_order"])
        self.patterns = []
        low, high = data["protocol"]["builtin_pattern_ids"]
        for item in data["patterns"]:
            steps = tuple(Step(int(s["on_ms"]), int(s["off_ms"]), int(s["level"])) for s in item["steps"])
            if len(steps) > int(data["protocol"]["max_pattern_steps"]):
                raise ValueError(f"Pattern {item['key']} has too many steps.")
            if not low <= int(item["id"]) <= high:
                raise ValueError(f"Pattern {item['key']} is outside the built-in id range.")
            if item["priority"] not in PRIORITIES:
                raise ValueError(f"Pattern {item['key']} has an unknown priority.")
            self.patterns.append(Pattern(int(item["id"]), item["key"], item["name"], item["meaning"], item["zones"],
                                         item["priority"], int(item["intensity"]), max(1, int(item["repeat"])), steps))
        self.by_id = {p.id: p for p in self.patterns}
        self.by_key = {p.key: p for p in self.patterns}
        if len(self.by_id) != len(self.patterns) or len(self.by_key) != len(self.patterns):
            raise ValueError("Pattern ids and keys must be unique.")
        for key in self.tutorial_order:
            if key not in self.by_key:
                raise ValueError(f"Tutorial names an unknown pattern: {key}.")

    @classmethod
    def load(cls, path=None):
        return cls(json.loads(Path(path or table_path()).read_text(encoding="utf-8")))

    def mode(self, name):
        if name not in self.modes:
            raise ValueError(f"Unknown mode: {name}.")
        return self.modes[name]


_TABLE = None


def table():
    """The shared table, loaded once."""
    global _TABLE
    if _TABLE is None:
        _TABLE = PatternTable.load()
    return _TABLE


ZONE_BITS = {"L": 1, "R": 2, "B": 4, "F": 8}


def zone_mask(zones):
    """'LR' -> 3, 'F' -> 8. Letters outside L/R/B/F are an error."""
    mask = 0
    for letter in zones:
        if letter not in ZONE_BITS:
            raise ValueError(f"Unknown zone letter: {letter}.")
        mask |= ZONE_BITS[letter]
    return mask


def mask_zones(mask):
    return [z for z in ZONE_ORDER if mask & ZONE_BITS[z]]


def effective_level(level, intensity, scale=255):
    """The duty the motor sees: level x intensity / 255 x zone scale / 255 (firmware arithmetic)."""
    return (level * intensity * scale) // (255 * 255)


class PatternPlayer:
    """Simulates the stole's pattern engine with millisecond timing.

    `start(command, now_ms)` replaces whatever is playing. `levels(now_ms)` gives the duty per
    zone at that moment. `timeline()` lists what was played as (zone letter, start, end, level),
    which the parity tests compare between the virtual stole and the firmware simulation.
    """

    def __init__(self, table_=None, config=None):
        self.table = table_ or table()
        self.config = config
        self.current = None
        self.segments = []

    def start(self, command, now_ms, pattern=None):
        from app.kandha.protocol import apply_config
        if self.config is not None:
            command = apply_config(command, self.config)
        self._truncate(now_ms)
        pattern = pattern or self.table.by_id.get(command.pattern)
        if pattern is None or command.pattern == 0 or command.zones == 0 or not pattern.steps:
            self.current = None
            return []
        scales = self.config.scales if self.config is not None else {z: 255 for z in ZONE_ORDER}
        zones = mask_zones(command.zones)
        t = now_ms
        new = []
        for _ in range(max(1, command.repeat)):
            for step in pattern.steps:
                if step.on_ms:
                    for z in zones:
                        new.append([z, t, t + step.on_ms, effective_level(step.level, command.intensity, scales[z])])
                t += step.on_ms + step.off_ms
        self.current = {"command": command, "pattern": pattern, "start": now_ms, "end": t}
        self.segments.extend(new)
        return new

    def stop(self, now_ms):
        self._truncate(now_ms)
        self.current = None

    def _truncate(self, now_ms):
        kept = []
        for seg in self.segments:
            if seg[1] >= now_ms:
                continue
            if seg[2] > now_ms:
                seg[2] = now_ms
            kept.append(seg)
        self.segments = kept
        if self.current and self.current["end"] <= now_ms:
            self.current = None

    def busy_until(self):
        return self.current["end"] if self.current else None

    def levels(self, now_ms):
        out = {z: 0 for z in ZONE_ORDER}
        for z, start, end, level in self.segments:
            if start <= now_ms < end:
                out[z] = max(out[z], level)
        return out

    def timeline(self):
        return [tuple(seg) for seg in self.segments]
