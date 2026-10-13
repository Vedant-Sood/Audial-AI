"""Classify an enrolled speaker from an ECAPA embedding; research head only."""
import argparse
import json
from pathlib import Path
import soundfile as sf
from app.inference.sign import LocalClassifier
from app.inference.diarization import ECAPADiarizer
from app.audio.features import mono_resample

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--ecapa-path", required=True)
    p.add_argument("--audio", required=True)
    a = p.parse_args()
    audio, rate = sf.read(a.audio, dtype="float32")
    embedding = ECAPADiarizer(Path(a.ecapa_path)).embed(mono_resample(audio, rate))
    print(json.dumps(LocalClassifier(a.checkpoint, "diarization").predict(embedding), indent=2))
