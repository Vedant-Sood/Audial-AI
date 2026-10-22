"""Length-framed Chrome/Edge native messaging; stdout contains protocol only."""

import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

from app.utils.paths import data_root

HOST_NAME = "org.audialai.bridge"
MAX_MESSAGE = 4 * 1024 * 1024


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Incomplete native message header")
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Native message exceeds the size limit")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Incomplete native message")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("Native message must be an object")
    return data


def write_message(stream, message):
    body = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > MAX_MESSAGE:
        raise ValueError("Native response exceeds the size limit")
    stream.write(struct.pack("<I", len(body)))
    stream.write(body)
    stream.flush()


def forward(message):
    info = json.loads((data_root() / "browser-bridge.json").read_text(encoding="utf-8"))
    url = urllib.parse.urlsplit(info["url"])
    if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.path:
        raise ValueError("Invalid loopback companion address")
    request = urllib.request.Request(
        info["url"] + "/api/bridge",
        data=json.dumps(message).encode(),
        headers={"Content-Type": "application/json", "X-Audial-Bridge": info["token"]},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            result = json.load(response)
            result["companion_url"] = info["url"]
            return result
    except urllib.error.HTTPError as error:
        try:
            result = json.load(error)
        except (ValueError, OSError):
            raise ValueError("Local companion rejected the request") from None
        raise ValueError(
            result.get("error", "Local companion rejected the request")
        ) from None


def main(input_stream=None, output_stream=None):
    if sys.platform == "win32" and input_stream is None and output_stream is None:
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    input_stream = sys.stdin.buffer if input_stream is None else input_stream
    output_stream = sys.stdout.buffer if output_stream is None else output_stream
    owner = None
    try:
        while True:
            message = read_message(input_stream)
            if message is None:
                break
            disconnected = False
            try:
                result = forward(message)
                if message.get("type") == "start":
                    owner = {
                        "type": "stop",
                        "profile": message["profile"],
                        "session_id": result["session_id"],
                    }
                elif message.get("type") == "stop":
                    owner = None
                response = {"id": message.get("id"), "ok": True, "result": result}
            except (OSError, ValueError, KeyError) as error:
                disconnected = isinstance(error, OSError)
                response = {
                    "id": message.get("id"),
                    "ok": False,
                    "error": "Start or reconnect the Audial-AI desktop companion. "
                    + str(error)[:400],
                }
            write_message(output_stream, response)
            if disconnected:
                break
    except (OSError, ValueError):
        pass
    finally:
        if owner:
            try:
                forward(owner)
            except (OSError, ValueError, KeyError):
                pass


if __name__ == "__main__":
    main()
