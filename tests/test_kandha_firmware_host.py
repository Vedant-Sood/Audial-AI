"""The Kandha Stole firmware, run on this computer.

Compiles the real firmware/kandha sources (pattern_engine.h, touch_pads.h and the whole kandha.ino
sketch) with the host C++ compiler against the Arduino and BLE stand-ins in tests/firmware_host,
then checks them against app/kandha/patterns.py PatternPlayer and docs/kandha/PROTOCOL.md.
Skipped when no C++ compiler is installed. The ESP32-S3 build itself is CI's job
(.github/workflows/firmware.yml).
"""
import os
import re
import shutil
import subprocess

import pytest

from app.kandha.patterns import Pattern, PatternPlayer, Step, table
from app.kandha.protocol import HapticCommand, StoleConfig
from app.utils.paths import project_root

ROOT = project_root()
HOST = ROOT / "tests" / "firmware_host"
FIRMWARE = ROOT / "firmware" / "kandha"
COMPILER = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
pytestmark = [
    pytest.mark.skipif(not COMPILER, reason="no C++ compiler to build the firmware on the host"),
    # Whatever g++ a Windows machine has on PATH may lack std::thread; Linux CI runs these.
    pytest.mark.skipif(os.name == "nt", reason="the firmware host build is checked on Linux and macOS"),
]


def _defines():
    text = (FIRMWARE / "config.h").read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^#define (\w+) (-?\d+)\b", text, re.M)}


CFG = _defines()
KICK_MS, MIN_DUTY = CFG["MOTOR_KICK_MS"], CFG["MOTOR_MIN_DUTY"]
POLL_MS, DEBOUNCE_MS = CFG["TOUCH_POLL_MS"], CFG["TOUCH_DEBOUNCE_MS"]
PIN_ZONE = {CFG["PIN_MOTOR_L"]: "L", CFG["PIN_MOTOR_R"]: "R", CFG["PIN_MOTOR_B"]: "B", CFG["PIN_MOTOR_F"]: "F"}
TAP, DOUBLE, LONG = 1, 2, 3


def _compile(out_dir, source, name, *extra):
    exe = out_dir / name
    cmd = [COMPILER, "-std=c++17", "-O1", "-Wall", f"-I{HOST}", f"-I{FIRMWARE}", str(HOST / source), "-o", str(exe), *extra]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, f"{source} does not compile on the host:\n{done.stderr}"
    return exe


@pytest.fixture(scope="module")
def engine_exe(tmp_path_factory):
    return _compile(tmp_path_factory.mktemp("fw_engine"), "engine_harness.cpp", "engine_harness")


@pytest.fixture(scope="module")
def sketch_exe(tmp_path_factory):
    return _compile(tmp_path_factory.mktemp("fw_sketch"), "sketch_harness.cpp", "sketch_harness", "-pthread")


def _run(exe, lines, env=None, check=True):
    done = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120, env=env)
    if check:
        assert done.returncode == 0, done.stderr
    return done


def _out(exe, lines):
    return _run(exe, lines).stdout.splitlines()


# ---------------------------------------------------------------------------- pattern engine
def _pwm(lines):
    """(ms, zone, duty) for every motor write."""
    out = []
    for line in lines:
        parts = line.split()
        if parts[0] == "PWM" and int(parts[2]) in PIN_ZONE:
            out.append((int(parts[1]), PIN_ZONE[int(parts[2])], int(parts[3])))
    return out


def _fw_level(writes, zone, t):
    level = 0
    for ms, z, duty in writes:
        if ms > t:
            break
        if z == zone:
            level = duty
    return level


def _floor(level):
    return 0 if level == 0 else max(level, MIN_DUTY)


def _expectation(player):
    """What each motor should get at ms t: PatternPlayer's level with the MOTOR_MIN_DUTY floor, and
    full duty for the first MOTOR_KICK_MS after the motor starts from rest. A step or command that
    takes over a motor still in its kick keeps the kick going."""
    runs = {z: [] for z in "LRBF"}                 # when each motor runs without a rest
    for z, start, end, level in sorted(player.timeline(), key=lambda seg: seg[1]):
        if not _floor(level) or end <= start:
            continue
        if runs[z] and runs[z][-1][1] >= start:
            runs[z][-1][1] = max(runs[z][-1][1], end)
        else:
            runs[z].append([start, end])
    kicks = [(z, a, min(b, a + KICK_MS)) for z in runs for a, b in runs[z]]

    def expected(zone, t):
        if any(z == zone and a <= t < b for z, a, b in kicks):
            return 255
        return _floor(player.levels(t)[zone])
    return expected


