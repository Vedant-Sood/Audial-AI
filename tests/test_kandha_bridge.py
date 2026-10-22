"""StoleBridge with a mock bleak: scan filter, pairing memory, reconnect backoff, stranger input, status, latency."""
import asyncio
import json
import threading
import time

import pytest

from app.kandha.bridge import BACKOFF_S, MockBackend, MockStole, StoleBridge, StoleLink, backoff
from app.kandha.protocol import GESTURE_TAP, PAD_Q, HapticCommand, StoleConfig, uuids


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
    assert found[0]["name"] == "KandhaStole-EE01"
    assert run(link.pair(stole.address, stole.name)) is True
    saved = json.loads((tmp_path / "stole.json").read_text())
    assert saved["address"] == stole.address and saved["name"] == "KandhaStole-EE01"
    assert link.state == "connected" and link.status.battery == 87 and recorder.last("stole_status")["battery"] == 87
    assert stole.received[0][1] == "config", "CONFIG is written on connect"
    # a second link remembers the device without scanning
    again = StoleLink(backend, Recorder(), store_path=tmp_path / "stole.json")
    assert again.paired == stole.address and again.paired_name == "KandhaStole-EE01"
    run(link.forget())
    assert link.paired is None and not (tmp_path / "stole.json").exists() and link.state == "disconnected"


def test_haptic_writes_reach_the_stole_only_while_connected_and_measure_latency(tmp_path):
    stole = MockStole()
    link = StoleLink(MockBackend([stole]), Recorder(), store_path=tmp_path / "s.json")
    assert run(link.write_haptic(HapticCommand(1, 1, 1, 200).encode())) is None, "not connected: nothing written"
    run(link.pair(stole.address))
    ms = run(link.write_haptic(HapticCommand(1, 1, 1, 200).encode()))
    assert ms is not None and ms < 50 and link.snapshot()["latency_ms"]["n"] == 1
    assert stole.received[-1][1] == "haptic" and stole.player.timeline()[0][0] == "L"
    assert run(link.write_config(StoleConfig(mirror=True))) is True and stole.config.mirror


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
