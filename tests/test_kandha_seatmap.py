"""SeatMap: pad assignment window, reassignment, saved rooms, practicum default, SeatSource angles."""
import json

import pytest

from app.kandha.protocol import GESTURE_DOUBLE, GESTURE_LONG, GESTURE_TAP, PAD_B, PAD_L, PAD_Q, PAD_R
from app.kandha.seatmap import ManualSeatSource, SeatMap, angle_to_zone


@pytest.fixture
def seat_map(tmp_path):
    return SeatMap(store_path=tmp_path / "rooms.json")


def test_new_voice_opens_a_six_second_window_for_a_pad_tap(seat_map):
    assert seat_map.new_voice(1, now=10.0) is None
    assert seat_map.window_open(15.9) and not seat_map.window_open(16.1)
    assert seat_map.on_pad(PAD_L, GESTURE_TAP, 12.0) == {"action": "assign-new", "voice": 1, "zone": "L"}
    assert seat_map.zone_for(1) == "L" and not seat_map.window_open(12.5), "the window closes once used"
    seat_map.new_voice(2, now=20.0)
    assert seat_map.on_pad(PAD_R, GESTURE_TAP, 27.0) == {"action": "no-window", "voice": None, "zone": "R"}
    assert seat_map.zone_for(2) is None, "touching nothing in time leaves the voice unmapped"


def test_double_tap_reassigns_the_current_voice_and_long_press_clears_it(seat_map):
    seat_map.new_voice(1, 0.0)
    seat_map.on_pad(PAD_L, GESTURE_TAP, 1.0)
    assert seat_map.on_pad(PAD_B, GESTURE_DOUBLE, 30.0, current_voice=1) == {"action": "reassign-current", "voice": 1, "zone": "B"}
    assert seat_map.zone_for(1) == "B"
    assert seat_map.on_pad(PAD_R, GESTURE_DOUBLE, 31.0, current_voice=None)["action"] == "no-current"
    assert seat_map.on_pad(PAD_R, GESTURE_LONG, 32.0, current_voice=1) == {"action": "clear-current", "voice": 1, "zone": None}
    assert seat_map.zone_for(1) is None
    assert seat_map.on_pad(PAD_Q, GESTURE_TAP, 33.0, current_voice=1) is None, "the queue pad is not a seat"
    assert [c[:2] for c in seat_map.changes] == [(1, "L"), (1, "B"), (1, None)]


def test_screen_assignment_validates_and_merge_keeps_a_seat(seat_map):
    assert seat_map.assign(3, "F") and not seat_map.assign(3, "F")
    with pytest.raises(ValueError):
        seat_map.assign(3, "X")
    with pytest.raises(ValueError):
        seat_map.assign(0, "L")
    seat_map.assign(4, None)
    seat_map.merge(keep=4, drop=3)
    assert seat_map.zone_for(4) == "F" and 3 not in seat_map.voices() and seat_map.order == [4]


def test_practicum_defaults_the_partner_to_the_front(tmp_path):
    seat_map = SeatMap(store_path=tmp_path / "r.json", mode="practicum")
    assert seat_map.new_voice(1, 0.0) is None, "the first voice (often the wearer's own) stays unmapped"
    assert seat_map.new_voice(2, 5.0) == "F"
    assert seat_map.on_pad(PAD_L, GESTURE_TAP, 6.0)["zone"] == "L", "the default can still be changed"
    assert seat_map.zone_for(2) == "L"
    seminar = SeatMap(store_path=tmp_path / "s.json", mode="seminar")
    assert seminar.new_voice(2, 0.0) is None
    with pytest.raises(ValueError):
        seminar.set_mode("hallway")


