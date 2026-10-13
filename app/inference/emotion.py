from pathlib import Path
import hashlib
import json

from accessibilityai_upgrade.predict import EmotionModel
from app.utils.paths import project_root, data_root


class VoiceEmotion:
    def __init__(self, path=None):
        selection = data_root() / "emotion_selection.json"
        self.source_name = "Bundled CREMA-D baseline"
        if path is None and selection.exists():
            info = json.loads(selection.read_text(encoding="utf-8"))
            candidate = Path(info["path"]).resolve()
            if not candidate.is_relative_to((data_root() / "models" / "emotion-user").resolve()):
                raise ValueError("Selected emotion model must be in the local model folder.")
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != info["sha256"]:
                raise ValueError("Selected emotion model changed; activate its verified training result again.")
            path = candidate
            self.source_name = info["dataset"]
        self.model = EmotionModel(path or project_root() / "models" / "emotion" / "emotion.joblib")

    def predict(self, audio):
        if not 6400 <= len(audio) <= 480000:
            return {"tone": "uncertain", "confidence": None, "reason": "segment_too_short_or_long"}
        return self.model.predict_samples(audio)
