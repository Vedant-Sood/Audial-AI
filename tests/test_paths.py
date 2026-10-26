from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

import app.utils.paths as paths
from app.utils.paths import atomic_json


def windows_denial():
    """The PermissionError Windows raises when a file is being replaced by someone else (WinError 5)."""
    error = PermissionError(13, "Access is denied")
    error.winerror = 5
    return error


def test_concurrent_json_saves_publish_complete_documents(tmp_path, monkeypatch):
    # Both writers reach the real os.replace at the same moment. On Windows one of them is refused
    # with WinError 5 now and then (CI run 39821899721); it must retry, not fail the save.
    target = tmp_path / "settings.json"
    barrier = threading.Barrier(2)
    replace = Path.replace

    def publish_together(source, destination):
        if destination == target and not getattr(local, "waited", False):
            local.waited = True
            barrier.wait(timeout=5)
        return replace(source, destination)

    local = threading.local()
    monkeypatch.setattr(Path, "replace", publish_together)
    values = [{"language": "हिन्दी", "writer": i, "text": "caption" * 1000} for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda value: atomic_json(target, value), values))

    assert json.loads(target.read_text(encoding="utf-8")) in values
    assert list(tmp_path.iterdir()) == [target]


def test_concurrent_saves_ride_out_windows_refusing_a_busy_replace(tmp_path, monkeypatch):
    # Windows semantics on any OS: while one replace onto the file is in progress, a second one is
    # refused with "Access is denied" instead of waiting. Both saves must still succeed.
    target = tmp_path / "settings.json"
    barrier = threading.Barrier(2)
    busy = threading.Lock()
    turned_away = threading.Event()
    local = threading.local()
    refused = []
    replace = Path.replace

    def publish_like_windows(source, destination):
        if destination != target:
            return replace(source, destination)
        if not getattr(local, "waited", False):
            local.waited = True
            barrier.wait(timeout=5)
        if not busy.acquire(blocking=False):
            refused.append(threading.get_ident())
            turned_away.set()
            raise windows_denial()
        try:
            turned_away.wait(timeout=2)            # hold the file until the other writer has been refused
            return replace(source, destination)
        finally:
            busy.release()

    monkeypatch.setattr(Path, "replace", publish_like_windows)
    values = [{"language": "हिन्दी", "writer": i, "text": "caption" * 1000} for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda value: atomic_json(target, value), values))

    assert refused                                 # the race really happened
    assert json.loads(target.read_text(encoding="utf-8")) in values
    assert list(tmp_path.iterdir()) == [target]


def test_windows_replace_refusals_are_retried_a_bounded_number_of_times(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    atomic_json(target, {"complete": True})
    attempts, naps = [], []

    def always_refused(*args):
        attempts.append(args)
        raise windows_denial()

    monkeypatch.setattr(Path, "replace", always_refused)
    monkeypatch.setattr(paths.time, "sleep", naps.append)
    with pytest.raises(PermissionError):
        atomic_json(target, {"complete": False})
    assert len(attempts) == len(paths.REPLACE_RETRY_DELAYS_S) + 1
    assert naps == list(paths.REPLACE_RETRY_DELAYS_S) and sum(naps) < 1
    assert json.loads(target.read_text()) == {"complete": True}
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

    attempts = []

    def denied(*args):
        attempts.append(args)
        raise PermissionError("Document is temporarily locked")

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        atomic_json(target, {"complete": False})
    assert len(attempts) == 1                      # not a Windows replace refusal: no retry
    assert json.loads(target.read_text()) == {"complete": True}
    assert list(tmp_path.iterdir()) == [target]
