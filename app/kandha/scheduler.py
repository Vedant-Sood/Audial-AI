"""HapticScheduler: which taps the stole plays, when, and which it drops.

Pure code: time is passed in (seconds, monotonic), nothing is threaded, nothing does I/O. The
rules come from docs/kandha/DESIGN.md section 7 and the constants from the shared pattern table:

- priority: speaker change > voice starts again > queue feedback > tone cue > silence;
- a speaker tap pre-empts a cue in progress; a cue arriving during a tap waits for the tap;
- a speaker decision pre-empts a "voice starts again" tap, and that tap never follows a speaker
  tap that is playing or waiting: one start, one seat tap;
- anything older than `stale_after_s` (1.5 s) is dropped, never played late; a waiting intent
  that will be that old before the running pattern ends gives way to a newer one;
- at most one tone cue every `cue_gap_s` (3 s), the same cue kind every `cue_same_kind_gap_s` (8 s);
- modes decide which intents exist at all; do-not-disturb keeps only queue feedback;
- a voice without a seat gets one tap at the front; the same voice is never tapped twice in a row.
"""
from dataclasses import dataclass, field, replace

from app.kandha.patterns import ZONE_ORDER, table as shared_table, zone_mask
from app.kandha.protocol import HapticCommand

CUES = ("drop", "rise", "hesitation")
INTENT_KINDS = ("speaker", "new_voice", "voice_resumes", "cue", "silence", "queue_ack", "queue_reminder",
                "low_battery", "connected", "test", "stop")
PRIORITY = {"speaker": 5, "new_voice": 5, "voice_resumes": 4, "queue_ack": 3, "queue_reminder": 3, "cue": 2,
            "silence": 1, "low_battery": 0, "connected": 0, "test": 9, "stop": 9}
SEAT_KINDS = ("speaker", "new_voice", "voice_resumes")
# intents whose value does not decay in 1.5 s
NEVER_STALE = {"low_battery", "connected", "test", "stop"}


@dataclass(frozen=True)
class Intent:
    kind: str
    created: float                 # monotonic seconds when the intent was raised
    voice: int | None = None
    cue: str | None = None
    zone: str | None = None        # for "test": which zone; for speaker kinds: an explicit zone override
    t: float | None = None         # audio time, kept for the session record
    new: bool = False
    pattern: str | None = None     # for "test": a pattern key other than zone_test
    repeat: int = 1
    demo: bool = False

    def __post_init__(self):
        if self.kind not in INTENT_KINDS:
            raise ValueError(f"Unknown intent kind: {self.kind}.")
        if self.kind == "cue" and self.cue not in CUES:
            raise ValueError("Cue intents need a cue of drop, rise or hesitation.")


@dataclass
class SchedulerSettings:
    mode: str = "seminar"
    dnd: bool = False
    cues: dict = field(default_factory=lambda: {"drop": True, "rise": True, "hesitation": True, "silence": True})
    seminar_cues: bool = False
    mirror: bool = False
    intensity: dict = field(default_factory=lambda: {z: 100 for z in ZONE_ORDER})   # percent per zone


@dataclass
class Played:
    command: HapticCommand
    intent: Intent
    pattern_key: str
    at: float
    until: float
    preempted: bool = False
    deferred: bool = False
    zone: str | None = None

    def as_dict(self):
        return {"seq": self.command.seq, "zones": self.command.zone_letters, "mask": self.command.zones,
                "pattern": self.pattern_key, "pattern_id": self.command.pattern, "intensity": self.command.intensity,
                "repeat": self.command.repeat, "intent": self.intent.kind, "cue": self.intent.cue, "voice": self.intent.voice,
                "zone": self.zone, "t": self.intent.t, "at": self.at, "until": self.until, "duration_ms": round((self.until - self.at) * 1000),
                "preempted": self.preempted, "deferred": self.deferred, "demo": self.intent.demo}


