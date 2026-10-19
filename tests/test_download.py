import hashlib
from io import BytesIO
from types import SimpleNamespace
import threading
import pytest

from app.models.download import Asset, Downloader, DownloadCancelled


class Response(BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


def asset(data=b"verified model bytes"):
    return Asset("https://models.example/model.bin", "model.bin", hashlib.sha256(data).hexdigest(), size=len(data))


def test_download_verifies_and_reuses_valid_assets_without_a_second_request(tmp_path):
    calls = []
    def open_(request, timeout):
        calls.append(request)
        return Response(b"verified model bytes")
    downloader = Downloader(tmp_path, opener=open_)
    first = downloader.fetch(asset())
    assert first.read_bytes() == b"verified model bytes"
    assert downloader.fetch(asset()) == first
    assert len(calls) == 1


def test_partial_file_is_resumed_with_a_validated_content_range(tmp_path):
    data = b"verified model bytes"
    (tmp_path / "model.bin.part").write_bytes(data[:8])
    def open_(request, timeout):
        assert request.get_header("Range") == "bytes=8-"
        return Response(data[8:], 206, {"Content-Range": f"bytes 8-{len(data)-1}/{len(data)}"})
    assert Downloader(tmp_path, opener=open_).fetch(asset()).read_bytes() == data


def test_ignored_range_restarts_instead_of_duplicating_bytes(tmp_path):
    (tmp_path / "model.bin.part").write_bytes(b"verified")
    downloader = Downloader(tmp_path, opener=lambda *a, **k: Response(b"verified model bytes"))
    assert downloader.fetch(asset()).read_bytes() == b"verified model bytes"


def test_corrupt_complete_file_is_rejected_and_partial_network_data_is_retained(tmp_path):
    downloader = Downloader(tmp_path, opener=lambda *a, **k: Response(b"wrong model bytes!!!"))
    with pytest.raises(OSError, match="integrity"):
        downloader.fetch(asset())
    assert not (tmp_path / "model.bin").exists()
    assert not (tmp_path / "model.bin.part").exists()
    downloader.opener = lambda *a, **k: Response(b"verified")
    with pytest.raises(OSError, match="integrity"):
        downloader.fetch(asset())
    assert (tmp_path / "model.bin.part").read_bytes() == b"verified"


def test_cancel_and_insufficient_space_never_publish_an_install(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        Downloader(tmp_path, cancel=cancel).fetch(asset())
    downloader = Downloader(tmp_path, disk_usage=lambda _: SimpleNamespace(free=10))
    with pytest.raises(OSError, match="free disk space"):
        downloader.fetch(asset())
    assert not (tmp_path / "model.bin").exists()


def test_unexpected_range_and_path_traversal_are_rejected(tmp_path):
    (tmp_path / "model.bin.part").write_bytes(b"verified")
    downloader = Downloader(tmp_path, opener=lambda *a, **k: Response(b"model",206,{"Content-Range":"bytes 0-4/19"}))
    with pytest.raises(OSError, match="different download range"):
        downloader.fetch(asset())
    with pytest.raises(ValueError, match="escapes"):
        downloader.fetch(Asset("https://models.example/x", "../outside", "a" * 64))


def test_gated_token_is_sent_only_to_hub_and_is_not_forwarded_on_redirect(tmp_path):
    requests = []
    def open_(request, timeout):
        requests.append(request)
        return Response(b"verified model bytes")
    original = asset()
    gated = Asset("https://huggingface.co/repo/resolve/pinned/model.bin", "hub.bin", original.digest, size=original.size)
    downloader = Downloader(tmp_path, opener=open_, token="hf_fixture_only")
    downloader.fetch(gated)
    downloader.fetch(original)
    assert requests[0].unredirected_hdrs["Authorization"] == "Bearer hf_fixture_only"
    assert "Authorization" not in requests[0].headers
    assert "Authorization" not in requests[1].unredirected_hdrs


def test_secure_hub_redirect_keeps_auth_only_on_the_https_hub():
    from urllib.request import Request
    from app.models.download import HubRedirect
    request = Request("https://huggingface.co/repo/resolve/revision/config.yaml")
    request.add_unredirected_header("Authorization", "Bearer hf_fixture_only")
    redirect = HubRedirect()
    for destination, expected in [("https://huggingface.co/api/resolve-cache/x", True),
                                  ("https://cdn.example/model", False),
                                  ("http://huggingface.co/plaintext", False)]:
        forwarded = redirect.redirect_request(request, None, 302, "Found", {}, destination)
        assert (forwarded.get_header("Authorization") is not None) is expected
