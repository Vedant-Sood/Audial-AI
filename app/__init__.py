"""AccessibilityAI: local captions, Indian Sign Language, and acoustic analysis."""
import os

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("WANDB_DISABLED", "true")
__version__ = "0.3.1"
