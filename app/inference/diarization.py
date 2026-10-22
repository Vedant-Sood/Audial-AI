from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.inference.asr import Word
from app.storage.transcript import Caption


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str
    similarity: float | None = None
    overlap: bool = False


def reconcile_words(words, turns):
    """Attribute words by interval overlap; preserve text and mark mixed speech."""
    captions = []
    for word in words:
        intersecting = [(turn, max(0, min(word.end, turn.end) - max(word.start, turn.start))) for turn in turns]
        intersecting = [(turn, span) for turn, span in intersecting if span > 0]
        overlap = any(turn.overlap for turn, span in intersecting)
        speaker, similarity = "Unattributed", None
        if overlap:
            speaker = "Overlap / unattributed"
        elif intersecting:
            best, _ = max(intersecting, key=lambda item: item[1])
            speaker, similarity = best.speaker, best.similarity
        if captions and captions[-1].speaker == speaker and captions[-1].overlap == overlap and word.start - captions[-1].end < 1.2:
            caption = captions[-1]
            separator = "" if word.text[:1].isspace() or word.text[:1] in ",.!?:;" else " "
            caption.text += separator + word.text
            caption.end = max(caption.end, word.end)
            if word.probability is not None:
                caption.word_confidence = word.probability if caption.word_confidence is None else min(caption.word_confidence, word.probability)
        else:
            captions.append(Caption(word.start, word.end, word.text.strip(), speaker, word.probability, similarity, overlap))
    return captions


class ECAPADiarizer:
    """Offline ECAPA embeddings with session-only centroid matching."""
    def __init__(self, model_path, device="cpu", threshold=0.7):
        import torch
        from hyperpyyaml import load_hyperpyyaml
        path = Path(model_path)
        required = ["hyperparams.yaml", "embedding_model.ckpt", "mean_var_norm_emb.ckpt"]
        if not all((path / name).is_file() for name in required):
            raise FileNotFoundError("A complete local ECAPA model is required.")
        with (path / "hyperparams.yaml").open() as source:
            hparams = load_hyperpyyaml(source, {"pretrained_path": str(path)})
        modules = hparams["modules"]
        self.feature = modules["compute_features"].to(device)
        self.feature_norm = modules["mean_var_norm"].to(device)
        self.embedding = modules["embedding_model"].to(device).eval()
        self.embedding.load_state_dict(torch.load(path / "embedding_model.ckpt", map_location=device, weights_only=True))
        self.embedding_norm = modules["mean_var_norm_emb"].to(device)
        # SpeechBrain's normalizer checkpoint is a statistics dictionary,
        # restored through its registered checkpoint loader.
        self.embedding_norm._load(path / "mean_var_norm_emb.ckpt")
        self.embedding_norm.to(device)
        self.device, self.threshold = device, threshold
        self.centroids, self.counts = [], []

    def embed(self, audio):
        import torch
        values = np.asarray(audio, dtype=np.float32)
        if values.ndim != 1 or len(values) < 8000 or not np.isfinite(values).all():
            raise ValueError("Speaker embeddings need at least half a second of finite mono speech.")
        with torch.inference_mode():
            signal = torch.from_numpy(values)[None].to(self.device)
            lengths = torch.ones(1, device=self.device)
            features = self.feature_norm(self.feature(signal), lengths)
            embedding = self.embedding(features, lengths)
            embedding = self.embedding_norm(embedding, lengths).reshape(-1).cpu().numpy()
        norm = float(np.linalg.norm(embedding))
        if norm < 1e-8:
            raise ValueError("Speaker embedding has near-zero norm; audio may be silence.")
        return embedding / norm

    def identify(self, embedding):
        similarities = [float(np.dot(embedding, centroid)) for centroid in self.centroids]
        index = int(np.argmax(similarities)) if similarities else 0
        score = max(similarities) if similarities else None
        if score is None or score < self.threshold:
            if len(self.centroids) >= 20:
                return "Unattributed", score
            self.centroids.append(embedding.copy())
            self.counts.append(1)
            index = len(self.centroids) - 1
        else:
            merged = self.centroids[index] * self.counts[index] + embedding
            self.centroids[index] = merged / max(float(np.linalg.norm(merged)), 1e-8)
            self.counts[index] += 1
        return f"Speaker {index + 1}", score

    def analyze(self, audio, offset=0):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        speech = get_speech_timestamps(np.asarray(audio, dtype=np.float32), VadOptions(min_silence_duration_ms=300))
        turns = []
        for interval in speech:
            start, end = interval["start"], interval["end"]
            if end - start < 8000:
                continue
            speaker, score = self.identify(self.embed(audio[start:end]))
            turns.append(SpeakerTurn(offset + start / 16000, offset + end / 16000, speaker, score))
        return turns


class OverlapDiarizer:
    def __init__(self, model_path, ecapa_path, device="cpu"):
        from pyannote.audio import Pipeline
        self.pipeline = Pipeline.from_pretrained(str(Path(model_path)))
        import torch
        self.pipeline.to(torch.device(device))
        self.ecapa = ECAPADiarizer(ecapa_path, device)

    def analyze(self, audio, offset=0):
        import torch
        output = self.pipeline({"waveform": torch.from_numpy(np.asarray(audio, np.float32))[None], "sample_rate": 16000})
        annotation = getattr(output, "speaker_diarization", output)
        intervals = [(segment.start, segment.end) for segment, _, _ in annotation.itertracks(yield_label=True)]
        turns = []
        for index, (start, end) in enumerate(intervals):
            mixed = any(max(start, a) < min(end, b) for j, (a, b) in enumerate(intervals) if j != index)
            sample_start = max(0, int(start * 16000))
            sample_end = min(len(audio), int(end * 16000))
            if mixed or end - start < 0.5 or sample_end - sample_start < 8000:
                speaker, score = "Overlap / unattributed" if mixed else "Unattributed", None
            else:
                speaker, score = self.ecapa.identify(self.ecapa.embed(audio[sample_start:sample_end]))
            turns.append(SpeakerTurn(offset + start, offset + end, speaker, score, mixed))
        return turns
