"""Shared PyTorch trainer. Requires real-data provenance in the NPZ sidecar."""
import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import random
import subprocess
import time
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
import yaml
from app.utils.paths import atomic_json
from app.models.manager import file_hash
from app.video.pose import POSE_SCHEMA
from training.networks import make_model


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(2)


def load_data(path, task):
    path = Path(path)
    provenance = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if not provenance.get("real_data") or not provenance.get("source_url") or not provenance.get("license"):
        raise ValueError("Training requires real-data source and license metadata")
    if task == "sign" and provenance.get("language") != "ISL":
        raise ValueError("Sign data must explicitly declare ISL")
    data = np.load(path, allow_pickle=False)
    x, y, split = data["X"].astype(np.float32), data["y"].astype(np.int64), data["split"].astype(str)
    labels = data["labels"].astype(str).tolist()
    groups = data["groups"].astype(str) if "groups" in data else None
    if not len(labels) or len(x) != len(y) or len(y) != len(split) or not np.isfinite(x).all():
        raise ValueError("Dataset dimensions / finite values are invalid")
    if y.min() < 0 or y.max() >= len(labels):
        raise ValueError("Label index outside declared vocabulary")
    if not set(split) <= {"train", "val", "test"}:
        raise ValueError("Only train, val and test splits are allowed")
    if not all(np.any(split == s) for s in ["train", "val", "test"]):
        raise ValueError("Require nonempty training, validation and held-out test partitions")
    expected_dim = 196 if task == "sign" else 80 if task == "prosody" else 192
    if x.shape[-1] != expected_dim or x.ndim != (3 if task == "sign" else 2):
        raise ValueError("Input feature schema mismatch")
    if provenance.get("group_disjoint"):
        if groups is None or len(groups) != len(y):
            raise ValueError("Group identifiers missing")
        sets = [set(groups[split == s]) for s in ["train", "val", "test"]]
        if sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2]:
            raise ValueError("Actor/signer leakage across splits")
    return x, y, split, labels, provenance


def metrics(y, pred, classes):
    matrix = np.zeros((classes, classes), dtype=int)
    for a, b in zip(y, pred):
        matrix[int(a), int(b)] += 1
    f1 = []
    for i in range(classes):
        tp = matrix[i, i]
        f1.append(float(2 * tp / max(1, matrix[i, :].sum() + matrix[:, i].sum())))
    return {"accuracy": float(np.mean(np.asarray(y) == pred)), "macro_f1": float(np.mean(f1)),
            "confusion_matrix": matrix.tolist(), "samples": len(y)}


def evaluate_batches(model, loader, device):
    model.eval()
    loss, count, target, predictions = 0.0, 0, [], []
    with torch.inference_mode():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss += float(torch.nn.functional.cross_entropy(logits, y).item()) * len(y)
            count += len(y)
            target.extend(y.cpu().tolist())
            predictions.extend(logits.argmax(1).cpu().tolist())
    return loss / max(count, 1), target, predictions


def atomic_torch(path, checkpoint):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    torch.save(checkpoint, tmp)
    tmp.replace(path)


