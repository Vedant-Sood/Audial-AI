"""StoleBridge with a mock bleak: scan filter, pairing memory, reconnect backoff, stranger input, status, latency."""
import asyncio
import json
import sys
import threading
import time

import pytest

from app.kandha.bridge import BACKOFF_S, MockBackend, MockBleakClient, MockStole, StoleBridge, StoleLink, backoff
from app.kandha.protocol import GESTURE_TAP, PAD_Q, HapticCommand, StoleConfig, name_prefix, uuids


def run(coro):
    return asyncio.run(coro)


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, kind, data):
        self.events.append((kind, data))

    def kinds(self):
        return [k for k, _ in self.events]

    def last(self, kind):
        return next((d for k, d in reversed(self.events) if k == kind), None)


def test_backoff_sequence_is_one_two_four_eight_sixteen_thirty():
    assert [backoff(i) for i in range(8)] == [1, 2, 4, 8, 16, 30, 30, 30] and BACKOFF_S[-1] == 30


def test_scan_lists_only_kandha_stoles_and_pairing_is_remembered(tmp_path):
    stole = MockStole("AA:BB:CC:DD:EE:01")
    unnamed = MockStole("AA:BB:CC:DD:EE:02", name="Headphones", advertises_service=False)
    by_name_only = MockStole("AA:BB:CC:DD:EE:03", advertises_service=False)
    backend = MockBackend([stole, unnamed, by_name_only])
    recorder = Recorder()
    link = StoleLink(backend, recorder, store_path=tmp_path / "stole.json")
    found = run(link.scan(0.1))
    assert sorted(d["address"] for d in found) == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:03"]
    assert found[0]["name"] == "Kandha-EE01" and by_name_only.name == "Kandha-EE03", "the brief's Kandha-XXXX"
    assert run(link.pair(stole.address, stole.name)) is True
    saved = json.loads((tmp_path / "stole.json").read_text())
    assert saved["address"] == stole.address and saved["name"] == "Kandha-EE01"
    assert link.state == "connected" and link.status.battery == 87 and recorder.last("stole_status")["battery"] == 87
    assert stole.received[0][1] == "config", "CONFIG is written on connect"
    # a second link remembers the device without scanning
    again = StoleLink(backend, Recorder(), store_path=tmp_path / "stole.json")
    assert again.paired == stole.address and again.paired_name == "Kandha-EE01"
    run(link.forget())
    assert link.paired is None and not (tmp_path / "stole.json").exists() and link.state == "disconnected"


def test_the_bleak_scan_matches_the_service_uuid_or_the_kandha_name_prefix(monkeypatch):
    from types import SimpleNamespace
    from app.kandha.bridge import BleakBackend

    def seen(address, name, services, rssi):
        return SimpleNamespace(address=address, name=None), SimpleNamespace(local_name=name, service_uuids=services, rssi=rssi)

    service = uuids()["service"]
    found = {"1": seen("AA:01", "Kandha-0A01", [], -70),               # name only, as the brief says it advertises
             "2": seen("AA:02", None, [service.upper()], -50),         # service UUID only
             "3": seen("AA:03", "Headphones", ["0000180f-0000-1000-8000-00805f9b34fb"], -40)}

    class Scanner:
        @staticmethod
        async def discover(timeout, return_adv):
            return found

    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakScanner=Scanner))
    devices = run(BleakBackend().scan(0.1, service, name_prefix()))
    assert [(d["address"], d["name"]) for d in devices] == [("AA:02", "AA:02"), ("AA:01", "Kandha-0A01")]


def test_haptic_writes_reach_the_stole_only_while_connected_and_measure_latency(tmp_path):
    stole = MockStole()
    link = StoleLink(MockBackend([stole]), Recorder(), store_path=tmp_path / "s.json")
    assert run(link.write_haptic(HapticCommand(1, 1, 1, 200).encode())) is None, "not connected: nothing written"
    run(link.pair(stole.address))
    ms = run(link.write_haptic(HapticCommand(1, 1, 1, 200).encode()))
    assert ms is not None and ms < 50 and link.snapshot()["latency_ms"]["n"] == 1
    assert stole.received[-1][1] == "haptic" and stole.player.timeline()[0][0] == "L"
    assert run(link.write_config(StoleConfig(mirror=True))) is True and stole.config.mirror


