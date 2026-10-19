"""Real offline pipeline check with the bundled licensed speech excerpt."""

import json
import socket
import threading
import time
from unittest.mock import patch

from app.services.engine import AudioEngine
from app.utils.config import Settings
from app.utils.paths import project_root


def verify_inference():
    events = []
    lock = threading.Lock()
    began = time.perf_counter()

    def receive(kind, data):
        with lock:
            events.append((kind, data, time.perf_counter() - began))

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
            engine.start(
                "combined",
                file_path=project_root() / "assets" / "evaluation_sample.wav",
            )
            engine.threads[0].join(timeout=180)
            if engine.running or any(t.is_alive() for t in engine.threads):
                engine.stop()
                raise RuntimeError(
                    "The offline pipeline did not finish and release its workers"
                )
    finally:
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
                "offline_pipeline": "PASS",
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