def train(config, task, resume=None, control_path=None):
    seed_all(int(config.get("seed", 42)))
    out = Path(config["output"])
    out.mkdir(parents=True, exist_ok=True)
    x, y, split, labels, provenance = load_data(config["data"], task)
    device = "cuda" if config.get("device", "auto") in {"auto", "cuda"} and torch.cuda.is_available() else "cpu"
    if config.get("device") == "cuda" and device != "cuda":
        raise RuntimeError("CUDA was requested but is unavailable")
    if task != "sign":
        mean, std = x[split == "train"].mean(axis=0), x[split == "train"].std(axis=0)
        x = (x - mean) / np.maximum(std, 1e-6)
    else:
        mean, std = np.zeros(x.shape[-1]), np.ones(x.shape[-1])
    model_config = config.get("model", {})
    model = make_model(task, model_config, len(labels)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(config.get("learning_rate", 0.001)), weight_decay=float(config.get("weight_decay", 0.01)))
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3)
    use_amp = device == "cuda" and config.get("precision", "fp16") in {"fp16", "bf16"}
    dtype = torch.bfloat16 if config.get("precision") == "bf16" else torch.float16
    if dtype == torch.bfloat16 and device == "cuda" and not torch.cuda.is_bf16_supported():
        dtype = torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp and dtype == torch.float16)
    start_epoch, best, bad_epochs = 0, math.inf, 0
    signature = file_hash(config["data"])
    if resume:
        state = torch.load(resume, map_location="cpu", weights_only=True)
        if state["data_sha256"] != signature or state["task"] != task or state["model_config"] != model_config:
            raise ValueError("Resume checkpoint does not match data / task / architecture")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        scaler.load_state_dict(state["scaler"])
        start_epoch, best, bad_epochs = state["epoch"], state["best"], state["bad_epochs"]
        torch.set_rng_state(state["torch_rng"])
        if device == "cuda" and state.get("cuda_rng"):
            torch.cuda.set_rng_state_all(state["cuda_rng"])
    batch = int(config.get("batch_size", 16))
    accum = max(1, int(config.get("gradient_accumulation", 1)))
    def loader(part, shuffle=False):
        mask = split == part
        return DataLoader(TensorDataset(torch.from_numpy(x[mask]), torch.from_numpy(y[mask])),
            batch_size=batch, shuffle=shuffle, num_workers=int(config.get("workers", 0)), pin_memory=device == "cuda")
    if resume:
        # DataLoader creates a random base seed even without shuffling. A
        # diagnostic loss measurement must not advance the restored RNG state.
        with torch.random.fork_rng(devices=[0] if device == "cuda" else []):
            initial_loss, _, _ = evaluate_batches(model, loader("train"), device)
    else:
        initial_loss, _, _ = evaluate_batches(model, loader("train"), device)
    started = time.monotonic()
    history = []
    writer = None
    if config.get("tensorboard", True):
        from torch.utils.tensorboard import SummaryWriter
        writer = SummaryWriter(str(out / "tensorboard"))
    metadata = {"task": task, "labels": labels, "model_config": model_config, "mean": mean.tolist(),
        "std": std.tolist(), "temperature": 1.0, "language": "ISL" if task == "sign" else None,
        "pose_schema": POSE_SCHEMA if task == "sign" else None, "feature_schema": "mfcc40_mean_std_v1" if task == "prosody" else None,
        "data_sha256": signature, "provenance": provenance, "experimental": True}
    command = "run"
    for epoch in range(start_epoch, int(config.get("epochs", 25))):
        model.train()
        train_loss, samples = 0.0, 0
        optimizer.zero_grad(set_to_none=True)
        train_loader = loader("train", True)
        for i, (xb, yb) in enumerate(train_loader):
            xb, yb = xb.to(device), yb.to(device)
            amp = torch.autocast(device_type="cuda", dtype=dtype) if use_amp else nullcontext()
            with amp:
                logits = model(xb)
                raw_loss = torch.nn.functional.cross_entropy(logits, yb)
                # Last accumulation group may be shorter.
                group_size = min(accum, len(train_loader) - (i // accum) * accum)
                loss = raw_loss / group_size
            if not torch.isfinite(loss):
                raise FloatingPointError("Non-finite training loss; latest epoch checkpoint remains valid")
            scaler.scale(loss).backward()
            if (i + 1) % accum == 0 or i + 1 == len(train_loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            train_loss += float(raw_loss.item()) * len(yb)
            samples += len(yb)
        val_loss, actual, pred = evaluate_batches(model, loader("val"), device)
        scores = metrics(actual, pred, len(labels))
        scheduler.step(val_loss)
        improved = val_loss < best
        bad_epochs = 0 if improved else bad_epochs + 1
        best = min(best, val_loss)
        checkpoint = {**metadata, "model": {k: v.cpu() for k, v in model.state_dict().items()},
            "epoch": epoch + 1, "best": best, "bad_epochs": bad_epochs,
            "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(), "scaler": scaler.state_dict(),
            "torch_rng": torch.get_rng_state(), "cuda_rng": torch.cuda.get_rng_state_all() if device == "cuda" else []}
        atomic_torch(out / "latest.pt", checkpoint)
        if improved:
            atomic_torch(out / "best.pt", {**metadata, "model": checkpoint["model"], "epoch": epoch + 1})
        if (epoch + 1) % int(config.get("checkpoint_interval", 5)) == 0:
            atomic_torch(out / f"epoch_{epoch + 1:04}.pt", checkpoint)
            for old in sorted(out.glob("epoch_*.pt"))[:-int(config.get("keep_checkpoints", 2))]:
                old.unlink()
        elapsed = time.monotonic() - started
        event = {"status": "running", "task": task, "epoch": epoch + 1, "loss": train_loss / samples,
            "validation_loss": val_loss, "validation_macro_f1": scores["macro_f1"], "validation_accuracy": scores["accuracy"],
            "elapsed_seconds": elapsed, "eta_seconds": elapsed / (epoch + 1 - start_epoch) * (int(config.get("epochs", 25)) - epoch - 1),
            "device": device, "vram_mb": torch.cuda.memory_allocated() / 2**20 if device == "cuda" else 0}
        event["gpu_utilization_percent"] = None
        if device == "cuda":
            try:
                gpu = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2)
                event["gpu_utilization_percent"] = float(gpu.stdout.strip().splitlines()[0])
            except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
                pass
        event["gpu_usage_note"] = "Whole device utilization sampled at epoch end; includes other processes"
        history.append(event)
        atomic_json(out / "progress.json", event)
        print(json.dumps(event), flush=True)
        if writer:
            for k in ["loss", "validation_loss", "validation_macro_f1"]:
                writer.add_scalar(k, event[k], epoch + 1)
        # Controls are honored at complete epoch boundaries; optimizer checkpoints are consistent.
        while control_path:
            try:
                command = json.loads(Path(control_path).read_text()).get("command", "run")
            except (FileNotFoundError, ValueError):
                command = "run"
            if command != "pause":
                break
            atomic_json(out / "progress.json", {**event, "status": "paused; checkpoint saved"})
            time.sleep(0.2)
        if command == "stop" or bad_epochs >= int(config.get("patience", 8)):
            break
    if not (out / "best.pt").exists():
        raise ValueError("No epochs ran. Increase epochs beyond the resumed epoch.")
    best_checkpoint = torch.load(out / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(best_checkpoint["model"])
    test_loss, actual, pred = evaluate_batches(model, loader("test"), device)
    train_final, _, _ = evaluate_batches(model, loader("train"), device)
    result = {"status": "stopped" if command == "stop" else "completed", "task": task, "device": device,
        "initial_training_loss": initial_loss, "final_training_loss": train_final,
        "loss_decreased": train_final < initial_loss, "test_loss": test_loss,
        "test": metrics(actual, pred, len(labels)), "labels": labels, "history": history,
        "data_sha256": signature, "provenance": provenance, "elapsed_seconds": time.monotonic() - started}
    atomic_json(out / "results.json", result)
    atomic_json(out / "progress.json", {**(history[-1] if history else {}), "status": result["status"]})
    if writer:
        writer.close()
    return result


def main(task):
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--resume")
    p.add_argument("--control")
    args = p.parse_args()
    config = yaml.safe_load(Path(args.config).read_text())
    try:
        train(config, task, args.resume, args.control)
    except torch.cuda.OutOfMemoryError:
        print("CUDA OOM. Close live inference, halve batch_size and increase gradient_accumulation. Resume latest.pt.", flush=True)
        raise