class Scenario:
    """The same commands for the C++ engine (as a harness script) and for PatternPlayer."""

    def __init__(self, ticks=None):
        self.script = ["reset"] + ([f"ticks {' '.join(map(str, ticks))}", "trace"] if ticks else [])
        self.config = StoleConfig()
        self.player = PatternPlayer(table(), self.config)
        self.custom = {}
        self.last_seq = None
        self.end = 0

    def cfg(self, scales=(255, 255, 255, 255), mute=False, mirror=False):
        self.config = StoleConfig(*scales, mute, mirror)
        self.player.config = self.config
        self.script.append(f"cfg {' '.join(map(str, scales))} {int(mute)} {int(mirror)}")

    def store(self, pid, steps):
        self.custom[pid] = Pattern(pid, f"custom{pid}", "", "", "any", "system", 255, 1, tuple(Step(*s) for s in steps))
        self.script.append(f"store {pid} {len(steps)} " + " ".join(f"{a} {b} {c}" for a, b, c in steps))

    def play(self, t, seq, zones, pattern, intensity, repeat=1):
        self.script.append(f"play {t} {seq} {zones} {pattern} {intensity} {repeat}")
        if seq != self.last_seq:
            self.last_seq = seq
            pat = table().by_id.get(pattern) or self.custom.get(pattern)
            self.player.start(HapticCommand(seq, zones, pattern, intensity, repeat), t, pattern=pat)
        end = self.player.busy_until() or t
        self.end = max(self.end, end + 20)

    def run(self, engine_exe):
        self.script.append(f"run {self.end}")
        lines = _out(engine_exe, self.script)
        return lines, _pwm(lines)


def _assert_matches(scenario, lines, writes, start):
    ticks = [int(line.split()[1]) for line in lines if line.startswith("TICK ")]
    times = [t for t in ticks if t >= start] if ticks else range(start, scenario.end)
    expected = _expectation(scenario.player)
    for zone in "LRBF":
        bad = [(t, _fw_level(writes, zone, t), expected(zone, t)) for t in times
               if _fw_level(writes, zone, t) != expected(zone, t)]
        assert not bad, f"zone {zone}: (ms, firmware, expected) {bad[:8]}"


@pytest.mark.parametrize("repeat", [1, 2])
@pytest.mark.parametrize("key", [p.key for p in table().patterns if p.steps and p.id])
def test_every_builtin_pattern_plays_like_the_python_player(engine_exe, key, repeat):
    p = table().by_key[key]
    s = Scenario()
    s.play(1000, 1, p.fixed_mask or 1, p.id, p.intensity, repeat)
    lines, writes = s.run(engine_exe)
    _assert_matches(s, lines, writes, 900)
    assert writes and writes[-1][2] == 0, "every motor ends at rest"


def test_config_low_levels_preemption_and_stop_match_the_python_player(engine_exe):
    s = Scenario()
    s.cfg(scales=(128, 200, 90, 255), mirror=True)
    s.play(1000, 1, 1 | 8, 6, 150)            # silence on L+F, mirrored to R+F, scaled per zone
    s.cfg()
    s.play(2000, 2, 8, 5, 60)                 # hesitation at 60: 28 before the 60 floor
    s.play(3000, 3, 8, 3, 200)                # drop on F ...
    s.play(3250, 4, 2, 1, 230)                # ... replaced by a seat tap on R
    s.play(4000, 5, 8, 3, 200)                # drop on F ...
    s.play(4150, 6, 8, 2, 230)                # ... replaced on the same, spinning motor: no kick
    s.play(5000, 7, 15, 11, 0)                # intensity 0 plays nothing
    s.play(6000, 8, 3, 7, 210)
    s.play(6100, 9, 3, 0, 0)                  # pattern 0 stops
    s.play(7000, 10, 3, 7, 210)
    s.play(7050, 11, 3, 20, 210)              # an unknown pattern stops what plays
    s.cfg(mute=True)
    s.play(8000, 12, 8, 1, 230)               # muted: silent
    lines, writes = s.run(engine_exe)
    _assert_matches(s, lines, writes, 900)


