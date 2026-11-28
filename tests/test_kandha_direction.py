"""Direction from multichannel audio (decision 0027). Every result here is SIMULATED: the rooms
are synthetic (app/kandha/room_synth.py), with real LibriSpeech voices at known bearings."""
import time

import numpy as np
import pytest

from app.kandha.bridge import MockBackend, MockStole
from app.kandha.direction import ArrayGeometry, DirectionTracker, circular_mean, gcc_phat, is_fake_stereo, side_zone
from app.kandha.room_synth import Room, Talker
from app.kandha.seatmap import angle_to_zone
from app.kandha.service import KandhaService

RATE = 48000


def run(room, tracker=None, step=2400):
    audio = room.render()
    tracker = tracker or DirectionTracker(room.geometry, room.rate)
    for i in range(0, len(audio), step):
        tracker.feed(audio[i:i + step], (i + step) / room.rate)
    return tracker


def angular_error(a, b):
    return abs((a - b + 180) % 360 - 180)


def test_gcc_phat_finds_a_known_delay():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(4096)
    lag, confidence = gcc_phat(np.roll(x, 3), x, RATE, 8)
    assert lag == pytest.approx(3.0, abs=0.13) and confidence > 0.9


@pytest.mark.parametrize("bearing", [0, 45, 90, 135, 180, 225, 270, 315, 20, 200])
def test_quad_array_recovers_the_bearing(bearing):
    tracker = run(Room(ArrayGeometry.quad(), [Talker(bearing, 0.3, 2.5)], noise_db=-50))
    found = tracker.direction_between(0, 10)
    assert found is not None and angular_error(found["bearing"], bearing) < 3, found


@pytest.mark.parametrize("bearing,zone", [(0, "F"), (30, "F"), (70, "R"), (90, "R"), (290, "L"), (270, "L"), (330, "F")])
def test_stereo_tells_left_centre_right(bearing, zone):
    tracker = run(Room(ArrayGeometry.stereo(0.03), [Talker(bearing, 0.3, 2.5)], noise_db=-50))
    found = tracker.direction_between(0, 10)
    assert found is not None and side_zone(found["bearing"], True) == zone, found


def test_stereo_cannot_tell_front_from_behind_and_says_so():
    """Two microphones in a line hear a voice behind exactly like one in front: it maps to F."""
    behind = run(Room(ArrayGeometry.stereo(0.03), [Talker(180, 0.3, 2.5)], noise_db=-50)).direction_between(0, 10)
    assert side_zone(behind["bearing"], True) == "F" and angle_to_zone(180) == "B"
    assert DirectionTracker(ArrayGeometry.stereo()).latest()["sided_only"] is True


def test_swapped_channels_are_corrected_by_the_swap_setting():
    room = Room(ArrayGeometry.stereo(0.03, swap=True), [Talker(270, 0.3, 2.5)], noise_db=-50)   # wired right-left
    wrong = run(room, DirectionTracker(ArrayGeometry.stereo(0.03), RATE)).direction_between(0, 10)
    right = run(room, DirectionTracker(ArrayGeometry.stereo(0.03, swap=True), RATE)).direction_between(0, 10)
    assert side_zone(wrong["bearing"], True) == "R" and side_zone(right["bearing"], True) == "L"


def test_noise_and_an_echo_still_give_the_right_zone():
    room = Room(ArrayGeometry.quad(), [Talker(90, 0.3, 3.0)], noise_db=-32, echoes=[(140, 0.004, 0.4)])
    found = run(room).direction_between(0, 10)
    assert found is not None and angle_to_zone(found["bearing"]) == "R"


def test_fake_stereo_is_detected():
    mono = np.random.default_rng(1).standard_normal(RATE)
    assert is_fake_stereo(np.stack([mono, mono], axis=1))
    assert is_fake_stereo(np.stack([mono, mono * (1 + 1e-5)], axis=1))
    assert not is_fake_stereo(Room(ArrayGeometry.stereo(), [Talker(90, 0, 1.0)]).render())


def test_frames_during_and_just_after_a_tap_are_ignored():
    room = Room(ArrayGeometry.quad(), [Talker(270, 0.0, 2.0)], noise_db=-50)
    tracker = DirectionTracker(room.geometry, RATE)
    tracker.mute(10.0)                                   # a tap "plays" for the whole clip
    run(room, tracker)
    assert tracker.direction_between(0, 10) is None and not tracker.readings


def test_turns_are_split_at_pauses_with_their_own_direction():
    room = Room(ArrayGeometry.quad(), [Talker(270, 0.3, 2.0), Talker(90, 3.0, 2.0)], noise_db=-50)
    turns = run(room).take_turns()
    zones = [angle_to_zone(t["bearing"]) for t in turns if t["bearing"] is not None and t["t1"] - t["t0"] > 0.6]
    assert zones[:2] == ["L", "R"], turns


