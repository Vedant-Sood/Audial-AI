"""Bounded background pipelines. Qt consumes events; UI never runs ML inference."""
from collections import deque
import os
import queue
import threading
import time
import numpy as np
from app.audio.capture import Microphone, UtteranceBuffer, ExternalAudio, SystemAudio
from app.audio.features import prosody, mfcc_features
from app.inference.asr import WhisperASR
from app.inference.diarization import ECAPADiarizer, OverlapDiarizer, reconcile_words
from app.inference.sign import LocalClassifier
from app.models.manager import ModelManager
from app.utils.config import PRESETS


def choose_device(requested):
    import torch
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was selected but PyTorch cannot use it. Choose CPU or run setup.bat again.")
    return "cuda" if requested in {"auto", "cuda"} and torch.cuda.is_available() else "cpu"


class AudioEngine:
    def __init__(self, settings, manager=None):
        self.settings = settings
        self.manager = manager or ModelManager()
        self.events = queue.Queue(maxsize=300)
        self.jobs = queue.Queue(maxsize=8)
        self.stop_requested = threading.Event()
        self.paused = threading.Event()
        self.gpu_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.rate_words = deque()
        self.capture = None
        self.threads = []
        self.running = False
        self.asr = self.diarizer = self.prosody_model = None
        self._mode = "combined"
        self.source = "microphone"
        self.observers = []
        self.emotion_model = None

    def subscribe(self, callback):
        self.observers.append(callback)
        return lambda: self.observers.remove(callback) if callback in self.observers else None

    def emit(self, kind, data):
        for observer in tuple(self.observers):
            try:
                observer(kind, data)
            except Exception:
                pass
        try:
            self.events.put_nowait((kind, data))
        except queue.Full:
            if kind in {"caption", "error"}:
                # Preserve completed words; discard only transient UI updates.
                with self.events.mutex:
                    for index, event in enumerate(self.events.queue):
                        if event[0] not in {"caption", "error"}:
                            del self.events.queue[index]
                            self.events.not_full.notify()
                            break
                self.events.put((kind, data))

    def start(self, mode="combined", file_path=None, source="microphone"):
        if self.running or any(t.is_alive() for t in self.threads):
            raise RuntimeError("The previous worker is still finishing. Wait for Idle.")
        if source not in {"microphone", "system", "browser"} or mode not in {"combined", "captions", "tone"}:
            raise ValueError("Unknown audio source or mode.")
        self.source = source
        self.capture = ExternalAudio() if source == "browser" and not file_path else None
        self._mode, self.running = mode, True
        self.stop_requested.clear()
        self.paused.clear()
        self.jobs = queue.Queue(maxsize=8)
        self.rate_words.clear()
        worker = threading.Thread(target=self._prepare, args=(file_path,), daemon=True)
        self.threads = [worker]
        worker.start()

    def _prepare(self, file_path):
        try:
            # Model download is a separate process. Inference must not contact the Hub.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            self.emit("status", "Loading local models…")
            preset = PRESETS[self.settings.preset]
            device = choose_device(self.settings.device)
            self.asr = self.diarizer = self.prosody_model = self.emotion_model = None
            if self._mode != "tone":
                model_id = preset["asr"]
                if not self.manager.installed(model_id):
                    raise FileNotFoundError(f"Install {model_id} on the Models page, or select a preset with an installed ASR model.")
                compute = preset["compute_type"] if device == "cuda" else "int8"
                try:
                    self.asr = WhisperASR(self.manager.path(model_id), device, compute, preset["beam_size"], self.settings.language)
                except (RuntimeError, OSError) as exc:
                    if device != "cuda":
                        raise
                    self.emit("warning", f"GPU ASR could not start ({exc}). Using CPU INT8 for this session.")
                    self.asr = WhisperASR(self.manager.path(model_id), "cpu", "int8", preset["beam_size"], self.settings.language)
                if self.settings.diarization != "off":
                    if not self.manager.installed("ecapa"):
                        raise FileNotFoundError("Install ECAPA for speaker IDs, or set Speaker backend to off in Settings.")
                    if self.settings.diarization == "pyannote":
                        if not self.manager.installed("pyannote"):
                            raise FileNotFoundError("Install Community-1 after accepting its conditions, or select ECAPA.")
                        self.diarizer = OverlapDiarizer(self.manager.path("pyannote"), self.manager.path("ecapa"), "cpu")
                    else:
                        self.diarizer = ECAPADiarizer(self.manager.path("ecapa"), "cpu")
            if self.settings.prosody_classifier and self.manager.installed("prosody-local"):
                self.prosody_model = LocalClassifier(self.manager.path("prosody-local") / "best.pt", "prosody")
            if self.settings.prosody_classifier:
                from app.inference.emotion import VoiceEmotion
                self.emotion_model = VoiceEmotion()
            if self.stop_requested.is_set() and (self.capture is None or self.capture.queue.empty()):
                self.running = False
                self.emit("status", "Idle")
                return
            infer = threading.Thread(target=self._infer, daemon=True)
            self.threads.append(infer)
            infer.start()
            if file_path:
                self._file_loop(file_path)
            else:
                if self.source != "browser":
                    self.capture = SystemAudio() if self.source == "system" else Microphone(self.settings.microphone)
                self.capture.start()
                self.emit("status", f"Listening to {self.source} audio · local processing")
                self._capture_loop(preset["chunk_seconds"])
        except Exception as exc:
            self.emit("error", str(exc))
        finally:
            if self.capture:
                self.capture.stop()
                self.capture = None
            # Drain final chunks in order before signaling completion.
            if len(self.threads) > 1 and self.threads[-1].is_alive():
                self.jobs.put(None)
                self.threads[-1].join()
            self.running = False
            self.emit("status", "Idle")

    def _submit(self, offset, audio, partial=False):
        if self.asr is None:
            return
        try:
            self.jobs.put_nowait((offset, audio.copy(), partial))
        except queue.Full:
            if not partial:
                self.emit("warning", f"Caption queue full: speech at {offset:.1f}s was dropped. Select FAST or disable partial updates.")

    def _capture_loop(self, max_seconds):
        buffer = UtteranceBuffer(max_seconds)
        recent = deque(maxlen=100)
        last_features, last_partial = 0.0, 0.0
        was_paused = False
        while not self.stop_requested.is_set() or not self.capture.queue.empty():
            if self.paused.is_set():
                if not was_paused:
                    final = buffer.flush()
                    if final:
                        self._submit(*final)
                    recent.clear()
                    was_paused = True
                time.sleep(0.05)
                continue
            was_paused = False
            try:
                index, audio = self.capture.queue.get(timeout=0.15)
            except queue.Empty:
                if isinstance(self.capture, SystemAudio) and self.capture.start_error:
                    raise RuntimeError(self.capture.start_error)
                continue
            recent.append(audio)
            if isinstance(self.capture, SystemAudio) and self.capture.start_error:
                raise RuntimeError(self.capture.start_error)
            final = buffer.feed(index, audio)
            if final:
                self._submit(*final)
            now = time.monotonic()
            if now - last_features > 0.25 and len(recent) >= 25:
                x = np.concatenate(list(recent))
                self._features(x, (index + len(audio)) / 16000)
                last_features = now
            if self.settings.partial_updates and buffer.blocks and now - last_partial >= 1.5 and self.jobs.empty():
                x = np.concatenate(buffer.blocks)
                if len(x) >= 16000:
                    self._submit(buffer.start_sample / 16000, x, True)
                    last_partial = now
            if self.capture.dropped:
                self.emit("warning", f"Audio input dropped {self.capture.dropped} blocks; timestamps preserve gaps.")
                self.capture.dropped = 0
            if self.capture.status:
                self.emit("warning", self.capture.status)
                self.capture.status = ""
        final = buffer.flush()
        if final:
            self._submit(*final)

    def _file_loop(self, path):
        import soundfile as sf
        from app.audio.features import mono_resample
        # Imported files are intentionally processed locally, without recording the microphone.
        try:
            audio, rate = sf.read(path, dtype="float32")
            audio = mono_resample(audio, rate)
        except (sf.LibsndfileError, RuntimeError):
            # PyAV bundled by faster-whisper decodes local audio/video without
            # shelling out to a system FFmpeg binary or contacting any service.
            from faster_whisper.audio import decode_audio
            audio = decode_audio(str(path), sampling_rate=16000)
        self.emit("status", "Processing local audio file…")
        step = int(PRESETS[self.settings.preset]["chunk_seconds"] * 16000)
        for index in range(0, len(audio), step):
            if self.stop_requested.is_set():
                break
            while self.paused.is_set() and not self.stop_requested.is_set():
                time.sleep(0.1)
            if self.stop_requested.is_set():
                break
            chunk = audio[index:index + step]
            self._features(chunk, (index + len(chunk)) / 16000)
            if self.asr:
                self.jobs.put((index / 16000, chunk.copy(), False))

    def _features(self, audio, timestamp):
        features = prosody(audio)
        with self.state_lock:
            while self.rate_words and self.rate_words[0][1] < timestamp - 20:
                self.rate_words.popleft()
            words = sum(n for start, end, n in self.rate_words)
            span = timestamp - self.rate_words[0][0] if self.rate_words else 0
        features["timestamp"] = timestamp
        if span >= 2 and self.asr is not None:
            features["speaking_rate_wpm"] = float(words * 60 / span)
            features["rate_source"] = "Finalized ASR words over a rolling window including pauses"
        if self.prosody_model:
            features["classification"] = self.prosody_model.predict(mfcc_features(audio))
        if self.emotion_model:
            features["emotion"] = self.emotion_model.predict(audio)
        self.emit("prosody", features)

    def _infer(self):
        while True:
            job = self.jobs.get()
            if job is None:
                break
            offset, audio, partial = job
            try:
                started = time.monotonic()
                with self.gpu_lock:
                    words = self.asr.transcribe(audio, offset, partial)
                    if partial:
                        self.emit("partial", "".join(w.text for w in words).strip())
                        continue
                    turns = self.diarizer.analyze(audio, offset) if self.diarizer else []
                for caption in reconcile_words(words, turns):
                    start = max(0, int((caption.start - offset) * 16000))
                    end = min(len(audio), int((caption.end - offset) * 16000))
                    if end - start >= 1600 and not caption.overlap:
                        voice = prosody(audio[start:end])
                        caption.voice = {k: voice[k] for k in ["f0_hz", "dbfs", "pitch_confidence"]}
                        if self.emotion_model:
                            estimate = self.emotion_model.predict(audio[start:end])
                            caption.voice.update(tone=estimate["tone"], tone_confidence=estimate.get("confidence"))
                    self.emit("caption", caption)
                with self.state_lock:
                    if words:
                        self.rate_words.append((words[0].start, words[-1].end, len(words)))
                self.emit("partial", "")
                self.emit("performance", {"inference_seconds": time.monotonic() - started,
                    "audio_seconds": len(audio) / 16000, "queue_depth": self.jobs.qsize()})
            except Exception as exc:
                self.emit("error", str(exc))

    def pause(self, enabled):
        if enabled:
            self.paused.set()
        else:
            self.paused.clear()
        if self.capture:
            self.capture.paused = enabled
            while not self.capture.queue.empty():
                try:
                    self.capture.queue.get_nowait()
                except queue.Empty:
                    break
        self.emit("status", "Paused" if enabled else "Listening · local processing")

    def stop(self):
        if self.capture:
            self.capture.paused = True
        self.stop_requested.set()
        self.paused.clear()


