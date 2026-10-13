"""ISL defaults, shared vocabulary, and complete cross-input playback contracts."""
from io import BytesIO
import json
from pathlib import Path
import shutil
import urllib.error
import urllib.request
import zipfile

import pytest

from app.services.browser import BrowserService
from app.services.isl import ISLVocabulary
from app.services.text_input import MAX_BYTES, read_text_bytes
from app.storage.transcript import Caption
from app.utils.config import Settings
from app.utils.paths import project_root


def vocabulary_pack(directory, video=False):
    """Reuse the real thank-you asset; only its text aliases are extended."""
    directory.mkdir()
    suffix = ".mp4" if video else ".npy"
    shutil.copy2(project_root() / ("assets/isl_lexicon/thank_you" + suffix), directory / ("thanks" + suffix))
    path = directory / "lexicon.json"
    path.write_text(json.dumps({"language": "ISL", "entries": [{
        "gloss": "thank you", "aliases": ["many thanks", "आभार"], "path": "thanks" + suffix,
        "fps": 15, "source_url": "https://zenodo.org/records/4010759", "license": "CC-BY-4.0",
    }]}), encoding="utf-8")
    return path


def call(service, route, data=None, headers=None):
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(service.url + route, data=data, headers=headers or {})
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw


def test_isl_is_fixed_for_every_speech_language_and_old_settings(tmp_path):
    path = tmp_path / "old-settings.json"
    path.write_text('{"language":"hi"}')
    assert Settings.load(path).sign_language == "ISL"
    assert Settings.load(path).auto_sign is True
    for speech_language in ["en", "hi", "ta", "auto"]:
        assert Settings(language=speech_language).validate().sign_language == "ISL"
    with pytest.raises(ValueError, match="Indian Sign Language"):
        Settings(sign_language="ASL").validate()


def test_added_pack_extends_bundled_signs_and_changes_are_shared(tmp_path):
    first, second = ISLVocabulary(), ISLVocabulary()
    path = vocabulary_pack(tmp_path / "pack")
    first.select(path)
    assert second.summary()["entries"] == 4
    steps = second.plan("आभार धन्यवाद good night")
    assert [step["entry"]["gloss"] for step in steps] == ["thank you", "thank you", "good night"]
    assert steps[0]["entry"]["path"] == path.parent / "thanks.npy"
    second.use_bundled()
    assert first.plan("many thanks")[0]["kind"] == "text"
    assert first.plan("thank you")[0]["kind"] == "sign"


def test_bad_pack_preserves_selection_and_missing_pack_falls_back(tmp_path):
    store = ISLVocabulary()
    good = vocabulary_pack(tmp_path / "pack")
    store.select(good)
    before = store.selection.read_bytes()
    bad = tmp_path / "other.json"
    bad.write_text('{"language":"ASL","entries":[]}')
    with pytest.raises(ValueError, match="Indian Sign Language"):
        store.select(bad)
    assert store.selection.read_bytes() == before
    good.unlink()
    assert store.plan("thank you")[0]["kind"] == "sign"
    assert "unavailable" in store.warning


def test_punctuation_symbols_and_unknown_scripts_preserve_input_order():
    text = "thanks,goodnight! 👋 தமிழ் टीम 👩🏽‍💻 Thank you."
    plan = ISLVocabulary().plan(text)
    assert [s["kind"] for s in plan] == ["sign", "sign", "text", "sign"]
    assert [s["text"] for s in plan] == ["thanks,", "goodnight!", "👋 தமிழ் टीम 👩🏽‍💻", "Thank you."]
    assert all(s["kind"] == "text" for s in ISLVocabulary().plan("good. night"))
    assert ISLVocabulary().plan("👋")[0]["text"] == "👋"


@pytest.mark.parametrize("filename,contents,expected", [
    ("note.txt", "धन्यवाद team", "धन्यवाद team"),
    ("note.md", "Thank you!", "Thank you!"),
    ("note.csv", "team,thanks", "team,thanks"),
    ("note.html", "<head><title>metadata</title></head><p>Thank &amp; you</p><script>not words</script>", "Thank & you"),
    ("note.srt", "1\n00:00:01,000 --> 00:00:02,000\n2026\nThank you!\n", "2026\nThank you!"),
    ("note.vtt", "WEBVTT\n\nNOTE secret metadata\nignored\n\ncue-1\n00:01.000 --> 00:02.000\n<c.green>धन्यवाद</c>\n", "धन्यवाद"),
    ("note.json", '{"captions":[{"text":"Thank you."}]}', "Thank you."),
])
def test_document_adapters_preserve_real_text(filename, contents, expected):
    text = read_text_bytes(filename, contents.encode())
    assert text == expected
    assert ISLVocabulary().plan(text)


def test_word_document_uses_paragraph_and_indic_text():
    body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>धन्यवाद</w:t></w:r></w:p><w:p><w:r><w:t>good night</w:t></w:r></w:p></w:body></w:document>'
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", body)
    text = read_text_bytes("note.docx", buf.getvalue())
    assert text == "धन्यवाद\ngood night"
    assert [s["entry"]["gloss"] for s in ISLVocabulary().plan(text)] == ["thank you", "good night"]