def test_the_spin_up_kick_lasts_motor_kick_ms_and_only_from_rest(engine_exe):
    s = Scenario()
    s.play(1000, 1, 1, 1, 230)                # seat_tap on L
    s.play(2000, 2, 8, 2, 230)                # new_voice: two taps, each from rest
    s.play(3000, 3, 8, 3, 200)                # drop: steps follow without a rest, one kick
    lines, writes = s.run(engine_exe)
    left = [w for w in writes if w[1] == "L"]
    assert left[-3:] == [(1000, "L", 255), (1000 + KICK_MS, "L", 230), (1120, "L", 0)]
    front = [(t, d) for t, z, d in writes if z == "F" and 2000 <= t < 2300]
    assert front == [(2000, 255), (2000 + KICK_MS, 230), (2060, 0), (2150, 255), (2150 + KICK_MS, 230), (2210, 0)]
    drop = [(t, d) for t, z, d in writes if z == "F" and 3000 <= t < 3700]
    assert drop[:2] == [(3000, 255), (3000 + KICK_MS, MIN_DUTY)], "one kick, onto the floored first step"
    assert 255 not in [d for _, d in drop[1:]], "the next steps start from a spinning motor: no kick"
    _assert_matches(s, lines, writes, 900)


def test_a_command_that_takes_over_a_kicking_motor_keeps_the_kick(engine_exe):
    s = Scenario()
    s.play(1000, 1, 1, 1, 230)                # seat_tap on L ...
    s.play(1000, 2, 1, 1, 230)                # ... and another in the same loop() pass
    s.play(2000, 3, 8, 2, 230)                # new_voice on F ...
    s.play(2005, 4, 8, 2, 230)                # ... replaced 5 ms into its kick
    s.play(3000, 5, 2, 7, 210)                # queue_ack on R ...
    s.play(3050, 6, 2, 1, 230)                # ... replaced after its kick: the motor spins, no kick
    s.play(4000, 7, 4, 7, 210)                # queue_ack on B ...
    s.play(4100, 8, 1, 1, 230)                # ... a command for L switches B off ...
    s.play(4100, 9, 4, 1, 230)                # ... and the next, in the same pass, B on: B never rested
    lines, writes = s.run(engine_exe)
    left = [(t, d) for t, z, d in writes if z == "L" and 900 <= t < 2000]
    assert left == [(1000, 255), (1000 + KICK_MS, 230), (1120, 0)]
    front = [(t, d) for t, z, d in writes if z == "F" and 2000 <= t < 2300]
    assert front == [(2000, 255), (2000 + KICK_MS, 230), (2065, 0), (2155, 255), (2155 + KICK_MS, 230), (2215, 0)]
    right = [(t, d) for t, z, d in writes if z == "R" and 3000 <= t < 3300]
    assert right == [(3000, 255), (3000 + KICK_MS, 181), (3050, 230), (3170, 0)]
    back = [(t, d) for t, z, d in writes if z == "B" and 4000 <= t < 4300]
    assert back == [(4000, 255), (4000 + KICK_MS, 181), (4100, 0), (4100, 230), (4220, 0)]
    _assert_matches(s, lines, writes, 900)


def test_a_step_without_on_time_only_rests_like_the_python_player(engine_exe):
    s = Scenario()
    s.store(40, [(30, 20, 255), (0, 50, 200), (30, 0, 40)])
    s.store(41, [(0, 0, 255)])
    s.store(42, [(10, 0, 100), (0, 0, 255), (30, 0, 100), (0, 25, 0), (5, 0, 180)])
    s.play(9000, 10, 4, 40, 255, 2)
    s.play(10000, 11, 4, 41, 255, 3)
    s.play(11000, 12, 1, 42, 255, 2)
    lines, writes = s.run(engine_exe)
    back = [(t, d) for t, z, d in writes if z == "B" and 9000 <= t < 10000]
    assert back == [(9000, 255), (9030, 0), (9100, 255), (9100 + KICK_MS, 60), (9130, 255), (9160, 0),
                    (9230, 255), (9230 + KICK_MS, 60), (9260, 0)], "no blip at 9050 and no drift"
    assert not [w for w in writes if 10000 <= w[0] < 11000], "a pattern of empty steps writes nothing"
    _assert_matches(s, lines, writes, 8900)


