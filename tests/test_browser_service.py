from io import BytesIO
import json
import time
import urllib.error
import urllib.request

import numpy as np
import pytest
import soundfile as sf

from app.services.browser import BrowserService
from app.storage.transcript import Caption
from app.utils.config import Settings


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
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    query = urllib.request.Request(service.url + path, data=data, headers=headers or {})
    try:
        response = urllib.request.urlopen(query, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw


def test_browser_controls_require_origin_and_own_session(companion):
    assert request(companion, "/api/start", b"[]", {"Content-Type":"application/json"})[0] == 400
    status, _ = request(companion, "/api/start", {"mode": "tone"}, {"Origin": "https://unrelated.example"})
    assert status == 403 and not companion.engine.running
    status, result = request(companion, "/api/start", {"mode": "tone"})
    assert status == 200 and result["session_id"]
    assert request(companion, "/api/start", {"mode": "tone"})[0] == 409
    assert request(companion, "/api/stop", {"session_id": "another-tab"})[0] == 409
    assert request(companion, "/api/stop", {"session_id": result["session_id"]})[0] == 200


def test_browser_audio_timestamps_and_stopped_session(companion):
    status, result = request(companion, "/api/start", {"mode": "tone"})
    assert status == 200
    body = BytesIO()
    sf.write(body, np.zeros(1600, np.float32), 16000, format="WAV", subtype="PCM_16")
    headers = {"Content-Type": "audio/wav", "X-Audio-Start-Seconds": "1", "X-Session-ID": result["session_id"]}
    assert request(companion, "/api/audio", body.getvalue(), headers)[0] == 200
    headers["X-Audio-Start-Seconds"] = "0"
    assert request(companion, "/api/audio", body.getvalue(), headers)[0] == 400
    request(companion, "/api/stop", {"session_id": result["session_id"]})
    headers["X-Audio-Start-Seconds"] = "2"
    assert request(companion, "/api/audio", body.getvalue(), headers)[0] == 409


def test_browser_exports_complete_captions_and_real_signs(companion):
    companion.engine.emit("caption", Caption(1, 2, "Thank you.", "Speaker 1", voice={"f0_hz": 120.}))
    status, events = request(companion, "/api/events?after=0")
    assert status == 200 and events["events"][-1]["data"]["text"] == "Thank you."
    status, subtitle = request(companion, "/api/export?format=vtt")
    assert status == 200 and b"00:00:01.000 --> 00:00:02.000" in subtitle
    assert b"Speaker 1: Thank you." in subtitle
    status, signs = request(companion, "/api/signs?text=Thank%20you%20team")
    assert status == 200 and signs["language"] == "ISL" and signs["missing"] == ["team"]
    assert signs["sequences"][0]["gloss"] == "thank you"
    assert len(signs["sequences"][0]["frames"][0]["leftHand"]) == 21
    assert request(companion, "/../app/main.py")[0] == 404


def test_browser_palette_persists_and_rejects_unsafe_color_values(companion):
    status, palette = request(companion, "/api/palette")
    assert status == 200
    colors = palette["colors"]
    colors["happy"] = "#010203"
    assert request(companion, "/api/palette", {"colors": colors})[0] == 200
    assert Settings.load().emotion_colors["happy"] == "#010203"
    colors["sad"] = "url(https://example.invalid)"
    assert request(companion, "/api/palette", {"colors": colors})[0] == 400
