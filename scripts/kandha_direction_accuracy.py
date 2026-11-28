"""SIMULATED zone accuracy of the direction finder (decision 0027) on synthetic rooms.

For every bearing in 15-degree steps, one LibriSpeech voice talks for 2.5 s in a synthetic room
(app/kandha/room_synth.py); the tracker's turn direction is turned into a stole zone and
compared with the truth. Conditions: clean (-50 dBFS noise per microphone), noisy (-30 dBFS),
and with an echo (a second path 4 ms later from 140 degrees away at 40% amplitude, -40 dBFS
noise). "stereo" is scored on what two microphones can do (left / centre / right, behind folded
to the front) and separately on the four true zones.

    python -m scripts.kandha_direction_accuracy --output docs/kandha/validation/direction-simulated.json
"""
import argparse
import json
from pathlib import Path

from app.kandha.direction import ArrayGeometry, DirectionTracker, side_zone
from app.kandha.room_synth import Room, Talker
from app.kandha.seatmap import angle_to_zone

CONDITIONS = {"clean": {"noise_db": -50, "echoes": []},
              "noisy": {"noise_db": -30, "echoes": []},
              "echo": {"noise_db": -40, "echoes": [(140, 0.004, 0.4)]}}
VOICES = ["198-209-0000", "3436-172162-0000", "5703-47212-0000"]


def run():
    results = {}
    for name, geometry in (("stereo", ArrayGeometry.stereo(0.03)), ("quad", ArrayGeometry.quad())):
        sided = geometry.channels == 2
        for cond, kw in CONDITIONS.items():
            rows, possible, true4, errors, misses = 0, 0, 0, [], []
            for k, bearing in enumerate(range(0, 360, 15)):
                room = Room(geometry, [Talker(bearing, 0.3, 2.5, VOICES[k % len(VOICES)])], seed=k, **kw)
                audio = room.render()
                tracker = DirectionTracker(geometry, room.rate)
                for i in range(0, len(audio), 2400):
                    tracker.feed(audio[i:i + 2400], (i + 2400) / room.rate)
                found = tracker.direction_between(0, 10)
                zone = side_zone(found["bearing"], sided) if found else None
                expected = side_zone(bearing, sided)
                rows += 1
                possible += zone == expected
                if zone != expected:
                    misses.append({"bearing": bearing, "expected": expected, "got": zone,
                                   "found_deg": round(found["bearing"], 1) if found else None, "on_boundary": bearing % 90 == 45})
                true4 += zone == angle_to_zone(bearing)
                if found and not sided:
                    errors.append(abs((found["bearing"] - bearing + 180) % 360 - 180))
            results[f"{name}/{cond}"] = {
                "bearings": rows,
                "zone_accuracy_for_what_it_can_tell": round(possible / rows, 3),
                "zone_accuracy_four_zones": round(true4 / rows, 3),
                "mean_bearing_error_deg": round(sum(errors) / len(errors), 1) if errors else None,
                "misses": misses,
                "misses_off_boundary": sum(1 for m in misses if not m["on_boundary"]),
            }
    return {"simulated": True, "method": __doc__.strip().splitlines()[0], "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = run()
    for key, value in report["results"].items():
        print(key, value)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
