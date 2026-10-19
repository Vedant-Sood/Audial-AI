import base64
from io import BytesIO
import json
import struct
import urllib.error
import urllib.request

import numpy as np
import pytest

from app.services.browser import BrowserService
from app.services.native_host import read_message, write_message, forward, MAX_MESSAGE
from app.audio.capture import ExternalAudio
from app.utils.config import Settings


def test_browser_only_sessions_do_not_fill_an_unconsumed_desktop_event_queue():
    from app.storage.transcript import Caption
    service = BrowserService(settings=Settings())
    try:
        for index in range(1000):
            service.engine.emit("caption", Caption(index, index + 1, f"Caption {index}"))
        assert service.engine.events.empty()
        assert len(service.events) == 400
        assert len(service.session.captions) == 1000
        assert service.session.captions[-1].text == "Caption 999"
    finally:
        service.unsubscribe()


def test_native_message_framing_preserves_utf8_and_rejects_partial_or_oversize():
    buffer = BytesIO()
    write_message(buffer, {"title": "धन्यवाद · meeting", "ok": True})
    buffer.seek(0)
    assert read_message(buffer)["title"] == "धन्यवाद · meeting"
    assert read_message(buffer) is None
    for bad in [b"a", struct.pack("<I", MAX_MESSAGE + 1), struct.pack("<I", 20) + b"{}"]:
        with pytest.raises(ValueError):
            read_message(BytesIO(bad))


def test_native_transport_disconnect_exits_without_holding_the_installed_runtime(monkeypatch):
    from app.services import native_host
    incoming, outgoing = BytesIO(), BytesIO()
    write_message(incoming, {"id": 1, "type": "poll", "profile": "test"})
    write_message(incoming, {"id": 2, "type": "poll", "profile": "test"})
    incoming.seek(0)
    def disconnected(message):
        raise ConnectionRefusedError("Desktop is not running")
    monkeypatch.setattr(native_host, "forward", disconnected)
    native_host.main(incoming, outgoing)
    outgoing.seek(0)
    response = read_message(outgoing)
    assert response["id"] == 1 and not response["ok"]
    assert read_message(outgoing) is None
    assert read_message(incoming)["id"] == 2


@pytest.fixture
def bridge_service(monkeypatch):
    service = BrowserService(settings=Settings(device="cpu"))
    monkeypatch.setattr(service.engine.manager, "installed", lambda _: True)
    def start(mode, source):
        assert source == "browser"
        service.engine.source = source
        service.engine.capture = ExternalAudio()
        service.engine.running = True
        service.engine.stop_requested.clear()
    monkeypatch.setattr(service.engine, "start", start)
    service.start()
    yield service
    service.stop()


def test_real_loopback_bridge_requires_auth_and_keeps_actual_tab_metadata(bridge_service):
    service = bridge_service
    request = urllib.request.Request(service.url + "/api/bridge", data=b'{}', headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 403
    result = forward({"profile": "chrome-test", "type": "tabs", "browser": "Chrome",
                      "tabs": [{"id": 7, "window_id": 3, "title": "Actual meeting", "supported": True},
                               {"id": 8, "window_id": 4, "title": "Settings", "supported": False}]})
    assert result["updated"]
    snapshot = service.bridge.snapshot()
    assert len(snapshot["profiles"][0]["tabs"]) == 2
    assert snapshot["profiles"][0]["tabs"][0]["title"] == "Actual meeting"
    assert service.bridge.queue_command("chrome-test", 7)["queued"]
    assert forward({"profile": "chrome-test", "type": "poll"})["commands"] == [{"type": "focus-tab", "tab_id": 7}]


def test_capture_switch_stale_packets_and_disconnect_release_the_owned_source(bridge_service):
    service = bridge_service
    now = [0.0]
    service.bridge.clock = lambda: now[0]
    forward({"profile": "edge-test", "type": "tabs", "browser": "Edge",
             "tabs": [{"id": 4, "title": "Selected source", "supported": True}]})
    owned = forward({"profile": "edge-test", "type": "start", "tab_id": 4})
    assert owned["title"] == "Selected source"
    assert "session_id" not in service.bridge.snapshot()["capture"]
    packet = {"profile": "edge-test", "type": "audio", "session_id": owned["session_id"],
              "pcm": base64.b64encode(np.zeros(3200, dtype="<i2").tobytes()).decode(),
              "sample_rate": 16000, "start_seconds": 0}
    assert forward(packet)["queued"]
    assert not service.engine.capture.queue.empty()
    with pytest.raises(ValueError, match="different capture"):
        forward({**packet, "session_id": "old-session"})
    with pytest.raises(ValueError, match="Stop the current"):
        forward({"profile": "edge-test", "type": "start", "tab_id": 4})
    now[0] = 16
    service.bridge.expire()
    assert service.bridge.owner is None and service.engine.stop_requested.is_set()


def test_closed_tabs_are_removed_and_restricted_pages_do_not_start_capture(bridge_service):
    service = bridge_service
    forward({"profile": "test", "type": "tabs", "tabs": [{"id": 4, "title": "Restricted", "supported": False}]})
    with pytest.raises(ValueError, match="supported"):
        forward({"profile": "test", "type": "start", "tab_id": 4})
    forward({"profile": "test", "type": "tabs", "tabs": []})
    with pytest.raises(ValueError, match="closed"):
        service.bridge.queue_command("test", 4)
    assert not service.engine.running
