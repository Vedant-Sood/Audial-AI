"""KandhaService and its HTTP routes: intents, queue, seats, settings, stole, SSE, consent gate, session events."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from app.kandha.bridge import MockBackend, MockStole
from app.kandha.service import KandhaService, KandhaSettings
from app.services.browser import BrowserService
from app.services.voice_view import clean_events
from app.storage.transcript import Caption, Session
from app.utils.config import Settings


@pytest.fixture
def stole():
    return MockStole()


@pytest.fixture
def companion(stole):
    service = BrowserService(settings=Settings(device="cpu"), kandha_backend=MockBackend([stole]))
    service.start()
    try:
        yield service
    finally:
        service.stop()
        for thread in tuple(service.engine.threads):
            thread.join(timeout=5)


def request(service, path, data=None, headers=None):
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    query = urllib.request.Request(service.url + path, data=data, headers=headers or {})
    try:
        response = urllib.request.urlopen(query, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        kind = response.headers.get("Content-Type", "")
        return response.status, (json.loads(raw) if "application/json" in kind and raw[:1] in b"{[" else raw), response.headers


def test_settings_validate_and_round_trip(tmp_path):
    s = KandhaSettings()
    assert s.validate().cues_by_mode["lecture"]["drop"] is False and s.cues_by_mode["practicum"]["rise"] is True
    s.intensity = {"L": 50}
    s.save(tmp_path / "s.json")
    loaded = KandhaSettings.load(tmp_path / "s.json")
    assert loaded.intensity == {"L": 50, "R": 100, "B": 100, "F": 100}
    assert loaded.stole_config().scale_l == 128
    for bad in ({"mode": "hallway"}, {"intensity": {"L": 500}}, {"queue_reminder_s": -1}, {"dnd": "yes"}):
        with pytest.raises(ValueError):
            KandhaSettings(**bad).validate()
    (tmp_path / "broken.json").write_text("nope")
    assert KandhaSettings.load(tmp_path / "broken.json").mode == "seminar"


def test_intents_are_scheduled_and_dispatched_to_virtual_and_real_stoles(tmp_path, stole):
    events = []
    service = KandhaService(publish=lambda k, d: events.append(d), home=tmp_path, backend=MockBackend([stole]), ticker=False)
    try:
        service.update_settings({"mode": "practicum"})
        out = service.intents([{"kind": "new_voice", "voice": 1, "t": 0.6, "age_ms": 3, "sent": time.time() * 1000, "new": True}], current=1)
        assert out["accepted"] == 1 and out["played"][0]["pattern"] == "new_voice" and out["played"][0]["device"] == "virtual"
        assert out["played"][0]["app_latency_ms"] is not None and out["played"][0]["app_latency_ms"] < 100
        assert service.seats.window_open(service.clock()) and service.current_voice == 1
        assert service.press_pad("R", "tap")["seats"] == {"1": "R"}
        assert service.pair(stole.address) is True
        time.sleep(0.3)   # the new-voice pattern (210 ms) must finish before the next tap plays
        out = service.intents([{"kind": "speaker", "voice": 2, "t": 5.0, "age_ms": 0}])
        assert out["played"][0]["zones"] == "F" and out["played"][0]["pattern"] == "seat_unmapped", "practicum partner default? no: voice 2 arrived as speaker, not new_voice"
        time.sleep(0.2)
        out = service.intents([{"kind": "speaker", "voice": 1, "t": 6.0, "age_ms": 0}])
        assert out["played"][0]["zones"] == "R" and out["played"][0]["device"] == "stole"
        time.sleep(0.05)
        assert stole.received[-1][1] == "haptic" and stole.player.timeline()[-1][0] == "R"
        assert service.virtual.timeline()[-1][0] == "R"
        with pytest.raises(ValueError):
            service.intents([{"kind": "cue", "cue": "sarcasm", "voice": 1}])
        with pytest.raises(ValueError):
            service.intents([{"kind": "speaker", "voice": 99}])
        with pytest.raises(ValueError):
            service.intents([{"kind": "speaker", "voice": 1}] * 51)
        kinds = [e["kind"] for e in events]
        assert "haptic" in kinds and "seat" in kinds and "stole_connected" in kinds
    finally:
        service.close()


def test_queue_pad_toggles_the_queue_with_a_squeeze_and_long_press_toggles_dnd(tmp_path, stole):
    events = []
    service = KandhaService(publish=lambda k, d: events.append(d), home=tmp_path, backend=MockBackend([stole]), ticker=False)
    try:
        service.pair(stole.address)
        stole.press(4, 1)
        time.sleep(0.1)
        assert service.queue.on and [e for e in events if e["kind"] == "queue"][-1]["source"] == "stole-pad"
        assert service.played[-1]["pattern"] == "queue_ack" and service.played[-1]["zones"] == "LR"
        stole.press(4, 3)
        time.sleep(0.1)
        assert service.settings.dnd is True
        assert service.set_queue(False, "screen")["changed"] and not service.queue.on
        service.queue.reminder_s = 1
        service.set_queue(True, "screen")
        service.clock = lambda: time.monotonic() + 2
        released = service.tick()
        assert any(r["pattern"] == "queue_reminder" for r in released)
    finally:
        service.close()


def test_test_patterns_play_in_do_not_disturb_and_stop_cancels(tmp_path):
    service = KandhaService(home=tmp_path, start_bridge=False, ticker=False)
    try:
        service.update_settings({"dnd": True})
        assert service.test("B")[0]["zones"] == "B"
        assert service.test("LR")[0]["zones"] == "LR" and service.test("LR")[0]["pattern"] == "zone_test"
        assert service.test(None, "rise")[0]["pattern"] == "rise"
        assert service.stop_haptics()[0]["pattern"] == "stop"
        with pytest.raises(ValueError):
            service.test("X")
        with pytest.raises(ValueError):
            service.test(None, "nope")
        assert service.snapshot()["stole"]["state"] == "unavailable"
    finally:
        service.close()


def test_new_session_uses_the_last_room_when_asked(tmp_path):
    service = KandhaService(home=tmp_path, start_bridge=False, ticker=False)
    try:
        service.intents([{"kind": "new_voice", "voice": 1, "new": True}])
        service.assign_seat(1, "L")
        service.rooms("save", "Lab")
        service.new_session()
        assert service.seats.loaded_room.name == "Lab"
        assert service.intents([{"kind": "new_voice", "voice": 5, "new": True}]) and service.seats.zone_for(5) == "L"
        service.update_settings({"use_last_layout": False})
        service.new_session()
        assert service.seats.loaded_room is None
    finally:
        service.close()


def test_http_routes_cover_state_intents_queue_seats_settings_rooms_and_stole(companion, stole):
    status, state, _ = request(companion, "/api/kandha/state")
    assert status == 200 and state["settings"]["mode"] == "seminar" and state["stole"]["backend"] == "mock"
    assert request(companion, "/api/kandha/settings", {"mode": "practicum", "intensity": {"F": 60}})[1]["intensity"]["F"] == 60
    assert request(companion, "/api/kandha/settings", {"mode": "nope"})[0] == 400
    status, out, _ = request(companion, "/api/kandha/intents", {"intents": [{"kind": "new_voice", "voice": 1, "t": 1.0, "age_ms": 2, "new": True}], "current": 1})
    assert status == 200 and out["played"][0]["pattern"] == "new_voice"
    assert request(companion, "/api/kandha/seats", {"voice": 1, "zone": "B"})[1]["seats"] == {"1": "B"}
    assert request(companion, "/api/kandha/seats", {"voice": 1, "zone": "Q"})[0] == 400
    assert request(companion, "/api/kandha/queue", {"on": True})[1]["on"] is True
    assert request(companion, "/api/kandha/rooms", {"action": "save", "name": "Lab"})[1]["result"]["slots"] == ["B"]
    assert request(companion, "/api/kandha/rooms")[1]["result"]["rooms"][0]["name"] == "Lab"
    assert request(companion, "/api/kandha/stole/scan", {"timeout": 1})[1]["devices"][0]["address"] == stole.address
    status, paired, _ = request(companion, "/api/kandha/stole/pair", {"address": stole.address, "name": stole.name})
    assert status == 200 and paired["connected"] is True and paired["stole"]["state"] == "connected"
    time.sleep(0.3)
    assert request(companion, "/api/kandha/test", {"zone": "F"})[1]["played"][0]["device"] == "stole"
    assert request(companion, "/api/kandha/pad", {"pad": "Q", "gesture": "tap"})[0] == 200
    assert request(companion, "/api/kandha/stole/forget", {})[1]["stole"]["paired"] is None
    assert request(companion, "/api/kandha/stop", {})[1]["played"][0]["pattern"] == "stop"
    assert request(companion, "/api/kandha/nothing", {})[0] == 404
    assert request(companion, "/api/kandha/intents", {"intents": "x"})[0] == 400


def test_sse_stream_delivers_state_then_live_events(companion):
    received = []

    def read():
        query = urllib.request.Request(companion.url + "/api/kandha/stream")
        with urllib.request.urlopen(query, timeout=10) as response:
            assert response.headers["Content-Type"].startswith("text/event-stream")
            for _ in range(5):
                event, data = None, None
                while True:
                    line = response.readline().decode().rstrip("\n")
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                    elif line == "" and event:
                        break
                received.append((event, data))
                if {"queue", "settings"} <= {k for k, _ in received}:
                    break

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    time.sleep(0.3)
    request(companion, "/api/kandha/queue", {"on": True})
    request(companion, "/api/kandha/settings", {"dnd": True})
    reader.join(5)
    kinds = [k for k, _ in received]
    assert kinds[0] == "state" and received[0][1]["settings"]["mode"] in ("seminar", "practicum")
    assert "queue" in kinds and "settings" in kinds
    assert [d for k, d in received if k == "queue"][0]["on"] is True


def test_saving_a_session_needs_consent_and_keeps_kandha_events(companion, tmp_path):
    status, started, _ = request(companion, "/api/start", {"mode": "tone"})
    assert status == 200
    events = [{"kind": "voice", "t": 0.4, "id": 1, "new": True}, {"kind": "haptic", "t": 0.5, "zones": "L", "pattern": "seat_tap", "voice": 1},
              {"kind": "seat", "t": 0.2, "voice": 1, "zone": "L"}, {"kind": "queue", "t": 3.0, "on": True}]
    assert request(companion, "/api/voice-events", {"session_id": started["session_id"], "events": events})[1]["stored"] == 4
    assert request(companion, "/api/kandha/session/save", {"consent": False})[0] == 403
    assert request(companion, "/api/kandha/session/save", {})[0] == 403
    status, saved, _ = request(companion, "/api/kandha/session/save", {"consent": True, "title": "Kandha seminar"})
    assert status == 200 and saved["voice_events"] == 4 and saved["title"] == "Kandha seminar"
    request(companion, "/api/stop", {"session_id": started["session_id"]})
    from app.utils.paths import data_root
    files = list((data_root() / "sessions").glob("*.json"))
    assert files and json.loads(files[0].read_text())["voice_view"]["events"][1]["pattern"] == "seat_tap"


@pytest.mark.parametrize("bad", [
    [{"kind": "haptic", "t": 1, "zones": "LX", "pattern": "seat_tap"}],
    [{"kind": "haptic", "t": 1, "zones": "L", "pattern": "<script>"}],
    [{"kind": "seat", "t": 1, "voice": 1, "zone": "Q"}],
    [{"kind": "seat", "t": 1, "voice": 0, "zone": "L"}],
])
def test_malformed_kandha_session_events_are_rejected(bad):
    with pytest.raises(ValueError):
        clean_events(bad)


def test_exports_ignore_kandha_events_but_json_keeps_them(tmp_path):
    session = Session(title="Kandha")
    session.add(Caption(0.5, 2.0, "Hello", "Unattributed"))
    session.add_voice_events(clean_events([{"kind": "voice", "t": 0.2, "id": 1}, {"kind": "haptic", "t": 0.5, "zones": "L", "pattern": "seat_tap", "voice": 1}, {"kind": "seat", "t": 0.1, "voice": 1, "zone": "L"}]))
    session.export(tmp_path / "t.vtt", "vtt")
    assert "Voice 1: Hello" in (tmp_path / "t.vtt").read_text()
    session.export(tmp_path / "t.txt", "txt")
    session.export(tmp_path / "t.json", "json")
    assert len(json.loads((tmp_path / "t.json").read_text())["voice_view"]["events"]) == 3


def test_the_prototype_pairs_with_the_simulated_stole_and_can_switch_links(tmp_path):
    events = []
    service = KandhaService(publish=lambda k, d: events.append(d), home=tmp_path, ticker=False)
    try:
        assert service.settings.link == "simulated" and service.snapshot()["stole"]["simulated"] is True
        found = service.scan(1)
        assert found[0]["name"] == "KandhaStole-SIM1"
        assert service.pair(found[0]["address"], found[0]["name"]) is True
        assert service.simulate("battery", 18)["simulated"] == "battery 17%" or service.simulate("battery", 18)["simulated"].startswith("battery 1")
        time.sleep(0.25)          # the "connected" ticks finish, then the deferred warning is released by a tick
        service.tick()
        assert any(e["kind"] == "haptic" and e["pattern"] == "low_battery" for e in events), "a low-battery warning taps the neck once"
        assert service.simulate("press", {"pad": "Q", "gesture": "tap"})["simulated"] == "pad Q gesture tap"
        time.sleep(0.05)
        assert service.queue.on
        assert service.simulate("charging", True)["simulated"] == "charging"
        with pytest.raises(ValueError):
            service.simulate("explode")
        with pytest.raises(ValueError):
            service.simulate("press", {"pad": "X", "gesture": "tap"})
        service.simulate("out_of_range")
        time.sleep(0.05)
        assert service.snapshot()["stole"]["state"] in ("reconnecting", "connected")
        # switching to the real link restarts the bridge on bleak; nothing is paired there
        service.update_settings({"link": "bluetooth"})
        assert service.snapshot()["stole"]["backend"] == "bleak" and service.snapshot()["stole"]["simulated"] is False
        with pytest.raises(ValueError):
            service.simulate("battery", 50)
        service.update_settings({"link": "simulated"})
        assert service.snapshot()["stole"]["simulated"] is True
        with pytest.raises(ValueError):
            service.update_settings({"link": "wifi"})
    finally:
        service.close()
