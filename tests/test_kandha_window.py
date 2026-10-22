"""The Kandha window: QtWebEngine over the loopback page, microphone granted to the loopback origin only.

The page load runs in a subprocess (`python -m app.main --kandha-check`): QtWebEngine must own the
QApplication from the start and tears down badly inside a long pytest process.
"""
import json
import os
import subprocess
import sys

import pytest

from PySide6.QtCore import QUrl

from app.ui.kandha_window import _is_loopback, prepare_chromium_flags
from app.utils.paths import project_root


def test_loopback_origins_and_chromium_flags(monkeypatch):
    assert _is_loopback(QUrl("http://127.0.0.1:8765/kandha/")) and _is_loopback(QUrl("http://localhost:1/"))
    assert not _is_loopback(QUrl("https://example.org/"))
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    flags = prepare_chromium_flags()
    assert "--disable-gpu" in flags and "--autoplay-policy=no-user-gesture-required" in flags
    assert prepare_chromium_flags().count("--autoplay-policy") == 1


@pytest.mark.skipif(os.environ.get("KANDHA_SKIP_WEBENGINE") == "1", reason="QtWebEngine not available here")
def test_kandha_check_loads_the_page_in_the_embedded_web_view(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu",
               ACCESSIBILITY_AI_HOME=str(tmp_path / "home"))
    result = subprocess.run([sys.executable, "-m", "app.main", "--kandha-check"], cwd=project_root(), env=env,
                            capture_output=True, text=True, timeout=400)
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert result.returncode == 0 and lines, result.stdout + result.stderr
    report = json.loads(lines[-1])
    assert report["ok"] is True, {"report": report, "stderr_tail": result.stderr[-2000:]}
    assert report["page"]["ready"] is True and report["page"]["qt"] is True
    assert report["page"]["toneModel"] is True and report["page"]["stream"] == "open"
    assert report["permission_api"] in ("QWebEnginePermission", "featurePermissionRequested")
    assert report["title"] == "Kandha"
