import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import pytest

from app.models.catalogue import CatalogueInstaller
from app.models.download import Asset
from app.models.manager import ModelManager


class Response(BytesIO):
    status = 200
    headers = {}


def test_fresh_catalogue_setup_verifies_assets_and_relaunches_offline(tmp_path, monkeypatch):
    content = {name: ("actual fixture " + name).encode() for name in ["config.json", "model.bin", "tokenizer.json"]}
    assets = [Asset("https://models.example/" + name, name, hashlib.sha256(data).hexdigest(), size=len(data), revision="f"*40)
              for name, data in content.items()]
    calls = []
    def open_(request, timeout):
        name = request.full_url.rsplit("/", 1)[-1]
        calls.append(name)
        return Response(content[name])
    monkeypatch.setattr("urllib.request.urlopen", open_)
    monkeypatch.setattr("app.models.catalogue.catalogue", lambda: [{"id": "whisper-tiny"}])
    monkeypatch.setattr(CatalogueInstaller, "resolve_assets", lambda *args: assets)
    monkeypatch.setattr("app.models.catalogue.get_token", lambda: pytest.fail("Public models must not depend on Windows Credential Manager or a private token"))
    manager = ModelManager(tmp_path / "models")
    installer = CatalogueInstaller(manager)
    assert installer.run()["whisper-tiny"]["state"] == "ready"
    assert manager.installed("whisper-tiny")
    receipt = json.loads((manager.path("whisper-tiny") / "installed.json").read_text())
    assert receipt["assets"][0]["revision"] == "f" * 40
    assert len(calls) == 3
    monkeypatch.setattr(CatalogueInstaller, "resolve_assets", lambda *args: pytest.fail("Offline launch contacted model metadata"))
    assert installer.run()["whisper-tiny"]["state"] == "ready"
    assert len(calls) == 3
    monkeypatch.setattr(CatalogueInstaller, "resolve_assets", lambda *args: assets)
    (manager.path("whisper-tiny") / "model.bin").write_bytes(b"corrupt")
    assert installer.run()["whisper-tiny"]["state"] == "ready"
    assert calls == ["config.json", "model.bin", "tokenizer.json", "model.bin"]


def test_one_failed_model_does_not_hide_other_readiness_or_gated_actions(tmp_path, monkeypatch):
    monkeypatch.setattr("app.models.catalogue.catalogue", lambda: [{"id": n} for n in ["whisper-tiny", "pyannote", "sign-local"]])
    monkeypatch.setattr(CatalogueInstaller, "resolve_assets", lambda *args: (_ for _ in ()).throw(OSError("Network unavailable")))
    monkeypatch.setattr(CatalogueInstaller, "install_local", lambda *args: tmp_path)
    states = CatalogueInstaller(ModelManager(tmp_path / "models")).run()
    assert states["whisper-tiny"]["state"] == "failed"
    assert states["pyannote"]["state"] == "needs_action"
    assert states["sign-local"]["state"] == "ready"
    assert "terms" in states["pyannote"]["message"]


def test_bundled_runtime_requirements_are_in_the_same_catalogue():
    from app.models.catalogue import catalogue
    ids = {entry["id"] for entry in catalogue()}
    assert {"silero-vad", "system-tts", "emotion-baseline", "sign-local", "emotion-wavlm", "whisper-tiny", "whisper-small", "whisper-medium", "ecapa", "pyannote", "hand-pose", "body-pose"} <= ids


def test_setup_preserves_an_explicit_bundled_emotion_selection(tmp_path, monkeypatch):
    from app.inference.emotion import VoiceEmotion
    from app.utils.paths import atomic_json, data_root
    selection = {"bundled": True}
    atomic_json(data_root() / "emotion_selection.json", selection)
    called = []
    monkeypatch.setattr("scripts.activate_emotion.activate", lambda *args: called.append(args))
    CatalogueInstaller(ModelManager(tmp_path / "models")).activate_default("emotion-wavlm", tmp_path)
    assert not called
    assert VoiceEmotion().model.bundle["feature_version"] == "mfcc-mel-prosody-v1"
    assert json.loads((data_root() / "emotion_selection.json").read_text()) == selection


def test_background_worker_failures_reach_persistent_alerts_and_view_is_bounded():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    from app.storage.transcript import Session, Caption
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    for message in ["Install a caption model", "Microphone permission denied", "Cannot open camera", "NVIDIA GPU unavailable"]:
        window.engine.emit("error", message)
    window.poll()
    assert len(window.notifications.history.items) == 4
    assert len(window.notifications.cards) == 3
    session = Session()
    panel = window.caption_panels[0]
    for i in range(1100):
        caption = Caption(i, i + 1, "Every word is retained")
        session.add(caption)
        panel.append_caption(session, caption)
    app.processEvents()
    assert panel.lines.count() == 500 and len(session.captions) == 1100
    assert session.to_dict()["captions"][0]["text"] == "Every word is retained"
    window.close()
