"""Synthetic multichannel rooms: voices at known bearings, for tests and the Recorded mode.

Every result made with this is SIMULATED. Each voice is a real LibriSpeech reading (the
fixtures in tests/fixtures/sanket), placed far away at a bearing; each microphone hears it
with the exact (fractional-sample) delay its position implies, plus optional echoes from other
directions and independent noise on every channel. Nothing models a real room's reverberation
faithfully: accuracy on these files is an upper bound, not a measurement.
"""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.kandha.direction import ArrayGeometry

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sanket"


def load_voice(name, rate=48000):
    """A LibriSpeech fixture as float64 mono at `rate`."""
    import soundfile as sf
    from scipy.signal import resample_poly
    audio, sr = sf.read(str(FIXTURES / f"{name}.wav"), dtype="float64")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != rate:
        g = np.gcd(int(sr), int(rate))
        audio = resample_poly(audio, rate // g, sr // g)
    return audio / (np.max(np.abs(audio)) + 1e-9) * 0.5


def voices():
    return sorted(p.stem for p in FIXTURES.glob("*.wav"))


def fractional_delay(signal, delay_s, rate):
    n = 1 << int(np.ceil(np.log2(len(signal) * 2)))
    spectrum = np.fft.rfft(signal, n)
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    return np.fft.irfft(spectrum * np.exp(-2j * np.pi * freqs * delay_s), n)[:len(signal)]


@dataclass
class Talker:
    bearing: float               # degrees clockwise from ahead
    start_s: float
    duration_s: float
    voice: str = "198-209-0000"
    gain: float = 1.0


@dataclass
class Room:
    geometry: ArrayGeometry
    talkers: list
    rate: int = 48000
    length_s: float | None = None
    noise_db: float = -60.0                 # independent noise on each microphone, dBFS
    echoes: list = field(default_factory=list)   # [(extra bearing offset deg, delay s, gain)]
    seed: int = 7

    def render(self):
        length = self.length_s or max(t.start_s + t.duration_s for t in self.talkers) + 0.5
        n = int(length * self.rate)
        out = np.zeros((n, self.geometry.channels))
        cache = {}
        for talker in self.talkers:
            if talker.voice not in cache:
                cache[talker.voice] = load_voice(talker.voice, self.rate)
            speech = cache[talker.voice]
            seg = int(talker.duration_s * self.rate)
            piece = np.resize(speech, seg) * talker.gain
            paths = [(talker.bearing, 0.0, 1.0)] + [((talker.bearing + off) % 360, d, g) for off, d, g in self.echoes]
            for bearing, extra, gain in paths:
                delays = self.geometry.delays(bearing)
                for ch, d in enumerate(delays):
                    shifted = fractional_delay(piece, d + extra, self.rate) * gain
                    start = int(talker.start_s * self.rate)
                    end = min(n, start + len(shifted))
                    out[start:end, ch] += shifted[:end - start]
        rng = np.random.default_rng(self.seed)
        out += rng.standard_normal(out.shape) * (10 ** (self.noise_db / 20))
        return out

    def truth(self):
        return [{"bearing": t.bearing, "start_s": t.start_s, "end_s": t.start_s + t.duration_s, "voice": t.voice} for t in self.talkers]


def write(path, room):
    """Write the room as a multichannel WAV plus a .json with the true bearings."""
    import json
    import soundfile as sf
    audio = room.render()
    peak = float(np.max(np.abs(audio)))
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    path = Path(path)
    sf.write(str(path), audio, room.rate, subtype="PCM_24")
    path.with_suffix(".json").write_text(json.dumps({"geometry": room.geometry.name, "positions": room.geometry.positions,
                                                     "rate": room.rate, "talkers": room.truth(), "simulated": True}, indent=1))
    return path