def test_late_ticks_do_not_push_the_pattern_back(engine_exe):
    s = Scenario(ticks=[1, 3, 7, 2, 5])
    s.play(1000, 1, 8, 3, 200)                # drop: seven back-to-back steps
    s.play(2000, 2, 3, 6, 150, 3)             # silence x3: rests between taps
    s.play(4000, 3, 4, 9, 170)                # low_battery
    lines, writes = s.run(engine_exe)
    assert sum(line.startswith("TICK ") for line in lines) > 100
    _assert_matches(s, lines, writes, 900)


def test_a_repeated_seq_is_ignored_until_the_filter_is_reset(engine_exe):
    lines = _out(engine_exe, ["reset", "play 1000 5 1 1 230 1", "play 1500 5 1 1 230 1",
                              "resetseq", "play 2000 5 1 1 230 1", "play 2500 6 1 1 230 1", "run 3000"])
    assert [line for line in lines if line.startswith("RET")] == ["RET 1000 5 1", "RET 1500 5 0", "RET 2000 5 1", "RET 2500 6 1"]


# ---------------------------------------------------------------------------- touch pads
def _gestures(engine_exe, presses, until, phase):
    """Gestures for raw touches [(pad, from, to)], polled every TOUCH_POLL_MS from 400 + phase."""
    script = ["pads_reset"] + [f"press {pad} {a} {b}" for pad, a, b in presses] + [f"poll {400 + phase} {until} {POLL_MS}"]
    return [tuple(map(int, line.split()[1:])) for line in _out(engine_exe, script) if line.startswith("GESTURE")]


PHASES = range(0, POLL_MS, 3)


@pytest.mark.parametrize("held", [100, 250, 400 - POLL_MS])
def test_a_short_touch_is_one_tap_once_the_double_window_has_passed(engine_exe, held):
    for phase in PHASES:
        got = _gestures(engine_exe, [(1, 1000, 1000 + held)], 3000, phase)
        assert [(pad, g) for _, pad, g in got] == [(1, TAP)], (phase, got)
        release = 1000 + held
        assert release + 300 < got[0][0] < release + 300 + 2 * POLL_MS, (phase, got)


@pytest.mark.parametrize("held", [400 + POLL_MS, 550, 700 - POLL_MS])
def test_a_touch_between_tap_and_long_is_nothing(engine_exe, held):
    for phase in PHASES:
        assert _gestures(engine_exe, [(2, 1000, 1000 + held)], 3000, phase) == [], phase


@pytest.mark.parametrize("gap", [60, 150, 300 - POLL_MS])
def test_a_second_touch_within_300_ms_makes_a_double(engine_exe, gap):
    for phase in PHASES:
        second = 1120 + gap
        got = _gestures(engine_exe, [(3, 1000, 1120), (3, second, second + 120)], 3000, phase)
        assert [(pad, g) for _, pad, g in got] == [(3, DOUBLE)], (phase, got)
        assert second + 120 + DEBOUNCE_MS <= got[0][0] < second + 120 + DEBOUNCE_MS + POLL_MS, (phase, got)


@pytest.mark.parametrize("gap", [300 + POLL_MS, 450])
def test_a_later_second_touch_is_two_taps(engine_exe, gap):
    for phase in PHASES:
        second = 1120 + gap
        got = _gestures(engine_exe, [(4, 1000, 1120), (4, second, second + 120)], 3000, phase)
        assert [(pad, g) for _, pad, g in got] == [(4, TAP), (4, TAP)], (phase, got)


@pytest.mark.parametrize("held", [700 + POLL_MS, 1000, 3000])
def test_a_held_touch_is_one_long_press_on_the_700_ms_mark(engine_exe, held):
    for phase in PHASES:
        got = _gestures(engine_exe, [(1, 1000, 1000 + held)], 5000, phase)
        assert [(pad, g) for _, pad, g in got] == [(1, LONG)], (phase, got)
        assert 1700 <= got[0][0] < 1700 + POLL_MS, (phase, got)


