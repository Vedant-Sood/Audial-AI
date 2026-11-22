import pytest
from app.utils.config import Settings


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(preset="FAST", language="hi", microphone=2)
    s.save(path)
    assert Settings.load(path).language == "hi"
    assert Settings.load(path).microphone == 2


def test_bad_preset_rejected():
    with pytest.raises(ValueError):
        Settings(preset="not-real").validate()


def test_bad_settings_file_reported(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("broken")
    with pytest.raises(ValueError):
        Settings.load(path)


def test_turbo_is_the_default_and_old_fast_defaults_move_to_it(tmp_path):
    import json
    from app.utils.config import PRESETS
    assert Settings().preset == "TURBO" and PRESETS["TURBO"]["asr"] == "whisper-turbo"
    old = tmp_path / "old.json"                    # written before settings_version existed
    old.write_text(json.dumps({"preset": "FAST", "language": "hi"}))
    assert Settings.load(old).preset == "TURBO"
    chosen = tmp_path / "chosen.json"              # FAST picked on purpose after the change is kept
    Settings(preset="FAST").save(chosen)
    assert Settings.load(chosen).preset == "FAST"
    small = tmp_path / "small.json"                # any other old choice is kept too
    small.write_text(json.dumps({"preset": "BALANCED"}))
    assert Settings.load(small).preset == "BALANCED"


def test_captions_fall_back_to_an_installed_model_until_turbo_is_downloaded():
    from app.utils.config import caption_model
    assert caption_model("TURBO", lambda m: m == "whisper-turbo") == ("whisper-turbo", None)
    assert caption_model("TURBO", lambda m: m in {"whisper-tiny", "whisper-small"}) == ("whisper-small", "whisper-turbo")
    assert caption_model("TURBO", lambda m: False) == ("whisper-turbo", None)
    assert caption_model("FAST", lambda m: m == "whisper-tiny") == ("whisper-tiny", None)
