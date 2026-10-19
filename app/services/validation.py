"""Real offline file and streaming checks with the licensed speech excerpt."""

import json
import socket
import threading
import time
from unittest.mock import patch

from app.services.engine import AudioEngine
from app.utils.config import Settings
from app.utils.paths import project_root


def verify_inference(stream=False):
    events = []
    lock = threading.Lock()
    listening = threading.Event()
    expression_received = threading.Event()
    began = time.perf_counter()

    def receive(kind, data):
        with lock:
            events.append((kind, data, time.perf_counter() - began))
        if kind == "status" and str(data).startswith("Listening to browser"):
            listening.set()
        if kind == "caption_voice" and data["estimate"].get("probabilities"):
            expression_received.set()

    def blocked(*args, **kwargs):
        raise RuntimeError("Offline validation attempted a network connection")

    engine = AudioEngine(
        Settings(device="cpu", partial_updates=False, prosody_classifier=True)
    )
    unsubscribe = engine.subscribe(receive)
    try:
        # Fail on any attempted socket connection, beyond HF offline flags.
        with (
            patch.object(socket.socket, "connect", blocked),
            patch.object(socket, "create_connection", blocked),
        ):
            sample = project_root() / "assets" / "evaluation_sample.wav"
            if stream:
                import numpy as np
                import soundfile as sf
                from app.audio.features import mono_resample

                audio, rate = sf.read(sample, dtype="float32")
                audio = mono_resample(audio, rate)
                # Real capture/VAD/ASR/expression code, paced as 20-ms PCM
                # packets. This opens neither a microphone nor a browser.
                engine.start("combined", source="browser")
                if not listening.wait(120):
                    engine.stop()
                    raise RuntimeError("Streaming models did not become ready")
                capture = engine.capture
                audio = np.r_[audio, np.zeros(16000, dtype=np.float32)]
                feeding_started = time.perf_counter()
                for offset in range(0, len(audio), 320):
                    if not engine.running:
                        raise RuntimeError("Streaming pipeline stopped before audio ended")
                    capture.feed(audio[offset:offset + 320], offset / 16000)
                    delay = feeding_started + (offset + 320) / 16000 - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                if capture.dropped:
                    raise RuntimeError("Streaming validation dropped input blocks")
                # Wait for actual asynchronous caption predictions before
                # exercising the normal live Stop/cancel-and-release path.
                if not expression_received.wait(120):
                    engine.stop()
                    raise RuntimeError("Streaming caption expression did not finish")
                engine.stop()
            else:
                engine.start("combined", file_path=sample)
            engine.threads[0].join(timeout=180)
            if engine.running or any(t.is_alive() for t in engine.threads):
                engine.stop()
                raise RuntimeError(
                    "The offline pipeline did not finish and release its workers"
                )
    finally:
        engine.stop()
        for worker in engine.threads:
            if worker is not threading.current_thread() and worker.is_alive():
                worker.join(timeout=30)
        unsubscribe()
    errors = [str(data) for kind, data, _ in events if kind == "error"]
    captions = [(data, elapsed) for kind, data, elapsed in events if kind == "caption"]
    expression = [
        (data, elapsed) for kind, data, elapsed in events if kind == "caption_voice"
    ]
    if (
        errors
        or not captions
        or not expression
        or not any(kind == "prosody" for kind, _, _ in events)
    ):
        raise RuntimeError(
            "Offline captions/expression/prosody failed: "
            + "; ".join(errors or ["A required result is missing"])
        )
    if not all(data["estimate"].get("probabilities") for data, _ in expression):
        raise RuntimeError("Expression did not return a real model prediction")
    if (
        engine.capture is not None
        or engine.asr is not None
        or engine.expression_worker is not None
    ):
        raise RuntimeError("The offline pipeline retained active resources")
    print(
        json.dumps(
            {
                "live_capture_pipeline" if stream else "offline_pipeline": "PASS",
                "audio_source": (
                    "Real-time software-fed supplied speech through ExternalAudio and the capture loop; no browser transport or physical device"
                    if stream else "Imported supplied speech file"
                ),
                "microphone_started": False,
                "captions": len(captions),
                "caption_text": " ".join(c.text for c, _ in captions),
                "first_caption_seconds": captions[0][1],
                "first_caption_expression_seconds": expression[0][1],
                "total_seconds": time.perf_counter() - began,
                "workers_released": True,
                "network_connections": "blocked during the entire inference check",
            }
        ),
        flush=True,
    )
