"""Kandha Stole protocol v1: every characteristic encodes and decodes, little-endian, bounded."""
import pytest

from app.kandha.patterns import Step, table
from app.kandha.protocol import (FLAG_LOW_BATTERY, FLAG_MIRRORED, GESTURE_DOUBLE, GESTURE_LONG, GESTURE_TAP, PAD_B, PAD_L,
                                 PAD_Q, PAD_R, HapticCommand, PadInput, StoleConfig, StoleStatus, apply_config, decode_pattern_upload,
                                 encode_pattern_upload, mirror_mask, name_prefix, uuids)


def test_uuids_come_from_the_table_and_never_reuse_the_band():
    ids = uuids()
    assert ids["service"] == "2ad2fdad-b9e2-4025-af4d-b35e6f13c100"
    assert set(ids) == {"service", "haptic", "patterns", "input", "status", "config"}
    assert len(set(ids.values())) == 6 and all(len(u) == 36 for u in ids.values())
    assert not any(u.startswith("a7c2f3e0") for u in ids.values())
    assert name_prefix() == "KandhaStole-"


def test_haptic_command_is_five_bytes_in_order():
    command = HapticCommand(seq=7, zones=3, pattern=1, intensity=230, repeat=2)
    assert command.encode() == bytes([7, 3, 1, 230, 2])
    assert HapticCommand.decode(bytes([7, 3, 1, 230, 2])) == command
    assert command.zone_letters == "LR"
    with pytest.raises(ValueError):
        HapticCommand(256, 1, 1, 1, 1)
    with pytest.raises(ValueError):
        HapticCommand(1, 16, 1, 1, 1)
    with pytest.raises(ValueError):
        HapticCommand.decode(b"\x01\x02")


def test_pattern_upload_is_little_endian_with_reserved_ids():
    steps = [Step(300, 1, 200), Step(0x1234, 0xABCD, 7)]
    payload = encode_pattern_upload(40, steps)
    assert payload[:2] == bytes([40, 2])
    assert payload[2:7] == bytes([0x2C, 0x01, 0x01, 0x00, 200])
    assert payload[7:12] == bytes([0x34, 0x12, 0xCD, 0xAB, 7])
    assert decode_pattern_upload(payload) == (40, steps)
    with pytest.raises(ValueError):
        encode_pattern_upload(31, steps)
    with pytest.raises(ValueError):
        encode_pattern_upload(40, [])
    with pytest.raises(ValueError):
        encode_pattern_upload(40, [Step(1, 1, 1)] * 17)
    with pytest.raises(ValueError):
        decode_pattern_upload(bytes([3, 1, 0, 0, 0, 0, 0]))
    with pytest.raises(ValueError):
        decode_pattern_upload(bytes([40, 2, 0, 0, 0, 0, 0]))


def test_input_decodes_pads_and_gestures_and_rejects_strangers():
    assert PadInput.decode(bytes([PAD_Q, GESTURE_TAP])) == PadInput(4, 1)
    assert PadInput.decode(bytes([PAD_L, GESTURE_DOUBLE])).pad_name == "L"
    assert PadInput.decode(bytes([PAD_B, GESTURE_LONG])).gesture_name == "long"
    assert PadInput(PAD_R, GESTURE_TAP).encode() == bytes([2, 1])
    for bad in (bytes([5, 1]), bytes([1, 4]), bytes([1]), bytes([0, 1])):
        with pytest.raises(ValueError):
            PadInput.decode(bad)


def test_status_reports_battery_firmware_and_flags():
    status = StoleStatus.decode(bytes([18, 0, 1, 2, FLAG_LOW_BATTERY | FLAG_MIRRORED]))
    assert status.battery == 18 and not status.charging and status.fw_major == 1 and status.fw_minor == 2
    assert status.low and status.as_dict()["mirrored"] and status.as_dict()["firmware"] == "1.2"
    assert StoleStatus.decode(bytes([250, 1, 1, 0, 0])).battery == 100
    assert StoleStatus(20, False, 1, 0).low, "20% is low by the table's threshold"
    assert not StoleStatus(21, False, 1, 0).low
    assert StoleStatus(55, True, 1, 3, 0).encode() == bytes([55, 1, 1, 3, 0])
    with pytest.raises(ValueError):
        StoleStatus.decode(b"\x01")


def test_config_round_trips_and_maps_percent_intensities_to_scales():
    config = StoleConfig(255, 128, 64, 0, mute=False, mirror=True, test_mode=False)
    assert config.encode() == bytes([255, 128, 64, 0, 0, 1, 0])
    assert StoleConfig.decode(config.encode()) == config
    from_settings = StoleConfig.from_settings({"L": 100, "R": 50, "B": 25, "F": 0}, mirror=True)
    assert from_settings.scales == {"L": 255, "R": 128, "B": 64, "F": 0} and from_settings.mirror
    assert StoleConfig.from_settings({}).scales == {"L": 255, "R": 255, "B": 255, "F": 255}
    with pytest.raises(ValueError):
        StoleConfig.decode(b"\x00" * 6)


def test_mirror_swaps_shoulders_and_mute_silences():
    assert mirror_mask(1) == 2 and mirror_mask(2) == 1 and mirror_mask(3) == 3 and mirror_mask(12) == 12 and mirror_mask(9) == 10
    command = HapticCommand(1, 1, 1, 200)
    assert apply_config(command, StoleConfig(mirror=True)).zones == 2
    assert apply_config(command, StoleConfig(mute=True)).intensity == 0
    assert apply_config(command, StoleConfig()) == command


def test_every_builtin_pattern_fits_the_protocol():
    for pattern in table().patterns:
        assert 0 <= pattern.id <= 31 and len(pattern.steps) <= 16
        for step in pattern.steps:
            assert 0 <= step.on_ms <= 65535 and 0 <= step.off_ms <= 65535 and 0 <= step.level <= 255