def test_a_new_connection_resets_the_mock_stoles_duplicate_filter():
    """C50, as the firmware does: the app's seq starts again with every launch, so a command with the
    previous connection's last seq still plays; within one connection a repeat is still a duplicate."""
    now = [1.0]
    stole = MockStole(clock=lambda: now[0])
    starts = []
    original = stole.player.start
    stole.player.start = lambda *args, **kwargs: (starts.append(now[0]), original(*args, **kwargs))[1]
    connected = bytes.fromhex("01030c7801")     # seq 1, both shoulders, the connection ticks

    async def scenario():
        first = MockBleakClient(stole, None, lambda: None)
        await first.connect()
        await first.write_gatt_char(uuids()["haptic"], connected)
        await first.write_gatt_char(uuids()["haptic"], connected)      # a duplicate delivery
        await first.disconnect()
        now[0] = 5.0
        second = MockBleakClient(stole, None, lambda: None)          # the app was launched again
        await second.connect()
        await second.write_gatt_char(uuids()["haptic"], connected)

    run(scenario())
    assert starts == [1.0, 5.0], starts


def test_reconnects_with_backoff_after_a_drop_and_keeps_captions_out_of_it(tmp_path):
    stole = MockStole()
    backend = MockBackend([stole])
    recorder = Recorder()
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    link = StoleLink(backend, recorder, store_path=tmp_path / "s.json", sleep=fake_sleep)

    async def scenario():
        await link.pair(stole.address)
        runner = asyncio.ensure_future(link.run())
        await asyncio.sleep(0)
        stole.connect_failures = 3          # the next three attempts fail
        stole.drop()
        for _ in range(60):
            await asyncio.sleep(0.01)
            if link.state == "connected" and stole.connect_failures == 0 and link.attempt == 0:
                break
        states = [d["state"] for k, d in recorder.events if k == "stole_state"]
        tries = [d.get("next_try_s") for k, d in recorder.events if k == "stole_state" and d.get("next_try_s")]
        await link.stop()
        await runner
        return states, tries

    states, tries = run(scenario())
    assert "reconnecting" in states and states[-1] == "disconnected" or link.state == "disconnected"
    assert tries[:3] == [1, 2, 4], f"backoff before the three failed attempts: {tries}"
    assert recorder.kinds().count("stole_connected") >= 2, "connected again after the drop"


def test_input_from_the_paired_stole_is_delivered_and_a_stranger_is_ignored(tmp_path):
    paired, stranger = MockStole("AA:BB:CC:DD:EE:01"), MockStole("AA:BB:CC:DD:EE:09")
    backend = MockBackend([paired, stranger])
    recorder = Recorder()
    link = StoleLink(backend, recorder, store_path=tmp_path / "s.json")

    async def scenario():
        await link.pair(paired.address)
        paired.press(PAD_Q, GESTURE_TAP)
        stranger.press(PAD_Q, GESTURE_TAP)
        # a notification arriving through a client for another address is dropped too
        link._on_input(None, bytes([4, 1]))
        link.client.address = stranger.address
        link._on_input(None, bytes([4, 1]))
        link._on_input(None, bytes([9, 9]))
        await asyncio.sleep(0.01)

    run(scenario())
    inputs = [d for k, d in recorder.events if k == "input"]
    assert inputs == [{"device": "stole", "pad": "Q", "gesture": "tap", "raw": "0401"}] * 2


def test_low_battery_is_reported_once_until_charging(tmp_path):
    stole = MockStole(battery=50)
    recorder = Recorder()
    link = StoleLink(MockBackend([stole]), recorder, store_path=tmp_path / "s.json")

    async def scenario():
        await link.pair(stole.address)
        stole.set_battery(20)
        stole.set_battery(15)
        stole.set_battery(12, charging=True)
        stole.set_battery(10, charging=False)
        await asyncio.sleep(0.01)

    run(scenario())
    assert recorder.kinds().count("low_battery") == 2
    assert recorder.last("stole_status")["battery"] == 10 and recorder.last("stole_status")["low_battery"]


