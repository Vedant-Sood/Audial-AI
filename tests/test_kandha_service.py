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
        for bad in (0, -1, True, "1", 1.5, 10 ** 7):
            with pytest.raises(ValueError):
                service.intents([{"kind": "speaker", "voice": bad}])
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
    session_id = request(companion, "/api/kandha/session/new", {})[1]["session_id"]
    events = [{"kind": "voice", "t": 0.4, "id": 1, "new": True}, {"kind": "haptic", "t": 0.5, "zones": "L", "pattern": "seat_tap", "voice": 1},
              {"kind": "seat", "t": 0.2, "voice": 1, "zone": "L"}, {"kind": "queue", "t": 3.0, "on": True}]
    assert request(companion, "/api/kandha/session/events", {"session_id": session_id, "events": events})[1]["stored"] == 4
    assert request(companion, "/api/kandha/session/save", {"consent": False, "session_id": session_id})[0] == 403
    assert request(companion, "/api/kandha/session/save", {"session_id": session_id})[0] == 403
    status, saved, _ = request(companion, "/api/kandha/session/save", {"consent": True, "session_id": session_id, "title": "Kandha seminar"})
    assert status == 200 and saved["voice_events"] == 4 and saved["title"] == "Kandha seminar"
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
        assert found[0]["name"] == "Kandha-SIM1"
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


# ---------------------------------------------------------------- review fixes (C6, C11, C13, C16/G3, C18/G2, C21, C25)
def test_an_intent_held_up_on_the_way_is_dropped_as_stale_not_played_late(tmp_path):
    """DESIGN 7.2: older than 1.5 s when it would play -> dropped. The page sends each intent's age
    when it leaves (age_ms) and that moment on its wall clock (sent); the trip, measured against
    the batches before it, is added."""
    service = KandhaService(home=tmp_path, start_bridge=False, ticker=False)
    try:
        service.update_settings({"mode": "practicum"})
        service.intents([{"kind": "silence", "t": 11.0, "age_ms": 0, "sent": time.time() * 1000}])    # an earlier batch, on time
        late = service.intents([{"kind": "speaker", "voice": 7, "t": 12.0, "age_ms": 0, "sent": time.time() * 1000 - 3000}])
        assert late["played"] == [] and service.scheduler.dropped[-1][1] == "stale", "held up 3 s on the way: never tapped late"
        old = service.intents([{"kind": "speaker", "voice": 8, "t": 12.0, "age_ms": 2000}])
        assert old["played"] == [] and service.scheduler.dropped[-1][1] == "stale", "2 s old when sent"
        fresh = service.intents([{"kind": "speaker", "voice": 9, "t": 12.0, "age_ms": 40, "sent": time.time() * 1000}])
        assert fresh["played"][0]["pattern"] == "seat_unmapped"
        assert 35 <= fresh["played"][0]["app_latency_ms"] < 200, "latency counts from when the intent was raised"
    finally:
        service.close()


def speaker(voice, page_clock_ms, age_ms=20):
    return {"kind": "speaker", "voice": voice, "t": float(voice), "age_ms": age_ms, "sent": page_clock_ms}


@pytest.mark.parametrize("behind_ms", [2500, 30000, -4000])
def test_a_page_clock_ahead_or_behind_neither_drops_every_tap_nor_hides_a_held_up_batch(tmp_path, behind_ms):
    """The page's wall clock (sent) need not agree with this service's: a browser tab can keep its
    own time base, or catch up with a time sync late. A steady difference bigger than the 1.5 s
    stale window must not drop every tap (behind) or let a batch held up on the way play late
    (ahead); the trip counts only beyond the fastest recent batch."""
    now = [100.0]
    service = KandhaService(home=tmp_path, start_bridge=False, ticker=False, clock=lambda: now[0])
    page_clock = lambda: time.time() * 1000 - behind_ms
    try:
        service.update_settings({"mode": "practicum"})
        for voice in range(1, 7):
            now[0] += 1.0                       # the tap before has finished
            out = service.intents([speaker(voice, page_clock())])
            assert [p["voice"] for p in out["played"]] == [voice], (voice, service.scheduler.dropped[-1:])
            assert 20 <= out["played"][0]["app_latency_ms"] < 200, "the intent's real age, not the clocks' difference"
        now[0] += 1.0
        late = service.intents([speaker(7, page_clock() - 3000, age_ms=0)])
        assert late["played"] == [] and service.scheduler.dropped[-1][1] == "stale", "held up 3 s on the way: never tapped late"
        now[0] += 1.0
        assert [p["voice"] for p in service.intents([speaker(8, page_clock())])["played"]] == [8], "the next batch on time plays"
    finally:
        service.close()


