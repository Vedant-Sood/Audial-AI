import os
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCESSIBILITY_AI_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
