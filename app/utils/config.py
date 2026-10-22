from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from app.utils.paths import atomic_json, data_root
from app.utils.palette import DEFAULT_EMOTION_COLORS, validate_palette

PRESETS = {
    "FAST": {"asr": "whisper-tiny", "compute_type": "int8_float16", "beam_size": 1, "chunk_seconds": 4},
    "BALANCED": {"asr": "whisper-small", "compute_type": "int8_float16", "beam_size": 3, "chunk_seconds": 6},
    "ACCURATE": {"asr": "whisper-medium", "compute_type": "float16", "beam_size": 5, "chunk_seconds": 8},
}


@dataclass
class Settings:
    preset: str = "FAST"
    device: str = "auto"
    language: str = "en"
    microphone: int | None = None
    camera: int = 0
    diarization: str = "off"
    sign_threshold: float = 0.75
    partial_updates: bool = True
    prosody_classifier: bool = False
    auto_speak_sign: bool = False
    sign_language: str = "ISL"
    auto_sign: bool = True
    reduced_motion: bool = False
    sign_speed: float = 1.0
    intensity_colors: list = field(default_factory=lambda: ["#2263ac", "#087f75", "#b75a17"])
    emotion_colors: dict = field(default_factory=lambda: DEFAULT_EMOTION_COLORS.copy())
    # Sanket voice view in browser capture: colours on; cues and tone estimates are opt-in
    voice_colors: bool = True
    voice_cues: bool = False
    voice_tone: bool = False

    def validate(self):
        if self.sign_language != "ISL" or not isinstance(self.auto_sign, bool):
            raise ValueError("The supported sign language is Indian Sign Language (ISL).")
        if self.preset not in PRESETS or self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("Unknown performance preset or device.")
        if self.diarization not in {"off", "ecapa", "pyannote"}:
            raise ValueError("Unknown speaker backend.")
        if not isinstance(self.sign_threshold, (int, float)) or not 0 <= self.sign_threshold <= 1:
            raise ValueError("Invalid sign threshold.")
        if not isinstance(self.sign_speed, (int, float)) or not 0.25 <= self.sign_speed <= 2:
            raise ValueError("Invalid playback speed.")
        if self.microphone is not None and (not isinstance(self.microphone, int) or self.microphone < 0):
            raise ValueError("Invalid microphone index.")
        if not isinstance(self.camera, int) or self.camera < 0:
            raise ValueError("Invalid camera index.")
        if not isinstance(self.intensity_colors, list) or len(self.intensity_colors) != 3:
            raise ValueError("Intensity colours must be a list of three values.")
        validate_palette(self.emotion_colors)
        if not all(isinstance(v, bool) for v in (self.voice_colors, self.voice_cues, self.voice_tone)):
            raise ValueError("Voice view preferences must be true or false.")
        return self

    def save(self, path=None):
        self.validate()
        atomic_json(path or data_root() / "settings.json", asdict(self))

    @classmethod
    def load(cls, path=None):
        target = Path(path or data_root() / "settings.json")
        if not target.exists():
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Settings must be an object.")
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__}).validate()
        except (TypeError, ValueError, OSError) as error:
            raise ValueError("Could not read settings.") from error
