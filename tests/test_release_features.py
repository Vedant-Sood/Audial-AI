"""User-facing regression checks for the desktop accessibility update."""
import json
from pathlib import Path
import numpy as np
import pytest

from app.services.lexicon import SignLexicon
from app.services.text_input import read_text
from app.utils.config import Settings
from app.utils.palette import DEFAULT_EMOTION_COLORS, foreground
from app.utils.paths import project_root
from scripts.train_indian_emotion import speaker_splits


def test_emotion_palette_migrates_and_rejects_invalid_css(tmp_path):
    path = tmp_path / "old-settings.json"
    path.write_text(json.dumps({"preset": "FAST", "language": "hi"}))
    settings = Settings.load(path)
    assert settings.emotion_colors == DEFAULT_EMOTION_COLORS
    settings.emotion_colors["happy"] = "#000000"
    settings.save(path)
    assert Settings.load(path).emotion_colors["happy"] == "#000000"
    settings.emotion_colors["sad"] = "red; background:url(remote)"
    with pytest.raises(ValueError, match="RRGGBB"):
        settings.save(path)


def test_saved_palette_appears_in_native_emotion_view(monkeypatch):
    from PySide6.QtWidgets import QApplication, QColorDialog
    from PySide6.QtGui import QColor
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#000000"))
    try:
        window.pick_emotion_color("happy")
        window.save_settings()
        panel = window.tone_panels[0]
        panel.show_emotion({"tone": "happy", "confidence": .8, "reason": None})
        assert panel.emotion_badge.text() == "Happy"
        assert "#000000" in panel.emotion_badge.styleSheet()
        assert "#ffffff" in panel.emotion_badge.styleSheet()
        assert Settings.load().emotion_colors["happy"] == "#000000"
    finally:
        window.close(); application.processEvents()


def test_hindi_and_unknown_text_keep_playback_order():
    lexicon = SignLexicon(project_root() / "assets/isl_lexicon/lexicon.json")
    steps = lexicon.plan("धन्यवाद टीम! good night 👋")
    assert [s["kind"] for s in steps] == ["sign", "text", "sign", "text"]
    assert steps[0]["entry"]["gloss"] == "thank you"
    assert steps[1]["text"] == "टीम!"
    assert steps[3]["text"] == "👋"
    assert lexicon.lookup("शुभ रात्रि धन्यवाद")[1] == []


def test_native_unknown_text_can_be_stepped_to_the_next_sign():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.reduce_motion.setChecked(True)
        window.play_signs("team thank you")
        assert window.pose.points is None
        assert "team" in window.sign_fallback.text()
        window.step_sign()
        assert window.pose.points is not None
        assert "thank you" in window.sign_fallback.text()
        window.stop_playback()
        window.step_sign()
        assert window.pose.points is None
    finally:
        window.close(); application.processEvents()


def test_subtitles_and_saved_transcripts_become_plain_text(tmp_path):
    path = tmp_path / "captions.vtt"
    path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<b>धन्यवाद</b> team\n\nNOTE Metadata\nnot a caption\n", encoding="utf-8")
    assert read_text(path) == "धन्यवाद team"
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"captions": [{"text": "Thank you!"}]}))
    assert read_text(path) == "Thank you!"


def test_training_never_shares_speakers_across_partitions():
    emotions = ["angry", "disgust", "fear", "happy", "neutral", "sad"]
    speakers = np.repeat([str(i) for i in range(20)], 6)
    labels = np.tile(emotions, 20)
    groups, splits = speaker_splits(speakers, labels)
    for name, indices in splits.items():
        assert set(speakers[indices]) == set(groups[name])
        for other in groups:
            if other != name:
                assert set(groups[name]).isdisjoint(groups[other])
    with pytest.raises(ValueError, match="15 speakers"):
        speaker_splits(speakers[:24], labels[:24])
