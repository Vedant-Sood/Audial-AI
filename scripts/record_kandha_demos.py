"""Actual Chromium: play both built-in demos and record what the stole was asked to play.

The demos (browser/kandha/demo.js) send their speaker, cue, queue and silence moments through
the page's real path: /api/kandha/intents, the HapticScheduler in the service, and the paired
mock stole, which receives the same HAPTIC bytes a real stole would. This script plays the
seminar and the practicum demo one after the other and writes, for each, the decoded commands
the mock stole received (in order, with seconds since the demo started), the page's own tap list
and the seats. It checks the order against the tap sequences that docs/kandha/DEMO_SCRIPT.md
narrates, so the film script and the demos cannot drift apart.

    python -m scripts.record_kandha_demos --browser /opt/pw-browsers/chromium --output docs/kandha/validation/demo-taps.json
"""
import argparse
import json
import os
from pathlib import Path
import platform
import tempfile
import time

# (pattern, zones) the stole receives, in order, as DEMO_SCRIPT.md tells them
EXPECTED = {
    # three new voices at the front; the queue squeeze; Priya (left) and Dr Rao (front) again; the
    # queue clears with one squeeze; the silence ticks; Arjun (right)
    "seminar": [("new_voice", "F"), ("new_voice", "F"), ("new_voice", "F"), ("queue_ack", "LR"), ("seat_tap", "L"),
                ("seat_tap", "F"), ("queue_ack", "LR"), ("silence", "LR"), ("seat_tap", "R")],
    # the client and Vikram are new (Vikram is marked "This is me" just after, so he is never tapped
    # again); the client again (front); the voice softened (drop); the silence; the client after it;
    # hesitation; the voice rose. The client's last line follows Vikram, who is never tapped, so the
    # same-voice rule plays no second seat tap for it.
    "roleplay": [("new_voice", "F"), ("new_voice", "F"), ("seat_tap", "F"), ("drop", "F"), ("silence", "LR"),
                 ("seat_tap", "F"), ("hesitation", "F"), ("rise", "F")],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser", default="/opt/pw-browsers/chromium")
    parser.add_argument("--output", type=Path, required=True, help="the JSON record to write")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright
    from app.kandha.bridge import MockBackend, MockStole
    from app.kandha.patterns import table
    from app.kandha.protocol import HapticCommand
    from app.services.browser import BrowserService
    from app.utils.config import Settings

    patterns = table()
    report = {"what": "The taps the two built-in demos play through the real scheduler, as the paired mock stole received them",
              "generated_by": "scripts/record_kandha_demos.py", "platform": platform.platform(),
              "simulated": ["the stole is the in-process mock (the same HAPTIC bytes, played by the Python PatternPlayer)",
                            "the demos are scripted: no microphone, scripted tone estimates"],
              "demos": {}, "page_errors": []}
    with tempfile.TemporaryDirectory(prefix="audial-kandha-demos-") as directory:
        os.environ["ACCESSIBILITY_AI_HOME"] = directory
        stole = MockStole()
        service = BrowserService(settings=Settings(device="cpu", voice_colors=True, voice_cues=True, voice_tone=True),
                                 kandha_backend=MockBackend([stole]))
        service.start()
        try:
            assert service.kandha.pair(stole.address, stole.name) is True
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=args.browser, headless=True, args=["--no-sandbox"])
                report["browser_version"] = browser.version
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.on("console", lambda m: report["page_errors"].append(m.text) if m.type == "error" else None)
                page.goto(service.url + "/kandha/")
                page.wait_for_function("() => window.Kandha && window.Kandha.ready().ready && window.Kandha.ready().stream === 'open'")
                page.wait_for_timeout(1000)
                for key in ("seminar", "roleplay"):
                    before = len(stole.received)
                    started = time.monotonic()
                    page.evaluate(f"window.Kandha.playDemo('{key}')")
                    page.wait_for_timeout(2000)
                    # a demo runs 32-38 s; it sets S.demo back to null when it ends
                    page.wait_for_function("() => window.Kandha.S.demo === null", timeout=120000, polling=250)
                    seconds = round(time.monotonic() - started, 1)
                    page.wait_for_timeout(1500)
                    received = [(ts, HapticCommand.decode(d)) for ts, kind, d in stole.received[before:] if kind == "haptic"]
                    state = page.evaluate("""() => ({
                        mode: window.Kandha.settings.mode,
                        voices: Object.fromEntries([...window.Kandha.S.speakers.entries()].map(([id, s]) => [id, s.name])),
                        seats: window.Kandha.K.seats,
                        taps: window.Kandha.S.taps.map(t => ({intent: t.intent, pattern: t.pattern, zones: t.zones, voice: t.voice, device: t.device})) })""")
                    stole_received = [{"at": round(ts - started, 2), "pattern": patterns.by_id[c.pattern].key, "zones": c.zone_letters} for ts, c in received]
                    report["demos"][key] = {"mode": state["mode"], "seconds": seconds, "voices": state["voices"], "seats": state["seats"],
                                            "stole_received": stole_received, "page_taps": state["taps"],
                                            "sequence": [[r["pattern"], r["zones"]] for r in stole_received]}
                browser.close()
        finally:
            service.stop()
    for key, want in EXPECTED.items():
        demo = report["demos"].get(key, {})
        demo["matches_demo_script"] = [tuple(x) for x in demo.get("sequence", [])] == want
        # the page shows every tap the stole played, in the same order
        demo["page_matches_stole"] = [(t["pattern"], t["zones"]) for t in demo.get("page_taps", [])] == [tuple(x) for x in demo.get("sequence", [])]
    report["result"] = "PASS" if not report["page_errors"] and all(d["matches_demo_script"] and d["page_matches_stole"] for d in report["demos"].values()) else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for key, demo in report["demos"].items():
        print(key, demo["mode"], f"{demo['seconds']} s", " ".join(f"{p}:{z}" for p, z in demo["sequence"]),
              "matches DEMO_SCRIPT.md" if demo["matches_demo_script"] else f"DIFFERS from DEMO_SCRIPT.md {EXPECTED[key]}")
    print("result:", report["result"], "page errors:", report["page_errors"])
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
