import threading
import time

import numpy as np

from app.inference.expression import ExpressionWorker, ExpressionDisplay
from app.storage.transcript import Caption
from app.services.engine import AudioEngine, choose_device
from app.utils.config import Settings


def test_expression_inference_is_serial_and_queues_remain_bounded():
    gate = threading.Event()
    entered = threading.Event()
    results = []
    class Model:
        concurrent = 0
        maximum = 0
        def predict(self, audio):
            self.concurrent += 1
            self.maximum = max(self.maximum, self.concurrent)
            entered.set()
            assert gate.wait(5)
            self.concurrent -= 1
            return {"tone": "happy", "confidence": .8, "probabilities": {"happy": .8}}
    model = Model()
    worker = ExpressionWorker(model, lambda kind, data: results.append((kind, data)))
    audio = np.zeros(16000, np.float32)
    try:
        worker.submit_display(audio, 1)
        assert entered.wait(2)
        started = time.perf_counter()
        for i in range(100):
            worker.submit_display(audio, i + 2)
            worker.submit_caption(audio, Caption(i, i + 1, "Exact caption words"))
        assert time.perf_counter() - started < .5
        assert len(worker.captions) <= 8 and worker.display_job is not None
        assert worker.dropped == 92
        assert sum(kind == "warning" for kind, _ in results) == 1
        gate.set()
        deadline = time.monotonic() + 2
        while not any(kind == "emotion" for kind, _ in results) and time.monotonic() < deadline:
            time.sleep(.01)
        assert any(kind == "emotion" for kind, _ in results)
        assert model.maximum == 1
    finally:
        gate.set()
        worker.close()
    assert not worker.thread.is_alive()


def test_display_stabilization_never_turns_uncertainty_into_a_previous_label():
    display = ExpressionDisplay()
    happy = {"tone": "happy", "confidence": .8}
    sad = {"tone": "sad", "confidence": .8}
    assert display.update(happy, 1)["tone"] == "happy"
    assert display.update(sad, 2)["tone"] == "uncertain"
    assert display.update(sad, 3)["tone"] == "sad"
    assert display.update({"tone": "uncertain", "reason": "low_confidence"}, 4)["tone"] == "uncertain"
    assert display.update(happy, 10)["tone"] == "happy"


def test_natural_file_completion_drains_pending_caption_estimates():
    entered, release = threading.Event(), threading.Event()
    events = []
    class Model:
        def predict(self, audio):
            entered.set()
            assert release.wait(3)
            return {"tone": "uncertain", "probabilities": {"happy": .4}}
    worker = ExpressionWorker(Model(), lambda kind, data: events.append((kind, data)))
    worker.submit_display(np.zeros(16000), 1)
    assert entered.wait(2)
    worker.submit_caption(np.zeros(16000), Caption(0, 1, "Final words"))
    closer = threading.Thread(target=lambda: worker.close(drain=True))
    closer.start()
    release.set()
    closer.join(3)
    assert not closer.is_alive() and not worker.thread.is_alive()
    assert len([1 for kind, _ in events if kind == "caption_voice"]) == 1


def test_optional_worker_failure_is_visible_without_breaking_caption_work():
    events = []
    failed = threading.Event()
    class Model:
        def predict(self, audio):
            raise OSError("Model file changed")
    def emit(kind, data):
        events.append((kind, data))
        if kind == "error": failed.set()
    worker = ExpressionWorker(Model(), emit)
    try:
        worker.submit_display(np.zeros(16000, np.float32), 1)
        assert failed.wait(2)
        assert "Captions and objective prosody continue" in events[0][1]
        assert worker.failed
    finally:
        worker.close()


def test_requested_unavailable_gpu_has_an_explicit_cpu_fallback(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    warnings = []
    assert choose_device("cuda", warnings.append) == "cpu"
    assert len(warnings) == 1 and "Using CPU" in warnings[0]


def test_caption_voice_updates_never_change_the_spoken_words():
    from app.services.browser import BrowserService
    service = BrowserService(settings=Settings())
    original = Caption(0, 1, "These words stay exact.", "Speaker 1", voice={"f0_hz": 130})
    service.on_event("caption", original)
    service.on_event("caption_voice", {"start": 0, "end": 1, "speaker": "Speaker 1", "estimate": {"tone": "uncertain", "confidence": .4}})
    assert service.session.captions[0].text == original.text
    assert service.session.captions[0].voice["tone"] == "uncertain"
    assert "tone" not in original.voice
    service.unsubscribe()
