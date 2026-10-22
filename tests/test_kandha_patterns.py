"""The shared Kandha pattern table: one source for the app, the virtual stole, the tests and the firmware."""
import json
import subprocess
import sys

import pytest

from app.kandha.patterns import PatternPlayer, PatternTable, effective_level, mask_zones, table, table_path, zone_mask
from app.kandha.protocol import HapticCommand, StoleConfig
from app.utils.paths import project_root


def test_table_loads_with_unique_ids_and_the_documented_tap_language():
    t = table()
    keys = {p.key for p in t.patterns}
    assert {"seat_tap", "new_voice", "drop", "rise", "hesitation", "silence", "queue_ack", "queue_reminder", "low_battery", "seat_unmapped", "zone_test", "stop"} <= keys
    assert t.by_key["seat_tap"].duration_ms == 120
    assert t.by_key["new_voice"].zones == "F" and len(t.by_key["new_voice"].steps) == 2
    assert t.by_key["drop"].duration_ms == 700
    assert [s.on_ms for s in t.by_key["rise"].steps] == [80, 80, 80]
    assert len(t.by_key["hesitation"].steps) == 5 and all(s.on_ms == 40 for s in t.by_key["hesitation"].steps)
    assert t.by_key["silence"].zones == "LR" and t.by_key["queue_ack"].zones == "LR" and t.by_key["low_battery"].zones == "B"
    assert len(t.by_key["low_battery"].steps) == 3
    assert all(0 <= p.id <= 31 for p in t.patterns), "built-ins stay in the reserved range"
    assert t.scheduler["stale_after_s"] == 1.5 and t.scheduler["cue_gap_s"] == 3 and t.scheduler["cue_same_kind_gap_s"] == 8
    assert t.mode("lecture")["seat_taps"] is False and t.mode("practicum")["cues"] is True and t.mode("dnd")["silence"] is False
    assert t.protocol["service_uuid"] != "a7c2f3e0-5b1d-4c8e-9f3a-53414e4b0001", "never the retired band's service"
    assert not t.protocol["service_uuid"].startswith("a7c2f3e0")


def test_quiet_by_default_the_whole_vocabulary_is_short():
    t = table()
    longest = max(p.duration_ms for p in t.patterns)
    assert longest <= 1500, "no pattern buzzes for longer than 1.5 s"
    assert all(p.duration_ms <= 700 for p in t.patterns if p.priority == "cue"), "a tone cue is at most one slow swell long"


@pytest.mark.parametrize("bad", [
    {"version": 2},
    {"patterns": [{"id": 40, "key": "x", "name": "", "meaning": "", "zones": "F", "priority": "cue", "intensity": 1, "repeat": 1, "steps": []}]},
    {"patterns": [{"id": 1, "key": "a", "name": "", "meaning": "", "zones": "F", "priority": "cue", "intensity": 1, "repeat": 1, "steps": []},
                  {"id": 1, "key": "b", "name": "", "meaning": "", "zones": "F", "priority": "cue", "intensity": 1, "repeat": 1, "steps": []}]},
    {"patterns": [{"id": 1, "key": "a", "name": "", "meaning": "", "zones": "F", "priority": "loud", "intensity": 1, "repeat": 1, "steps": []}]},
    {"tutorial_order": ["nope"]},
])
def test_malformed_tables_are_rejected(bad):
    data = json.loads(table_path().read_text())
    data.update(bad)
    with pytest.raises(ValueError):
        PatternTable(data)


def test_zone_masks_round_trip_and_reject_unknown_letters():
    assert zone_mask("LR") == 3 and zone_mask("F") == 8 and zone_mask("B") == 4
    assert mask_zones(15) == ["L", "R", "B", "F"] and mask_zones(10) == ["R", "F"]
    with pytest.raises(ValueError):
        zone_mask("X")
    assert effective_level(255, 255) == 255 and effective_level(255, 128, 128) == 64


def test_player_plays_steps_on_every_selected_zone_and_a_new_command_replaces_the_old():
    t = table()
    player = PatternPlayer(t)
    drop = t.by_key["drop"]
    player.start(HapticCommand(1, zone_mask("F"), drop.id, drop.intensity), 1000)
    assert player.busy_until() == 1700
    assert player.levels(1050)["F"] == effective_level(70, drop.intensity) and player.levels(1050)["L"] == 0
    # a speaker tap on the left shoulder pre-empts the swell
    tap = t.by_key["seat_tap"]
    player.start(HapticCommand(2, zone_mask("L"), tap.id, tap.intensity), 1200)
    assert player.levels(1250)["F"] == 0 and player.levels(1250)["L"] == effective_level(255, tap.intensity)
    assert player.busy_until() == 1320
    timeline = player.timeline()
    assert timeline[0] == ("F", 1000, 1100, effective_level(70, drop.intensity))
    assert timeline[1][2] == 1200, "the interrupted step ends when the new command arrived"
    assert timeline[-1] == ("L", 1200, 1320, effective_level(255, tap.intensity))
    assert player.levels(1400) == {"L": 0, "R": 0, "B": 0, "F": 0}


def test_player_honours_repeat_mute_mirror_and_per_zone_scales():
    t = table()
    tap = t.by_key["seat_tap"]
    player = PatternPlayer(t, StoleConfig(scale_l=128, mirror=True))
    player.start(HapticCommand(1, zone_mask("R"), tap.id, 255, repeat=2), 0)
    assert player.busy_until() == 240
    assert player.levels(10) == {"L": 128, "R": 0, "B": 0, "F": 0}, "mirror moves R to L and L's scale applies"
    muted = PatternPlayer(t, StoleConfig(mute=True))
    muted.start(HapticCommand(2, zone_mask("F"), tap.id, 255), 0)
    assert muted.levels(10)["F"] == 0
    stop = PatternPlayer(t)
    stop.start(HapticCommand(3, zone_mask("F"), tap.id, 255), 0)
    stop.start(HapticCommand(4, 0, 0, 0), 50)
    assert stop.busy_until() is None and stop.timeline()[0][2] == 50


def test_firmware_header_is_generated_from_the_table_and_up_to_date():
    result = subprocess.run([sys.executable, str(project_root() / "scripts/generate_kandha_patterns.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    header = (project_root() / "firmware/kandha/patterns.h").read_text()
    t = table()
    assert f'#define KANDHA_SERVICE_UUID "{t.protocol["service_uuid"]}"' in header
    for p in t.patterns:
        assert f'"{p.key}"' in header
    assert f"#define KANDHA_PATTERN_COUNT {len(t.patterns)}" in header
    assert "{120, 0, 255}" in header  # the seat tap's single step
