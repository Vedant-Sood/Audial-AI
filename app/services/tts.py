import queue
import threading


class LocalTTS:
    def __init__(self):
        self.queue = queue.Queue(maxsize=8)
        self.error = None
        self.speaking = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def say(self, text):
        if text.strip():
            if not self.thread.is_alive():
                raise RuntimeError(self.error or "Local speech engine is unavailable")
            self.speaking.set()
            self.queue.put_nowait(text[:4000])

    def _run(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()  # Windows SAPI5; no remote voice service.
            while True:
                text = self.queue.get()
                if text is None:
                    break
                engine.say(text)
                engine.runAndWait()
                if self.queue.empty():
                    self.speaking.clear()
        except Exception as exc:
            self.error = str(exc)
            self.speaking.clear()

    def close(self):
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