def test_connect_failure_and_scan_failure_become_messages_not_crashes(tmp_path):
    class BrokenBackend(MockBackend):
        async def scan(self, timeout, service_uuid, prefix):
            raise OSError("No Bluetooth adapter")

    backend = BrokenBackend([])
    recorder = Recorder()
    link = StoleLink(backend, recorder, store_path=tmp_path / "s.json")
    assert run(link.scan(0.1)) == [] and "No Bluetooth adapter" in link.last_error
    assert run(link.pair("11:22:33:44:55:66")) is False and link.state == "reconnecting" and link.paired == "11:22:33:44:55:66"


def test_thread_wrapper_runs_the_link_and_stops_cleanly(tmp_path):
    stole = MockStole()
    backend = MockBackend([stole])
    recorder = Recorder()
    bridge = StoleBridge(recorder, backend=backend, store_path=tmp_path / "s.json")
    bridge.start()
    try:
        assert bridge.scan(0.1)[0]["address"] == stole.address
        assert bridge.pair(stole.address, stole.name) is True and bridge.connected
        bridge.write_haptic(HapticCommand(3, 8, 1, 230).encode()).result(5)
        bridge.write_config(StoleConfig(scale_f=100)).result(5)
        assert stole.player.timeline()[0][0] == "F" and stole.config.scale_f == 100
        stole.press(PAD_Q, GESTURE_TAP)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and recorder.last("input") is None:
            time.sleep(0.01)
        assert recorder.last("input")["pad"] == "Q"
        assert bridge.snapshot()["state"] == "connected" and bridge.snapshot()["backend"] == "mock"
    finally:
        bridge.stop()
    assert bridge.thread is None and threading.active_count() >= 1


# ---------------------------------------------------------------------------- pairing races and failures
class YieldingBackend(MockBackend):
    """Like real bleak, connect() and disconnect() await I/O, so other tasks run meanwhile."""

    def client(self, address, disconnected_callback):
        client = MockBleakClient(self.stoles.get(address), disconnected_callback, lambda: self.loop)
        plain_connect, plain_disconnect = client.connect, client.disconnect

        async def connect():
            await asyncio.sleep(0.05)
            return await plain_connect()

        async def disconnect():
            await asyncio.sleep(0.01)
            return await plain_disconnect()

        client.connect, client.disconnect = connect, disconnect
        return client


class NoClientBackend(MockBackend):
    """bleak, or its platform backend, cannot be imported: building a client raises."""

    def client(self, address, disconnected_callback):
        raise ImportError("No module named 'bleak'")


async def instant(_seconds):
    await asyncio.sleep(0)


