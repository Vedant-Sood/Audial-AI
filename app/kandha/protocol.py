"""Kandha Stole Bluetooth protocol v1: byte layouts, UUIDs and the config arithmetic.

Every payload is little-endian and fixed-format (docs/kandha/PROTOCOL.md). The firmware in
firmware/kandha/ reads the same bytes; tests/test_kandha_protocol.py round-trips every one.
"""
from dataclasses import dataclass, replace
import struct

from app.kandha.patterns import ZONE_BITS, ZONE_ORDER, table

ZONE_L, ZONE_R, ZONE_B, ZONE_F = 1, 2, 4, 8
PAD_L, PAD_R, PAD_B, PAD_Q = 1, 2, 3, 4
GESTURE_TAP, GESTURE_DOUBLE, GESTURE_LONG = 1, 2, 3
PAD_NAMES = {PAD_L: "L", PAD_R: "R", PAD_B: "B", PAD_Q: "Q"}
GESTURE_NAMES = {GESTURE_TAP: "tap", GESTURE_DOUBLE: "double", GESTURE_LONG: "long"}
FLAG_MUTED, FLAG_MIRRORED, FLAG_TEST, FLAG_LOW_BATTERY, FLAG_PLAYING, FLAG_CALIBRATED = 1, 2, 4, 8, 16, 32
MAX_CUSTOM_STEPS = 16
BUILTIN_MAX = 31


def uuids():
    """Service and characteristic UUIDs from the shared table."""
    p = table().protocol
    return {"service": p["service_uuid"], **p["characteristics"]}


def name_prefix():
    return table().protocol["name_prefix"]


def _u8(value, name):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer from 0 to 255.")
    return value


@dataclass(frozen=True)
class HapticCommand:
    seq: int
    zones: int
    pattern: int
    intensity: int
    repeat: int = 1

    def __post_init__(self):
        for field in ("seq", "zones", "pattern", "intensity", "repeat"):
            _u8(getattr(self, field), field)
        if self.zones > 15:
            raise ValueError("zones is a bitmask of L=1 R=2 B=4 F=8.")

    def encode(self):
        return bytes((self.seq, self.zones, self.pattern, self.intensity, self.repeat))

    @classmethod
    def decode(cls, data):
        if len(data) != 5:
            raise ValueError("HAPTIC payloads are 5 bytes.")
        return cls(*data)

    @property
    def zone_letters(self):
        return "".join(z for z in ZONE_ORDER if self.zones & ZONE_BITS[z])


def encode_pattern_upload(pattern_id, steps):
    """PATTERNS payload: [id][n][(on_ms u16)(off_ms u16)(level u8)] x n."""
    if type(pattern_id) is not int or not BUILTIN_MAX < pattern_id <= 255:
        raise ValueError("Custom pattern ids are 32 to 255.")
    if not 1 <= len(steps) <= MAX_CUSTOM_STEPS:
        raise ValueError(f"Custom patterns have 1 to {MAX_CUSTOM_STEPS} steps.")
    out = bytearray((pattern_id, len(steps)))
    for step in steps:
        out += struct.pack("<HHB", step.on_ms, step.off_ms, step.level)
    return bytes(out)


def decode_pattern_upload(data):
    from app.kandha.patterns import Step
    if len(data) < 2 or data[1] < 1 or data[1] > MAX_CUSTOM_STEPS or len(data) != 2 + 5 * data[1]:
        raise ValueError("Malformed PATTERNS payload.")
    if data[0] <= BUILTIN_MAX:
        raise ValueError("Ids 0-31 are reserved for built-in patterns.")
    steps = [Step(*struct.unpack_from("<HHB", data, 2 + 5 * i)) for i in range(data[1])]
    return data[0], steps


@dataclass(frozen=True)
class PadInput:
    pad: int
    gesture: int

    def encode(self):
        return bytes((_u8(self.pad, "pad"), _u8(self.gesture, "gesture")))

    @classmethod
    def decode(cls, data):
        if len(data) != 2:
            raise ValueError("INPUT payloads are 2 bytes.")
        pad, gesture = data
        if pad not in PAD_NAMES or gesture not in GESTURE_NAMES:
            raise ValueError("Unknown pad or gesture.")
        return cls(pad, gesture)

    @property
    def pad_name(self):
        return PAD_NAMES[self.pad]

    @property
    def gesture_name(self):
        return GESTURE_NAMES[self.gesture]


@dataclass(frozen=True)
class StoleStatus:
    battery: int
    charging: bool
    fw_major: int
    fw_minor: int
    flags: int = 0

    def encode(self):
        return bytes((_u8(self.battery, "battery"), 1 if self.charging else 0, _u8(self.fw_major, "fw_major"),
                      _u8(self.fw_minor, "fw_minor"), _u8(self.flags, "flags")))

    @classmethod
    def decode(cls, data):
        if len(data) != 5:
            raise ValueError("STATUS payloads are 5 bytes.")
        battery = min(100, data[0])
        return cls(battery, bool(data[1]), data[2], data[3], data[4])

    @property
    def low(self):
        return bool(self.flags & FLAG_LOW_BATTERY) or self.battery <= int(table().scheduler["low_battery_percent"])

    def as_dict(self):
        return {"battery": self.battery, "charging": self.charging, "firmware": f"{self.fw_major}.{self.fw_minor}",
                "muted": bool(self.flags & FLAG_MUTED), "mirrored": bool(self.flags & FLAG_MIRRORED),
                "test_mode": bool(self.flags & FLAG_TEST), "low_battery": self.low,
                "playing": bool(self.flags & FLAG_PLAYING), "calibrated": bool(self.flags & FLAG_CALIBRATED)}


@dataclass(frozen=True)
class StoleConfig:
    scale_l: int = 255
    scale_r: int = 255
    scale_b: int = 255
    scale_f: int = 255
    mute: bool = False
    mirror: bool = False
    test_mode: bool = False

    def encode(self):
        return bytes((_u8(self.scale_l, "scale_l"), _u8(self.scale_r, "scale_r"), _u8(self.scale_b, "scale_b"),
                      _u8(self.scale_f, "scale_f"), 1 if self.mute else 0, 1 if self.mirror else 0, 1 if self.test_mode else 0))

    @classmethod
    def decode(cls, data):
        if len(data) != 7:
            raise ValueError("CONFIG payloads are 7 bytes.")
        return cls(data[0], data[1], data[2], data[3], bool(data[4]), bool(data[5]), bool(data[6]))

    @property
    def scales(self):
        return {"L": self.scale_l, "R": self.scale_r, "B": self.scale_b, "F": self.scale_f}

    @classmethod
    def from_settings(cls, intensity, mirror=False, mute=False, test_mode=False):
        """Per-zone intensity in percent (0-100) from settings -> device scales."""
        scale = lambda z: max(0, min(255, round(int(intensity.get(z, 100)) * 255 / 100)))
        return cls(scale("L"), scale("R"), scale("B"), scale("F"), bool(mute), bool(mirror), bool(test_mode))


def mirror_mask(mask):
    """Swap L and R in a zone mask."""
    swapped = mask & ~(ZONE_L | ZONE_R)
    if mask & ZONE_L:
        swapped |= ZONE_R
    if mask & ZONE_R:
        swapped |= ZONE_L
    return swapped


def apply_config(command, config):
    """What the firmware does with a HAPTIC command under the current CONFIG (mute and mirror).

    Per-zone scales are applied per zone by the pattern engine, so they are not folded here.
    """
    zones = mirror_mask(command.zones) if config.mirror else command.zones
    intensity = 0 if config.mute else command.intensity
    return replace(command, zones=zones, intensity=intensity)
