"""The Kandha page in real Chromium, served by a real BrowserService with the mock stole paired.

Covers the page fixes that only show in a browser: C15 (a focused seat chip moves only its voice),
C17 (Demos in the dock), C19 (the voice dialog's Enter, Escape and close), C20 (the clock after a
demo or a pause), C22 (the seat highlight ends with the seat window), C23 (no "Turn taken" from a
new session), C24 (the queue strip after a reload), G4 (browser captions only as an opt-in), C1
(the intents know the silence setting), G7 (the on-screen pads read gestures as the stole does),
the unreachable-service status and flash, the page's tag on every intent (its clock measured on its
own), and the microphone remembered by its name.

The browser's speech recognition is replaced by a counting fake, the microphone is Chromium's fake
device, and demos are fast-forwarded with Playwright's clock. Skipped without Playwright or Chromium
(KANDHA_CHROMIUM, /opt/pw-browsers/chromium, or Playwright's own install).
"""
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

FAKE_SR = """
(() => {
  window.__sr = { created: 0, started: 0, aborted: 0 };
  class FakeSR {
    constructor() { window.__sr.created++; }
    start() { window.__sr.started++; setTimeout(() => this.onstart && this.onstart(), 10); }
    abort() { window.__sr.aborted++; }
    stop() {}
  }
  window.webkitSpeechRecognition = FakeSR;
  try { delete window.SpeechRecognition; } catch (e) { /* ignore */ }
  window.SpeechRecognition = undefined;
})();
"""
# every microphone the page opens: what it asked for and what it got
RECORD_MICROPHONE = """
(() => {
  window.__gum = [];
  const md = navigator.mediaDevices, open = md.getUserMedia.bind(md);
  md.getUserMedia = async (c) => { const s = await open(c); window.__gum.push({ asked: c && c.audio && c.audio.deviceId || null, label: s.getAudioTracks()[0].label }); return s; };
})();
"""
# the page's own timers of 5 s or more never fire (so only the service can end the seat highlight)
NO_LONG_TIMERS = """
(() => { const later = window.setTimeout; window.setTimeout = (f, ms, ...args) => (+ms >= 5000 ? 0 : later(f, ms, ...args)); })();
"""
READY = "() => window.Kandha && window.Kandha.ready().ready && window.Kandha.ready().stream === 'open'"
STATUS = "() => [document.querySelector('#status').dataset.state, document.querySelector('#statusText').textContent]"
SAVED = "() => JSON.parse(localStorage.getItem('kandha.settings.v1') || '{}')"


