"""Resumable, bounded-memory model downloads with authoritative checksums."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request
from urllib.parse import urlparse


class DownloadCancelled(Exception):
    pass


class HubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        result = super().redirect_request(
            request, response, code, message, headers, new_url
        )
        origin = urlparse(request.full_url)
        target = urlparse(new_url)
        if (
            result is not None
            and origin.scheme == "https"
            and origin.hostname == "huggingface.co"
            and target.scheme == "https"
            and target.hostname == "huggingface.co"
        ):
            token = request.get_header("Authorization")
            if token:
                result.add_unredirected_header("Authorization", token)
        return result


@dataclass(frozen=True)
class Asset:
    url: str
    filename: str
    digest: str
    algorithm: str = "sha256"
    size: int | None = None
    revision: str | None = None


def digest_file(path, algorithm="sha256"):
    path = Path(path)
    digest = hashlib.new("sha1" if algorithm == "git-sha1" else algorithm)
    if algorithm == "git-sha1":
        digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Downloader:
    def __init__(
        self,
        root,
        cancel=None,
        progress=None,
        opener=None,
        disk_usage=shutil.disk_usage,
        token=None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cancel = cancel
        self.progress = progress or (lambda event: None)
        self.opener = opener
        self.disk_usage = disk_usage
        self.token = token

    def check_cancelled(self):
        if self.cancel is not None and self.cancel.is_set():
            raise DownloadCancelled(
                "Setup paused. Downloaded parts are retained; Resume continues them."
            )

    def valid(self, path, asset):
        return (
            path.is_file()
            and (asset.size is None or path.stat().st_size == asset.size)
            and digest_file(path, asset.algorithm) == asset.digest
        )

    def fetch(self, asset):
        if asset.algorithm not in {"sha256", "git-sha1", "md5"} or not asset.digest:
            raise ValueError(
                "An upstream checksum is required before downloading a model asset."
            )
        path = (self.root / asset.filename).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Model asset path escapes its staging directory.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.check_cancelled()
        if self.valid(path, asset):
            self.progress(
                {
                    "file": asset.filename,
                    "downloaded": path.stat().st_size,
                    "total": asset.size,
                    "state": "verified",
                }
            )
            return path
        part = path.with_name(path.name + ".part")
        if part.is_symlink():
            raise ValueError("A model download part cannot be a symbolic link.")
        start = part.stat().st_size if part.is_file() else 0
        if asset.size is not None and start > asset.size:
            part.unlink()
            start = 0
        if asset.size is not None and start == asset.size:
            if self.valid(part, asset):
                os.replace(part, path)
                return path
            # A crash can leave a full-length, corrupt part before verification.
            # Asking for bytes after EOF would otherwise repeat HTTP 416 forever.
            part.unlink()
            start = 0
        remaining = max(0, (asset.size or 0) - start)
        if self.disk_usage(self.root).free < remaining + 64 * 1024 * 1024:
            raise OSError(
                "Not enough free disk space for this model. Free storage and choose Retry."
            )
        headers = {"Accept-Encoding": "identity"}
        if start:
            headers["Range"] = f"bytes={start}-"
        request = urllib.request.Request(asset.url, headers=headers)
        target = urlparse(asset.url)
        if self.token and target.scheme == "https" and target.hostname == "huggingface.co":
            # Send credentials only to the Hub, never to a redirected CDN or
            # another model host. Hub redirects carry their own signed access.
            request.add_unredirected_header("Authorization", "Bearer " + self.token)
        opener = self.opener or (
            urllib.request.build_opener(HubRedirect()).open
            if self.token
            else urllib.request.urlopen
        )
        try:
            response = opener(request, timeout=30)
        except urllib.error.HTTPError as error:
            if error.code == 416 and self.valid(part, asset):
                os.replace(part, path)
                return path
            raise
        with response:
            status = getattr(response, "status", 200)
            response_headers = getattr(response, "headers", {})
            if start and status == 206:
                content_range = response_headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {start}-"):
                    raise OSError(
                        "The server returned a different download range. Retry after reconnecting."
                    )
            else:
                # A server can ignore Range; restart rather than append duplicate bytes.
                start = 0
            mode = "ab" if start else "wb"
            received = start
            with part.open(mode) as output:
                while True:
                    self.check_cancelled()
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    received += len(block)
                    if asset.size is not None and received > asset.size:
                        raise OSError("The downloaded model exceeds its recorded size.")
                    self.progress(
                        {
                            "file": asset.filename,
                            "downloaded": received,
                            "total": asset.size,
                            "state": "downloading",
                        }
                    )
                output.flush()
                os.fsync(output.fileno())
        self.check_cancelled()
        if not self.valid(part, asset):
            # Incomplete networks retain their part; full corrupt files cannot be reused.
            if asset.size is None or part.stat().st_size >= asset.size:
                part.unlink(missing_ok=True)
            raise OSError(
                "Model integrity check failed. A partial download is retained when safe; choose Retry."
            )
        os.replace(part, path)
        self.progress(
            {
                "file": asset.filename,
                "downloaded": path.stat().st_size,
                "total": asset.size,
                "state": "verified",
            }
        )
        return path
