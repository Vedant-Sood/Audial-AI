"""Where a voice comes from: GCC-PHAT over microphone pairs (decision 0027, V2_DESIGN §4.2).

One implementation for every multichannel source: a laptop's two microphones ("stereo"), a
four-microphone array ("quad", the mic pod's square), and recorded or synthetic files. The
mic pod's firmware will reimplement the same steps in C++ and must pass the same synthetic
test vectors (tests/test_kandha_direction.py).

Steps for each 85 ms frame (4,096 samples at 48 kHz, half overlap):
1. skip it if a stole tap is playing or ended less than 100 ms ago (motor noise), or if it is
   quieter than the running noise floor + 9 dB (no speech);
2. for every microphone pair, GCC-PHAT restricted to 300-4,000 Hz gives the arrival-time
   difference, with 8x interpolation for sub-sample resolution, and a confidence: how much of
   the band agrees on that one delay (1 = a single clean source);
3. two microphones give the side only (left, centre, right: they cannot tell front from
   behind); three or more give a full bearing by least squares.

Bearings are degrees clockwise from straight ahead (front 0, right 90, behind 180, left 270),
the convention of app/kandha/seatmap.angle_to_zone. Nothing here stores or sends audio: frames
are analysed in memory and dropped; only angles, confidences and levels leave this module.
"""
from collections import deque
from dataclasses import dataclass
import math
import threading

import numpy as np

SPEED_OF_SOUND = 343.0           # m/s at about 20 °C
BAND_HZ = (300.0, 4000.0)
FRAME = 4096
HOP = 2048
TAP_GUARD_S = 0.10               # ignore audio for this long after a tap ends (motor coasting)
SPEECH_ABOVE_FLOOR_DB = 9.0
INTERP = 8


@dataclass(frozen=True)
class ArrayGeometry:
    """Microphone positions in metres: x to the wearer's right, y straight ahead."""
    name: str
    positions: tuple

    @classmethod
    def stereo(cls, spacing_m=0.03, swap=False):
        """Two microphones side by side, channel 0 on the left (as measured on the owner's laptop)."""
        left, right = (-spacing_m / 2, 0.0), (spacing_m / 2, 0.0)
        return cls("stereo", (right, left) if swap else (left, right))

    @classmethod
    def quad(cls, side_m=0.04):
        """The mic pod's square: front-left, front-right, back-right, back-left."""
        h = side_m / 2
        return cls("quad", ((-h, h), (h, h), (h, -h), (-h, -h)))

    @property
    def channels(self):
        return len(self.positions)

    @property
    def pairs(self):
        n = self.channels
        return [(i, j) for i in range(n) for j in range(i + 1, n)]

    def max_lag(self, rate):
        span = max(math.dist(self.positions[i], self.positions[j]) for i, j in self.pairs)
        return int(math.ceil(span / SPEED_OF_SOUND * rate)) + 1

    def delays(self, bearing_deg):
        """Arrival time of a far-away source at each microphone, relative to the array centre."""
        b = math.radians(bearing_deg)
        u = (math.sin(b), math.cos(b))
        return [-(x * u[0] + y * u[1]) / SPEED_OF_SOUND for x, y in self.positions]


_HANN = {}


def _hann(n):
    if n not in _HANN:
        _HANN[n] = np.hanning(n)
    return _HANN[n]


def gcc_phat(a, b, rate, max_lag, band=BAND_HZ, interp=INTERP):
    """Arrival time at a minus arrival time at b, in samples (positive: b heard it first),
    and the confidence in [0, 1] that one source dominates the band."""
    n = 1 << int(math.ceil(math.log2(len(a) + len(b))))
    # A Hann window: with hard frame edges, the edges (at the same place in both channels) leak
    # the strong speech frequencies into the weak ones and pull every delay towards zero; on
    # synthetic speech that under-read a 4-sample delay as 2.8 (white noise was unaffected).
    w = _hann(len(a))
    A, B = np.fft.rfft(a * w, n), np.fft.rfft(b * w, n)
    G = A * np.conj(B)
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    mask = (freqs >= band[0]) & (freqs <= band[1])
    bins = int(mask.sum())
    if bins == 0:
        return 0.0, 0.0
    G = np.where(mask, G / (np.abs(G) + 1e-12), 0)
    cc = np.fft.irfft(G, n * interp) * interp
    reach = max_lag * interp
    window = np.concatenate((cc[-reach:], cc[:reach + 1]))
    k = int(np.argmax(window))
    peak = float(window[k])
    lag = (k - reach) / interp
    confidence = max(0.0, min(1.0, peak * n / (2.0 * bins)))
    return lag, confidence