def test_rooms_store_slot_order_not_people_and_preassign_the_next_session(tmp_path):
    first = SeatMap(store_path=tmp_path / "rooms.json")
    first.new_voice(1, 0.0); first.assign(1, "L")
    first.new_voice(2, 1.0); first.assign(2, "R")
    first.new_voice(3, 2.0)
    room = first.save_room("Seminar room 2.14")
    assert room["slots"] == ["L", "R"], "trailing unmapped voices are not stored"
    saved = json.loads((tmp_path / "rooms.json").read_text())
    assert saved["last_room"] == "Seminar room 2.14" and "voice" not in json.dumps(saved).lower().replace("version", "")
    second = SeatMap(store_path=tmp_path / "rooms.json")
    assert second.last_room == "Seminar room 2.14" and second.loaded_room is None
    second.load_room("Seminar room 2.14")
    assert second.new_voice(7, 0.0) == "L" and second.new_voice(9, 1.0) == "R" and second.new_voice(11, 2.0) is None
    assert second.changes[0] == (7, "L", "room")
    # loading a room mid-session assigns the voices already heard, in order of appearance
    third = SeatMap(store_path=tmp_path / "rooms.json")
    third.new_voice(5, 0.0); third.new_voice(6, 1.0)
    third.load_room("Seminar room 2.14")
    assert third.voices() == {5: "L", 6: "R"}
    assert third.delete_room("Seminar room 2.14") and not third.delete_room("Seminar room 2.14")
    assert third.last_room is None and third.loaded_room is None
    with pytest.raises(ValueError):
        third.load_room("missing")
    with pytest.raises(ValueError):
        third.save_room("   ")


def test_a_damaged_room_file_is_ignored_not_fatal(tmp_path):
    (tmp_path / "rooms.json").write_text("{not json")
    assert SeatMap(store_path=tmp_path / "rooms.json").list_rooms() == []
    (tmp_path / "rooms.json").write_text(json.dumps({"rooms": [{"name": "Lab", "slots": ["F", "Q", "L"]}, {"slots": []}], "last_room": "Lab"}))
    loaded = SeatMap(store_path=tmp_path / "rooms.json")
    assert loaded.list_rooms()[0]["slots"] == ["F", None, "L"] and loaded.last_room == "Lab"


def test_seat_source_angles_map_to_zones_for_a_future_microphone_array(seat_map):
    assert [angle_to_zone(a) for a in (0, 44, 45, 134, 135, 224, 225, 314, 315, -30, 450)] == ["F", "F", "R", "R", "B", "B", "L", "L", "F", "F", "R"]
    seat_map.assign(1, "L"); seat_map.assign(2, "F"); seat_map.assign(3, None)
    source = ManualSeatSource(seat_map)
    assert source.angles() == {1: 270.0, 2: 0.0}
    assert {v: angle_to_zone(a) for v, a in source.angles().items()} == {1: "L", 2: "F"}


def test_snapshot_describes_the_window_and_reset_keeps_the_room(seat_map):
    seat_map.new_voice(1, 0.0)
    snap = seat_map.snapshot(now=2.0)
    assert snap["pending"] == {"voice": 1, "until_s": 4.0} and snap["seats"] == {"1": None}
    seat_map.save_room("Lab")
    seat_map.reset()
    assert seat_map.voices() == {} and seat_map.loaded_room.name == "Lab"
    seat_map.reset(keep_room=False)
    assert seat_map.loaded_room is None


def test_the_wearers_own_voice_is_me_never_seated_and_never_saved(tmp_path):
    seat_map = SeatMap(store_path=tmp_path / "rooms.json")
    seat_map.new_voice(1, 0.0); seat_map.assign(1, "L")
    seat_map.new_voice(2, 1.0); seat_map.assign(2, "me")
    assert seat_map.zone_for(2) == "me" and seat_map.new_voice(2, 5.0) == "me"
    seat_map.assign(3, "me")
    assert seat_map.zone_for(2) is None, "only one voice can be the wearer"
    assert seat_map.save_room("Lab")["slots"] == ["L"], "me is never stored in a room"
    assert ManualSeatSource(seat_map).angles() == {1: 270.0}
