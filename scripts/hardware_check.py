import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import psutil
from app.utils.paths import atomic_json, data_root


def hardware_report(probe_camera=True):
    report = {"os": platform.platform(), "python": sys.version, "cpu": platform.processor(),
        "cpu_logical_cores": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 2),
        "disk_free_gb": round(shutil.disk_usage(data_root()).free / 2**30, 2), "nvidia_gpus": [], "cuda_available": False}
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        for line in proc.stdout.strip().splitlines():
            fields = [s.strip() for s in line.split(",")]
            if len(fields) == 4:
                report["nvidia_gpus"].append(dict(zip(["name", "vram_mb", "driver", "utilization_percent"], fields)))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import torch
        report.update(torch_version=torch.__version__, torch_cuda_build=torch.version.cuda, cuda_available=torch.cuda.is_available())
        if torch.cuda.is_available():
            report["torch_gpu_name"] = torch.cuda.get_device_name(0)
            report["torch_gpu_vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2)
    except Exception as exc:
        report["torch_error"] = str(exc)
    try:
        import sounddevice as sd
        report["microphones"] = [{"index": i, "name": d["name"], "channels": d["max_input_channels"], "sample_rate": d["default_samplerate"]}
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    except Exception as exc:
        report["microphone_error"] = str(exc)
    if probe_camera:
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            try:
                ok, frame = cap.read()
                report["camera_0"] = {"available": bool(ok), "resolution": list(frame.shape[:2]) if ok else None}
            finally:
                cap.release()
        except Exception as exc:
            report["camera_error"] = str(exc)
    gpu_ram = report.get("torch_gpu_vram_gb", 0)
    report["recommended_preset"] = "BALANCED" if report["cuda_available"] and gpu_ram >= 6 and report["ram_gb"] >= 16 else "FAST"
    report["accurate_preset"] = "Eligible for local testing" if gpu_ram >= 8 and report["ram_gb"] >= 24 else "Measure memory before selecting"
    return report


def main():
    report = hardware_report()
    path = data_root() / "hardware_report.json"
    atomic_json(path, report)
    print(json.dumps(report, indent=2))
    print("Saved", path)


if __name__ == "__main__":
    main()
