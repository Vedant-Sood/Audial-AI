"""Sanket voice view in the browser companion: static app, model integrity, events and exports."""
import hashlib
import json
import re
import urllib.error
import urllib.request

import pytest

from app.audio.capture import ExternalAudio
from app.services import browser as browser_module
from app.services.browser import KANDHA_FILES, SANKET_FILES, BrowserService
from app.services.voice_view import VoiceTrack, clean_events
from app.storage.transcript import Caption, Session
from app.utils.config import Settings
from app.utils.paths import project_root


@pytest.fixture
def companion():
    service = BrowserService(settings=Settings(device="cpu"))
    service.start()
    try:
        yield service
    finally:
        service.stop()
        for thread in tuple(service.engine.threads):
            thread.join(timeout=5)


def request(service, path, data=None, headers=None):
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    query = urllib.request.Request(service.url + path, data=data, headers=headers or {})
    try:
        response = urllib.request.urlopen(query, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        kind = response.headers.get("Content-Type", "")
        return response.status, (json.loads(raw) if "application/json" in kind and raw[:1] in b"{[" else raw), response.headers


def test_kandha_page_is_csp_safe_and_every_script_it_loads_is_served(companion):
    status, page, headers = request(companion, "/kandha/")
    assert status == 200
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in headers["Content-Security-Policy"].split("style-src")[0]
    assert not re.search(rb"<script(?![^>]*\bsrc=)", page), "no inline scripts"
    assert not re.search(rb" on[a-z]+=", page), "no inline event handlers"
    for src in re.findall(rb'<script src="([^"]+)"', page):
        src = src.decode()
        if src.startswith("../sanket/"):
            assert src.removeprefix("../sanket/") in SANKET_FILES
            assert request(companion, "/sanket/" + src.removeprefix("../sanket/"))[0] == 200
        else:
            assert src in KANDHA_FILES
            assert request(companion, "/kandha/" + src)[0] == 200
    assert request(companion, "/kandha/fonts/AtkinsonHyperlegible-Regular.ttf")[2]["Content-Type"] == "font/ttf"
    assert request(companion, "/kandha/fonts/OFL.txt")[0] == 200
    assert request(companion, "/kandha/patterns.json")[1]["protocol"]["name_prefix"] == "KandhaStole-"
    assert request(companion, "/kandha/package.json")[0] == 404
    assert request(companion, "/kandha/../app/main.py")[0] == 404
    assert request(companion, "/sanket/band.js")[0] == 404, "the band is retired"
    assert request(companion, "/sanket/app.js")[0] == 404, "the old Sanket app moved to /kandha/"
    # the companion page keeps its strict policy and still loads the shared engine
    assert "'unsafe-inline'" not in request(companion, "/")[2]["Content-Security-Policy"]
    for name in ("voice-session.js", "voice-view.js", "sanket/engine.js", "sanket/tone.js"):
        assert request(companion, "/" + name)[0] == 200
    assert b"band" not in request(companion, "/")[1].lower()


def test_old_sanket_addresses_redirect_to_kandha(companion):
    import urllib.request
    for path in ("/sanket", "/sanket/", "/sanket/index.html", "/kandha"):
        query = urllib.request.Request(companion.url + path)
        opener = urllib.request.build_opener(NoRedirect())
        try:
            response = opener.open(query, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            assert response.status == 308 and response.headers["Location"] == "/kandha/"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_tone_model_is_served_only_when_it_matches_its_recorded_hash(companion, tmp_path, monkeypatch):
    status, model, _ = request(companion, "/kandha/tone-model.json")
    assert status == 200 and model["labels"] == ["angry", "disgust", "fear", "happy", "neutral", "sad"]
    provenance = json.loads((project_root() / "models/sanket/provenance.json").read_text())
    assert provenance["sha256"] == hashlib.sha256((project_root() / "models/sanket/tone_model.json").read_bytes()).hexdigest()
    # Windows checkouts may convert this shared text file to CRLF; the recorded hash is of the LF file.
    splits = (project_root() / "models/emotion/splits.json").read_bytes().replace(b"\r\n", b"\n")
    assert provenance["splits"]["sha256"] == hashlib.sha256(splits).hexdigest()
    fake = tmp_path / "root"
    (fake / "models/sanket").mkdir(parents=True)
    (fake / "models/sanket/tone_model.json").write_text("{}")
    (fake / "models/sanket/provenance.json").write_text(json.dumps({"sha256": "0" * 64}))
    monkeypatch.setattr(browser_module, "project_root", lambda: fake)
    assert request(companion, "/kandha/tone-model.json")[0] == 400 and request(companion, "/sanket/tone-model.json")[0] == 400


def test_voice_events_need_the_owning_session_and_are_republished(companion):
    status, started, _ = request(companion, "/api/start", {"mode": "tone"})
    assert status == 200
    events = [{"kind": "voice", "t": 0.4, "id": 1, "new": True},
              {"kind": "cue", "t": 3.1, "cue": "rise", "voice": 1},
              {"kind": "tone", "t0": 1.0, "t1": 2.9, "voice": 1, "relative": "intense", "label": "angry", "confidence": 0.86}]
    assert request(companion, "/api/voice-events", {"session_id": "another-tab", "events": events})[0] == 409
    status, result, _ = request(companion, "/api/voice-events", {"session_id": started["session_id"], "events": events})
    assert status == 200 and result["stored"] == 3
    status, stream, _ = request(companion, "/api/events?after=0")
    voice = [e for e in stream["events"] if e["kind"] == "voice"]
    assert voice and voice[-1]["data"]["events"][1]["cue"] == "rise"
    request(companion, "/api/stop", {"session_id": started["session_id"]})


@pytest.mark.parametrize("bad", [
    [{"kind": "voice", "t": float("nan"), "id": 1}],
    [{"kind": "cue", "t": 1, "cue": "sarcasm", "voice": 1}],
    [{"kind": "tone", "t0": 2, "t1": 1, "voice": 1, "relative": "usual", "label": "uncertain"}],
    [{"kind": "tone", "t0": 1, "t1": 2, "voice": 1, "relative": "usual", "label": "happy", "confidence": 0.5}],
    [{"kind": "voice", "t": 1, "id": "1; drop"}],
    [{"kind": "html", "t": 1}],
    [{"kind": "voice", "t": 1, "id": 1}] * 201,
])
def test_malformed_or_low_confidence_voice_events_are_rejected(bad):
    with pytest.raises(ValueError):
        clean_events(json.loads(json.dumps(bad, allow_nan=True)))


def test_exports_name_unattributed_captions_by_voice_and_keep_tone_notes(tmp_path):
    session = Session(title="Seminar")
    session.add(Caption(0.5, 2.0, "Let us look at the case.", "Unattributed"))
    session.add(Caption(4.4, 6.0, "But she still goes to college.", "Unattributed"))
    session.add(Caption(6.5, 7.0, "Named by diarization.", "Speaker 1"))
    session.add_voice_events(clean_events([
        {"kind": "voice", "t": 0.2, "id": 1}, {"kind": "voice", "t": 4.2, "id": 2},
        {"kind": "tone", "t0": 4.3, "t1": 6.1, "voice": 2, "relative": "softer", "label": "sad", "confidence": 0.84},
        {"kind": "cue", "t": 5.0, "cue": "drop", "voice": 2}]))
    session.export(tmp_path / "t.vtt", "vtt")
    vtt = (tmp_path / "t.vtt").read_text()
    assert "Voice 1: Let us look at the case." in vtt and "Voice 2: But she still" in vtt
    assert "Speaker 1: Named by diarization." in vtt
    session.export(tmp_path / "t.txt", "txt")
    txt = (tmp_path / "t.txt").read_text()
    assert "[tone: softer, sad-sounding; estimate sad 84%]" in txt and "Voice softened (Voice 2)" in txt
    session.export(tmp_path / "t.json", "json")
    data = json.loads((tmp_path / "t.json").read_text())
    assert data["captions"][1]["voice_view"] == {"voice": "Voice 2", "tone": {"relative": "softer", "label": "sad", "confidence": 0.84}}
    reloaded = Session.load(tmp_path / "t.json")
    assert len(reloaded.voice_events) == 4 and reloaded.captions[1].text.startswith("But")
    assert not VoiceTrack([])


def test_voice_preferences_persist_and_reach_status(companion):
    status, _, _ = request(companion, "/api/status")
    assert status == 200
    assert request(companion, "/api/voice-view/settings", {"colors": True, "cues": "yes", "tone": False})[0] == 400
    status, saved, _ = request(companion, "/api/voice-view/settings", {"colors": True, "cues": True, "tone": True})
    assert status == 200 and saved["cues"] and saved["model"]
    assert Settings.load().voice_cues is True
    assert request(companion, "/api/status")[1]["voice_view"]["tone"] is True


def test_a_page_may_choose_hindi_without_changing_the_desktop_preference(companion):
    assert request(companion, "/api/start", {"mode": "tone", "language": "fr"})[0] == 400
    before = companion.settings.language
    status, started, _ = request(companion, "/api/start", {"mode": "tone", "language": "hi"})
    assert status == 200 and companion.engine.language == "hi"
    assert companion.settings.language == before
    assert request(companion, "/api/status")[1]["language"] == "hi"
    # Saving an unrelated setting during capture must not persist the override.
    request(companion, "/api/voice-view/settings", {"colors": True, "cues": False, "tone": False})
    assert Settings.load().language == before
    request(companion, "/api/stop", {"session_id": started["session_id"]})
    assert companion.settings.language == before


def test_failed_session_start_does_not_change_language_preferences(companion):
    before = companion.settings.language
    assert request(companion, "/api/start", {"mode": "invalid", "language": "hi"})[0] == 400
    assert companion.settings.language == before


def test_extension_tab_capture_carries_voice_preferences_and_stores_its_voice_events(monkeypatch):
    service = BrowserService(settings=Settings(device="cpu", voice_cues=True))
    monkeypatch.setattr(service.engine.manager, "installed", lambda _: True)
    def start(mode, source):
        service.engine.source, service.engine.capture, service.engine.running = source, ExternalAudio(), True
        service.engine.stop_requested.clear()
    monkeypatch.setattr(service.engine, "start", start)
    service.start()
    try:
        bridge = service.bridge
        bridge.handle({"profile": "chrome", "type": "tabs", "tabs": [{"id": 3, "title": "Lecture", "supported": True}]})
        owned = bridge.handle({"profile": "chrome", "type": "start", "tab_id": 3})
        assert owned["voice_view"]["cues"] is True and owned["voice_view"]["model"]
        assert "voice_view" not in bridge.owner
        events = [{"kind": "voice", "t": 0.3, "id": 1, "new": True}, {"kind": "cue", "t": 2.0, "cue": "silence", "voice": None}]
        with pytest.raises(ValueError, match="different capture"):
            bridge.handle({"profile": "other", "type": "voice", "session_id": owned["session_id"], "events": events})
        assert bridge.handle({"profile": "chrome", "type": "voice", "session_id": owned["session_id"], "events": events})["stored"] == 2
        assert len(service.session.voice_events) == 2
    finally:
        service.stop()