def test_a_page_clock_that_steps_costs_a_few_taps_at_most(tmp_path):
    """A clock step (a time sync after sleep) changes the difference mid-session. A page clock that
    jumps ahead loses nothing. One that falls behind by more than the stale window looks like a
    held-up batch until CLOCK_SAMPLES batches have shown the new difference: at most that many
    taps are lost, then they all play again."""
    from app.kandha.service import CLOCK_SAMPLES
    now = [100.0]
    service = KandhaService(home=tmp_path, start_bridge=False, ticker=False, clock=lambda: now[0])
    voices = iter(range(1, 1000))

    def taps(behind_ms, batches):
        played = []
        for _ in range(batches):
            now[0] += 1.0
            voice = next(voices)
            played.append(bool(service.intents([speaker(voice, time.time() * 1000 - behind_ms)])["played"]))
        return played

    try:
        service.update_settings({"mode": "practicum"})
        assert all(taps(0, 3)), "the clocks agree"
        assert all(taps(-5000, 3)), "the page clock jumps 5 s ahead: nothing is lost"
        for behind_ms in (0, 2500):             # it falls back 5 s, then 2.5 s more
            after_step = taps(behind_ms, CLOCK_SAMPLES + 4)
            assert after_step[CLOCK_SAMPLES:] == [True] * 4, (behind_ms, after_step)
        assert all(taps(-1000, 3)), "ahead again: at once"
    finally:
        service.close()


def test_one_odd_sent_or_another_page_s_clock_never_makes_this_page_s_taps_look_late(tmp_path):
    """The clocks' difference is kept per page (the page's tag), and one batch alone never sets
    it: a single `sent` ahead of the rest (a bad value, a clock ahead for one batch) or a second
    page whose clock runs 5 s ahead all along drops no tap, and a held-up batch is still dropped."""
    from app.kandha.service import CLOCK_PAGES, CLOCK_SAMPLES
    now = [100.0]
    service = KandhaService(home=tmp_path, start_bridge=False, ticker=False, clock=lambda: now[0])
    voices = iter(range(1, 1000))

    def tap(ahead_ms=0, page=None, held_ms=0):
        now[0] += 1.0                           # the tap before has finished
        intent = speaker(next(voices), time.time() * 1000 + ahead_ms - held_ms, age_ms=0 if held_ms else 20)
        if page is not None:
            intent["page"] = page
        return bool(service.intents([intent])["played"])

    try:
        service.update_settings({"mode": "practicum"})
        for odd in (5000, 1e15):                # pages that send no tag share one history
            assert all(tap() for _ in range(3))
            tap(odd)
            assert [tap() for _ in range(CLOCK_SAMPLES + 2)] == [True] * (CLOCK_SAMPLES + 2), odd
            assert not tap(held_ms=3000), "held up 3 s on the way: never tapped late"
        # two pages, one on time and one 5 s ahead, taking turns
        both = [(tap(page="here"), tap(5000, page="there")) for _ in range(CLOCK_SAMPLES + 2)]
        assert both == [(True, True)] * (CLOCK_SAMPLES + 2), both
        assert not tap(page="here", held_ms=3000) and not tap(5000, page="there", held_ms=3000)
        assert tap(page="here") and tap(5000, page="there")
        # many pages over a long run: only the last few are remembered
        for n in range(CLOCK_PAGES + 4):
            tap(page=f"page-{n}")
        assert len(service.clock_gaps) == CLOCK_PAGES and "page-0" not in service.clock_gaps
    finally:
        service.close()


