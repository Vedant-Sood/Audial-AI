import threading

from app.inference.asr import Word
from app.inference.diarization import SpeakerTurn, reconcile_words
from training.evaluation.speech_metrics import wer


def test_word_error_rate():
    assert wer("The experiment needs another trial", "The experiment needs a trial")["wer"] == 0.2
    assert wer("", "inserted")["edits"] == 1


def test_word_timestamps_map_to_turns():
    words = [Word(0, 1, " One", .8), Word(1, 2, " two", .9), Word(2, 3, " reply", .7)]
    captions = reconcile_words(words, [SpeakerTurn(0, 2, "Speaker 1"), SpeakerTurn(2, 3, "Speaker 2")])
    assert len(captions) == 2
    assert captions[0].text == "One two"
    assert captions[0].word_confidence == .8


def test_overlap_words_are_unattributed():
    words = [Word(1, 2, " mixed", .8)]
    turns = [SpeakerTurn(1, 2, "Speaker 1", .7, True), SpeakerTurn(1, 2, "Speaker 2", .7, True)]
    captions = reconcile_words(words, turns)
    assert captions[0].speaker == "Overlap / unattributed"
    assert captions[0].overlap is True


def test_session_language_is_kept_during_model_loading_and_reset_on_restart(monkeypatch):
    from app.services import engine as module
    from app.utils.config import Settings

    settings = Settings(device="cpu")
    engine = module.AudioEngine(settings)
    loading, resume = threading.Event(), threading.Event()
    languages = []

    def delayed_device(*args):
        loading.set()
        assert resume.wait(timeout=5)
        return "cpu"

    def model(path, device, compute_type, beam_size, language):
        languages.append(language)
        return object()

    monkeypatch.setattr(module, "choose_device", delayed_device)
    monkeypatch.setattr(module, "WhisperASR", model)
    monkeypatch.setattr(engine.manager, "installed", lambda _: True)
    monkeypatch.setattr(engine, "_capture_loop", lambda *_: None)
    engine.start(source="browser", language="hi")
    worker = engine.threads[0]
    try:
        assert loading.wait(timeout=5)
        settings.language = "fr"
    finally:
        resume.set()
        worker.join(timeout=5)
    assert not worker.is_alive() and not engine.running
    assert languages == ["hi"]

    engine.start(source="browser")
    engine.threads[0].join(timeout=5)
    assert not engine.running
    assert languages == ["hi", "fr"]