def test_touches_shorter_than_the_debounce_are_ignored(engine_exe):
    for phase in PHASES:
        blips = [(1, 1000, 1000 + DEBOUNCE_MS - 5), (2, 1500, 1510), (4, 2000, 2000 + DEBOUNCE_MS - 1)]
        assert _gestures(engine_exe, blips, 3000, phase) == [], phase


def test_chatter_and_dropouts_shorter_than_the_debounce_do_not_split_a_touch(engine_exe):
    for phase in PHASES:
        chatter = [(1, 1000, 1004), (1, 1009, 1200), (1, 1203, 1207)]        # bouncy contact at both ends
        dropout = [(2, 1000, 1150), (2, 1180, 1300)]                         # 30 ms dropout inside a tap
        long_dropout = [(3, 1000, 1400), (3, 1425, 2000)]                    # and inside a long press
        got = _gestures(engine_exe, chatter + dropout + long_dropout, 4000, phase)
        assert sorted((pad, g) for _, pad, g in got) == [(1, TAP), (2, TAP), (3, LONG)], (phase, got)


def test_pads_are_independent_and_a_third_touch_starts_afresh(engine_exe):
    for phase in PHASES:
        presses = [(1, 1000, 1100), (1, 1250, 1350), (1, 1500, 1600),         # double, then a tap
                   (4, 1050, 2200),                                           # Q held meanwhile
                   (2, 1300, 1400)]                                           # R tapped meanwhile
        got = _gestures(engine_exe, presses, 4000, phase)
        assert [(pad, g) for _, pad, g in got if pad == 1] == [(1, DOUBLE), (1, TAP)], (phase, got)
        assert [(pad, g) for _, pad, g in got if pad != 1] == [(4, LONG), (2, TAP)] or \
            [(pad, g) for _, pad, g in got if pad != 1] == [(2, TAP), (4, LONG)], (phase, got)


# ---------------------------------------------------------------------------- the sketch
def _notifies(lines, name):
    out = []
    for line in lines:
        parts = line.split()
        if parts[0] == "NOTIFY" and parts[2] == name:
            out.append((int(parts[1]), bytes.fromhex(parts[3])))
    return out


def _state(lines):
    return [tuple(map(int, line.split()[1:])) for line in lines if line.startswith("STATE")]


def test_ble_callbacks_only_post_and_loop_applies_in_order(sketch_exe):
    lines = _out(sketch_exe, [
        "setup", "until 1000", "echo mark",
        "connect", "write haptic 0101017801", "state",       # the Bluetooth task posts; nothing moves yet
        "loop 1", "state",                                  # loop() connects, then plays
        "disconnect", "state",                              # posted only: still playing
        "loop 1", "state",                                  # loop() stops every motor
        "connect", "write haptic 0208037801", "loop 1", "write config ffffffff010000", "state", "loop 1", "state",
    ])
    after = lines[lines.index("ECHO mark"):]
    first = next(i for i, line in enumerate(after) if line.startswith("STATE"))
    assert not any(line.startswith("PWM") for line in after[:first]), "a callback never touches the motors"
    states = _state(lines)
    assert states[0][1:3] == (0, 0)                         # not connected, not playing
    assert states[1][1:4] == (1, 1, 255)                    # connected, seat_tap on L kicking
    assert states[2][1] == 1 and states[2][3] > 0
    assert states[3][1:] == (0, 0, 0, 0, 0, 0)              # disconnected: all motors off
    assert states[4][1] == 1 and states[4][6] > 0           # drop on F, mute not applied yet
    assert states[5][1:3] == (0, 1) and states[5][3:] == (0, 0, 0, 0)


def test_a_new_connection_resets_the_duplicate_filter(sketch_exe):
    lines = _out(sketch_exe, [
        "setup", "until 1000", "connect", "loop 1", "write haptic 01030c7801", "until 1400",
        "disconnect", "until 2000", "echo relaunch",
        "connect", "loop 1", "write haptic 01030c7801", "until 2400",       # the app's seq starts at 1 again
    ])
    after = lines[lines.index("ECHO relaunch"):]
    assert any("seq=1 zones=3 pattern=12" in line and line.endswith("-> play") for line in after), after
    assert [w for w in _pwm(after) if w[2] > 0], "the connection ticks play after a reconnect"


