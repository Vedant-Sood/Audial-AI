"""Single-owner expression inference, bounded queues, and display stabilization.

Raw per-caption predictions remain unchanged. Stabilization only controls the
live indicator; uncertainty is never replaced with an old confident label.
"""

from collections import deque
import threading
import time

import numpy as np


class ExpressionDisplay:
    def __init__(self):
        self.label = None
        self.candidate = None
        self.timestamp = None

    def update(self, estimate, timestamp):
        result = dict(estimate)
        label = result.get("tone", "uncertain")
        if (
            self.timestamp is None
            or timestamp < self.timestamp
            or timestamp - self.timestamp > 3
        ):
            self.label = self.candidate = None
        self.timestamp = timestamp
        if label == "uncertain":
            self.label = self.candidate = None
            return result
        if self.label is None or self.label == label or self.candidate == label:
            self.label, self.candidate = label, None
            return result
        self.candidate = label
        return {
            **result,
            "raw_tone": label,
            "tone": "uncertain",
            "reason": "changing_vocal_expression",
        }


class ExpressionWorker:
    def __init__(self, model, emit, max_captions=8):
        self.model, self.emit = model, emit
        self.condition = threading.Condition()
        self.captions = deque(maxlen=max_captions)
        self.display_job = None
        self.display = ExpressionDisplay()
        self.stopping = False
        self.draining = False
        self.failed = False
        self.dropped = 0
        self.last_display = 0.0
        self.thread = threading.Thread(
            target=self.run, name="audial-expression", daemon=True
        )
        self.thread.start()

    def submit_display(self, audio, timestamp):
        with self.condition:
            if self.stopping or self.failed:
                return False
            self.display_job = (np.asarray(audio, dtype=np.float32).copy(), timestamp)
            self.condition.notify()
            return True

    def submit_caption(self, audio, caption):
        with self.condition:
            if self.stopping or self.failed:
                return False
            if len(self.captions) == self.captions.maxlen:
                self.captions.popleft()
                self.dropped += 1
                if self.dropped == 1:
                    self.emit(
                        "warning",
                        "Vocal-expression analysis is behind. Some optional estimates are omitted; captions and objective voice measurements remain complete.",
                    )
            key = {
                "start": caption.start,
                "end": caption.end,
                "speaker": caption.speaker,
            }
            self.captions.append((np.asarray(audio, dtype=np.float32).copy(), key))
            self.condition.notify()
            return True

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(
                    lambda: self.stopping or self.captions or self.display_job
                )
                if self.stopping and (not self.draining or not self.captions):
                    break
                if (
                    not self.stopping
                    and self.display_job
                    and (not self.captions or time.monotonic() - self.last_display > 2)
                ):
                    kind = "display"
                    audio, key = self.display_job
                    self.display_job = None
                    self.last_display = time.monotonic()
                else:
                    kind = "caption"
                    audio, key = self.captions.popleft()
            try:
                started = time.perf_counter()
                estimate = self.model.predict(audio)
                estimate = {
                    **estimate,
                    "inference_seconds": time.perf_counter() - started,
                }
                if self.stopping and not self.draining:
                    continue
                if kind == "display":
                    self.emit(
                        "emotion",
                        {
                            "timestamp": key,
                            "estimate": self.display.update(estimate, key),
                        },
                    )
                else:
                    self.emit("caption_voice", {**key, "estimate": estimate})
            except Exception as error:
                self.failed = True
                self.emit(
                    "error",
                    "Vocal-expression model failed: "
                    + str(error)
                    + ". Captions and objective prosody continue; check model setup.",
                )
                with self.condition:
                    self.captions.clear()
                    self.display_job = None

    def close(self, drain=False):
        with self.condition:
            self.draining = drain
            self.stopping = True
            if not drain:
                self.captions.clear()
            self.display_job = None
            self.condition.notify_all()
        self.thread.join()
        self.model = None
