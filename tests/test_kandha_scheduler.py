"""HapticScheduler rules: priority, stale drop, rate limits, pre-emption, modes, unmapped voices, queue timing."""
import pytest

from app.kandha.scheduler import HapticScheduler, Intent, QueueTracker, SchedulerSettings


def seats(voice):
    return {1: "L", 2: "R", 3: "B", 4: "F"}.get(voice)


def make(mode="practicum", **kw):
    settings = SchedulerSettings(mode=mode, **kw)
    return HapticScheduler(seats, settings)


def played(scheduler, intent, now):
    out = scheduler.submit(intent, now)
    return out[0].as_dict() if out else None


def test_speaker_change_taps_the_seat_zone_once_and_not_the_same_voice_twice():
    s = make()
    tap = played(s, Intent("speaker", created=0.0, voice=2, t=5.0), 0.0)
    assert tap["zones"] == "R" and tap["pattern"] == "seat_tap" and tap["duration_ms"] == 120 and tap["voice"] == 2
    assert played(s, Intent("speaker", created=1.0, voice=2), 1.0) is None, "same voice again: no tap"
    assert s.dropped[-1][1] == "same-voice"
    assert played(s, Intent("speaker", created=2.0, voice=1), 2.0)["zones"] == "L"
    assert played(s, Intent("speaker", created=3.0, voice=3), 3.0)["zones"] == "B"
    assert played(s, Intent("speaker", created=4.0, voice=4), 4.0)["zones"] == "F"


def test_unmapped_voice_gets_one_front_tap_and_new_voice_gets_the_double_tap():
    s = make()
    unmapped = played(s, Intent("speaker", created=0.0, voice=9), 0.0)
    assert unmapped["zones"] == "F" and unmapped["pattern"] == "seat_unmapped"
    new = played(s, Intent("new_voice", created=1.0, voice=10, new=True), 1.0)
    assert new["zones"] == "F" and new["pattern"] == "new_voice" and new["duration_ms"] == 210


def test_stale_intents_are_dropped_instead_of_played_late():
    s = make()
    assert played(s, Intent("speaker", created=0.0, voice=1), 1.6) is None
    assert s.dropped[-1] [1] == "stale"
    assert played(s, Intent("speaker", created=0.0, voice=1), 1.4) is not None
    # a cue that waited behind a tap for too long is dropped at release time
    s2 = make()
    s2.submit(Intent("speaker", created=10.0, voice=2), 10.0)
    assert s2.submit(Intent("cue", created=8.7, cue="rise"), 10.05) == [] and s2.pending is not None
    assert s2.tick(10.3) == [] and s2.dropped[-1][1] == "stale"
    # low battery is never stale
    assert played(s2, Intent("low_battery", created=0.0), 100.0)["zones"] == "B"


def test_tone_cues_obey_the_three_second_gap_and_eight_second_same_kind_gap():
    s = make()
    assert played(s, Intent("cue", created=0.0, cue="rise"), 0.0)["pattern"] == "rise"
    assert played(s, Intent("cue", created=2.0, cue="drop"), 2.0) is None and s.dropped[-1][1] == "cue-gap"
    assert played(s, Intent("cue", created=3.1, cue="drop"), 3.1)["pattern"] == "drop"
    assert played(s, Intent("cue", created=7.0, cue="rise"), 7.0) is None and s.dropped[-1][1] == "same-cue-gap"
    assert played(s, Intent("cue", created=8.1, cue="rise"), 8.1)["pattern"] == "rise"
    assert played(s, Intent("cue", created=11.2, cue="hesitation"), 11.2)["pattern"] == "hesitation"


def test_speaker_tap_preempts_a_cue_and_a_cue_waits_for_a_tap():
    s = make()
    swell = played(s, Intent("cue", created=0.0, cue="drop"), 0.0)
    assert swell["duration_ms"] == 700
    tap = played(s, Intent("speaker", created=0.2, voice=1), 0.2)
    assert tap is not None and s.history[0].preempted and tap["seq"] == swell["seq"] + 1
    # a cue arriving during the 120 ms tap waits, then plays when the tap ends
    s2 = make()
    s2.submit(Intent("speaker", created=5.0, voice=2), 5.0)
    assert s2.submit(Intent("cue", created=5.02, cue="rise"), 5.02) == []
    assert s2.tick(5.1) == [], "still tapping"
    released = s2.tick(5.13)
    assert released and released[0].pattern_key == "rise" and released[0].deferred
    # silence never waits: it is dropped when the stole is busy
    s2.submit(Intent("speaker", created=6.0, voice=3), 6.0)
    assert s2.submit(Intent("silence", created=6.01), 6.01) == [] and s2.dropped[-1][1] == "busy"


def test_priority_order_speaker_over_queue_over_cue_over_silence():
    s = make()
    s.submit(Intent("silence", created=0.0), 0.0)                                   # 360 ms
    assert played(s, Intent("cue", created=0.05, cue="rise"), 0.05) is not None, "a cue pre-empts silence"
    assert played(s, Intent("queue_ack", created=0.1), 0.1) is not None, "queue feedback pre-empts a cue"
    assert played(s, Intent("speaker", created=0.15, voice=1), 0.15) is not None, "a speaker tap pre-empts queue feedback"
    # equal priority waits; the best waiting intent wins and the loser is dropped
    s.submit(Intent("queue_reminder", created=0.2), 0.2)
    s.submit(Intent("queue_ack", created=0.21), 0.21)
    assert s.pending.kind == "queue_ack" and s.dropped[-1][1] == "superseded"


