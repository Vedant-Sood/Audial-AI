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
