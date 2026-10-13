from dataclasses import dataclass
from pathlib import Path
import threading

import numpy as np


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    probability: float | None = None


class WhisperASR:
    def __init__(self, model_path, device="cpu", compute_type="int8", beam_size=1, language="en"):
        path = Path(model_path)
        if not all((path / name).is_file() for name in ["model.bin", "config.json", "tokenizer.json"]):
            raise FileNotFoundError("Install a complete Whisper model before starting captions.")
        from app.utils.cuda_runtime import configure_cuda_dlls
        configure_cuda_dlls()
        from faster_whisper import WhisperModel
        self.model = WhisperModel(str(path), device=device, compute_type=compute_type,
                                 local_files_only=True, cpu_threads=2, num_workers=1)
        self.beam_size = beam_size
        self.language = language or None
        self.lock = threading.Lock()

    def transcribe(self, audio, offset=0.0, partial=False):
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError("ASR requires finite mono 16-kHz audio.")
        if len(samples) < 1600 or np.sqrt(np.mean(samples ** 2)) < 0.001:
            return []
        words = []
        with self.lock:
            segments, _ = self.model.transcribe(samples, language=self.language,
                beam_size=1 if partial else self.beam_size, word_timestamps=True,
                vad_filter=True, condition_on_previous_text=False, temperature=0.0)
            for segment in segments:
                if segment.words:
                    for word in segment.words:
                        words.append(Word(offset + word.start, offset + word.end, word.word, word.probability))
                elif segment.text.strip():
                    words.append(Word(offset + segment.start, offset + segment.end, segment.text, None))
        return words