def test_pdf_extracts_actual_text_and_rejects_image_only_pages():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 10 Td (Thank you team.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = BytesIO(); writer.write(buf)
    text = read_text_bytes("note.pdf", buf.getvalue())
    assert text == "Thank you team."
    assert [s["kind"] for s in ISLVocabulary().plan(text)] == ["sign", "text"]
    blank = PdfWriter(); blank.add_blank_page(300, 300)
    buf = BytesIO(); blank.write(buf)
    with pytest.raises(ValueError, match="no extractable text"):
        read_text_bytes("scan.pdf", buf.getvalue())


def test_input_limits_report_failure_instead_of_truncating():
    assert read_text_bytes("note.txt", b"x" * 20000) == "x" * 20000
    with pytest.raises(ValueError, match="20,000"):
        ISLVocabulary().plan("x" * 20001)
    with pytest.raises(ValueError, match="20,000"):
        read_text_bytes("note.txt", b"x" * 20001)
    with pytest.raises(ValueError, match="2 MB"):
        read_text_bytes("note.txt", b"x" * (MAX_BYTES + 1))


def test_native_captions_documents_and_clipboard_share_complete_isl_playback(tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.auto_sign.isChecked()
        window.reduce_motion.setChecked(True)
        QApplication.clipboard().setText("team धन्यवाद")
        window.clipboard_signs()
        assert window.current_sign_step["kind"] == "text"
        assert all("team" in canvas.message for canvas in window.sign_canvases)
        window.step_sign()
        assert window.current_sign_step["entry"]["gloss"] == "thank you"
        document = tmp_path / "note.txt"; document.write_text("good night")
        window.display_sign_file(document)
        assert window.current_sign_step["entry"]["gloss"] == "good night"
        window.play_signs(" ".join(["thanks"] * 150))
        assert len(window.media_queue) == 149  # Previous versions silently capped at 100.
        window.stop_playback()
        window.engine.emit("caption", Caption(0, 1, "team धन्यवाद"))
        window.poll()
        assert window.current_sign_step["text"] == "team"
        assert window.media_queue[0]["entry"]["gloss"] == "thank you"
        window.session_dirty = False
    finally:
        window.session_dirty = False
        window.close(); app.processEvents()


def test_unreadable_pose_becomes_text_instead_of_stalling_other_signs(tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    pack = vocabulary_pack(tmp_path / "bad-media-pack")
    (pack.parent / "thanks.npy").write_bytes(b"not a numpy file")
    store = ISLVocabulary(); store.select(pack)
    service = BrowserService(settings=Settings(), vocabulary=store)
    try:
        data = service.sign_plan("thank you good night")
        assert [s["kind"] for s in data["steps"]] == ["text", "pose"]
        assert data["steps"][0]["text"] == "thank you" and data["steps"][0]["reason"]
    finally:
        service.unsubscribe()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.reduce_motion.setChecked(True)
        window.play_signs("thank you good night")
        assert window.current_sign_step["kind"] == "text" and window.current_sign_step["text"] == "thank you"
        window.step_sign()
        assert window.current_sign_step["entry"]["gloss"] == "good night"
        assert window.pose.points is not None
    finally:
        window.close(); app.processEvents()


def test_caption_preference_does_not_cancel_explicit_native_input():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.reduce_motion.setChecked(True)
        window.play_signs("typed text thanks")
        window.engine.emit("caption", Caption(0, 1, "good night"))
        window.poll()
        window.auto_sign.setChecked(False)
        assert window.current_sign_step["text"] == "typed text"
        assert [step["entry"]["gloss"] for step in window.media_queue] == ["thank you"]
        window.step_sign()
        assert window.current_sign_step["entry"]["gloss"] == "thank you"
    finally:
        window.session_dirty = False
        window.close(); app.processEvents()


def test_browser_uses_shared_pack_video_and_ordered_untruncated_steps(tmp_path):
    vocabulary = ISLVocabulary()
    vocabulary.select(vocabulary_pack(tmp_path / "video-pack", video=True))
    service = BrowserService(settings=Settings(language="hi"), vocabulary=vocabulary)
    service.start()
    try:
        status, data = call(service, "/api/status")
        assert status == 200 and data["language"] == "hi" and data["sign_language"] == "ISL" and data["auto_sign"]
        status, data = call(service, "/api/signs", {"text": "team many thanks 👋 good night"})
        assert status == 200
        assert [s["kind"] for s in data["steps"]] == ["text", "video", "text", "pose"]
        media = data["steps"][1]["url"]
        status, raw = call(service, media, headers={"Range": "bytes=0-31"})
        assert status == 206 and len(raw) == 32 and b"ftyp" in raw
        assert call(service, "/api/sign-media/../../LICENSE")[0] == 404
        vocabulary.use_bundled()
        text = " ".join(["thanks"] * 150)
        status, data = call(service, "/api/signs", {"text": text})
        assert status == 200 and len(data["steps"]) == 150 and len(data["sequences"]) == 1
        assert data["text"] == text
        assert call(service, "/api/signs", {"text": "x" * 20001})[0] == 400
        status, data = call(service, "/api/document?filename=note.srt", b"1\n00:00:01,000 --> 00:00:02,000\n2026 thanks\n")
        assert status == 200 and data["text"] == "2026 thanks"
        assert [s["kind"] for s in data["steps"]] == ["text", "pose"]
        assert call(service, "/api/isl/settings", {"auto_sign": True, "language": "ASL"})[0] == 400
        assert call(service, "/api/isl/settings", {"auto_sign": False})[0] == 200
        assert Settings.load().sign_language == "ISL" and Settings.load().auto_sign is False
    finally:
        service.stop()