def test_the_seat_window_closing_tells_every_page_that_nobody_waits(tmp_path):
    """The 6 s seat window after a new voice: when it runs out unused the service says pending: null,
    and a pad tap with no window (or one that seats the voice) says so too, so no page keeps the
    "waiting for a seat" highlight."""
    events = []
    now = [10.0]
    service = KandhaService(publish=lambda kind, data: events.append(data), home=tmp_path, start_bridge=False, ticker=False,
                            clock=lambda: now[0])

    def last_seat():
        return [e for e in events if e["kind"] == "seat"][-1]

    try:
        service.intents([{"kind": "new_voice", "voice": 3, "t": 1.0, "new": True}])
        opened = last_seat()
        assert opened["pending"]["voice"] == 3 and opened["source"] == "new-voice"
        now[0] += service.seats.window_s - 0.5
        service.tick()
        assert last_seat() is opened, "still open: nothing to say"
        now[0] += 1.0
        service.tick()
        closed = last_seat()
        assert closed["pending"] is None and closed["voice"] == 3 and closed["action"] == "window-closed"
        assert "zone" not in closed, "the page must not take this for a seat change"
        assert service.seats.snapshot(now[0])["seats"] == closed["seats"] == {"3": None}
        service.tick()
        assert [e.get("action") for e in events].count("window-closed") == 1, "said once"
        service.press_pad("L", "tap")
        assert last_seat()["action"] == "no-window" and last_seat()["pending"] is None
        # a tap inside the window seats the voice: nobody waits, and the window does not close again later
        service.intents([{"kind": "new_voice", "voice": 4, "t": 9.0, "new": True}])
        service.press_pad("R", "tap")
        assert last_seat()["action"] == "assign-new" and last_seat()["zone"] == "R" and last_seat()["pending"] is None
        now[0] += service.seats.window_s + 1
        service.tick()
        assert [e.get("action") for e in events].count("window-closed") == 1
        # seated from the screen while the window is open: the event says nobody waits either
        service.intents([{"kind": "new_voice", "voice": 5, "t": 20.0, "new": True}])
        service.assign_seat(5, "B")
        assert last_seat()["source"] == "screen" and last_seat()["pending"] is None
    finally:
        service.close()


def raw_post(service, path, body):
    """POST a hand-built body (json.loads accepts Infinity, NaN and 1e999; JSON.stringify never sends them)."""
    return request(service, path, body.encode(), {"Content-Type": "application/json"})


def test_bad_numbers_get_a_400_and_never_drop_the_connection(companion):
    for path, body in (("/api/kandha/test", '{"zone": "F", "repeat": Infinity}'), ("/api/kandha/test", '{"zone": "F", "repeat": 1e999}'),
                       ("/api/kandha/test", '{"zone": "F", "repeat": -Infinity}'), ("/api/kandha/test", '{"zone": "F", "repeat": 2.0}'),
                       ("/api/kandha/stole/scan", '{"timeout": NaN}'), ("/api/kandha/stole/scan", '{"timeout": 1e999}'),
                       ("/api/kandha/stole/scan", '{"timeout": "6"}'), ("/api/browser-command", '{"profile": "p", "tab_id": 1e999}'),
                       ("/api/kandha/intents", '{"intents": [{"kind": "speaker", "voice": 1, "age_ms": Infinity}]}')):
        status, out, _ = raw_post(companion, path, body)
        assert status == 400 and out["error"], (path, body)
    assert request(companion, "/api/kandha/test", {"zone": "F", "repeat": 2})[0] == 200
    assert request(companion, "/api/kandha/stole/scan", {"timeout": 10 ** 400})[0] == 200, "a huge whole number is clamped, not a crash"


