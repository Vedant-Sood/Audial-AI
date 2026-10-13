"""Run locally: actual tests are PASS/FAIL/SKIP, never substituted cloud results."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import threading
import time
import numpy as np
import psutil
from app.utils.paths import atomic_json, data_root, project_root
from app.models.manager import ModelManager
from scripts.hardware_check import hardware_report


def validate(output=None, sample=None, capture=True, speak=True, model_root=None):
    output = Path(output or data_root())
    output.mkdir(parents=True, exist_ok=True)
    manager = ModelManager(model_root)
    result = {"environment": "LOCAL WINDOWS" if sys.platform == "win32" else "CLOUD / NON-WINDOWS",
        "timestamp": datetime.now(timezone.utc).isoformat(), "hardware": hardware_report(probe_camera=capture), "tests": {},
        "local_hardware_benchmarked": sys.platform == "win32"}
    models = {}
    audio = None
    sample = Path(sample) if sample else project_root() / "assets" / "evaluation_sample.wav"
    if sample.is_file():
        import soundfile as sf
        from app.audio.features import mono_resample
        audio, rate = sf.read(sample, dtype="float32")
        audio = mono_resample(audio, rate)
    def run(name, function, skip=None):
        if skip:
            result["tests"][name] = {"status": "SKIP", "reason": skip}
            return
        started = time.monotonic()
        before_cpu = time.process_time()
        try:
            details = function()
            result["tests"][name] = {"status": "PASS", "seconds": time.monotonic() - started, "details": details}
        except Exception as exc:
            result["tests"][name] = {"status": "FAIL", "seconds": time.monotonic() - started, "error": str(exc)}
        result["tests"][name]["cpu_seconds"] = time.process_time() - before_cpu
        try:
            # A cloud process namespace can map os.getpid() to a different host
            # process in /proc. Do not report that process's small RSS as ours.
            if sys.platform.startswith("linux"):
                status = Path("/proc/self/status").read_text()
                rss_line = next(line for line in status.splitlines() if line.startswith("VmRSS:"))
                result["tests"][name]["ram_rss_mb"] = int(rss_line.split()[1]) / 1024
                result["tests"][name]["ram_source"] = "/proc/self/status"
            else:
                result["tests"][name]["ram_rss_mb"] = psutil.Process().memory_info().rss / 2**20
        except (psutil.Error, OSError, StopIteration, ValueError):
            # Some cloud PID namespaces cannot be inspected by psutil.
            try:
                import resource
                result["tests"][name]["ram_peak_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                result["tests"][name]["ram_note"] = "Peak RSS from resource; current RSS unavailable in this cloud namespace"
            except ImportError:
                result["tests"][name]["ram_note"] = "Process memory unavailable"
        print(name, result["tests"][name]["status"], flush=True)
    import torch
    torch.set_num_threads(2)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    run("cuda", lambda: {"name": torch.cuda.get_device_name(0), "tensor_sum": float((torch.ones(4, device="cuda") * 2).sum().cpu())}, None if device == "cuda" else "CUDA unavailable")
    def asr():
        from app.inference.asr import WhisperASR
        chosen = next(m for m in ["whisper-small", "whisper-tiny", "whisper-medium"] if manager.installed(m))
        start = time.monotonic()
        models["asr"] = WhisperASR(manager.path(chosen), device, "int8_float16" if device == "cuda" else "int8")
        load_time = time.monotonic() - start
        start = time.monotonic()
        words = models["asr"].transcribe(audio)
        infer_time = time.monotonic() - start
        if not words:
            raise ValueError("No words recognized in the supplied speech sample")
        return {"model": chosen, "device": device, "load_seconds": load_time, "inference_seconds": infer_time,
                "rtf": infer_time / max(len(audio) / 16000, 1e-6), "word_count": len(words), "nonempty": bool(words)}
    run("whisper", asr, "No local ASR model / sample" if audio is None or not any(manager.installed(m) for m in ["whisper-tiny", "whisper-small", "whisper-medium"]) else None)
    def diarizer():
        from app.inference.diarization import ECAPADiarizer
        start = time.monotonic()
        models["diarizer"] = ECAPADiarizer(manager.path("ecapa"), "cpu")
        load_time = time.monotonic() - start
        start = time.monotonic()
        turns = models["diarizer"].analyze(audio)
        if not turns:
            raise ValueError("No speech turns detected in the supplied speech sample")
        return {"load_seconds": load_time, "inference_seconds": time.monotonic() - start,
            "turns": len(turns), "der": None, "note": "Inference check; DER requires annotated multi-speaker reference"}
    run("diarization", diarizer, "ECAPA / sample missing" if not manager.installed("ecapa") or audio is None else None)
    def feature_test():
        from app.audio.features import prosody
        f = prosody(audio)
        if not np.isfinite(f["dbfs"]):
            raise ValueError("Non-finite features")
        return {k: v for k, v in f.items() if k not in ["waveform", "f0_curve"]}
    run("prosody", feature_test, "No sample" if audio is None else None)
    def sign_test():
        from app.inference.sign import LocalClassifier
        path = project_root() / "assets" / "sign_evaluation.npy"
        features = np.load(path, allow_pickle=False)
        models["sign"] = LocalClassifier(manager.path("sign-local") / "best.pt", "sign")
        return models["sign"].predict(features)
    run("sign_recognition", sign_test, "ISL checkpoint / real pose sample missing" if not manager.installed("sign-local") or not (project_root() / "assets" / "sign_evaluation.npy").is_file() else None)
    def webcam():
        import cv2
        cap = cv2.VideoCapture(0)
        try:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Webcam could not provide a frame")
            details = {"resolution": list(frame.shape[:2])}
            if manager.installed("hand-pose") and manager.installed("body-pose"):
                from app.video.pose import PoseExtractor
                pose = PoseExtractor(manager.path("hand-pose") / "model.task", manager.path("body-pose") / "model.task")
                try:
                    features, points = pose.extract(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    details["feature_dimensions"] = len(features)
                finally:
                    pose.close()
            return details
        finally:
            cap.release()
    run("webcam_and_pose", webcam, None if capture else "Physical device capture disabled")
    def mic():
        import sounddevice as sd
        recording = sd.rec(32000, samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        return {"samples": len(recording), "rms": float(np.sqrt(np.mean(recording ** 2)))}
    run("microphone", mic, None if capture else "Physical device capture disabled")
    def tts():
        import pyttsx3
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        if not voices:
            raise RuntimeError("No local voices installed")
        if speak:
            engine.say("Accessibility AI local speech test.")
            engine.runAndWait()
        return {"voices": len(voices), "speech_requested": speak, "heard_by_user": "requires listening confirmation"}
    run("tts", tts, None if capture else "Physical audio output disabled")
    def combined():
        from app.inference.diarization import reconcile_words
        from app.audio.features import prosody
        start = time.monotonic()
        words = models["asr"].transcribe(audio)
        turns = models["diarizer"].analyze(audio)
        features = prosody(audio)
        captions = reconcile_words(words, turns)
        if not captions:
            raise ValueError("Combined pipeline produced no captions")
        return {"captions": len(captions), "rtf": (time.monotonic() - start) / (len(audio) / 16000),
                "f0_hz": features["f0_hz"], "note": "Finite local sample; live devices and sustained latency need their own tests"}
    run("combined_pipeline", combined, None if "asr" in models and "diarizer" in models else "ASR / diarization did not load")
    result["cuda_peak_allocated_mb"] = torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else None
    if device == "cuda":
        try:
            proc = __import__('subprocess').run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
            result["device_total_used_vram_mb"] = proc.stdout.strip()
        except Exception:
            pass
    # CTranslate2 allocations are not included in PyTorch's memory counter.
    result["vram_note"] = "PyTorch peak excludes CTranslate2; nvidia-smi reports whole-device use, including other processes"
    prefix = "local" if sys.platform == "win32" else "cloud"
    atomic_json(output / f"{prefix}_benchmark_results.json", result)
    lines = [f"# {result['environment']} validation", "", f"Timestamp: {result['timestamp']}", "", "| Check | Status | Seconds |", "|---|---|---|"]
    lines += [f"| {k} | {v['status']} | {v.get('seconds', 0):.3f} |" for k, v in result["tests"].items()]
    lines += ["", "See JSON for errors, skip reasons and measured load/inference times. Skipped checks have no performance result.", "", result["vram_note"]]
    (output / f"{prefix}_benchmark_results.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main():
    result = validate()
    print(json.dumps(result, indent=2))
    print("Reports saved to", data_root())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output")
    p.add_argument("--sample")
    p.add_argument("--model-root")
    p.add_argument("--no-capture", action="store_true")
    p.add_argument("--no-speak", action="store_true")
    a = p.parse_args()
    validate(a.output, a.sample, not a.no_capture, not a.no_speak, a.model_root)