def is_fake_stereo(block, tolerance=1e-3):
    """True when a "stereo" source is really one signal sent twice (many laptop mics do this)."""
    block = np.asarray(block, dtype=np.float64)
    if block.ndim != 2 or block.shape[1] < 2:
        return True
    a, b = block[:, 0], block[:, 1]
    scale = max(float(np.max(np.abs(a))), 1e-9)
    if float(np.max(np.abs(a - b))) <= tolerance * scale:
        return True
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return False
    return bool(np.corrcoef(a, b)[0, 1] > 0.99999)


@dataclass
class Reading:
    t: float                  # seconds, the caller's clock, end of the frame
    bearing: float | None     # degrees clockwise from ahead; None when unsure
    confidence: float         # 0-1
    level_db: float           # dBFS of the frame
    sided_only: bool          # two microphones: front and behind are not told apart


def locate(frame, geometry, rate):
    """(bearing or None, confidence) for one multichannel frame."""
    max_lag = geometry.max_lag(rate)
    taus, rows, confs = [], [], []
    for i, j in geometry.pairs:
        lag, conf = gcc_phat(frame[:, i], frame[:, j], rate, max_lag)
        pi, pj = geometry.positions[i], geometry.positions[j]
        taus.append(lag / rate)
        rows.append((-(pi[0] - pj[0]) / SPEED_OF_SOUND, -(pi[1] - pj[1]) / SPEED_OF_SOUND))
        confs.append(conf)
    confidence = float(np.mean(confs))
    if geometry.channels == 2:
        (x0, y0), (x1, y1) = geometry.positions
        span = math.hypot(x1 - x0, y1 - y0)
        s = max(-1.0, min(1.0, taus[0] * SPEED_OF_SOUND / span * (1 if x1 > x0 else -1)))
        return math.degrees(math.asin(s)) % 360.0, confidence
    A = np.array(rows)
    u, *_ = np.linalg.lstsq(A, np.array(taus), rcond=None)
    if float(np.hypot(*u)) < 1e-6:
        return None, 0.0
    return math.degrees(math.atan2(u[0], u[1])) % 360.0, confidence


def circular_mean(bearings, weights=None):
    if not bearings:
        return None
    w = np.ones(len(bearings)) if weights is None else np.asarray(weights, dtype=float)
    r = np.radians(bearings)
    s, c = float(np.sum(w * np.sin(r))), float(np.sum(w * np.cos(r)))
    if math.hypot(s, c) < 1e-9:
        return None
    return math.degrees(math.atan2(s, c)) % 360.0


