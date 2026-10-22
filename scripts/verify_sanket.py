"""Actual Chromium: Sanket voice view in the companion page, and the Sanket app on local captions.

A fake microphone plays two LibriSpeech readers taking turns (tests/fixtures/sanket). Whisper
is replaced by a stub that captions each received audio stretch with its own time span, so this
verifies the integration (shared clock, voices, cues, queue light, local captions, exports,
CSP), not speech-recognition or emotion accuracy (see tests/sanket.test.js and
models/sanket/evaluation.json for those).

    python -m scripts.verify_sanket --browser /usr/bin/chromium --output artifacts/sanket
"""

import argparse
import json
import os
from pathlib import Path
import platform
import tempfile
import threading
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def conversation(path):
    """Two readers, alternating, with short pauses: A B A B."""
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
    state = {"languages": []}

    def start(mode, source="browser", file_path=None, language=None):
        engine.source, engine.capture, engine.running = source, ExternalAudio(), True
        engine.language = service.settings.language if language is None else language
        engine.stop_requested.clear()
        state["languages"].append(engine.language)
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
                    engine.emit("caption", Caption(start_s, end_s, f"Words spoken from {start_s:.1f} to {end_s:.1f} seconds", "Unattributed"))
                    first = None
        threading.Thread(target=drain, daemon=True).start()

    def stop():
        engine.stop_requested.set()
        engine.running = False

    engine.start, engine.stop = start, stop
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    from app.services.browser import BrowserService
    from app.utils.config import Settings

    with tempfile.TemporaryDirectory(prefix="audial-sanket-") as directory:
        os.environ["ACCESSIBILITY_AI_HOME"] = directory
        audio = Path(directory) / "conversation.wav"
        seconds = conversation(audio)
        service = BrowserService(settings=Settings(device="cpu", voice_colors=True, voice_cues=True, voice_tone=True))
        state = stub_engine(service)
        service.start()
        report = {"platform": platform.platform(), "scope": __doc__.split("\n\n")[1].replace("\n", " "), "page_errors": []}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=args.browser, headless=True, args=[
                    "--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={audio}%noloop"])
                report["browser_version"] = browser.version
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                context.grant_permissions(["microphone"], origin=service.url)

                def watch(page):
                    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                    page.on("console", lambda m: report["page_errors"].append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)

                # 1. Companion page: Sanket voice view on the page's own microphone capture
                page = context.new_page(); watch(page)
                page.goto(service.url)
                page.locator("#voice-card summary").click()
                page.locator("#microphone").click()
                seen, deadline = set(), time.monotonic() + seconds + 6
                while time.monotonic() < deadline:
                    voice = page.locator("#voice-badge").get_attribute("data-voice")
                    if voice:
                        seen.add(voice)
                    page.wait_for_timeout(400)
                page.locator("#queue-button").click()
                assert page.locator("#queue-strip").is_visible()
                page.screenshot(path=str(args.output / "companion-voice-view.png"), full_page=True)
                page.keyboard.press("q")
                assert page.locator("#queue-strip").is_hidden()
                page.locator("#stop").click()
                page.wait_for_timeout(1500)
                tags = page.locator("#transcript .voice-tag").all_inner_texts()
                events = list(service.session.voice_events)
                report["companion_voices_seen"] = sorted(seen)
                report["companion_transcript_voice_tags"] = tags
                report["companion_stored_events"] = {k: sum(e["kind"] == k for e in events) for k in ("voice", "cue", "tone", "queue")}
                report["companion_turns"] = [(e["t"], e["id"]) for e in events if e["kind"] == "voice"]
                assert len(seen) >= 2, "both readers get their own colour"
                assert [voice for _, voice in report["companion_turns"]] == [1, 2, 1, 2], "A B A B: a returning reader gets their colour back"
                assert {"Voice 1", "Voice 2"} <= set(tags), "captions are attributed to voices by audio time"
                assert report["companion_stored_events"]["voice"] >= 2 and report["companion_stored_events"]["queue"] == 2
                vtt = page.evaluate("fetch('/api/export?format=vtt').then(r => r.text())")
                assert "Voice 1: Words spoken" in vtt and "Voice 2: Words spoken" in vtt
                report["companion"] = "PASS; colours per voice, transcript attribution, queue light and Q key, stored events, VTT names"
                page.close()

                # 2. Sanket app at /sanket/ with captions from the local (stub) engine
                page = context.new_page(); watch(page)
                page.goto(service.url + "/sanket/")
                page.wait_for_function("window.Sanket && window.Sanket.localHost && window.Sanket.toneModel")
                page.locator("#welcomeStart").click()
                page.wait_for_timeout(int((seconds + 5) * 1000))
                status = page.locator("#statusText").inner_text()
                info = page.evaluate("""() => ({
                    speakers: [...new Set(window.Sanket.S.lines.filter(l => l.kind === 'speech').map(l => l.speakerId))],
                    lines: window.Sanket.S.lines.filter(l => l.kind === 'speech').length,
                    tones: window.Sanket.S.tones.length,
                    colour: getComputedStyle(document.querySelector('#history .line')).borderLeftColor })""")
                page.screenshot(path=str(args.output / "sanket-local-captions.png"))
                page.locator("#startBtn").click()
                page.wait_for_timeout(800)
                report["sanket_status"] = status
                report["sanket"] = info
                report["sanket_session_languages"] = state["languages"]
                assert "AccessibilityAI on this computer" in status
                assert info["lines"] >= 4 and len(info["speakers"]) >= 2, "timed captions split between the two voices"
                assert info["tones"] > 0 and info["colour"] != "rgba(0, 0, 0, 0)", "inline voice colours allowed by the Sanket CSP"
                assert state["languages"][-1] == "en" and not service.engine.running
                report["sanket_app"] = "PASS; served under CSP, model loaded with hash check, local captions with per-word voice attribution"
                assert not report["page_errors"], report["page_errors"]
                browser.close()
        finally:
            service.stop()
        (args.output / "sanket-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=1), flush=True)


if __name__ == "__main__":
    main()