def test_status_is_notified_when_a_pattern_ends_on_its_own(sketch_exe):
    lines = _out(sketch_exe, ["setup", "until 1000", "connect", "until 2000",
                              "write haptic 0201017801", "until 2500"])     # seat_tap on L: 120 ms
    status = [(t, data[4] & 16) for t, data in _notifies(lines, "status") if t >= 2000]
    assert status == [(2000, 16), (2120, 0)], status


def test_status_is_notified_on_every_flag_change(sketch_exe):
    """Each STATUS flag (mute 1, mirror 2, test mode 4, low battery 8, playing 16) and the battery
    and charging bytes are notified when they change: a write in the loop() pass that applies it,
    a console command in the next pass (loop() reads the console last), the battery at its next
    sample. None waits for the 30 s period."""
    lines = _out(sketch_exe, [
        "setup", "until 1000", "connect", "until 2000",
        "write config ffffffff010000", "until 2100",            # mute
        "write config ffffffff000100", "until 2200",            # mirror
        "write config ffffffff000001", "until 2300",            # test mode
        "write config ffffffff000000", "until 2400",            # all off
        "console mirror 1", "until 2500", "console mirror 0", "until 2600",
        "battery 1700", "until 5100",                           # 3.4 V: 10 %, low, seen at the 5 s sample
        "charging 1", "until 10100",                            # on the charger: not low any more
        "write haptic 0101017801", "until 10400",               # seat_tap on L: 120 ms
    ])
    status = [(t, data[0], data[1], data[4] & 31) for t, data in _notifies(lines, "status") if t >= 2000]
    assert status == [
        (2000, 95, 0, 1), (2100, 95, 0, 2), (2200, 95, 0, 4), (2300, 95, 0, 0),
        (2401, 95, 0, 2), (2501, 95, 0, 0),
        (5000, 10, 0, 8), (10000, 10, 1, 0),
        (10100, 10, 1, 16), (10220, 10, 1, 0),
    ], status


def test_test_mode_echoes_each_command_as_an_input(sketch_exe):
    lines = _out(sketch_exe, ["setup", "until 1000", "connect", "write config ffffffff000001",
                              "loop 1", "write haptic 2a01017801", "until 1200"])
    assert (1001, bytes([0, 0x2A])) in _notifies(lines, "input")


def _backlog(lines):
    return [line for line in lines if "fell behind" in line]


def test_a_backlog_keeps_the_newest_commands(sketch_exe):
    script = ["setup", "until 1000", "connect", "loop 1"]
    script += [f"write haptic {seq:02x}0101e601" for seq in range(1, 21)]
    lines = _out(sketch_exe, script + ["loop 1"])
    played = [line for line in lines if line.startswith("SERIAL HAPTIC")]
    assert _backlog(lines) == ["SERIAL BLE: loop() fell behind: 4 writes left out with nothing lost, 0 lost"]
    assert len(played) == 16 and "seq=20 " in played[-1] and all(line.endswith("-> play") for line in played)


def test_a_folded_command_leaves_the_duplicate_filter_as_it_would_have(sketch_exe):
    # seq 6 is folded into the seq 5 behind it. Had 6 been played, 5 would play after it.
    lines = _out(sketch_exe, ["setup", "until 1000", "connect", "write haptic 0501017801", "loop 1", "echo backlog",
                              "write haptic 060f09aa01", *["write config ffffffff000000"] * 15,
                              "write haptic 0502017801", "loop 1"])
    after = lines[lines.index("ECHO backlog"):]
    assert [line for line in after if line.startswith("SERIAL HAPTIC")] == \
        ["SERIAL HAPTIC seq=5 zones=2 pattern=1 intensity=120 repeat=1 -> play"]
    assert _backlog(after) == ["SERIAL BLE: loop() fell behind: 1 writes left out with nothing lost, 0 lost"]