class HapticScheduler:
    def __init__(self, seat_lookup, settings=None, table=None):
        self.table = table or shared_table()
        self.seat_lookup = seat_lookup
        self.settings = settings or SchedulerSettings()
        rules = self.table.scheduler
        self.stale_after = float(rules["stale_after_s"])
        self.cue_gap = float(rules["cue_gap_s"])
        self.cue_same_gap = float(rules["cue_same_kind_gap_s"])
        self.seq = 0
        self.current = None            # Played, while its pattern runs
        self.pending = None            # one deferred intent (highest priority, freshest)
        self.last_cue_at = -1e9
        self.last_cue_by_kind = {}
        self.last_tapped_voice = None
        self.dropped = []              # (intent, reason) for diagnostics and tests
        self.history = []              # Played, in order

    # ------------------------------------------------------------------ mode rules
    def rules(self):
        return self.table.mode("dnd" if self.settings.dnd else self.settings.mode)

    def allowed(self, intent):
        """Whether this kind of intent exists in the current mode and settings."""
        rules = self.rules()
        kind = intent.kind
        if kind in ("test", "stop", "connected", "low_battery"):
            return True if kind != "low_battery" or not self.settings.dnd else False
        if kind in ("speaker", "new_voice", "voice_resumes"):
            return bool(rules["seat_taps"])
        if kind == "cue":
            cues = rules["cues"]
            if cues == "optional":
                cues = self.settings.seminar_cues
            return bool(cues) and bool(self.settings.cues.get(intent.cue, True))
        if kind == "silence":
            return bool(rules["silence"]) and bool(self.settings.cues.get("silence", True))
        return bool(rules["queue"])

    # ------------------------------------------------------------------ resolution
    def resolve(self, intent):
        """(pattern, zone mask, zone letter) for an intent, or None when nothing should play."""
        by = self.table.by_key
        kind = intent.kind
        if kind in ("speaker", "voice_resumes"):
            zone = intent.zone or self.seat_lookup(intent.voice)
            if zone == "me":
                return None
            if zone is None:
                return by["seat_unmapped"], zone_mask("F"), None
            return by["seat_tap"], zone_mask(zone), zone
        if kind == "new_voice":
            return by["new_voice"], zone_mask("F"), None
        if kind == "cue":
            return by[intent.cue], zone_mask("F"), None
        if kind == "silence":
            return by["silence"], zone_mask("LR"), None
        if kind == "queue_ack":
            return by["queue_ack"], zone_mask("LR"), None
        if kind == "queue_reminder":
            return by["queue_reminder"], zone_mask("LR"), None
        if kind == "low_battery":
            return by["low_battery"], zone_mask("B"), None
        if kind == "connected":
            return by["connected"], zone_mask("LR"), None
        if kind == "test":
            pattern = by[intent.pattern or "zone_test"]
            zone = intent.zone or ("F" if pattern.zones in ("seat", "any") else None)
            mask = zone_mask(zone) if zone else pattern.fixed_mask
            return pattern, mask, zone
        if kind == "stop":
            return by["stop"], 0, None
        return None

    def command_for(self, pattern, mask, repeat=1):
        self.seq = (self.seq + 1) % 256
        return HapticCommand(self.seq, mask, pattern.id, pattern.intensity, max(1, min(255, repeat)))

    # ------------------------------------------------------------------ submit / tick
    def submit(self, intent, now):
        """Offer an intent. Returns the commands that start now (0 or 1)."""
        self._expire(now)
        if intent.kind not in NEVER_STALE and now - intent.created > self.stale_after:
            return self._drop(intent, "stale")
        if not self.allowed(intent):
            return self._drop(intent, "mode")
        if intent.kind == "silence":
            # after a silence, whoever speaks next "starts": allow a tap for the same voice
            self.last_tapped_voice = None
        if intent.kind == "speaker" and intent.voice is not None and intent.voice == self.last_tapped_voice and not intent.zone:
            return self._drop(intent, "same-voice")
        if self._is_self(intent):
            return self._drop(intent, "self")
        if intent.kind == "cue":
            if now - self.last_cue_at < self.cue_gap:
                return self._drop(intent, "cue-gap")
            if now - self.last_cue_by_kind.get(intent.cue, -1e9) < self.cue_same_gap:
                return self._drop(intent, "same-cue-gap")
        if intent.kind == "stop":
            self.pending = None
            played = self._play(intent, now)
            self.current = None
            return self._started(played)
        if intent.kind == "voice_resumes" and self.pending is not None and self.pending.kind in SEAT_KINDS and not self._doomed(self.pending, now):
            # a seat tap for this start is already waiting: never a second one
            return self._drop(intent, "superseded")
        busy = self.current is not None and self.current.until > now
        if busy:
            playing = PRIORITY[self.current.intent.kind]
            mine = PRIORITY[intent.kind]
            if mine > playing or intent.kind == "test":      # a newer test always replaces an older one
                running = self.current
                played = self._play(intent, now, preempted_current=True)
                if played is not None:
                    running.preempted = True
                return self._started(played)
            if intent.kind == "silence":
                return self._drop(intent, "busy")
            if intent.kind == "voice_resumes" and self.current.intent.kind in SEAT_KINDS:
                # a seat tap for this start is already playing: never a second one
                return self._drop(intent, "superseded")
            # wait for the running pattern, keeping only the best waiting intent; one that will be
            # stale before the stole is free can never play, so it does not keep a fresher one out
            if self.pending is not None and self._doomed(self.pending, now):
                self._drop(self.pending, "stale")
                self.pending = None
            if self.pending is None or mine > PRIORITY[self.pending.kind] or (mine == PRIORITY[self.pending.kind] and intent.created >= self.pending.created):
                if self.pending is not None:
                    self._drop(self.pending, "superseded")
                self.pending = intent
            else:
                self._drop(intent, "busy")
            return []
        return self._started(self._play(intent, now))

    def tick(self, now):
        """Release a deferred intent once the stole is free. Returns the commands that start now."""
        self._expire(now)
        if self.pending is None or (self.current is not None and self.current.until > now):
            return []
        intent, self.pending = self.pending, None
        if intent.kind not in NEVER_STALE and now - intent.created > self.stale_after:
            return self._drop(intent, "stale")
        # the wearer may have changed the mode or marked the voice "me" while it waited
        if not self.allowed(intent):
            return self._drop(intent, "mode")
        if self._is_self(intent):
            return self._drop(intent, "self")
        if intent.kind == "cue" and (now - self.last_cue_at < self.cue_gap or now - self.last_cue_by_kind.get(intent.cue, -1e9) < self.cue_same_gap):
            return self._drop(intent, "cue-gap")
        return self._started(self._play(intent, now, deferred=True))

    def _doomed(self, intent, now):
        """Whether a waiting intent will be stale by the time the running pattern ends."""
        free_at = max(now, self.current.until) if self.current is not None else now
        return intent.kind not in NEVER_STALE and free_at - intent.created > self.stale_after

    def _is_self(self, intent):
        return intent.kind in SEAT_KINDS and intent.voice is not None and self.seat_lookup(intent.voice) == "me"

    @staticmethod
    def _started(played):
        return [played] if played is not None else []

    def _expire(self, now):
        if self.current is not None and self.current.until <= now:
            self.current = None

    def _play(self, intent, now, preempted_current=False, deferred=False):
        resolved = self.resolve(intent)
        if resolved is None:
            # nothing to play (the wearer's own voice): record it instead of failing the caller
            self._drop(intent, "self")
            return None
        pattern, mask, zone = resolved
        if intent.kind in SEAT_KINDS and self.pending is not None and self.pending.kind == "voice_resumes":
            # a resume still waiting gives way to the seat tap starting now
            self._drop(self.pending, "superseded")
            self.pending = None
        command = self.command_for(pattern, mask, intent.repeat)
        played = Played(command, intent, pattern.key, now, now + pattern.duration_ms * max(1, command.repeat) / 1000.0 / max(1, pattern.repeat),
                        deferred=deferred, zone=zone)
        self.current = played
        self.history.append(played)
        if intent.kind == "cue":
            self.last_cue_at = now
            self.last_cue_by_kind[intent.cue] = now
        if intent.kind in SEAT_KINDS:
            self.last_tapped_voice = intent.voice
        return played

    def _drop(self, intent, reason):
        self.dropped.append((intent, reason))
        if len(self.dropped) > 500:
            del self.dropped[:250]
        return []

    def reset_session(self):
        """A new listening session: forget the last tapped voice and cue timing, keep settings."""
        self.current = None
        self.pending = None
        self.last_cue_at = -1e9
        self.last_cue_by_kind = {}
        self.last_tapped_voice = None
        self.history = []
        self.dropped = []


class QueueTracker:
    """"I want to speak" timing: acknowledgement on toggle, a reminder after a long wait."""

    def __init__(self, table=None):
        rules = (table or shared_table()).scheduler
        self.default_s = int(rules["queue_reminder_default_s"])
        self.min_gap = float(rules["queue_reminder_min_gap_s"])
        self.reminder_s = self.default_s
        self.on = False
        self.since = None
        self.last_reminder = None

    def set(self, on, now):
        on = bool(on)
        changed = on != self.on
        self.on = on
        self.since = now if on else None
        self.last_reminder = None
        return changed

    def waited(self, now):
        return 0.0 if not self.on else now - self.since

    def due(self, now):
        """True once per reminder interval while waiting, never more than once a minute."""
        if not self.on or self.reminder_s <= 0:
            return False
        waited = now - self.since
        if waited < self.reminder_s:
            return False
        if self.last_reminder is not None and now - self.last_reminder < max(self.min_gap, self.reminder_s):
            return False
        self.last_reminder = now
        return True
