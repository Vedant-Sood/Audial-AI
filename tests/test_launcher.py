"""Startup failures stay visible without blocking background worker jobs."""

from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("arguments, dialogs", [(["--setup-models"], 0), ([], 1)])
def test_windows_startup_failure_uses_the_appropriate_reporting_channel(
    arguments, dialogs, monkeypatch, tmp_path, capsys
):
    import app.main
    import app.utils.paths
    import ctypes

    shown = []
    monkeypatch.setattr(
        ctypes, "windll",
        SimpleNamespace(user32=SimpleNamespace(MessageBoxW=lambda *args: shown.append(args))),
        raising=False,
    )
    monkeypatch.setattr(sys, "argv", ["launcher.py", *arguments])
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app.utils.paths, "data_root", lambda: tmp_path)

    def failed():
        raise RuntimeError("Fixture startup failure")

    monkeypatch.setattr(app.main, "main", failed)
    with pytest.raises(SystemExit) as exit_:
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "launcher.py"), run_name="__main__")
    assert exit_.value.code == 1
    assert "Fixture startup failure" in (tmp_path / "startup-error.log").read_text()
    assert len(shown) == dialogs
    if not dialogs:
        assert "Fixture startup failure" in capsys.readouterr().err