def test_startup_stole_events_reach_the_event_feed(tmp_path):
    """A remembered pairing reconnects while BrowserService is being built: those events are kept."""
    from app.kandha.bridge import SimulatedStole
    from app.utils.paths import atomic_json, data_root
    atomic_json(data_root() / "kandha" / "stole-simulated.json", {"address": SimulatedStole.ADDRESS, "name": "Kandha-SIM1", "protocol": 1})
    service = BrowserService(settings=Settings(device="cpu"))
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not service.kandha.bridge.connected:
            time.sleep(0.02)
        time.sleep(0.1)
        with service.lock:
            kinds = [e["data"].get("kind") for e in service.events if e["kind"] == "kandha"]
        assert "stole_state" in kinds and "stole_connected" in kinds and "haptic" in kinds, kinds
        assert service.id >= len(kinds) > 0
    finally:
        service.kandha.close()
        service.unsubscribe()


def test_save_and_exports_write_the_kandha_session_on_screen_never_an_earlier_capture(companion):
    # an earlier Whisper capture, stopped without consent
    status, started, _ = request(companion, "/api/start", {"mode": "tone"})
    assert status == 200
    companion.engine.emit("caption", Caption(0.5, 2.0, "Leftover words from an earlier capture", "Unattributed"))
    request(companion, "/api/voice-events", {"session_id": started["session_id"], "events": [{"kind": "voice", "t": 0.4, "id": 1}]})
    request(companion, "/api/stop", {"session_id": started["session_id"]})
    from app.utils.paths import data_root
    sessions = data_root() / "sessions"
    # a new Kandha session (a demo, or browser captions: no Whisper at all) has nothing yet
    status, fresh, _ = request(companion, "/api/kandha/session/new", {})
    assert status == 200 and isinstance(fresh["session_id"], str) and "seats" in fresh
    sid = fresh["session_id"]
    assert request(companion, "/api/kandha/session/save", {"consent": True, "session_id": sid})[0] == 400, "nothing to save"
    assert request(companion, f"/api/export?format=vtt&session={sid}")[0] == 400
    assert not sessions.exists() or not list(sessions.glob("*.json"))
    # the page records what it showed: captions from any source and its events
    captions = [{"start": 1.0, "end": 2.5, "text": "Good morning, everyone.", "voice": 1},
                {"start": 2.5, "end": 4.0, "text": "Shall we begin with the case?", "voice": 2}]
    events = [{"kind": "voice", "t": 1.0, "id": 1, "new": True}, {"kind": "voice", "t": 2.5, "id": 2, "new": True},
              {"kind": "cue", "t": 3.0, "cue": "rise", "voice": 2}, {"kind": "tone", "t0": 2.5, "t1": 4.0, "voice": 2, "relative": "intense", "label": "uncertain", "confidence": None},
              {"kind": "queue", "t": 3.5, "on": True}, {"kind": "haptic", "t": 2.6, "zones": "R", "pattern": "seat_tap", "voice": 2},
              {"kind": "seat", "t": 2.7, "voice": 2, "zone": "R"}]
    status, out, _ = request(companion, "/api/kandha/session/events", {"session_id": sid, "events": events, "captions": captions})
    assert status == 200 and out == {"stored": 7, "captions": 2}
    assert request(companion, "/api/kandha/session/events", {"session_id": "someone-else", "events": events})[0] == 409
    assert request(companion, "/api/kandha/session/events", {"session_id": sid, "captions": [{"start": 2, "end": 1, "text": "x", "voice": 1}]})[0] == 400
    assert request(companion, "/api/kandha/session/events", {"session_id": sid, "captions": [{"start": 1, "end": 2, "text": " ", "voice": 1}]})[0] == 400
    # consent first, then only this session
    assert request(companion, "/api/kandha/session/save", {"consent": False, "session_id": sid})[0] == 403
    assert request(companion, "/api/kandha/session/save", {"consent": True})[0] == 409
    assert request(companion, "/api/kandha/session/save", {"consent": True, "session_id": "stale"})[0] == 409
    status, vtt, _ = request(companion, f"/api/export?format=vtt&session={sid}")
    assert status == 200 and b"Voice 1: Good morning, everyone." in vtt and b"Leftover" not in vtt
    assert request(companion, "/api/export?format=json&session=stale")[0] == 409
    status, saved, _ = request(companion, "/api/kandha/session/save", {"consent": True, "session_id": sid, "title": "Kandha demo: Seminar"})
    assert status == 200 and saved == {"saved": f"{sid}.json", "title": "Kandha demo: Seminar", "captions": 2, "voice_events": 7}
    data = json.loads((sessions / f"{sid}.json").read_text())
    assert [c["text"] for c in data["captions"]] == ["Good morning, everyone.", "Shall we begin with the case?"]
    assert {e["kind"] for e in data["voice_view"]["events"]} == {"voice", "cue", "tone", "queue", "haptic", "seat"}
    assert "Leftover" not in json.dumps(data)
    # the companion's own export (no session) is unchanged: its last capture
    assert b"Leftover" in request(companion, "/api/export?format=vtt")[1]
    # the next session replaces the record; the old id can no longer write or save
    request(companion, "/api/kandha/session/new", {})
    assert request(companion, "/api/kandha/session/events", {"session_id": sid, "events": events})[0] == 409
    assert request(companion, "/api/kandha/session/save", {"consent": True, "session_id": sid})[0] == 409


