# Kandha Stole Bluetooth protocol v1

Authoritative values live in `browser/sanket/kandha-patterns.json` (`protocol`, `zones`,
`pads`, `gestures`, `patterns`). `app/kandha/protocol.py` encodes and decodes every payload and
`firmware/kandha/` implements the same bytes. All multi-byte values are **little-endian**.

## Advertising and pairing

- Name: `Kandha-XXXX` (as the brief specifies), where `XXXX` are the last four hex digits of the
  BLE address. The prototype's simulated stole is `Kandha-SIM1`.
- Advertised service: `2ad2fdad-b9e2-4025-af4d-b35e6f13c100`. A scan lists a device that
  advertises this service UUID **or** a name starting with `Kandha-`.
- Pairing is user-initiated in the Stole panel (scan, choose, pair). The app remembers the
  address and reconnects only to it. `INPUT` notifications from any other address are ignored.
  The firmware requests LE Secure Connections "Just Works" bonding; the app does not rely on it.
- The stole requests an ATT MTU of 185 so a full PATTERNS upload fits one write.

## Characteristics

| Name | UUID (`…` = `2ad2fdad-b9e2-4025-af4d-b35e6f13c1`) | Properties | Length |
|---|---|---|---|
| HAPTIC | `…01` | write without response | 5 |
| PATTERNS | `…02` | write | 2 + 5·n (n ≤ 16) |
| INPUT | `…03` | notify | 2 |
| STATUS | `…04` | read, notify | 5 |
| CONFIG | `…05` | read, write | 7 |

### HAPTIC `[seq u8][zones u8][pattern u8][intensity u8][repeat u8]`

- `seq`: wraps at 255; within one connection the stole ignores a command whose `seq` equals
  the previous one (a duplicate delivery), so the app increments per command. The stole forgets
  the last `seq` on every new connection, so the first command after a reconnect or an app
  restart always plays. The app's mock and simulated stoles do the same.
- `zones`: bitmask `L=1, R=2, B=4, F=8`. `0` plays nothing.
- `pattern`: 0 = stop; 1–31 built-in (table below); 32–255 custom (uploaded through PATTERNS).
- `intensity`: 0–255 scales every step's `level`. The duty a zone's motor gets is
  `level × intensity × zone scale / (255 × 255)`, in whole numbers (0 when CONFIG `mute` is
  set). The firmware then adds two things for coin ERM motors (`firmware/kandha/config.h`):
  - a floor: any non-zero duty below `MOTOR_MIN_DUTY` = 60 is raised to 60, because the motor
    does not start below it;
  - a spin-up kick: a motor that starts from rest runs at full duty (255) for its first
    `MOTOR_KICK_MS` = 15 ms, timed from that start. A step or command that takes over within
    those 15 ms keeps the kick until they are up; a motor already spinning gets none.

  The app's `PatternPlayer`, the virtual stole and the screen use the formula without the floor
  and the kick; `tests/test_kandha_firmware_host.py` checks that the firmware equals them with
  both added.
- `repeat`: 1–255 plays of the whole step list. 0 is treated as 1.
- A new command **replaces** whatever is playing: the new pattern takes over at once, with no
  stop in between. This is how a speaker tap pre-empts a cue.

### PATTERNS `[id u8][n u8][(on_ms u16)(off_ms u16)(level u8)] × n`

- `id`: 32–255. Ids 0–31 are reserved for built-ins and are rejected.
- `n`: 1–16 steps. Each step drives the selected zones at `level` for `on_ms`, then rests
  `off_ms`. A step with `on_ms` 0 only rests; a step with both 0 is skipped. Steps are timed
  from when they were due, so a late tick never pushes the rest of a pattern back. Uploaded
  patterns live in RAM until power-off; uploading the id that is playing does not change the
  pattern already playing.

### INPUT `[pad u8][gesture u8]`