async def settle(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    return predicate()


async def finish(link, runner):
    """Stop the link; True when run() ended promptly."""
    await link.stop()
    done, _ = await asyncio.wait({runner}, timeout=2)
    if not done:
        runner.cancel()
    return bool(done)


def test_forget_then_pair_again_still_reconnects_after_a_drop(tmp_path):
    first, second = MockStole("AA:BB:CC:DD:EE:01"), MockStole("AA:BB:CC:DD:EE:02")
    link = StoleLink(MockBackend([first, second]), Recorder(), store_path=tmp_path / "s.json", sleep=instant)

    async def scenario():
        runner = asyncio.ensure_future(link.run())
        await asyncio.sleep(0)
        for step in (lambda: link.pair(first.address), link.forget, lambda: link.pair(first.address)):
            await step()
            await asyncio.sleep(0.01)               # a person's clicks are apart: run() catches up between them
        first.connect_failures = 1
        first.drop()
        after_forget = await settle(lambda: link.connected and first.connect_failures == 0)
        await link.pair(second.address)             # switch stoles without Forget, then lose the link
        await asyncio.sleep(0.01)
        second.drop()
        after_switch = await settle(lambda: link.connected and len(second.clients) == 1)
        return after_forget, after_switch, await finish(link, runner)

    after_forget, after_switch, stopped = run(scenario())
    assert after_forget, f"Forget, Pair, drop: the stole never reconnected ({link.snapshot()})"
    assert after_switch, f"Pair another stole, drop: it never reconnected ({link.snapshot()})"
    assert stopped and first.clients == [] and second.clients == []


def test_pairing_the_connected_stole_again_keeps_one_client_and_one_input_per_press(tmp_path):
    stole = MockStole()
    recorder = Recorder()
    link = StoleLink(MockBackend([stole]), recorder, store_path=tmp_path / "s.json", sleep=instant)

    async def press_count():
        before = recorder.kinds().count("input")
        stole.press(PAD_Q, GESTURE_TAP)
        await asyncio.sleep(0.01)
        return recorder.kinds().count("input") - before

    async def scenario():
        runner = asyncio.ensure_future(link.run())
        await asyncio.sleep(0)
        out = {"first": await link.pair(stole.address, "Old name"), "again": await link.pair(stole.address, "New name")}
        await asyncio.sleep(0.05)
        out |= {"clients": len(stole.clients), "inputs": await press_count(), "name": link.paired_name,
                "connected_events": recorder.kinds().count("stole_connected")}
        await link.forget()                         # Forget then Pair: still exactly one client
        await link.pair(stole.address)
        out["clients_after_forget"] = len(stole.clients)
        stole.drop()                                # and the reconnect loop still follows this connection
        out["reconnected"] = await settle(lambda: link.connected)
        out |= {"clients_after_drop": len(stole.clients), "inputs_after_drop": await press_count(),
                "stopped": await finish(link, runner)}
        return out

    out = run(scenario())
    assert out["first"] is True and out["again"] is True and out["name"] == "New name"
    assert out["clients"] == 1 and out["inputs"] == 1 and out["connected_events"] == 1, out
    assert out["clients_after_forget"] == 1 and out["reconnected"], out
    assert out["clients_after_drop"] == 1 and out["inputs_after_drop"] == 1 and out["stopped"], out


def test_pair_racing_the_reconnect_loop_opens_one_connection_when_connect_yields(tmp_path):
    stole, other = MockStole("AA:BB:CC:DD:EE:01"), MockStole("AA:BB:CC:DD:EE:02")
    recorder = Recorder()
    link = StoleLink(YieldingBackend([stole, other]), recorder, store_path=tmp_path / "s.json", sleep=instant)

    async def scenario():
        runner = asyncio.ensure_future(link.run())
        await asyncio.sleep(0)
        out = {"paired": await link.pair(stole.address)}       # the kick wakes run() while connect() awaits
        await asyncio.sleep(0.2)
        out |= {"clients": len(stole.clients), "connected_events": recorder.kinds().count("stole_connected")}
        stole.press(PAD_Q, GESTURE_TAP)
        await asyncio.sleep(0.01)
        out["inputs"] = recorder.kinds().count("input")
        stole.drop()                                # run() starts reconnecting ...
        await asyncio.sleep(0.01)
        out["repaired"] = await link.pair(stole.address)        # ... and the user presses Pair meanwhile
        await asyncio.sleep(0.2)
        out["clients_after_repair"] = len(stole.clients)
        stole.drop()                                # run() reconnects again; the user picks the other stole
        await asyncio.sleep(0.01)
        out["switched"] = await link.pair(other.address)
        await asyncio.sleep(0.2)
        out |= {"old_clients": len(stole.clients), "new_clients": len(other.clients),
                "on_other": link.connected and link.paired == other.address, "stopped": await finish(link, runner)}
        return out

    out = run(scenario())
    assert out["paired"] and out["clients"] == 1 and out["connected_events"] == 1 and out["inputs"] == 1, out
    assert out["repaired"] and out["clients_after_repair"] == 1, out
    assert out["switched"] and out["old_clients"] == 0 and out["new_clients"] == 1 and out["on_other"], out
    assert out["stopped"], out

    # the same through the bridge thread, where pair() is posted to the loop that runs run()
    stole = MockStole()
    recorder = Recorder()
    bridge = StoleBridge(recorder, backend=YieldingBackend([stole]), store_path=tmp_path / "t.json")
    bridge.start()
    try:
        assert bridge.pair(stole.address) is True
        time.sleep(0.2)
        stole.press(PAD_Q, GESTURE_TAP)
        time.sleep(0.1)
        assert len(stole.clients) == 1 and recorder.kinds().count("stole_connected") == 1
        assert recorder.kinds().count("input") == 1
    finally:
        started = time.monotonic()
        bridge.stop()
        stop_s = time.monotonic() - started
    assert stop_s < 2 and stole.clients == [], "stop() waits for the link to close, without waiting out its timeout"


def test_a_backend_that_cannot_build_a_client_leaves_the_bridge_responsive(tmp_path):
    stole = MockStole()
    store = tmp_path / "stole.json"
    store.write_text(json.dumps({"address": stole.address, "name": stole.name, "protocol": 1}))
    bridge = StoleBridge(Recorder(), backend=NoClientBackend([stole]), store_path=store)
    bridge.start()                                  # the remembered stole is tried straight away
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and "bleak" not in str(bridge.snapshot()["error"]):
            time.sleep(0.01)
        assert bridge.thread.is_alive(), "the bridge thread died"
        assert "bleak" in bridge.snapshot()["error"] and bridge.snapshot()["state"] == "reconnecting"
        started = time.monotonic()
        assert [d["address"] for d in bridge.scan(0.1)] == [stole.address]
        assert bridge.pair(stole.address, stole.name) is False and "bleak" in bridge.snapshot()["error"]
        bridge.forget()
        assert not store.exists() and bridge.snapshot()["paired"] is None
        assert time.monotonic() - started < 2, "bridge calls waited out their timeouts"
    finally:
        started = time.monotonic()
        bridge.stop()
        stop_s = time.monotonic() - started
    assert stop_s < 2 and bridge.thread is None

    # even if the link loop itself fails, calls are still served and stop() is prompt
    recorder = Recorder()
    crashing = StoleBridge(recorder, backend=MockBackend([stole]), store_path=tmp_path / "other.json")

    async def broken_run():
        raise RuntimeError("boom")

    crashing.link.run = broken_run
    crashing.start()
    try:
        time.sleep(0.05)
        assert crashing.thread.is_alive() and "boom" in recorder.last("stole_error")["error"]
        assert crashing.pair(stole.address) is True and crashing.connected
    finally:
        started = time.monotonic()
        crashing.stop()
        stop_s = time.monotonic() - started
    assert stop_s < 2 and crashing.thread is None


class LateConnectBackend(MockBackend):
    """connect() finishes in the same moment its cancel lands and the cancel is lost (asyncio.wait_for on
    Python 3.11 does this), so the attempt carries on after forget(), another pair() or stop() asked it to end."""

    def client(self, address, disconnected_callback):
        client = MockBleakClient(self.stoles.get(address), disconnected_callback, lambda: self.loop)
        plain_connect = client.connect

        async def connect():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
            return await plain_connect()

        client.connect = connect
        return client


class RadioBackend(MockBackend):
    """Like bleak: it cannot name a remembered stole until a scan hears it."""

    name_of = None


@pytest.mark.parametrize("action", ["stop", "forget", "forget_then_pair_again", "pair_other"])
def test_a_connect_that_outlives_its_cancel_never_becomes_the_live_link(tmp_path, action):
    stole, other = MockStole("AA:BB:CC:DD:EE:01"), MockStole("AA:BB:CC:DD:EE:02")
    recorder = Recorder()
    link = StoleLink(LateConnectBackend([stole, other]), recorder, store_path=tmp_path / "s.json", sleep=instant)

    async def scenario():
        tasks = [asyncio.ensure_future(link.pair(stole.address))]
        await asyncio.sleep(0.01)                   # connect() is under way
        if action == "stop":
            await link.stop()
        elif action == "forget":
            await link.forget()
        elif action == "forget_then_pair_again":    # two quick clicks: Pair comes while Forget is still closing
            forgetting = asyncio.ensure_future(link.forget())
            tasks.append(asyncio.ensure_future(link.pair(stole.address)))
            await forgetting
        else:
            tasks.append(asyncio.ensure_future(link.pair(other.address)))
        await asyncio.sleep(0.01)
        during = {"clients": len(stole.clients) + len(other.clients), "live": link.client is not None}
        await link.stop()
        await asyncio.wait(tasks, timeout=1)
        return during | {"after": len(stole.clients) + len(other.clients), "live_after": link.client is not None,
                         "pending": sum(not t.done() for t in tasks)}

    out = run(scenario())
    assert out["clients"] == 0 and not out["live"], f"{action}: an abandoned attempt kept a client ({out})"
    assert out["after"] == 0 and not out["live_after"] and out["pending"] == 0, out
    assert recorder.kinds().count("stole_connected") == 0 and link.state == "disconnected", (out, link.snapshot())
    assert link.last_error is None, "an abandoned attempt is not an error to show"


def test_a_call_in_flight_when_the_bridge_stops_fails_as_a_plain_error(tmp_path):
    bridge = StoleBridge(Recorder(), backend=MockBackend([MockStole()], scan_delay=2.0), store_path=tmp_path / "s.json")
    bridge.start()
    result = {}

    def scan():
        try:
            result["devices"] = bridge.scan(3.0)
        except BaseException as error:              # the HTTP handler catches RuntimeError, never CancelledError
            result["error"] = error

    worker = threading.Thread(target=scan)
    worker.start()
    time.sleep(0.2)                                 # the scan is under way
    started = time.monotonic()
    bridge.stop()
    worker.join(5)
    assert isinstance(result.get("error"), RuntimeError), result
    assert time.monotonic() - started < 2

    # a call whose loop thread has gone never waits out its timeout
    gone = StoleBridge(Recorder(), backend=MockBackend(), store_path=tmp_path / "t.json")
    gone.loop = asyncio.new_event_loop()            # nobody runs this loop ...
    gone.thread = threading.Thread(target=time.sleep, args=(0.2,))
    gone.thread.start()                             # ... and its thread ends a moment from now
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError):
            gone.call(asyncio.sleep(0), 5)
        assert time.monotonic() - started < 2
    finally:
        gone.loop.run_until_complete(asyncio.sleep(0.01))
        gone.loop.close()