def test_the_page_record_shows_what_the_stole_plays_after_mirror_and_zone_intensity(tmp_path):
    from app.kandha.patterns import effective_level, table
    events = []
    service = KandhaService(publish=lambda k, d: events.append(d), home=tmp_path, start_bridge=False, ticker=False)
    try:
        service.update_settings({"mirror": True, "intensity": {"L": 0, "R": 50}})
        tap = table().by_key["seat_tap"]
        played = service.test("L")[0]
        assert played["command_zones"] == "L" and played["zones"] == "R", "mirror: a left tap plays on the right shoulder"
        assert {s["zone"] for s in played["segments"]} == {"R"}
        assert played["segments"][0]["level"] == effective_level(tap.steps[0].level, played["intensity"], round(50 * 255 / 100))
        assert service.virtual.levels()["R"] == played["segments"][0]["level"] and service.virtual.levels()["L"] == 0
        assert [e for e in events if e["kind"] == "haptic"][-1]["segments"] == played["segments"], "the stream carries the same detail"
        silent = service.test("R")[0]
        assert silent["zones"] == "L" and all(s["level"] == 0 for s in silent["segments"]), "a zone at 0 % does not light"
        service.update_settings({"mirror": False, "intensity": {"L": 100, "R": 100}})
        steps = service.test(None, "new_voice")[0]
        assert [(s["zone"], s["start_ms"], s["end_ms"]) for s in steps["segments"]] == [("F", 0, 60), ("F", 150, 210)], "two taps with a rest"
        assert steps["duration_ms"] == 210
        assert service.stop_haptics()[0]["zones"] == "" and service.played[-1]["segments"] == []
    finally:
        service.close()


def test_switching_the_link_publishes_the_new_link_kind(tmp_path):
    events = []
    service = KandhaService(publish=lambda k, d: events.append(d), home=tmp_path, ticker=False)
    try:
        assert service.snapshot()["stole"]["simulated"] is True
        events.clear()
        service.update_settings({"link": "bluetooth"})
        states = [e for e in events if e["kind"] == "stole_state"]
        assert states and states[-1]["simulated"] is False and states[-1]["backend"] == "bleak"
        events.clear()
        service.update_settings({"link": "simulated"})
        time.sleep(0.1)
        states = [e for e in events if e["kind"] == "stole_state"]
        assert states and all(s["simulated"] is True and s["backend"] == "mock" for s in states), states
    finally:
        service.close()