class DirectionTracker:
    """Feed multichannel audio; ask where the last turn came from.

    Thread-safe: audio arrives on a capture thread, questions come from HTTP handlers.
    """

    def __init__(self, geometry, rate=48000, history_s=30.0, min_confidence=0.35):
        self.geometry = geometry
        self.rate = rate
        self.min_confidence = min_confidence
        self.readings = deque(maxlen=int(history_s * rate / HOP) + 4)
        self.buffer = np.zeros((0, geometry.channels))
        self.buffer_t = None
        self.floor_db = None
        self.muted_until = -1e9
        self.lock = threading.Lock()
        self.levels = [-120.0] * geometry.channels
        self.segment = None              # (start t, [readings]) while someone is speaking
        self.turns = deque(maxlen=50)    # finished speech segments with their direction
        self.silent_frames = 0

    def mute(self, until_t):
        """A tap plays until until_t: ignore audio until then plus the motor guard."""
        with self.lock:
            self.muted_until = max(self.muted_until, until_t + TAP_GUARD_S)

    def feed(self, samples, t_end):
        """samples: (n, channels) float; t_end: the caller's clock at the last sample."""
        samples = np.asarray(samples, dtype=np.float64)
        if samples.ndim == 1:
            samples = samples[:, None]
        if samples.shape[1] != self.geometry.channels:
            raise ValueError(f"Expected {self.geometry.channels} channels, got {samples.shape[1]}.")
        out = []
        with self.lock:
            self.levels = [float(20 * np.log10(np.sqrt(np.mean(samples[:, c] ** 2)) + 1e-12)) for c in range(samples.shape[1])]
            self.buffer = np.vstack((self.buffer, samples))
            self.buffer_t = t_end
            while len(self.buffer) >= FRAME:
                frame = self.buffer[:FRAME]
                frame_end = t_end - (len(self.buffer) - FRAME) / self.rate
                self.buffer = self.buffer[HOP:]
                reading = self._frame(frame, frame_end)
                if reading is not None:
                    out.append(reading)
        return out

    def _frame(self, frame, t):
        level = float(20 * np.log10(np.sqrt(np.mean(frame ** 2)) + 1e-12))
        if self.floor_db is None:
            self.floor_db = level
        # the floor follows quiet frames quickly and loud ones very slowly
        self.floor_db += (level - self.floor_db) * (0.2 if level < self.floor_db else 0.002)
        if t < self.muted_until:
            return None
        speaking = level > self.floor_db + SPEECH_ABOVE_FLOOR_DB
        if not speaking:
            self.silent_frames += 1
            if self.segment and self.silent_frames >= 4:       # ~170 ms of quiet ends a segment
                self._close_segment()
            return None
        self.silent_frames = 0
        bearing, confidence = locate(frame, self.geometry, self.rate)
        reading = Reading(t, bearing if confidence >= self.min_confidence else None, confidence, level,
                          self.geometry.channels == 2)
        self.readings.append(reading)
        if self.segment is None:
            self.segment = (t - FRAME / self.rate, [])
        self.segment[1].append(reading)
        return reading

    def _close_segment(self):
        start, readings = self.segment
        self.segment = None
        if not readings:
            return
        end = readings[-1].t
        summary = self._summarise(readings)
        self.turns.append({"t0": start, "t1": end, **summary})

    def _summarise(self, readings):
        good = [r for r in readings if r.bearing is not None]
        if not good:
            return {"bearing": None, "confidence": 0.0, "frames": len(readings)}
        bearing = circular_mean([r.bearing for r in good], [r.confidence for r in good])
        return {"bearing": bearing, "confidence": round(float(np.mean([r.confidence for r in good])), 3),
                "frames": len(good)}

    def direction_between(self, t0, t1, min_frames=3):
        """Where speech between t0 and t1 came from: {bearing, confidence, frames} or None."""
        with self.lock:
            readings = [r for r in self.readings if t0 <= r.t <= t1]
        summary = self._summarise(readings)
        if summary["bearing"] is None or summary["frames"] < min_frames:
            return None
        return summary

    def take_turns(self):
        """Finished speech segments since the last call."""
        with self.lock:
            turns = list(self.turns)
            self.turns.clear()
        return turns

    def latest(self):
        with self.lock:
            last = self.readings[-1] if self.readings else None
            return {"levels_db": [round(x, 1) for x in self.levels],
                    "bearing": None if last is None or last.bearing is None else round(last.bearing, 1),
                    "confidence": 0.0 if last is None else round(last.confidence, 2),
                    "t": None if last is None else last.t,
                    "sided_only": self.geometry.channels == 2,
                    "floor_db": None if self.floor_db is None else round(self.floor_db, 1)}


def side_zone(bearing, sided_only):
    """The stole zone for a bearing. With two microphones front and behind cannot be told apart,
    so anything not clearly to one side is "front"; a pad corrects it."""
    from app.kandha.seatmap import angle_to_zone
    if bearing is None:
        return None
    zone = angle_to_zone(bearing)
    if sided_only and zone == "B":
        return "F"
    return zone
