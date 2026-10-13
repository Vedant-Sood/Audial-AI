import pytest
from app.models.manager import ModelManager, REGISTRY
from scripts.download_datasets import safe_extract
import zipfile


def test_incomplete_model_is_not_installed(tmp_path):
    m = ModelManager(tmp_path)
    p = m.path("whisper-tiny")
    p.mkdir()
    (p / "installed.json").write_text("{}")
    assert not m.installed("whisper-tiny")


def test_unknown_model_cannot_escape_root(tmp_path):
    with pytest.raises(ValueError):
        ModelManager(tmp_path).path("../outside")


def test_gated_model_requires_acceptance(tmp_path):
    with pytest.raises(PermissionError):
        ModelManager(tmp_path).install("pyannote")


def test_archive_path_traversal_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError):
        safe_extract(archive, tmp_path / "out")
