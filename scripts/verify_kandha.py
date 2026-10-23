"""Actual Chromium: Kandha on a fake microphone, Whisper stubbed, the mock stole paired.

Two LibriSpeech readers take turns (A B A B, tests/fixtures/sanket). Whisper is replaced by a stub
that captions each received stretch with its own time span, and the stole is the in-process mock
(the same bytes and timing as the firmware simulation). This verifies the integration, not speech
or emotion accuracy:

- the correct zones fire in the correct order (new voice, new voice, then the seats);
- the in-app latency budget (page intent -> stole write) holds;
- no cue storms: outside speaker changes at most one tap in any 1.5 s window;
- queue presses (key and stole pad) light the strip and are saved with the session;
- a consented "Save to sessions" writes this session's captions and events, as on screen;
- a pad double-tap reseats the voice speaking now.

    python -m scripts.verify_kandha --browser /opt/pw-browsers/chromium --output artifacts/kandha
"""
import argparse
import json
import os
from pathlib import Path
import platform
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def conversation(path):
    """Two readers, alternating, with short pauses: A B A B (the same clip as verify_sanket)."""
    def read(name):
        with wave.open(str(ROOT / "tests/fixtures/sanket" / f"{name}.wav")) as clip:
            return np.frombuffer(clip.readframes(clip.getnframes()), "<i2").astype(np.float32) / 32768
    a, b = read("198-209-0000"), read("3436-172162-0000")
    gap = lambda s: np.random.default_rng(1).normal(0, 3e-4, int(s * 16000)).astype(np.float32)
    parts = [gap(0.6), a[:8 * 16000], gap(0.8), b[:8 * 16000], gap(0.8), a[8 * 16000:13 * 16000], gap(0.8), b[8 * 16000:14 * 16000], gap(2)]
    signal = np.concatenate(parts)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
        out.writeframes((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes())
    return len(signal) / 16000


def stub_engine(service):
    """Browser capture without Whisper: every ~2.5 s of received audio becomes one timed caption."""
    from app.audio.capture import ExternalAudio
    from app.storage.transcript import Caption
    engine = service.engine
    engine.manager.installed = lambda _: True

    # the same signature as AudioEngine.start: /api/start passes the caption language
    def start(mode, source="browser", file_path=None, language=None):
        engine.source, engine.capture, engine.running = source, ExternalAudio(), True
        engine.language = service.settings.language if language is None else language
        engine.stop_requested.clear()
        capture = engine.capture

        def drain():
            first, last = None, None
            while not engine.stop_requested.is_set():
                try:
                    sequence, samples = capture.queue.get(timeout=0.2)
                except Exception:
                    continue
                first = sequence if first is None else first
                last = sequence + len(samples)
                if (last - first) / 16000 >= 2.5:
                    start_s, end_s = first / 16000, last / 16000
                    # a word confidence, as Whisper gives: the saved Kandha session must keep it
                    engine.emit("caption", Caption(start_s, end_s, f"Words spoken from {start_s:.1f} to {end_s:.1f} seconds", "Unattributed", 0.9))
                    first = None
        threading.Thread(target=drain, daemon=True).start()

    def stop():
        engine.stop_requested.set()
        engine.running = False

    engine.start, engine.stop = start, stop


def storms(taps, window=1.5):
    """The most cue-like taps (tone cues, silence, low battery) that started inside any window of
    `window` seconds. Speaker taps are excluded by the brief; queue squeezes answer the wearer's own
    presses and the connected ticks happen once, so they are not cues either."""
    times = sorted(t["at"] for t in taps if t["intent"] in ("cue", "silence", "low_battery"))
    worst = 0
    for i, t0 in enumerate(times):
        n = sum(1 for t in times[i:] if t - t0 <= window)
        worst = max(worst, n)
    return worst


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser", default="/opt/pw-browsers/chromium")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    from app.kandha.bridge import MockBackend, MockStole
    from app.kandha.patterns import table
    from app.kandha.protocol import GESTURE_DOUBLE, GESTURE_TAP, PAD_B, PAD_Q, HapticCommand
    from app.services.browser import BrowserService
    from app.utils.config import Settings

    with tempfile.TemporaryDirectory(prefix="audial-kandha-") as directory:
        os.environ["ACCESSIBILITY_AI_HOME"] = directory
        audio = Path(directory) / "conversation.wav"
        seconds = conversation(audio)
        stole = MockStole()
        service = BrowserService(settings=Settings(device="cpu", voice_colors=True, voice_cues=True, voice_tone=True), kandha_backend=MockBackend([stole]))
        stub_engine(service)
        service.start()
        report = {"platform": platform.platform(), "scope": __doc__.split("\n\n")[1].replace("\n", " "), "simulated": [
            "Whisper is a stub (captions are time spans, not words)", "the stole is the in-process mock, so Bluetooth latency is not measured",
            "the microphone is Chromium's fake device playing a WAV file"], "page_errors": []}
        try:
            # a saved room seats the first voice left and the second right, like a seminar room remembered from last week
            service.kandha.rooms("save", "E2E room")
            service.kandha.seats.rooms["E2E room"].slots = ["L", "R"]
            service.kandha.seats._save_store()
            service.kandha.update_settings({"mode": "seminar", "use_last_layout": True})
            assert service.kandha.pair(stole.address, stole.name) is True
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=args.browser, headless=True, args=[
                    "--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={audio}%noloop"])
                report["browser_version"] = browser.version
                context = browser.new_context(viewport={"width": 1280, "height": 720})
                context.grant_permissions(["microphone"], origin=service.url)
                page = context.new_page()
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.on("console", lambda m: report["page_errors"].append(m.text) if m.type == "error" else None)
                page.goto(service.url + "/kandha/")
                page.wait_for_function("window.Kandha && window.Kandha.ready().ready && window.Kandha.ready().stream === 'open' && window.Kandha.localHost")
                page.locator("#welcomeStart").click()
                started = time.monotonic()
                # a queue press from the keyboard early on, and from the stole pad later
                page.wait_for_timeout(1500)
                page.keyboard.press("q")
                page.wait_for_timeout(400)
                strip_after_key = page.locator("#strip").evaluate("e => e.classList.contains('is-on')")
                page.wait_for_timeout(1200)
                page.keyboard.press("q")
                page.wait_for_timeout(400)
                strip_after_second_key = page.locator("#strip").evaluate("e => e.classList.contains('is-on')")
                page.wait_for_timeout(1200)
                stole.press(PAD_Q, GESTURE_TAP)
                page.wait_for_timeout(500)
                strip_after_pad = page.locator("#strip").evaluate("e => e.classList.contains('is-on')")
                page.wait_for_timeout(1200)
                stole.press(PAD_Q, GESTURE_TAP)
                # let the conversation play; reseat the current voice to "behind" with a pad double-tap mid-way
                page.wait_for_timeout(int(seconds * 1000 * 0.55))
                current = service.kandha.current_voice
                stole.press(PAD_B, GESTURE_DOUBLE)
                page.wait_for_timeout(600)
                reseated = service.kandha.seats.zone_for(current) if current else None
                page.wait_for_timeout(int(seconds * 1000 * 0.5) + 3000)
                page.screenshot(path=str(args.output / "kandha-live.png"))
                page.locator("#startBtn").click()
                page.wait_for_timeout(1200)
                page.locator("#tab-review").click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(args.output / "kandha-review.png"), full_page=True)
                # a consented save writes this session (its captions and events), never an older capture
                page.locator("#consentBox").check()
                page.locator("#saveSession").click()
                page.wait_for_function("() => document.querySelector('#toast').textContent.includes('Saved to Audial-AI sessions')", timeout=10000)
                save_toast = page.locator("#toast").text_content()
                page_state = page.evaluate("""() => ({
                    voices: [...window.Kandha.S.speakers.keys()], lines: window.Kandha.S.lines.filter(l => l.kind === 'speech').length,
                    taps: window.Kandha.S.taps.map(t => ({zones: t.zones, pattern: t.pattern, voice: t.voice, device: t.device, latency: t.app_latency_ms, intent: t.intent})),
                    queue_lines: window.Kandha.S.lines.filter(l => l.kind === 'queue').map(l => l.text), seats: window.Kandha.K.seats })""")
                record = service.kandha_session
                # another Kandha window starts a session: this page says so at once and can no longer
                # save or export; a blank ?session= is refused, never the companion's own capture
                page.evaluate("() => fetch('/api/kandha/session/new', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({page: 'second-window'})})")
                page.wait_for_function("() => document.querySelector('[data-export=vtt]').disabled && document.querySelector('#saveSession').disabled", timeout=5000)
                # the review screen is open, so the reason is also said in the toast (a live region)
                page.wait_for_function("() => document.querySelector('#toast').textContent.startsWith('Another Kandha window')", timeout=5000)
                try:
                    blank = urllib.request.urlopen(service.url + "/api/export?format=vtt&session=", timeout=10).status
                except urllib.error.HTTPError as error:
                    blank = error.code
                report["replaced_by_another_window"] = {"note": page.locator("#saveNote").text_content(), "toast": page.locator("#toast").text_content(),
                                                        "toast_live": page.locator("#toast").get_attribute("aria-live"),
                                                        "buttons_described_by_note": page.evaluate("() => [...document.querySelectorAll('#saveSession, [data-export]')].every(b => b.getAttribute('aria-describedby') === 'saveNote')"),
                                                        "blank_export_status": blank}
                browser.close()
            # ---- what the stole received, decoded from the bytes
            t = table()
            received = [(ts, HapticCommand.decode(d)) for ts, kind, d in stole.received if kind == "haptic"]
            decoded = [{"at": round(ts - started, 3), "pattern": t.by_id[c.pattern].key, "zones": c.zone_letters, "seq": c.seq} for ts, c in received]
            dispatched = list(service.kandha.played)
            speaker_taps = [d for d in decoded if d["pattern"] in ("new_voice", "seat_tap", "seat_unmapped")]
            report["stole_received"] = decoded
            report["speaker_taps_in_order"] = [(d["pattern"], d["zones"]) for d in speaker_taps]
            latencies = sorted(x["app_latency_ms"] for x in dispatched if x.get("app_latency_ms") is not None)
            writes = service.kandha.bridge.link.latencies
            report["latency_ms"] = {"page_to_dispatch": {"n": len(latencies), "p50": latencies[len(latencies) // 2] if latencies else None,
                                                         "p95": latencies[int(len(latencies) * 0.95)] if latencies else None, "max": latencies[-1] if latencies else None},
                                    "bridge_write_rtt": {"n": len(writes), "max": max(writes) if writes else None},
                                    "budget_in_app_ms": 150, "budget_with_bluetooth_ms": 300, "note": "mock stole: the Bluetooth part is a budget, not a measurement"}
            report["cue_storm_worst_window_1_5s"] = storms(dispatched)
            # the page's own session record (what Save to sessions writes), whatever the caption source
            events = list(record.voice_events) if record is not None else []
            report["session_events"] = {k: sum(e["kind"] == k for e in events) for k in ("voice", "cue", "tone", "queue", "haptic", "seat")}
            from app.utils.paths import data_root
            saved = [json.loads(p.read_text(encoding="utf-8")) for p in (data_root() / "sessions").glob("*.json")]
            report["saved_session"] = {"toast": save_toast, "files": len(saved), "title": saved[0]["title"] if saved else None,
                                       "captions": len(saved[0]["captions"]) if saved else 0,
                                       "with_word_confidence": sum(c.get("word_confidence") == 0.9 for c in saved[0]["captions"]) if saved else 0,
                                       "events": len(saved[0].get("voice_view", {}).get("events", [])) if saved else 0}
            report["queue"] = {"strip_after_key": strip_after_key, "strip_after_second_key": strip_after_second_key, "strip_after_pad": strip_after_pad, "lines": page_state["queue_lines"]}
            report["pad_double_tap_reseated_current_voice_to"] = reseated
            report["page"] = page_state
            report["all_taps_in_order"] = [(x["intent"], x["pattern"], x["zones"], round(x["at"] - started, 2)) for x in dispatched]
            (args.output / "kandha-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
            # ---- assertions
            assert page_state["lines"] >= 4 and len(page_state["voices"]) >= 2, "timed captions and two voices"
            assert [p for p, _ in report["speaker_taps_in_order"][:2]] == ["new_voice", "new_voice"], "two new voices announced at the front"
            assert report["speaker_taps_in_order"][0][1] == "F"
            seats = [z for p, z in report["speaker_taps_in_order"] if p == "seat_tap"]
            assert seats[:1] == ["L"], f"the first reader returns on the left: {report['speaker_taps_in_order']}"
            assert "R" in seats or "B" in seats, "the second reader returns on the right (or behind, after the reseat)"
            assert report["latency_ms"]["page_to_dispatch"]["p95"] is not None and report["latency_ms"]["page_to_dispatch"]["p95"] <= 150, report["latency_ms"]
            assert report["cue_storm_worst_window_1_5s"] <= 1, "no cue storms"
            assert strip_after_key and not strip_after_second_key and strip_after_pad, "queue strip follows the Q key and the stole pad"
            assert report["session_events"]["queue"] >= 4 and report["session_events"]["voice"] >= 2 and report["session_events"]["haptic"] >= 4
            assert saved and len(saved) == 1 and saved[0]["id"] == record.id and saved[0]["title"].startswith("Kandha seminar"), report["saved_session"]
            assert report["saved_session"]["captions"] == page_state["lines"] and report["saved_session"]["events"] == len(events), "the saved session is the one on screen"
            assert report["saved_session"]["with_word_confidence"] == page_state["lines"], "every Whisper line keeps its engine caption's word confidence"
            replaced = report["replaced_by_another_window"]
            assert replaced["note"].startswith("Another Kandha window") and replaced["blank_export_status"] == 409, replaced
            assert replaced["toast"] == replaced["note"] and replaced["toast_live"] == "polite" and replaced["buttons_described_by_note"], replaced
            assert reseated == "B", "a pad double-tap reseats the voice speaking now"
            assert not report["page_errors"], report["page_errors"]
            report["result"] = "PASS"
        finally:
            service.stop()
        (args.output / "kandha-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=1), flush=True)


if __name__ == "__main__":
    main()
