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
