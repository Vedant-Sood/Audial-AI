"""Deterministic acoustic features shared by training and inference."""

from functools import lru_cache
from io import BytesIO
from math import gcd

import numpy as np
from scipy.fft import dct, irfft, rfft
from scipy.io import wavfile
from scipy.signal import resample_poly

SAMPLE_RATE = 16000
FEATURE_VERSION = "mfcc-mel-prosody-v1"


def read_wav(source):
    rate, samples = wavfile.read(BytesIO(source) if isinstance(source, bytes) else source)
    if samples.dtype.kind == "u":
        samples = (samples.astype(np.float64) - 128.0) / 128.0
    elif samples.dtype.kind == "i":
        samples = samples.astype(np.float64) / float(2 ** (samples.dtype.itemsize * 8 - 1))
    else:
        samples = samples.astype(np.float64)
    return prepare(samples, rate)


def prepare(samples, rate):
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1 or not np.all(np.isfinite(samples)):
        raise ValueError("Audio must contain finite mono or stereo samples.")
    if not isinstance(rate, (int, np.integer)) or not 8000 <= rate <= 192000:
        raise ValueError("Unsupported sample rate.")
    if len(samples) < int(rate * 0.4) or len(samples) > rate * 30:
        raise ValueError("Use audio segments between 0.4 and 30 seconds.")
    if rate != SAMPLE_RATE:
        factor = gcd(int(rate), SAMPLE_RATE)
        samples = resample_poly(samples, SAMPLE_RATE // factor, int(rate) // factor)
    return samples


def frames(samples, length=400, hop=160):
    if len(samples) < length:
        samples = np.pad(samples, (0, length - len(samples)))
    return np.lib.stride_tricks.sliding_window_view(samples, length)[::hop].copy()


@lru_cache(maxsize=1)
def mel_filters():
    mel = lambda hz: 2595.0 * np.log10(1.0 + hz / 700.0)
    hz = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)
    edges = hz(np.linspace(mel(50), mel(7600), 42))
    frequencies = np.fft.rfftfreq(512, 1 / SAMPLE_RATE)
    filters = []
    for low, center, high in zip(edges[:-2], edges[1:-1], edges[2:]):
        filters.append(np.maximum(0, np.minimum((frequencies - low) / (center - low),
                                                (high - frequencies) / (high - center))))
    return np.asarray(filters)


def prosody(samples):
    """Pitch and recorded level describe the audio, not someone's inner state."""
    centered = samples - samples.mean()
    windows = frames(centered, length=640)
    rms = np.sqrt(np.mean(windows * windows, axis=1))
    active = rms > max(0.002, float(rms.max()) * 0.15)
    tapered = windows * np.hanning(640)
    autocorrelation = irfft(np.abs(rfft(tapered, n=2048, axis=1)) ** 2, n=2048, axis=1)
    low, high = SAMPLE_RATE // 500, SAMPLE_RATE // 60
    lags = np.argmax(autocorrelation[:, low:high + 1], axis=1) + low
    strength = autocorrelation[np.arange(len(lags)), lags] / np.maximum(autocorrelation[:, 0], 1e-12)
    voiced = active & (strength > 0.35)
    pitch = SAMPLE_RATE / lags[voiced]
    pitch_stats = np.percentile(pitch, [10, 25, 50, 75, 90]) if len(pitch) else np.zeros(5)
    return {
        "duration_seconds": round(len(samples) / SAMPLE_RATE, 3),
        "rms_dbfs": round(20 * np.log10(max(float(np.sqrt(np.mean(samples * samples))), 1e-8)), 2),
        "pitch_median_hz": round(float(pitch_stats[2]), 1) if len(pitch) else None,
        "pitch_range_hz": round(float(pitch_stats[4] - pitch_stats[0]), 1) if len(pitch) else None,
        "voiced_fraction": round(float(voiced.mean()), 3),
        "active_fraction": round(float(active.mean()), 3),
        "clipped_fraction": round(float((np.abs(samples) >= 0.999).mean()), 4),
        "_pitch_features": np.r_[pitch_stats, np.std(pitch) if len(pitch) else 0, voiced.mean()],
    }


def extract_features(samples):
    samples = np.asarray(samples, dtype=np.float64)
    details = prosody(samples)
    samples = samples - samples.mean()
    peak = float(np.max(np.abs(samples)))
    normalized = samples / max(peak, 1e-8)
    windows = frames(normalized)
    energy = np.sqrt(np.mean(windows * windows, axis=1))
    emphasized = np.r_[normalized[0], normalized[1:] - 0.97 * normalized[:-1]]
    power = np.abs(rfft(frames(emphasized) * np.hanning(400), n=512, axis=1)) ** 2
    log_mel = np.log(np.maximum(power @ mel_filters().T, 1e-10))
    mfcc = dct(log_mel, type=2, norm="ortho", axis=1)[:, :20]
    delta = np.gradient(mfcc, axis=0)
    frequencies = np.fft.rfftfreq(512, 1 / SAMPLE_RATE)
    mass = power.sum(axis=1) + 1e-10
    centroid = (power * frequencies).sum(axis=1) / mass
    bandwidth = np.sqrt((power * (frequencies[None, :] - centroid[:, None]) ** 2).sum(axis=1) / mass)
    flatness = np.exp(np.log(power + 1e-10).mean(axis=1)) / (power.mean(axis=1) + 1e-10)
    zcr = (np.diff(np.signbit(windows), axis=1)).mean(axis=1)
    spectral = np.c_[centroid, bandwidth, flatness, zcr]
    features = np.r_[mfcc.mean(0), mfcc.std(0), delta.mean(0), delta.std(0),
                     log_mel.mean(0), log_mel.std(0), spectral.mean(0), spectral.std(0),
                     details.pop("_pitch_features"), np.percentile(energy, [10, 25, 50, 75, 90]),
                     energy.mean(), energy.std(), np.mean(np.abs(np.diff(energy)))]
    return features.astype(np.float32), details
