from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from app.utils.paths import atomic_json


def test_concurrent_json_saves_publish_complete_documents(tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    barrier = threading.Barrier(2)
    replace = Path.replace

    def publish_together(source, destination):
        if destination == target:
            barrier.wait(timeout=5)
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", publish_together)
    values = [{"language": "हिन्दी", "writer": i, "text": "caption" * 1000} for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda value: atomic_json(target, value), values))

    assert json.loads(target.read_text(encoding="utf-8")) in values
    assert list(tmp_path.iterdir()) == [target]


def test_failed_json_save_preserves_previous_document_and_cleans_staging(tmp_path):
    target = tmp_path / "state.json"
    atomic_json(target, {"complete": True})
    with pytest.raises(TypeError):
        atomic_json(target, {"not_serializable": object()})
    assert json.loads(target.read_text()) == {"complete": True}
    assert list(tmp_path.iterdir()) == [target]


def test_failed_publication_preserves_previous_document_and_cleans_staging(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    atomic_json(target, {"complete": True})

    def denied(*args):
        raise PermissionError("Document is temporarily locked")

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        atomic_json(target, {"complete": False})
    assert json.loads(target.read_text()) == {"complete": True}
    assert list(tmp_path.iterdir()) == [target]
