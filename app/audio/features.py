"""Objective features only. dBFS is a digital level, not sound-pressure level."""
import numpy as np
from scipy.fft import dct
from scipy.signal import find_peaks, resample_poly
from math import gcd

SAMPLE_RATE = 16000


def mono_resample(audio, rate, target=SAMPLE_RATE):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if audio.ndim != 1 or rate <= 0:
        raise ValueError("Expected mono/stereo audio and a positive sample rate")
    if not np.isfinite(audio).all():
        raise ValueError("Non-finite audio samples")
    if rate != target:
        div = gcd(int(rate), int(target))
        audio = resample_poly(audio, target // div, rate // div).astype(np.float32)
    return np.clip(audio, -1, 1)


def frames(audio, length=640, hop=320):
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) < length:
        audio = np.pad(audio, (0, length - len(audio)))
    return np.lib.stride_tricks.sliding_window_view(audio, length)[::hop].copy()


def pitch_frame(frame, rate=SAMPLE_RATE):
    x = np.asarray(frame, dtype=np.float64)
    x = (x - x.mean()) * np.hanning(len(x))
    if np.sqrt(np.mean(x * x)) < 0.003:
        return None, 0.0
    spectrum = np.fft.rfft(x, n=2 ** int(np.ceil(np.log2(len(x) * 2))))
    corr = np.fft.irfft(spectrum * spectrum.conj())[:len(x)]
    corr /= max(corr[0], 1e-12)
    lo, hi = int(rate / 450), min(len(corr) - 1, int(rate / 60))
    peaks, _ = find_peaks(corr[lo:hi + 1])
    if not len(peaks):
        return None, 0.0
    # Select the earliest strong peak to reduce octave-halving errors.
    candidates = peaks + lo
    best = candidates[np.argmax(corr[candidates])]
    strong = candidates[corr[candidates] >= max(0.45, corr[best] * 0.92)]
    lag = int(strong[0]) if len(strong) else int(best)
    confidence = float(np.clip(corr[lag], 0, 1))
    return (float(rate / lag), confidence) if confidence > 0.45 else (None, confidence)


def prosody(audio, rate=SAMPLE_RATE):
    x = mono_resample(audio, rate)
    f = frames(x)
    rms = np.sqrt(np.mean(f * f, axis=1))
    voiced = rms > 0.008
    pitches = [pitch_frame(a) for a in f]
    values = [p for p, c in pitches if p is not None]
    spectrum = np.abs(np.fft.rfft(f * np.hanning(f.shape[1]), axis=1))
    freq = np.fft.rfftfreq(f.shape[1], 1 / SAMPLE_RATE)
    centroid = (spectrum * freq).sum(axis=1) / np.maximum(spectrum.sum(axis=1), 1e-9)
    changes = np.diff(np.r_[True, voiced, True].astype(int))
    starts = np.flatnonzero(changes == -1)
    ends = np.flatnonzero(changes == 1)
    durations = [(b - a) * 0.02 for a, b in zip(starts, ends) if b > a and (b - a) * 0.02 >= 0.2]
    return {"f0_hz": float(np.median(values)) if values else None,
            "pitch_std_hz": float(np.std(values)) if values else None,
            "pitch_confidence": float(np.mean([c for p, c in pitches if p is not None])) if values else 0.0,
            "f0_curve": [p for p, c in pitches],
            "dbfs": float(20 * np.log10(max(float(np.sqrt(np.mean(x * x))) if len(x) else 0, 1e-6))),
            "energy": float(np.mean(x * x)) if len(x) else 0,
            "spectral_centroid_hz": float(np.mean(centroid)),
            "voiced_fraction": float(np.mean(voiced)),
            "pause_count": len(durations), "pause_seconds": float(sum(durations)),
            "speaking_rate_wpm": None, "rate_source": "Requires ASR word timestamps",
            "waveform": x[::max(1, len(x) // 200)].tolist()[:200]}


def mfcc_features(audio, rate=SAMPLE_RATE):
    """40 MFCC mean + std = 80 dimensions, shared by training and inference."""
    x = mono_resample(audio, rate)
    f = frames(x, 400, 160) * np.hanning(400)
    power = np.abs(np.fft.rfft(f, n=512, axis=1)) ** 2
    hz = lambda m: 700 * (10 ** (m / 2595) - 1)
    mel = lambda h: 2595 * np.log10(1 + h / 700)
    bins = np.floor(513 * hz(np.linspace(mel(20), mel(7600), 66)) / SAMPLE_RATE).astype(int)
    filters = np.zeros((64, 257))
    for i in range(64):
        a, b, c = bins[i:i + 3]
        if b > a:
            filters[i, a:b] = np.arange(b - a) / (b - a)
        if c > b:
            filters[i, b:c] = np.arange(c - b, 0, -1) / (c - b)
    coeff = dct(np.log(np.maximum(power @ filters.T, 1e-10)), type=2, norm="ortho", axis=1)[:, :40]
    return np.r_[coeff.mean(axis=0), coeff.std(axis=0)].astype(np.float32)
