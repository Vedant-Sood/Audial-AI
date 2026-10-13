import json
from pathlib import Path
import queue

import numpy as np
import pytest
import soundfile as sf

from app.audio.capture import ExternalAudio, SystemAudio
from app.audio.features import mono_resample
from app.inference.emotion import VoiceEmotion
from app.services.engine import AudioEngine
from app.services.lexicon import SignLexicon
from app.services.sign_lights import rasterize
from app.storage.transcript import Caption, Session
from app.utils.config import Settings
from app.utils.paths import project_root


def test_queued_speech_is_finalized_when_stopped(monkeypatch):
    engine = AudioEngine(Settings(partial_updates=False))
    engine.capture = ExternalAudio()
    samples, rate = sf.read(project_root() / "assets/evaluation_sample.wav", dtype="float32")
    engine.capture.feed(mono_resample(samples, rate))
    submitted = []
    monkeypatch.setattr(engine, "_submit", lambda offset, audio, partial=False: submitted.append((offset, audio)))
    monkeypatch.setattr(engine, "_features", lambda *args: None)
    engine.stop()
    engine._capture_loop(4)
    assert engine.capture.queue.empty()
    assert submitted and sum(len(audio) for _, audio in submitted) >= 16000
    assert all(offset >= 0 and np.isfinite(audio).all() for offset, audio in submitted)


def test_audio_gaps_and_out_of_order_packets():
    capture = ExternalAudio()
    capture.feed(np.ones(320, np.float32) * .01, 0)
    capture.feed(np.ones(320, np.float32) * .01, 2)
    assert [capture.queue.get()[0], capture.queue.get()[0]] == [0, 32000]
    with pytest.raises(ValueError, match="capture order"):
        capture.feed(np.zeros(320), 1)
    with pytest.raises(ValueError, match="finite"):
        capture.feed(np.full(320, np.nan))


def test_loopback_failure_is_reported_without_any_audio():
    engine = AudioEngine(Settings())
    engine.capture = SystemAudio()
    engine.capture.start_error = "Device disconnected"
    with pytest.raises(RuntimeError, match="Device disconnected"):
        engine._capture_loop(4)


def test_lights_hide_missing_landmarks_and_use_binary_cells():
    points = np.zeros((49, 4), np.float32)
    assert not rasterize(points).any()
    points[1] = [.2, .5, 0, 1]
    points[2] = [.8, .5, 0, 1]
    grid = rasterize(points)
    assert grid.dtype == bool and grid.sum() > 50
    points[2, 3] = 0
    assert rasterize(points).sum() == 1
    with pytest.raises(ValueError):
        rasterize(np.full((49, 4), np.inf))


def test_restored_vocabulary_preserves_unknown_words():
    lexicon = SignLexicon(project_root() / "assets/isl_lexicon/lexicon.json")
    known, missing = lexicon.lookup("Good evening, team. Thank you! Good night. Pleased.")
    assert [entry["gloss"] for entry in known] == ["good evening", "thank you", "good night", "pleased"]
    assert missing == ["team"]
    for entry in known:
        frames = np.load(entry["path"], allow_pickle=False)
        assert frames.shape[1:] == (49, 4) and len(frames) > 1
        assert any(rasterize(frame).any() for frame in frames)


def test_exports_keep_spoken_words_separate_from_voice_estimates(tmp_path):
    session = Session(title="Meeting")
    caption = Caption(.75, 2.25, "Keep the exact words.", "Speaker 1",
                      voice={"f0_hz": 142., "tone": "uncertain"})
    session.add(caption)
    for kind in ("json", "srt", "vtt", "csv", "txt"):
        path = tmp_path / ("meeting." + kind)
        session.export(path, kind)
        assert "Keep the exact words." in path.read_text(encoding="utf-8-sig")
    vtt = (tmp_path / "meeting.vtt").read_text()
    assert "00:00:00.750 --> 00:00:02.250" in vtt
    assert "uncertain" not in vtt
    assert Session.load(tmp_path / "meeting.json").captions[0].voice == caption.voice
    legacy = session.to_dict()
    legacy["captions"][0].pop("voice")
    (tmp_path / "old.json").write_text(json.dumps(legacy))
    assert Session.load(tmp_path / "old.json").captions[0].voice == {}


def test_completed_caption_survives_full_transient_event_queue():
    engine = AudioEngine(Settings())
    for _ in range(engine.events.maxsize):
        engine.emit("partial", "draft")
    caption = Caption(0, 1, "Completed words")
    engine.emit("caption", caption)
    items = [engine.events.get_nowait() for _ in range(engine.events.qsize())]
    assert ("caption", caption) in items


def test_emotion_abstains_on_silence_and_short_segments():
    model = VoiceEmotion()
    assert model.predict(np.zeros(16000, np.float32))["tone"] == "uncertain"
    assert model.predict(np.zeros(100, np.float32))["reason"] == "segment_too_short_or_long"


def test_floating_window_and_manual_step_share_the_light_pose():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.reduce_motion.setChecked(True)
        window.open_floating()
        window.play_signs("thank you good night")
        first = window.pose.points.copy()
        window.step_sign()
        assert not window.pose_timer.isActive()
        assert window.floating_display.canvas.points is window.pose.points
        assert not np.array_equal(first, window.pose.points)
        window.pose_frame_index = len(window.pose_frames)
        window.step_sign()
        assert not window.pose_timer.isActive()
        assert window.pose_frames is not None
    finally:
        window.close()
        application.processEvents()


def test_clipboard_text_uses_signs_without_creating_a_speech_transcript():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    application.clipboard().setText("Good evening, team.")
    window = MainWindow()
    try:
        window.reduce_motion.setChecked(True)
        window.open_floating()
        window.clipboard_signs()
        assert window.sign_text.toPlainText() == "Good evening, team."
        assert "team" in window.lexicon_label.text()
        assert window.pose.points is not None
        assert window.floating_display.caption.text() == "Good evening, team."
        assert not window.session.captions
    finally:
        window.close()
        application.processEvents()