class CameraEngine:
    def __init__(self, settings, manager=None, emit=None):
        self.settings = settings
        self.manager = manager or ModelManager()
        self.emit = emit or (lambda k, v: None)
        self.stop_requested = threading.Event()
        self.record = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_requested.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import cv2
        from app.video.pose import PoseExtractor
        cap, extractor = None, None
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            if not all(self.manager.installed(m) for m in ["hand-pose", "body-pose"]):
                raise FileNotFoundError("Install hand and body pose assets on Models before using the webcam.")
            extractor = PoseExtractor(self.manager.path("hand-pose") / "model.task", self.manager.path("body-pose") / "model.task")
            model = LocalClassifier(self.manager.path("sign-local") / "best.pt", "sign") if self.manager.installed("sign-local") else None
            cap = cv2.VideoCapture(self.settings.camera)
            if not cap.isOpened():
                raise RuntimeError("Cannot open camera. Check Windows camera permissions and the device index.")
            sequence, was_recording = [], False
            last_frame = 0.0
            self.emit("camera_status", "Webcam ready · record one isolated sign")
            while not self.stop_requested.is_set():
                if time.monotonic() - last_frame < 1 / 15:
                    time.sleep(0.01)
                    continue
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError("Webcam frame unavailable")
                frame = cv2.resize(frame, (640, 480))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                features, points = extractor.extract(rgb)
                self.emit("frame", rgb.copy())
                self.emit("pose", points)
                recording = self.record.is_set()
                if recording:
                    if not was_recording:
                        sequence = []
                    sequence.append(features)
                    if len(sequence) >= 150:
                        self.record.clear()
                        recording = False
                if was_recording and not recording:
                    if len(sequence) < 8:
                        self.emit("camera_status", "Record at least half a second of signing.")
                    elif model is None:
                        self.emit("camera_status", "No ISL checkpoint installed. Import a trained checkpoint on Models.")
                    else:
                        visible = np.mean(np.asarray(sequence).reshape(-1, 49, 4)[:, 7:, 3] > 0.3)
                        if visible < 0.15:
                            self.emit("camera_status", "Hands were not visible enough; please record again.")
                        else:
                            prediction = model.predict(sequence)
                            prediction["accepted"] = prediction["score"] >= self.settings.sign_threshold
                            self.emit("sign", prediction)
                was_recording = recording
                last_frame = time.monotonic()
        except Exception as exc:
            self.emit("error", str(exc))
        finally:
            self.record.clear()
            if cap:
                cap.release()
            if extractor:
                extractor.close()
            self.emit("camera_status", "Webcam stopped")

    def stop(self):
        self.stop_requested.set()
        self.record.clear()