def test_voices_past_64_keep_the_intents_api_working(companion):
    status, out, _ = request(companion, "/api/kandha/intents", {"intents": [{"kind": "new_voice", "voice": 65, "t": 1.0, "new": True}], "current": 65})
    assert status == 200 and out["played"][0]["pattern"] == "new_voice"
    time.sleep(0.3)
    status, out, _ = request(companion, "/api/kandha/intents", {"intents": [{"kind": "silence", "t": 9.0}], "current": 65})
    assert status == 200 and out["accepted"] == 1
    assert request(companion, "/api/kandha/seats", {"voice": 65, "zone": "L"})[1]["seats"]["65"] == "L"
    assert request(companion, "/api/kandha/merge", {"keep": 1, "drop": 65})[0] == 200
    assert request(companion, "/api/kandha/intents", {"intents": [{"kind": "speaker", "voice": 0}]})[0] == 400
    assert clean_events([{"kind": "voice", "t": 1, "id": 1000}, {"kind": "haptic", "t": 1, "zones": "L", "pattern": "seat_tap", "voice": 900}])[0]["id"] == 1000


def test_a_blank_kandha_session_export_is_refused_never_an_earlier_capture(companion):
    # the page lost its record id (another window replaced the session): ?session= is empty
    status, started, _ = request(companion, "/api/start", {"mode": "tone"})
    assert status == 200
    companion.engine.emit("caption", Caption(0.5, 2.0, "Words from another group's capture", "Unattributed"))
    request(companion, "/api/stop", {"session_id": started["session_id"]})
    sid = request(companion, "/api/kandha/session/new", {})[1]["session_id"]
    request(companion, "/api/kandha/session/events", {"session_id": sid, "captions": [{"start": 1, "end": 2, "text": "Ours", "voice": 1}]})
    for query in ("session=", "session", "session=&format=json", "session=%20"):
        status, body, _ = request(companion, f"/api/export?format=vtt&{query}")
        assert status == 409, (query, status)
        assert b"another group" not in json.dumps(body).encode()
    # a named session still exports; no session at all is the companion's own export
    assert b"Voice 1: Ours" in request(companion, f"/api/export?format=vtt&session={sid}")[1]
    assert b"another group" in request(companion, "/api/export?format=vtt")[1]


def test_a_whisper_captioned_kandha_session_keeps_the_engine_caption_details(companion):
    from app.utils.paths import data_root
    status, started, _ = request(companion, "/api/start", {"mode": "tone"})
    capture = started["session_id"]
    sid = request(companion, "/api/kandha/session/new", {})[1]["session_id"]
    companion.engine.emit("caption", Caption(1.25, 3.5, "Good morning everyone", "Speaker 1", 0.82, 0.91, False, {"f0_hz": 180.0, "dbfs": -22.0}))
    companion.engine.emit("caption", Caption(4.0, 6.0, "so shall we begin then", "Speaker 1", 0.64, 0.7, True, {"f0_hz": 150.0}))
    link = lambda start, end, capture=capture: {"capture": capture, "start": start, "end": end}
    captions = [
        # one Whisper caption shown whole
        {"start": 1.25, "end": 3.5, "text": "Good morning everyone", "voice": 1, "whisper": link(1.25, 3.5)},
        # one Whisper caption the page split between two voices
        {"start": 4.0, "end": 5.2, "text": "so shall we", "voice": 1, "whisper": link(4.0, 6.0)},
        {"start": 5.2, "end": 6.0, "text": "begin then", "voice": 2, "whisper": link(4.0, 6.0)},
        # a link to another capture, or to no caption at all, adds nothing
        {"start": 7.0, "end": 8.0, "text": "Elsewhere", "voice": 2, "whisper": link(1.25, 3.5, "other-capture")},
        {"start": 8.0, "end": 9.0, "text": "Browser words", "voice": 2},
    ]
    assert request(companion, "/api/kandha/session/events", {"session_id": sid, "captions": captions})[1]["captions"] == 5
    # the tone estimate for the first caption arrives after the page sent it
    companion.engine.emit("caption_voice", {"start": 1.25, "end": 3.5, "speaker": "Speaker 1", "estimate": {"tone": "neutral", "confidence": 0.6}})
    request(companion, "/api/stop", {"session_id": capture})
    for bad in ({"capture": 5, "start": 1, "end": 2}, {"capture": "x", "start": -1, "end": 2}, "x", {"capture": "x" * 65, "start": 1, "end": 2}):
        assert request(companion, "/api/kandha/session/events", {"session_id": sid, "captions": [{"start": 1, "end": 2, "text": "x", "voice": 1, "whisper": bad}]})[0] == 400
    status, saved, _ = request(companion, "/api/kandha/session/save", {"consent": True, "session_id": sid})
    assert status == 200 and saved["captions"] == 5
    rows = json.loads((data_root() / "sessions" / f"{sid}.json").read_text())["captions"]
    whole, first, second, elsewhere, browser = rows
    assert (whole["speaker"], whole["word_confidence"], whole["speaker_similarity"], whole["overlap"]) == ("Voice 1", 0.82, 0.91, False)
    assert whole["voice"] == {"f0_hz": 180.0, "dbfs": -22.0, "tone": "neutral", "tone_confidence": 0.6}
    # a piece of a split caption keeps the caption's word confidence and overlap, not another voice's tone
    for piece in (first, second):
        assert (piece["word_confidence"], piece["overlap"], piece["speaker_similarity"], piece["voice"]) == (0.64, True, None, {})
    for row in (elsewhere, browser):
        assert (row["word_confidence"], row["speaker_similarity"], row["overlap"], row["voice"]) == (None, None, None, {})
    assert "whisper" not in whole


