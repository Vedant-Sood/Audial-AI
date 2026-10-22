"""The Kandha window: QtWebEngine over the loopback page, microphone granted to the loopback origin only."""
import json
import os

import pytest

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication

from app.kandha.bridge import MockBackend, MockStole
from app.services.browser import BrowserService
from app.ui.kandha_window import KandhaWindow, prepare_chromium_flags, _is_loopback
from app.utils.config import Settings


def test_loopback_origins_and_chromium_flags(monkeypatch):
    assert _is_loopback(QUrl("http://127.0.0.1:8765/kandha/")) and _is_loopback(QUrl("http://localhost:1/"))
    assert not _is_loopback(QUrl("https://example.org/"))
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    flags = prepare_chromium_flags()
    assert "--disable-gpu" in flags and "--autoplay-policy=no-user-gesture-required" in flags
    assert prepare_chromium_flags().count("--autoplay-policy") == 1


@pytest.mark.skipif(os.environ.get("KANDHA_SKIP_WEBENGINE") == "1", reason="QtWebEngine not available here")
def test_window_loads_the_page_and_reports_ready():
    prepare_chromium_flags("--no-sandbox --disable-gpu")
    app = QApplication.instance() or QApplication([])
    service = BrowserService(settings=Settings(device="cpu"), kandha_backend=MockBackend([MockStole()]))
    url = service.start()
    window = KandhaWindow(url)
    window.show()
    result = {}

    def probe():
        window.run_js("JSON.stringify(window.Kandha ? window.Kandha.ready() : null)", on_probe)

    def on_probe(value):
        data = json.loads(value) if value else None
        if data and data.get("ready") and data.get("stream") == "open":
            result.update(data)
            app.quit()
        else:
            QTimer.singleShot(250, probe)

    QTimer.singleShot(500, probe)
    QTimer.singleShot(40000, app.quit)
    try:
        app.exec()
    finally:
        window.close()
        service.stop()
    assert result.get("ready") is True and result.get("qt") is True and result.get("toneModel") is True, result
    assert window.permission_api in ("QWebEnginePermission", "featurePermissionRequested")
    assert window.windowTitle() == "Kandha"