def chromium_candidates():
    for path in (os.environ.get("KANDHA_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if path and Path(path).exists():
            yield path
    yield None   # Playwright's own Chromium, when installed


@pytest.fixture(scope="module")
def kandha(tmp_path_factory):
    from app.kandha.bridge import MockBackend, MockStole
    from app.services.browser import BrowserService
    from app.utils.config import Settings
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ACCESSIBILITY_AI_HOME", str(tmp_path_factory.mktemp("kandha-page-home")))
        mp.setenv("HF_HUB_OFFLINE", "1")
        pw = sync_api.sync_playwright().start()
        browser = None
        for path in chromium_candidates():
            try:
                browser = pw.chromium.launch(executable_path=path, headless=True, args=[
                    "--no-sandbox", "--disable-gpu", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
                break
            except sync_api.Error:
                continue
        if browser is None:
            pw.stop()
            pytest.skip("Chromium for Playwright is not installed")
        stole = MockStole()
        # Whisper is not installed in this temporary home, so the page has no local captions
        service = BrowserService(settings=Settings(device="cpu", voice_colors=True, voice_cues=True, voice_tone=True), kandha_backend=MockBackend([stole]))
        service.start()
        try:
            assert service.kandha.pair(stole.address, stole.name) is True
            yield type("Kandha", (), {"browser": browser, "service": service, "url": service.url})
        finally:
            browser.close()
            pw.stop()
            service.stop()


@contextmanager
def kandha_page(k, posts=None, clock=False, grant=True, scripts=(FAKE_SR,), failing_requests=False):
    """A fresh browser context on the page; fails on any page error. clock: Playwright's clock, to fast-forward
    demos. failing_requests: the test makes requests fail itself (page.route), so their console errors are expected."""
    k.service.kandha.update_settings({"mode": "seminar"})
    k.service.kandha.set_queue(False)
    ctx = k.browser.new_context(viewport={"width": 1280, "height": 800})
    if grant:
        ctx.grant_permissions(["microphone"], origin=k.url)
    for script in scripts:
        ctx.add_init_script(script)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not (failing_requests and m.text.startswith("Failed to load resource")) else None)
    if posts is not None:
        page.on("request", lambda r: posts.append(json.loads(r.post_data)) if r.method == "POST" and r.url.endswith("/api/kandha/seats") else None)
    if clock:
        page.clock.install()
    try:
        page.goto(k.url + "/kandha/")
        page.wait_for_function(READY, timeout=20000)
        yield page
        assert not errors, errors
    finally:
        ctx.close()


def wait_seats(page, expected, timeout=5):
    page.wait_for_function("(exp) => { const s = window.Kandha.K.seats; return Object.entries(exp).every(([k, v]) => (s[k] ?? null) === v); }", arg=expected, timeout=timeout * 1000)


def tab_to(page, selector, limit=80):
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    for i in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate("(sel) => !!document.activeElement && document.activeElement.matches(sel)", selector):
            return i + 1
    return None


def run_demo_to_end(page, step_ms=2000, limit=40):
    """Fast-forward a playing demo to its end on Playwright's clock."""
    for _ in range(limit):
        page.clock.run_for(step_ms)
        if page.evaluate("() => !window.Kandha.S.demo && document.querySelector('#statusText').textContent === 'Demo finished'"):
            return
    raise AssertionError("the demo did not finish")


def press_queue(page, on):
    page.keyboard.press("q")
    page.wait_for_function("(on) => window.Kandha.S.queue.on === on", arg=on)


def test_c15_a_focused_seat_chip_moves_only_its_own_voice(kandha):
    posts = []
    with kandha_page(kandha, posts) as page:
        # seminar seats 1 F, 2 L, 3 R; voice 3 speaking. Focus voice 2 on the room diagram (no click) and press 4.
        page.evaluate("() => { const K = window.Kandha; K.onSpeaker(1, 1, true); K.onSpeaker(2, 2, true); K.onSpeaker(3, 3, true); K.assignSeat(1, 'F', 'demo'); K.assignSeat(2, 'L', 'demo'); K.assignSeat(3, 'R', 'demo'); }")
        wait_seats(page, {"1": "F", "2": "L", "3": "R"})
        page.evaluate("() => window.Kandha.showScreen('seats')")
        page.wait_for_timeout(150)
        posts.clear()
        page.evaluate("() => document.querySelector('#roomBig [data-voice=\"2\"]').focus()")
        page.keyboard.press("4")
        wait_seats(page, {"2": "F", "3": "R"})
        page.wait_for_timeout(300)
        assert [(p["voice"], p["zone"]) for p in posts] == [(2, "F")], posts
        assert page.evaluate("() => document.activeElement && document.activeElement.getAttribute('data-voice')") == "2", "focus stays on the moved voice"
        posts.clear()
        page.keyboard.press("1")
        wait_seats(page, {"2": "L", "3": "R"})
        page.wait_for_timeout(300)
        assert [(p["voice"], p["zone"]) for p in posts] == [(2, "L")], posts
    posts = []
    with kandha_page(kandha, posts) as page:
        # practicum-like: the client 1 at the front, Vikram 2 is "me", the client speaking. Tab to Vikram's unseated chip, press 3.
        page.evaluate("() => { const K = window.Kandha; K.onSpeaker(1, 1, true); K.onSpeaker(2, 2, true); K.assignSeat(1, 'F', 'demo'); K.assignSeat(2, 'me', 'demo'); K.onSpeaker(1, 5, false); }")
        wait_seats(page, {"1": "F", "2": "me"})
        page.evaluate("() => window.Kandha.showScreen('seats')")
        page.wait_for_timeout(150)
        posts.clear()
        assert tab_to(page, "#unseated [data-chip='2']") is not None
        page.keyboard.press("3")
        wait_seats(page, {"1": "F", "2": "B"})
        page.wait_for_timeout(300)
        assert [(p["voice"], p["zone"]) for p in posts] == [(2, "B")], posts
        focus = page.evaluate("() => document.activeElement && (document.activeElement.getAttribute('data-voice') || document.activeElement.dataset.chip)")
        assert focus == "2", "focus follows the voice onto the room diagram"


def test_c19_enter_saves_the_voice_name_and_escape_or_close_never_renames(kandha):
    with kandha_page(kandha) as page:
        name = "() => ({ open: document.querySelector('#voiceDlg').open, name: window.Kandha.S.speakers.get(1).name })"
        page.evaluate("() => window.Kandha.onSpeaker(1, 1, true)")
        page.locator("#voices [data-voice='1']").click()
        page.locator("#voiceName").fill("Renamed By Enter")
        page.locator("#voiceName").press("Enter")
        page.wait_for_timeout(200)
        assert page.evaluate(name) == {"open": False, "name": "Renamed By Enter"}
        page.locator("#voices [data-voice='1']").click()
        page.locator("#voiceName").fill("Saved By Click")
        page.locator("#voiceSave").click()
        page.locator("#voices [data-voice='1']").click()
        page.locator("#voiceName").fill("Escaped")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert page.evaluate(name) == {"open": False, "name": "Saved By Click"}, "Escape after an earlier Save does not rename"
        page.locator("#voices [data-voice='1']").click()
        page.locator("#voiceName").fill("Closed")
        page.locator("#voiceDlg .dlg__close").click()
        page.wait_for_timeout(200)
        assert page.evaluate(name) == {"open": False, "name": "Saved By Click"}, "the close button does not rename"
        page.locator("#missBtn").click()
        page.locator("#missDlg .dlg__close").click()
        page.wait_for_timeout(100)
        assert not page.evaluate("() => document.querySelector('#missDlg').open")


def test_c22_the_seat_highlight_ends_when_the_seat_window_closes(kandha, monkeypatch):
    """Two ways, each checked alone: the page's own timer (the service's window-closed event never
    arrives, as on a dropped stream) and the service's event (the page's own timer never fires)."""
    new_voice = "() => fetch('/api/kandha/intents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intents: [{ kind: 'new_voice', voice: 7, t: 0, new: true, age_ms: 0, sent: Date.now() }] }) })"
    highlighted = "() => document.querySelectorAll('.room__seat.is-over').length"
    cleared = "() => document.querySelectorAll('.room__seat.is-over').length === 0 && window.Kandha.K.pending === null"
    service = kandha.service.kandha
    publish = service.publish
    monkeypatch.setattr(service, "publish", lambda kind, data: None if data.get("action") == "window-closed" else publish(kind, data))
    with kandha_page(kandha) as page:
        page.evaluate(new_voice)
        page.wait_for_timeout(800)
        assert page.evaluate(highlighted) == 8, "highlighted while the window is open"
        page.wait_for_function(cleared, timeout=9000)
        assert service.seats.snapshot(service.clock())["pending"] is None
    monkeypatch.undo()
    with kandha_page(kandha, scripts=(FAKE_SR, NO_LONG_TIMERS)) as page:
        page.evaluate(new_voice)
        page.wait_for_timeout(800)
        assert page.evaluate(highlighted) == 8
        page.wait_for_function(cleared, timeout=9000)
        assert page.evaluate("() => window.Kandha.S.lines.filter(l => l.kind === 'seat').length") == 0, "a window closing is not a seat change"


def test_c23_a_new_session_with_the_queue_on_adds_no_turn_taken(kandha):
    queue_lines = "() => window.Kandha.S.lines.filter(l => l.kind === 'queue').map(l => l.text)"
    with kandha_page(kandha) as page:
        press_queue(page, True)
        page.wait_for_timeout(1200)
        page.locator("#welcomeStart").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        page.wait_for_timeout(1000)
        assert page.evaluate(queue_lines) == []
        assert page.evaluate("() => [window.Kandha.S.queue.on, document.querySelector('#strip').classList.contains('is-on'), document.querySelector('#queueBtn').getAttribute('aria-pressed')]") == [False, False, "false"]
        record = kandha.service.kandha_session
        assert not [e for e in (record.voice_events if record else []) if e.get("kind") == "queue"]
        page.locator("#startBtn").click()
    with kandha_page(kandha, clock=True) as page:
        press_queue(page, True)
        page.wait_for_timeout(1200)
        page.locator("#welcome [data-demo='roleplay']").click()
        page.wait_for_function("() => !!window.Kandha.S.demo")
        page.clock.run_for(1500)
        assert page.evaluate(queue_lines) == []
        assert not page.evaluate("() => document.querySelector('#strip').classList.contains('is-on')")


def test_c24_after_a_reload_the_queue_strip_goes_on_from_the_service_wait(kandha):
    with kandha_page(kandha) as page:
        press_queue(page, True)
        page.wait_for_timeout(500)
        with kandha.service.kandha.lock:
            kandha.service.kandha.queue.since -= 120
        page.reload()
        page.wait_for_function(READY, timeout=20000)
        page.wait_for_function("() => window.Kandha.S.queue.on === true", timeout=5000)
        page.wait_for_timeout(700)
        mins, secs = page.locator("#stripTime").inner_text().split(":")
        assert abs(int(mins) * 60 + int(secs) - kandha.service.kandha.snapshot()["queue"]["waited_s"]) <= 2
        press_queue(page, False)
        line = page.evaluate("() => window.Kandha.S.lines.filter(l => l.kind === 'queue').map(l => l.text).pop()")
        assert line and int(line.split("after ")[1].split(" ")[0]) >= 120, line


def test_g4_browser_captions_only_when_turned_on(kandha):
    with kandha_page(kandha) as page:
        page.wait_for_function("() => !!window.Kandha.localHost", timeout=10000)
        box = page.evaluate("() => { const b = document.querySelector('#setBrowserCaptions'); return { checked: b.checked, label: b.closest('label').textContent.replace(/\\s+/g, ' ') }; }")
        assert not box["checked"] and "maker" in box["label"] and "server" in box["label"], box
        privacy = page.evaluate("() => document.querySelector('#privacyTitle').parentElement.textContent.replace(/\\s+/g, ' ')")
        assert "The one exception" not in privacy and "Off unless" in privacy, privacy
        page.locator("#welcomeStart").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        page.wait_for_timeout(1200)
        st = page.evaluate("() => ({ sr: window.__sr, status: document.querySelector('#statusText').textContent, hint: document.querySelector('#nowHint').textContent, engine: !!window.Kandha.engine })")
        assert st["sr"]["started"] == 0 and "browser captions" not in st["status"], "never a silent fallback"
        assert "Whisper" in st["hint"] and "taps" in st["status"] and st["engine"], "the page says why, and voices keep working"
        page.evaluate("() => window.Kandha.showScreen('settings')")
        page.locator("#setBrowserCaptions").check()
        page.wait_for_timeout(600)
        on = page.evaluate("() => ({ sr: window.__sr, status: document.querySelector('#statusText').textContent })")
        assert on["sr"]["started"] >= 1 and "browser captions" in on["status"], on
        page.locator("#setBrowserCaptions").uncheck()
        page.wait_for_timeout(600)
        off = page.evaluate("() => ({ sr: window.__sr, status: document.querySelector('#statusText').textContent })")
        assert off["sr"]["aborted"] >= 1 and "browser captions" not in off["status"], off
        assert page.evaluate(SAVED)["browserCaptions"] is False
        page.locator("#startBtn").click()


def test_c17_c20_demos_from_the_dock_and_the_clock_after_a_demo(kandha):
    with kandha_page(kandha, clock=True) as page:
        page.locator("#welcome [data-demo='roleplay']").click()
        page.wait_for_function("() => !!window.Kandha.S.demo")
        # C17: Demos in the dock, visible and reachable by keyboard while a demo plays
        assert page.locator("#demoBtn").is_visible()
        assert tab_to(page, "#demoBtn") is not None
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        assert page.evaluate("() => document.querySelector('#demoDlg').open")
        page.locator("#demoDlg [data-demo='seminar']").click()
        page.wait_for_function("() => !!window.Kandha.S.demo && window.Kandha.S.demoTitle === 'Case seminar'")
        assert not page.evaluate("() => document.querySelector('#demoDlg').open")
        run_demo_to_end(page)
        # C20: after the demo the clock stays at its end
        end_caption = page.evaluate("() => Math.max(...window.Kandha.S.lines.filter(l => l.kind === 'speech').map(l => l.t))")
        press_queue(page, True)
        page.evaluate("() => window.Kandha.assignSeat(1, 'B', 'screen')")
        page.wait_for_function("() => window.Kandha.S.lines.filter(l => l.kind === 'seat').length > 0 && window.Kandha.K.seats['1'] === 'B'", timeout=5000)
        lines = page.evaluate("() => window.Kandha.S.lines.filter(l => l.kind === 'queue' || l.kind === 'seat').slice(-2).map(l => [l.kind, l.t])")
        assert len(lines) == 2 and all(t >= end_caption - 0.5 for _, t in lines), (lines, end_caption)
        page.evaluate("() => window.Kandha.showScreen('review')")
        page.wait_for_timeout(200)
        mins, secs = page.locator("#reviewSummary").inner_text().split(" ")[0].split(":")
        assert int(mins) * 60 + int(secs) >= end_caption - 1, "the review gives the demo's real length"
        tl = page.evaluate("""() => { const svg = document.querySelector('#timelineWrap svg'); const w = +svg.getAttribute('width');
            const labels = [...svg.querySelectorAll('text')].map(t => t.textContent).filter(s => /^\\d+:\\d\\d$/.test(s));
            const right = Math.max(...[...svg.querySelectorAll('rect')].map(r => (+r.getAttribute('x') || 0) + (+r.getAttribute('width') || 0)));
            return { w, labels, right }; }""")
        assert len(tl["labels"]) > 1 and tl["right"] <= tl["w"] + 1, tl
        rows = [r for r in page.evaluate("() => window.Kandha.exportText()").split("\n")[2:] if r.startswith("[")]
        asked = max(i for i, r in enumerate(rows) if "asked to speak" in r)
        last_speech = max(i for i, r in enumerate(rows) if ": " in r and "—" not in r and "~" not in r)
        assert asked > last_speech, "the text export lists post-demo events after the demo's captions"
        page.evaluate("() => window.Kandha.showScreen('live')")
        page.locator("#missBtn").click()
        page.wait_for_timeout(200)
        miss = page.evaluate("() => ({ shown: document.querySelectorAll('#missList li').length, all: window.Kandha.S.lines.length })")
        page.keyboard.press("Escape")
        assert miss["shown"] < miss["all"], "What did I miss lists only the last 30 seconds"
        # C17: a demo can be replayed after one ended, and the queue left on adds no line
        page.locator("#demoBtn").click()
        page.locator("#demoDlg [data-demo='roleplay']").click()
        page.wait_for_function("() => !!window.Kandha.S.demo")
        page.clock.run_for(600)
        replay = page.evaluate("() => ({ title: window.Kandha.S.demoTitle, demo: !!window.Kandha.S.demo, queueLines: window.Kandha.S.lines.filter(l => l.kind === 'queue').length })")
        assert replay == {"title": "Practicum role-play", "demo": True, "queueLines": 0}, replay
        page.locator("#demoBtn").click()
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        assert page.evaluate("() => !document.querySelector('#demoDlg').open && document.activeElement && document.activeElement.id === 'demoBtn'")


def test_c20_pause_keeps_the_engine_clock_and_a_demo_after_listening_has_its_own(kandha):
    queue_t = "() => window.Kandha.S.lines.filter(l => l.kind === 'queue').pop().t"
    with kandha_page(kandha, clock=True) as page:
        page.locator("#welcomeStart").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        page.wait_for_function("() => window.Kandha.engine && window.Kandha.engine.t > 2.2", timeout=10000)
        page.locator("#startBtn").click()
        page.wait_for_function("() => window.Kandha.S.running === false")
        frozen = page.evaluate("() => window.Kandha.engine.t")
        press_queue(page, True)
        assert abs(page.evaluate(queue_t) - frozen) < 0.05, "after Pause an event is stamped at the paused engine time"
        press_queue(page, False)
        page.locator("#startBtn").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        page.wait_for_timeout(800)
        page.locator("#demoBtn").click()
        page.locator("#demoDlg [data-demo='roleplay']").click()
        page.wait_for_function("() => !!window.Kandha.S.demo")
        assert page.evaluate("() => [window.Kandha.S.running, !!window.Kandha.engine, document.querySelector('#startLabel').textContent]") == [False, False, "Start"]
        run_demo_to_end(page)
        end_caption = page.evaluate("() => Math.max(...window.Kandha.S.lines.filter(l => l.kind === 'speech').map(l => l.t))")
        press_queue(page, True)
        assert page.evaluate(queue_t) >= end_caption - 0.5
        press_queue(page, False)


def test_c1_the_intents_follow_the_silence_setting_with_the_cue_on_or_off(kandha):
    intents = "() => [window.Kandha.intents.silenceSec, window.Kandha.intents.silenceFrom]"
    seminar_silence = "#cueTable input[data-cmode='seminar'][data-cue='silence']"
    with kandha_page(kandha) as page:
        # passed from the start, before any silence cue could show it
        assert page.evaluate(intents) == [4, "page"]
        page.evaluate("() => window.Kandha.showScreen('settings')")
        page.select_option("#setSilence", "8")
        page.wait_for_function("() => window.Kandha.intents.silenceSec === 8")
        # "Long silence" unticked: the engine's cue goes, the intents keep the setting
        cue_was = page.locator(seminar_silence).is_checked()
        page.locator(seminar_silence).set_checked(False)
        page.wait_for_function("() => window.Kandha.K.settings.cues_by_mode.seminar.silence === false")
        try:
            page.locator("#startBtn").click()
            page.wait_for_function("() => window.Kandha.S.running === true && !!window.Kandha.engine", timeout=10000)
            engine = page.evaluate("() => [window.Kandha.engine.settings.silenceSec, window.Kandha.engine.settings.cues.silence]")
            assert engine == [8, False]
            assert page.evaluate(intents) == [8, "page"]
            page.select_option("#setSilence", "3")
            page.wait_for_function("() => window.Kandha.intents.silenceSec === 3 && window.Kandha.engine.settings.silenceSec === 3")
            page.locator("#startBtn").click()
        finally:
            page.locator(seminar_silence).set_checked(cue_was)
            page.wait_for_function("(on) => window.Kandha.K.settings.cues_by_mode.seminar.silence === on", arg=cue_was)
        # a new session keeps the page's setting
        page.locator("#startBtn").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        assert page.evaluate(intents) == [3, "page"]
        # lowered during a silence, the engine's silence cue comes late (4 s after the speech, not
        # 3): the page's setting stays, the late cue does not replace it
        page.evaluate("""() => { const E = window.Kandha.engine, t = window.Kandha.intents.engineT + 0.1;
            E.onEvent({ type: 'speech-end', t }); E.onEvent({ type: 'cue', kind: 'silence', t: t + 4 }); }""")
        assert page.evaluate(intents) == [3, "page"]
        page.locator("#startBtn").click()


def test_an_unreachable_service_flashes_every_seat_tap_and_a_new_session_drops_the_old_status(kandha):
    with kandha_page(kandha, clock=True, failing_requests=True) as page:
        page.locator("#welcomeStart").click()
        page.wait_for_function("() => document.querySelector('#status').dataset.state === 'live'", timeout=10000)
        page.evaluate("() => window.Kandha.assignSeat(9, 'L', 'screen')")
        page.wait_for_function("() => window.Kandha.K.seats['9'] === 'L'")
        # the fallback flashes, recorded: a service record has segments, the page's own flash none
        page.evaluate("""() => { const P = window.KandhaViews.StoleView.prototype, pulse = P.pulse; window.__flashes = [];
            P.pulse = function (r) { if (r && !r.segments) window.__flashes.push(r.zones); return pulse.call(this, r); }; }""")
        page.route("**/api/kandha/intents", lambda route: route.abort())
        page.evaluate("() => window.Kandha.intents.emit({ kind: 'voice_resumes', voice: 9, t: 5, new: false })")
        page.wait_for_function("() => document.querySelector('#statusText').textContent.startsWith('Stole service unreachable')")
        assert "L" in page.evaluate("() => window.__flashes"), "a voice resuming after a silence flashes its seat"
        page.locator("#startBtn").click()
        assert page.evaluate(STATUS) == ["idle", "Paused"]
        page.locator("#demoBtn").click()
        page.locator("#demoDlg [data-demo='seminar']").click()
        page.wait_for_function("() => !!window.Kandha.S.demo")
        page.clock.run_for(1000)
        # the demo's own taps fail too, so the line says so again before the service comes back
        page.wait_for_function("() => document.querySelector('#statusText').textContent.startsWith('Stole service unreachable')")
        page.unroute("**/api/kandha/intents")
        # the service answers again: the demo's own status comes back, never the live session's
        page.evaluate("() => window.Kandha.intents.emit({ kind: 'silence', t: 1, voice: null })")
        page.wait_for_function("() => !document.querySelector('#statusText').textContent.startsWith('Stole service unreachable')")
        assert page.evaluate(STATUS) == ["demo", "Demo · Case seminar"]


def test_each_intent_carries_its_age_and_the_system_clock_when_it_was_sent(kandha):
    bodies = []
    with kandha_page(kandha) as page:
        for t in (1, 2):
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/kandha/intents")) as answer:
                page.evaluate("(t) => window.Kandha.intents.emit({ kind: 'silence', t, voice: null })", t)
            bodies.extend(json.loads(answer.value.request.post_data)["intents"])
        assert len(bodies) == 2, bodies
        for body in bodies:
            assert 0 <= body["age_ms"] < 5000, body
            assert abs(body["sent"] - time.time() * 1000) < 60000, "sent is a reading of this computer's clock"
            assert "page" not in body, "the trip is measured per batch on the shared clock; no page history"


def test_a_chip_picked_in_one_session_is_not_picked_in_the_next(kandha):
    with kandha_page(kandha) as page:
        page.evaluate("() => { const K = window.Kandha; K.onSpeaker(1, 1, true); K.onSpeaker(2, 2, true); K.assignSeat(1, 'F', 'demo'); K.assignSeat(2, 'L', 'demo'); }")
        wait_seats(page, {"1": "F", "2": "L"})
        page.evaluate("() => window.Kandha.showScreen('seats')")
        page.wait_for_timeout(150)
        page.click("#roomBig [data-voice='2']")
        page.wait_for_function("() => !!document.querySelector('#roomBig .is-selected')")
        page.evaluate("() => window.Kandha.playDemo('seminar')")
        page.wait_for_timeout(400)
        assert page.evaluate("() => document.querySelectorAll('#roomBig .is-selected').length") == 0


def test_g7_the_on_screen_stole_pads_send_the_stole_s_gestures(kandha):
    with kandha_page(kandha, clock=True) as page:
        sent = []
        page.on("request", lambda r: sent.append(json.loads(r.post_data)) if r.method == "POST" and r.url.endswith("/api/kandha/pad") else None)
        pad = page.locator("#stoleLive [data-pad='B']")
        pad.scroll_into_view_if_needed()
        box = pad.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

        def touch(held_ms):
            page.mouse.down()
            page.clock.run_for(held_ms)
            page.mouse.up()
        touch(100)                      # a tap, sent 300 ms after it ends
        page.clock.run_for(150)
        assert sent == []
        page.clock.run_for(400)
        touch(100)                      # a second touch 100 ms after a tap's end: a double
        page.clock.run_for(100)
        touch(100)
        page.clock.run_for(600)
        touch(500)                      # 400-699 ms: nothing
        page.clock.run_for(600)
        touch(900)                      # a long press, once
        page.clock.run_for(600)
        page.wait_for_timeout(300)
        assert [(p["pad"], p["gesture"]) for p in sent] == [("B", "tap"), ("B", "double"), ("B", "long")], sent


def test_the_microphone_is_remembered_by_its_name_when_its_id_changes(kandha):
    remember = "(s) => { localStorage.setItem('kandha.settings.v1', JSON.stringify(s)); }"
    selected = "() => { const o = document.querySelector('#setMic').selectedOptions[0]; return o ? o.textContent : null; }"
    with kandha_page(kandha, scripts=(FAKE_SR, RECORD_MICROPHONE)) as page:
        names = page.evaluate("async () => (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput').map(d => d.label)")
        chosen = next((n for n in names if n and n != names[0]), None)
        assert chosen, names
        # an id from an earlier launch (the Kandha window's profile, or another port, gives new ids)
        page.evaluate(remember, {"micId": "id-from-an-earlier-launch", "micLabel": chosen, "screen": "settings"})
        page.reload()
        page.wait_for_function(READY, timeout=20000)
        page.wait_for_function(f"() => ({selected})() === {json.dumps(chosen)}", timeout=5000)
        saved = page.evaluate(SAVED)
        assert saved["micId"] == page.evaluate("() => document.querySelector('#setMic').value") and saved["micId"] != "id-from-an-earlier-launch"
        page.locator("#startBtn").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        assert page.evaluate("() => window.__gum.at(-1).label") == chosen, "Start opens the saved microphone"
        page.locator("#startBtn").click()
        # a saved microphone that is not plugged in: changing another setting keeps the choice
        page.evaluate(remember, {"micId": "gone", "micLabel": "A microphone not plugged in", "screen": "settings"})
        page.reload()
        page.wait_for_function(READY, timeout=20000)
        page.wait_for_function(f"() => ({selected})() === 'Default microphone'", timeout=5000)
        page.locator("#setName").fill("Vikram")
        page.locator("#setName").dispatch_event("change")
        assert [page.evaluate(SAVED)[k] for k in ("name", "micId", "micLabel")] == ["Vikram", "gone", "A microphone not plugged in"]
        # choosing in the list saves the id and the name
        page.select_option("#setMic", label=names[-1])
        saved = page.evaluate(SAVED)
        assert saved["micLabel"] == names[-1] and saved["micId"] == page.evaluate("() => document.querySelector('#setMic').value") != ""
    # a browser tab before permission: no names until a microphone is open, so Start finds it by name then
    with kandha_page(kandha, grant=False, scripts=(FAKE_SR, RECORD_MICROPHONE)) as page:
        page.evaluate(remember, {"micId": "id-from-another-port", "micLabel": chosen})
        page.reload()
        page.wait_for_function(READY, timeout=20000)
        page.locator("#welcomeStart").click()
        page.wait_for_function("() => window.Kandha.S.running === true", timeout=10000)
        assert page.evaluate("() => window.__gum.at(-1).label") == chosen
        assert page.evaluate(SAVED)["micId"] not in ("", "id-from-another-port")
        page.locator("#startBtn").click()