def test_a_new_session_names_the_window_that_started_it(companion):
    # the "session" event tells other Kandha windows their session was replaced; the record is
    # already the new one when they hear it
    heard = []
    feed = companion.kandha.subscribe()
    try:
        first = request(companion, "/api/kandha/session/new", {"page": "window-a"})[1]["session_id"]
        second = request(companion, "/api/kandha/session/new", {"page": "window-b"})[1]["session_id"]
        request(companion, "/api/kandha/session/new", {"page": ["not", "a", "tag"]})
        while not feed.empty():
            event = feed.get_nowait()
            if event["kind"] == "session":
                heard.append(event["page"])
    finally:
        companion.kandha.unsubscribe(feed)
    assert heard == ["window-a", "window-b", None]
    assert first != second
    assert request(companion, "/api/kandha/session/events", {"session_id": first, "events": []})[0] == 409


def test_two_windows_starting_at_once_hear_the_session_events_in_record_order(companion, monkeypatch):
    # The page marks itself replaced when it hears another window's "session" event, so the
    # window that holds the current record must hear its own event last. Window A's thread is
    # held up between the record swap and its event (a thread switch) while B starts a session.
    real = companion.kandha.new_session
    swapped = threading.Event()

    def held_up(page=None):
        if page == "window-a":
            swapped.set()
            time.sleep(0.3)
        return real(page)

    monkeypatch.setattr(companion.kandha, "new_session", held_up)
    feed = companion.kandha.subscribe()
    ids = {}

    def start(tag):
        ids[tag] = request(companion, "/api/kandha/session/new", {"page": tag})[1]["session_id"]

    try:
        a = threading.Thread(target=start, args=("window-a",))
        a.start()
        assert swapped.wait(5)
        b = threading.Thread(target=start, args=("window-b",))
        b.start()
        a.join(10)
        b.join(10)
        heard = []
        while not feed.empty():
            event = feed.get_nowait()
            if event["kind"] == "session":
                heard.append(event["page"])
    finally:
        companion.kandha.unsubscribe(feed)
    assert len(heard) == 2
    current = [tag for tag, sid in ids.items() if sid == companion.kandha_session.id]
    assert current == [heard[-1]]
    assert request(companion, "/api/kandha/session/events", {"session_id": ids[heard[-1]], "events": []})[0] == 200
    assert request(companion, "/api/kandha/session/events", {"session_id": ids[heard[0]], "events": []})[0] == 409