def test_a_backlog_never_loses_a_connect_or_a_disconnect(sketch_exe):
    lines = _out(sketch_exe, [
        "setup", "until 1000",
        "connect", *[f"write haptic {seq:02x}0f09aa01" for seq in range(1, 21)],
        "loop 1", "state",                                  # connected, playing the newest command
        "disconnect", "connect", *["write config ffffffff000000"] * 17,
        "loop 1", "state",                                  # the disconnect in between stopped it
        *[f"write haptic {seq:02x}0f09aa01" for seq in range(1, 18)], "disconnect",
        "loop 1", "state",
    ])
    states = _state(lines)
    assert states[0][1:3] == (1, 1) and states[0][3] > 0
    assert states[1][1:] == (0, 1, 0, 0, 0, 0)
    assert states[2][1:] == (0, 0, 0, 0, 0, 0)
    assert all(line.endswith(" 0 lost") for line in _backlog(lines))


def test_a_backlog_never_loses_the_settings(sketch_exe):
    lines = _out(sketch_exe, [
        "setup", "until 1000", "connect", "loop 1",
        "write config ffffffff010000", *[f"write haptic {seq:02x}0101e601" for seq in range(1, 17)],
        "loop 1", "state",                                  # muted first: the commands play silently
        "write config ffffffff000000", "loop 1", "write haptic 200f09aa01", "loop 1", "state",
        "write config ffffffff010000", *["write config ffffffff000000"] * 16,
        "loop 1", "state",                                  # the mute still stopped the motors
    ])
    states = _state(lines)
    assert states[0][1] == 1 and states[0][3:] == (0, 0, 0, 0)
    assert states[1][1] == 1 and states[1][3] > 0
    assert states[2][1] == 0 and states[2][3:] == (0, 0, 0, 0)
    configs = [line for line in lines if line.startswith("SERIAL CONFIG")]
    assert "mute=1" in configs[0] and configs[-1].endswith("mute=0 mirror=0 test=0")
    assert len(_backlog(lines)) == 2 and all(line.endswith(" 0 lost") for line in _backlog(lines))


def test_a_backlog_of_pattern_uploads_keeps_the_settings(sketch_exe):
    uploads = [f"write patterns {pid:02x}0164000000c8" for pid in range(32, 48)]
    lines = _out(sketch_exe, ["setup", "until 1000", "connect", "loop 1", "write config ffffffff000100", *uploads, "loop 1"])
    assert any(line.startswith("SERIAL CONFIG") and "mirror=1" in line for line in lines)
    stored = [line for line in lines if line.startswith("SERIAL PATTERNS")]
    assert len(stored) == 15 and stored[0].startswith("SERIAL PATTERNS id=33 ")
    assert _backlog(lines) == ["SERIAL BLE: loop() fell behind: 0 writes left out with nothing lost, 1 lost"]


def test_a_disconnect_or_mute_during_a_motor_write_leaves_no_motor_running(sketch_exe):
    # loop() is held inside each of its first 8 motor writes while the Bluetooth task
    # disconnects or mutes. The sketch from before the mailbox left a motor on in 12 of these 16.
    lines = _out(sketch_exe, ["setup", "interleave 8"])
    assert "INTERLEAVE held=16 stuck=0 of 16" in lines


def test_no_data_race_between_the_bluetooth_task_and_loop(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("fw_tsan")
    probe = out_dir / "probe.cpp"
    probe.write_text("#include <thread>\nint main() { std::thread t([] {}); t.join(); }\n")
    if subprocess.run([COMPILER, "-fsanitize=thread", "-pthread", str(probe), "-o", str(out_dir / "probe")],
                      capture_output=True).returncode != 0 or \
            subprocess.run([str(out_dir / "probe")], capture_output=True).returncode != 0:
        pytest.skip("ThreadSanitizer is not available")
    exe = _compile(out_dir, "sketch_harness.cpp", "sketch_tsan", "-pthread", "-fsanitize=thread", "-g")
    done = _run(exe, ["setup", "race 400", "interleave 8"], env={**os.environ, "TSAN_OPTIONS": "halt_on_error=1"}, check=False)
    assert "ThreadSanitizer" not in done.stderr, done.stderr[:4000]
    assert done.returncode == 0 and "RACE 400 stuck=0" in done.stdout and "INTERLEAVE held=16 stuck=0 of 16" in done.stdout