@pytest.mark.parametrize("mode,dnd,expect", [
    ("lecture", False, {"speaker": False, "new_voice": False, "cue": False, "silence": True, "queue_ack": True}),
    ("seminar", False, {"speaker": True, "new_voice": True, "cue": False, "silence": True, "queue_ack": True}),
    ("practicum", False, {"speaker": True, "new_voice": True, "cue": True, "silence": True, "queue_ack": True}),
    ("practicum", True, {"speaker": False, "new_voice": False, "cue": False, "silence": False, "queue_ack": True}),
])
def test_modes_decide_which_intents_exist(mode, dnd, expect):
    s = make(mode, dnd=dnd)
    now = 0.0
    for kind, allowed in expect.items():
        now += 10
        intent = Intent(kind, created=now, voice=now and int(now), cue="rise" if kind == "cue" else None)
        assert (played(s, intent, now) is not None) == allowed, f"{mode} dnd={dnd} {kind}"


def test_seminar_cues_are_optional_and_each_cue_has_its_own_switch():
    s = make("seminar")
    assert played(s, Intent("cue", created=0.0, cue="rise"), 0.0) is None
    s.settings.seminar_cues = True
    assert played(s, Intent("cue", created=10.0, cue="rise"), 10.0) is not None
    s.settings.cues["drop"] = False
    assert played(s, Intent("cue", created=20.0, cue="drop"), 20.0) is None and s.dropped[-1][1] == "mode"
    s.settings.cues["silence"] = False
    assert played(s, Intent("silence", created=30.0), 30.0) is None


def test_after_a_silence_the_same_voice_may_be_tapped_again_and_resumes_tap_the_seat():
    s = make()
    assert played(s, Intent("speaker", created=0.0, voice=1), 0.0)["zones"] == "L"
    assert played(s, Intent("silence", created=5.0), 5.0)["pattern"] == "silence"
    assert played(s, Intent("speaker", created=9.0, voice=1), 9.0)["zones"] == "L", "a voice starting again after silence taps"
    assert played(s, Intent("voice_resumes", created=20.0, voice=1), 20.0)["zones"] == "L"


def test_test_intents_play_any_zone_and_pattern_and_stop_cancels():
    s = make("lecture", dnd=True)
    test = played(s, Intent("test", created=0.0, zone="B"), 0.0)
    assert test["zones"] == "B" and test["pattern"] == "zone_test"
    tutorial = played(s, Intent("test", created=0.0, pattern="rise"), 1.0)
    assert tutorial["zones"] == "F" and tutorial["pattern"] == "rise"
    squeeze = played(s, Intent("test", created=0.0, pattern="queue_ack"), 2.0)
    assert squeeze["zones"] == "LR"
    stop = played(s, Intent("stop", created=0.0), 2.1)
    assert stop["pattern"] == "stop" and stop["mask"] == 0 and s.current is None


def test_connected_and_low_battery_wait_for_a_free_stole_and_dnd_mutes_low_battery():
    s = make()
    s.submit(Intent("speaker", created=0.0, voice=1), 0.0)
    assert s.submit(Intent("connected", created=0.0), 0.01) == [] and s.pending.kind == "connected"
    assert s.tick(0.2)[0].pattern_key == "connected"
    assert played(s, Intent("low_battery", created=1.0), 1.0)["pattern"] == "low_battery"
    s.settings.dnd = True
    assert played(s, Intent("low_battery", created=2.0), 2.0) is None


def test_sequence_numbers_wrap_and_reset_session_forgets_timing_but_not_settings():
    s = make(mirror=True)
    s.seq = 254
    first = played(s, Intent("speaker", created=0.0, voice=1), 0.0)
    second = played(s, Intent("speaker", created=1.0, voice=2), 1.0)
    assert (first["seq"], second["seq"]) == (255, 0)
    s.reset_session()
    assert s.last_tapped_voice is None and s.history == [] and s.settings.mirror is True
    assert played(s, Intent("speaker", created=2.0, voice=2), 2.0) is not None


def test_queue_tracker_reminds_after_the_wait_and_at_most_once_a_minute():
    q = QueueTracker()
    assert q.reminder_s == 60
    assert q.set(True, 0.0) and not q.set(True, 0.0)
    assert not q.due(30.0) and q.due(60.0) and not q.due(90.0) and q.due(121.0)
    assert q.waited(121.0) == 121.0
    q.reminder_s = 20
    q.set(True, 200.0)
    assert q.due(220.0) and not q.due(239.0), "never more than once a minute even with a short reminder"
    assert q.due(281.0)
    q.set(False, 300.0)
    assert not q.due(400.0) and q.waited(400.0) == 0.0
    q.reminder_s = 0
    q.set(True, 500.0)
    assert not q.due(700.0), "0 disables reminders"
