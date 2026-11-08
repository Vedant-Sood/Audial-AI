"""VirtualStole: the on-screen stole. Same bytes, same config arithmetic, same timing as the real one;
the levels leave out the firmware's 60/255 motor floor and 15 ms spin-up kick (PROTOCOL.md).

The scheduler writes the five HAPTIC bytes to every device it has; the virtual stole decodes
them exactly as the firmware would and runs a PatternPlayer so the page can draw each zone's
level at any moment. Its four pads can be pressed from the screen and produce the same INPUT
payloads the real pads do. It reports a STATUS like a real stole (battery 100 %, firmware
"virtual").
"""
import time

from app.kandha.patterns import PatternPlayer, mask_zones, table as shared_table
from app.kandha.protocol import (FLAG_MIRRORED, FLAG_MUTED, FLAG_PLAYING, FLAG_TEST, HapticCommand, PadInput, StoleConfig,
                                 StoleStatus, decode_pattern_upload)


class VirtualStole:
    name = "Virtual stole"
    address = "virtual"
    firmware = (0, 1)

    def __init__(self, table=None, clock=time.monotonic, on_event=None):
        self.table = table or shared_table()
        self.clock = clock
        self.on_event = on_event or (lambda kind, data: None)
        self.config = StoleConfig()
        self.player = PatternPlayer(self.table, self.config)
        self.custom = {}
        self.last_seq = None
        self.received = []        # (monotonic seconds, characteristic, bytes)

    @property
    def connected(self):
        return True

    def now_ms(self):
        return int(self.clock() * 1000)

    def write_haptic(self, data):
        """A HAPTIC write. Returns what is now playing (for the page) or None for a stop / duplicate."""
        command = HapticCommand.decode(bytes(data))
        now_ms = self.now_ms()
        self.received.append((self.clock(), "haptic", bytes(data)))
        if command.seq == self.last_seq:
            return None                      # a duplicate delivery, as the firmware treats it
        self.last_seq = command.seq
        pattern = self.table.by_id.get(command.pattern) or self.custom.get(command.pattern)
        segments = self.player.start(command, now_ms, pattern=pattern)
        if not segments:
            self.on_event("haptic", {"device": "virtual", "seq": command.seq, "stopped": True})
            return None
        effective = self.player.current["command"]      # after mute / mirror
        # zones, mask and intensity as played (after CONFIG); each segment's level has the
        # zone's intensity scale applied, as the motor would run it before the firmware's
        # 60/255 floor and 15 ms spin-up kick
        played = {"device": "virtual", "seq": command.seq, "zones": "".join(mask_zones(effective.zones)), "mask": effective.zones,
                  "pattern_id": command.pattern, "pattern": pattern.key if hasattr(pattern, "key") else f"custom-{command.pattern}",
                  "intensity": effective.intensity, "repeat": command.repeat,
                  "duration_ms": self.player.current["end"] - now_ms,
                  "segments": [{"zone": z, "start_ms": s - now_ms, "end_ms": e - now_ms, "level": lvl} for z, s, e, lvl in segments]}
        self.on_event("haptic", played)
        return played

    def write_config(self, data):
        self.config = StoleConfig.decode(bytes(data))
        self.player.config = self.config
        self.received.append((self.clock(), "config", bytes(data)))
        self.on_event("stole_status", self.status().as_dict() | {"device": "virtual"})

    def write_patterns(self, data):
        from app.kandha.patterns import Pattern
        pattern_id, steps = decode_pattern_upload(bytes(data))
        self.custom[pattern_id] = Pattern(pattern_id, f"custom-{pattern_id}", f"Custom {pattern_id}", "", "any", "system", 255, 1, tuple(steps))
        self.received.append((self.clock(), "patterns", bytes(data)))

    def status(self):
        flags = (FLAG_MUTED if self.config.mute else 0) | (FLAG_MIRRORED if self.config.mirror else 0) | (FLAG_TEST if self.config.test_mode else 0)
        if self.player.busy_until() is not None and self.player.busy_until() > self.now_ms():
            flags |= FLAG_PLAYING
        return StoleStatus(100, False, self.firmware[0], self.firmware[1], flags)

    def press(self, pad, gesture):
        """A pad pressed on the screen: the same two bytes the real stole would notify."""
        payload = PadInput(pad, gesture).encode()
        self.on_event("input", {"device": "virtual", "raw": payload.hex(), "pad": PadInput.decode(payload).pad_name,
                                "gesture": PadInput.decode(payload).gesture_name})
        return payload

    def levels(self, now=None):
        return self.player.levels(self.now_ms() if now is None else int(now * 1000))

    def timeline(self):
        return self.player.timeline()

    def snapshot(self):
        busy = self.player.busy_until()
        return {"device": "virtual", "connected": True, "status": self.status().as_dict(), "config": self.config.encode().hex(),
                "playing": bool(busy and busy > self.now_ms()), "levels": self.levels()}