def test_circular_mean_wraps_around_north():
    assert angular_error(circular_mean([350, 10]), 0) < 1e-6


class _FakeInput:
    def __init__(self, tracker):
        self.tracker = tracker

    def status(self):
        return {"simulated": True, **self.tracker.latest()}

    def stop(self):
        pass


def test_end_to_end_direction_seats_voices_and_taps_the_right_shoulder(tmp_path):
    """4-channel synthetic room -> direction -> seat map -> scheduler -> HAPTIC bytes on the mock stole."""
    stole = MockStole()
    clock = [0.0]
    service = KandhaService(home=tmp_path, backend=MockBackend([stole]), ticker=False, clock=lambda: clock[0])
    try:
        assert service.pair(stole.address) is True
        geometry = ArrayGeometry.quad()
        tracker = DirectionTracker(geometry, RATE)
        service.use_direction(_FakeInput(tracker))
        audio = Room(geometry, [Talker(270, 0.3, 2.7), Talker(90, 4.0, 2.7)], noise_db=-50).render()

        def play_until(t):
            start = int(play_until.at * RATE)
            end = int(t * RATE)
            for i in range(start, end, 2400):
                tracker.feed(audio[i:min(i + 2400, end)], min(i + 2400, end) / RATE)
            play_until.at = t
        play_until.at = 0.0

        # voice 1 starts on the left; the engine announces a new voice 1.2 s into the turn
        play_until(1.5); clock[0] = 1.5
        out = service.intents([{"kind": "new_voice", "voice": 1, "t": 1.5, "age_ms": 0, "new": True}])
        assert service.seats.zone_for(1) == "L" and service.seats.source_of(1) == "direction"
        assert out["played"][0]["pattern"] == "seat_tap" and out["played"][0]["zones"] == "L"
        time.sleep(0.1)
        assert stole.received[-1][1] == "haptic" and stole.received[-1][2][1:3] == bytes([1, 1])   # zones L, seat_tap

        # voice 2 on the right
        play_until(5.2); clock[0] = 5.2
        out = service.intents([{"kind": "new_voice", "voice": 2, "t": 5.2, "age_ms": 0, "new": True}])
        assert service.seats.zone_for(2) == "R" and out["played"][0]["zones"] == "R"
        time.sleep(0.1)
        assert stole.received[-1][2][1:3] == bytes([2, 1])                                       # zones R, seat_tap

        # a person's choice wins: seat voice 2 in front by hand; direction keeps hearing it on the right
        service.assign_seat(2, "F", "screen")
        play_until(6.6); clock[0] = 6.6
        out = service.intents([{"kind": "speaker", "voice": 2, "t": 6.6, "age_ms": 0}])
        assert service.seats.zone_for(2) == "F"
        assert service.snapshot()["seats"]["sources"]["1"] == "direction"
    finally:
        service.close()


def test_mono_mode_changes_nothing(tmp_path):
    service = KandhaService(home=tmp_path, ticker=False)
    try:
        assert service.settings.audio_mode == "mono" and service.direction is None
        out = service.intents([{"kind": "new_voice", "voice": 1, "t": 1.0, "age_ms": 0, "new": True}])
        assert out["played"][0]["pattern"] == "new_voice" and service.audio_status()["running"] is False
    finally:
        service.close()


def test_recorded_mode_plays_a_synthetic_file_and_reports_simulated(tmp_path):
    from app.kandha.room_synth import write
    path = write(tmp_path / "room.wav", Room(ArrayGeometry.quad(), [Talker(90, 0.2, 1.5)], noise_db=-50))
    service = KandhaService(home=tmp_path / "home", ticker=False)
    try:
        service.update_settings({"audio_mode": "recorded", "recorded_file": str(path)})
        deadline = time.monotonic() + 6
        status = service.audio_status()
        while time.monotonic() < deadline and status.get("bearing") is None:
            time.sleep(0.1)
            status = service.audio_status()
        assert status["simulated"] is True and status["channels"] == 4 and status["error"] is None
        assert status["bearing"] is not None and angle_to_zone(status["bearing"]) == "R"
        service.update_settings({"audio_mode": "mono"})
        assert service.direction is None
    finally:
        service.close()


def test_bad_audio_settings_are_refused(tmp_path):
    service = KandhaService(home=tmp_path, ticker=False)
    try:
        with pytest.raises(ValueError):
            service.update_settings({"audio_mode": "eight-channel"})
        with pytest.raises(ValueError):
            service.update_settings({"stereo_spacing_m": 3})
        service.update_settings({"audio_mode": "recorded", "recorded_file": str(tmp_path / "missing.wav")})
        assert "recorded WAV" in service.audio_status()["error"]
    finally:
        service.close()
