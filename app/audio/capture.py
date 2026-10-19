import queue
import numpy as np
import threading


class Microphone:
    def __init__(self, device=None):
        self.device = device
        self.queue = queue.Queue(maxsize=200)
        self.stream = None
        self.dropped = 0
        self.status = ""
        self.sequence = 0
        self.paused = False

    def start(self):
        import sounddevice as sd
        self.sequence = 0
        self.paused = False
        def callback(data, count, timing, status):
            if status:
                self.status = str(status)
            # Capture sample index travels with each block so drops cannot compress time.
            item = (self.sequence, data[:, 0].copy())
            self.sequence += count
            if self.paused:
                return
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                self.dropped += 1
        self.stream = sd.InputStream(device=self.device, channels=1, samplerate=16000,
                                     blocksize=320, dtype="float32", callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            stream = self.stream
            self.stream = None
            try:
                stream.stop()
            finally:
                stream.close()


class UtteranceBuffer:
    """20-ms VAD blocks; hard boundaries keep memory and latency bounded."""
    def __init__(self, max_seconds=6, silence_seconds=0.45):
        self.max_seconds = max_seconds
        self.silence_seconds = silence_seconds
        self.blocks = []
        self.preroll = []
        self.start_sample = 0
        self.silent = 0
        self.expected_sample = None
        try:
            import webrtcvad
            self.vad = webrtcvad.Vad(2)
        except ImportError:
            self.vad = None

    def speech(self, block):
        if self.vad and len(block) == 320:
            pcm = (np.clip(block, -1, 1) * 32767).astype(np.int16).tobytes()
            return self.vad.is_speech(pcm, 16000)
        return bool(np.sqrt(np.mean(block ** 2)) > 0.009)

    def flush(self):
        if not self.blocks:
            return None
        audio = np.concatenate(self.blocks)
        start = self.start_sample / 16000
        self.blocks, self.silent = [], 0
        return (start, audio) if len(audio) >= 3200 else None

    def feed(self, sample_index, block):
        discontinuity = self.expected_sample is not None and sample_index != self.expected_sample
        previous = self.flush() if discontinuity else None
        self.expected_sample = sample_index + len(block)
        if discontinuity:
            self.preroll = []
        active = self.speech(block)
        if not self.blocks:
            if not active:
                self.preroll.append((sample_index, block))
                self.preroll = self.preroll[-8:]
                return previous
            self.start_sample = self.preroll[0][0] if self.preroll else sample_index
            self.blocks = [b for i, b in self.preroll]
            self.preroll = []
        self.blocks.append(block)
        self.silent = 0 if active else self.silent + len(block) / 16000
        if self.silent >= self.silence_seconds or sum(len(b) for b in self.blocks) / 16000 >= self.max_seconds:
            return self.flush()
        return previous


class ExternalAudio:
    """16-kHz PCM from a browser; gaps remain visible if the bounded queue drops."""
    def __init__(self):
        self.queue = queue.Queue(maxsize=500)
        self.dropped, self.status, self.sequence = 0, "", 0
        self.paused = False
        self.lock = threading.Lock()
        self.remainder = np.empty(0, np.float32)

    def start(self):
        pass

    def feed(self, samples, start_seconds=None):
        samples = np.asarray(samples, np.float32)
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError("External audio must be finite mono PCM.")
        with self.lock:
            if start_seconds is not None:
                if not np.isfinite(start_seconds) or start_seconds < 0:
                    raise ValueError("Invalid external audio timestamp.")
                start_sample = round(start_seconds * 16000)
                expected = self.sequence + len(self.remainder)
                if start_sample < expected - 1:
                    raise ValueError("External audio packets must arrive in capture order.")
                if abs(start_sample - expected) > 1:
                    self.remainder = np.empty(0, np.float32)
                    self.sequence = start_sample
            joined = np.r_[self.remainder, samples]
            complete = len(joined) // 320 * 320
            self.remainder = joined[complete:].copy()
            for start in range(0, complete, 320):
                item = (self.sequence, joined[start:start + 320].copy())
                self.sequence += 320
                if self.paused:
                    continue
                try:
                    self.queue.put_nowait(item)
                except queue.Full:
                    self.dropped += 1

    def stop(self):
        self.paused = True


class SystemAudio(ExternalAudio):
    """Explicit loopback capture of the selected default output through SoundCard."""
    def __init__(self):
        super().__init__()
        self.stop_requested = threading.Event()
        self.thread = None
        self.started = threading.Event()
        self.start_error = None

    def start(self):
        self.stop_requested.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.started.wait(5):
            self.stop_requested.set()
            raise RuntimeError("System audio capture did not initialize. Use the browser's Share tab audio instead.")
        if self.start_error:
            raise RuntimeError(self.start_error)

    def _run(self):
        try:
            import soundcard as sc
            speaker = sc.default_speaker()
            if speaker is None:
                raise RuntimeError("No default audio output is available.")
            microphone = sc.get_microphone(id=speaker.id, include_loopback=True)
            if microphone is None or not microphone.isloopback:
                raise RuntimeError("The current output does not offer loopback audio. Share a browser tab with audio instead.")
            with microphone.recorder(samplerate=16000) as recorder:
                self.started.set()
                while not self.stop_requested.is_set():
                    recorded = np.asarray(recorder.record(numframes=320), np.float32)
                    self.feed(recorded.mean(axis=1) if recorded.ndim == 2 else recorded)
        except Exception as error:
            self.start_error = str(error)
            self.status = "System audio stopped: " + str(error)
            self.started.set()

    def stop(self):
        self.stop_requested.set()
        super().stop()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
