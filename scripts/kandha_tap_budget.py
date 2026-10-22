"""Tap budget, part 2 (Python): how many taps per minute would the wearer feel in each mode?

    node scripts/kandha_tap_budget.mjs docs/kandha/validation/tap_budget_intents.json
    python scripts/kandha_tap_budget.py docs/kandha/validation/tap_budget_intents.json docs/kandha/validation/tap_budget.json

Runs the real HapticScheduler over the recorded intents in audio time, for Lecture, Seminar
(cues off, the default), Seminar with cues on, Practicum and Do not disturb. Reports taps per
minute, with and without speaker changes. Target: at most 6 per minute in Seminar excluding
speaker changes.
"""
import json
from pathlib import Path
import sys

from app.kandha.scheduler import HapticScheduler, Intent, SchedulerSettings

MODES = [("lecture", SchedulerSettings(mode="lecture")), ("seminar", SchedulerSettings(mode="seminar")),
         ("seminar_cues_on", SchedulerSettings(mode="seminar", seminar_cues=True)), ("practicum", SchedulerSettings(mode="practicum")),
         ("dnd", SchedulerSettings(mode="seminar", dnd=True))]
ZONES = ["L", "R", "B", "F"]


def count(case, settings):
    seats = {}
    scheduler = HapticScheduler(lambda v: seats.get(v), settings)
    played = []
    tick_t = 0.0
    for raw in case["intents"]:
        t = raw["created"]
        while tick_t < t:
            played += scheduler.tick(tick_t)
            tick_t += 0.02
        if raw["kind"] == "new_voice" and raw["voice"] not in seats:
            seats[raw["voice"]] = ZONES[(len(seats)) % 4]      # as if the wearer seated each new voice at once
        intent = Intent(raw["kind"], created=t, voice=raw["voice"], cue=raw["cue"], t=raw["t"], new=raw["new"])
        played += scheduler.submit(intent, t)
    for _ in range(100):
        played += scheduler.tick(tick_t)
        tick_t += 0.02
    minutes = case["minutes"]
    speaker = [p for p in played if p.intent.kind in ("speaker", "new_voice", "voice_resumes")]
    other = [p for p in played if p.intent.kind not in ("speaker", "new_voice", "voice_resumes")]
    by_kind = {}
    for p in played:
        key = p.intent.cue or p.intent.kind
        by_kind[key] = by_kind.get(key, 0) + 1
    return {"minutes": round(minutes, 2), "taps": len(played), "taps_per_minute": round(len(played) / minutes, 2),
            "excluding_speaker_changes_per_minute": round(len(other) / minutes, 2), "speaker_changes_per_minute": round(len(speaker) / minutes, 2),
            "by_kind": by_kind, "dropped": len(scheduler.dropped)}


def main(argv):
    source, target = Path(argv[1]), Path(argv[2])
    data = json.loads(source.read_text(encoding="utf-8"))
    report = {"what": "Taps per minute the wearer would feel, per mode, over the natural-speech fixtures (LibriSpeech readers), computed by the real scheduler from recorded engine intents",
              "generated_by": "scripts/kandha_tap_budget.py", "target": "Seminar: at most 6 taps per minute excluding speaker changes",
              "fixtures": data["fixtures"], "cases": {}}
    worst_seminar = 0.0
    for name, case in data["cases"].items():
        report["cases"][name] = {"engine_intents": len(case["intents"]), "engine_cues": len(case["engine_cues"]), "backchannels_suppressed": case["suppressed"], "modes": {}}
        for mode, settings in MODES:
            result = count(case, settings)
            report["cases"][name]["modes"][mode] = result
            if mode == "seminar":
                worst_seminar = max(worst_seminar, result["excluding_speaker_changes_per_minute"])
    report["seminar_worst_excluding_speaker_changes_per_minute"] = worst_seminar
    report["target_met"] = worst_seminar <= 6
    target.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for name, case in report["cases"].items():
        print(name, {m: (r["taps_per_minute"], r["excluding_speaker_changes_per_minute"]) for m, r in case["modes"].items()})
    print("seminar worst (excluding speaker changes):", worst_seminar, "per minute; target met:", report["target_met"])
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