def test_a_name_saved_by_an_earlier_build_gives_way_to_the_stoles_own_name(tmp_path):
    stole = MockStole("AA:BB:CC:DD:EE:01")
    store = tmp_path / "s.json"
    store.write_text(json.dumps({"address": stole.address, "name": "KandhaStole-EE01", "protocol": 1}))  # the old prefix
    # the simulated stole lives in the app, so its backend names it straight away
    assert StoleLink(MockBackend([stole]), Recorder(), store_path=store).paired_name == "Kandha-EE01"
    # a stole on the radio is renamed when a scan hears its new name
    recorder = Recorder()
    link = StoleLink(RadioBackend([stole]), recorder, store_path=store)
    assert link.paired_name == "KandhaStole-EE01"
    run(link.scan(0))
    assert link.paired_name == "Kandha-EE01" and json.loads(store.read_text())["name"] == "Kandha-EE01"
    assert recorder.last("stole_state")["name"] == "Kandha-EE01"
    assert StoleLink(RadioBackend([stole]), Recorder(), store_path=store).paired_name == "Kandha-EE01"


class SlowCloseBackend(MockBackend):
    """Closing a half-made connection takes longer than making a new one."""

    def client(self, address, disconnected_callback):
        client = MockBleakClient(self.stoles.get(address), disconnected_callback, lambda: self.loop)
        plain_connect, plain_disconnect = client.connect, client.disconnect

        async def connect():
            await asyncio.sleep(0.02)
            return await plain_connect()

        async def disconnect():
            await asyncio.sleep(0.1)
            return await plain_disconnect()

        client.connect, client.disconnect = connect, disconnect
        return client


def test_forget_and_pair_at_once_leave_one_connection(tmp_path):
    stole = MockStole()
    recorder = Recorder()
    link = StoleLink(SlowCloseBackend([stole]), recorder, store_path=tmp_path / "s.json", sleep=instant)

    async def scenario():
        runner = asyncio.ensure_future(link.run())
        first = asyncio.ensure_future(link.pair(stole.address))
        await asyncio.sleep(0.005)                  # connect() is under way
        await asyncio.gather(link.forget(), link.pair(stole.address))   # Pair lands while Forget still closes
        await asyncio.sleep(0.3)
        before = recorder.kinds().count("input")
        stole.press(PAD_Q, GESTURE_TAP)
        await asyncio.sleep(0.01)
        out = {"clients": len(stole.clients), "connected": link.connected, "paired": link.paired,
               "inputs": recorder.kinds().count("input") - before, "stopped": await finish(link, runner)}
        await asyncio.wait({first}, timeout=1)
        return out | {"left": len(stole.clients)}

    out = run(scenario())
    assert out["paired"] == stole.address and out["connected"], out
    assert out["clients"] == 1 and out["inputs"] == 1, out
    assert out["stopped"] and out["left"] == 0, out
