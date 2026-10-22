"""VirtualStole parity: the same HAPTIC bytes produce the same zone timeline as the mock (firmware-parity) stole."""
from app.kandha.bridge import MockStole
from app.kandha.patterns import effective_level, table, zone_mask
from app.kandha.protocol import GESTURE_DOUBLE, PAD_Q, HapticCommand, PadInput, StoleConfig, uuids
from app.kandha.scheduler import HapticScheduler, Intent, SchedulerSettings
from app.kandha.virtual import VirtualStole


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_virtual_and_mock_stoles_play_identical_timelines_for_a_scheduler_session():
    clock = Clock()
    events = []
    virtual = VirtualStole(clock=clock, on_event=lambda k, d: events.append((k, d)))
    mock = MockStole(clock=clock)
    scheduler = HapticScheduler(lambda v: {1: "L", 2: "R"}.get(v), SchedulerSettings(mode="practicum"))
    script = [(0.0, Intent("speaker", created=100.0, voice=1)), (0.05, Intent("cue", created=100.05, cue="rise")),
              (0.5, Intent("speaker", created=100.5, voice=2)), (0.55, Intent("cue", created=100.55, cue="drop")),
              (0.6, Intent("speaker", created=100.6, voice=1)), (4.0, Intent("silence", created=104.0)),
              (5.0, Intent("queue_ack", created=105.0)), (9.0, Intent("cue", created=109.0, cue="hesitation"))]
    for offset, intent in script:
        clock.t = 100.0 + offset
        for played in scheduler.submit(intent, clock.t) + scheduler.tick(clock.t):
            data = played.command.encode()
            virtual.write_haptic(data)
            mock.write(uuids()["haptic"], data)
        clock.t += 0.2
        for played in scheduler.tick(clock.t):
            data = played.command.encode()
            virtual.write_haptic(data)
            mock.write(uuids()["haptic"], data)
    assert virtual.timeline() == mock.timeline() if hasattr(mock, "timeline") else virtual.timeline() == mock.player.timeline()
    assert virtual.timeline() == mock.player.timeline()
    zones = [z for z, *_ in virtual.timeline()]
    assert zones[0] == "L" and "R" in zones and {"L", "R"} <= set(zones)
    kinds = [d["pattern"] for k, d in events if k == "haptic" and "pattern" in d]
    assert kinds[0] == "seat_tap" and "silence" in kinds and "queue_ack" in kinds
    assert all(0 < d["duration_ms"] <= 1500 for k, d in events if k == "haptic" and "pattern" in d)


def test_virtual_stole_applies_config_like_the_firmware_and_reports_status():
    clock = Clock()
    virtual = VirtualStole(clock=clock)
    tap = table().by_key["seat_tap"]
    config = StoleConfig.from_settings({"L": 100, "R": 40, "B": 100, "F": 100}, mirror=True)
    virtual.write_config(config.encode())
    assert virtual.status().as_dict()["mirrored"]
    played = virtual.write_haptic(HapticCommand(1, zone_mask("L"), tap.id, tap.intensity).encode())
    assert played["zones"] == "R", "mirror moves the left tap to the right shoulder"
    assert virtual.levels()["R"] == effective_level(255, tap.intensity, config.scale_r) and virtual.levels()["L"] == 0
    assert virtual.status().as_dict()["playing"]
    clock.t += 0.2
    assert not virtual.status().as_dict()["playing"] and virtual.levels() == {"L": 0, "R": 0, "B": 0, "F": 0}
    virtual.write_config(StoleConfig(mute=True).encode())
    assert virtual.write_haptic(HapticCommand(2, zone_mask("F"), tap.id, tap.intensity).encode())["intensity"] == 0
    assert virtual.status().as_dict()["muted"] and virtual.snapshot()["device"] == "virtual"


def test_duplicate_sequence_numbers_stop_and_custom_patterns_behave_like_the_real_stole():
    clock = Clock()
    virtual, mock = VirtualStole(clock=clock), MockStole(clock=clock)
    tap = table().by_key["seat_tap"]
    first = HapticCommand(9, zone_mask("B"), tap.id, 200).encode()
    for device_write in (virtual.write_haptic, lambda d: mock.write(uuids()["haptic"], d)):
        device_write(first)
    clock.t += 0.05
    assert virtual.write_haptic(first) is None, "the same seq again is a duplicate delivery"
    mock.write(uuids()["haptic"], first)
    assert virtual.timeline() == mock.player.timeline() == [("B", 100000, 100120, effective_level(255, 200))]
    clock.t += 0.01
    assert virtual.write_haptic(HapticCommand(10, 0, 0, 0).encode()) is None
    mock.write(uuids()["haptic"], HapticCommand(10, 0, 0, 0).encode())
    assert virtual.timeline()[0][2] == 100060 == mock.player.timeline()[0][2]
    from app.kandha.patterns import Step
    from app.kandha.protocol import encode_pattern_upload
    upload = encode_pattern_upload(40, [Step(30, 20, 255), Step(30, 0, 100)])
    virtual.write_patterns(upload)
    mock.write(uuids()["patterns"], upload)
    clock.t += 0.1
    virtual.write_haptic(HapticCommand(11, zone_mask("F"), 40, 255).encode())
    mock.write(uuids()["haptic"], HapticCommand(11, zone_mask("F"), 40, 255).encode())
    assert virtual.timeline() == mock.player.timeline() and virtual.timeline()[-1] == ("F", 100210, 100240, 100)


def test_screen_pads_produce_the_real_input_bytes():
    events = []
    virtual = VirtualStole(on_event=lambda k, d: events.append((k, d)))
    assert virtual.press(PAD_Q, GESTURE_DOUBLE) == PadInput(PAD_Q, GESTURE_DOUBLE).encode() == bytes([4, 2])
    assert events[-1] == ("input", {"device": "virtual", "raw": "0402", "pad": "Q", "gesture": "double"})
