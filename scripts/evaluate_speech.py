import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import soundfile as sf
from app.audio.features import mono_resample
from app.inference.asr import WhisperASR
from app.inference.diarization import ECAPADiarizer
from training.evaluation.speech_metrics import wer, diarization_metrics
from app.utils.paths import atomic_json


def evaluate(manifest, asr_path, ecapa_path=None, device="cpu"):
    """JSON list: audio, text, optional reference_turns. Reference paths relative to JSON."""
    manifest = Path(manifest)
    rows = json.loads(manifest.read_text())
    asr = WhisperASR(Path(asr_path), device, "int8_float16" if device == "cuda" else "int8")
    outputs, edits, count = [], 0, 0
    for row in rows:
        audio, rate = sf.read(manifest.parent / row["audio"], dtype="float32")
        audio = mono_resample(audio, rate)
        started = time.monotonic()
        words = asr.transcribe(audio)
        elapsed = time.monotonic() - started
        hypothesis = "".join(w.text for w in words).strip()
        score = wer(row["text"], hypothesis)
        edits += score["edits"]
        count += score["reference_words"]
        item = {"audio": row["audio"], "reference": row["text"], "hypothesis": hypothesis,
            **score, "seconds": elapsed, "rtf": elapsed / max(len(audio) / 16000, 1e-6)}
        if ecapa_path and row.get("reference_turns"):
            diarizer = ECAPADiarizer(Path(ecapa_path))
            turns = [asdict(t) for t in diarizer.analyze(audio)]
            item["diarization"] = diarization_metrics(row["reference_turns"], turns, len(audio) / 16000)
        outputs.append(item)
    return {"samples": len(outputs), "wer": edits / max(1, count), "edits": edits, "reference_words": count,
        "results": outputs, "device": device, "note": "Corpus metrics apply only to this declared reference set"}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--asr-path", required=True)
    p.add_argument("--ecapa-path")
    p.add_argument("--device", default="cpu")
    p.add_argument("--output", default="speech_evaluation.json")
    a = p.parse_args()
    atomic_json(a.output, evaluate(a.manifest, a.asr_path, a.ecapa_path, a.device))