- `pad`: `1=L 2=R 3=B 4=Q`. `gesture`: `1=tap 2=double 3=long`.
- Gesture timing, the same on the stole and on the page's on-screen pads:
  - a touch shorter than 400 ms is a tap, sent 300 ms after it ends, unless a second touch
    starts within 300 ms of its end, which makes a double (sent when that second touch ends);
  - a touch held 700 ms is a long press, sent once on the 700 ms mark;
  - a touch of 400–699 ms sends nothing.

  On the stole, times are measured to within the 20 ms poll, a pad is debounced for 40 ms, and
  dropouts shorter than that do not split a touch. On the page, leaving the pad, a cancelled
  pointer or the pad losing keyboard focus cancels a touch, and Enter or Space on a focused pad
  follow the same rules.

What the app does with them:

| Pad | tap | double | long |
|---|---|---|---|
| L / R / B | assign the voice that just appeared (6 s window) to that zone | reassign the voice speaking now | clear the seat of the voice speaking now |
| Q | toggle "I want to speak" (queue noted squeeze) | same as tap | toggle do-not-disturb |

### STATUS `[battery u8][charging u8][fw_major u8][fw_minor u8][flags u8]`

- `battery`: 0–100 %. `charging`: 0/1.
- `flags`: bit0 muted, bit1 mirrored, bit2 test mode, bit3 low battery (≤ 20 %), bit4 a
  pattern is playing, bit5 touch pads calibrated.
- Notified as soon as any flag changes (including bit4 clearing when a pattern ends on its
  own) and at least every 30 s; readable at any time.

### CONFIG `[scale_L u8][scale_R u8][scale_B u8][scale_F u8][mute u8][mirror u8][test_mode u8]`

- Per-zone scale 0–255 (255 = full). `mute` stops every motor. `mirror` swaps L and R in every
  HAPTIC command (for wearing the stole the other way round or for a left-handed layout).
  `test_mode` makes the stole echo each HAPTIC command as an INPUT `[0][seq]` for bench checks.
- The app writes CONFIG on connect and whenever settings change; the virtual stole applies the
  same arithmetic in Python (`app/kandha/protocol.py: apply_config`). Reading CONFIG returns
  exactly the bytes the app last wrote.

## How the stole takes in writes

The BLE callbacks only queue each write for the firmware's `loop()`, which applies them in the
order they arrived, on its next pass. The queue holds 16 writes. Connects and disconnects are
counted, not queued, so none is lost: a disconnect stops every motor and a connect resets the
`seq` filter, in their place among the writes. If `loop()` falls behind (for
example during the serial console's `cal`), the firmware leaves out first a write that would
change nothing (a malformed write, a HAPTIC with a later HAPTIC behind it, a CONFIG with a later
CONFIG behind it and no HAPTIC between), then the oldest HAPTIC, then the oldest PATTERNS upload,
and the serial console says how many were left out.

## Built-in patterns (ids from the JSON table)

| id | key | zones | steps |
|---|---|---|---|
| 0 | stop | — | — |
| 1 | seat_tap | seat | 120 ms @255 |
| 2 | new_voice | F | 60 @255, rest 90, 60 @255 |
| 3 | drop | F | 7 × 100 ms swell 70→255→120 |
| 4 | rise | F | 3 × 80 ms @255, rest 70 |
| 5 | hesitation | F | 5 × 40 ms @120, rest 40 |
| 6 | silence | LR | 60 @150, rest 240, 60 @150 |
| 7 | queue_ack | LR | 180 @220 |
| 8 | queue_reminder | LR | 260 @200 |
| 9 | low_battery | B | 3 × 300 ms @170, rest 300 |
| 10 | seat_unmapped | F | 120 @230 |
| 11 | zone_test | any | 150 @255, rest 120, 150 @255 |
| 12 | connected | LR | 50 @130, rest 90, 50 @130 |

## Reconnection

Backoff 1, 2, 4, 8, 16, 30, 30 … seconds between attempts to the remembered address, reset on
success. While disconnected, captions are unaffected, commands go to the virtual stole and the
screen flashes the zone; the Stole panel shows "Reconnecting…" with the attempt count.

## Latency budget

Engine speaker decision → motor start: ≤ 150 ms inside the app (page → loopback HTTP →
scheduler → bridge write) and ≤ 300 ms worst case including a 30 ms connection interval and
one retransmission. The in-app part is measured with the mock device by
`scripts/verify_kandha.py`; the Bluetooth part is a budget until there is hardware.
